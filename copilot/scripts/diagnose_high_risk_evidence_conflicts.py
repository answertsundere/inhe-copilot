"""Diagnose conflicting high-risk evidence in replay traces.

Conflicts in load capacity, material safety, certification, age, or child-safety
evidence should keep the turn blocked or under human review. This script is
read-only and exports conflict candidates for evidence governance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.eval_tables import EvalRun, EvalTrace  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402


HIGH_RISK_FACT_TYPES = {
    "load_capacity",
    "material_safety",
    "material",
    "certification_report",
    "age_range",
    "child_safety",
    "child_suitability",
    "food_grade",
    "non_toxic_claim",
}

NUMERIC_PATTERN = re.compile(r"(?P<a>\d+(?:\.\d+)?)\s*(?:[-~到至]\s*(?P<b>\d+(?:\.\d+)?))?\s*(?P<unit>kg|KG|公斤|斤|岁|周岁|cm|CM|厘米|mm|MM|毫米)")
SAFETY_CLAIM_TERMS = ("无毒", "食品级", "有证书", "检测报告", "3C", "绝对安全", "不会夹手", "保护宝宝安全")


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


def _sidecar(trace: EvalTrace) -> dict[str, str]:
    raw = trace.get_raw_response() or {}
    sidecar = raw.get("sidecar_context") if isinstance(raw.get("sidecar_context"), dict) else {}
    if not sidecar:
        sidecar = _dig(raw, "copilot_context", "sidecar_context") or {}
    return {
        "product_title": sanitize_text(sidecar.get("product_title") or sidecar.get("product_name")),
        "sku_code": sanitize_text(sidecar.get("sku_code")),
        "i_id": sanitize_text(sidecar.get("i_id")),
    }


def _extract_claims(text: str) -> tuple[set[str], set[str]]:
    clean = sanitize_text(text)
    numeric: set[str] = set()
    for match in NUMERIC_PATTERN.finditer(clean):
        a = match.group("a")
        b = match.group("b") or ""
        unit = match.group("unit").lower().replace("公斤", "kg").replace("周岁", "岁")
        numeric.add(f"{a}{('-' + b) if b else ''}{unit}")
    safety = {term for term in SAFETY_CLAIM_TERMS if term in clean}
    return numeric, safety


def _candidate_text(item: dict[str, Any]) -> str:
    return sanitize_text(
        item.get("chunk_preview")
        or item.get("preview")
        or item.get("chunk_text")
        or item.get("text")
        or ""
    )


def _collect_candidates(trace: EvalTrace) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in trace.get_selected_evidence() or []:
        if not isinstance(item, dict):
            continue
        text = _candidate_text(item)
        numeric, safety = _extract_claims(text)
        candidates.append({
            "source": "selected_evidence",
            "source_type": sanitize_text(item.get("source_type")),
            "evidence_role": sanitize_text(item.get("evidence_role") or item.get("evidence_fact_type") or item.get("query_fact_type")),
            "score": item.get("rerank_score") or item.get("score") or 0,
            "preview": text[:200],
            "numeric_claims": sorted(numeric),
            "safety_claims": sorted(safety),
        })
    raw = trace.get_raw_response() or {}
    shadow = raw.get("pgvector_shadow") if isinstance(raw.get("pgvector_shadow"), dict) else {}
    for bucket_name in ("product_fact", "service_action", "media_reference"):
        bucket = shadow.get(bucket_name) if isinstance(shadow.get(bucket_name), dict) else {}
        for item in bucket.get("top_candidates") or []:
            if not isinstance(item, dict):
                continue
            text = _candidate_text(item)
            numeric, safety = _extract_claims(text)
            candidates.append({
                "source": f"pgvector_shadow:{bucket_name}",
                "source_type": sanitize_text(item.get("source_type")),
                "evidence_role": sanitize_text(item.get("evidence_role")),
                "media_role": sanitize_text(item.get("media_role")),
                "score": item.get("score") or 0,
                "preview": text[:200],
                "numeric_claims": sorted(numeric),
                "safety_claims": sorted(safety),
            })
    return candidates


def _classify_conflict(query_fact_type: str, candidates: list[dict[str, Any]]) -> tuple[str, list[str]]:
    numeric_claims: set[str] = set()
    safety_claims: set[str] = set()
    source_types: set[str] = set()
    for candidate in candidates:
        numeric_claims.update(candidate.get("numeric_claims") or [])
        safety_claims.update(candidate.get("safety_claims") or [])
        if candidate.get("source_type"):
            source_types.add(candidate["source_type"])
    if len(numeric_claims) > 1:
        return "numeric_conflict", sorted(numeric_claims)
    if query_fact_type in {"material_safety", "child_safety", "food_grade", "non_toxic_claim", "certification_report"} and safety_claims:
        if len(safety_claims) > 1 or any(candidate.get("source", "").startswith("pgvector_shadow:service_action") for candidate in candidates):
            return "safety_claim_conflict", sorted(safety_claims)
    if len(source_types) > 1 and query_fact_type in HIGH_RISK_FACT_TYPES and (numeric_claims or safety_claims):
        return "source_trust_conflict", sorted(numeric_claims | safety_claims)
    if not candidates:
        return "needs_manual_verification", []
    return "no_conflict", sorted(numeric_claims | safety_claims)


def diagnose_high_risk_evidence_conflicts(
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

    rows: list[dict[str, Any]] = []
    for trace in traces:
        query_fact_type = sanitize_text(trace.query_fact_type)
        if query_fact_type not in HIGH_RISK_FACT_TYPES:
            continue
        candidates = _collect_candidates(trace)
        category, claims = _classify_conflict(query_fact_type, candidates)
        rows.append({
            "run_uid": trace.run_uid,
            "case_uid": trace.case_uid,
            "turn_uid": trace.turn_uid,
            "buyer_message_preview": sanitize_text(trace.buyer_message)[:160],
            "query_fact_type": query_fact_type,
            "sidecar": _sidecar(trace),
            "quality_bucket": (trace.get_quality_bucket() or {}).get("quality_bucket", ""),
            "failure_labels": trace.get_failure_labels(),
            "conflict_category": category,
            "claims": claims,
            "candidate_count": len(candidates),
            "candidates": candidates[:8],
            "must_block_or_handoff": category != "no_conflict",
            "suggested_action": _suggested_action(category),
        })
    counts = Counter(row["conflict_category"] for row in rows)
    summary = {
        "run_uid": resolved_run_uid,
        "high_risk_trace_count": len(rows),
        "by_conflict_category": dict(counts),
        "blocked_or_handoff_required_count": sum(1 for row in rows if row["must_block_or_handoff"]),
        "notes": [
            "Conflicting high-risk evidence is not merged into an answer.",
            "This script is read-only and does not change final gate behavior.",
        ],
    }
    result = {"summary": summary, "rows": rows}
    _write_json(json_output, result)
    return sanitize_obj(result)


def _suggested_action(category: str) -> str:
    if category == "numeric_conflict":
        return "人工核验同一商品同一 fact_type 的数值口径；冲突消除前保持 blocked/requires_human_review"
    if category == "safety_claim_conflict":
        return "人工核验证书、安全、无毒、年龄等高风险承诺；未确认前不能直接发送"
    if category == "source_trust_conflict":
        return "按来源可信层级重审证据，低可信或过期来源不得覆盖结构化字段"
    if category == "needs_manual_verification":
        return "缺少可核验证据，保持人工确认"
    return "无冲突；仍需遵守 fact_type 和 final gate 合同"


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose high-risk evidence conflicts for replay traces.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    result = diagnose_high_risk_evidence_conflicts(run_uid=args.run_uid, json_output=args.json_output)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
