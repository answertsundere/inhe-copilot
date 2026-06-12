from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.response_strategy_router import response_strategy_router


def test_price_protection_routes_to_policy_intent():
    result = detect_intent({
        "normalized_message": "\u6211\u521a\u4e70\u5c31\u964d\u4ef7\u4e86\uff0c\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\u5417?",
        "trace_steps": [],
    })

    assert result["intent"] == "price_protection"
    assert result["skill"] == "aftersales"


def test_price_protection_with_order_can_query_order():
    result = response_strategy_router({
        "intent": "price_protection",
        "risk_level": "low",
        "order_id": "6926666820903533935",
        "slots": {"identifier_type": "platform_trade_id", "platform_trade_id": "6926666820903533935"},
        "trace_steps": [],
    })

    assert result["response_strategy"] == "aftersales"
    assert result["answer_mode"] == "aftersales_policy"
    assert "jst_lookup_outbound_tool" in result["required_tools"]
    assert "template_select_tool" in result["allowed_tools"]


def test_price_protection_reply_gives_next_steps():
    result = generate_reply({
        "normalized_message": "\u6211\u521a\u4e70\u5c31\u964d\u4ef7\u4e86\uff0c\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\u5417?",
        "customer_message": "\u6211\u521a\u4e70\u5c31\u964d\u4ef7\u4e86\uff0c\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\u5417?",
        "intent": "price_protection",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "order_id": "6926666820903533935",
        "slots": {"platform_trade_id": "6926666820903533935"},
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert result["answer_mode"] == "policy_grounded_answer"
    assert "\u6211\u7684\u670d\u52a1" in reply
    assert "\u81ea\u52a9\u7533\u8bf7\u4ef7\u4fdd" in reply
    assert "\u540c\u6b3e\u540c\u7ec4\u5408" in reply
    assert "\u622a\u56fe" in reply
    assert "\u7a0d\u540e\u4f1a\u8054\u7cfb" not in reply

