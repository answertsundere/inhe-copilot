"""Trace Grounded Reasoning shadow drafts for reviewed training samples.

This script is diagnostic only. It does not call the Agent, write knowledge, or
change sendability.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import init_db
from app.models.eval_tables import AgentAnswerMemory  # noqa: F401 - register table
from app.services.answer_memory_adapter_service import AnswerMemoryAdapterService
from app.services.answer_memory_service import infer_scenario_type, plain_text
from app.services.eval_sanitizer_service import sanitize_text
from app.services.fact_type_service import classify_query_fact_type
from app.services.grounded_reasoning_draft_service import (
    GroundedReasoningDraftService,
    has_forbidden_claim_violation,
    has_unsupported_media_claim,
    is_generic_handoff_only,
    used_answer_memory_as_fact,
)


def _load_samples(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        for key in ("samples", "items", "data", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


def _selected_evidence_from_sample(sample: dict[str, Any], query_fact_type: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for key, fact_type in (
        ("product_title", "product_identity"),
        ("sku", "sku_code"),
    ):
        value = sanitize_text(sample.get(key))
        if value:
            facts.append(
                {
                    "source_type": "training_sample_context",
                    "fact_type": fact_type,
                    "content": value,
                    "source_type": "training_sample_context",
                    "reference_only": True,
                }
            )
    return facts


def trace_samples(samples: list[dict[str, Any]], *, limit: int = 5000) -> dict[str, Any]:
    memory_service = AnswerMemoryAdapterService()
    grounded_service = GroundedReasoningDraftService()
    rows = []
    generated_count = 0
    skipped_count = 0
    high_risk_count = 0
    requires_human_review_count = 0
    can_change_can_send_count = 0
    used_answer_memory_as_fact_count = 0
    forbidden_claim_violation_count = 0
    unsupported_media_claim_count = 0
    generic_handoff_only_count = 0
    skipped_by_reason: dict[str, int] = {}
    admitted_fact_count = 0
    rejected_evidence_count = 0
    rejected_evidence_by_reason: dict[str, int] = {}
    admission_warning_count = 0
    admission_warnings_by_reason: dict[str, int] = {}
    conflicting_evidence_group_count = 0
    conflict_check_skipped_count = 0
    answer_leakage_count = 0
    requested_attribute_coverage_count = 0
    requested_attribute_source_counts: dict[str, int] = {}

    for sample in samples[: max(1, min(int(limit or 5000), 5000))]:
        question = sanitize_text(plain_text(sample.get("customer_quote")))
        if not question:
            reason = "missing_context"
        elif question.startswith("http"):
            reason = "link_only"
        elif "图片" in question and len(question) <= 8:
            reason = "image_only"
        else:
            reason = ""
        if reason:
            skipped_count += 1
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            rows.append({"sample_id": sample.get("id"), "skipped": True, "skip_reason": reason})
            continue
        fact = classify_query_fact_type(question, intent="")
        query_fact_type = sanitize_text(fact.get("query_fact_type"))
        scenario_type = infer_scenario_type(sample, query_fact_type)
        guidance = memory_service.build_for_context(
            customer_message=question,
            sku_code=sample.get("sku") or "",
            product_title=sample.get("product_title") or "",
            query_fact_type=query_fact_type,
            scenario_type=scenario_type,
        )
        selected_evidence = _selected_evidence_from_sample(sample, query_fact_type)
        draft = grounded_service.build_for_response(
            {
                "query_fact_type": query_fact_type,
                "selected_evidence": selected_evidence,
                "answer_memory_guidance": guidance,
                "evidence_debug": {"query_fact_type": query_fact_type, "selected_evidence": selected_evidence},
                "reply_blocks": [],
                "can_send": False,
                "requires_human_review": True,
            },
            customer_message=question,
            product_identity={
                "product_title": sample.get("product_title") or "",
                "sku_code": sample.get("sku") or "",
                "order_id": sample.get("order_no") or "",
            },
            answer_memory_guidance=guidance,
        )
        generated_count += 1
        if draft.get("risk_level") == "high":
            high_risk_count += 1
        if draft.get("requires_human_review"):
            requires_human_review_count += 1
        if draft.get("can_change_can_send"):
            can_change_can_send_count += 1
        if used_answer_memory_as_fact(draft):
            used_answer_memory_as_fact_count += 1
        if has_forbidden_claim_violation(draft):
            forbidden_claim_violation_count += 1
        if has_unsupported_media_claim(draft, []):
            unsupported_media_claim_count += 1
        if is_generic_handoff_only(draft):
            generic_handoff_only_count += 1
        admitted_fact_count += len(draft.get("used_facts") or [])
        rejected_evidence_count += len(draft.get("rejected_evidence") or [])
        for item in draft.get("rejected_evidence") or []:
            reason = str(item.get("reason") or "unknown")
            rejected_evidence_by_reason[reason] = rejected_evidence_by_reason.get(reason, 0) + 1
        conflict_groups = {
            str(item.get("attribute_key") or "")
            for item in draft.get("rejected_evidence") or []
            if item.get("reason") == "conflicting_evidence" and item.get("attribute_key")
        }
        conflicting_evidence_group_count += len(conflict_groups)
        warnings = draft.get("admission_warnings") or []
        admission_warning_count += len(warnings)
        for item in warnings:
            reason = str(item.get("reason") or "unknown")
            admission_warnings_by_reason[reason] = admission_warnings_by_reason.get(reason, 0) + 1
            if reason == "conflict_check_skipped":
                conflict_check_skipped_count += 1
        if any("correct_answer" in str(item.get("source") or "") for item in draft.get("used_facts") or []):
            answer_leakage_count += 1
        plan = draft.get("fact_coverage_plan") or {}
        requested_keys = plan.get("requested_attribute_keys") or []
        if requested_keys:
            requested_attribute_coverage_count += 1
        source = str(plan.get("requested_attribute_source") or "unavailable")
        requested_attribute_source_counts[source] = requested_attribute_source_counts.get(source, 0) + 1
        rows.append(
            {
                "sample_id": sample.get("id"),
                "query_fact_type": query_fact_type,
                "scenario_type": scenario_type,
                "grounded_reasoning_draft": draft,
            }
        )

    return {
        "total": len(rows),
        "scanned_count": len(samples[: max(1, min(int(limit or 5000), 5000))]),
        "eligible_count": generated_count,
        "generated_count": generated_count,
        "skipped_count": skipped_count,
        "high_risk_count": high_risk_count,
        "requires_human_review_count": requires_human_review_count,
        "can_change_can_send_count": can_change_can_send_count,
        "used_answer_memory_as_fact_count": used_answer_memory_as_fact_count,
        "forbidden_claim_violation_count": forbidden_claim_violation_count,
        "unsupported_media_claim_count": unsupported_media_claim_count,
        "generic_handoff_only_count": generic_handoff_only_count,
        "skipped_by_reason": skipped_by_reason,
        "answer_leakage_count": answer_leakage_count,
        "requested_attribute_coverage_count": requested_attribute_coverage_count,
        "requested_attribute_coverage_rate": round(requested_attribute_coverage_count / generated_count, 4) if generated_count else None,
        "requested_attribute_source_counts": dict(sorted(requested_attribute_source_counts.items())),
        "admitted_fact_count": admitted_fact_count,
        "rejected_evidence_count": rejected_evidence_count,
        "rejected_evidence_by_reason": rejected_evidence_by_reason,
        "admission_warning_count": admission_warning_count,
        "admission_warnings_by_reason": admission_warnings_by_reason,
        "conflicting_evidence_group_count": conflicting_evidence_group_count,
        "conflict_check_skipped_count": conflict_check_skipped_count,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace Grounded Reasoning shadow drafts.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    init_db()
    result = trace_samples(_load_samples(args.input), limit=args.limit)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
