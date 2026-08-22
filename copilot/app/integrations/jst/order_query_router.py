"""Select the configured read-only JST order transport without cross-provider fallback."""

from __future__ import annotations


def normalized_order_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    return provider if provider in {"jst_standard", "qimen"} else "jst_standard"


def lookup_order_by_provider(
    identifier: str,
    identifier_type: str,
    *,
    provider: str = "jst_standard",
    shop_ref: str = "",
    shop_id: str = "",
    exhaustive: bool = True,
    standard_lookup=None,
) -> dict:
    selected = normalized_order_provider(provider)
    if selected == "qimen":
        if identifier_type not in {"platform_trade_id", "platform_order_id"}:
            return {
                "found": False,
                "endpoint": "jushuitan.order.list.query",
                "query_type": identifier_type,
                "duration_ms": 0,
                "safe_fallback_reason": "identifier_not_supported",
                "error_code": "qimen_identifier_not_supported",
                "attempted_paths": [],
            }
        from app.integrations.jst.qimen_order_query import (
            lookup_qimen_order_by_platform_trade_id,
        )

        return lookup_qimen_order_by_platform_trade_id(
            identifier,
            shop_ref=shop_ref,
            shop_id=shop_id,
        )

    if standard_lookup is None:
        from app.integrations.jst.live_query import lookup_order_by_identifier

        standard_lookup = lookup_order_by_identifier

    kwargs = {}
    if exhaustive is not True:
        kwargs["exhaustive"] = exhaustive
    if shop_id:
        kwargs["shop_id"] = shop_id
    return standard_lookup(identifier, identifier_type, **kwargs)
