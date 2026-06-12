from __future__ import annotations


def _run_parallel(message: str, conversation_context: dict | None = None) -> dict:
    from app.agent.nodes.parallel_understanding import parallel_understanding

    state = {
        "customer_message": message,
        "normalized_message": message,
        "conversation_context": conversation_context or {},
        "trace_steps": [],
    }
    return parallel_understanding(state)


def _result_data(result: dict, analyzer: str) -> dict:
    return result["parallel_understanding"][analyzer]["data"]


def test_platform_trade_logistics_not_product_question():
    result = _run_parallel("5118207015382036103 我的快递什么时候到")
    intent = _result_data(result, "intent_classifier")
    slots = _result_data(result, "slot_entity_extractor")
    tools = _result_data(result, "tool_need_predictor")
    safety = _result_data(result, "safety_precheck")

    assert intent["primary_intent"] == "logistics_eta"
    assert intent["primary_intent"] != "product_question"
    assert slots["identifiers"][0]["type"] == "platform_trade_id"
    assert "jst_lookup_outbound_tool" in tools["required_tools"]
    assert "一定到" in safety["forbidden_claims"]


def test_material_question_requires_evidence():
    result = _run_parallel("这个儿童书架是不是实木的")
    intent = _result_data(result, "intent_classifier")
    customer = _result_data(result, "customer_state_analyzer")
    safety = _result_data(result, "safety_precheck")

    assert intent["primary_intent"] == "material_question"
    assert "product_question" in intent["secondary_intents"]
    assert customer["customer_concern"] == "worries_material"
    assert "材质" in safety["requires_evidence_for"]
    assert "实木" in safety["forbidden_claims"]
    assert "不是实木" in safety["forbidden_claims"]


def test_eta_certainty_sets_boundary_contract():
    result = _run_parallel("明天能不能一定到？")
    customer = _result_data(result, "customer_state_analyzer")
    safety = _result_data(result, "safety_precheck")

    assert customer["customer_concern"] == "wants_eta_certainty"
    assert customer["needs_boundary_setting"] is True
    assert "一定到" in safety["forbidden_claims"]
    assert "保证到" in safety["forbidden_claims"]
    assert "物流状态" in safety["requires_evidence_for"]


def test_complaint_logistics_compound_intent_high_risk():
    result = _run_parallel("再不发货我就投诉平台")
    intent = _result_data(result, "intent_classifier")
    risk = _result_data(result, "risk_classifier")
    tools = _result_data(result, "tool_need_predictor")
    safety = _result_data(result, "safety_precheck")

    assert intent["primary_intent"] in ("logistics_eta", "complaint")
    assert "complaint" in intent["secondary_intents"]
    assert risk["risk_level"] == "high"
    assert risk["need_human_review"] is True
    assert "sop_lookup_tool" in tools["required_tools"]
    assert "承诺赔偿" in safety["forbidden_claims"]


def test_missing_item_requires_manual_followup():
    result = _run_parallel("收到的货少了一件")
    intent = _result_data(result, "intent_classifier")
    risk = _result_data(result, "risk_classifier")
    tools = _result_data(result, "tool_need_predictor")

    assert intent["primary_intent"] == "missing_item"
    assert risk["risk_level"] in ("medium", "high")
    assert risk["need_human_review"] is True
    assert "sop_lookup_tool" in tools["required_tools"]


def test_followup_numeric_fills_requested_slot():
    result = _run_parallel(
        "5118207015382036103",
        conversation_context={
            "last_requested_slots": ["order_id", "tracking_no"],
            "active_issue": "delivery_not_received",
        },
    )
    ctx = _result_data(result, "context_resolver")
    assert ctx["is_followup"] is True
    assert ctx["fills_requested_slot"] == "order_id_or_trade_id"
    assert ctx["active_issue"] == "delivery_not_received"


def test_tracking_no_not_product_question():
    result = _run_parallel("SF0229477422177 到哪里了")
    intent = _result_data(result, "intent_classifier")
    slots = _result_data(result, "slot_entity_extractor")
    tools = _result_data(result, "tool_need_predictor")

    assert intent["primary_intent"] in ("logistics_eta", "logistics_tracking")
    assert slots["identifiers"][0]["type"] == "tracking_no"
    assert "jst_lookup_tracking_tool" in tools["required_tools"]
    assert intent["primary_intent"] != "product_question"


def test_analyzer_failure_does_not_break_node(monkeypatch):
    import app.agent.nodes.parallel_understanding as module

    def broken(_state):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_risk_classifier", broken)
    result = module.parallel_understanding({
        "customer_message": "一号狮子围兜防水吗",
        "normalized_message": "一号狮子围兜防水吗",
        "trace_steps": [],
    })

    pu = result["parallel_understanding"]
    assert pu["overall_status"] == "degraded"
    assert pu["risk_classifier"]["status"] == "failed"
    assert any(step.get("analyzer") == "risk_classifier" and step.get("status") == "failed" for step in result["trace_steps"])
