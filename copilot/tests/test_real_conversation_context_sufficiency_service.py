from app.services.real_conversation_context_sufficiency_service import assess_context_sufficiency


def test_aftersales_turn_without_order_or_product_is_context_gap():
    result = assess_context_sufficiency(
        turn_understanding={
            "should_score": True,
            "turn_actionability": "actionable_question",
            "query_fact_type": "aftersales",
        },
        real_context_summary={"has_product_context": False, "has_order_context": False},
        real_context_identity={},
    ).to_dict()

    assert result["is_sufficient"] is False
    assert result["missing_context_fields"] == ["order_or_product"]
    assert result["should_count_in_agent_accuracy"] is False


def test_aftersales_turn_with_sku_identity_is_scoreable():
    result = assess_context_sufficiency(
        turn_understanding={
            "should_score": True,
            "turn_actionability": "actionable_question",
            "query_fact_type": "aftersales",
        },
        real_context_summary={"has_product_context": False, "has_order_context": False},
        real_context_identity={"sku_code": "YH06K43B03S13"},
    ).to_dict()

    assert result["is_sufficient"] is True
    assert result["should_count_in_agent_accuracy"] is True


def test_logistics_turn_requires_order_context():
    result = assess_context_sufficiency(
        turn_understanding={
            "should_score": True,
            "turn_actionability": "actionable_question",
            "query_fact_type": "delivery_not_received",
        },
        real_context_summary={"has_product_context": True, "has_order_context": False},
        real_context_identity={"sku_code": "YH06K43B03S13"},
    ).to_dict()

    assert result["is_sufficient"] is False
    assert result["missing_context_fields"] == ["order"]


def test_installation_turn_can_use_product_title_context():
    result = assess_context_sufficiency(
        turn_understanding={
            "should_score": True,
            "turn_actionability": "actionable_question",
            "query_fact_type": "installation",
        },
        real_context_summary={"has_product_context": False, "product_title_preview": "儿童收纳柜"},
        real_context_identity={},
    ).to_dict()

    assert result["is_sufficient"] is True
    assert result["has_product_context"] is True


def test_non_scored_turn_is_not_agent_accuracy_denominator():
    result = assess_context_sufficiency(
        turn_understanding={"should_score": False, "turn_actionability": "acknowledgement"},
        real_context_summary={},
        real_context_identity={},
    ).to_dict()

    assert result["is_sufficient"] is True
    assert result["should_count_in_agent_accuracy"] is False
