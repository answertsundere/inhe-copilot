"""Compare replay trace answerability between verified and provisional modes.

The script is read-only. It can summarize one run, or compare a verified-only
run against a verified-plus-ai-prefill run when both run ids are provided.
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

from app.db import SessionLocal, init_db
from app.models.eval_tables import EvalRun, EvalTrace
from app.services.ai_provisional_knowledge_service import _fact_type_aliases
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _load_traces(db, run_uid: str, sample_limit: int) -> list[EvalTrace]:
    return (
        db.query(EvalTrace)
        .filter(EvalTrace.run_uid == run_uid)
        .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
        .limit(max(1, int(sample_limit or 50)))
        .all()
    )


def _pack_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    evidence_debug = raw.get("evidence_debug") if isinstance(raw.get("evidence_debug"), dict) else {}
    summary = evidence_debug.get("product_context_pack_summary") if isinstance(evidence_debug.get("product_context_pack_summary"), dict) else {}
    pack = summary.get("evidence_pack") if isinstance(summary.get("evidence_pack"), dict) else {}
    if pack:
        return pack
    pack = raw.get("product_first_evidence_pack") if isinstance(raw.get("product_first_evidence_pack"), dict) else {}
    return pack


def _identity_from_pack(pack: dict[str, Any]) -> dict[str, Any]:
    identity = pack.get("resolved_product_identity") if isinstance(pack.get("resolved_product_identity"), dict) else {}
    return {
        "i_id": sanitize_text(identity.get("i_id") or identity.get("item_id") or ""),
        "sku_code": sanitize_text(identity.get("sku") or identity.get("sku_code") or ""),
        "kb_product_id": identity.get("product_id") or identity.get("kb_product_id"),
        "identity_sources": identity.get("identity_sources") or [],
        "identity_status": "resolved" if (identity.get("i_id") or identity.get("sku") or identity.get("product_id")) else "",
    }


def _truthy_provisional(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    return bool(
        item.get("provisional_knowledge_used")
        or item.get("provisional_draft_uid")
        or item.get("source_table") == "ai_provisional_knowledge"
        or item.get("protocol_source_type") == "ai_prefill"
    )


def _identity_sources(item: dict[str, Any], pack_identity: dict[str, Any]) -> list[str]:
    raw = item.get("identity_sources")
    if not raw and isinstance(item.get("metadata"), dict):
        raw = item["metadata"].get("identity_sources")
    if not raw:
        raw = pack_identity.get("identity_sources") or []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [sanitize_text(value) for value in raw if sanitize_text(value)]
    return []


def _provisional_evidence_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    pack_identity = _identity_from_pack(pack)
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for list_name in ("ai_provisional_knowledge", "matched_facts", "product_scoped_chunks"):
        values = pack.get(list_name)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict) or not _truthy_provisional(item):
                continue
            draft_uid = sanitize_text(
                item.get("provisional_draft_uid")
                or item.get("source_id")
                or item.get("evidence_id")
                or item.get("entry_id")
                or item.get("chunk_id")
            )
            key = draft_uid or json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            i_id = sanitize_text(item.get("i_id") or metadata.get("i_id") or pack_identity.get("i_id"))
            sku_code = sanitize_text(item.get("sku_code") or item.get("sku") or metadata.get("sku_code") or pack_identity.get("sku_code"))
            kb_product_id = item.get("kb_product_id") or metadata.get("kb_product_id") or pack_identity.get("kb_product_id")
            identity_status = sanitize_text(item.get("identity_status") or metadata.get("identity_status") or pack_identity.get("identity_status"))
            if not identity_status and (i_id or sku_code or kb_product_id):
                identity_status = "resolved"
            result.append(sanitize_obj({
                "provisional_draft_uid": draft_uid,
                "i_id": i_id,
                "sku_code": sku_code,
                "kb_product_id": kb_product_id,
                "identity_sources": _identity_sources(item, pack_identity),
                "identity_status": identity_status,
                "query_fact_type": sanitize_text(item.get("fact_type") or item.get("evidence_fact_type")),
                "verification_status": sanitize_text(item.get("verification_status") or metadata.get("verification_status")),
                "usable_for_eval": bool(item.get("usable_for_eval") if item.get("usable_for_eval") is not None else metadata.get("usable_for_eval")),
                "usable_for_auto_send": bool(item.get("usable_for_auto_send") or metadata.get("usable_for_auto_send")),
                "needs_human_review": bool(item.get("needs_human_review")),
                "source_list": list_name,
            }))
    return result


def _has_provisional_used(raw: dict[str, Any]) -> bool:
    return bool(_provisional_evidence_from_pack(_pack_from_raw(raw)))


def summarize_run(db, run_uid: str, sample_limit: int = 50) -> dict[str, Any]:
    traces = _load_traces(db, run_uid, sample_limit)
    buckets = Counter()
    failures = Counter()
    query_fact_types = Counter()
    answer_sources = Counter()
    passed_count = 0
    failed_count = 0
    provisional_used_turns: list[dict[str, Any]] = []
    provisional_used_evidence_count = 0
    auto_send_with_provisional_count = 0
    for trace in traces:
        raw = trace.get_raw_response() or {}
        if trace.passed:
            passed_count += 1
        else:
            failed_count += 1
        bucket = raw.get("quality_bucket") if isinstance(raw, dict) else {}
        if isinstance(bucket, dict):
            buckets[bucket.get("quality_bucket") or "unknown"] += 1
        for label in trace.get_failure_labels() or []:
            failures[label] += 1
        if trace.query_fact_type:
            query_fact_types[trace.query_fact_type] += 1
        answer_trace = trace.get_answer_trace() or {}
        source = answer_trace.get("final_answer_source") or answer_trace.get("selected_evidence_role") or ""
        if source:
            answer_sources[source] += 1
        pack = _pack_from_raw(raw)
        provisional_evidence = _provisional_evidence_from_pack(pack)
        if provisional_evidence:
            provisional_used_evidence_count += len(provisional_evidence)
            reply_delivery = raw.get("reply_delivery") if isinstance(raw.get("reply_delivery"), dict) else {}
            can_send = bool(raw.get("can_send"))
            auto_ready = bool(reply_delivery.get("auto_send_ready"))
            if auto_ready:
                auto_send_with_provisional_count += 1
            provisional_used_turns.append(sanitize_obj({
                "case_uid": trace.case_uid,
                "turn_uid": trace.turn_uid,
                "buyer_message_preview": sanitize_text(trace.buyer_message)[:120],
                "query_fact_type": trace.query_fact_type,
                "provisional_evidence": provisional_evidence,
                "can_send": can_send,
                "sendable_reply_empty": not bool(sanitize_text(raw.get("sendable_reply"))),
                "reply_delivery_auto_send_ready": auto_ready,
                "requires_human_review": bool(trace.requires_human_review or raw.get("requires_human_review")),
                "quality_bucket": bucket.get("quality_bucket") if isinstance(bucket, dict) else "",
                "failure_labels": trace.get_failure_labels() or [],
            }))
    return sanitize_obj({
        "run_uid": run_uid,
        "sampled_turns": len(traces),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "quality_bucket_counts": dict(buckets),
        "failure_type_counts": dict(failures),
        "query_fact_type_counts": dict(query_fact_types),
        "answer_source_counts": dict(answer_sources),
        "provisional_used_count": len(provisional_used_turns),
        "provisional_used_turn_count": len(provisional_used_turns),
        "provisional_used_evidence_count": provisional_used_evidence_count,
        "provisional_used_turns": provisional_used_turns,
        "auto_send_with_provisional_count": auto_send_with_provisional_count,
        "case_sequence": [f"{trace.case_uid}:{trace.turn_index}" for trace in traces],
    })


def _provisional_inventory(db) -> dict[str, Any]:
    from app.models.eval_tables import AIProvisionalKnowledge

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


def compare_modes(run_uid: str = "", sample_limit: int = 50, provisional_run_uid: str = "") -> dict[str, Any]:
    db = SessionLocal()
    try:
        verified_uid = sanitize_text(run_uid) or _latest_run_uid(db)
        provisional_uid = sanitize_text(provisional_run_uid)
        inventory = _provisional_inventory(db)
        verified = summarize_run(db, verified_uid, sample_limit)
        if not provisional_uid:
            return sanitize_obj({
                "run_uid": verified_uid,
                "sampled_turns": verified["sampled_turns"],
                "verified_only": {
                    "quality_bucket_counts": verified["quality_bucket_counts"],
                    "failure_type_counts": verified["failure_type_counts"],
                    "query_fact_type_counts": verified["query_fact_type_counts"],
                    "answer_source_counts": verified["answer_source_counts"],
                },
                "verified_plus_ai_prefill": {
                    **inventory,
                    "provisional_used_count": verified["provisional_used_count"],
                    "provisional_used_turn_count": verified["provisional_used_turn_count"],
                    "provisional_used_evidence_count": verified["provisional_used_evidence_count"],
                    "auto_send_with_provisional_count": verified["auto_send_with_provisional_count"],
                    "provisional_used_turns": verified["provisional_used_turns"],
                    "note": "Pass --provisional-run-uid to compare against a separate verified_plus_ai_prefill replay run.",
                },
            })
        provisional = summarize_run(db, provisional_uid, sample_limit)
        return sanitize_obj({
            "summary": {
                "run_uid_verified_only": verified_uid,
                "run_uid_verified_plus_ai_prefill": provisional_uid,
                "same_case_sequence": verified["case_sequence"] == provisional["case_sequence"],
                "total_turns": max(verified["sampled_turns"], provisional["sampled_turns"]),
                "passed": _delta(
                    verified["passed_count"],
                    provisional["passed_count"],
                ),
                "failed": _delta(
                    verified["failed_count"],
                    provisional["failed_count"],
                ),
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
                "provisional_used_count": provisional["provisional_used_count"],
                "provisional_used_turn_count": provisional["provisional_used_turn_count"],
                "provisional_used_evidence_count": provisional["provisional_used_evidence_count"],
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
    parser.add_argument("--sample-limit", type=int, default=50)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    init_db()
    result = compare_modes(args.run_uid, args.sample_limit, args.provisional_run_uid)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
