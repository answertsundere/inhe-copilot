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
