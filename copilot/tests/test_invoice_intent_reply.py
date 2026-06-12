from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.response_strategy_router import response_strategy_router


def test_invoice_request_routes_to_invoice_intent():
    result = detect_intent({
        "normalized_message": "\u8fd9\u4e2a\u8ba2\u5355\u53ef\u4ee5\u5f00\u7535\u5b50\u53d1\u7968\u5417?",
        "trace_steps": [],
    })

    assert result["intent"] == "invoice"
    assert result["skill"] == "aftersales"


def test_invoice_with_order_can_query_order_status():
    result = response_strategy_router({
        "intent": "invoice",
        "risk_level": "low",
        "order_id": "6926666820903533935",
        "slots": {"identifier_type": "platform_trade_id", "platform_trade_id": "6926666820903533935"},
        "trace_steps": [],
    })

    assert result["response_strategy"] == "aftersales"
    assert result["answer_mode"] == "aftersales_policy"
    assert "jst_lookup_outbound_tool" in result["required_tools"]
    assert "template_select_tool" in result["allowed_tools"]


def test_invoice_reply_is_policy_specific_not_general():
    result = generate_reply({
        "normalized_message": "\u8fd9\u4e2a\u8ba2\u5355\u53ef\u4ee5\u5f00\u7535\u5b50\u53d1\u7968\u5417?",
        "customer_message": "\u8fd9\u4e2a\u8ba2\u5355\u53ef\u4ee5\u5f00\u7535\u5b50\u53d1\u7968\u5417?",
        "intent": "invoice",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "order_id": "6926666820903533935",
        "slots": {"platform_trade_id": "6926666820903533935"},
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert result["answer_mode"] == "policy_grounded_answer"
    assert "\u7535\u5b50\u53d1\u7968" in reply
    assert "\u5b9e\u4ed8\u91d1\u989d" in reply
    assert "\u62ac\u5934" in reply
    assert "\u7a0e\u53f7" in reply
    assert "\u6211\u5728\u7684" not in reply

