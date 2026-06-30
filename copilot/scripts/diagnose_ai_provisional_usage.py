"""Diagnose why usable AI provisional drafts did or did not hit a replay run."""

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

from app.db import SessionLocal, init_db
from app.models.eval_tables import AIProvisionalKnowledge, EvalRun, EvalTrace
from app.services.ai_provisional_knowledge_service import _fact_type_aliases
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from scripts.compare_replay_knowledge_modes import _pack_from_raw, _provisional_evidence_from_pack


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _identity_from_trace(trace: EvalTrace) -> dict[str, Any]:
    pack = _pack_from_raw(trace.get_raw_response() or {})
    identity = pack.get("resolved_product_identity") if isinstance(pack.get("resolved_product_identity"), dict) else {}
    return {
        "i_id": sanitize_text(identity.get("i_id") or identity.get("item_id") or ""),
        "sku_code": sanitize_text(identity.get("sku") or identity.get("sku_code") or ""),
        "kb_product_id": identity.get("product_id") or identity.get("kb_product_id"),
        "has_pack": bool(pack),
        "pack": pack,
    }


def _same_identity(draft: AIProvisionalKnowledge, identity: dict[str, Any]) -> bool:
    draft_iid = sanitize_text(draft.i_id)
    draft_sku = sanitize_text(draft.sku_code)
    return bool(
        (draft_iid and draft_iid == sanitize_text(identity.get("i_id")))
        or (draft_sku and draft_sku == sanitize_text(identity.get("sku_code")))
        or (draft.kb_product_id and draft.kb_product_id == identity.get("kb_product_id"))
    )


def _fact_alias_match(left: str, right: str) -> bool:
    left_aliases = _fact_type_aliases(left)
    right_aliases = _fact_type_aliases(right)
    return bool(left_aliases and right_aliases and left_aliases.intersection(right_aliases))


def _used_draft_uids(trace: EvalTrace) -> set[str]:
    pack = _pack_from_raw(trace.get_raw_response() or {})
    return {
        item.get("provisional_draft_uid")
        for item in _provisional_evidence_from_pack(pack)
        if item.get("provisional_draft_uid")
    }


def _miss_reason(draft: AIProvisionalKnowledge, traces: list[EvalTrace], trace_identities: dict[str, dict[str, Any]]) -> str:
    if not (sanitize_text(draft.i_id) or sanitize_text(draft.sku_code) or draft.kb_product_id):
        return "provisional_without_identity"
    if not traces:
        return "no_replay_turn_for_identity"

    identity_turns = [trace for trace in traces if _same_identity(draft, trace_identities[trace.turn_uid])]
    if not identity_turns:
        any_resolved_identity = any(
            identity.get("i_id") or identity.get("sku_code") or identity.get("kb_product_id")
            for identity in trace_identities.values()
        )
        return "no_replay_turn_for_identity" if any_resolved_identity else "product_identity_not_resolved_in_replay"

    alias_turns = [trace for trace in identity_turns if _fact_alias_match(draft.query_fact_type, trace.query_fact_type)]
    if not alias_turns:
        return "fact_type_mismatch"

    if any(not trace_identities[trace.turn_uid].get("has_pack") for trace in alias_turns):
        return "no_product_context_pack"

    for trace in alias_turns:
        used_ids = _used_draft_uids(trace)
        if used_ids and draft.draft_uid not in used_ids:
            return "evidence_pack_not_consumed"
    return "unknown"


def diagnose_usage(run_uid: str = "", limit: int = 500) -> dict[str, Any]:
    db = SessionLocal()
    try:
        target = sanitize_text(run_uid) or _latest_run_uid(db)
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == target)
            .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            .all()
        )
        trace_identities = {trace.turn_uid: _identity_from_trace(trace) for trace in traces}
        used_ids = set()
        for trace in traces:
            used_ids.update(_used_draft_uids(trace))

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
            identity_turns = [trace for trace in traces if _same_identity(draft, trace_identities[trace.turn_uid])]
            alias_turns = [trace for trace in traces if _fact_alias_match(draft.query_fact_type, trace.query_fact_type)]
            has_related_turn = any(
                sanitize_text(draft.turn_uid) and draft.turn_uid == trace.turn_uid
                for trace in traces
            )
            used = draft.draft_uid in used_ids
            reason = "used" if used else _miss_reason(draft, traces, trace_identities)
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
        return sanitize_obj({
            "run_uid": target,
            "replay_turn_count": len(traces),
            "usable_provisional_count": len(drafts),
            "used_draft_count": len(used_ids),
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
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    init_db()
    result = diagnose_usage(args.run_uid, args.limit)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
