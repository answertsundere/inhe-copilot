from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.generate_logistics_reply import generate_logistics_reply


def test_intercept_request_routes_to_logistics():
    result = detect_intent({
        "normalized_message": "\u53ef\u4ee5\u5e2e\u6211\u62e6\u622a\u5417",
        "trace_steps": [],
    })

    assert result["intent"] == "logistics_eta"


def test_shipped_intercept_uses_courier_not_warehouse():
    result = generate_logistics_reply({
        "normalized_message": "\u53ef\u4ee5\u5e2e\u6211\u62e6\u622a\u5417",
        "intent": "logistics_eta",
        "order_status": "shipped",
        "order": {
            "items": [{"name": "\u4e00\u53f7\u5c0f\u9ca8\u5e8a\u62a4\u680f"}],
            "logistics_company": "\u5fb7\u90a6\u5feb\u9012",
            "l_id": "DPK379205847601",
            "send_date": "2026-05-27 08:40:43",
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "\u5feb\u9012\u5c1d\u8bd5\u62e6\u622a" in reply
    assert "\u4ed3\u5e93\u62e6\u622a" not in reply
    assert "\u4e0d\u80fd\u4fdd\u8bc1\u4e00\u5b9a" in reply


def test_unshipped_address_change_can_sync_warehouse():
    result = generate_logistics_reply({
        "normalized_message": "\u8fd8\u6ca1\u53d1\u7684\u8bdd\u53ef\u4ee5\u5e2e\u6211\u6539\u5730\u5740\u5417",
        "intent": "logistics_eta",
        "order_status": "pending_shipment",
        "order": {
            "items": [{"name": "\u4e00\u53f7\u5c0f\u9ca8\u5e8a\u62a4\u680f"}],
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "\u8fd8\u6ca1\u6709\u53d1\u51fa" in reply
    assert "\u540c\u6b65\u4ed3\u5e93" in reply
