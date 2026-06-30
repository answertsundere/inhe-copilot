"""Compare verified-only and verified-plus-ai-prefill replay runs."""

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


def _raw_replay_counts_from_json(path: str) -> dict[str, int]:
    if not sanitize_text(path):
        return {"total_turns": 0, "total_cases": 0}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"total_turns": 0, "total_cases": 0}
    replay = data.get("replay") if isinstance(data.get("replay"), dict) else {}
    schedule = data.get("schedule") if isinstance(data.get("schedule"), dict) else {}
    return {
        "total_turns": int(replay.get("turns") or replay.get("total_turns") or schedule.get("total_turns") or 0),
        "total_cases": int(replay.get("total_cases") or schedule.get("total_cases") or 0),
    }


def _load_traces(db, run_uid: str, sample_limit: int) -> list[EvalTrace]:
    return (
        db.query(EvalTrace)
        .filter(EvalTrace.run_uid == run_uid)
        .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
        .limit(max(1, int(sample_limit or 50)))
        .all()
    )


def summarize_run(db, run_uid: str, sample_limit: int = 50) -> dict[str, Any]:
    traces = _load_traces(db, run_uid, sample_limit)
    buckets = Counter()
    failures = Counter()
    query_fact_types = Counter()
    answer_sources = Counter()
    passed_count = 0
    failed_count = 0
    used_turns: list[dict[str, Any]] = []
    used_draft_uids: set[str] = set()
    used_evidence_count = 0
    auto_send_with_provisional_count = 0
    for trace in traces:
        raw = trace.get_raw_response() or {}
        if trace.passed:
            passed_count += 1
        else:
            failed_count += 1
        bucket = trace.get_quality_bucket()
        if bucket:
            buckets[bucket.get("quality_bucket") or "unknown"] += 1
        for label in trace.get_failure_labels() or []:
            failures[label] += 1
        if trace.query_fact_type:
            query_fact_types[trace.query_fact_type] += 1
        answer_trace = trace.get_answer_trace() or {}
        source = answer_trace.get("final_answer_source") or answer_trace.get("selected_evidence_role") or ""
        if source:
            answer_sources[source] += 1

        usage = extract_ai_provisional_usage_from_trace(trace)
        if usage["provisional_used_turn"]:
            used_evidence_count += int(usage["provisional_evidence_count"])
            used_draft_uids.update(
                item.get("draft_uid") or item.get("provisional_draft_uid")
                for item in usage["provisional_evidence"]
                if item.get("draft_uid") or item.get("provisional_draft_uid")
            )
            if usage["auto_send_with_provisional"]:
                auto_send_with_provisional_count += 1
            used_turns.append({
                "case_uid": usage["case_uid"],
                "turn_uid": usage["turn_uid"],
                "buyer_message_preview": usage["buyer_message_preview"],
                "query_fact_type": usage["query_fact_type"],
                "provisional_evidence": usage["provisional_evidence"],
                "can_send": usage["can_send"],
                "sendable_reply_empty": usage["sendable_reply_empty"],
                "requires_human_review": usage["requires_human_review"],
                "quality_bucket": usage["quality_bucket"],
                "failure_labels": usage["failure_labels"],
            })

    return sanitize_obj({
        "run_uid": run_uid,
        "sampled_turns": len(traces),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "quality_bucket_counts": dict(buckets),
        "failure_type_counts": dict(failures),
        "query_fact_type_counts": dict(query_fact_types),
        "answer_source_counts": dict(answer_sources),
        "provisional_used_turn_count": len(used_turns),
        "provisional_used_evidence_count": used_evidence_count,
        "provisional_used_draft_count": len(used_draft_uids),
        "provisional_used_turns": used_turns,
        "auto_send_with_provisional_count": auto_send_with_provisional_count,
        "case_sequence": [f"{trace.case_uid}:{trace.turn_index}" for trace in traces],
        "sampled_case_count": len({trace.case_uid for trace in traces}),
    })


def _provisional_inventory(db) -> dict[str, Any]:
    rows = db.query(AIProvisionalKnowledge).filter(
        AIProvisionalKnowledge.usable_for_eval == True,  # noqa: E712
        AIProvisionalKnowledge.usable_for_auto_send == False,  # noqa: E712
    ).all()
    with_identity = [
        row for row in rows
        if sanitize_text(row.i_id) or sanitize_text(row.sku_code) or row.kb_product_id
    ]
    return {
        "provisional_available_count": len(rows),
        "provisional_with_identity_count": len(with_identity),
        "provisional_without_identity_count": len(rows) - len(with_identity),
    }


def _delta(left: int, right: int) -> dict[str, int]:
    return {"verified_only": int(left), "verified_plus_ai_prefill": int(right), "delta": int(right) - int(left)}


def compare_modes(
    run_uid: str = "",
    sample_limit: int = 50,
    provisional_run_uid: str = "",
    *,
    verified_only_json: str = "",
    verified_plus_ai_prefill_json: str = "",
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        verified_uid = sanitize_text(run_uid) or _run_uid_from_json(verified_only_json) or _latest_run_uid(db)
        provisional_uid = sanitize_text(provisional_run_uid) or _run_uid_from_json(verified_plus_ai_prefill_json)
        inventory = _provisional_inventory(db)
        verified = summarize_run(db, verified_uid, sample_limit)
        if not provisional_uid:
            return sanitize_obj({
                "run_uid": verified_uid,
                "sampled_turns": verified["sampled_turns"],
                "verified_only": verified,
                "verified_plus_ai_prefill": {
                    **inventory,
                    "note": "Pass --provisional-run-uid or --verified-plus-ai-prefill to compare a provisional replay run.",
                },
            })
        provisional = summarize_run(db, provisional_uid, sample_limit)
        compared_trace_count = max(verified["sampled_turns"], provisional["sampled_turns"])
        raw_verified = _raw_replay_counts_from_json(verified_only_json)
        raw_provisional = _raw_replay_counts_from_json(verified_plus_ai_prefill_json)
        return sanitize_obj({
            "summary": {
                "run_uid_verified_only": verified_uid,
                "run_uid_verified_plus_ai_prefill": provisional_uid,
                "same_case_sequence": verified["case_sequence"] == provisional["case_sequence"],
                "compared_trace_count": compared_trace_count,
                "compared_turn_count": compared_trace_count,
                "compared_case_count": max(verified["sampled_case_count"], provisional["sampled_case_count"]),
                "raw_replay_total_turns_verified_only": raw_verified["total_turns"],
                "raw_replay_total_turns_verified_plus_ai_prefill": raw_provisional["total_turns"],
                "raw_replay_total_cases_verified_only": raw_verified["total_cases"],
                "raw_replay_total_cases_verified_plus_ai_prefill": raw_provisional["total_cases"],
                "total_turns_deprecated": compared_trace_count,
                "total_turns_deprecated_note": (
                    "Deprecated: this is the compared sample trace count, "
                    "not the raw replay total turns."
                ),
                "passed": _delta(verified["passed_count"], provisional["passed_count"]),
                "failed": _delta(verified["failed_count"], provisional["failed_count"]),
                "auto_sendable": _delta(
                    verified["quality_bucket_counts"].get("auto_sendable", 0),
                    provisional["quality_bucket_counts"].get("auto_sendable", 0),
                ),
                "knowledge_gap": _delta(
                    verified["quality_bucket_counts"].get("knowledge_gap", 0),
                    provisional["quality_bucket_counts"].get("knowledge_gap", 0),
                ),
                "context_gap": _delta(
                    verified["quality_bucket_counts"].get("context_gap", 0),
                    provisional["quality_bucket_counts"].get("context_gap", 0),
                ),
                "safe_handoff": _delta(
                    verified["quality_bucket_counts"].get("safe_handoff", 0),
                    provisional["quality_bucket_counts"].get("safe_handoff", 0),
                ),
                "agent_error": _delta(
                    verified["quality_bucket_counts"].get("agent_error", 0),
                    provisional["quality_bucket_counts"].get("agent_error", 0),
                ),
                "rag_miss": _delta(
                    verified["failure_type_counts"].get("rag_miss", 0),
                    provisional["failure_type_counts"].get("rag_miss", 0),
                ),
                "needs_human_review": _delta(
                    verified["failure_type_counts"].get("needs_human_review", 0),
                    provisional["failure_type_counts"].get("needs_human_review", 0),
                ),
                **inventory,
                "provisional_used_turn_count": provisional["provisional_used_turn_count"],
                "provisional_used_evidence_count": provisional["provisional_used_evidence_count"],
                "provisional_used_draft_count": provisional["provisional_used_draft_count"],
                "auto_send_with_provisional_count": provisional["auto_send_with_provisional_count"],
            },
            "verified_only": verified,
            "verified_plus_ai_prefill": provisional,
            "provisional_used_turns": provisional["provisional_used_turns"],
        })
    finally:
        db.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare verified-only and provisional eval knowledge modes.")
    parser.add_argument("--run-uid", default="", help="Verified-only/baseline run uid.")
    parser.add_argument("--provisional-run-uid", default="", help="Verified-plus-ai-prefill run uid.")
    parser.add_argument("--verified-only", default="", help="JSON output from verified_only replay.")
    parser.add_argument("--verified-plus-ai-prefill", default="", help="JSON output from verified_plus_ai_prefill replay.")
    parser.add_argument("--sample-limit", type=int, default=50)
    parser.add_argument("--json-output", "--output", dest="json_output", default="")
    args = parser.parse_args()
    init_db()
    result = compare_modes(
        args.run_uid,
        args.sample_limit,
        args.provisional_run_uid,
        verified_only_json=args.verified_only,
        verified_plus_ai_prefill_json=args.verified_plus_ai_prefill,
    )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
