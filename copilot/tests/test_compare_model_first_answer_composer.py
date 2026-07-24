from argparse import Namespace
import json

import pytest

from scripts import compare_model_first_answer_composer as comparison


def _scenario():
    return {
        "scenario_uid": "scenario-hmac",
        "business_domain": "商品事实",
        "risk_level": "medium",
        "must_handoff": False,
        "api_request_template": {
            "message": "这款是什么材质，耐摔吗？",
            "conversation_history": [{"role": "customer", "content": "我问的是这个款"}],
            "sku_code": "SKU-A",
        },
        "expected_claims": [
            {
                "expected_status": "supported",
                "required_answer_points": ["ABS"],
            },
            {
                "expected_status": "unresolved",
                "required_answer_points": ["不能保证耐摔"],
            },
        ],
        "forbidden_claims": ["保证摔不坏"],
        "gold_reply": "must not enter Agent payload",
        "required_actions": ["hidden evaluator action"],
    }


def test_agent_payload_excludes_evaluation_fields():
    payload = comparison._agent_payload(_scenario())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "gold_reply" not in serialized
    assert "expected_claims" not in serialized
    assert "required_actions" not in serialized
    assert payload["message"] == "这款是什么材质，耐摔吗？"


def test_agent_payload_rejects_evaluation_field_nested_in_template():
    scenario = _scenario()
    scenario["api_request_template"]["copilot_context"] = {
        "rubric": {"hidden": True},
    }

    with pytest.raises(ValueError, match="evaluation_field_leakage:rubric"):
        comparison._agent_payload(scenario)


def test_response_scoring_separates_supported_and_unresolved_claims():
    score = comparison._score_response(
        _scenario(),
        {
            "suggested_reply": "这款是ABS材质，但目前不能保证耐摔。",
            "selected_evidence": [{"evidence_uid": "material"}],
            "can_send": False,
            "requires_human_review": True,
            "final_answer_audit": {"passed": True, "issues": []},
            "final_semantic_fit_audit": {"passed": True, "issues": []},
            "reply_blocks": [{"type": "text"}],
            "model_first_answer_composer": {
                "status": "accepted",
                "used_evidence_uids": ["material"],
                "unresolved_claim_types": ["stability"],
            },
            "minimal_decision_context": {
                "claim_resolutions": [
                    {
                        "claim_type": "material",
                        "status": "supported",
                        "evidence_uids": ["material"],
                    },
                    {
                        "claim_type": "stability",
                        "status": "unresolved",
                        "evidence_uids": [],
                    },
                ],
            },
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["supported_complete"] is True
    assert score["unresolved_complete"] is True
    assert score["partial_answer_success"] is True
    assert score["runtime_supported_claim_numerator"] == 1
    assert score["runtime_supported_claim_denominator"] == 1
    assert score["runtime_unresolved_handling_numerator"] == 1
    assert score["runtime_unresolved_handling_denominator"] == 1
    assert score["unsupported_high_risk_claim"] is False
    assert score["can_send"] is False


def test_response_scoring_blocks_forbidden_and_media_claims():
    score = comparison._score_response(
        _scenario(),
        {
            "suggested_reply": "保证摔不坏，安装视频已经发给您了。",
            "selected_evidence": [],
            "can_send": True,
            "requires_human_review": False,
            "reply_blocks": [{"type": "text"}],
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["unsupported_high_risk_claim"] is True
    assert score["unsupported_media_promise"] is True
    assert score["can_send"] is True


@pytest.mark.parametrize(
    "reply",
    [
        "这款不能保证摔不坏。",
        "目前无法保证摔不坏。",
        "我们不会保证摔不坏。",
    ],
)
def test_response_scoring_does_not_treat_safe_negation_as_forbidden_claim(reply):
    score = comparison._score_response(
        _scenario(),
        {
            "suggested_reply": reply,
            "selected_evidence": [],
            "can_send": False,
            "requires_human_review": True,
            "reply_blocks": [{"type": "text"}],
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["forbidden_claim_hits"] == []
    assert score["unsupported_high_risk_claim"] is False


def test_response_scoring_handles_coordinated_uncertain_high_risk_claims():
    scenario = _scenario()
    scenario["forbidden_claims"] = ["无毒", "食品级"]

    score = comparison._score_response(
        scenario,
        {
            "suggested_reply": "至于宝宝啃咬是否无毒或食品级，目前无法从现有信息确认。",
            "selected_evidence": [],
            "can_send": False,
            "requires_human_review": True,
            "reply_blocks": [{"type": "text"}],
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["forbidden_claim_hits"] == []
    assert score["unsupported_high_risk_claim"] is False


def test_runtime_contract_requires_only_paired_feature_flag_difference():
    runtime = {
        "runtime_commit": "commit",
        "source_tree_sha256": "hash",
        "formal_model": "MiniMax-M3",
        "source_tree_drift": False,
        "formal_knowledge_query_only": True,
        "readiness": {"ready": True},
        "feature_flags": {
            "formal_evidence_convergence": True,
            "model_first_answer_composer": True,
        },
    }

    assert comparison._runtime_contract(
        runtime,
        mode="ON",
        expected_commit="commit",
        expected_source_hash="hash",
        expected_model="MiniMax-M3",
    ) == []


def test_correctness_gate_rejects_partial_audit_and_latency_failures():
    off = {"requires_human_review_count": 8}
    on = {
        "partial_answer_success": {"numerator": 0, "denominator": 4},
        "runtime_supported_claim_attribution": {"numerator": 3, "denominator": 6},
        "runtime_unresolved_claim_declaration": {"numerator": 10, "denominator": 12},
        "final_audit_pass_count": 6,
        "semantic_audit_pass_count": 4,
        "requires_human_review_count": 8,
        "latency_ms": {"p95": 40_350},
    }

    assert comparison._correctness_gate_blockers(off, on, scenario_count=8) == [
        "partial_answer_incomplete",
        "supported_claim_attribution_incomplete",
        "unresolved_claim_declaration_incomplete",
        "final_audit_incomplete",
        "semantic_audit_incomplete",
        "latency_p95_exceeded",
    ]


def test_goal_truth_is_diagnostic_only_and_separates_dependency():
    fixture = (
        comparison.PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "model_first_goal_truth"
        / "v1.json"
    )

    truth = comparison._load_goal_truth(fixture)

    safety = truth["hq-7c578c7f63c4829a2b70"]
    assert [item["expected_goal_kind"] for item in safety] == [
        "customer_goal",
        "evidence_dependency",
    ]
    assert safety[0]["expected_claim_type"] == "bite_or_toxicity"
    assert safety[1]["expected_claim_type"] == "material_composition"


def test_goal_funnel_finds_earliest_understanding_and_requested_claim_breakpoints():
    scenario = {
        "api_request_template": {"message": "current question"},
        "current_buyer_message": "current question",
    }
    truth = [
        {
            "scenario_uid": "scenario-hmac",
            "source_turn_uid": "turn-hmac",
            "source_provenance": "dataset.current_buyer_message",
            "diagnostic_goal_ref": "goal-material",
            "expected_goal_kind": "customer_goal",
            "expected_claim_type": "material_composition",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
        },
        {
            "scenario_uid": "scenario-hmac",
            "source_turn_uid": "turn-hmac",
            "source_provenance": "dataset.current_buyer_message",
            "diagnostic_goal_ref": "goal-moisture",
            "expected_goal_kind": "customer_goal",
            "expected_claim_type": "moisture_resistance",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
        },
    ]
    response = {
        "turn_understanding": {
            "query_fact_type": "material",
            "secondary_fact_types": ["moisture_resistance"],
            "requested_claims": [{"claim_type": "material"}],
        },
        "final_answer_audit": {"passed": True},
        "final_semantic_fit_audit": {"passed": True},
    }

    rows = comparison._goal_funnel(scenario, response, truth)

    assert rows[0]["observed_in_turn_understanding"] is True
    assert rows[0]["observed_in_requested_claims"] is True
    assert rows[1]["observed_in_turn_understanding"] is True
    assert rows[1]["earliest_breakpoint"] == "requested_claim_missing"


def test_goal_funnel_does_not_count_evidence_dependency_as_customer_goal():
    rows = [
        {
            "scenario_uid": "scenario-hmac",
            "expected_goal_kind": "customer_goal",
            "expected_claim_type": "customer-fact",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
            "diagnostic_goal_ref": "goal-customer",
            "observed_in_turn_understanding": True,
            "earliest_breakpoint": None,
        },
        {
            "scenario_uid": "scenario-hmac",
            "expected_goal_kind": "evidence_dependency",
            "expected_claim_type": "supporting-fact",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
            "diagnostic_goal_ref": "goal-dependency",
            "observed_in_turn_understanding": False,
            "earliest_breakpoint": "requested_claim_missing",
        },
    ]

    summary = comparison._goal_recall_summary(
        rows,
        [{
            "scenario_uid": "scenario-hmac",
            "customer_goals": [{"claim_type": "customer-fact"}],
        }],
    )

    assert summary["customer_goal_recall"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert summary["target_denominator"] == 0


def test_goal_recall_precision_counts_unexpected_runtime_goals():
    rows = [{
        "scenario_uid": "scenario-hmac",
        "expected_goal_kind": "customer_goal",
        "diagnostic_label_uncertain": False,
        "diagnostic_goal_ref": "goal-material",
        "expected_claim_type": "material_composition",
        "expected_attribute_key": "",
        "observed_in_turn_understanding": True,
        "earliest_breakpoint": None,
    }]

    summary = comparison._goal_recall_summary(
        rows,
        [{
            "scenario_uid": "scenario-hmac",
            "customer_goals": [
                {"claim_type": "material"},
                {"claim_type": "placement_scene"},
            ],
        }],
    )

    assert summary["customer_goal_precision"] == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
    }
    assert summary["unexpected_runtime_goals"] == [{
        "scenario_uid": "scenario-hmac",
        "claim_type": "placement_scene",
        "attribute_key": "",
    }]
