"""Read exact-identity product facts and review-only media from Product Hub.

The client intentionally exposes no search, write, raw-note, or delivery API.
Callers receive small structured projections and decide eligibility through the
existing Product Context Pack, admission, and media-delivery contracts.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from http.client import HTTPException
from time import monotonic
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


_DEFAULT_TIMEOUT_SECONDS = 2.0
_MAX_TIMEOUT_SECONDS = 5.0
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_MANUAL_FILE_CHECKS = 3
_MANUAL_FILE_CHECK_BUDGET_SECONDS = 5.0

_HUB_REVIEWABLE_MEDIA_STATUSES = {"approved", "live"}
_HUB_IMAGE_MEDIA_CONTRACT = {
    "main": ("sku_image", "appearance_image"),
    "detail": ("sku_image", "appearance_image"),
    "buyer": ("sku_image", "appearance_image"),
    "sku": ("sku_image", "appearance_image"),
    "manual": ("pack_guide_image", "packing_list_image"),
    "pack": ("pack_guide_image", "packing_list_image"),
    "patent": ("certificate_image", "certificate_image"),
    "qc": ("certificate_image", "certificate_image"),
}


def _enabled(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def answer_context_shadow_enabled() -> bool:
    return _enabled("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED")


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


def _empty_sku_assets_result(state: str, reason_code: str, sku_code: str) -> dict[str, Any]:
    return {
        "state": state,
        "reason_code": reason_code,
        "product_code": "",
        "resolved_sku_code": sku_code,
        "assets": [],
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
    fact = {
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
    hub_sku_id = _bounded_text(raw.get("skuId"), 128)
    if hub_sku_id:
        # This is a Hub record identifier, not a customer-facing SKU code.
        fact["hub_sku_id"] = hub_sku_id
    return fact


def _read_exact_sku_resolution(
    sku: str,
    *,
    base: str,
    timeout: float,
) -> dict[str, Any]:
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
    return {
        "state": "ready",
        "reason_code": "",
        "product_code": product_code,
        "resolved_sku_code": sku,
        "hub_sku_id": _bounded_text(raw_sku.get("id"), 128),
        "hub_sku_status": raw_sku.get("status"),
        "facts": [],
    }


def _safe_hub_media_asset(
    raw: Any,
    *,
    base: str,
    product_code: str,
    sku_code: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    asset_id = _bounded_text(raw.get("id"), 128)
    source_asset_type = _bounded_text(raw.get("assetType"), 64).lower()
    source_review_status = _bounded_text(raw.get("status"), 32).lower()
    media_contract = _HUB_IMAGE_MEDIA_CONTRACT.get(source_asset_type)
    if not asset_id or not media_contract or source_review_status not in _HUB_REVIEWABLE_MEDIA_STATUSES:
        return None

    expected_preview_path = f"/api/v2/media/preview/{quote(asset_id, safe='')}"
    preview_path = _bounded_text(raw.get("previewUrl"), 512)
    if preview_path != expected_preview_path:
        return None

    asset_type, media_purpose = media_contract
    label = _bounded_text(raw.get("label"), 160)
    scene = _bounded_text(raw.get("scene"), 96)
    return {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "media_purpose": media_purpose,
        "asset_title": label,
        "scene_tags": [scene] if scene else [],
        "asset_url": f"{base}{expected_preview_path}",
        "source": "product_hub.agent_assets",
        "source_table": "product_hub.assets",
        "source_review_status": source_review_status,
        "product_code": product_code,
        "resolved_sku_code": sku_code,
    }


def _safe_hub_manual(raw: Any, *, base: str, product_code: str,
                     product_id: str, sku_code: str, sku_id: str) -> dict[str, Any] | None:
    """A catalog PDF is a review reference, not proof of variant applicability."""
    if not isinstance(raw, dict):
        return None
    asset_id = _bounded_text(raw.get("id"), 128)
    name = _bounded_text(raw.get("canonicalName"), 240)
    bound_sku = raw.get("skuId")
    if (
        not asset_id or not name.lower().endswith(".pdf")
        or raw.get("assetType") != "manual"
        or not isinstance(raw.get("status"), str)
        or raw.get("status") not in _HUB_REVIEWABLE_MEDIA_STATUSES
        or raw.get("productId") != product_id
        or (bound_sku not in (None, "") and (not sku_id or bound_sku != sku_id))
        or type(raw.get("sizeBytes")) is not int or raw["sizeBytes"] <= 0
    ):
        return None
    try:
        url = urlsplit(_bounded_text(raw.get("originalUrl"), 2048))
        params = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if (
        url.scheme or url.netloc or url.fragment or url.path != "/api/asset"
        or set(params) != {"scope", "relative"} or params["scope"] != ["normalized"]
        or len(params["relative"]) != 1
    ):
        return None
    relative = params["relative"][0]
    parts = relative.replace("\\", "/").split("/")
    if (
        not relative.isprintable() or any(p in {"", ".", ".."} for p in parts)
        or any(c in relative for c in (":", "%")) or parts[-1] != name
    ):
        return None
    return {
        "asset_id": asset_id, "asset_type": "product_manual",
        "media_purpose": "product_manual", "asset_title": name,
        "asset_url": f"{base}/api/asset?{urlencode({'scope': 'normalized', 'relative': relative})}",
        "source": "product_hub.agent_assets", "source_table": "product_hub.assets",
        "source_review_status": raw["status"], "product_code": product_code,
        "resolved_sku_code": sku_code, "scene_tags": [],
        "binding_scope": "sku" if bound_sku else "product",
        "size_bytes": raw["sizeBytes"],
        "availability": "not_checked", "applicability": "needs_review",
    }


class _NoManualRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _check_manual_file(asset: dict[str, Any], *, timeout: float) -> str:
    """Check only a bounded prefix; this is not full-content/hash validation."""
    url = asset["asset_url"]  # Already constrained by _safe_hub_manual.
    request = Request(url, headers={"Range": "bytes=0-4", "Accept": "application/pdf",
                                   "Accept-Encoding": "identity"}, method="GET")
    try:
        with build_opener(_NoManualRedirect()).open(request, timeout=timeout) as response:
            if response.geturl() != url or response.status not in {200, 206}:
                return "unexpected_response"
            headers = response.headers
            if headers.get("Content-Encoding", "identity").lower() != "identity":
                return "encoded_response"
            if headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/pdf":
                return "not_pdf"
            length = headers.get("Content-Length", "")
            if not re.fullmatch(r"[0-9]+", length):
                return "invalid_size"
            if response.status == 206:
                extent = re.fullmatch(r"bytes 0-4/([0-9]+)", headers.get("Content-Range", ""))
                if not extent or int(length) != 5 or int(extent[1]) != asset["size_bytes"]:
                    return "size_mismatch"
            elif int(length) != asset["size_bytes"]:
                return "size_mismatch"
            if response.read(5) != b"%PDF-":
                return "invalid_pdf_header"
    except HTTPError as exc:
        exc.close()
        return "not_found" if exc.code == 404 else "http_unavailable"
    except (TimeoutError, URLError, OSError, HTTPException, ValueError):
        return "unavailable"
    return ""


class ProductHubReviewedFactsClient:
    """Bounded, default-off reader for the Product Hub Agent facts contract."""

    def resolve_active_sku_identity(self, sku_code: Any) -> dict[str, Any]:
        """Prove a current SKU/product binding; return no product facts or actions."""
        sku = _bounded_text(sku_code, 128) if isinstance(sku_code, str) else ""
        if not _enabled("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED"):
            return _empty_sku_result("disabled", "product_hub_read_disabled", sku)
        if not sku:
            return _empty_sku_result("not_attempted", "product_hub_sku_code_missing", "")
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base:
            return _empty_sku_result("unconfigured", "product_hub_base_url_invalid", sku)
        timeout = _bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
        resolution = _read_exact_sku_resolution(sku, base=base, timeout=timeout)
        if resolution["state"] != "ready":
            return resolution
        if resolution["hub_sku_status"] != "active" or not resolution["hub_sku_id"]:
            return _empty_sku_result("invalid_response", "product_hub_sku_inactive_or_unbound", sku)
        code = resolution["product_code"]
        payload, error = _read_json(f"{base}/api/agent/products/{quote(code, safe='')}", timeout=timeout)
        product = payload.get("product") if isinstance(payload, dict) else None
        if error or not payload or payload.get("ok") is not True:
            return _empty_sku_result("unavailable", "product_hub_product_unavailable", sku)
        if (
            not isinstance(product, dict) or product.get("productCode") != code
            or product.get("status") != "active" or not isinstance(product.get("id"), str)
            or not _bounded_text(product["id"], 128)
        ):
            return _empty_sku_result("invalid_response", "product_hub_product_identity_invalid", sku)
        return {
            **resolution, "hub_product_id": product["id"],
            "product_name": _bounded_text(product.get("name"), 256),
            "identity_source": "product_hub_exact_sku",
        }

    def fetch_domain_policy_selector(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Project control metadata from the exact resolved product, never facts."""
        product = self._read_verified_product_passport(identity)
        policy_id = product.get("domainPolicyId")
        # FilePolicyRepository owns ID/schema/hash validation, not source text.
        if not isinstance(policy_id, str) or not _bounded_text(policy_id, 64):
            return {}
        return {"catalog_metadata": {"domain_policy_id": policy_id}}

    def fetch_product_category_context(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Expose category presence only, bound to the current isolated SKU."""
        if (
            os.getenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "").strip() != "product_hub_review_only"
            or os.getenv("COPILOT_RUNTIME_ENV", "production").strip().lower() not in {"development", "test"}
            or not _enabled("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY")
        ):
            return {}
        product = self._read_verified_product_passport(identity)
        category = product.get("category")
        if not isinstance(category, str) or not _bounded_text(category, 256):
            return {}
        return {
            "source": "product_hub.agent_passport", "category_available": True,
            "identity_scope": {key: identity[key] for key in (
                "sku_code", "product_code", "hub_product_id", "hub_sku_id",
            )},
        }

    def _read_verified_product_passport(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Shared exact-binding check; raw fields remain private to projections."""
        if (
            not _enabled("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED")
            or identity.get("status") != "resolved"
            or identity.get("source") != "product_hub_exact_sku"
        ):
            return {}
        keys = ("product_code", "hub_product_id", "hub_sku_id", "sku_code")
        if any(not isinstance(identity.get(key), str) or not _bounded_text(identity[key], 128) for key in keys):
            return {}
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base or urlsplit(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
            return {}
        code = identity["product_code"]
        payload, error = _read_json(
            f"{base}/api/agent/products/{quote(code, safe='')}/passport",
            timeout=_bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)),
        )
        if error or not isinstance(payload, dict) or payload.get("ok") is not True:
            return {}
        product, skus = payload.get("product"), payload.get("skus")
        if (
            not isinstance(product, dict) or not isinstance(skus, list)
            or product.get("id") != identity["hub_product_id"]
            or product.get("productCode") != code or product.get("status") != "active"
        ):
            return {}
        matches = [sku for sku in skus if isinstance(sku, dict) and sku.get("skuCode") == identity["sku_code"]]
        if (
            len(matches) != 1 or matches[0].get("id") != identity["hub_sku_id"]
            or matches[0].get("productId") != identity["hub_product_id"]
            or matches[0].get("status") != "active"
        ):
            return {}
        return product

    def fetch_answer_context_for_sku(self, sku_code: Any) -> dict[str, Any]:
        """Read the versioned transport for shadow comparison, not admission."""
        sku = _bounded_text(sku_code, 128)

        def empty(state: str, reason: str) -> dict[str, Any]:
            return {**_empty_sku_result(state, reason, sku), "assets": []}

        if not answer_context_shadow_enabled():
            return empty("disabled", "product_hub_answer_context_shadow_disabled")
        if not sku:
            return empty("not_attempted", "product_hub_sku_code_missing")
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base:
            return empty("unconfigured", "product_hub_base_url_invalid")
        payload, error = _read_json(
            f"{base}/api/agent/answer-context?skuCode={quote(sku, safe='')}",
            timeout=_bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)),
        )
        if error:
            state = error if error in {"not_found", "unavailable"} else "invalid_response"
            return empty(state, f"product_hub_answer_context_{error}")
        invalid = empty("invalid_response", "product_hub_answer_context_contract_invalid")
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or payload.get("readOnly") is not True
            or payload.get("contractVersion") != "answer-context-v1"
        ):
            return invalid
        identity = payload.get("identity")
        if not isinstance(identity, dict):
            return invalid
        code = _bounded_text(identity.get("productCode"), 128)
        if (
            not code or identity.get("productCode") != code
            or identity.get("skuCode") != sku
            or identity.get("productStatus") != "active"
            or identity.get("skuStatus") != "active"
        ):
            return invalid
        raw_facts, raw_assets = payload.get("directFacts"), payload.get("mediaCandidates")
        if not isinstance(raw_facts, list) or not isinstance(raw_assets, list):
            return invalid
        facts, assets = [], []
        fact_ids, asset_ids = set(), set()
        unsupported_media_type_count = 0
        for raw in raw_facts:
            if (
                not isinstance(raw, dict)
                or not isinstance(raw.get("id"), str)
                or raw.get("evidenceRole") != "direct_product_fact"
                or raw.get("productCode") != code
                or raw.get("skuCode") not in ("", sku)
                or raw.get("applies") not in ("", sku)
                or raw.get("status") != "confirmed"
                or raw.get("conflict") is not False
                or bool(raw.get("skuCode")) != bool(_bounded_text(raw.get("skuId"), 128))
            ):
                return invalid
            fact = _safe_fact(raw, product_code=code)
            if not fact or fact["id"] in fact_ids:
                return invalid
            fact_ids.add(fact["id"])
            facts.append(fact)
        for raw in raw_assets:
            if (
                not isinstance(raw, dict)
                or not isinstance(raw.get("assetId"), str)
                or raw.get("evidenceRole") != "media_reference"
                or raw.get("usage") != "review_only_not_factual"
                or raw.get("productCode") != code
                or raw.get("skuCode") not in ("", sku)
                or not isinstance(raw.get("status"), str)
                or raw.get("status") not in _HUB_REVIEWABLE_MEDIA_STATUSES
            ):
                return invalid
            asset_id = _bounded_text(raw.get("assetId"), 128)
            asset_type = _bounded_text(raw.get("assetType"), 64).lower()
            if not asset_id or not asset_type or asset_id in asset_ids:
                return invalid
            asset_ids.add(asset_id)
            if asset_type not in _HUB_IMAGE_MEDIA_CONTRACT:
                unsupported_media_type_count += 1
                continue
            asset = _safe_hub_media_asset(
                {**raw, "id": raw.get("assetId")}, base=base, product_code=code, sku_code=sku,
            )
            if not asset:
                return invalid
            assets.append(asset)
        return {
            "state": "ready", "reason_code": "", "product_code": code,
            "resolved_sku_code": sku, "identity_source": "product_hub_exact_sku",
            "facts": sorted(facts, key=lambda fact: fact["id"]),
            "assets": sorted(assets, key=lambda asset: asset["asset_id"]),
            "source_media_count": len(raw_assets),
            "unsupported_media_type_count": unsupported_media_type_count,
        }

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
        resolution = _read_exact_sku_resolution(sku, base=base, timeout=timeout)
        if resolution.get("state") != "ready":
            return resolution

        facts = self.fetch_confirmed_facts(resolution["product_code"])
        return {
            **facts,
            "resolved_sku_code": sku,
            "identity_source": "product_hub_exact_sku",
        }

    def fetch_reviewable_assets_for_sku(self, sku_code: Any) -> dict[str, Any]:
        """Project exact-SKU approved/live images as review-only media candidates."""

        sku = _bounded_text(sku_code, 128)
        if not _enabled("COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED"):
            return _empty_sku_assets_result("disabled", "product_hub_media_read_disabled", sku)
        if not sku:
            return _empty_sku_assets_result("not_attempted", "product_hub_sku_code_missing", "")
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base:
            return _empty_sku_assets_result("unconfigured", "product_hub_base_url_invalid", sku)

        timeout = _bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
        resolution = _read_exact_sku_resolution(sku, base=base, timeout=timeout)
        if resolution.get("state") != "ready":
            return _empty_sku_assets_result(
                str(resolution.get("state") or "invalid_response"),
                str(resolution.get("reason_code") or "product_hub_sku_response_invalid"),
                sku,
            )

        url = f"{base}/api/agent/skus/{quote(sku, safe='')}/assets"
        payload, error = _read_json(url, timeout=timeout)
        if error == "not_found":
            return _empty_sku_assets_result("not_found", "product_hub_sku_assets_not_found", sku)
        if error == "unavailable":
            return _empty_sku_assets_result("unavailable", "product_hub_http_unavailable", sku)
        if error == "response_too_large":
            return _empty_sku_assets_result("invalid_response", "product_hub_response_too_large", sku)
        if error == "invalid_json":
            return _empty_sku_assets_result("invalid_response", "product_hub_response_invalid_json", sku)
        if error or not isinstance(payload, dict) or payload.get("ok") is not True:
            return _empty_sku_assets_result("invalid_response", "product_hub_assets_response_invalid", sku)
        if _bounded_text(payload.get("skuCode"), 128) != sku:
            return _empty_sku_assets_result("invalid_response", "product_hub_asset_sku_code_mismatch", sku)
        raw_assets = payload.get("items")
        if not isinstance(raw_assets, list):
            return _empty_sku_assets_result("invalid_response", "product_hub_assets_contract_invalid", sku)

        assets = [
            asset
            for raw in raw_assets
            if (asset := _safe_hub_media_asset(
                raw,
                base=base,
                product_code=str(resolution["product_code"]),
                sku_code=sku,
            ))
        ]
        assets.sort(key=lambda item: str(item.get("asset_id") or ""))
        return {
            "state": "ready",
            "reason_code": "",
            "product_code": resolution["product_code"],
            "resolved_sku_code": sku,
            "assets": assets,
            "identity_source": "product_hub_exact_sku",
        }

    def fetch_manuals_for_sku(self, sku_code: Any) -> dict[str, Any]:
        """Find approved PDF references on the exact SKU's verified product."""
        sku = _bounded_text(sku_code, 128)

        def empty(state: str, reason: str) -> dict[str, Any]:
            return _empty_sku_assets_result(state, reason, sku)

        if not _enabled("COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED"):
            return empty("disabled", "product_hub_media_read_disabled")
        if not sku:
            return empty("not_attempted", "product_hub_sku_code_missing")
        base = _base_url(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
        if not base:
            return empty("unconfigured", "product_hub_base_url_invalid")
        timeout = _bounded_timeout(os.getenv("COPILOT_PRODUCT_HUB_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
        resolution = _read_exact_sku_resolution(sku, base=base, timeout=timeout)
        if resolution["state"] != "ready":
            return empty(resolution["state"], resolution["reason_code"])
        if resolution["hub_sku_status"] != "active":
            return empty("invalid_response", "product_hub_manual_sku_inactive")
        code = resolution["product_code"]
        payload, error = _read_json(f"{base}/api/agent/products/{quote(code, safe='')}", timeout=timeout)
        if error:
            return empty("unavailable", "product_hub_manual_product_unavailable")
        product = payload.get("product") if isinstance(payload, dict) else None
        if (
            not payload or payload.get("ok") is not True or not isinstance(product, dict)
            or product.get("productCode") != code or product.get("status") != "active"
            or not isinstance(product.get("id"), str)
            or not _bounded_text(product.get("id"), 128)
        ):
            return empty("invalid_response", "product_hub_manual_product_mismatch")
        query = urlencode({"productCode": code, "type": "manual", "page": 1, "pageSize": 200})
        payload, error = _read_json(f"{base}/api/agent/assets?{query}", timeout=timeout)
        if error:
            return empty("unavailable", "product_hub_manual_assets_unavailable")
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return empty("invalid_response", "product_hub_manual_assets_invalid")
        rows, total = payload.get("items"), payload.get("total")
        if not isinstance(rows, list) or type(total) is not int or not 0 <= total == len(rows) <= 200:
            return empty("invalid_response", "product_hub_manual_list_incomplete")
        ids = [row.get("id") for row in rows if isinstance(row, dict)]
        if len(ids) != len(rows) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            return empty("invalid_response", "product_hub_manual_assets_invalid")
        assets = [asset for row in rows if (asset := _safe_hub_manual(
            row, base=base, product_code=code, product_id=product["id"],
            sku_code=sku, sku_id=resolution["hub_sku_id"],
        ))]
        verified, failures = [], []
        deadline = monotonic() + _MANUAL_FILE_CHECK_BUDGET_SECONDS
        for asset in sorted(assets, key=lambda item: item["asset_id"])[:_MAX_MANUAL_FILE_CHECKS]:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            error = _check_manual_file(asset, timeout=min(timeout, remaining))
            if error:
                failures.append({"asset_id": asset["asset_id"], "reason_code": error})
                continue
            asset.update(availability="header_verified",
                         file_checked_at=datetime.now(timezone.utc).isoformat())
            verified.append(asset)
        unchecked = len(assets) - len(verified) - len(failures)
        return {
            "state": "unavailable" if assets and not verified else "ready",
            "reason_code": "product_hub_manual_no_verified_file" if assets and not verified else "",
            "product_code": code,
            "resolved_sku_code": sku, "identity_source": "product_hub_exact_sku",
            "assets": verified, "file_failures": failures,
            "unchecked_file_count": unchecked, "catalog_candidate_count": len(assets),
        }
