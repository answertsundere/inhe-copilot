from __future__ import annotations

import json

from scripts import run_real_derived_business_matrix as runner


def _case(fact_type: str = "dimensions") -> dict:
    return {
        "case_uid": "real_derived_case_opaque",
        "dataset_tier": "real_derived",
        "scenario_domain": "product_specification",
        "query_fact_type": fact_type,
        "requested_claims": [{"claim_type": fact_type, "attribute_key": fact_type}],
        "requested_attribute_keys": [fact_type],
        "product_context_quality": "identity_scoped",
        "sidecar_quality": "product_identity_present",
        "expected_claims": [{"claim_type": fact_type}],
        "unresolved_claims": [],
        "prohibited_claims": [],
        "required_action_points": [],
        "expected_media_roles": [],
        "expected_delivery_contract": "factual_preview_only",
        "provenance": {"source_kind": "real_derived"},
        "privacy_status": "pseudonymized",
        "approval_status": "published_direct_field",
        "expected_direct_evidence": True,
        "_runtime_identity": {"i_id": "raw-iid", "sku_code": "raw-sku"},
        "_question": "generic question",
    }


def test_public_case_never_exports_runtime_identity_or_question():
    public = runner._public_case(_case())
    assert "_runtime_identity" not in public
    assert "_question" not in public
    assert "raw-iid" not in json.dumps(public)


def test_run_cases_uses_identity_only_in_payload_and_reports_structural_result(monkeypatch):
    captured = {}

    def fake_post(_url, payload, _timeout):
        captured.update(payload)
        return 200, {
            "analysis_pipeline": {"version": "v1"},
            "suggested_reply": "reply",
            "selected_evidence": [{"fact_type": "dimensions"}],
            "evidence_debug": {"admitted_answer_context": {"direct_product_facts": [{"fact_type": "dimensions"}]}},
            "can_send": False,
            "requires_human_review": True,
        }, 12.3, ""

    monkeypatch.setattr(runner, "_post", fake_post)
    result = runner.run_cases([_case()], api_url="http://example.invalid/analyze", timeout=1)[0]
    assert captured["i_id"] == "raw-iid"
    assert result["passed"] is True
    assert "raw-iid" not in json.dumps(result)
    assert "agent_reply" not in result


def test_high_risk_real_derived_case_requires_review(monkeypatch):
    case = _case("load_capacity")
    case["expected_direct_evidence"] = False
    case["unresolved_claims"] = ["load_capacity"]
    case["prohibited_claims"] = ["load_capacity"]
    case["expected_delivery_contract"] = "requires_human_review"

    monkeypatch.setattr(runner, "_post", lambda *_args: (200, {
        "suggested_reply": "review", "can_send": False, "requires_human_review": True,
    }, 1.0, ""))
    result = runner.run_cases([case], api_url="http://example.invalid/analyze", timeout=1)[0]
    assert result["passed"] is True
    assert result["can_send"] is False
