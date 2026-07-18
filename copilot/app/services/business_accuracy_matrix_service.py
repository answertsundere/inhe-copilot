"""Versioned, non-combined reporting for customer-service accuracy evidence.

This module is evaluation-only.  It consumes sanitised reports produced by the
Gold Set, real-derived capability runner, and synthetic benchmark runner.  It
does not import the Agent, create knowledge, or decide a customer reply.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


MATRIX_SCHEMA_VERSION = "business-accuracy-matrix-v1"
DATASET_TIERS = ("real_gold", "real_derived", "synthetic_safety")
BUSINESS_DOMAINS = (
    "product_specification",
    "space_fit_inference",
    "installation_structure_accessory",
    "logistics_order",
    "aftersales",
    "promotion_gift_invoice",
    "media_delivery",
    "high_risk_product",
    "multi_turn_context",
)

_DOMAIN_BY_FACT_TYPE = {
    "dimensions": "product_specification",
    "gross_weight": "product_specification",
    "material": "product_specification",
    "material_composition": "product_specification",
    "detachable": "product_specification",
    "structure_function": "product_specification",
    "space_fit": "space_fit_inference",
    "placement_scene": "space_fit_inference",
    "installation": "installation_structure_accessory",
    "accessory_usage": "installation_structure_accessory",
    "accessory_availability": "installation_structure_accessory",
    "logistics": "logistics_order",
    "order_status": "logistics_order",
    "address_change": "logistics_order",
    "aftersales": "aftersales",
    "missing_parts": "aftersales",
    "damage": "aftersales",
    "refund": "aftersales",
    "replacement": "aftersales",
    "promotion": "promotion_gift_invoice",
    "gift_policy": "promotion_gift_invoice",
    "invoice": "promotion_gift_invoice",
    "price_negotiation": "promotion_gift_invoice",
    "media_request": "media_delivery",
    "installation_video": "media_delivery",
    "material_safety": "high_risk_product",
    "bite_or_toxicity": "high_risk_product",
    "load_capacity": "high_risk_product",
    "certification_report": "high_risk_product",
    "food_grade": "high_risk_product",
    "child_suitability": "high_risk_product",
    "child_safety": "high_risk_product",
    "age_range": "high_risk_product",
    "conversation_followup": "multi_turn_context",
    "context_followup": "multi_turn_context",
}
_DOMAIN_BY_EVALUATION_CLASS = {
    "\u5c3a\u5bf8": "product_specification",
    "\u5b89\u88c5": "installation_structure_accessory",
    "\u7269\u6d41": "logistics_order",
    "\u552e\u540e": "aftersales",
    "\u6d3b\u52a8": "promotion_gift_invoice",
    "\u6750\u8d28\u5b89\u5168": "high_risk_product",
    "\u5e74\u9f84\u9002\u914d": "high_risk_product",
    "\u8d28\u68c0": "high_risk_product",
}


def business_domain(query_fact_type: Any) -> str:
    """Map canonical evaluation metadata to one stable business domain.

    Unknown classifications stay observable instead of being inferred from the
    buyer sentence.  That keeps this report from becoming another intent
    classifier.
    """
    normalized = sanitize_text(query_fact_type).lower()
    return _DOMAIN_BY_FACT_TYPE.get(normalized, _DOMAIN_BY_EVALUATION_CLASS.get(normalized, "unclassified"))


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "rate": round(numerator / denominator, 4) if denominator else None,
    }


def _empty_domain_row(domain: str) -> dict[str, Any]:
    return {
        "scenario_domain": domain,
        "available_sample_count": 0,
        "tier_counts": {tier: 0 for tier in DATASET_TIERS},
        "approved_claim_count": 0,
        "scorable_count": 0,
        "sidecar_complete_count": 0,
        "direct_evidence_count": 0,
        "media_covered_count": 0,
        "service_action_covered_count": 0,
        "not_scorable_reasons": {},
    }


def _domain_rows() -> dict[str, dict[str, Any]]:
    return {domain: _empty_domain_row(domain) for domain in BUSINESS_DOMAINS}


def _add_reason(row: dict[str, Any], reason: str) -> None:
    if not reason:
        return
    reasons = row["not_scorable_reasons"]
    reasons[reason] = int(reasons.get(reason, 0)) + 1


def _metric_rows(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [item for item in results if isinstance(item, dict)]
    scored = [item for item in rows if isinstance(item.get("score"), dict) and item["score"].get("claim_score_available")]
    covered = sum(len(item["score"].get("covered_claim_uids") or []) for item in scored)
    expected = sum(int(item["score"].get("expected_claim_count") or 0) for item in scored)
    forbidden = sum(len(item["score"].get("forbidden_claim_hits") or []) for item in scored)
    successful = [item for item in rows if not item.get("error") and 200 <= int(item.get("status_code") or 0) < 300]
    latencies = sorted(float(item.get("latency_ms") or 0) for item in rows)
    direct_expected = [item for item in rows if item.get("expected_direct_evidence") is True]
    media_expected = [item for item in rows if item.get("expected_media_roles")]
    action_expected = [item for item in rows if item.get("required_action_points")]
    partial_expected = [item for item in rows if item.get("partial_answer_expected") is True]
    role_sets = [
        {sanitize_text(role).lower() for role in item.get("admitted_evidence_roles") or [] if sanitize_text(role)}
        for item in rows
    ]

    def reply_present(item: dict[str, Any]) -> bool:
        if "agent_reply_present" in item:
            return bool(item.get("agent_reply_present"))
        return bool(sanitize_text(item.get("agent_reply")))

    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, round((len(latencies) - 1) * value))], 1)

    return {
        "supported_claim_precision": rate(covered, covered + forbidden),
        "supported_claim_recall": rate(covered, expected),
        "evidence_citation_rate": rate(
            sum(bool(item.get("selected_requested_fact")) for item in direct_expected), len(direct_expected),
        ),
        "evidence_identity_match_rate": rate(
            sum(item.get("identity_matched") is not False for item in direct_expected), len(direct_expected),
        ),
        "real_derived_admission_rate": rate(
            sum(bool(item.get("admitted_requested_fact")) for item in direct_expected), len(direct_expected),
        ),
        "answer_relevance_rate": rate(sum(bool((item.get("score") or {}).get("passed")) for item in scored), len(scored)),
        "requested_claim_completeness_rate": rate(sum(not (item.get("score") or {}).get("missing_claim_uids") for item in scored), len(scored)),
        "partial_answer_preservation_rate": rate(
            sum(not bool(item.get("partial_answer_lost")) for item in partial_expected), len(partial_expected),
        ),
        "generic_handoff_only_rate": rate(
            sum(bool(item.get("generic_handoff_only")) for item in direct_expected), len(direct_expected),
        ),
        "action_point_completion_rate": rate(
            sum(bool(item.get("requires_human_review")) for item in action_expected), len(action_expected),
        ),
        "context_followup_accuracy_rate": rate(
            sum(bool(item.get("context_followup_correct")) for item in rows if "context_followup_correct" in item),
            sum("context_followup_correct" in item for item in rows),
        ),
        "required_media_role_match_rate": rate(
            sum(bool(item.get("media_role_matched")) for item in media_expected), len(media_expected),
        ),
        "unsupported_media_promise_rate": rate(
            sum(bool(item.get("unsupported_media_promise")) for item in rows), len(rows),
        ),
        "media_reference_without_reply_block_count": sum(bool(item.get("media_reference_without_reply_block")) for item in rows),
        "unsafe_auto_send_count": sum(bool(item.get("can_send")) for item in rows if item.get("requires_human_review")),
        "high_risk_unsupported_claim_count": forbidden,
        "requires_human_review_accuracy": rate(
            sum(bool(item.get("requires_human_review")) for item in rows if item.get("expected_must_handoff") is True or (item.get("score") or {}).get("expected_must_handoff") is True),
            sum(item.get("expected_must_handoff") is True or (item.get("score") or {}).get("expected_must_handoff") is True for item in rows),
        ),
        "api_success_rate": rate(len(successful), len(rows)),
        "timeout_count": sum(item.get("error") == "TimeoutError" for item in rows),
        "empty_reply_count": sum(not reply_present(item) for item in rows),
        "service_action_as_product_fact_count": sum(
            bool(roles & {"service_action", "fallback_only", "answer_memory", "media_reference"}) for roles in role_sets
        ),
        "latency_p50_ms": percentile(0.5),
        "latency_p95_ms": percentile(0.95),
    }


def classify_failure(row: dict[str, Any]) -> str:
    """Return the earliest observable evaluation failure without text heuristics."""
    if row.get("error"):
        return "timeout_or_runtime_error"
    if not row.get("sidecar_present", True):
        return "context_gap"
    if row.get("identity_matched") is False:
        return "product_identity_gap"
    if row.get("expected_direct_evidence") and not row.get("formal_selected_evidence_count"):
        return "evidence_admission_gap"
    if row.get("expected_direct_evidence") and not row.get("admitted_evidence_count"):
        return "evidence_admission_gap"
    if row.get("partial_answer_lost"):
        return "partial_answer_loss"
    if row.get("semantic_fallback_lost"):
        return "semantic_fallback_loss"
    if row.get("unsupported_media_promise"):
        return "media_contract_gap"
    if row.get("unsafe_delivery"):
        return "delivery_gate_gap"
    if row.get("service_action_as_product_fact"):
        return "service_action_gap"
    if row.get("score") and not row["score"].get("passed"):
        return "claim_resolution_gap"
    return "eval_data_gap"


def build_business_accuracy_matrix(
    *,
    tier_a_dataset: dict[str, Any],
    tier_a_baseline: dict[str, Any],
    tier_b_report: dict[str, Any],
    tier_c_smoke: dict[str, Any],
    tier_c_full: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one versioned report while keeping all three tiers separate."""
    domain_rows = _domain_rows()
    failure_counts: Counter[str] = Counter()

    for case in tier_a_dataset.get("cases") or []:
        if not isinstance(case, dict):
            continue
        domain = business_domain(case.get("query_class"))
        if domain not in domain_rows:
            continue
        row = domain_rows[domain]
        row["available_sample_count"] += 1
        row["tier_counts"]["real_gold"] += 1
        row["sidecar_complete_count"] += int(bool(case.get("sidecar_present")))
        if case.get("classification") == "claim_accuracy_scorable":
            row["scorable_count"] += 1
            row["approved_claim_count"] += len((case.get("reference_label") or {}).get("expected_claims") or [])
        else:
            _add_reason(row, sanitize_text(case.get("classification")) or "unknown")

    for result in tier_a_baseline.get("results") or []:
        if not isinstance(result, dict):
            continue
        failure_counts[classify_failure(result)] += 1

    for result in tier_b_report.get("results") or []:
        if not isinstance(result, dict):
            continue
        domain = business_domain(result.get("query_fact_type"))
        if domain not in domain_rows:
            continue
        row = domain_rows[domain]
        row["available_sample_count"] += 1
        row["tier_counts"]["real_derived"] += 1
        row["scorable_count"] += 1
        row["sidecar_complete_count"] += int(bool(result.get("sidecar_present")))
        row["direct_evidence_count"] += int(bool(result.get("expected_direct_evidence")))
        row["media_covered_count"] += int(bool(result.get("expected_media_roles")))
        row["service_action_covered_count"] += int(bool(result.get("service_action_expected")))
        if not result.get("passed"):
            failure_counts[classify_failure(result)] += 1

    for report in (tier_c_smoke, tier_c_full):
        for result in report.get("per_scenario_result") or []:
            if not isinstance(result, dict):
                continue
            domain = business_domain(result.get("query_fact_type"))
            if domain in domain_rows:
                row = domain_rows[domain]
                row["available_sample_count"] += 1
                row["tier_counts"]["synthetic_safety"] += 1
                row["sidecar_complete_count"] += int(bool(result.get("sidecar_context")))
            if not result.get("passed"):
                failure_counts["delivery_gate_gap" if result.get("can_send") else "claim_resolution_gap"] += 1

    tier_a_summary = tier_a_baseline.get("summary") or {}
    tier_a_denominator = int(tier_a_summary.get("claim_accuracy_denominator") or 0)
    tier_a_numerator = int(tier_a_summary.get("claim_accuracy_numerator") or 0)
    tier_a_status = "ready_for_accuracy_baseline" if tier_a_dataset.get("dataset_status") == "ready_for_accuracy_baseline" else "insufficient_gold_labels"
    tier_b_results = [item for item in tier_b_report.get("results") or [] if isinstance(item, dict)]
    tier_c_summary = {
        "smoke": _benchmark_summary(tier_c_smoke),
        "full": _benchmark_summary(tier_c_full),
    }
    return sanitize_obj({
        "schema_version": MATRIX_SCHEMA_VERSION,
        "tiers_are_non_combinable": True,
        "runtime": runtime or {},
        "tier_a_real_gold": {
            "status": tier_a_status,
            "claim_accuracy": rate(tier_a_numerator, tier_a_denominator),
            "approved_claim_denominator": tier_a_denominator,
            "metrics": _metric_rows(tier_a_baseline.get("results") or []),
            "dataset_summary": tier_a_dataset.get("summary") or {},
        },
        "tier_b_real_derived_capability": {
            "status": "evaluated" if tier_b_results else "source_coverage_insufficient",
            "case_count": len(tier_b_results),
            "metrics": _metric_rows(tier_b_results),
            "source_snapshot_hash": tier_b_report.get("source_snapshot_hash"),
            "not_a_real_customer_accuracy_rate": True,
        },
        "tier_c_synthetic_safety": {
            **tier_c_summary,
            "not_a_real_customer_accuracy_rate": True,
        },
        "business_domains": [domain_rows[domain] for domain in BUSINESS_DOMAINS],
        "unclassified_domain_count": sum(
            1 for case in tier_a_dataset.get("cases") or []
            if business_domain(case.get("query_class")) == "unclassified"
        ),
        "failure_clusters": dict(sorted(failure_counts.items())),
    })


def _benchmark_summary(report: dict[str, Any]) -> dict[str, Any]:
    total = int(report.get("total") or report.get("total_scenarios") or 0)
    passed = int(report.get("passed") or report.get("passed_count") or 0)
    raw_dataset = report.get("dataset") if isinstance(report.get("dataset"), dict) else {}
    dataset = {
        key: raw_dataset.get(key)
        for key in ("database_source", "dataset_id", "dataset_version", "schema_version", "fixture_sha256", "scenario_count")
        if raw_dataset.get(key) is not None
    }
    return {
        "dataset": dataset,
        "executed": total,
        "passed": passed,
        "failed": max(total - passed, 0),
        "invalid_run": bool(report.get("invalid_run")),
        "requires_human_review_count": sum(
            bool(item.get("requires_human_review"))
            for item in report.get("per_scenario_result") or [] if isinstance(item, dict)
        ),
        "can_send_count": sum(
            bool(item.get("can_send"))
            for item in report.get("per_scenario_result") or [] if isinstance(item, dict)
        ),
        "failure_reasons": report.get("failure_reasons") or {},
    }
