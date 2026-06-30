"""Diagnose why usable AI provisional drafts did or did not hit a replay run."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db
from app.models.eval_tables import AIProvisionalKnowledge, EvalRun, EvalTrace
from app.services.ai_provisional_knowledge_service import _fact_type_aliases
from app.services.ai_provisional_usage_trace_service import extract_ai_provisional_usage_from_trace
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _run_uid_from_json(path: str) -> str:
    if not sanitize_text(path):
        return ""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return sanitize_text(
            data.get("run_uid")
            or (data.get("replay") or {}).get("run_uid")
            or (data.get("schedule") or {}).get("run_uid")
        )
    return ""


def _identity_from_usage(usage: dict[str, Any]) -> dict[str, Any]:
    identities = []
    for item in usage.get("provisional_evidence") or []:
        identities.append({
            "i_id": sanitize_text(item.get("i_id")),
            "sku_code": sanitize_text(item.get("sku_code")),
            "kb_product_id": item.get("kb_product_id"),
        })
    return {"identities": identities}


def _same_identity(draft: AIProvisionalKnowledge, usage: dict[str, Any]) -> bool:
    draft_iid = sanitize_text(draft.i_id)
    draft_sku = sanitize_text(draft.sku_code)
    for identity in _identity_from_usage(usage)["identities"]:
        if (
            (draft_iid and draft_iid == sanitize_text(identity.get("i_id")))
            or (draft_sku and draft_sku == sanitize_text(identity.get("sku_code")))
            or (draft.kb_product_id and draft.kb_product_id == identity.get("kb_product_id"))
        ):
            return True
    return False


def _fact_alias_match(left: str, right: str) -> bool:
    left_aliases = _fact_type_aliases(left)
    right_aliases = _fact_type_aliases(right)
    return bool(left_aliases and right_aliases and left_aliases.intersection(right_aliases))


def _trace_has_product_context_pack(trace: EvalTrace) -> bool:
    raw = trace.get_raw_response() or {}
    if raw.get("product_first_evidence_pack"):
        return True
    product_context = raw.get("product_context_pack") if isinstance(raw.get("product_context_pack"), dict) else {}
    if product_context.get("product_first_evidence_pack") or product_context.get("evidence_pack"):
        return True
    evidence_debug = raw.get("evidence_debug") if isinstance(raw.get("evidence_debug"), dict) else {}
    summary = evidence_debug.get("product_context_pack_summary") if isinstance(evidence_debug.get("product_context_pack_summary"), dict) else {}
    return bool(summary.get("evidence_pack") or summary.get("product_first_evidence_pack"))


def _miss_reason(draft: AIProvisionalKnowledge, traces: list[EvalTrace], usages: dict[str, dict[str, Any]]) -> str:
    if not (sanitize_text(draft.i_id) or sanitize_text(draft.sku_code) or draft.kb_product_id):
        return "provisional_without_identity"
    if not traces:
        return "no_replay_turn_for_identity"

    identity_turns = [trace for trace in traces if _same_identity(draft, usages[trace.turn_uid])]
    if not identity_turns:
        any_usage_identity = any(
            item.get("i_id") or item.get("sku_code") or item.get("kb_product_id")
            for usage in usages.values()
            for item in usage.get("provisional_evidence", [])
        )
        return "no_replay_turn_for_identity" if any_usage_identity else "product_identity_not_resolved_in_replay"

    alias_turns = [trace for trace in identity_turns if _fact_alias_match(draft.query_fact_type, trace.query_fact_type)]
    if not alias_turns:
        return "fact_type_mismatch"

    if any(not _trace_has_product_context_pack(trace) for trace in alias_turns):
        return "no_product_context_pack"

    for trace in alias_turns:
        used_ids = {
            item.get("draft_uid") or item.get("provisional_draft_uid")
            for item in usages[trace.turn_uid].get("provisional_evidence", [])
        }
        if used_ids and draft.draft_uid not in used_ids:
            return "evidence_pack_not_consumed"
    return "unknown"


def diagnose_usage(run_uid: str = "", limit: int = 500, *, run_json: str = "") -> dict[str, Any]:
    db = SessionLocal()
    try:
        target = sanitize_text(run_uid) or _run_uid_from_json(run_json) or _latest_run_uid(db)
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == target)
            .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            .all()
        )
        usages = {trace.turn_uid: extract_ai_provisional_usage_from_trace(trace) for trace in traces}
        used_by_draft: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for usage in usages.values():
            for item in usage.get("provisional_evidence") or []:
                draft_uid = sanitize_text(item.get("draft_uid") or item.get("provisional_draft_uid"))
                if draft_uid:
                    used_by_draft[draft_uid].append({
                        "case_uid": usage.get("case_uid"),
                        "turn_uid": usage.get("turn_uid"),
                        "query_fact_type": usage.get("query_fact_type"),
                        "evidence": item,
                    })

        drafts = (
            db.query(AIProvisionalKnowledge)
            .filter(
                AIProvisionalKnowledge.usable_for_eval == True,  # noqa: E712
                AIProvisionalKnowledge.usable_for_auto_send == False,  # noqa: E712
            )
            .order_by(AIProvisionalKnowledge.updated_at.desc(), AIProvisionalKnowledge.id.desc())
            .limit(max(1, min(int(limit or 500), 2000)))
            .all()
        )
        rows = []
        reasons = Counter()
        for draft in drafts:
            identity_turns = [trace for trace in traces if _same_identity(draft, usages[trace.turn_uid])]
            alias_turns = [trace for trace in traces if _fact_alias_match(draft.query_fact_type, trace.query_fact_type)]
            has_related_turn = any(
                sanitize_text(draft.turn_uid) and draft.turn_uid == trace.turn_uid
                for trace in traces
            )
            used = draft.draft_uid in used_by_draft
            reason = "used" if used else _miss_reason(draft, traces, usages)
            reasons[reason] += 1
            rows.append(sanitize_obj({
                "draft_uid": draft.draft_uid,
                "query_fact_type": draft.query_fact_type,
                "i_id": draft.i_id,
                "sku_code": draft.sku_code,
                "kb_product_id": draft.kb_product_id,
                "source_run_uid": draft.source_run_uid,
                "task_uid": draft.task_uid,
                "appears_same_identity_in_replay": bool(identity_turns),
                "appears_alias_query_fact_type_in_replay": bool(alias_turns),
                "has_related_turn": has_related_turn,
                "used": used,
                "miss_reason": reason,
            }))
        used_evidence_count = sum(len(value) for value in used_by_draft.values())
        return sanitize_obj({
            "run_uid": target,
            "replay_turn_count": len(traces),
            "usable_provisional_count": len(drafts),
            "used_turn_count": sum(1 for usage in usages.values() if usage.get("provisional_used_turn")),
            "used_evidence_count": used_evidence_count,
            "used_draft_count": len(used_by_draft),
            "usage_by_draft_uid": dict(used_by_draft),
            "miss_reason_counts": dict(reasons),
            "drafts": rows,
        })
    finally:
        db.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Diagnose AI provisional evidence usage for a replay run.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--run-json", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json-output", "--output", dest="json_output", default="")
    args = parser.parse_args()
    init_db()
    result = diagnose_usage(args.run_uid, args.limit, run_json=args.run_json)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
