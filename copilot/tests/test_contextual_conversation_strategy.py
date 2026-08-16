from __future__ import annotations

import pytest

from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder
from app.agent.nodes.response_strategy_planner import response_strategy_planner
from app.services import semantic_fact_type_service


def _contextual_turn(semantic_key: str) -> dict:
    return {
        "schema_version": "turn-understanding/v2",
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "goal_understanding_status": "valid",
        "requested_claims": [],
        "customer_goals": [
            {
                "goal_kind": "contextual_constraint",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "semantic_key": semantic_key,
            }
        ],
    }


def _raw_contextual_goal(semantic_key: str) -> dict:
    return {
        "goal_kind": "contextual_constraint",
        "claim_type_status": "unmapped",
        "claim_type": "",
        "attribute_key": "",
        "subject_scope": "",
        "semantic_key": semantic_key,
        "policy_intent_ref": "",
        "source_text": "opaque current turn",
        "continued_from": "",
    }


def test_contextual_semantic_key_is_a_bounded_contract():
    assert (
        semantic_fact_type_service._goal_type_reason_code(
            _raw_contextual_goal("conversation_closure"),
            "contextual_constraint",
        )
        == ""
    )
    assert (
        semantic_fact_type_service._goal_type_reason_code(
            _raw_contextual_goal(""),
            "contextual_constraint",
        )
        == "contextual_semantic_key_invalid"
    )
    assert (
        semantic_fact_type_service._goal_type_reason_code(
            _raw_contextual_goal("invented_context_state"),
            "contextual_constraint",
        )
        == "contextual_semantic_key_invalid"
    )


@pytest.mark.parametrize("prior_domain", ["installation", "aftersales"])
def test_conversation_closure_routes_by_structured_turn_semantics(prior_domain: str):
    result = response_strategy_planner(
        {
            "intent": "general",
            "customer_concern": "smalltalk",
            "customer_state": {},
            "conversation_context": {"prior_domain": prior_domain},
            "customer_message": "current turn is intentionally opaque to policy code",
            "turn_understanding": _contextual_turn("conversation_closure"),
        }
    )

    assert result["reply_goal"] == "acknowledge_conversation_closure"
    assert result["response_strategy_plan"]["should_answer_directly"] is True
    assert result["response_strategy_plan"]["should_ask_slot"] is False
    assert result["missing_slots"] == []


def test_other_contextual_semantics_do_not_impersonate_conversation_closure():
    result = response_strategy_planner(
        {
            "intent": "general",
            "customer_concern": "smalltalk",
            "customer_state": {},
            "conversation_context": {},
            "customer_message": "current turn is intentionally opaque to policy code",
            "turn_understanding": _contextual_turn("confirmation"),
        }
    )

    assert result["reply_goal"] != "acknowledge_conversation_closure"


def test_gold_csr_closure_reply_is_natural_and_makes_no_action_claim():
    result = gold_csr_reply_builder(
        {
            "suggested_reply": "legacy fallback",
            "response_strategy_plan": {
                "reply_goal": "acknowledge_conversation_closure"
            },
            "answer_mode": "clarification",
            "intent": "general",
            "customer_concern": "smalltalk",
        }
    )

    reply = result["suggested_reply"]
    assert "明白" in reply
    assert "随时" in reply
    assert "核对" not in reply
    assert "确认后" not in reply
    assert "已处理" not in reply
    assert "？" not in reply
