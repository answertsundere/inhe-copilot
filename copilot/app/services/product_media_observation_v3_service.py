"""Shadow-only product-media observations with object and measurement bindings.

The v3 contract intentionally stays outside formal retrieval and reply delivery.
It records what an offline model observed, not what the customer-service Agent
is permitted to claim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.services.product_media_observation_service import (
    _asset_identity,
    _asset_value,
    _high_risk_attribute,
    _media_content_hash,
    identity_scope_issue,
    media_asset_eligibility,
    resolve_product_media_image,
)


V3_SCHEMA_VERSION = "product_media_observation_v3"
SUBJECT_SCOPES = {"product", "packaging", "component", "accessory", "included_item", "display_prop"}
MEASUREMENT_AXES = {"length", "width", "height", "depth", "thickness", "diameter", "capacity", "count"}
OBSERVATION_TYPES = {"labelled_measurement", "count", "visible_structure", "visible_text"}
_OBSERVATION_FIELDS = {
    "subject_scope", "subject_ref", "subject_label", "state_or_mode", "parent_subject_ref",
    "observation_type", "attribute_key", "measurement_axis", "raw_observation", "value", "unit",
    "evidence_text", "object_bbox", "label_bbox", "confidence",
}


def v3_model_prompt(*, max_observations: int) -> str:
    return (
        f"Return one JSON object only. schema_version must be {V3_SCHEMA_VERSION}; maximum observations is {max_observations}. "
        "Each observation must include subject_scope, subject_ref, subject_label, state_or_mode, parent_subject_ref, "
        "observation_type, attribute_key, measurement_axis, raw_observation, value, unit, evidence_text, "
        "object_bbox, label_bbox, confidence. subject_scope is product, packaging, component, accessory, included_item, "
        "or display_prop. observation_type is labelled_measurement, count, visible_structure, or visible_text. "
        "measurement_axis is length, width, height, depth, thickness, diameter, capacity, or count. "
        "Use object_bbox and label_bbox as x,y,width,height numbers in a 0-1000 image coordinate system. "
        "For a labelled measurement provide both boxes, value, and unit. Do not infer load, safety, toxicity, certification, "
        "child suitability, wall fixing, drilling, or installation instructions. Keep uncertain text as visible_text."
    )


def parse_v3_model_json(content: Any) -> dict[str, Any]:
    text = _text(content)
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("v3_non_json_response") from exc
    if not isinstance(payload, dict):
        raise ValueError("v3_model_response_not_object")
    return payload


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        return None
    try:
        result = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (TypeError, ValueError):
        return None
    if any(number < 0 or number > 1000 for number in result.values()):
        return None
    return result


def _uid(*parts: str) -> str:
    return "pmov3_" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ProductMediaObservationV3:
    observation_uid: str
    media_asset_id: int
    product_identity: dict[str, str]
    subject_scope: str
    subject_ref: str
    subject_label: str
    state_or_mode: str
    parent_subject_ref: str
    observation_type: str
    attribute_key: str
    measurement_axis: str
    raw_observation: str
    value: str
    unit: str
    evidence_text: str
    object_bbox: dict[str, float] | None
    label_bbox: dict[str, float] | None
    confidence: float
    provenance: dict[str, Any]
    warning_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update({
            "review_status": "pending_review",
            "direct_answer_allowed": False,
            "used_for_generation": False,
            "can_change_can_send": False,
        })
        return data


class ProductMediaObservationV3Extractor:
    """Validates object-bound offline observations from one product-media asset."""

    def __init__(self, model_runner: Callable[[Any, bytes, str, int], dict[str, Any]]):
        self._model_runner = model_runner

    def extract_asset(
        self,
        asset: Any,
        *,
        expected_product_identity: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        result = {"media_asset_id": asset_id, "observations": [], "rejected_evidence": [], "warnings": []}
        reasons = media_asset_eligibility(asset)
        scope_issue = identity_scope_issue(_asset_identity(asset), expected_product_identity)
        if scope_issue:
            reasons.append(scope_issue)
        if reasons:
            result["rejected_evidence"].append({"media_asset_id": asset_id, "reason": reasons[0]})
            result["warnings"].extend(reasons)
            return result
        image = resolve_product_media_image(asset, timeout_seconds=timeout_seconds)
        if not image:
            result["rejected_evidence"].append({"media_asset_id": asset_id, "reason": "media_read_failed"})
            return result
        raw = self._model_runner(asset, image[0], image[1], timeout_seconds)
        parsed = self._parse(asset, raw, hashlib.sha256(image[0]).hexdigest())
        result.update(parsed)
        return result

    def _parse(self, asset: Any, raw: Any, observed_media_sha256: str) -> dict[str, Any]:
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        if not isinstance(raw, dict) or set(raw) - {"schema_version", "model_version", "observations"}:
            return {"observations": [], "rejected_evidence": [{"media_asset_id": asset_id, "reason": "model_response_schema_invalid"}], "warnings": []}
        if raw.get("schema_version") != V3_SCHEMA_VERSION or not isinstance(raw.get("observations"), list):
            return {"observations": [], "rejected_evidence": [{"media_asset_id": asset_id, "reason": "model_response_schema_invalid"}], "warnings": []}
        accepted: list[ProductMediaObservationV3] = []
        rejected: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, item in enumerate(raw["observations"]):
            observation, reason = self._validate(asset, item, observed_media_sha256, _text(raw.get("model_version")))
            if observation is None:
                rejected.append({"media_asset_id": asset_id, "observation_index": index, "reason": reason})
            else:
                accepted.append(observation)
                warnings.extend(observation.warning_reasons)
        accepted.sort(key=lambda item: item.observation_uid)
        return {"observations": [item.to_dict() for item in accepted], "rejected_evidence": rejected, "warnings": sorted(set(warnings))}

    def _validate(
        self, asset: Any, item: Any, observed_media_sha256: str, model_version: str,
    ) -> tuple[ProductMediaObservationV3 | None, str]:
        if not isinstance(item, dict) or set(item) - _OBSERVATION_FIELDS:
            return None, "observation_schema_invalid"
        scope = _text(item.get("subject_scope")).lower()
        subject_ref = _text(item.get("subject_ref"))
        subject_label = _text(item.get("subject_label"))
        state_or_mode = _text(item.get("state_or_mode"))
        parent_ref = _text(item.get("parent_subject_ref"))
        observation_type = _text(item.get("observation_type")).lower()
        attribute_key = _text(item.get("attribute_key")).lower()
        axis = _text(item.get("measurement_axis")).lower()
        raw_observation = _text(item.get("raw_observation"))
        value = _text(item.get("value"))
        unit = _text(item.get("unit"))
        evidence_text = _text(item.get("evidence_text"))
        object_bbox = _bbox(item.get("object_bbox"))
        label_bbox = _bbox(item.get("label_bbox"))
        if scope not in SUBJECT_SCOPES or not subject_ref or not subject_label or not raw_observation:
            return None, "subject_binding_missing"
        if parent_ref == subject_ref:
            return None, "subject_parent_self_reference"
        if observation_type not in OBSERVATION_TYPES:
            return None, "observation_type_not_allowed"
        if _high_risk_attribute(subject_label, state_or_mode, attribute_key, raw_observation, evidence_text):
            return None, "out_of_scope_high_risk"
        if observation_type == "visible_text":
            return None, "visible_text_reference_only"
        if object_bbox is None:
            return None, "object_bbox_required"
        if observation_type == "labelled_measurement":
            if axis not in MEASUREMENT_AXES - {"count"} or not value or not unit or label_bbox is None:
                return None, "measurement_target_binding_missing"
        elif observation_type == "count":
            if axis != "count" or not value:
                return None, "count_binding_invalid"
        elif axis:
            return None, "measurement_axis_not_allowed"
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            return None, "confidence_invalid"
        if not 0.0 <= confidence <= 1.0 or confidence < 0.75:
            return None, "low_confidence"
        identity = _asset_identity(asset)
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        warning_reasons: list[str] = []
        if observation_type == "labelled_measurement" and scope != "product":
            warning_reasons.append(f"{scope}_measurement_not_product_dimension")
        provenance = {
            "schema_version": V3_SCHEMA_VERSION,
            "model_version": model_version,
            "media_asset_id": asset_id,
            "observed_media_sha256": observed_media_sha256,
            "asset_content_hash": _media_content_hash(asset),
            "identity_scope": [{"namespace": key, "value": value} for key, value in identity.items() if value],
        }
        uid = _uid(observed_media_sha256, scope, subject_ref, state_or_mode, observation_type, attribute_key, axis, value, unit)
        return ProductMediaObservationV3(
            observation_uid=uid, media_asset_id=asset_id, product_identity=identity,
            subject_scope=scope, subject_ref=subject_ref, subject_label=subject_label,
            state_or_mode=state_or_mode, parent_subject_ref=parent_ref,
            observation_type=observation_type, attribute_key=attribute_key, measurement_axis=axis,
            raw_observation=raw_observation, value=value, unit=unit, evidence_text=evidence_text,
            object_bbox=object_bbox, label_bbox=label_bbox, confidence=confidence,
            provenance=provenance, warning_reasons=warning_reasons,
        ), ""


def build_product_understanding_graph(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a read-only graph from already validated v3 observations."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    warnings: list[str] = []
    for observation in sorted(observations, key=lambda item: _text(item.get("observation_uid"))):
        subject_ref = _text(observation.get("subject_ref"))
        if not subject_ref:
            continue
        nodes.setdefault(subject_ref, {
            "subject_ref": subject_ref,
            "subject_scope": _text(observation.get("subject_scope")),
            "subject_label": _text(observation.get("subject_label")),
            "state_or_mode": _text(observation.get("state_or_mode")),
        })
        parent = _text(observation.get("parent_subject_ref"))
        if parent:
            if parent in nodes:
                edges.append({"from": subject_ref, "to": parent, "relation": "part_of"})
            else:
                warnings.append("parent_subject_unresolved")
        if _text(observation.get("observation_type")) in {"labelled_measurement", "count"}:
            edges.append({"from": subject_ref, "to": _text(observation.get("observation_uid")), "relation": "measured_as"})
    return {"nodes": list(nodes.values()), "edges": edges, "warnings": sorted(set(warnings)), "shadow_only": True,
            "used_for_final_reply": False, "can_change_can_send": False}


def select_bound_observations(
    observations: list[dict[str, Any]], *, requested_subject_scope: str, requested_measurement_axis: str,
) -> list[dict[str, Any]]:
    """Select only exact structured scope and axis matches; never parse buyer text."""
    if requested_subject_scope not in SUBJECT_SCOPES or requested_measurement_axis not in MEASUREMENT_AXES:
        return []
    return [
        item for item in observations
        if _text(item.get("subject_scope")) == requested_subject_scope
        and _text(item.get("measurement_axis")) == requested_measurement_axis
        and _text(item.get("observation_type")) in {"labelled_measurement", "count"}
    ]
