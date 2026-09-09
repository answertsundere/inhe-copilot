from __future__ import annotations


def _result(*, found: bool, shop_id: str = "") -> dict:
    return {
        "found": found,
        "data": {"shop_id": shop_id} if found else None,
        "source": "jst_live",
        "endpoint": "orders/single/query",
        "query_type": "test",
        "duration_ms": 1,
        "safe_fallback_reason": "not_found" if not found else "",
    }


def test_unknown_identifier_does_not_admit_direct_result_from_another_shop(monkeypatch):
    """A selected store is a hard admission boundary for every lookup path."""
    from app.integrations.jst import live_query

    monkeypatch.setattr(live_query, "_lookup_outbound_for_identifier", lambda *_args, **_kwargs: _result(found=False))
    monkeypatch.setattr(live_query, "lookup_order_by_order_id", lambda *_args, **_kwargs: _result(found=True, shop_id="other-shop"))
    monkeypatch.setattr(live_query, "lookup_order_by_platform_order_id", lambda *_args, **_kwargs: _result(found=False))

    result = live_query.lookup_order_by_identifier(
        "opaque-sidebar-order-reference",
        "unknown_identifier",
        exhaustive=False,
        shop_id="selected-shop",
    )

    assert result["found"] is False
    assert result.get("data") is None


def test_unknown_identifier_admits_direct_result_from_selected_shop(monkeypatch):
    from app.integrations.jst import live_query

    monkeypatch.setattr(live_query, "_lookup_outbound_for_identifier", lambda *_args, **_kwargs: _result(found=False))
    monkeypatch.setattr(live_query, "lookup_order_by_order_id", lambda *_args, **_kwargs: _result(found=True, shop_id="selected-shop"))

    result = live_query.lookup_order_by_identifier(
        "opaque-sidebar-order-reference",
        "unknown_identifier",
        exhaustive=False,
        shop_id="selected-shop",
    )

    assert result["found"] is True
    assert result["data"]["shop_id"] == "selected-shop"


def test_unresolved_display_shop_still_allows_exact_order_lookup(monkeypatch):
    """A UI label may fail to map without suppressing an exact order lookup."""
    from app.integrations.jst import live_query

    direct_calls = []

    monkeypatch.setattr(
        live_query,
        "_resolve_dispatch_shop_scope",
        lambda **_kwargs: {"status": "not_found", "shop_id": ""},
    )
    monkeypatch.setattr(
        live_query,
        "_lookup_outbound_for_identifier",
        lambda _identifier, **kwargs: direct_calls.append(("outbound", kwargs)) or _result(found=False),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_order_id",
        lambda _identifier: direct_calls.append(("order_id", {})) or _result(found=False),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_platform_order_id",
        lambda _identifier: direct_calls.append(("platform_order_id", {})) or _result(found=True),
    )

    result = live_query.lookup_order_by_identifier(
        "opaque-sidebar-order-reference",
        "unknown_identifier",
        shop_name="unmapped-ui-store-label",
    )

    assert result["found"] is True
    assert [name for name, _kwargs in direct_calls] == [
        "outbound",
        "order_id",
        "platform_order_id",
    ]
    assert direct_calls[0][1] == {}


def test_unresolved_display_shop_never_enables_unscoped_row_scans(monkeypatch):
    """An unmapped UI label permits exact filters, never a row-list scan."""
    from app.integrations.jst import live_query

    direct_calls = []

    monkeypatch.setattr(
        live_query,
        "_resolve_dispatch_shop_scope",
        lambda **_kwargs: {"status": "ambiguous", "shop_id": ""},
    )
    monkeypatch.setattr(
        live_query,
        "_lookup_outbound_for_identifier",
        lambda _identifier, **kwargs: direct_calls.append(("outbound", kwargs)) or _result(found=False),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_order_id",
        lambda _identifier: direct_calls.append(("order_id", {})) or _result(found=False),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_platform_order_id",
        lambda _identifier: direct_calls.append(("platform_order_id", {})) or _result(found=False),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_platform_order_id_history",
        lambda _identifier: direct_calls.append(("platform_order_id_history", {})) or _result(found=False),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_outer_so_id",
        lambda _identifier: (_ for _ in ()).throw(AssertionError("outer scan must not run")),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_logistics_by_tracking_no",
        lambda _identifier: (_ for _ in ()).throw(AssertionError("tracking scan must not run")),
    )

    result = live_query.lookup_order_by_identifier(
        "opaque-sidebar-order-reference",
        "unknown_identifier",
        exhaustive=True,
        shop_name="ambiguous-ui-store-label",
    )

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "shop_scope_ambiguous"
    assert [name for name, _kwargs in direct_calls] == [
        "outbound",
        "order_id",
        "platform_order_id",
        "platform_order_id_history",
    ]
