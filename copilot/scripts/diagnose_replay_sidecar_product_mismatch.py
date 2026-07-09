"""Diagnose eval-sidecar product mismatch in real conversation replay traces.

This script is read-only. It does not update replay rows, KB data, or product
identity mappings. The goal is to separate eval fixture issues from Agent
answering errors when local replay injects a single sidecar product for a mixed
real-conversation sample.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.eval_tables import EvalRun, EvalTrace  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402


PRODUCT_CATEGORY_TERMS = (
    "书架",
    "柜",
    "收纳",
    "餐椅",
    "椅",
    "书桌",
    "桌",
    "床",
    "护栏",
    "围栏",
    "餐盘",
    "台面",
    "隔板",
    "侧板",
    "挡板",
    "抽屉",
)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _dig(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _sidecar(trace: EvalTrace) -> dict[str, Any]:
    raw = trace.get_raw_response() or {}
    identity = trace.get_product_identity() or {}
    sidecar = raw.get("sidecar_context") if isinstance(raw.get("sidecar_context"), dict) else {}
    if not sidecar:
        sidecar = _dig(raw, "copilot_context", "sidecar_context") or {}
    if not sidecar:
        sidecar = _dig(identity, "sidecar_context") or {}
    return {
        "product_title": sanitize_text(sidecar.get("product_title") or sidecar.get("product_name")),
        "sku_code": sanitize_text(sidecar.get("sku_code")),
        "i_id": sanitize_text(sidecar.get("i_id")),
        "order_id": sanitize_text(sidecar.get("order_id")),
        "quality": sanitize_text(sidecar.get("sidecar_context_quality") or raw.get("sidecar_context_quality")),
        "sources": sidecar.get("sidecar_context_sources") or raw.get("sidecar_context_sources") or [],
    }


def _real_product_context(trace: EvalTrace) -> dict[str, str]:
    raw = trace.get_raw_response() or {}
    identity = trace.get_product_identity() or {}
    real_identity = identity.get("real_context_product_identity") if isinstance(identity.get("real_context_product_identity"), dict) else {}
    real_context = identity.get("real_context") if isinstance(identity.get("real_context"), dict) else {}
    metadata_product = ""
    return {
        "product_title": sanitize_text(
            real_identity.get("product_title")
            or real_identity.get("order_product_title")
            or real_identity.get("display_product_name")
            or real_context.get("product_title_preview")
            or raw.get("product_title")
            or metadata_product
        ),
        "sku_code": sanitize_text(real_identity.get("sku_code") or raw.get("sku_code")),
        "i_id": sanitize_text(real_identity.get("i_id") or raw.get("i_id")),
        "item_id_hash": sanitize_text(real_identity.get("item_id_hash")),
    }


def _category_terms(text: str) -> set[str]:
    clean = sanitize_text(text)
    return {term for term in PRODUCT_CATEGORY_TERMS if term and term in clean}


def _contains_cross_category_signal(buyer_text: str, sidecar_title: str) -> tuple[bool, list[str]]:
    buyer_terms = _category_terms(buyer_text)
    sidecar_terms = _category_terms(sidecar_title)
    other_terms = sorted(term for term in buyer_terms if term not in sidecar_terms)
    return bool(other_terms and sidecar_title), other_terms


def _selected_product_signals(trace: EvalTrace) -> dict[str, Any]:
    selected = trace.get_selected_evidence() or []
    titles: Counter[str] = Counter()
    iids: Counter[str] = Counter()
    previews: list[str] = []
    for item in selected:
        if not isinstance(item, dict):
            continue
        for key in ("product_title", "product_name", "title"):
            text = sanitize_text(item.get(key))
            if text:
                titles[text] += 1
        for key in ("i_id", "sku_code", "product_id"):
            text = sanitize_text(item.get(key))
            if text:
                iids[text] += 1
        preview = sanitize_text(item.get("chunk_preview") or item.get("preview") or item.get("text"))
        if preview:
            previews.append(preview[:120])
    return {
        "selected_evidence_count": len(selected),
        "product_titles": dict(titles.most_common(5)),
        "product_ids": dict(iids.most_common(5)),
        "previews": previews[:3],
    }


def _reply_product_terms(reply: str) -> list[str]:
    return sorted(_category_terms(reply))


def _classify_row(trace: EvalTrace) -> dict[str, Any]:
    buyer = sanitize_text(trace.buyer_message)
    agent = sanitize_text(trace.agent_reply)
    sidecar = _sidecar(trace)
    real_product = _real_product_context(trace)
    evidence = _selected_product_signals(trace)
    buyer_cross, buyer_terms = _contains_cross_category_signal(buyer, sidecar["product_title"])
    real_title = real_product.get("product_title", "")
    real_vs_sidecar = bool(real_title and sidecar["product_title"] and real_title != sidecar["product_title"])
    sidecar_missing = not (sidecar["product_title"] or sidecar["sku_code"] or sidecar["i_id"])

    evidence_ids = set(evidence.get("product_ids") or {})
    sidecar_ids = {sidecar.get("i_id"), sidecar.get("sku_code")} - {""}
    evidence_product_mismatch = bool(evidence_ids and sidecar_ids and not (evidence_ids & sidecar_ids))

    if sidecar_missing:
        category = "insufficient_product_context"
    elif real_vs_sidecar or buyer_cross:
        category = "likely_sidecar_fixture_mismatch"
    elif evidence_product_mismatch:
        category = "evidence_product_mismatch"
    else:
        category = "no_mismatch"

    quality_bucket = trace.get_quality_bucket() or {}
    adjusted_bucket = quality_bucket.get("quality_bucket", "")
    if category == "likely_sidecar_fixture_mismatch" and adjusted_bucket == "agent_error":
        adjusted_bucket = "eval_fixture_gap"

    return {
        "run_uid": trace.run_uid,
        "case_uid": trace.case_uid,
        "turn_uid": trace.turn_uid,
        "buyer_message_preview": buyer[:160],
        "agent_reply_preview": agent[:180],
        "query_fact_type": sanitize_text(trace.query_fact_type),
        "quality_bucket": quality_bucket.get("quality_bucket", ""),
        "adjusted_quality_bucket": adjusted_bucket,
        "failure_labels": trace.get_failure_labels(),
        "classification": category,
        "buyer_mentions_other_product": buyer_cross,
        "buyer_other_product_terms": buyer_terms,
        "sidecar": sidecar,
        "real_product_context": real_product,
        "selected_evidence": evidence,
        "reply_product_terms": _reply_product_terms(agent),
        "suggested_action": _suggested_action(category),
    }


def _suggested_action(category: str) -> str:
    if category == "likely_sidecar_fixture_mismatch":
        return "将该轮从 Agent 主链路错误中隔离为 eval fixture gap；使用真实千牛侧栏或按样本注入正确商品后再评估"
    if category == "evidence_product_mismatch":
        return "检查 evidence pack 产品身份来源，禁止错商品证据进入 direct answer"
    if category == "insufficient_product_context":
        return "补齐商品标题/SKU/i_id 侧栏上下文；不要用平台 hash 猜商品"
    return "无需按 sidecar 错配处理"


def diagnose_sidecar_product_mismatch(
    *,
    run_uid: str = "",
    json_output: str = "",
    db_factory=SessionLocal,
) -> dict[str, Any]:
    db = db_factory()
    try:
        resolved_run_uid = sanitize_text(run_uid) or _latest_run_uid(db)
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == resolved_run_uid)
            .order_by(EvalTrace.id.asc())
            .all()
        )
    finally:
        db.close()

    rows = [_classify_row(trace) for trace in traces]
    counts = Counter(row["classification"] for row in rows)
    agent_error_fixture_gap_count = sum(
        1
        for row in rows
        if row["quality_bucket"] == "agent_error" and row["adjusted_quality_bucket"] == "eval_fixture_gap"
    )
    summary = {
        "run_uid": resolved_run_uid,
        "trace_count": len(rows),
        "classification_counts": dict(counts),
        "agent_error_eval_fixture_gap_count": agent_error_fixture_gap_count,
        "notes": [
            "This is read-only diagnostics; it does not rewrite EvalTrace quality buckets.",
            "eval_fixture_gap means local replay sidecar likely injected a product different from the real buyer question.",
        ],
    }
    result = {"summary": summary, "rows": rows}
    _write_json(json_output, result)
    return sanitize_obj(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose sidecar product mismatch for replay traces.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    result = diagnose_sidecar_product_mismatch(run_uid=args.run_uid, json_output=args.json_output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
