from __future__ import annotations


def _fuse(message: str, conversation_context: dict | None = None) -> dict:
    from app.agent.nodes.parallel_understanding import parallel_understanding
    from app.agent.nodes.decision_fusion import decision_fusion

    state = {
        "customer_message": message,
        "normalized_message": message,
        "conversation_context": conversation_context or {},
        "trace_steps": [],
    }
    state.update(parallel_understanding(state))
    return decision_fusion(state)


def test_fusion_platform_trade_requires_outbound_lookup():
    result = _fuse("5118207015382036103 我的快递什么时候到")
    fusion = result["decision_fusion"]

    assert fusion["final_intent"] == "logistics_eta"
    assert "jst_lookup_outbound_tool" in fusion["required_tools"]
    assert fusion["final_intent"] != "product_question"
    assert "一定到" in fusion["safety_contract"]["forbidden_claims"]


def test_fusion_complaint_forces_high_risk_human_review():
    result = _fuse("再不发货我就投诉平台")
    fusion = result["decision_fusion"]

    assert fusion["risk_level"] == "high"
    assert fusion["need_human_review"] is True
    assert "sop_lookup_tool" in fusion["required_tools"]
    assert fusion["answer_mode"] == "sop_human_review_answer"


def test_fusion_material_question_contract():
    result = _fuse("这个儿童书架是不是实木的")
    fusion = result["decision_fusion"]

    assert fusion["final_intent"] in ("material_question", "product_question")
    assert fusion["customer_concern"] == "worries_material"
    assert "材质" in fusion["safety_contract"]["requires_evidence_for"]
    assert "实木" in fusion["safety_contract"]["forbidden_claims"]
    assert fusion["answer_mode"] == "no_evidence_clarification"


def test_fusion_eta_certainty_reply_goal():
    result = _fuse("明天能不能一定到？")
    fusion = result["decision_fusion"]

    assert fusion["reply_goal"] == "explain_no_guarantee"
    assert "一定到" in fusion["safety_contract"]["forbidden_claims"]
    assert "物流状态" in fusion["safety_contract"]["requires_evidence_for"]


def test_fusion_followup_preserves_active_issue():
    result = _fuse(
        "5118207015382036103",
        conversation_context={
            "last_requested_slots": ["order_id", "tracking_no"],
            "active_issue": "delivery_not_received",
        },
    )
    fusion = result["decision_fusion"]
    assert fusion["final_intent"] == "delivery_not_received"
    assert "jst_lookup_outbound_tool" in fusion["required_tools"]


def test_graph_debug_contains_parallel_understanding():
    from app.services.reply_service import ReplyService
    from app.main import get_reply_service

    service: ReplyService = get_reply_service()
    result = service.analyze("明天能不能一定到？", conversation_id="parallel-test")
    data = result.to_dict()
    debug = data.get("evidence_debug", {})

    assert debug.get("parallel_observation_mode") is True
    assert "parallel_understanding" in debug
    assert "decision_fusion" in debug
    assert "safety_contract" in debug
    assert "analyzer_durations" in debug
    assert "fusion_reasons" in debug
    assert debug.get("final_intent") == "logistics_eta"
    assert data["suggested_reply"]
