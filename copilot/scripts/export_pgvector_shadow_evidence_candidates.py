"""Export read-only evidence governance candidates from replay pgvector shadow.

The output is a governance list only. It must not be used as formal RAG evidence
until reviewed and promoted through a separate process.
"""

from __future__ import annotations

import argparse
import json
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


DIRECT_ROLES = {"product_fact_direct", "faq_direct", "product_facts", "faq"}
SERVICE_ROLES = {"service_action", "fallback_only"}
MEDIA_ROLES = {"media_reference"}

EXCEL_COLUMNS = [
    ("候选分类", "candidate_type"),
    ("回放批次", "run_uid"),
    ("案例 ID", "case_uid"),
    ("轮次 ID", "turn_uid"),
    ("买家问题预览", "buyer_message_preview"),
    ("问题类型", "query_fact_type"),
    ("侧栏商品", "sidecar_product_title"),
    ("侧栏 SKU", "sidecar_sku_code"),
    ("侧栏 i_id", "sidecar_i_id"),
    ("来源类型", "source_type"),
    ("证据角色", "evidence_role"),
    ("素材角色", "media_role"),
    ("候选预览", "candidate_text_preview"),
    ("分数", "score"),
    ("可直接回答", "direct_answerable"),
    ("不能自动发送原因", "not_auto_send_reason"),
    ("建议治理动作", "suggested_action"),
]


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_excel(path: str, rows: list[dict[str, Any]]) -> None:
    if not path:
        return
    from openpyxl import Workbook
    from openpyxl.styles import Font

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "pgvector候选证据"
    ws.append([label for label, _ in EXCEL_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([row.get(key, "") for _, key in EXCEL_COLUMNS])
    wb.save(target)


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


def _sidecar_from_trace(trace: EvalTrace) -> dict[str, str]:
    raw = trace.get_raw_response() or {}
    sidecar = raw.get("sidecar_context") if isinstance(raw.get("sidecar_context"), dict) else {}
    if not sidecar:
        sidecar = _dig(raw, "copilot_context", "sidecar_context") or {}
    return {
        "product_title": sanitize_text(sidecar.get("product_title") or sidecar.get("product_name")),
        "sku_code": sanitize_text(sidecar.get("sku_code")),
        "i_id": sanitize_text(sidecar.get("i_id")),
    }


def _candidate_type(source_type: str, evidence_role: str) -> str:
    source_type = sanitize_text(source_type)
    evidence_role = sanitize_text(evidence_role)
    if evidence_role in {"product_fact_direct", "faq_direct"} or source_type in {"product_facts", "product_fact", "faq", "kbqa"}:
        return "product_fact_candidate"
    if evidence_role in SERVICE_ROLES or source_type in {"generic_rule", "generic_rules", "response_templates"}:
        return "service_action_candidate"
    if evidence_role in MEDIA_ROLES or source_type == "media_asset":
        return "media_reference_candidate"
    return "reference_only_candidate"


def _not_auto_send_reason(candidate_type: str) -> str:
    if candidate_type == "product_fact_candidate":
        return "pgvector shadow 只是候选证据，未进入正式 evidence pack 审核"
    if candidate_type == "service_action_candidate":
        return "service_action 只能作为客服动作 fallback，不能当商品事实"
    if candidate_type == "media_reference_candidate":
        return "media_reference 只表示素材候选，必须后续满足素材 role 和 reply_blocks 合同"
    if candidate_type == "conflict_candidate":
        return "同一商品或 fact_type 存在冲突候选，必须人工核验"
    return "候选角色不足以直接发送"


def _suggested_action(candidate_type: str) -> str:
    if candidate_type == "product_fact_candidate":
        return "进入证据候选审核；确认来源可信、商品身份和 fact_type 后再考虑正式化"
    if candidate_type == "service_action_candidate":
        return "进入服务动作 fallback 治理；保持 requires_human_review，不提升 can_send"
    if candidate_type == "media_reference_candidate":
        return "进入素材治理；确认素材审核状态、media role 和是否可生成 reply block"
    if candidate_type == "conflict_candidate":
        return "进入高风险冲突证据核验；冲突消除前必须 blocked 或人工确认"
    return "人工复核候选角色"


def _candidate_rows_from_shadow(
    *,
    run_uid: str,
    case_uid: str,
    turn_uid: str,
    buyer_message: str,
    query_fact_type: str,
    sidecar: dict[str, str],
    shadow: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    buckets = [
        ("product_fact", shadow.get("product_fact") or {}),
        ("service_action", shadow.get("service_action") or {}),
        ("media_reference", shadow.get("media_reference") or {}),
    ]
    for _, bucket in buckets:
        candidates = bucket.get("top_candidates") if isinstance(bucket, dict) else []
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            source_type = sanitize_text(candidate.get("source_type"))
            evidence_role = sanitize_text(candidate.get("evidence_role"))
            ctype = _candidate_type(source_type, evidence_role)
            rows.append({
                "candidate_type": ctype,
                "run_uid": run_uid,
                "case_uid": case_uid,
                "turn_uid": turn_uid,
                "buyer_message_preview": sanitize_text(buyer_message)[:160],
                "query_fact_type": query_fact_type,
                "sidecar_product_title": sidecar.get("product_title", ""),
                "sidecar_sku_code": sidecar.get("sku_code", ""),
                "sidecar_i_id": sidecar.get("i_id", ""),
                "candidate_id": sanitize_text(candidate.get("id")),
                "source_type": source_type,
                "evidence_role": evidence_role,
                "media_role": sanitize_text(candidate.get("media_role")),
                "candidate_text_preview": sanitize_text(candidate.get("preview"))[:240],
                "score": candidate.get("score") or 0,
                "direct_answerable": ctype == "product_fact_candidate",
                "not_auto_send_reason": _not_auto_send_reason(ctype),
                "suggested_action": _suggested_action(ctype),
            })
    return rows


def _rows_from_shadow_json(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("rows") or []:
        shadow = item.get("pgvector_shadow") or {}
        sidecar = item.get("sidecar") or {}
        mode_results = shadow.get("filter_mode_results") if isinstance(shadow, dict) else {}
        if mode_results:
            pseudo_shadow = {"product_fact": {"top_candidates": []}, "service_action": {"top_candidates": []}, "media_reference": {"top_candidates": []}}
            for mode in ("strict", "service_action_merge", "no_fact_type", "product_only", "fact_type_alias"):
                mode_payload = mode_results.get(mode) or {}
                for candidate in mode_payload.get("top_candidates") or []:
                    ctype = _candidate_type(candidate.get("source_type", ""), candidate.get("evidence_role", ""))
                    if ctype == "product_fact_candidate":
                        pseudo_shadow["product_fact"]["top_candidates"].append(candidate)
                    elif ctype == "service_action_candidate":
                        pseudo_shadow["service_action"]["top_candidates"].append(candidate)
                    elif ctype == "media_reference_candidate":
                        pseudo_shadow["media_reference"]["top_candidates"].append(candidate)
            shadow = pseudo_shadow
        rows.extend(_candidate_rows_from_shadow(
            run_uid=sanitize_text(payload.get("summary", {}).get("run_uid") or item.get("run_uid")),
            case_uid=sanitize_text(item.get("case_uid")),
            turn_uid=sanitize_text(item.get("turn_uid")),
            buyer_message=sanitize_text(item.get("buyer_message_preview")),
            query_fact_type=sanitize_text(item.get("query_fact_type")),
            sidecar={
                "product_title": sanitize_text(sidecar.get("product_title")),
                "sku_code": sanitize_text(sidecar.get("sku_code")),
                "i_id": sanitize_text(sidecar.get("i_id")),
            },
            shadow=shadow,
        ))
    return rows


def export_pgvector_shadow_candidates(
    *,
    run_uid: str = "",
    shadow_json: str = "",
    json_output: str = "",
    excel_output: str = "",
    db_factory=SessionLocal,
) -> dict[str, Any]:
    if shadow_json:
        rows = _rows_from_shadow_json(shadow_json)
        resolved_run_uid = sanitize_text(run_uid) or ""
    else:
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
        rows = []
        for trace in traces:
            raw = trace.get_raw_response() or {}
            shadow = raw.get("pgvector_shadow") if isinstance(raw.get("pgvector_shadow"), dict) else {}
            if not shadow:
                continue
            rows.extend(_candidate_rows_from_shadow(
                run_uid=trace.run_uid,
                case_uid=trace.case_uid,
                turn_uid=trace.turn_uid,
                buyer_message=trace.buyer_message,
                query_fact_type=sanitize_text(trace.query_fact_type),
                sidecar=_sidecar_from_trace(trace),
                shadow=shadow,
            ))
    type_counts = Counter(row["candidate_type"] for row in rows)
    summary = {
        "run_uid": resolved_run_uid,
        "candidate_count": len(rows),
        "by_candidate_type": dict(type_counts),
        "direct_answerable_count": sum(1 for row in rows if row.get("direct_answerable")),
        "service_action_count": type_counts.get("service_action_candidate", 0),
        "media_reference_count": type_counts.get("media_reference_candidate", 0),
        "notes": [
            "This export is read-only and does not write formal KB/RAG data.",
            "service_action and media_reference candidates must not increase can_send.",
        ],
    }
    result = {"summary": summary, "rows": rows}
    _write_json(json_output, result)
    _write_excel(excel_output, rows)
    return sanitize_obj(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export pgvector shadow governance candidates.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--shadow-json", default="")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--excel-output", default="")
    args = parser.parse_args()
    result = export_pgvector_shadow_candidates(
        run_uid=args.run_uid,
        shadow_json=args.shadow_json,
        json_output=args.json_output,
        excel_output=args.excel_output,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
