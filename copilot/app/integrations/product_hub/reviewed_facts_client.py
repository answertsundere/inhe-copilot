"""Read confirmed, exact-identity product facts from the Product Hub Agent API.

The client intentionally exposes no search, write, media, or raw-note API.
Callers receive a small structured projection and decide eligibility through the
existing Product Context Pack and admission contracts.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


_DEFAULT_TIMEOUT_SECONDS = 2.0
_MAX_TIMEOUT_SECONDS = 5.0
_MAX_RESPONSE_BYTES = 512 * 1024


def _enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_timeout(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = _DEFAULT_TIMEOUT_SECONDS
    return max(0.1, min(parsed, _MAX_TIMEOUT_SECONDS))


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit or not text.isprintable():
        return ""
    return text


def _base_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
    except ValueError:
        return ""


def _empty_result(state: str, reason_code: str, product_code: str) -> dict[str, Any]:
    return {
        "state": state,
        "reason_code": reason_code,
        "product_code": product_code,
        "facts": [],
    }


def _empty_sku_result(state: str, reason_code: str, sku_code: str) -> dict[str, Any]:
    return {
        "state": state,
        "reason_code": reason_code,
        "product_code": "",
        "resolved_sku_code": sku_code,
        "facts": [],
    }


def _read_json(url: str, *, timeout: float) -> tuple[dict[str, Any] | None, str]:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if int(getattr(response, "status", 200) or 200) != 200:
                return None, "unavailable"
            payload_bytes = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        return None, "not_found" if exc.code == 404 else "unavailable"
    except (TimeoutError, URLError, OSError):
        return None, "unavailable"

    if len(payload_bytes) > _MAX_RESPONSE_BYTES:
        return None, "response_too_large"
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_payload"
    return payload, ""


def _safe_fact(raw: Any, *, product_code: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    fact_id = _bounded_text(raw.get("id"), 128)
    fact_type = _bounded_text(raw.get("type"), 64).lower()
    value = _bounded_text(raw.get("value"), 500)
    status = _bounded_text(raw.get("status"), 32).lower()
    if not fact_id or not fact_type or not value or not status:
        return None
    return {
        "id": fact_id,
        "product_code": product_code,
        "sku_code": _bounded_text(raw.get("skuCode"), 128),
        "type": fact_type,
        "attr": _bounded_text(raw.get("attr"), 128),
        "value": value,
        "unit": _bounded_text(raw.get("unit"), 32),
        "scope": _bounded_text(raw.get("scope"), 64),
        "applies": _bounded_text(raw.get("applies"), 128),
        "source": _bounded_text(raw.get("source"), 64),
        "status": status,
        "conflict": bool(raw.get("conflict")),
        "updated_at": _bounded_text(raw.get("updatedAt"), 64),
    }


class ProductHubReviewedFactsClient:
    """Bounded, default-off reader for the Product Hub Agent facts contract."""

    def fetch_confirmed_facts(self, product_code: Any) -> dict[str, Any]:
        code = _bounded_text(product_code, 128)
        if not _enabled("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED"):
            return _empty_result("disabled", "product_hub_read_disabled", code)
        if not code:
            return _empty_result("not_attempted", "product_code_missing", code)
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base:
            return _empty_result("unconfigured", "product_hub_base_url_invalid", code)

        timeout = _bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
        url = f"{base}/api/agent/products/{quote(code, safe='')}/facts?status=confirmed"
        payload, error = _read_json(url, timeout=timeout)
        if error == "not_found":
            return _empty_result("not_found", "product_hub_product_not_found", code)
        if error == "unavailable":
            return _empty_result("unavailable", "product_hub_http_unavailable", code)
        if error == "response_too_large":
            return _empty_result("invalid_response", "product_hub_response_too_large", code)
        if error == "invalid_json":
            return _empty_result("invalid_response", "product_hub_response_invalid_json", code)
        if error or not isinstance(payload, dict) or payload.get("ok") is not True:
            return _empty_result("invalid_response", "product_hub_response_invalid", code)
        returned_code = _bounded_text(payload.get("productCode"), 128)
        if returned_code != code:
            return _empty_result("invalid_response", "product_code_mismatch", code)
        raw_facts = payload.get("facts")
        if not isinstance(raw_facts, list):
            return _empty_result("invalid_response", "product_hub_facts_contract_invalid", code)

        facts = [fact for item in raw_facts if (fact := _safe_fact(item, product_code=code))]
        return {
            "state": "ready",
            "reason_code": "",
            "product_code": code,
            "facts": facts,
        }

    def fetch_confirmed_facts_for_sku(self, sku_code: Any) -> dict[str, Any]:
        """Resolve one exact Hub SKU before reading its product's confirmed facts."""

        sku = _bounded_text(sku_code, 128)
        if not _enabled("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED"):
            return _empty_sku_result("disabled", "product_hub_read_disabled", sku)
        if not sku:
            return _empty_sku_result("not_attempted", "product_hub_sku_code_missing", "")
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base:
            return _empty_sku_result("unconfigured", "product_hub_base_url_invalid", sku)

        timeout = _bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
        url = f"{base}/api/agent/skus/{quote(sku, safe='')}"
        payload, error = _read_json(url, timeout=timeout)
        if error == "not_found":
            return _empty_sku_result("not_found", "product_hub_sku_not_found", sku)
        if error == "unavailable":
            return _empty_sku_result("unavailable", "product_hub_http_unavailable", sku)
        if error == "response_too_large":
            return _empty_sku_result("invalid_response", "product_hub_response_too_large", sku)
        if error == "invalid_json":
            return _empty_sku_result("invalid_response", "product_hub_response_invalid_json", sku)
        if error or not isinstance(payload, dict) or payload.get("ok") is not True:
            return _empty_sku_result("invalid_response", "product_hub_sku_response_invalid", sku)

        raw_sku = payload.get("sku")
        if not isinstance(raw_sku, dict):
            return _empty_sku_result("invalid_response", "product_hub_sku_contract_invalid", sku)
        returned_sku = _bounded_text(raw_sku.get("skuCode"), 128)
        product_code = _bounded_text(raw_sku.get("productCode"), 128)
        if returned_sku != sku:
            return _empty_sku_result("invalid_response", "product_hub_sku_code_mismatch", sku)
        if not product_code:
            return _empty_sku_result("invalid_response", "product_hub_sku_product_code_missing", sku)

        facts = self.fetch_confirmed_facts(product_code)
        return {
            **facts,
            "resolved_sku_code": sku,
            "identity_source": "product_hub_exact_sku",
        }
