"""Offline, shadow-only observations extracted from product media.

This module deliberately does not persist observations and is not imported by
the formal retrieval, product-context, or reply pipeline.  A media role is
metadata, not proof that the pixels support a product claim.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import requests
from openai import OpenAI

from app import config
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


OBSERVATION_SCHEMA_VERSION = "product_media_observation_shadow_v1"
LOW_RISK_OBSERVATION_TYPES = {
    "layer_count",
    "compartment_count",
    "labelled_dimension",
    "visible_structure",
    "visible_text",
}
HIGH_RISK_TERMS = (
    "load_capacity",
    "bearing_capacity",
    "pinch_safety",
    "child_suitability",
    "child_safety",
    "toxicity",
    "non_toxic",
    "food_grade",
    "certification",
    "stability",
    "anti_tip",
    "installation_prescription",
    "承重",
    "无毒",
    "食品级",
    "认证",
    "检测报告",
    "防倾倒",
    "膨胀螺丝",
)
DIMENSION_ATTRIBUTES = {"width", "height", "depth", "length"}
COUNT_TYPES = {"layer_count", "compartment_count"}
ASSET_ALLOWED_TYPES = {"size_image", "sku_image", "pack_guide_image", "accessory_image"}
DIMENSION_ASSET_TYPES = {"size_image"}
MIN_CONFIDENCE = 0.75
MAX_IMAGE_BYTES = 8 * 1024 * 1024

_OBSERVATION_FIELDS = {
    "observation_type",
    "attribute_key",
    "raw_observation",
    "normalized_value",
    "unit",
    "domain",
    "ocr_text",
    "region",
    "confidence",
}
_MODEL_RESPONSE_FIELDS = {"observations", "model_version"}
_LENGTH_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|毫米|厘米|米)", re.IGNORECASE)
_COUNT_RE = re.compile(r"(?P<value>\d+)\s*(?:层|格|个|层板|隔层)?")


@dataclass(frozen=True)
class ProductMediaObservation:
    observation_uid: str
    media_asset_id: int
    product_id: str
    i_id: str
    sku_code: str
    media_role: str
    observation_type: str
    attribute_key: str
    raw_observation: str
    normalized_value: str | None
    normalized_unit: str | None
    normalized_domain: str | None
    ocr_text: str
    region: dict[str, Any] | None
    confidence: float
    extraction_model: str
    extraction_version: str
    media_content_hash: str
    provenance: dict[str, Any]
    risk_class: str = "low"
    review_status: str = "pending_review"
    direct_answer_allowed: bool = False
    used_for_generation: bool = False
    can_change_can_send: bool = False
    warning_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_obj(asdict(self))


def _text(value: Any) -> str:
    return sanitize_text(str(value or "")).strip()


def _asset_value(asset: Any, key: str) -> Any:
    return asset.get(key) if isinstance(asset, dict) else getattr(asset, key, None)


def _asset_identity(asset: Any) -> dict[str, str]:
    return {
        "product_id": _text(_asset_value(asset, "product_id")),
        "i_id": _text(_asset_value(asset, "i_id")),
        "sku_code": _text(_asset_value(asset, "sku_code")),
    }


def _identity_complete(identity: dict[str, str]) -> bool:
    """An internal i_id is the minimum product scope for this shadow pass.

    SKU-only records can be variant aliases and product_id-only records have no
    durable namespace outside the current database.  They remain diagnostics,
    not observation candidates, until an explicit identity contract exists.
    """
    return bool(identity.get("i_id"))


def identity_scope_issue(actual: dict[str, str], expected: dict[str, Any] | None) -> str:
    """Return an explicit identity issue without attempting namespace mapping."""
    target = {key: _text((expected or {}).get(key)) for key in actual if _text((expected or {}).get(key))}
    if not target:
        return ""
    actual_scoped = {key: value for key, value in actual.items() if value}
    common = set(actual_scoped).intersection(target)
    if not common:
        return "product_identity_namespace_missing"
    if any(actual_scoped[key] != target[key] for key in common):
        return "product_identity_mismatch"
    return ""


def _media_content_hash(asset: Any) -> str:
    existing = _text(_asset_value(asset, "content_hash"))
    if existing:
        return existing
    return ""


def media_asset_eligibility(asset: Any) -> list[str]:
    reasons: list[str] = []
    if _text(_asset_value(asset, "status")).lower() != "approved":
        reasons.append("media_not_approved")
    if not bool(_asset_value(asset, "usable_for_agent")):
        reasons.append("media_not_usable")
    if _text(_asset_value(asset, "asset_type")) not in ASSET_ALLOWED_TYPES:
        reasons.append("media_role_not_supported")
    if not _identity_complete(_asset_identity(asset)):
        reasons.append("product_identity_incomplete")
    if not _media_content_hash(asset):
        reasons.append("media_content_hash_missing")
    if not _text(_asset_value(asset, "asset_url")):
        reasons.append("media_source_missing")
    return reasons


def _safe_model_name() -> str:
    return _text(config.COPILOT_VLM_MODEL)


def vlm_configured() -> bool:
    return bool(
        config.COPILOT_VLM_ENABLED
        and config.COPILOT_VLM_API_BASE
        and config.COPILOT_VLM_API_KEY
        and config.COPILOT_VLM_MODEL
    )


def resolve_product_media_image(asset: Any, *, timeout_seconds: int = 20) -> tuple[bytes, str] | None:
    """Read a media asset only for the offline extractor; never persist bytes."""
    raw = _asset_value(asset, "source_raw") or {}
    if not isinstance(raw, dict) and hasattr(asset, "get_source_raw"):
        raw = asset.get_source_raw() or {}
    url = _text(_asset_value(asset, "asset_url"))
    if url.startswith("/ask/api/media-assets/uploads/"):
        relative = url.removeprefix("/ask/api/media-assets/uploads/")
        path = Path(config.BASE_DIR) / "app" / "media_uploads" / relative
        if path.is_file():
            return path.read_bytes(), path.suffix or ".png"
    original_path = _text(raw.get("original_path")) if isinstance(raw, dict) else ""
    if original_path and Path(original_path).is_file():
        path = Path(original_path)
        return path.read_bytes(), path.suffix or ".png"
    if url.startswith(("http://", "https://")):
        response = requests.get(url, timeout=max(1, min(timeout_seconds, 30)))
        response.raise_for_status()
        data = response.content
        if not data or len(data) > MAX_IMAGE_BYTES:
            return None
        return data, Path(url.split("?", 1)[0]).suffix or ".png"
    return None


def _image_data_url(image_bytes: bytes, extension: str) -> str:
    suffix = extension.lower().lstrip(".")
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix or 'png'}"
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _model_prompt(asset: Any) -> str:
    media_role = _text(_asset_value(asset, "asset_type"))
    return (
        "Extract only visible, low-risk observations from this product image. "
        "Return strict JSON with exactly model_version and observations. "
        "Each observation must contain exactly observation_type, attribute_key, "
        "raw_observation, normalized_value, unit, domain, ocr_text, region, confidence. "
        "Allowed observation_type values: layer_count, compartment_count, labelled_dimension, "
        "visible_structure, visible_text. Do not infer load capacity, safety, toxicity, "
        "certification, stability, or installation instructions. "
        f"The asset role is {media_role}; it is metadata and does not prove image contents."
    )


def call_product_media_vlm(asset: Any, image_bytes: bytes, extension: str, *, timeout_seconds: int = 20) -> dict[str, Any]:
    """Use the existing OpenAI-compatible customer-image VLM configuration."""
    timeout = max(1, min(timeout_seconds, config.COPILOT_VLM_TIMEOUT_SECONDS, 30))
    client = OpenAI(
        api_key=config.COPILOT_VLM_API_KEY,
        base_url=config.COPILOT_VLM_API_BASE,
        max_retries=0,
        timeout=timeout,
    )
    response = client.chat.completions.create(
        model=config.COPILOT_VLM_MODEL,
        messages=[
            {"role": "system", "content": "You extract attributable product-media observations as strict JSON."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _model_prompt(asset)},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_bytes, extension)}},
                ],
            },
        ],
        temperature=0,
        max_tokens=1000,
        response_format={"type": "json_object"},
        timeout=timeout,
    )
    raw = response.choices[0].message.content or ""
    return json.loads(raw)


def _number(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalize_dimension(raw: str, value: Any, unit: Any) -> tuple[str | None, str | None, str | None]:
    match = _LENGTH_RE.search(f"{value or ''} {unit or ''}") or _LENGTH_RE.search(raw)
    if not match:
        return None, None, None
    number = _number(match.group("value"))
    if number is None:
        return None, None, None
    source_unit = match.group("unit").lower()
    multiplier = {"mm": Decimal("0.1"), "毫米": Decimal("0.1"), "cm": Decimal("1"), "厘米": Decimal("1"), "m": Decimal("100"), "米": Decimal("100")}[source_unit]
    normalized = (number * multiplier).normalize()
    return format(normalized, "f"), "cm", "length_metric"


def _normalize_count(raw: str, value: Any) -> tuple[str | None, str | None, str | None]:
    number = _number(value)
    if number is None:
        match = _COUNT_RE.search(raw)
        number = _number(match.group("value")) if match else None
    if number is None or number < 0 or number != number.to_integral_value():
        return None, None, None
    return str(int(number)), "count", "count"


def _has_high_risk_signal(*values: Any) -> bool:
    text = " ".join(_text(value).lower() for value in values)
    return any(term.lower() in text for term in HIGH_RISK_TERMS)


def _stable_uid(*parts: str) -> str:
    raw = "|".join(parts)
    return "pmo_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class ProductMediaObservationExtractor:
    """Converts one approved media asset into pending, offline observations."""

    def __init__(self, model_runner: Callable[[Any, bytes, str, int], dict[str, Any]] | None = None):
        self._model_runner = model_runner

    def extract_asset(
        self,
        asset: Any,
        *,
        expected_product_identity: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        reasons = media_asset_eligibility(asset)
        scope_issue = identity_scope_issue(_asset_identity(asset), expected_product_identity)
        if scope_issue:
            reasons.append(scope_issue)
        asset_id = _asset_value(asset, "id") or _asset_value(asset, "asset_id")
        result: dict[str, Any] = {
            "media_asset_id": int(asset_id or 0),
            "observations": [],
            "rejected_evidence": [],
            "warnings": [],
            "model_called": False,
            "model_success": False,
        }
        if reasons:
            result["rejected_evidence"].append({"media_asset_id": result["media_asset_id"], "reason": reasons[0]})
            result["warnings"].extend(reasons)
            return result
        if not vlm_configured() and self._model_runner is None:
            result["rejected_evidence"].append({"media_asset_id": result["media_asset_id"], "reason": "vlm_not_configured"})
            result["warnings"].append("vlm_not_configured")
            return result
        try:
            image = resolve_product_media_image(asset, timeout_seconds=timeout_seconds)
        except Exception as exc:
            result["rejected_evidence"].append({"media_asset_id": result["media_asset_id"], "reason": "media_read_failed"})
            result["warnings"].append(f"media_read_failed:{type(exc).__name__}")
            return result
        if not image:
            result["rejected_evidence"].append({"media_asset_id": result["media_asset_id"], "reason": "media_read_failed"})
            result["warnings"].append("media_read_failed")
            return result
        result["model_called"] = True
        try:
            if self._model_runner is not None:
                raw = self._model_runner(asset, image[0], image[1], timeout_seconds)
            else:
                raw = call_product_media_vlm(asset, image[0], image[1], timeout_seconds=timeout_seconds)
        except Exception as exc:
            result["rejected_evidence"].append({"media_asset_id": result["media_asset_id"], "reason": "vlm_call_failed"})
            result["warnings"].append(f"vlm_call_failed:{type(exc).__name__}")
            return result
        result["model_success"] = True
        parsed = self._parse_response(asset, raw)
        result["observations"] = [item.to_dict() for item in parsed["observations"]]
        result["rejected_evidence"].extend(parsed["rejected_evidence"])
        result["warnings"].extend(parsed["warnings"])
        return result

    def _parse_response(self, asset: Any, raw: Any) -> dict[str, Any]:
        parsed = raw if isinstance(raw, dict) else {}
        if set(parsed) - _MODEL_RESPONSE_FIELDS or not isinstance(parsed.get("observations"), list):
            return {
                "observations": [],
                "rejected_evidence": [{"media_asset_id": _asset_value(asset, "id"), "reason": "model_response_schema_invalid"}],
                "warnings": ["model_response_schema_invalid"],
            }
        observations: list[ProductMediaObservation] = []
        rejected: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, item in enumerate(parsed["observations"]):
            candidate, reason, candidate_warnings = self._parse_observation(asset, item, parsed.get("model_version"))
            warnings.extend(candidate_warnings)
            if candidate is not None:
                observations.append(candidate)
            else:
                rejected.append({"media_asset_id": _asset_value(asset, "id"), "observation_index": index, "reason": reason})
        observations.sort(key=lambda item: item.observation_uid)
        return {"observations": observations, "rejected_evidence": rejected, "warnings": sorted(set(warnings))}

    def _parse_observation(self, asset: Any, item: Any, model_version: Any) -> tuple[ProductMediaObservation | None, str, list[str]]:
        if not isinstance(item, dict) or set(item) - _OBSERVATION_FIELDS:
            return None, "observation_schema_invalid", []
        observation_type = _text(item.get("observation_type")).lower()
        raw_observation = _text(item.get("raw_observation"))
        attribute_key = _text(item.get("attribute_key")).lower()
        ocr_text = _text(item.get("ocr_text"))
        if observation_type not in LOW_RISK_OBSERVATION_TYPES or not raw_observation:
            return None, "observation_type_invalid", []
        if _has_high_risk_signal(observation_type, attribute_key, raw_observation, ocr_text):
            return None, "out_of_scope_high_risk", []
        media_role = _text(_asset_value(asset, "asset_type"))
        if observation_type == "labelled_dimension":
            if media_role not in DIMENSION_ASSET_TYPES:
                return None, "media_role_not_dimension_source", []
            if attribute_key not in DIMENSION_ATTRIBUTES:
                return None, "dimension_attribute_invalid", []
            normalized_value, normalized_unit, normalized_domain = _normalize_dimension(raw_observation, item.get("normalized_value"), item.get("unit"))
            if normalized_value is None:
                return None, "dimension_normalization_failed", []
        elif observation_type in COUNT_TYPES:
            if not attribute_key:
                attribute_key = observation_type
            normalized_value, normalized_unit, normalized_domain = _normalize_count(raw_observation, item.get("normalized_value"))
            if normalized_value is None:
                return None, "count_normalization_failed", []
        else:
            attribute_key = attribute_key or observation_type
            normalized_value = normalized_unit = normalized_domain = None
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            return None, "confidence_invalid", []
        if not 0.0 <= confidence <= 1.0:
            return None, "confidence_invalid", []
        if confidence < MIN_CONFIDENCE:
            return None, "low_confidence", ["low_confidence"]
        region = item.get("region")
        if region is not None and not isinstance(region, dict):
            return None, "region_invalid", []
        warning_reasons = ["region_missing"] if region is None else []
        identity = _asset_identity(asset)
        content_hash = _media_content_hash(asset)
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        uid = _stable_uid(
            content_hash,
            identity["product_id"],
            identity["i_id"],
            identity["sku_code"],
            observation_type,
            attribute_key,
            raw_observation,
            normalized_value or "",
            normalized_unit or "",
        )
        provenance = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "media_asset_id": asset_id,
            "media_content_hash": content_hash,
            "identity_scope": [
                {"namespace": key, "value": value}
                for key, value in identity.items() if value
            ],
            "source": _text(_asset_value(asset, "source")),
        }
        return ProductMediaObservation(
            observation_uid=uid,
            media_asset_id=asset_id,
            product_id=identity["product_id"],
            i_id=identity["i_id"],
            sku_code=identity["sku_code"],
            media_role=media_role,
            observation_type=observation_type,
            attribute_key=attribute_key,
            raw_observation=raw_observation,
            normalized_value=normalized_value,
            normalized_unit=normalized_unit,
            normalized_domain=normalized_domain,
            ocr_text=ocr_text,
            region=region,
            confidence=confidence,
            extraction_model=_safe_model_name() or "configured_openai_compatible_vlm",
            extraction_version=_text(model_version) or OBSERVATION_SCHEMA_VERSION,
            media_content_hash=content_hash,
            provenance=provenance,
            warning_reasons=warning_reasons,
        ), "", warning_reasons
