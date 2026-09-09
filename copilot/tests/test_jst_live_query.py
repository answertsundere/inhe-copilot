from __future__ import annotations


def test_live_order_lookup_surfaces_an_ip_allowlist_block_as_a_safe_reason(monkeypatch):
    from app.integrations.jst import live_query
    from app.integrations.jst.errors import JSTAPIError

    class FakeJSTClient:
        def call(self, _endpoint, _business):
            raise JSTAPIError(code=110, message="redacted", endpoint="orders/single/query")

    live_query._cache.clear()
    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_order_id("123456")

    assert result["found"] is False
    assert result["error_code"] == "jst_ip_allowlist_blocked"
    assert result["safe_fallback_reason"] == "jst_ip_allowlist_blocked"


def test_jst_live_query_uses_structured_unknown_sidebar_order_reference(monkeypatch):
    """Unknown sidebar identifiers use the existing bounded JST multi-path lookup."""
    from app.agent.nodes import jst_live_query as node

    calls = []

    def fake_lookup(identifier, identifier_type, **kwargs):
        calls.append((identifier, identifier_type, kwargs))
        return {
            "found": False,
            "safe_fallback_reason": "not_found",
            "duration_ms": 1,
            "endpoint": "",
            "query_type": "unknown_identifier",
            "attempted_paths": ["outbound"],
        }

    monkeypatch.setattr(node, "lookup_order_by_identifier", fake_lookup)
    reference = "opaque-sidebar-order-reference"
    result = node.jst_live_query(
        {
            "slots": {
                "order_id": reference,
                "possible_numeric_id": "",
                "identifier_type": "unknown_identifier",
            },
            "copilot_context": {
                "shop_id": "shop-test",
                "shop_name": "Scoped Test Shop",
            },
            "trace_steps": [],
        }
    )

    assert calls == [
        (
            reference,
            "unknown_identifier",
            {"shop_id": "shop-test", "shop_name": "Scoped Test Shop"},
        )
    ]
    assert result["used_fact_tool"] == "jst_live_query"
    assert all(
        reference not in str(step.get("summary") or "")
        for step in result["trace_steps"]
    )


def test_jst_live_query_promotes_a_verified_single_order_item_to_exact_product_identity(monkeypatch):
    """A successful exact JST lookup must make its sole SKU available to the existing pack."""
    from app.agent.nodes import jst_live_query as node

    def fake_lookup(_identifier, _identifier_type, **_kwargs):
        return {
            "found": True,
            "endpoint": "orders/out/simple/query",
            "query_type": "outbound_so_id",
            "duration_ms": 1,
            "attempted_paths": ["outbound"],
            "data": {
                "o_id": "internal-order",
                "items": [
                    {
                        "name": "internal-product",
                        "sku_id": "SKU-EXACT-001",
                        "i_id": "ITEM-EXACT-001",
                        "qty": 1,
                    }
                ],
            },
        }

    monkeypatch.setattr(node, "lookup_order_by_identifier", fake_lookup)

    result = node.jst_live_query({
        "slots": {
            "order_id": "opaque-sidebar-order-reference",
            "identifier_type": "unknown_identifier",
        },
        "copilot_context": {},
        "trace_steps": [],
    })

    identity = result["order_product_identity"]
    assert identity["status"] == "resolved"
    assert identity["source"] == "jst_order_items"
    assert identity["reason"] == "single_order_item"
    assert identity["sku_id"] == "SKU-EXACT-001"
    assert result["slots"]["sku_code"] == "SKU-EXACT-001"
    assert result["product_identity_source"] == "jst_order_items"
    assert result["trace_steps"][-1]["order_product_identity_status"] == "resolved"


def test_jst_live_query_promotes_an_integration_verified_exact_item_from_a_multi_item_order(monkeypatch):
    """An exact JST order-item identifier is stronger than multi-item text matching."""
    from app.agent.nodes import jst_live_query as node

    def fake_lookup(_identifier, _identifier_type, **_kwargs):
        return {
            "found": True,
            "endpoint": "orders/out/simple/query",
            "query_type": "outbound_so_id",
            "duration_ms": 1,
            "attempted_paths": ["outbound"],
            "data": {
                "o_id": "internal-order",
                "items": [
                    {"name": "product-a", "sku_id": "SKU-A", "i_id": "ITEM-A", "qty": 1},
                    {"name": "product-b", "sku_id": "SKU-B", "i_id": "ITEM-B", "qty": 1},
                ],
                "matched_item": {"name": "product-b", "sku_id": "SKU-B", "i_id": "ITEM-B", "qty": 1},
                "matched_item_reason": "exact_jst_order_item",
            },
        }

    monkeypatch.setattr(node, "lookup_order_by_identifier", fake_lookup)

    result = node.jst_live_query({
        "slots": {
            "order_id": "opaque-sidebar-order-reference",
            "identifier_type": "unknown_identifier",
        },
        "copilot_context": {},
        "trace_steps": [],
    })

    assert result["order_product_identity"]["reason"] == "exact_jst_order_item"
    assert result["slots"]["sku_code"] == "SKU-B"
    assert result["trace_steps"][-1]["order_product_identity_status"] == "resolved"


def test_jst_live_query_does_not_promote_an_ambiguous_multi_item_order(monkeypatch):
    """The live JST bridge must not choose a SKU from a multi-item order by position."""
    from app.agent.nodes import jst_live_query as node

    def fake_lookup(_identifier, _identifier_type, **_kwargs):
        return {
            "found": True,
            "endpoint": "orders/out/simple/query",
            "query_type": "outbound_so_id",
            "duration_ms": 1,
            "attempted_paths": ["outbound"],
            "data": {
                "o_id": "internal-order",
                "items": [
                    {"name": "product-a", "sku_id": "SKU-A", "i_id": "ITEM-A", "qty": 1},
                    {"name": "product-b", "sku_id": "SKU-B", "i_id": "ITEM-B", "qty": 1},
                ],
            },
        }

    monkeypatch.setattr(node, "lookup_order_by_identifier", fake_lookup)

    result = node.jst_live_query({
        "slots": {
            "order_id": "opaque-sidebar-order-reference",
            "identifier_type": "unknown_identifier",
        },
        "copilot_context": {},
        "trace_steps": [],
    })

    assert "order_product_identity" not in result
    assert "slots" not in result
    assert result["trace_steps"][-1]["order_product_identity_status"] == "ambiguous"
