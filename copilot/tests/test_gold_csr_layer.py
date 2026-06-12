import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _invoke(message: str, conversation_id: str = "test_gold_csr") -> dict:
    from app.agent.graph import customer_service_graph

    return customer_service_graph.invoke({
        "customer_message": message,
        "conversation_id": conversation_id,
        "trace_steps": [],
    })


def test_eta_certainty_sets_boundary_and_asks_for_order():
    from app.agent.context.context_store import context_store

    context_store.clear()
    result = _invoke("明天能不能一定到？", "eta_boundary")
    reply = result["suggested_reply"]

    assert result["customer_concern"] == "wants_eta_certainty"
    assert result["reply_goal"] == "explain_no_guarantee"
    assert "无法" in reply or "不能" in reply
    assert "订单号" in reply or "物流单号" in reply
    assert "保证一定" not in reply


def test_product_material_unknown_clarifies_without_fabricating():
    from app.agent.context.context_store import context_store

    context_store.clear()
    result = _invoke("这个是不是实木的？", "material_unknown")
    reply = result["suggested_reply"]

    assert result["customer_concern"] == "worries_material"
    assert result["reply_goal"] == "clarify_product_identity"
    assert "商品链接" in reply or "截图" in reply or "SKU" in reply
    assert "是实木" not in reply
    assert "不是实木" not in reply


def test_complaint_deescalates_and_requires_human_review():
    from app.agent.context.context_store import context_store

    context_store.clear()
    result = _invoke("再不处理我就投诉平台", "complaint")
    reply = result["suggested_reply"]

    assert result["customer_concern"] == "angry_about_delay"
    assert result["reply_goal"] == "deescalate_complaint"
    assert result["requires_human_review"] is True
    assert reply
    assert "主管" in reply or "人工" in reply
    assert "赔偿" not in reply or "不会先承诺赔偿" in reply


def test_social_frustration_does_not_ask_for_order():
    from app.agent.context.context_store import context_store

    context_store.clear()
    result = _invoke("你是傻子吗", "social_frustration")
    reply = result["suggested_reply"]

    assert result["intent"] == "general"
    assert result["customer_concern"] == "social_frustration"
    assert result["reply_goal"] == "social_reply"
    assert "订单号" not in reply
    assert "商品名称" not in reply
    assert "问题截图" not in reply
    assert "具体问题" in reply or "重新按事实查" in reply


def test_sarcasm_does_not_ask_for_order():
    from app.agent.context.context_store import context_store

    context_store.clear()
    result = _invoke("你真是人才", "social_sarcasm")
    reply = result["suggested_reply"]

    assert result["customer_concern"] == "social_frustration"
    assert result["reply_goal"] == "social_reply"
    assert "订单号" not in reply
    assert "商品名称" not in reply
    assert "具体问题" in reply or "重新按事实查" in reply


def test_multi_turn_numeric_followup_uses_previous_order_request():
    from unittest.mock import patch
    from app.agent.context.context_store import context_store

    context_store.clear()
    first = _invoke("显示签收了但我没收到", "multi_delivery")
    assert first["reply_goal"] == "handle_delivery_not_received"
    assert first["requires_human_review"] is True

    mock_result = {
        "found": True,
        "data": {
            "o_id": "1636367",
            "outer_so_id": "5118207015382036103",
            "status": "Confirmed",
            "send_date": "2026-06-01 13:22:39",
            "logistics_company": "顺丰速运",
            "l_id": "SF0229477422177",
            "items": [{"name": "测试商品", "qty": 1}],
        },
        "source": "jst_live_mock",
        "endpoint": "orders/out/simple/query",
        "query_type": "unknown->outbound_so_id",
        "duration_ms": 1,
    }

    with patch("app.agent.nodes.jst_live_query.lookup_order_by_identifier", return_value=mock_result):
        second = _invoke("5118207015382036103", "multi_delivery")

    assert second["intent"] == "delivery_not_received"
    assert second["slots"]["identifier_type"] == "unknown_identifier"
    assert second["order_found"] is True
    assert second["reply_goal"] == "handle_delivery_not_received"
    assert second["requires_human_review"] is True
    assert "SF0229477422177" in second["suggested_reply"]
    assert "商品链接" not in second["suggested_reply"]
