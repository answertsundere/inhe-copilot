from __future__ import annotations


def test_lookup_product_by_i_id_uses_array_i_ids(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            return {
                "data": {
                    "datas": [
                        {"i_id": "YH88K01", "name": "英禾宝宝围栏"},
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_product_by_i_id("YH88K01")

    assert result["found"] is True
    assert calls == [
        (
            "mall/item/query",
            {"page_index": 1, "page_size": 10, "i_ids": ["YH88K01"]},
        )
    ]


def test_lookup_product_by_name_uses_time_window_not_keyword_params(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            assert "name" not in params
            assert "item_name" not in params
            assert "keyword" not in params
            assert params["modified_begin"]
            assert params["modified_end"]
            if endpoint == "skumap/query":
                return {
                    "data": {
                        "datas": [
                            {
                                "i_id": "YH88K01",
                                "sku_id": "YH88K01B01S01",
                                "shop_i_id": "100000000000",
                                "name": "英禾宝宝游戏围栏加厚爬行垫配套围栏",
                            },
                        ]
                    }
                }
            return {"data": {"datas": []}}

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_product_by_name("英禾宝宝游戏围栏加厚爬行垫配套围栏")

    assert result["found"] is True
    assert result["endpoint"] == "skumap/query"
    assert calls[0][0] == "skumap/query"
    assert calls[0][1]["page_size"] == 100


def test_lookup_product_by_sku_falls_back_to_recent_scan(monkeypatch):
    from app.integrations.jst import live_query
    from app.integrations.jst.errors import JSTAPIError

    live_query._cache.clear()
    calls = []

    class FakeJSTClient:
        def call(self, endpoint, params):
            calls.append((endpoint, params))
            if "sku_ids" in params:
                raise JSTAPIError(code=150, message="数组的反序列化不支持类型 System.String", endpoint=endpoint)
            return {
                "data": {
                    "datas": [
                        {"sku_id": "YH88K01B01S26", "i_id": "YH88K01", "name": "一号喂养柜"},
                    ]
                }
            }

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_product_by_sku("YH88K01B01S26")

    assert result["found"] is True
    assert result["query_type"] == "sku_recent_modified_scan"
    assert calls[0][1]["sku_ids"] == ["YH88K01B01S26"]
    assert "modified_begin" in calls[1][1]
    assert "modified_end" in calls[1][1]


def test_lookup_order_by_order_id_skips_non_numeric_o_id(monkeypatch):
    from app.integrations.jst import live_query

    live_query._cache.clear()

    class FakeJSTClient:
        def call(self, endpoint, params):
            raise AssertionError("non-numeric o_id should not call JST")

    monkeypatch.setattr(live_query, "JSTClient", FakeJSTClient)

    result = live_query.lookup_order_by_order_id("TB20260610ABC")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "non_numeric_o_id"
