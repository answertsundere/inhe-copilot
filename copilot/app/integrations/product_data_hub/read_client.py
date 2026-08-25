"""Exact-identity, read-only access to the Product Data Hub v2 API."""

from __future__ import annotations

import json
import re
from hashlib import sha256
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


def _domain_policy_id(value: Any) -> str:
    candidate = str(value or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate):
        return ""
    return candidate


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

    def lookup_exact_bundle(self, *, i_id: str = "", sku_id: str = "") -> dict[str, Any]:
        """Read fact and labeled-media candidates for one already exact identity.

        The Hub remains read-only.  This boundary only projects explicit,
        confirmed, non-conflicting facts that belong to the resolved product or
        its exact SKU; it does not infer a product fact from an asset label.
        """
        resolved = self.lookup_exact(i_id=i_id, sku_id=sku_id)
        if resolved.get("status") != "resolved":
            return {
                **resolved,
                "facts": [],
                "assets": [],
            }

        product = resolved.get("product") or {}
        sku = resolved.get("sku") or {}
        product_id = str(product.get("hub_product_id") or "")
        sku_hub_id = str(sku.get("hub_sku_id") or "")
        if not product_id:
            return {
                **_empty_result("unavailable", "resolved_product_id_missing"),
                "facts": [],
                "assets": [],
            }

        try:
            facts_payload = self._get_json(f"/api/v2/products/{product_id}/facts")
            assets_payload = self._get_json(f"/api/v2/products/{product_id}/labeled-images")
            facts = facts_payload.get("facts")
            assets = assets_payload.get("items")
            if facts_payload.get("ok") is not True or not isinstance(facts, list):
                raise ValueError("invalid_facts_contract")
            if assets_payload.get("ok") is not True or not isinstance(assets, list):
                raise ValueError("invalid_assets_contract")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return {
                **_empty_result("unavailable", "bundle_read_failed"),
                "facts": [],
                "assets": [],
            }

        projected_facts = [
            self._fact_projection(row, product_id=product_id, sku_id=sku_hub_id)
            for row in facts
            if isinstance(row, dict)
        ]
        product_color_options = self._product_color_options_projection(
            facts,
            product_id=product_id,
        )
        if product_color_options:
            projected_facts.append(product_color_options)
        projected_assets = [
            self._asset_projection(
                row,
                product_code=str(product.get("product_code") or ""),
                sku_code=str(sku.get("sku_code") or ""),
            )
            for row in assets
            if isinstance(row, dict)
        ]
        return {
            **resolved,
            "reference_only": False,
            "used_for_fact": True,
            "facts": [row for row in projected_facts if row],
            "assets": [row for row in projected_assets if row],
        }

    def _product_color_options_projection(
        self,
        facts: list[dict[str, Any]],
        *,
        product_id: str,
    ) -> dict[str, Any] | None:
        """Aggregate only confirmed colors for active variants of one product."""
        try:
            skus_payload = self._get_json("/api/v2/skus")
            skus = skus_payload.get("items")
            if skus_payload.get("ok") is not True or not isinstance(skus, list):
                return None
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return None

        active_skus = sorted(
            (
                row
                for row in skus
                if isinstance(row, dict)
                and _active(row)
                and str(row.get("productId") or "") == product_id
                and str(row.get("id") or "").strip()
            ),
            key=lambda row: _code(row.get("skuCode")),
        )
        if len(active_skus) < 2:
            return None

        confirmed_colors: dict[str, tuple[str, str]] = {}
        for row in facts:
            if not isinstance(row, dict):
                continue
            if str(row.get("productId") or "") != product_id:
                continue
            if str(row.get("type") or "").strip().lower() not in {"color", "colors"}:
                continue
            if str(row.get("status") or "").strip().lower() != "confirmed" or bool(row.get("conflict")):
                continue
            sku_id = str(row.get("skuId") or "").strip()
            value = str(row.get("value") or "").strip()
            if sku_id and value:
                confirmed_colors[sku_id] = (value, str(row.get("updatedAt") or "").strip())

        values: list[str] = []
        updated_at: list[str] = []
        for sku in active_skus:
            color = confirmed_colors.get(str(sku.get("id") or ""))
            if color and color[0] not in values:
                values.append(color[0])
                if color[1]:
                    updated_at.append(color[1])
        if len(values) < 2:
            return None

        value = "、".join(values)
        digest = sha256(value.encode("utf-8")).hexdigest()[:16]
        return {
            "fact_uid": f"product_data_hub:{product_id}:color-options:{digest}",
            "fact_type": "colors",
            "attribute_key": "可选颜色",
            "value": value,
            "unit": "",
            "scope": "商品整体",
            "applies": "",
            "source": "product_data_hub:confirmed_sku_colors",
            "source_detail": "",
            "review_status": "confirmed",
            "identity_scope": {"hub_product_id": product_id},
            "updated_at": max(updated_at, default=""),
        }

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
    def _fact_projection(row: dict[str, Any], *, product_id: str, sku_id: str) -> dict[str, Any] | None:
        if str(row.get("productId") or "") != product_id:
            return None
        if str(row.get("status") or "").strip().lower() != "confirmed" or bool(row.get("conflict")):
            return None
        row_sku_id = str(row.get("skuId") or "")
        if row_sku_id and row_sku_id != sku_id:
            return None
        fact_id = str(row.get("id") or "").strip()
        fact_type = str(row.get("type") or "").strip()
        value = str(row.get("value") or "").strip()
        if not fact_id or not fact_type or not value:
            return None
        return {
            "fact_uid": f"product_data_hub:{fact_id}",
            "fact_type": fact_type,
            "attribute_key": str(row.get("attr") or "").strip(),
            "value": value,
            "unit": str(row.get("unit") or "").strip(),
            "scope": str(row.get("scope") or "").strip(),
            "applies": str(row.get("applies") or "").strip(),
            "source": f"product_data_hub:{str(row.get('source') or 'unknown').strip()}",
            "source_detail": str(row.get("sourceDetail") or "").strip(),
            "review_status": "confirmed",
            "identity_scope": {
                "hub_product_id": product_id,
                "hub_sku_id": sku_id,
            },
            "updated_at": str(row.get("updatedAt") or "").strip(),
        }

    def _asset_projection(self, row: dict[str, Any], *, product_code: str, sku_code: str) -> dict[str, Any] | None:
        asset_id = str(row.get("assetId") or "").strip()
        label = str(row.get("label") or "").strip()
        preview_path = self._safe_preview_path(row.get("previewUrl"))
        asset_type = _HUB_ASSET_TYPE_BY_LABEL.get(label, "")
        if not asset_id or not label or not preview_path or not asset_type:
            return None
        labels = row.get("labels")
        normalized_labels = [str(item).strip() for item in labels if str(item).strip()] if isinstance(labels, list) else [label]
        if label not in normalized_labels:
            normalized_labels.insert(0, label)
        return {
            "asset_id": asset_id,
            "asset_type": asset_type,
            "labels": normalized_labels,
            "label_note": str(row.get("labelNote") or "").strip(),
            "spec_ref": str(row.get("specRef") or "").strip(),
            "asset_title": str(row.get("canonicalName") or "").strip(),
            "asset_url": f"{self.base_url}{preview_path}",
            "source": "product_data_hub",
            "product_code": product_code,
            "sku_code": sku_code,
            "auto_send_level": "auto",
        }

    @staticmethod
    def _safe_preview_path(value: Any) -> str:
        try:
            parsed = urlsplit(str(value or "").strip())
        except ValueError:
            return ""
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            return ""
        path = parsed.path
        if not path.startswith("/api/v2/media/preview/"):
            return ""
        return path

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
            "domain_policy_id": _domain_policy_id(row.get("domainPolicyId")),
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


_HUB_ASSET_TYPE_BY_LABEL = {
    "产品信息图": "sku_image",
    "白底单品图": "sku_image",
    "尺寸参数图": "size_image",
    "合格证质检": "certificate_image",
    "材质说明": "material_image",
    "安装说明": "install_image",
    "包装清单": "pack_guide_image",
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


def lookup_product_data_hub_bundle(*, i_id: str = "", sku_id: str = "") -> dict[str, Any]:
    from app import config

    if not config.COPILOT_PRODUCT_DATA_HUB_ENABLED:
        return {**_empty_result("disabled", "feature_disabled"), "facts": [], "assets": []}
    client = ProductDataHubReadClient(
        config.COPILOT_PRODUCT_DATA_HUB_BASE_URL,
        timeout_seconds=config.COPILOT_PRODUCT_DATA_HUB_TIMEOUT_SECONDS,
    )
    return client.lookup_exact_bundle(i_id=i_id, sku_id=sku_id)
