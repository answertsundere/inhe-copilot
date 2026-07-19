from __future__ import annotations

from types import SimpleNamespace

from app.services.agent_decision_proposal_service import (
    _model_led_action_plan,
    build_model_led_candidate_preview,
    build_supervisor_partial_answer_preview,
)


def _context() -> dict:
    return {
        "customer_goal": "尺寸和安全怎么样",
        "requested_claims": [{"claim_type": "dimensions"}, {"claim_type": "material_safety"}],
        "product_identity": {},
        "admitted_evidence": [{
            "evidence_uid": "ev-size", "content": "商品宽度为80cm", "fact_type": "dimensions", "attribute_key": "width",
        }],
        "claim_resolutions": [
            {"claim_uid": "claim-size", "claim_type": "dimensions", "status": "supported", "evidence_uids": ["ev-size"]},
            {"claim_uid": "claim-safety", "claim_type": "material_safety", "status": "unresolved", "reason": "no_admitted_direct_evidence"},
        ],
        "unresolved_claims": [{"claim_type": "material_safety", "status": "unresolved"}],
        "service_actions": [{"evidence_uid": "action-1", "text": "核对商品资料", "non_fact": True}],
        "allowed_read_only_tools": ["rag_search_tool"],
        "allowed_low_risk_inferences": [{"type": "bounded_low_risk_inference"}],
        "recent_conversation_turns": [{"role": "customer", "content": "上一个尺寸呢", "turn_uid": "turn-1", "turn_index": 1}],
        "context_stats": {},
    }


def test_action_plan_is_claim_state_driven_and_supports_compound_actions():
    actions = _model_led_action_plan(_context(), actual_reply_blocks=[{"type": "image"}])

    assert {
        "answer_from_evidence", "bounded_low_risk_inference", "partial_answer_then_handoff",
        "ask_clarifying_question", "request_read_only_tool", "offer_service_action", "request_specific_media",
    }.issubset(actions)


def test_model_candidate_is_review_only_and_preserves_every_required_clause(monkeypatch):
    expected_text = build_supervisor_partial_answer_preview(_context())["candidate_text"]

    class FakeClient:
        api_key = "configured"
        model = "formal-model"

        def create_chat_completion(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=expected_text
            ))])

    monkeypatch.setattr(
        "app.services.agent_decision_proposal_service._preview_safety_validation",
        lambda *_args, **_kwargs: {"passed": True, "issues": [], "audit_summary": {}},
    )
    candidate = build_model_led_candidate_preview(_context(), client=FakeClient())

    assert candidate["can_send"] is False
    assert candidate["used_for_final_reply"] is False
    assert candidate["status"] == "accepted"
    assert candidate["evidence_uids"] == ["ev-size"]


def test_model_candidate_rejects_missing_or_unsupported_clause():
    class FakeClient:
        api_key = "configured"
        model = "formal-model"

        def create_chat_completion(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="亲，这款绝对安全，可以放心使用。"
            ))])

    candidate = build_model_led_candidate_preview(_context(), client=FakeClient())

    assert candidate["status"] == "provider_blocked"
    assert candidate["rejection_reason"] == "required_clause_not_preserved"
