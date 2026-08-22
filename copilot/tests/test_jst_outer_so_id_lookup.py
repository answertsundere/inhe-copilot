import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_outbound_exact_lookup_uses_shop_without_recent_time_window(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "5118207015382036103"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            return {
                "data": {
                    "datas": [
                        {
                            "o_id": "1636367",
                            "shop_id": "13221776",
                            "status": "Confirmed",
                            "items": [{"outer_oi_id": target, "name": "test item"}],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_outbound_by_so_id(target, shop_id="13221776")

    assert result["found"] is True
    assert result["data"]["shop_id"] == "13221776"
    assert calls == [
        (
            "orders/out/simple/query",
            {
                "page_index": 1,
                "page_size": 20,
                "so_ids": [target],
                "shop_id": "13221776",
            },
        )
    ]


def test_outbound_exact_lookup_rejects_other_shop_or_other_identifier(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "5118207015382036103"

    class FakeJSTClient:
        def call(self, endpoint, params):
            return {
                "data": {
                    "datas": [
                        {
                            "o_id": "wrong-shop",
                            "shop_id": "99999999",
                            "items": [{"outer_oi_id": target}],
                        },
                        {
                            "o_id": "wrong-order",
                            "shop_id": "13221776",
                            "items": [{"outer_oi_id": "OTHER"}],
                        },
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_outbound_by_so_id(target, shop_id="13221776")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "not_found"


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


def test_outer_so_id_scan_continues_past_legacy_five_page_limit(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "PLATFORM-ORDER-TARGET"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            assert endpoint == "orders/single/query"
            calls.append(dict(params))
            page_index = params["page_index"]
            if page_index < 7:
                return {
                    "data": {
                        "orders": [
                            {
                                "o_id": f"order-{page_index}-{row_index}",
                                "outer_so_id": f"OTHER-{page_index}-{row_index}",
                            }
                            for row_index in range(100)
                        ]
                    }
                }
            if page_index == 7:
                return {
                    "data": {
                        "orders": [
                            {
                                "o_id": "matched-order",
                                "outer_so_id": target,
                                "items": [{"name": "matched item"}],
                            }
                        ]
                    }
                }
            raise AssertionError("scan must stop after the target is found")

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_outer_so_id(target)

    assert result["found"] is True
    assert result["data"]["o_id"] == "matched-order"
    assert [call["page_index"] for call in calls] == list(range(1, 8))
    assert result["scanned_pages"] == 7


def test_outer_so_id_scan_fails_closed_when_provider_repeats_a_full_page(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    calls = []
    repeated_orders = [
        {"o_id": f"same-{row_index}", "outer_so_id": f"OTHER-{row_index}"}
        for row_index in range(100)
    ]

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append(dict(params))
            return {"data": {"orders": repeated_orders}}

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_outer_so_id("MISSING-TARGET")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "pagination_stalled"
    assert result["error_code"] == "pagination_stalled"
    assert [call["page_index"] for call in calls] == [1, 2]


def test_outer_so_id_scan_matches_exact_item_level_platform_identifier(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "ITEM-LEVEL-PLATFORM-ORDER"

    class FakeJSTClient:
        def call(self, endpoint, params):
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "internal-order",
                            "outer_so_id": "",
                            "items": [
                                {
                                    "outer_oi_id": target,
                                    "sku_id": "GENERIC-SKU",
                                    "name": "generic item",
                                }
                            ],
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_outer_so_id(target)

    assert result["found"] is True
    assert result["data"]["o_id"] == "internal-order"
    assert result["data"]["outer_so_id"] == target


def test_platform_trade_dispatch_passes_explicit_jst_shop_to_complete_scan(monkeypatch):
    from app.integrations.jst import live_query

    miss = {"found": False, "duration_ms": 0, "safe_fallback_reason": "not_found"}
    monkeypatch.setattr(live_query, "lookup_outbound_by_so_id", lambda *args, **kwargs: dict(miss))
    monkeypatch.setattr(live_query, "lookup_order_by_order_id", lambda *args, **kwargs: dict(miss))
    monkeypatch.setattr(live_query, "lookup_order_by_platform_order_id", lambda *args, **kwargs: dict(miss))
    monkeypatch.setattr(live_query, "lookup_order_by_platform_order_id_history", lambda *args, **kwargs: dict(miss))
    captured = []

    def fake_outer(identifier, *, max_pages=None, shop_id=""):
        captured.append((identifier, max_pages, shop_id))
        return dict(miss)

    monkeypatch.setattr(live_query, "lookup_order_by_outer_so_id", fake_outer)

    result = live_query.lookup_order_by_identifier(
        "PLATFORM-ORDER",
        "platform_trade_id",
        shop_id="JST-SHOP-42",
    )

    assert result["found"] is False
    assert captured == [("PLATFORM-ORDER", None, "JST-SHOP-42")]


def test_tmall_platform_trade_id_uses_sales_outbound_only(monkeypatch):
    from app.integrations.jst import live_query

    calls = []

    def fail_unsupported(*_args, **_kwargs):
        raise AssertionError("Tmall ordinary order API is unsupported")

    def fake_outbound(identifier, *, shop_id=""):
        calls.append((identifier, shop_id))
        return {
            "found": False,
            "endpoint": "orders/out/simple/query",
            "query_type": "outbound_so_id",
            "duration_ms": 17,
            "safe_fallback_reason": "not_found",
        }

    monkeypatch.setattr(live_query, "lookup_outbound_by_so_id", fake_outbound)
    monkeypatch.setattr(live_query, "lookup_order_by_order_id", fail_unsupported)
    monkeypatch.setattr(live_query, "lookup_order_by_platform_order_id", fail_unsupported)
    monkeypatch.setattr(live_query, "lookup_order_by_platform_order_id_history", fail_unsupported)
    monkeypatch.setattr(live_query, "lookup_order_by_outer_so_id", fail_unsupported)

    result = live_query.lookup_order_by_identifier(
        "PLATFORM-ORDER",
        "platform_trade_id",
        shop_id="JST-SHOP-42",
        shop_platform="tmall",
    )

    assert calls == [("PLATFORM-ORDER", "JST-SHOP-42")]
    assert result["found"] is False
    assert result["lookup_complete"] is True
    assert result["safe_fallback_reason"] == "sales_outbound_record_not_visible"
    assert result["source_capability"] == "sales_outbound_only"
    assert [path["query_type"] for path in result["attempted_paths"]] == ["outbound_so_id"]


def test_tmall_platform_trade_id_preserves_found_sales_outbound(monkeypatch):
    from app.integrations.jst import live_query

    monkeypatch.setattr(
        live_query,
        "lookup_outbound_by_so_id",
        lambda identifier, *, shop_id="": {
            "found": True,
            "endpoint": "orders/out/simple/query",
            "query_type": "outbound_so_id",
            "duration_ms": 11,
            "data": {"so_id": identifier, "shop_id": shop_id},
        },
    )

    result = live_query.lookup_order_by_identifier(
        "PLATFORM-ORDER",
        "platform_trade_id",
        shop_id="JST-SHOP-42",
        shop_platform="tmall",
    )

    assert result["found"] is True
    assert result["query_type"] == "platform_trade_id->outbound_so_id"
    assert result["source_capability"] == "sales_outbound_only"


def test_outer_so_id_scan_rejects_matching_identifier_from_another_shop(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    target = "SAME-PLATFORM-ORDER"
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append(dict(params))
            return {
                "data": {
                    "orders": [
                        {
                            "o_id": "wrong-shop-order",
                            "outer_so_id": target,
                            "shop_id": "OTHER-SHOP",
                        }
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_outer_so_id(target, shop_id="EXPECTED-SHOP")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "outer_so_id_not_found_in_complete_recent_scan"
    assert calls[0]["shop_id"] == "EXPECTED-SHOP"
