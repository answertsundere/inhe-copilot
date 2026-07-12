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
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from app import config
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


OBSERVATION_SCHEMA_VERSION = "product_media_observation_shadow_v2"
OBSERVATION_ATTRIBUTE_CONTRACT_VERSION = "product_media_observation_attributes_v1"
LOW_RISK_OBSERVATION_TYPES = {
    "layer_count",
    "compartment_count",
    "labelled_dimension",
    "visible_structure",
    "visible_text",
}
DIMENSION_ATTRIBUTES = {"width", "height", "depth", "length"}
COUNT_TYPES = {"layer_count", "compartment_count"}
ASSET_ALLOWED_TYPES = {"size_image", "sku_image", "pack_guide_image", "accessory_image"}
DIMENSION_ASSET_TYPES = {"size_image"}
MIN_CONFIDENCE = 0.75
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PRODUCT_MEDIA_VLM_MAX_TOKENS = 4096

# This is a shadow-only contract, not a product-fact registry.  Every accepted
# type/key pair must be listed positively; text observations cannot smuggle an
# unsupported attribute through an OCR label.
OBSERVATION_TYPE_ATTRIBUTE_ALLOWLIST = {
    "layer_count": {"layer_count"},
    "compartment_count": {"compartment_count"},
    "labelled_dimension": DIMENSION_ATTRIBUTES,
    "visible_structure": {
        "visible_structure",
        "shelf_layout",
        "open_compartment",
        "door_layout",
        "drawer_layout",
        "partition_layout",
    },
    "visible_text": {"visible_text"},
}

# Canonical high-risk attributes are a veto layer over the positive allowlist.
# Aliases cover model field names and visual/OCR text, but do not create any
# new eligible observation type.
HIGH_RISK_ATTRIBUTE_ALIASES = {
    "age_range": {"age_range", "suitable_age", "applicable_age", "\u9002\u7528\u5e74\u9f84", "\u51e0\u5c81", "\u5b9d\u5b9d\u53ef\u7528"},
    "child_suitability": {"child_suitability", "\u513f\u7ae5\u9002\u7528", "\u5a74\u513f\u9002\u7528"},
    "child_safety": {"child_safety", "\u513f\u7ae5\u5b89\u5168", "\u5b9d\u5b9d\u5b89\u5168"},
    "pinch_safety": {"pinch_safety", "pinch_protection", "anti_pinch", "\u9632\u5939", "\u5939\u624b", "\u5939\u811a"},
    "load_capacity": {"load_capacity", "bearing_capacity", "weight_limit", "\u627f\u91cd", "\u8f7d\u91cd"},
    "toxicity": {"toxicity", "non_toxic", "\u65e0\u6bd2", "\u6709\u6bd2"},
    "food_grade": {"food_grade", "\u98df\u54c1\u7ea7"},
    "certification": {"certification", "certification_report", "test_report", "\u8ba4\u8bc1", "\u5408\u683c\u8bc1", "\u68c0\u6d4b\u62a5\u544a"},
    "stability": {"stability", "anti_tip", "\u7a33\u56fa", "\u9632\u503e\u5012"},
    "installation_prescription": {
        "installation_method", "installation_prescription", "wall_fixing", "expansion_screw",
        "structural_modification", "\u56fa\u5b9a\u5230\u5899", "\u81a8\u80c0\u87ba\u4e1d", "\u6253\u5b54", "\u6539\u88c5",
    },
}

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
_LENGTH_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|\u6beb\u7c73|\u5398\u7c73|\u7c73)", re.IGNORECASE)
_COUNT_RE = re.compile(r"(?P<value>\d+)\s*(?:\u5c42|\u683c|\u4e2a|\u5c42\u677f|\u9694\u5c42)?")
_AGE_RANGE_CLAIM_RE = re.compile(
    r"(?:\d{1,2}\s*(?:\u5468\u5c81|\u5c81|years?\s*old))(?:\s*(?:\u4ee5\u4e0a|\u4ee5\u4e0b|[-~\u81f3\u5230]\s*\d{1,2}\s*(?:\u5468\u5c81|\u5c81|years?\s*old)))?",
    re.IGNORECASE,
)
_FORMALDEHYDE_SAFETY_CLAIM_RE = re.compile(
    r"(?:\u65e0|\u4e0d\u542b|\u96f6)\s*(?:\u7532\u919b|\u919b)|formaldehyde[-\s]?free",
    re.IGNORECASE,
)


class ProductMediaObservationProviderError(RuntimeError):
    """The configured VLM endpoint did not complete a bounded request."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


class ProductMediaObservationSchemaError(ValueError):
    """The VLM returned no parseable observation schema."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class ProductMediaVlmConnection:
    """Explicit OpenAI-compatible connection values for shadow-only probes."""

    api_base: str
    api_key: str
    model: str


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
    observed_media_sha256: str
    asset_content_hash: str
    hash_comparison_status: str
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


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value.lower()))


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


def _looks_like_placeholder(value: Any) -> bool:
    normalized = _text(value).lower()
    if not normalized:
        return True
    return normalized in {"none", "null", "placeholder", "changeme", "your-api-key", "your_api_key"} or normalized.startswith("<")


def vlm_configuration_status() -> dict[str, bool]:
    return {
        "enabled": bool(config.COPILOT_VLM_ENABLED),
        "api_base_configured": not _looks_like_placeholder(config.COPILOT_VLM_API_BASE),
        "api_key_configured": not _looks_like_placeholder(config.COPILOT_VLM_API_KEY),
        "model_configured": not _looks_like_placeholder(config.COPILOT_VLM_MODEL),
    }


def vlm_configured() -> bool:
    status = vlm_configuration_status()
    return all(status.values())


def configured_product_media_vlm_connection() -> ProductMediaVlmConnection:
    return ProductMediaVlmConnection(
        api_base=str(config.COPILOT_VLM_API_BASE or ""),
        api_key=str(config.COPILOT_VLM_API_KEY or ""),
        model=str(config.COPILOT_VLM_MODEL or ""),
    )


def _read_local_image(path: Path) -> tuple[bytes, str] | None:
    if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        return None
    data = path.read_bytes()
    return (data, path.suffix or ".png") if data else None


def resolve_product_media_image(asset: Any, *, timeout_seconds: int = 20) -> tuple[bytes, str] | None:
    """Read a media asset only for the offline extractor; never persist bytes."""
    raw = _asset_value(asset, "source_raw") or {}
    if not isinstance(raw, dict) and hasattr(asset, "get_source_raw"):
        raw = asset.get_source_raw() or {}
    url = _text(_asset_value(asset, "asset_url"))
    if url.startswith("/ask/api/media-assets/uploads/"):
        relative = url.removeprefix("/ask/api/media-assets/uploads/")
        path = Path(config.BASE_DIR) / "app" / "media_uploads" / relative
        return _read_local_image(path)
    original_path = _text(raw.get("original_path")) if isinstance(raw, dict) else ""
    if original_path:
        return _read_local_image(Path(original_path))
    if url.startswith(("http://", "https://")):
        with requests.get(url, timeout=max(1, min(timeout_seconds, 30)), stream=True) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    return None
                chunks.append(chunk)
        data = b"".join(chunks)
        return (data, Path(url.split("?", 1)[0]).suffix or ".png") if data else None
    return None


def _image_data_url(image_bytes: bytes, extension: str) -> str:
    suffix = extension.lower().lstrip(".")
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix or 'png'}"
    return f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _model_prompt(asset: Any, *, max_observations: int = 10) -> str:
    media_role = _text(_asset_value(asset, "asset_type"))
    return (
        f"Return one JSON object only with model_version and observations (maximum {max_observations}). "
        "Each observation has exactly observation_type, attribute_key, raw_observation, "
        "normalized_value, unit, domain, ocr_text, region, confidence. Allowed types are "
        "layer_count, compartment_count, labelled_dimension, visible_structure, visible_text. "
        "Use only these exact type/key pairs: layer_count/layer_count, "
        "compartment_count/compartment_count, labelled_dimension/width|height|depth|length, "
        "visible_structure/visible_structure|shelf_layout|open_compartment|door_layout|drawer_layout|partition_layout, "
        "visible_text/visible_text. Region must be null unless you can provide a JSON object; "
        "never use a prose location string for region. "
        "Extract only visible low-risk details. Do not include reasoning or infer load, safety, "
        "toxicity, certification, stability, or installation instructions. "
        f"Asset role: {media_role}; role metadata is not visual proof."
    )


def _safe_http_status_category(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return "4xx" if 400 <= status < 500 else "5xx" if 500 <= status < 600 else "other"
    return ""


def _is_unsupported_response_format(exc: Exception) -> bool:
    if not isinstance(exc, APIStatusError) and _safe_http_status_category(exc) != "4xx":
        return False
    message = str(exc).lower()
    return "response_format" in message and any(
        marker in message for marker in ("unsupported", "not support", "unknown parameter", "invalid parameter")
    )


def _classify_vlm_exception(exc: Exception) -> str:
    if _is_unsupported_response_format(exc):
        return "unsupported_parameter"
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return "authentication_error"
    if isinstance(exc, RateLimitError):
        return "rate_limit_error"
    if isinstance(exc, APITimeoutError) or isinstance(exc, TimeoutError):
        return "timeout_error"
    if isinstance(exc, (APIConnectionError, InternalServerError)):
        return "provider_error"
    if _safe_http_status_category(exc) == "5xx":
        return "provider_error"
    return "provider_error"


def _response_metadata(response: Any, raw: str) -> dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    message = getattr(choice, "message", None)
    usage = getattr(response, "usage", None)
    return {
        "http_status_category": "",
        "sdk_exception_class": "",
        "finish_reason": _text(getattr(choice, "finish_reason", "")).lower(),
        "content_present": bool(raw.strip()),
        "content_length": len(raw),
        "content_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else "",
        "starts_with_markdown_fence": raw.lstrip().startswith("```"),
        "complete_json_object_detected": False,
        "json_parse_success": False,
        "schema_parse_success": False,
        "reasoning_content_present": bool(_text(getattr(message, "reasoning_content", ""))),
        "refusal_present": bool(_text(getattr(message, "refusal", ""))),
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
    }


_OUTER_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(\{.*\})\s*```\s*$", re.IGNORECASE | re.DOTALL)


def _normalize_complete_json_object(raw: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if metadata["finish_reason"] in {"length", "max_tokens"}:
        raise ProductMediaObservationSchemaError("truncated_response")
    if not raw.strip():
        raise ProductMediaObservationSchemaError("empty_response")
    text = raw.strip()
    fenced = _OUTER_JSON_FENCE_RE.fullmatch(text)
    if fenced:
        text = fenced.group(1).strip()
    metadata["complete_json_object_detected"] = text.startswith("{") and text.endswith("}")
    if not metadata["complete_json_object_detected"]:
        raise ProductMediaObservationSchemaError("non_json_response")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProductMediaObservationSchemaError("non_json_response") from exc
    metadata["json_parse_success"] = True
    if (
        not isinstance(parsed, dict)
        or set(parsed) - _MODEL_RESPONSE_FIELDS
        or not isinstance(parsed.get("observations"), list)
    ):
        raise ProductMediaObservationSchemaError("schema_error")
    metadata["schema_parse_success"] = True
    return parsed


def _request_variant_payload(
    asset: Any,
    image_bytes: bytes,
    extension: str,
    *,
    connection: ProductMediaVlmConnection,
    timeout: int,
    variant: str,
    max_tokens: int | None = None,
    max_observations: int = 10,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profiles = {
        "product_media_response_format": {"max_tokens": PRODUCT_MEDIA_VLM_MAX_TOKENS, "response_format": True},
        "customer_image_response_format": {"max_tokens": 1200, "response_format": True},
        "sidecar_plain_json": {"max_tokens": 4096, "response_format": False},
        "plain_json_prompt": {"max_tokens": PRODUCT_MEDIA_VLM_MAX_TOKENS, "response_format": False},
    }
    if variant not in profiles:
        raise ValueError("unknown_vlm_request_variant")
    profile = profiles[variant]
    request = {
        "model": connection.model,
        "messages": [
            {"role": "system", "content": "Extract attributable product-media observations as strict JSON."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _model_prompt(asset, max_observations=max_observations)},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_bytes, extension)}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens or profile["max_tokens"],
        "timeout": timeout,
    }
    if profile["response_format"]:
        request["response_format"] = {"type": "json_object"}
    if chat_template_kwargs:
        request["chat_template_kwargs"] = dict(chat_template_kwargs)
    return request


def _run_product_media_vlm_variant(
    asset: Any,
    image_bytes: bytes,
    extension: str,
    *,
    connection: ProductMediaVlmConnection | None = None,
    timeout_seconds: int,
    variant: str,
    max_tokens: int | None = None,
    max_observations: int = 10,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run one bounded visual request and return only sanitized transport metadata."""
    has_explicit_connection = connection is not None
    connection = connection or configured_product_media_vlm_connection()
    timeout_ceiling = 45 if has_explicit_connection else config.COPILOT_VLM_TIMEOUT_SECONDS
    timeout = max(1, min(timeout_seconds, timeout_ceiling, 45))
    client = OpenAI(
        api_key=connection.api_key,
        base_url=connection.api_base,
        max_retries=0,
        timeout=timeout,
    )
    request = _request_variant_payload(
        asset,
        image_bytes,
        extension,
        connection=connection,
        timeout=timeout,
        variant=variant,
        max_tokens=max_tokens,
        max_observations=max_observations,
        chat_template_kwargs=chat_template_kwargs,
    )
    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        category = _classify_vlm_exception(exc)
        return None, {
            "request_variant": variant,
            "sdk_exception_class": type(exc).__name__,
            "http_status_category": _safe_http_status_category(exc),
            "error_category": category,
            "finish_reason": "",
            "content_present": False,
            "content_length": 0,
            "content_sha256": "",
            "starts_with_markdown_fence": False,
            "complete_json_object_detected": False,
            "json_parse_success": False,
            "schema_parse_success": False,
            "reasoning_content_present": False,
            "refusal_present": False,
            "prompt_tokens": None,
            "completion_tokens": None,
        }
    raw = response.choices[0].message.content or ""
    metadata = _response_metadata(response, raw)
    metadata["request_variant"] = variant
    try:
        parsed = _normalize_complete_json_object(raw, metadata)
    except ProductMediaObservationSchemaError as exc:
        metadata["error_category"] = exc.category
        return None, metadata
    metadata["error_category"] = ""
    return parsed, metadata


def probe_product_media_vlm(
    asset: Any,
    image_bytes: bytes,
    extension: str,
    *,
    timeout_seconds: int = 20,
    request_variant: str = "product_media_response_format",
    allow_compatibility_retry: bool = False,
    connection: ProductMediaVlmConnection | None = None,
) -> dict[str, Any]:
    """Return one safe, read-only provider probe without model text or image data."""
    parsed, metadata = _run_product_media_vlm_variant(
        asset,
        image_bytes,
        extension,
        connection=connection,
        timeout_seconds=timeout_seconds,
        variant=request_variant,
    )
    metadata["retry_count"] = 0
    metadata["retry_reason"] = ""
    if (
        allow_compatibility_retry
        and request_variant == "product_media_response_format"
        and parsed is None
        and metadata.get("error_category") == "unsupported_parameter"
    ):
        _, metadata = _run_product_media_vlm_variant(
            asset,
            image_bytes,
            extension,
            connection=connection,
            timeout_seconds=timeout_seconds,
            variant="plain_json_prompt",
        )
        metadata["retry_count"] = 1
        metadata["retry_reason"] = "unsupported_response_format"
    return metadata


def run_product_media_vlm_transport(
    asset: Any,
    image_bytes: bytes,
    extension: str,
    *,
    timeout_seconds: int = 20,
    connection: ProductMediaVlmConnection | None = None,
    request_variant: str = "product_media_response_format",
    max_tokens: int | None = None,
    max_observations: int = 10,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Execute the production transport contract without exposing model text."""
    parsed, metadata = _run_product_media_vlm_variant(
        asset,
        image_bytes,
        extension,
        connection=connection,
        timeout_seconds=timeout_seconds,
        variant=request_variant,
        max_tokens=max_tokens,
        max_observations=max_observations,
        chat_template_kwargs=chat_template_kwargs,
    )
    metadata["retry_count"] = 0
    metadata["retry_reason"] = ""
    if (
        parsed is None
        and request_variant == "product_media_response_format"
        and metadata.get("error_category") == "unsupported_parameter"
    ):
        parsed, metadata = _run_product_media_vlm_variant(
            asset,
            image_bytes,
            extension,
            connection=connection,
            timeout_seconds=timeout_seconds,
            variant="plain_json_prompt",
            max_tokens=max_tokens,
            max_observations=max_observations,
            chat_template_kwargs=chat_template_kwargs,
        )
        metadata["retry_count"] = 1
        metadata["retry_reason"] = "unsupported_response_format"
    return parsed, metadata


def call_product_media_vlm(
    asset: Any,
    image_bytes: bytes,
    extension: str,
    *,
    timeout_seconds: int = 20,
    max_tokens: int | None = None,
    max_observations: int = 10,
) -> dict[str, Any]:
    """Call the shadow VLM with one explicit compatibility retry at most."""
    parsed, metadata = run_product_media_vlm_transport(
        asset,
        image_bytes,
        extension,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        max_observations=max_observations,
    )
    if parsed is not None:
        return parsed
    category = str(metadata.get("error_category") or "provider_error")
    if category in {"empty_response", "truncated_response", "non_json_response", "schema_error"}:
        raise ProductMediaObservationSchemaError(category)
    raise ProductMediaObservationProviderError(category)


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
    multiplier = {
        "mm": Decimal("0.1"),
        "\u6beb\u7c73": Decimal("0.1"),
        "cm": Decimal("1"),
        "\u5398\u7c73": Decimal("1"),
        "m": Decimal("100"),
        "\u7c73": Decimal("100"),
    }[source_unit]
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


def _high_risk_attribute(*values: Any) -> str:
    text = " ".join(_text(value).lower() for value in values)
    for canonical, aliases in HIGH_RISK_ATTRIBUTE_ALIASES.items():
        if any(alias.lower() in text for alias in aliases):
            return canonical
    if _AGE_RANGE_CLAIM_RE.search(text):
        return "age_range"
    if _FORMALDEHYDE_SAFETY_CLAIM_RE.search(text):
        return "toxicity"
    return ""


def _reject_ambiguous_variant_dimensions(
    observations: list[ProductMediaObservation],
) -> tuple[list[ProductMediaObservation], list[dict[str, Any]]]:
    """Reject dimension values that cannot be attributed to one variant scope."""
    grouped: dict[str, list[ProductMediaObservation]] = {}
    for observation in observations:
        if observation.observation_type == "labelled_dimension" and observation.normalized_value:
            grouped.setdefault(observation.attribute_key, []).append(observation)

    ambiguous_uids: set[str] = set()
    rejected: list[dict[str, Any]] = []
    for group in grouped.values():
        values = {
            (item.normalized_value, item.normalized_unit, item.normalized_domain)
            for item in group
        }
        if len(values) < 2:
            continue
        for item in group:
            ambiguous_uids.add(item.observation_uid)
            rejected.append({
                "media_asset_id": item.media_asset_id,
                "observation_uid": item.observation_uid,
                "attribute_key": item.attribute_key,
                "reason": "ambiguous_variant_dimension_scope",
            })
    return [item for item in observations if item.observation_uid not in ambiguous_uids], rejected


def _stable_uid(*parts: str) -> str:
    raw = "|".join(parts)
    return "pmo_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class ProductMediaObservationExtractor:
    """Converts one approved media asset into pending, offline observations."""

    def __init__(
        self,
        model_runner: Callable[[Any, bytes, str, int], dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        max_observations: int = 10,
        image_preprocessor: Callable[[bytes], Any] | None = None,
    ):
        self._model_runner = model_runner
        self._max_tokens = max_tokens
        self._max_observations = max(1, min(int(max_observations), 10))
        self._image_preprocessor = image_preprocessor

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
            "observed_media_sha256": "",
            "asset_content_hash": _media_content_hash(asset),
            "hash_comparison_status": "not_read",
            "execution_result": "not_started",
            "completion_result": "not_started",
            "execution_failures": [],
            "completion_failures": [],
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
        observed_media_sha256 = hashlib.sha256(image[0]).hexdigest()
        model_image, model_extension = image
        if self._image_preprocessor is not None:
            try:
                prepared = self._image_preprocessor(image[0])
                model_image, model_extension = prepared.data, prepared.extension
                result["preprocessing"] = dict(prepared.provenance)
            except Exception as exc:
                result["execution_result"] = "preprocessing_error"
                result["completion_result"] = "not_started"
                result["execution_failures"].append({"category": "preprocessing_error"})
                result["warnings"].append(f"execution_failure:{type(exc).__name__}")
                return result
        asset_content_hash = _media_content_hash(asset)
        if _is_sha256(asset_content_hash):
            hash_comparison_status = "verified_match" if asset_content_hash.lower() == observed_media_sha256 else "mismatch"
        else:
            hash_comparison_status = "asset_hash_not_comparable"
        result.update({
            "observed_media_sha256": observed_media_sha256,
            "asset_content_hash": asset_content_hash,
            "hash_comparison_status": hash_comparison_status,
        })
        if hash_comparison_status == "mismatch":
            result["rejected_evidence"].append({"media_asset_id": result["media_asset_id"], "reason": "media_content_hash_mismatch"})
            result["warnings"].append("media_content_hash_mismatch")
            return result
        if hash_comparison_status == "asset_hash_not_comparable":
            result["warnings"].append("asset_hash_not_comparable")
        result["model_called"] = True
        try:
            if self._model_runner is not None:
                raw = self._model_runner(asset, model_image, model_extension, timeout_seconds)
            else:
                raw = call_product_media_vlm(
                    asset,
                    model_image,
                    model_extension,
                    timeout_seconds=timeout_seconds,
                    max_tokens=self._max_tokens,
                    max_observations=self._max_observations,
                )
        except ProductMediaObservationSchemaError as exc:
            result["execution_result"] = "success"
            result["completion_result"] = str(exc.category or "schema_invalid")
            result["completion_failures"].append({"category": result["completion_result"]})
            result["warnings"].append(f"completion_failure:{result['completion_result']}")
            return result
        except ProductMediaObservationProviderError as exc:
            category = str(exc.category or "provider_error")
            result["execution_result"] = category
            result["completion_result"] = "not_started"
            result["execution_failures"].append({"category": category})
            result["warnings"].append(f"execution_failure:{category}")
            return result
        except Exception as exc:
            result["execution_result"] = "provider_error"
            result["completion_result"] = "not_started"
            result["execution_failures"].append({"category": "provider_error"})
            result["warnings"].append(f"execution_failure:{type(exc).__name__}")
            return result
        result["model_success"] = True
        result["execution_result"] = "success"
        result["completion_result"] = "complete_json"
        parsed = self._parse_response(
            asset,
            raw,
            observed_media_sha256=observed_media_sha256,
            hash_comparison_status=hash_comparison_status,
        )
        result["observations"] = [item.to_dict() for item in parsed["observations"]]
        if result.get("preprocessing"):
            for item in result["observations"]:
                item.setdefault("provenance", {})["preprocessing"] = result["preprocessing"]
        result["rejected_evidence"].extend(parsed["rejected_evidence"])
        result["warnings"].extend(parsed["warnings"])
        return result

    def _parse_response(
        self,
        asset: Any,
        raw: Any,
        *,
        observed_media_sha256: str,
        hash_comparison_status: str,
    ) -> dict[str, Any]:
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
            candidate, reason, candidate_warnings = self._parse_observation(
                asset,
                item,
                parsed.get("model_version"),
                observed_media_sha256=observed_media_sha256,
                hash_comparison_status=hash_comparison_status,
            )
            warnings.extend(candidate_warnings)
            if candidate is not None:
                observations.append(candidate)
            else:
                rejected.append({"media_asset_id": _asset_value(asset, "id"), "observation_index": index, "reason": reason})
        observations, ambiguous_dimensions = _reject_ambiguous_variant_dimensions(observations)
        rejected.extend(ambiguous_dimensions)
        observations.sort(key=lambda item: item.observation_uid)
        return {"observations": observations, "rejected_evidence": rejected, "warnings": sorted(set(warnings))}

    def _parse_observation(
        self,
        asset: Any,
        item: Any,
        model_version: Any,
        *,
        observed_media_sha256: str,
        hash_comparison_status: str,
    ) -> tuple[ProductMediaObservation | None, str, list[str]]:
        if not isinstance(item, dict) or set(item) - _OBSERVATION_FIELDS:
            return None, "observation_schema_invalid", []
        observation_type = _text(item.get("observation_type")).lower()
        raw_observation = _text(item.get("raw_observation"))
        attribute_key = _text(item.get("attribute_key")).lower()
        ocr_text = _text(item.get("ocr_text"))
        if observation_type not in LOW_RISK_OBSERVATION_TYPES or not raw_observation:
            return None, "observation_contract_unknown", []
        if _high_risk_attribute(observation_type, attribute_key, raw_observation, ocr_text):
            return None, "out_of_scope_high_risk", []
        media_role = _text(_asset_value(asset, "asset_type"))
        allowed_keys = OBSERVATION_TYPE_ATTRIBUTE_ALLOWLIST.get(observation_type, set())
        if attribute_key not in allowed_keys:
            return None, "attribute_not_allowed", []
        if observation_type == "labelled_dimension":
            if media_role not in DIMENSION_ASSET_TYPES:
                return None, "media_role_not_dimension_source", []
            normalized_value, normalized_unit, normalized_domain = _normalize_dimension(raw_observation, item.get("normalized_value"), item.get("unit"))
            if normalized_value is None:
                return None, "dimension_normalization_failed", []
        elif observation_type in COUNT_TYPES:
            normalized_value, normalized_unit, normalized_domain = _normalize_count(raw_observation, item.get("normalized_value"))
            if normalized_value is None:
                return None, "count_normalization_failed", []
        else:
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
            observed_media_sha256,
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
            "attribute_contract_version": OBSERVATION_ATTRIBUTE_CONTRACT_VERSION,
            "media_asset_id": asset_id,
            "observed_media_sha256": observed_media_sha256,
            "asset_content_hash": content_hash,
            "hash_comparison_status": hash_comparison_status,
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
            observed_media_sha256=observed_media_sha256,
            asset_content_hash=content_hash,
            hash_comparison_status=hash_comparison_status,
            provenance=provenance,
            warning_reasons=warning_reasons,
        ), "", warning_reasons
