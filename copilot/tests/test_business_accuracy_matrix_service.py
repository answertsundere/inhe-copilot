from __future__ import annotations

from app.services.business_accuracy_matrix_service import (
    BUSINESS_DOMAINS,
    build_business_accuracy_matrix,
    business_domain,
    classify_failure,
)


def test_domain_mapping_uses_structured_fact_type_not_customer_text():
    assert business_domain("dimensions") == "product_specification"
    assert business_domain("installation") == "installation_structure_accessory"
    assert business_domain("\u552e\u540e") == "aftersales"
    assert business_domain("not-a-known-fact") == "unclassified"


def test_matrix_keeps_real_gold_real_derived_and_synthetic_separate():
    gold = {
        "dataset_status": "insufficient_gold_labels",
        "summary": {"total_cases": 1},
        "cases": [{
            "query_class": "dimensions", "classification": "claim_label_pending", "sidecar_present": True,
            "reference_label": {"expected_claims": []},
        }],
    }
    baseline = {"summary": {"claim_accuracy_numerator": 0, "claim_accuracy_denominator": 0}, "results": []}
    tier_b = {"results": [{
        "query_fact_type": "gross_weight", "sidecar_present": True, "expected_direct_evidence": True,
        "formal_selected_evidence_count": 1, "admitted_evidence_count": 1,
        "selected_requested_fact": True, "admitted_requested_fact": True,
        "agent_reply_present": True, "passed": True,
    }]}
    smoke = {"total": 1, "passed": 1, "per_scenario_result": [{"query_fact_type": "installation", "passed": True, "requires_human_review": True, "can_send": False}]}
    full = {"total": 2, "passed": 2, "per_scenario_result": [{"query_fact_type": "material_safety", "passed": True, "requires_human_review": True, "can_send": False}]}

    report = build_business_accuracy_matrix(
        tier_a_dataset=gold,
        tier_a_baseline=baseline,
        tier_b_report=tier_b,
        tier_c_smoke=smoke,
        tier_c_full=full,
        runtime={"runtime_commit": "test"},
    )

    assert report["tiers_are_non_combinable"] is True
    assert report["tier_a_real_gold"]["status"] == "insufficient_gold_labels"
    assert report["tier_a_real_gold"]["claim_accuracy"]["rate"] is None
    assert report["tier_b_real_derived_capability"]["case_count"] == 1
    assert report["tier_b_real_derived_capability"]["metrics"]["empty_reply_count"] == 0
    assert report["tier_b_real_derived_capability"]["metrics"]["evidence_citation_rate"]["rate"] == 1.0
    assert report["tier_c_synthetic_safety"]["full"]["executed"] == 2
    assert "database_path" not in report["tier_c_synthetic_safety"]["full"]["dataset"]
    assert [item["scenario_domain"] for item in report["business_domains"]] == list(BUSINESS_DOMAINS)
    product = next(item for item in report["business_domains"] if item["scenario_domain"] == "product_specification")
    assert product["tier_counts"]["real_gold"] == 1
    assert product["tier_counts"]["real_derived"] == 1


def test_failure_classification_prefers_earliest_observable_gap():
    assert classify_failure({"error": "TimeoutError"}) == "timeout_or_runtime_error"
    assert classify_failure({"sidecar_present": False}) == "context_gap"
    assert classify_failure({"identity_matched": False}) == "product_identity_gap"
    assert classify_failure({"expected_direct_evidence": True, "formal_selected_evidence_count": 0}) == "evidence_admission_gap"
    assert classify_failure({"expected_direct_evidence": True, "formal_selected_evidence_count": 1, "admitted_evidence_count": 0}) == "evidence_admission_gap"
