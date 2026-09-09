import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_unknown_identifier_falls_back_to_outer_so_id_scan(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "5118207015382036103"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            if params.get("o_ids") or params.get("so_ids"):
                return {"data": {"orders": []}}
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "1636367",
                            "so_id": "SHOP-1",
                            "outer_so_id": target,
                            "status": "WaitConfirm",
                            "created": "2026-06-01 12:20:03",
                            "pay_date": "2026-06-01 12:20:26",
                            "items": [{"name": "test item", "qty": 1}],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_identifier(target, "unknown_identifier")

    assert result["found"] is True
    assert result["query_type"] == "unknown->outer_so_id_scan"
    assert result["endpoint"] == "orders/single/query"
    assert result["data"]["o_id"] == "1636367"
    assert result["data"]["outer_so_id"] == target
    assert any(
        endpoint == "orders/single/query"
        and not params.get("o_ids")
        and not params.get("so_ids")
        for endpoint, params in calls
    )


def test_unknown_identifier_uses_sales_outbound_before_outer_scan(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "5118207015382036103"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            if endpoint == "orders/out/simple/query":
                return {
                    "data": {
                        "datas": [
                            {
                                "io_id": "1368759",
                                "o_id": "1636367",
                                "status": "Confirmed",
                                "io_date": "2026-06-01 13:22:39",
                                "logistics_company": "SF",
                                "l_id": "SF0229477422177",
                                "items": [{"name": "cabinet", "outer_oi_id": target, "qty": 1}],
                            }
                        ]
                    }
                }
            return {"data": {"orders": []}}

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_identifier(target, "unknown_identifier")

    assert result["found"] is True
    assert result["endpoint"] == "orders/out/simple/query"
    assert result["query_type"] == "unknown->outbound_so_id"
    assert result["data"]["o_id"] == "1636367"
    assert result["data"]["outer_so_id"] == target
    assert calls[-1][0] == "orders/out/simple/query"


def test_platform_trade_id_falls_back_to_same_order_id(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "6926666820903533935"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            if endpoint == "orders/out/simple/query":
                return {"data": {"datas": []}}
            if params.get("o_ids") == [target]:
                return {
                    "data": {
                        "orders": [
                            {
                                "o_id": target,
                                "so_id": target,
                                "status": "WaitConfirm",
                                "logistics_company": "DBKD",
                                "l_id": "DPK379205847601",
                                "items": [{"name": "一号小熊床护栏", "sku_id": "YH_TEST", "qty": 1}],
                            }
                        ]
                    }
                }
            return {"data": {"orders": []}}

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_identifier(target, "platform_trade_id")

    assert result["found"] is True
    assert result["query_type"] == "platform_trade_id->same_order_id"
    assert result["data"]["o_id"] == target
    assert result["data"]["items"][0]["name"] == "一号小熊床护栏"
    assert any(endpoint == "orders/out/simple/query" for endpoint, _ in calls)
    assert any(params.get("o_ids") == [target] for _, params in calls)


def test_platform_trade_id_falls_back_to_historical_so_id(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "6926666820903533935"
    calls = []
    so_id_calls = 0

    class FakeJSTClient:
        def call(self, endpoint, params):
            nonlocal so_id_calls
            calls.append((endpoint, params))
            if endpoint == "orders/out/simple/query":
                return {"data": {"datas": []}}
            if params.get("o_ids") == [target]:
                return {"data": {"orders": []}}
            if params.get("so_ids") == [target]:
                so_id_calls += 1
                if so_id_calls >= 2:
                    return {
                        "data": {
                            "orders": [
                                {
                                    "o_id": "1636367",
                                    "so_id": target,
                                    "status": "Sent",
                                    "logistics_company": "DBKD",
                                    "l_id": "DPK379205847601",
                                    "items": [{"name": "一号小熊床护栏", "sku_id": "YH_TEST", "qty": 1}],
                                }
                            ]
                        }
                    }
                return {"data": {"orders": []}}
            return {"data": {"orders": []}}

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_identifier(target, "platform_trade_id")

    assert result["found"] is True
    assert result["query_type"] == "platform_trade_id->so_id_history_fallback"
    assert result["data"]["so_id"] == target
    assert result["data"]["items"][0]["name"] == "一号小熊床护栏"
    assert so_id_calls >= 2
    assert any(path["query_type"] == "platform_order_id_history" for path in result["attempted_paths"])


def test_unknown_identifier_not_found_checks_outer_so_id_before_tracking(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            if endpoint == "logistic/query":
                return {"data": {"orders": []}}
            if params.get("o_ids") or params.get("so_ids"):
                return {"data": {"orders": []}}
            return {"data": {"orders": [{"outer_so_id": "OTHER"}]}}

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_identifier("5118207015382036103", "unknown_identifier")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "not_found_by_any_path"
    outer_scan_index = next(
        i for i, (endpoint, params) in enumerate(calls)
        if endpoint == "orders/single/query" and not params.get("o_ids") and not params.get("so_ids")
    )
    tracking_index = next(i for i, (endpoint, _) in enumerate(calls) if endpoint == "logistic/query")
    assert outer_scan_index < tracking_index


def test_unknown_identifier_propagates_provider_failure_instead_of_not_found(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    failure = {
        "found": False,
        "endpoint": "orders/single/query",
        "query_type": "mock",
        "duration_ms": 1,
        "error_code": "config_missing",
        "error_message": "credentials unavailable",
        "safe_fallback_reason": "jst_not_configured",
    }

    monkeypatch.setattr(live_query, "lookup_outbound_by_so_id", lambda _value: dict(failure))
    monkeypatch.setattr(live_query, "lookup_order_by_order_id", lambda _value: dict(failure))
    monkeypatch.setattr(live_query, "lookup_order_by_platform_order_id", lambda _value: dict(failure))
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_platform_order_id_history",
        lambda _value: dict(failure),
    )
    monkeypatch.setattr(live_query, "lookup_order_by_outer_so_id", lambda _value: dict(failure))
    monkeypatch.setattr(live_query, "lookup_logistics_by_tracking_no", lambda _value: dict(failure))

    result = live_query.lookup_order_by_identifier(
        "9999999999999999999",
        "unknown_identifier",
    )

    assert result["found"] is False
    assert result["error_code"] == "config_missing"
    assert result["safe_fallback_reason"] == "jst_not_configured"
    assert len(result["attempted_paths"]) == 6


def test_outbound_direct_hint_matches_child_order_after_exact_field_verification(monkeypatch):
    """A direct outbound filter is only a hint; an exact child-order field still proves identity."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "marketplace-child-order"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            assert endpoint == "orders/out/simple/query"
            return {
                "data": {
                    "datas": [
                        {
                            "o_id": "internal-order",
                            "status": "Sent",
                            "items": [
                                {
                                    "sku_id": "SKU-OTHER",
                                    "i_id": "PRODUCT-OTHER",
                                    "name": "other product",
                                    "outer_oi_id": "other-child-order",
                                    "qty": 1,
                                },
                                {
                                    "sku_id": "SKU-CHILD",
                                    "i_id": "PRODUCT-CHILD",
                                    "name": "matched product",
                                    "outer_oi_id": target,
                                    "qty": 1,
                                },
                            ],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_outbound_by_so_id(target)

    assert result["found"] is True
    assert len(calls) == 1
    assert calls[0][1]["so_ids"] == [target]
    assert result["data"]["matched_item"]["sku_id"] == "SKU-CHILD"


def test_outbound_scoped_scan_reaches_second_page_after_direct_hint_miss(monkeypatch):
    """A known shop may narrow a paginated scan, but never replaces the exact identifier check."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "marketplace-child-order"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            if endpoint == "shops/query":
                return {"data": {"datas": [{"shop_id": "shop-17", "shop_name": "Target Store"}]}}
            assert endpoint == "orders/out/simple/query"
            assert params["shop_id"] == "shop-17"
            if params.get("so_ids"):
                return {"data": {"datas": []}}
            if params["page_index"] == 1:
                return {"data": {"datas": [{"o_id": f"other-{index}"} for index in range(100)]}}
            return {
                "data": {
                    "datas": [{
                        "o_id": "internal-order",
                        "shop_id": "shop-17",
                        "items": [{"sku_id": "SKU-CHILD", "outer_oi_id": target, "qty": 1}],
                    }]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_outbound_by_so_id(target, shop_name="Target Store")

    assert result["found"] is True
    outbound_calls = [params for endpoint, params in calls if endpoint == "orders/out/simple/query"]
    assert outbound_calls[0]["so_ids"] == [target]
    assert [params.get("page_index") for params in outbound_calls[1:]] == [1, 2]
    assert result["data"]["matched_item"]["sku_id"] == "SKU-CHILD"


def test_outbound_refuses_ambiguous_shop_name_before_querying_orders(monkeypatch):
    """A display name that identifies multiple shops cannot select an order-search scope."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            assert endpoint == "shops/query"
            return {
                "data": {
                    "datas": [
                        {"shop_id": "shop-17", "shop_name": "Duplicate Store"},
                        {"shop_id": "shop-18", "shop_name": "Duplicate Store"},
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_outbound_by_so_id(
        "marketplace-child-order",
        shop_name="Duplicate Store",
    )

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "shop_scope_ambiguous"
    assert [endpoint for endpoint, _ in calls] == ["shops/query"]


def test_outbound_exact_lookup_rejects_unmatched_outbound_row(monkeypatch):
    """A non-empty sales-outbound response is not an identity proof by itself."""
    from app.integrations.jst import live_query

    live_query._cache.clear()

    class FakeJSTClient:
        def call(self, endpoint, params):
            assert endpoint == "orders/out/simple/query"
            return {
                "data": {
                    "datas": [
                        {
                            "o_id": "other-order",
                            "outer_so_id": "other-trade",
                            "items": [
                                {
                                    "sku_id": "SKU-OTHER",
                                    "outer_oi_id": "other-child-order",
                                    "qty": 1,
                                }
                            ],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_outbound_by_so_id("marketplace-child-order")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "outbound_identifier_not_matched"


def test_platform_order_history_rejects_a_nonmatching_first_row(monkeypatch):
    """History lookup must not turn an arbitrary returned order into a match."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "marketplace-order"

    class FakeJSTClient:
        def call(self, endpoint, params):
            assert endpoint == "orders/single/query"
            assert params["so_ids"] == [target]
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "other-order",
                            "so_id": "other-marketplace-order",
                            "items": [{"sku_id": "SKU-OTHER", "qty": 1}],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)
    monkeypatch.setattr(
        live_query,
        "_historical_modified_windows",
        lambda **_kwargs: [("2026-08-01 00:00:00", "2026-08-07 23:59:59")],
    )

    result = live_query.lookup_order_by_platform_order_id_history(target)

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "not_found_in_75d_history"


def test_outer_so_id_scan_rejects_substring_only_match(monkeypatch):
    """One identifier must never match merely because it is a substring."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "marketplace-order"

    class FakeJSTClient:
        def call(self, endpoint, params):
            assert endpoint == "orders/single/query"
            assert "so_ids" not in params
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "other-order",
                            "outer_so_id": f"prefix-{target}-suffix",
                            "items": [{"sku_id": "SKU-OTHER", "qty": 1}],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_outer_so_id(target)

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "outer_so_id_not_found_in_recent_orders"


def test_internal_order_lookup_rejects_a_nonmatching_returned_row(monkeypatch):
    """A non-empty o_ids response is not proof unless its o_id matches exactly."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "123456789012"

    class FakeJSTClient:
        def call(self, endpoint, params):
            assert endpoint == "orders/single/query"
            assert params["o_ids"] == [target]
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "other-internal-order",
                            "so_id": "other-store-order",
                            "items": [{"sku_id": "SKU-OTHER", "qty": 1}],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_order_id(target)

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "o_id_not_matched"


def test_platform_order_lookup_rejects_a_nonmatching_returned_row(monkeypatch):
    """A non-empty so_ids response is not proof unless its so_id matches exactly."""
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "marketplace-order-123"

    class FakeJSTClient:
        def call(self, endpoint, params):
            assert endpoint == "orders/single/query"
            assert params["so_ids"] == [target]
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "other-internal-order",
                            "so_id": "other-marketplace-order",
                            "items": [{"sku_id": "SKU-OTHER", "qty": 1}],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_platform_order_id(target)

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "so_id_not_matched"
