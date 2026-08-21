"""Exact-identity, read-only access to the Product Data Hub v2 API."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


_MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _empty_result(status: str, reason: str = "") -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "match_reason": "",
        "product": {},
        "sku": {},
        "reference_only": True,
        "used_for_fact": False,
        "source": "product_data_hub",
    }


def _code(value: Any) -> str:
    return str(value or "").strip().casefold()


def _active(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").strip().lower() == "active"


class ProductDataHubReadClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 2.0):
        self.base_url = self._normalize_base_url(base_url)
        self.timeout_seconds = max(0.2, min(float(timeout_seconds or 2.0), 10.0))

    def lookup_exact(self, *, i_id: str = "", sku_id: str = "") -> dict[str, Any]:
        product_code = _code(i_id)
        sku_code = _code(sku_id)
        if not product_code and not sku_code:
            return _empty_result("not_configured", "no_exact_identity")
        if not self.base_url:
            return _empty_result("not_configured", "invalid_base_url")

        try:
            products_payload = self._get_json("/api/v2/products")
            products = products_payload.get("items")
            if products_payload.get("ok") is not True or not isinstance(products, list):
                return _empty_result("unavailable", "invalid_products_contract")

            active_products = [row for row in products if isinstance(row, dict) and _active(row)]
            product_matches = [
                row for row in active_products
                if product_code and _code(row.get("productCode")) == product_code
            ]
            if len(product_matches) > 1:
                return _empty_result("ambiguous", "duplicate_product_code")
            if product_code and not product_matches:
                return _empty_result("not_found", "product_code_not_found")
            product = product_matches[0] if product_matches else None

            sku = None
            if sku_code:
                skus_payload = self._get_json("/api/v2/skus")
                skus = skus_payload.get("items")
                if skus_payload.get("ok") is not True or not isinstance(skus, list):
                    return _empty_result("unavailable", "invalid_skus_contract")
                sku_matches = [
                    row for row in skus
                    if isinstance(row, dict) and _active(row) and _code(row.get("skuCode")) == sku_code
                ]
                if len(sku_matches) > 1:
                    return _empty_result("ambiguous", "duplicate_sku_code")
                sku = sku_matches[0] if sku_matches else None
                if sku is None:
                    return _empty_result("not_found", "sku_code_not_found")
                sku_product = next(
                    (row for row in active_products if str(row.get("id") or "") == str(sku.get("productId") or "")),
                    None,
                )
                if sku_product is None:
                    return _empty_result("unavailable", "sku_parent_missing")
                if product is not None and str(product.get("id") or "") != str(sku_product.get("id") or ""):
                    return _empty_result("identity_conflict", "product_sku_parent_mismatch")
                product = sku_product

            if product is None:
                return _empty_result("not_found", "product_code_not_found")

            match_reason = "exact_product_and_sku_code" if product_code and sku_code else (
                "exact_sku_code" if sku_code else "exact_product_code"
            )
            return {
                "status": "resolved",
                "reason": "",
                "match_reason": match_reason,
                "product": self._product_projection(product),
                "sku": self._sku_projection(sku) if sku else {},
                "reference_only": True,
                "used_for_fact": False,
                "source": "product_data_hub",
            }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return _empty_result("unavailable", "read_failed")

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(f"{self.base_url}{path}", headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid_json_root")
        return payload

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        try:
            parsed = urlsplit(str(value or "").strip())
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return ""
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                return ""
            port = parsed.port
        except ValueError:
            return ""
        host = parsed.hostname.lower()
        netloc = host if port is None else f"{host}:{port}"
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))

    @staticmethod
    def _product_projection(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "hub_product_id": str(row.get("id") or ""),
            "product_code": str(row.get("productCode") or ""),
            "product_name": str(row.get("productName") or ""),
            "brand": str(row.get("brand") or ""),
            "category_code": str(row.get("catCode") or ""),
            "category_name": str(row.get("catName") or row.get("category") or ""),
            "status": str(row.get("status") or ""),
            "updated_at": str(row.get("updatedAt") or ""),
        }

    @staticmethod
    def _sku_projection(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "hub_sku_id": str(row.get("id") or ""),
            "sku_code": str(row.get("skuCode") or ""),
            "color": str(row.get("color") or ""),
            "size": str(row.get("size") or ""),
            "spec": str(row.get("spec") or ""),
            "status": str(row.get("status") or ""),
        }


def lookup_product_data_hub_reference(*, i_id: str = "", sku_id: str = "") -> dict[str, Any]:
    from app import config

    if not config.COPILOT_PRODUCT_DATA_HUB_ENABLED:
        return _empty_result("disabled", "feature_disabled")
    client = ProductDataHubReadClient(
        config.COPILOT_PRODUCT_DATA_HUB_BASE_URL,
        timeout_seconds=config.COPILOT_PRODUCT_DATA_HUB_TIMEOUT_SECONDS,
    )
    return client.lookup_exact(i_id=i_id, sku_id=sku_id)
