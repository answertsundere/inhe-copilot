"""Diagnose the latest real-conversation replay failures.

The script is read-only. It summarizes the latest real-conversation EvalRun,
prints top failure samples, and groups recommendations by generic replay fields
instead of buyer text, product names, SKUs, orders, or fixed sample IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.db import SessionLocal  # noqa: E402
from app.models.eval_tables import EvalFailure, EvalRun, EvalTrace  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402


AGENT_ERROR = "agent_error"
KNOWLEDGE_GAP = "knowledge_gap"
CONTEXT_GAP = "context_gap"
SAFE_HANDOFF = "safe_handoff"

PRIORITY_BUCKETS = {
    AGENT_ERROR: 0,
    KNOWLEDGE_GAP: 1,
    CONTEXT_GAP: 2,
    SAFE_HANDOFF: 3,
}

MEDIA_FACT_TYPES = {"installation", "accessory_usage", "media_asset", "video", "image"}
POLICY_FACT_TYPES = {"aftersales", "aftersales_policy", "promotion_policy", "activity_rules"}
ORDER_FACT_TYPES = {"logistics", "delivery_not_received", "order_status", "aftersales", "aftersales_policy"}


def _count(values) -> dict[str, int]:
    counter = Counter(str(value or "unknown") for value in values)
    return dict(counter.most_common())


def _safe_json(value: Any) -> str:
    return json.dumps(sanitize_obj(value), ensure_ascii=False, indent=2)


def _quality_bucket(trace: EvalTrace) -> str:
    quality = trace.get_quality_bucket() or {}
    return sanitize_text(quality.get("quality_bucket")) or ("auto_sendable" if trace.passed else AGENT_ERROR)


def _failure_labels(trace: EvalTrace, failures: list[EvalFailure]) -> list[str]:
    labels = list(trace.get_failure_labels() or [])
    labels.extend(failure.failure_type for failure in failures)
    return sorted({sanitize_text(label) for label in labels if sanitize_text(label)})


def _failure_dicts(failures: list[EvalFailure]) -> list[dict[str, Any]]:
    return [failure.to_dict() for failure in failures]


def _answer_trace_summary(answer_trace: dict[str, Any]) -> dict[str, Any]:
    return sanitize_obj({
        "query_fact_type": answer_trace.get("query_fact_type", ""),
        "required_fact_types": answer_trace.get("required_fact_types", []),
        "evidence_answered_fact_types": answer_trace.get("evidence_answered_fact_types", []),
        "rag_evidence_used": answer_trace.get("rag_evidence_used", {}),
        "mode": answer_trace.get("mode", ""),
        "block_reasons": answer_trace.get("block_reasons", []),
        "final_audit": answer_trace.get("final_audit", {}),
    })


def _has_media_context(trace: EvalTrace) -> bool:
    answer_trace = trace.get_answer_trace() or {}
    media = answer_trace.get("conversation_media_reference")
    if isinstance(media, dict):
        return int(media.get("media_context_count") or 0) > 0
    raw = trace.get_raw_response() or {}
    return bool(raw.get("conversation_media_context") or raw.get("recommended_assets"))


def _context_flags(trace: EvalTrace) -> dict[str, bool]:
    product_identity = trace.get_product_identity() or {}
    return {
        "has_product_context": any(bool(value) for value in product_identity.values()),
        "has_order_context": bool(sanitize_text(trace.order_identity_hash)),
        "has_media_context": _has_media_context(trace),
    }


def infer_engineering_module(
    *,
    quality_bucket: str,
    failure_labels: list[str],
    failures: list[dict[str, Any]],
    turn_understanding: dict[str, Any],
    answer_trace: dict[str, Any],
    selected_evidence_count: int,
    context_flags: dict[str, bool],
) -> str:
    labels = set(failure_labels)
    expected = sanitize_text(
        turn_understanding.get("expected_query_fact_type")
        or turn_understanding.get("effective_query_fact_type")
        or turn_understanding.get("query_fact_type")
        or answer_trace.get("query_fact_type")
    )
    fix_areas = {
        sanitize_text(failure.get("suggested_fix_area"))
        for failure in failures
        if sanitize_text(failure.get("suggested_fix_area"))
    }
    if labels & {"turn_understanding_missing", "encoding_corruption"}:
        return "turn_understanding"
    if "intent_contract_mismatch" in labels or "query_fact_type_missing" in labels:
        return "final_gate"
    if "wrong_topic_reply" in labels or "semantic_mismatch" in labels:
        return "final_gate"
    if "unrequested_product_fact" in labels or "generic_reply_to_actionable_issue" in labels:
        return "answer_policy"
    if "evidence_misuse" in labels:
        return "evidence_rerank"
    if "unsupported_media_claim" in labels:
        return "data_gap_media_asset"
    if "tool_policy_blocked" in labels:
        return "human_policy_boundary"
    if quality_bucket == CONTEXT_GAP or labels & {"context_gap", "context_insufficient"}:
        if expected in ORDER_FACT_TYPES and not context_flags.get("has_order_context"):
            return "order_context"
        if not context_flags.get("has_product_context"):
            return "product_identity"
        return "context_extractor"
    if "no_product_identified" in labels:
        return "product_identity"
    if "rag_miss" in labels:
        if expected in MEDIA_FACT_TYPES or fix_areas & {"media_ops", "media_pipeline"}:
            return "data_gap_media_asset"
        if expected in POLICY_FACT_TYPES or fix_areas & {"sop_policy", "activity_rule"}:
            return "data_gap_policy_rule"
        if selected_evidence_count == 0:
            return "rag_retrieval"
        return "data_gap_product_field"
    if quality_bucket == SAFE_HANDOFF:
        return "human_policy_boundary"
    return "answer_policy"


def _recommended_fix(module: str, failure_type: str, query_fact_type: str) -> tuple[str, str]:
    if module == "turn_understanding":
        return (
            "Strengthen turn understanding rules or semantic contract for this actionability/fact type.",
            "code_fix",
        )
    if module == "context_extractor":
        return (
            "Extract and pass structured real conversation context before calling Agent; do not rely on buyer text only.",
            "code_fix",
        )
    if module == "product_identity":
        return (
            "Improve product context extraction from conversation metadata/product cards before RAG retrieval.",
            "code_fix",
        )
    if module == "order_context":
        return (
            "Extract order/logistics context into hashed order fields and pass it through copilot_context.",
            "code_fix",
        )
    if module == "rag_retrieval":
        return (
            f"Review retrieval scope and fact-type routing for {query_fact_type or 'unknown'}; keep failures visible if evidence is absent.",
            "code_fix",
        )
    if module == "evidence_rerank":
        return (
            "Tune evidence rerank/direct vs supporting evidence selection for the required fact type.",
            "code_fix",
        )
    if module == "answer_policy":
        return (
            "Tighten no-evidence and wrong-topic answer policy using existing product/order context and turn contract.",
            "code_fix",
        )
    if module == "final_gate":
        return (
            "Enforce expected vs actual query_fact_type and final semantic topics before marking replay passed.",
            "code_fix",
        )
    if module == "data_gap_media_asset":
        return (
            "Route missing installation/video/image evidence to media asset governance; do not invent media in Agent replies.",
            "data_fix",
        )
    if module == "data_gap_policy_rule":
        return (
            "Route missing aftersales/promotion/activity policy to operations policy governance.",
            "data_fix",
        )
    if module == "human_policy_boundary":
        return (
            "Keep human handoff for risk/policy boundary until operations defines safe automation rules.",
            "policy_fix",
        )
    return ("Review trace and repair task details before code changes.", "manual_triage")


def _expected_impact(count: int, total_failed: int) -> str:
    if total_failed <= 0:
        return "unknown"
    share = count / total_failed
    if share >= 0.25:
        return "high"
    if share >= 0.1:
        return "medium"
    return "low"


def _sample_record(trace: EvalTrace, failures: list[EvalFailure]) -> dict[str, Any]:
    understanding = trace.get_turn_understanding() or {}
    answer_trace = trace.get_answer_trace() or {}
    failure_dicts = _failure_dicts(failures)
    labels = _failure_labels(trace, failures)
    quality_bucket = _quality_bucket(trace)
    context_flags = _context_flags(trace)
    selected_evidence = trace.get_selected_evidence() or []
    module = infer_engineering_module(
        quality_bucket=quality_bucket,
        failure_labels=labels,
        failures=failure_dicts,
        turn_understanding=understanding,
        answer_trace=answer_trace,
        selected_evidence_count=len(selected_evidence),
        context_flags=context_flags,
    )
    block_reasons = []
    for failure in failure_dicts:
        if failure.get("message"):
            block_reasons.append(failure.get("message"))
    block_reasons.extend(answer_trace.get("block_reasons") or [])
    return sanitize_obj({
        "case_uid": trace.case_uid,
        "turn_uid": trace.turn_uid,
        "customer_message": trace.buyer_message,
        "original_csr_reply": trace.reference_human_reply,
        "agent_reply": trace.agent_reply,
        "quality_bucket": quality_bucket,
        "module": module,
        "failure_labels": labels,
        "failure_types": [failure.failure_type for failure in failures],
        "query_fact_type": trace.query_fact_type,
        "expected_query_fact_type": understanding.get("expected_query_fact_type") or understanding.get("query_fact_type", ""),
        "actual_query_fact_type": understanding.get("actual_query_fact_type") or answer_trace.get("query_fact_type", ""),
        "turn_actionability": understanding.get("turn_actionability", ""),
        **context_flags,
        "selected_evidence_count": len(selected_evidence),
        "rag_evidence_used": answer_trace.get("rag_evidence_used", {}),
        "block_reasons": block_reasons,
        "suggested_fix_area": sorted({failure.suggested_fix_area for failure in failures if failure.suggested_fix_area}),
        "answer_trace": _answer_trace_summary(answer_trace),
    })


def _recommendations(samples: list[dict[str, Any]], total_failed: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        failure_type = ",".join(sample.get("failure_labels") or sample.get("failure_types") or ["unknown"])
        key = (
            sanitize_text(sample.get("module")) or "unknown",
            failure_type or "unknown",
            sanitize_text(sample.get("query_fact_type")) or sanitize_text(sample.get("expected_query_fact_type")) or "unknown",
        )
        groups[key].append(sample)
    result = []
    for (module, failure_type, fact_type), group in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True):
        fix, fix_kind = _recommended_fix(module, failure_type, fact_type)
        result.append(sanitize_obj({
            "module": module,
            "failure_type": failure_type,
            "query_fact_type": fact_type,
            "count": len(group),
            "representative_samples": [
                {
                    "case_uid": sample["case_uid"],
                    "turn_uid": sample["turn_uid"],
                    "quality_bucket": sample["quality_bucket"],
                    "failure_labels": sample["failure_labels"],
                }
                for sample in group[:3]
            ],
            "recommended_fix": fix,
            "expected_impact": _expected_impact(len(group), total_failed),
            "whether_code_fix_or_data_fix": fix_kind,
        }))
    return result


def diagnose_latest_run(limit: int = 20, run_uid: str = "") -> dict[str, Any]:
    db = SessionLocal()
    try:
        query = db.query(EvalRun).filter(EvalRun.source_type == "real_conversation")
        if run_uid:
            query = query.filter(EvalRun.run_uid == sanitize_text(run_uid))
        run = query.order_by(EvalRun.created_at.desc(), EvalRun.id.desc()).first()
        if run is None:
            return {"ok": False, "error": "no real_conversation eval run found"}

        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == run.run_uid)
            .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            .all()
        )
        failures = db.query(EvalFailure).filter(EvalFailure.run_uid == run.run_uid).all()
        failures_by_turn: dict[str, list[EvalFailure]] = defaultdict(list)
        for failure in failures:
            failures_by_turn[failure.turn_uid].append(failure)

        def counts_in_quality(trace: EvalTrace) -> bool:
            quality = trace.get_quality_bucket() or {}
            return quality.get("should_count_in_quality_rate") is not False

        failed_traces = [
            trace
            for trace in traces
            if counts_in_quality(trace) and (not trace.passed or _failure_labels(trace, failures_by_turn.get(trace.turn_uid, [])))
        ]
        records = [_sample_record(trace, failures_by_turn.get(trace.turn_uid, [])) for trace in failed_traces]
        records.sort(key=lambda sample: (
            PRIORITY_BUCKETS.get(sample.get("quality_bucket"), 9),
            0 if sample.get("failure_labels") else 1,
            sample.get("turn_uid", ""),
        ))
        top_samples = records[: max(1, limit)]
        total_failed = len(failed_traces)
        summary = {
            "run_uid": run.run_uid,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "trace_count": len(traces),
            "total_turns": run.total_turns or sum(1 for trace in traces if counts_in_quality(trace)),
            "passed_turns": run.passed_turns or sum(1 for trace in traces if counts_in_quality(trace) and trace.passed),
            "failed_turns": run.failed_turns or total_failed,
            "unscored_or_noise_turns": sum(1 for trace in traces if _quality_bucket(trace) == "unscored_or_noise"),
            "context_gap_turns": sum(1 for trace in traces if _quality_bucket(trace) == "context_gap"),
            "quality_bucket_distribution": _count(_quality_bucket(trace) for trace in traces),
            "failure_type_distribution": _count(
                label
                for trace in failed_traces
                for label in _failure_labels(trace, failures_by_turn.get(trace.turn_uid, []))
            ),
            "query_fact_type_distribution": _count(trace.query_fact_type for trace in traces),
            "suggested_fix_area_distribution": _count(
                failure.suggested_fix_area or "unknown"
                for failure in failures
                if failure.turn_uid in {trace.turn_uid for trace in failed_traces}
            ),
        }
        recommendations = _recommendations(records, total_failed)
        return sanitize_obj({
            "ok": True,
            "summary": summary,
            "top_samples": top_samples,
            "top_recommendations": recommendations[:20],
        })
    finally:
        db.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Diagnose latest real conversation replay failures.")
    parser.add_argument("--limit", type=int, default=20, help="Top failed turn samples to print.")
    parser.add_argument("--run-uid", default="", help="Optional specific real_conversation run_uid.")
    parser.add_argument("--json-output", default="", help="Optional sanitized JSON output path.")
    args = parser.parse_args()

    result = diagnose_latest_run(limit=args.limit, run_uid=args.run_uid)
    print(_safe_json(result))
    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as fh:
            fh.write(_safe_json(result))
            fh.write("\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
