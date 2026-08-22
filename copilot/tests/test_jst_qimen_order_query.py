import hashlib


def _configured_client(monkeypatch, response):
    from app.integrations.jst.qimen_order_query import QimenOrderClient

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return response

    def post(url, *, data, timeout):
        captured.update({"url": url, "data": dict(data), "timeout": timeout})
        return Response()

    monkeypatch.setenv("COPILOT_QIMEN_APP_KEY", "app-key")
    monkeypatch.setenv("COPILOT_QIMEN_APP_SECRET", "app-secret")
    monkeypatch.setenv("COPILOT_QIMEN_CUSTOMER_ID", "customer-route")
    monkeypatch.setenv(
        "COPILOT_QIMEN_ROUTER_URL",
        "https://example.api.taobao.com/router/qm",
    )
    return QimenOrderClient(post=post, now=lambda: "2026-08-22 12:00:00"), captured


def test_qimen_client_uses_top_signature_and_exact_order_query(monkeypatch):
    client, captured = _configured_client(monkeypatch, {"code": 0, "datas": []})

    client.query_order("platform-order-ref", shop_id="provider-store")

    data = captured["data"]
    assert data["method"] == "jushuitan.order.list.query"
    assert data["target_app_key"] == "23060081"
    assert data["customer_id"] == "customer-route"
    assert data["so_ids"] == "platform-order-ref"
    assert data["shop_id"] == "provider-store"
    unsigned = {key: value for key, value in data.items() if key != "sign" and value}
    source = "app-secret" + "".join(
        f"{key}{value}" for key, value in sorted(unsigned.items())
    ) + "app-secret"
    assert data["sign"] == hashlib.md5(source.encode("utf-8")).hexdigest().upper()


def test_qimen_lookup_returns_only_exact_order_and_product_identity(monkeypatch):
    from app.integrations.jst.qimen_order_query import lookup_qimen_order_by_platform_trade_id

    response = {
        "jushuitan_order_list_query_response": {
            "result": {
                "code": 0,
                "datas": [
                    {
                        "o_id": "internal-ref",
                        "so_id": "platform-order-ref",
                        "status": "Sent",
                        "l_id": "tracking-ref",
                        "receiver_name": "must-not-leak",
                        "receiver_address": "must-not-leak",
                        "shop_buyer_id": "must-not-leak",
                        "items": [
                            {
                                "sku_id": "sku-ref",
                                "i_id": "item-ref",
                                "name": "internal product name",
                                "qty": 1,
                                "properties_value": "white",
                            }
                        ],
                    }
                ],
            }
        }
    }
    client, _captured = _configured_client(monkeypatch, response)

    result = lookup_qimen_order_by_platform_trade_id(
        "platform-order-ref",
        shop_id="provider-store",
        client=client,
    )

    assert result["found"] is True
    assert result["endpoint"] == "jushuitan.order.list.query"
    assert result["data"] == {
        "o_id": "internal-ref",
        "so_id": "platform-order-ref",
        "outer_so_id": "platform-order-ref",
        "status": "Sent",
        "logistics_company": "",
        "l_id": "tracking-ref",
        "send_date": "",
        "sign_time": "",
        "items": [
            {
                "sku_id": "sku-ref",
                "i_id": "item-ref",
                "name": "internal product name",
                "qty": 1,
                "properties_value": "white",
                "shop_sku_id": "",
                "shop_i_id": "",
            }
        ],
    }


def test_qimen_lookup_rejects_non_matching_order_row(monkeypatch):
    from app.integrations.jst.qimen_order_query import lookup_qimen_order_by_platform_trade_id

    client, _captured = _configured_client(
        monkeypatch,
        {"code": 0, "datas": [{"so_id": "different-order", "items": []}]},
    )

    result = lookup_qimen_order_by_platform_trade_id(
        "platform-order-ref",
        client=client,
    )

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "not_found"


def test_qimen_lookup_reports_missing_configuration_without_network(monkeypatch):
    from app.integrations.jst.qimen_order_query import lookup_qimen_order_by_platform_trade_id

    for key in (
        "COPILOT_QIMEN_APP_KEY",
        "COPILOT_QIMEN_APP_SECRET",
        "COPILOT_QIMEN_CUSTOMER_ID",
        "COPILOT_QIMEN_ROUTER_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    result = lookup_qimen_order_by_platform_trade_id("platform-order-ref")

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "provider_not_configured"
    assert result["error_code"] == "qimen_not_configured"


def test_qimen_client_rejects_non_taobao_router_host(monkeypatch):
    from app.integrations.jst.qimen_order_query import QimenOrderClient

    monkeypatch.setenv("COPILOT_QIMEN_APP_KEY", "app-key")
    monkeypatch.setenv("COPILOT_QIMEN_APP_SECRET", "app-secret")
    monkeypatch.setenv("COPILOT_QIMEN_CUSTOMER_ID", "customer-route")
    monkeypatch.setenv("COPILOT_QIMEN_ROUTER_URL", "https://untrusted.example/router/qm")

    assert QimenOrderClient().is_configured() is False


def test_provider_router_keeps_qimen_platform_order_off_generic_jst(monkeypatch):
    from app.integrations.jst.order_query_router import lookup_order_by_provider

    calls = []
    monkeypatch.setattr(
        "app.integrations.jst.qimen_order_query.lookup_qimen_order_by_platform_trade_id",
        lambda identifier, **kwargs: calls.append((identifier, kwargs)) or {
            "found": False,
            "safe_fallback_reason": "provider_not_configured",
        },
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generic JST must not run for a Qimen-routed platform order")
        ),
    )

    result = lookup_order_by_provider(
        "platform-order-ref",
        "platform_trade_id",
        provider="qimen",
        shop_ref="logical-store",
        shop_id="provider-store",
        exhaustive=False,
    )

    assert result["safe_fallback_reason"] == "provider_not_configured"
    assert calls == [
        (
            "platform-order-ref",
            {"shop_ref": "logical-store", "shop_id": "provider-store"},
        )
    ]


def test_provider_router_preserves_generic_jst_for_other_stores(monkeypatch):
    from app.integrations.jst.order_query_router import lookup_order_by_provider

    captured = {}

    def fake_generic(identifier, identifier_type, **kwargs):
        captured.update({
            "identifier": identifier,
            "identifier_type": identifier_type,
            **kwargs,
        })
        return {"found": False, "safe_fallback_reason": "not_found"}

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_generic,
    )

    lookup_order_by_provider(
        "platform-order-ref",
        "platform_trade_id",
        provider="jst_standard",
        shop_id="provider-store",
        exhaustive=False,
    )

    assert captured == {
        "identifier": "platform-order-ref",
        "identifier_type": "platform_trade_id",
        "shop_id": "provider-store",
        "exhaustive": False,
    }
