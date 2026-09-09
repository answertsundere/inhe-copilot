"""Conversation-only context reaches the existing composer, never admission."""

import copy

import pytest

from app.agent.nodes.evidence_builder import _formal_evidence_convergence
from app.services.canonical_conversation_turn_service import normalize_conversation_turns


def _build(monkeypatch, history):
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    state = {
        "customer_message": "How wide is it?",
        "copilot_context": {"conversation_history": history},
        "conversation_history": [{"role": "customer", "content": "unowned old context"}],
    }
    before = copy.deepcopy(state)
    result = _formal_evidence_convergence(state, product_facts=[], policy_facts=[], faq_evidence=[])
    assert state == before
    return result


def test_canonical_history_reaches_reply_context_without_becoming_fact(monkeypatch):
    turns, _ = normalize_conversation_turns([
        {"role": "user", "content": "I asked about the carton; contact 13800138000."},
        {"role": "assistant", "content": "It is wood and can carry 900kg."},
        {"role": "user", "content": "Do not guess. Tell me the carton width."},
    ])
    result = _build(monkeypatch, turns)
    context = result["minimal_decision_context"]
    recent = context["recent_conversation_turns"]
    assert len(recent) == 3
    assert [row["role"] for row in recent] == ["customer", "agent", "customer"]
    assert "13800138000" not in str(recent)
    assert "wood" in recent[1]["content"]
    assert context["admitted_evidence"] == []
    assert result["selected_evidence"] == []
    assert result["admitted_answer_context"]["direct_product_facts"] == []
    assert "unowned old context" not in str(context)


@pytest.mark.parametrize("history", [None, [], "bad history", {"content": "bad shape"}])
def test_reply_context_does_not_fall_back_to_unowned_history(monkeypatch, history):
    result = _build(monkeypatch, history)
    assert result["minimal_decision_context"]["recent_conversation_turns"] == []


def test_reply_context_keeps_existing_history_budget(monkeypatch):
    turns, _ = normalize_conversation_turns([
        {"role": "user", "content": f"turn-{index} " + "x" * 500} for index in range(12)
    ])
    recent = _build(monkeypatch, turns)["minimal_decision_context"]["recent_conversation_turns"]
    assert len(recent) == 8
    assert recent[0]["content"].startswith("turn-4")
    assert all(len(row["content"]) <= 280 for row in recent)
