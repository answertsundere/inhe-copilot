from __future__ import annotations

import pytest


def test_analyze_accepts_top_level_conversation_history(monkeypatch):
    from app.api import analyze_routes
    from app.main import create_app
    import app.services.analysis_execution_service as execution_service

    captured = {}

    def fake_execute_analysis(**kwargs):
        captured.update(kwargs)
        return {
            "suggested_reply": "ok",
            "intent": "aftersales",
            "risk_level": "medium",
            "requires_human_review": True,
            "trace_steps": [],
            "evidence_debug": {},
            "execution_debug": {},
        }

    monkeypatch.setattr(analyze_routes, "get_services", lambda: object())
    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)

    app = create_app()
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/analyze",
        json={
            "message": "这个是哪个？还能补吗？",
            "conversation_history": [
                {"role": "customer", "text": "小熊床护栏有个零件断了"},
                {"role": "agent", "text": "麻烦拍一下断掉的零件"},
                {"role": "customer", "text": "这个是哪个？还能补吗？"},
            ],
        },
    )

    assert response.status_code == 200
    assert captured["copilot_context"]["conversation_history"][0]["role"] == "customer"
    assert captured["customer_message"] == "这个是哪个？还能补吗？"


def test_analyze_rejects_malformed_strict_conversation_history_before_graph(monkeypatch):
    from app.api import analyze_routes
    from app.main import create_app
    import app.services.analysis_execution_service as execution_service

    monkeypatch.setattr(analyze_routes, "get_services", lambda: object())
    monkeypatch.setattr(
        execution_service,
        "execute_analysis",
        lambda **_kwargs: pytest.fail("strict conversation context must stop before graph execution"),
    )

    app = create_app()
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/api/analyze",
        json={
            "message": "帮我看一下",
            "conversation_history": "buyer: legacy text",
            "copilot_context": {"evaluation_context_contract": "strict"},
        },
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_conversation_context"
    assert response.get_json()["error_reason"] == "conversation_history_expected_list"


def test_platform_order_id_fast_path_keeps_platform_type():
    from app.services.logistics_fast_path import get_explicit_logistics_identifier

    result = get_explicit_logistics_identifier({
        "intent": "logistics_eta",
        "risk_level": "low",
        "slots": {
            "identifier_type": "platform_order_id",
            "order_id": "6926666820903533935",
            "platform_order_id": "6926666820903533935",
        },
    })

    assert result == {
        "identifier_type": "platform_order_id",
        "identifier_value": "6926666820903533935",
    }


def test_platform_order_intercept_can_use_deterministic_fast_path():
    from app.services.logistics_fast_path import get_explicit_logistics_identifier

    result = get_explicit_logistics_identifier({
        "customer_message": "可以帮我拦截吗？我不想要了。",
        "intent": "aftersales",
        "risk_level": "medium",
        "slots": {
            "identifier_type": "platform_order_id",
            "platform_order_id": "6926666820903533935",
        },
    })

    assert result == {
        "identifier_type": "platform_order_id",
        "identifier_value": "6926666820903533935",
    }


def test_platform_order_id_uses_outbound_tool_for_order_operation():
    from app.agent.nodes.response_strategy_router import response_strategy_router

    result = response_strategy_router({
        "intent": "logistics_eta",
        "risk_level": "low",
        "slots": {
            "identifier_type": "platform_order_id",
            "order_id": "6926666820903533935",
            "platform_order_id": "6926666820903533935",
        },
        "trace_steps": [],
    })

    assert result["response_strategy"] == "logistics_with_order"
    assert result["required_tools"] == ["jst_lookup_outbound_tool"]


def test_intercept_with_order_cannot_be_downgraded_to_generic_aftersales():
    from app.agent.nodes.router_validation import router_validation

    result = router_validation({
        "customer_message": "可以帮我拦截吗？我不想要了。",
        "normalized_message": "可以帮我拦截吗？我不想要了。",
        "intent": "aftersales",
        "router_decision": {"intent": "aftersales"},
        "router_source": "llm",
        "slots": {
            "identifier_type": "platform_order_id",
            "order_id": "6926666820903533935",
            "platform_order_id": "6926666820903533935",
        },
        "trace_steps": [],
    })

    assert result["intent"] == "logistics_eta"
    assert result["order_operation"] == "intercept"
    assert result["selected_tool"] == "jst_live_query"


def test_wrong_item_missing_parts_installation_preserves_all_intents():
    from app.agent.nodes.parallel_understanding import _intent_classifier

    result = _intent_classifier({
        "normalized_message": "收到的不是我拍的，而且少了配件，这个怎么安装？",
    })

    assert result["primary_intent"] == "missing_item"
    assert "wrong_item" in result["secondary_intents"]
    assert "installation_question" in result["secondary_intents"]


def test_manual_followup_overrides_installation_primary_route():
    from app.agent.nodes.parallel_controls import apply_parallel_pre_strategy_controls

    result = apply_parallel_pre_strategy_controls({
        "intent": "installation",
        "risk_level": "low",
        "decision_fusion": {
            "final_intent": "missing_item",
            "risk_level": "medium",
            "need_human_review": True,
        },
        "trace_steps": [],
    })

    assert result["intent"] == "aftersales"
    assert result["requires_human_review"] is True


def test_known_product_missing_capacity_does_not_request_product_link():
    from app.agent.nodes.reply_relevance_guard import reply_relevance_guard

    result = reply_relevance_guard({
        "customer_message": "这个可以放多少本绘本？会不会压弯？",
        "normalized_message": "这个可以放多少本绘本？会不会压弯？",
        "intent": "product_question",
        "suggested_reply": "亲，我再帮您确认一下。",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "2号收纳架",
        },
        "trace_steps": [],
    })

    assert "2号收纳架" in result["suggested_reply"]
    assert "商品链接" not in result["suggested_reply"]
    assert "已审核资料" not in result["suggested_reply"]
    assert "资料库" not in result["suggested_reply"]
    assert "确认" in result["suggested_reply"] or "核实" in result["suggested_reply"]


def test_known_product_without_evidence_escalates_instead_of_asking_identity():
    from app.agent.nodes.response_strategy_planner import response_strategy_planner

    result = response_strategy_planner({
        "intent": "product_question",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "2号收纳架",
        },
        "evidence": {"product_facts": [], "faq_evidence": []},
        "trace_steps": [],
    })

    assert result["missing_slots"] == []
    assert result["requires_human_review"] is True


def test_known_product_safety_concern_without_evidence_escalates():
    from app.agent.nodes.response_strategy_planner import response_strategy_planner

    result = response_strategy_planner({
        "intent": "product_question",
        "customer_concern": "worries_product_safety",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "2号收纳架",
        },
        "evidence": {"product_facts": [], "faq_evidence": []},
        "trace_steps": [],
    })

    assert result["missing_slots"] == []
    assert result["requires_human_review"] is True


def test_parallel_understanding_uses_only_customer_history():
    from app.agent.nodes.parallel_understanding import _text

    text = _text({
        "normalized_message": "这个是哪个？还能补吗？",
        "copilot_context": {
            "conversation_history": [
                {"role": "customer", "text": "小熊床护栏有个零件断了"},
                {"role": "agent", "text": "麻烦拍一下安装位置"},
                {"role": "customer", "text": "这个是哪个？还能补吗？"},
            ],
        },
    })

    assert "零件断了" in text
    assert "拍一下安装位置" not in text
    assert text.count("这个是哪个？还能补吗？") == 1


def test_aftersales_reply_uses_customer_history_for_broken_part():
    from app.agent.nodes.generate_reply import _aftersales_reply

    reply = _aftersales_reply({
        "customer_message": "这个是哪个？还能补吗？",
        "copilot_context": {
            "conversation_history": [
                {"role": "customer", "text": "小熊床护栏有个零件断了"},
                {"role": "agent", "text": "麻烦拍一下断掉的零件"},
                {"role": "customer", "text": "这个是哪个？还能补吗？"},
            ],
        },
    })

    assert "零件破损" in reply
    assert "少件/缺配件" not in reply
    assert "补配件" in reply
    assert "暂时不先承诺" in reply


def test_dropped_parts_are_damaged_aftersales_and_require_review():
    from app.agent.nodes.parallel_understanding import _intent_classifier, _risk_classifier
    from app.agent.nodes.generate_reply import _aftersales_reply

    state = {"normalized_message": "我的滑滑梯零件都掉了，有没有补？"}
    intent = _intent_classifier(state)
    risk = _risk_classifier(state)
    reply = _aftersales_reply(state)

    assert intent["primary_intent"] == "damaged_item"
    assert risk["risk_level"] == "medium"
    assert risk["need_human_review"] is True
    assert "滑滑梯" in reply
    assert "零件破损" in reply


def test_known_product_material_guard_does_not_request_link():
    from app.agent.nodes.reply_relevance_guard import reply_relevance_guard

    result = reply_relevance_guard({
        "customer_message": "这个材质安全吗？",
        "normalized_message": "这个材质安全吗？",
        "intent": "product_question",
        "suggested_reply": "麻烦发一下商品链接，我帮您核实。",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "2号收纳架",
        },
        "trace_steps": [],
    })

    assert "2号收纳架" in result["suggested_reply"]
    assert "商品链接" not in result["suggested_reply"]


def test_reply_that_promises_manual_action_sets_review_flag():
    from app.agent.nodes.build_response import build_response

    result = build_response({
        "suggested_reply": "我先帮您转人工/货品同事确认，确认后再回复您。",
        "risk_level": "low",
        "trace_steps": [],
    })

    assert result["requires_human_review"] is True
    assert result["review_reason"] == "最终回复包含人工处理动作"
