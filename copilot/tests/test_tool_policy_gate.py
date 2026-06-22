from app.agent.tools.tool_policy_gate import evaluate_tool_call


def test_order_intent_with_order_entity_allows_jst():
    decision = evaluate_tool_call(
        "jst_lookup_order_tool",
        {
            "intent": "logistics_trace",
            "slots": {"order_id": "1234567890123456"},
            "query_fact_type": "logistics",
        },
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_product_material_question_blocks_jst_even_when_text_mentions_order():
    decision = evaluate_tool_call(
        "jst_lookup_order_tool",
        {
            "intent": "product_question",
            "query_fact_type": "material",
            "normalized_message": "这个材质安全吗，我不是问订单",
            "slots": {"order_id": "1234567890123456"},
        },
    )

    assert decision.allowed is False
    assert decision.reason == "intent_not_allowed"


def test_image_question_allows_media_tool_with_structured_product_entity():
    decision = evaluate_tool_call(
        "media_asset_recommend_tool",
        {
            "intent": "product_question",
            "query_fact_type": "visual_asset",
            "product_entities": [{"sku_code": "SKU-1"}],
        },
    )

    assert decision.allowed is True


def test_product_question_with_product_entity_allows_rag():
    decision = evaluate_tool_call(
        "rag_search_tool",
        {
            "intent": "product_question",
            "query_fact_type": "material",
            "product_entities": [{"sku_code": "SKU-1"}],
        },
    )

    assert decision.allowed is True


def test_missing_order_entity_blocks_order_tool_with_missing_entity_reason():
    decision = evaluate_tool_call(
        "jst_lookup_order_tool",
        {
            "intent": "logistics_trace",
            "query_fact_type": "logistics",
            "normalized_message": "我的订单到哪了",
        },
    )

    assert decision.allowed is False
    assert decision.reason == "required_entity_missing"
    assert "order_entity" in decision.required_entities_missing


def test_write_tool_is_blocked_by_default():
    decision = evaluate_tool_call(
        "send_message_tool",
        {"intent": "product_question", "query_fact_type": "material"},
    )

    assert decision.allowed is False
    assert decision.risk_level == "write_or_side_effect"


def test_policy_uses_structured_context_not_message_keywords():
    decision = evaluate_tool_call(
        "jst_lookup_order_tool",
        {
            "intent": "product_question",
            "query_fact_type": "dimensions",
            "normalized_message": "订单里的这个商品尺寸多大",
            "product_entities": [{"sku_code": "SKU-1"}],
        },
    )

    assert decision.allowed is False
    assert decision.reason == "intent_not_allowed"
