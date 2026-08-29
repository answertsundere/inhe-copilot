from __future__ import annotations


def test_jst_tool_result_hydrates_single_item_product_identity():
    from app.agent.tools.executor import _extract_legacy_fields

    fields = _extract_legacy_fields(
        {
            "jst_lookup_order_tool": {
                "found": True,
                "o_id": "ORDER-EXAMPLE",
                "status": "已发货",
                "items": [
                    {
                        "name": "示例收纳柜",
                        "sku_id": "SKU-EXAMPLE-01",
                        "i_id": "PRODUCT-EXAMPLE-01",
                        "qty": 1,
                    }
                ],
            }
        },
        {"slots": {}, "trace_steps": []},
    )

    identity = fields["order_product_identity"]
    assert identity["status"] == "resolved"
    assert identity["source"] == "jst_order_items"
    assert identity["internal_product_name"] == "示例收纳柜"
    assert identity["sku_id"] == "SKU-EXAMPLE-01"
    assert identity["i_id"] == "PRODUCT-EXAMPLE-01"
    assert fields["matched_product_name"] == "示例收纳柜"
    assert fields["slots"]["sku_code"] == "SKU-EXAMPLE-01"
