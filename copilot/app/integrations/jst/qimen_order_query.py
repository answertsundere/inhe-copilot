"""Read-only Taobao/Tmall order lookup through JST's Qimen custom API."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

import requests


_METHOD = "jushuitan.order.list.query"
_TARGET_APP_KEY = "23060081"
_DEFAULT_TIMEOUT_SECONDS = 5.0


class QimenConfigurationError(RuntimeError):
    pass


class QimenProtocolError(RuntimeError):
    pass


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _safe_router_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except (TypeError, ValueError):
        return ""
    hostname = str(parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or not (hostname == "api.taobao.com" or hostname.endswith(".api.taobao.com"))
        or parsed.username
        or parsed.password
    ):
        return ""
    if parsed.query or parsed.fragment:
        return ""
    return value


def _top_sign(params: dict[str, str], secret: str) -> str:
    unsigned = {
        key: value
        for key, value in params.items()
        if key != "sign" and key and value not in (None, "")
    }
    source = secret + "".join(
        f"{key}{value}" for key, value in sorted(unsigned.items())
    ) + secret
    return hashlib.md5(source.encode("utf-8")).hexdigest().upper()


class QimenOrderClient:
    """Minimal TOP transport for the single approved read-only JST method."""

    def __init__(
        self,
        *,
        post: Callable = requests.post,
        now: Callable[[], str] | None = None,
    ):
        self._app_key = _env("COPILOT_QIMEN_APP_KEY")
        self._app_secret = _env("COPILOT_QIMEN_APP_SECRET")
        self._session = _env("COPILOT_QIMEN_SESSION")
        self._customer_id = _env("COPILOT_QIMEN_CUSTOMER_ID")
        self._router_url = _safe_router_url(_env("COPILOT_QIMEN_ROUTER_URL"))
        self._target_app_key = _env("COPILOT_QIMEN_TARGET_APP_KEY") or _TARGET_APP_KEY
        self._post = post
        self._now = now or (lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def is_configured(self) -> bool:
        return bool(
            self._app_key
            and self._app_secret
            and self._customer_id
            and self._router_url
        )

    def query_order(self, platform_trade_id: str, *, shop_id: str = "") -> dict:
        if not self.is_configured():
            raise QimenConfigurationError("Qimen order provider is not configured")
        if not str(platform_trade_id or "").strip():
            raise QimenProtocolError("platform trade id is required")

        params = {
            "app_key": self._app_key,
            "method": _METHOD,
            "timestamp": self._now(),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "customer_id": self._customer_id,
            "target_app_key": self._target_app_key,
            "page_index": "1",
            "page_size": "10",
            "so_ids": str(platform_trade_id).strip(),
        }
        if self._session:
            params["session"] = self._session
        if str(shop_id or "").strip():
            params["shop_id"] = str(shop_id).strip()
        params["sign"] = _top_sign(params, self._app_secret)

        response = self._post(
            self._router_url,
            data=params,
            timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise QimenProtocolError("Qimen response must be a JSON object")
        return payload


def _as_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _response_body(payload: dict) -> dict:
    if isinstance(payload.get("error_response"), dict):
        raise QimenProtocolError("Qimen provider returned an error response")
    body = payload.get("jushuitan_order_list_query_response", payload)
    body = _as_object(body)
    if not body:
        raise QimenProtocolError("Qimen response body is missing")
    result = _as_object(body.get("result"))
    return result or body


def _rows(payload: dict) -> list[dict]:
    body = _response_body(payload)
    code = body.get("code")
    if code not in (None, 0, "0"):
        raise QimenProtocolError("JST Qimen method returned a non-success code")
    for key in ("datas", "orders", "data"):
        value = body.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = value.get("orders") or value.get("datas")
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
    return []


def _item_projection(item: dict) -> dict:
    return {
        "sku_id": str(item.get("sku_id") or "").strip(),
        "i_id": str(item.get("i_id") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "qty": item.get("qty", ""),
        "properties_value": str(item.get("properties_value") or "").strip(),
        "shop_sku_id": str(item.get("shop_sku_id") or "").strip(),
        "shop_i_id": str(item.get("shop_i_id") or "").strip(),
    }


def _order_projection(order: dict) -> dict:
    items = order.get("items") if isinstance(order.get("items"), list) else []
    so_id = str(order.get("so_id") or "").strip()
    return {
        "o_id": str(order.get("o_id") or "").strip(),
        "so_id": so_id,
        "outer_so_id": so_id,
        "status": str(order.get("status") or order.get("shop_status") or "").strip(),
        "logistics_company": str(
            order.get("logistics_company") or order.get("lc_name") or ""
        ).strip(),
        "l_id": str(order.get("l_id") or "").strip(),
        "send_date": str(order.get("send_date") or "").strip(),
        "sign_time": str(order.get("sign_time") or "").strip(),
        "items": [_item_projection(item) for item in items if isinstance(item, dict)],
    }


def _failure(reason: str, *, code: str = "", duration_ms: int = 0) -> dict:
    return {
        "found": False,
        "endpoint": _METHOD,
        "query_type": "platform_trade_id",
        "duration_ms": duration_ms,
        "safe_fallback_reason": reason,
        "error_code": code or None,
        "attempted_paths": [_METHOD],
    }


def lookup_qimen_order_by_platform_trade_id(
    platform_trade_id: str,
    *,
    shop_ref: str = "",
    shop_id: str = "",
    client: QimenOrderClient | None = None,
) -> dict:
    """Resolve a Taobao/Tmall online order without exposing buyer PII."""

    del shop_ref  # Logical store provenance is retained by the caller, not sent to TOP.
    started = time.perf_counter()
    provider = client or QimenOrderClient()
    if not provider.is_configured():
        return _failure("provider_not_configured", code="qimen_not_configured")
    try:
        payload = provider.query_order(platform_trade_id, shop_id=shop_id)
        rows = _rows(payload)
    except QimenConfigurationError:
        return _failure("provider_not_configured", code="qimen_not_configured")
    except requests.Timeout:
        return _failure("timeout", code="qimen_timeout")
    except (requests.RequestException, ValueError, QimenProtocolError):
        return _failure("provider_error", code="qimen_protocol_error")

    duration_ms = int((time.perf_counter() - started) * 1000)
    expected = str(platform_trade_id or "").strip()
    exact = [row for row in rows if str(row.get("so_id") or "").strip() == expected]
    if len(exact) != 1:
        reason = "not_found" if not exact else "ambiguous_result"
        return _failure(reason, duration_ms=duration_ms)
    return {
        "found": True,
        "data": _order_projection(exact[0]),
        "endpoint": _METHOD,
        "query_type": "platform_trade_id->qimen_exact_so_id",
        "duration_ms": duration_ms,
        "attempted_paths": [_METHOD],
    }
