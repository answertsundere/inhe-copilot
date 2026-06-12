from __future__ import annotations


def test_graph_order_product_identity_reaches_debug(monkeypatch):
    from app.agent.context.context_store import context_store
    from app.agent.graph import customer_service_graph

    context_store.clear()

    def fake_lookup(identifier, identifier_type):
        return {
            "found": True,
            "endpoint": "orders/out/simple/query",
            "duration_ms": 3,
            "data": {
                "o_id": "1636367",
                "so_id": "5118207015382036103",
                "items": [
                    {"name": "一号喂养柜", "sku_id": "SKU-YG-001", "i_id": "I-YG-001", "qty": 1}
                ],
            },
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = customer_service_graph.invoke({
        "customer_message": "我没找到，怎么让他自动感应",
        "conversation_id": "graph-order-product",
        "order_id": "5118207015382036103",
        "copilot_context": {
            "order_candidates": [
                {"value": "5118207015382036103", "type": "platform_trade_id_candidate"}
            ],
            "product_candidates": [{"value": "平台标题 英禾喂养多功能收纳柜"}],
        },
        "trace_steps": [],
    })

    assert result["matched_product_name"] == "一号喂养柜"
    assert result["order_product_identity"]["sku_id"] == "SKU-YG-001"
    assert result["evidence_debug"]["order_product_identity"]["matched_product_name"] == "一号喂养柜"
    assert any(t.get("node") == "order_product_resolver" for t in result["trace_steps"])

    cached = context_store.get("graph-order-product")
    assert cached["order_product_identity"]["matched_product_name"] == "一号喂养柜"
