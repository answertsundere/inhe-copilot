from __future__ import annotations

import hashlib

import pytest

from app.agent.nodes.response_strategy_router import response_strategy_router


def _goal(*, semantic_key: str, goal_kind: str = "customer_goal") -> dict:
    source_text = "Please resolve the current request."
    return {
        "schema_version": "canonical-goal-identity/v1",
        "goal_ref": f"goal_{semantic_key}",
        "goal_kind": goal_kind,
        "claim_type_status": "unmapped",
        "claim_type": "",
        "semantic_key": semantic_key,
        "source": "current_customer_message",
        "source_stage": "semantic_fact_type_service",
        "source_turn_uid": "turn_current",
        "source_span_start": 0,
        "source_span_end": len(source_text),
        "source_span_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "owner": "turn_understanding_owner",
    }


def _state(goal: dict, *, status: str = "valid") -> dict:
    return {
        "intent": "general",
        "risk_level": "low",
        "normalized_message": "Please resolve the current request.",
        "customer_message": "Please resolve the current request.",
        "slots": {},
        "copilot_context": {},
        "turn_understanding": {
            "schema_version": "turn-understanding/v2",
            "owner": "turn_understanding_owner",
            "source_stage": "query_fact_type_classifier",
            "goal_understanding_status": status,
            "customer_goals": [goal],
            "requested_claims": [{"goal_ref": goal.get("goal_ref", "")}],
        },
    }


@pytest.mark.parametrize("semantic_key", ["current_terms", "availability_window"])
def test_authoritative_customer_goal_enters_existing_evidence_route(semantic_key: str):
    result = response_strategy_router(_state(_goal(semantic_key=semantic_key)))

    assert result["response_strategy"] == "product_question"
    assert result["should_query_knowledge"] is True
    assert result["answer_mode"] == "product_answer"


@pytest.mark.parametrize(
    ("goal", "status"),
    [
        (_goal(semantic_key="current_terms"), "degraded"),
        (_goal(semantic_key="current_terms", goal_kind="media_request"), "valid"),
        ({**_goal(semantic_key="current_terms"), "owner": "public_input"}, "valid"),
        ({**_goal(semantic_key="current_terms"), "source_span_sha256": "invalid"}, "valid"),
    ],
)
def test_non_authoritative_or_non_fact_goal_stays_in_clarification(goal: dict, status: str):
    result = response_strategy_router(_state(goal, status=status))

    assert result["response_strategy"] == "clarification"
    assert result["should_query_facts"] is False
