import pytest

from app.agent.context.conversation_context import apply_conversation_context
from app.agent.nodes.query_fact_type_classifier import query_fact_type_classifier
from app.services.final_answer_auditor import audit_final_answer


@pytest.mark.parametrize(
    ("message", "expected_fact_types"),
    [
        ("宝宝能用吗，今天能发吗？", {"material", "stock_shipping"}),
        ("材质安全吗，有现货吗？", {"material", "stock_shipping"}),
        ("这个防水吗，什么时候发货？", {"material", "stock_shipping"}),
    ],
)
def test_query_understanding_keeps_multi_intent_fact_types(message, expected_fact_types):
    state = {
        "customer_message": message,
        "normalized_message": message,
        "intent": "product_question",
        "risk_level": "low",
        "slots": {},
        "trace_steps": [],
    }

    result = query_fact_type_classifier(state)

    understanding = result["query_understanding"]
    actual_fact_types = {
        understanding["query_fact_type"],
        *understanding["secondary_fact_types"],
    }
    assert expected_fact_types <= actual_fact_types
    assert {"material_safety", "stock_query"} <= set(understanding["sub_intents"])
    assert understanding["original_message"] == message
    assert understanding["normalized_message"] == message
    assert message in understanding["retrieval_query"]


def test_logistics_turn_retrieval_query_does_not_include_previous_material_context():
    message = "我的订单到哪了，订单号202501010001"
    state = {
        "customer_message": message,
        "normalized_message": message,
        "intent": "logistics_eta",
        "risk_level": "low",
        "slots": {"order_id": "202501010001", "identifier_type": "internal_order_id"},
        "history_snapshot": {
            "confirmed_product": "一号收纳柜",
            "current_intent": "material_safety",
            "last_agent_question": "您是想问材质吗？",
        },
        "trace_steps": [],
    }

    result = query_fact_type_classifier(state)

    understanding = result["query_understanding"]
    assert understanding["intent"] == "logistics_eta"
    assert "材质" not in understanding["retrieval_query"]
    assert "一号收纳柜" not in understanding["retrieval_query"]
    assert understanding["order_entities"]


def test_product_entity_switch_records_context_reset_reason():
    state = {
        "customer_message": "SKU YH06K53B05S99 这个材质安全吗",
        "normalized_message": "SKU YH06K53B05S99 这个材质安全吗",
        "intent": "product_question",
        "slots": {"sku_code": "YH06K53B05S99"},
        "conversation_context": {
            "conversation_id": "phase2_entity_switch",
            "active_issue": "product_question",
            "confirmed_product": "商品A",
            "order_product_identity": {
                "sku_id": "YH06K53B05S13",
                "matched_product_name": "商品A",
            },
            "last_requested_slots": [],
        },
        "order_product_identity": {
            "sku_id": "YH06K53B05S99",
            "matched_product_name": "商品B",
        },
        "trace_steps": [],
    }

    result = apply_conversation_context(state)

    assert result["context_reset_reason"] == "product_entity_changed"
    assert result["conversation_context"]["confirmed_product"] == ""
    trace = result["trace_steps"][-1]
    assert "context_reset:product_entity_changed" in trace["summary"]


def test_final_auditor_blocks_size_question_answered_as_load_capacity():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这款单层均匀承重约15-30kg，放书籍玩具都够用。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "dimensions"},
    }

    audited = audit_final_answer(response, customer_message="这个尺寸是多少？")

    assert audited["final_answer_audit"]["passed"] is False
    assert any("dimensions" in issue or "wrong_topic" in issue for issue in audited["final_answer_audit"]["issues"])
    assert audited["requires_human_review"] is True


def test_final_auditor_blocks_age_question_answered_as_material():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这款主要是环保PP和钢管材质，日常使用比较好打理。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "age_range"},
    }

    audited = audit_final_answer(response, customer_message="这个适合一岁宝宝用吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert any("age_range" in issue or "wrong_topic" in issue for issue in audited["final_answer_audit"]["issues"])
    assert audited["requires_human_review"] is True
