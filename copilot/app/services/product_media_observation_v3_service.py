"""Shadow-only product-media observations with staged object grounding.

This module records what a local VLM observed in a product image.  It is not a
formal evidence source and cannot affect customer replies or delivery.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from app.services.product_media_observation_service import (
    _asset_identity,
    _asset_value,
    _high_risk_attribute,
    _media_content_hash,
    identity_scope_issue,
    media_asset_eligibility,
    resolve_product_media_image_details,
)
from app.services.product_media_panel_proposal_service import (
    bbox_containment_ratio,
    panel_geometry_diagnostics,
    panel_proposal_alignment,
    propose_panel_layout,
)


V3_SCHEMA_VERSION = "product_media_observation_v3"
STAGES = ("image_classification", "object_localization", "label_localization", "measurement_binding")
PANEL_BBOX_REPAIR_STAGE = "panel_bbox_repair"
SUBJECT_SCOPES = {"product", "packaging", "component", "accessory", "included_item", "display_prop"}
IMAGE_PRIMARY_TYPES = {"single_panel", "multi_panel", "packaging_only", "product_only", "mixed_packaging_product"}
_LEGACY_SINGLE_PANEL_TYPES = SUBJECT_SCOPES
MEASUREMENT_AXES = {"length", "width", "height", "depth", "thickness", "diameter", "capacity", "count", "unknown"}
OBSERVATION_TYPES = {"labelled_measurement", "count", "visible_structure", "visible_text"}
_BBOX_KEYS = {"x", "y", "width", "height"}
_PACKAGING_LABEL_CUES = ("包装", "纸箱", "外箱", "包裹", "package", "packaging", "carton", "shipping box")
_COMPONENT_LABEL_CUES = ("部件", "零件", "component", "part")


def _text(value: Any) -> str:
    return str(value or "").strip()


def v3_model_prompt(*, max_observations: int, stage: str = "measurement_binding", context: dict[str, Any] | None = None) -> str:
    """Return the strict JSON instruction for one grounding stage.

    Coordinates may be normalised (0..1), normalised_1000 (0..1000), or pixel
    coordinates when ``coordinate_space`` is ``pixel``.  The validator turns
    every accepted box into 0..1 before it becomes a shadow observation.
    """
    if stage not in {*STAGES, PANEL_BBOX_REPAIR_STAGE}:
        raise ValueError("v3_stage_not_allowed")
    shared = (
        f"Return one JSON object only. schema_version must be {V3_SCHEMA_VERSION}; stage must be {stage}. "
        "Never infer load, safety, toxicity, certification, child suitability, wall fixing, drilling, or installation instructions. "
        "Use only what is visible in this image. Every bbox uses x,y as its top-left corner, with width,height extending right and down; never use center coordinates. "
    )
    prior = json.dumps(context or {}, ensure_ascii=False, separators=(",", ":"))
    if stage == "image_classification":
        return shared + (
            "Return image_primary_type as one of single_panel, multi_panel, packaging_only, product_only, mixed_packaging_product. "
            "Return panels as a list. Each panel needs panel_ref, panel_title, panel_bbox, state_or_mode. "
            "For a single-panel image panels must be exactly []. A continuous specification sheet or product canvas remains single_panel even when it shows multiple parts, measurements, or text blocks. "
            "Only use a non-empty panels list when image_primary_type is multi_panel and the image has distinct framed or gutter-separated sub-canvases; "
            "then every panel_bbox is mandatory and uses x,y,width,height plus coordinate_space. "
            "If Panel Proposal Context has status ready, keep each panel aligned to those proposals: accept, make only a small adjustment, "
            "merge proposals only when they clearly form one panel, or reject the proposal. Do not return unrelated near-full-image boxes. "
            f"Panel Proposal Context: {prior}"
        )
    if stage == PANEL_BBOX_REPAIR_STAGE:
        return shared + (
            "Return panels only. Preserve every existing panel_ref and provide only panel_ref and panel_bbox. "
            "Do not add objects, labels, measurements, facts, or text extraction. Every panel_bbox is mandatory and uses "
            "x,y,width,height plus coordinate_space. Keep repaired boxes aligned to any supplied panel proposals; do not return full-image duplicates. Previous stage context: "
            f"{prior}"
        )
    if stage == "object_localization":
        return shared + (
            "Return subjects as a list of visible objects. Each subject needs subject_ref, subject_scope, subject_label, "
            "parent_subject_ref, state_or_mode, panel_ref, object_bbox, confidence. subject_scope must be product, packaging, "
            "component, accessory, included_item, or display_prop. Use product only for the complete sellable item. A box, carton, package, "
            "or shipping container must be packaging; a named part must be component or accessory. object_bbox is required and uses x,y,width,height plus coordinate_space. "
            f"Previous stage context: {prior}"
        )
    if stage == "label_localization":
        return shared + (
            "Return labels as a list of visible dimension labels, arrows, or callout lines. Each label needs label_ref, label_bbox, "
            "panel_ref, evidence_text, confidence. label_bbox is required and uses x,y,width,height plus coordinate_space. OCR text is reference only. "
            f"Maximum labels: {max_observations}. Previous stage context: {prior}"
        )
    return shared + (
        "Return observations as a list which binds one subject_ref to one label_ref. Each observation needs subject_ref, label_ref, "
        "observation_type, attribute_key, measurement_axis, raw_observation, value, unit, evidence_text, confidence. "
        "observation_type is labelled_measurement, count, visible_structure, or visible_text. A labelled_measurement needs value and unit. "
        "measurement_axis is length, width, height, depth, thickness, diameter, capacity, count, or unknown. Use unknown when the axis is unclear. "
        "Do not bind an unlocated number to an object. "
        f"Maximum observations: {max_observations}. Previous stage context: {prior}"
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


def _normalised_bbox(value: Any, *, image_size: tuple[int, int] | None = None) -> dict[str, float] | None:
    if isinstance(value, list) and len(value) == 4:
        value = {"x": value[0], "y": value[1], "width": value[2] - value[0], "height": value[3] - value[1], "coordinate_space": "normalized_1000"}
    if not isinstance(value, dict) or not _BBOX_KEYS.issubset(value):
        return None
    try:
        coords = {key: float(value[key]) for key in _BBOX_KEYS}
    except (TypeError, ValueError):
        return None
    coordinate_space = _text(value.get("coordinate_space")).lower()
    maximum = max(coords.values())
    if coordinate_space in {"", "normalized"} and maximum <= 1:
        divisor = 1.0
    elif coordinate_space in {"", "normalized_1000", "0_1000"} and maximum <= 1000:
        divisor = 1000.0
    elif coordinate_space in {"pixel", "image"} and image_size and image_size[0] > 0 and image_size[1] > 0:
        if coords["x"] + coords["width"] <= image_size[0] and coords["y"] + coords["height"] <= image_size[1]:
            return {
                "x": coords["x"] / image_size[0], "y": coords["y"] / image_size[1],
                "width": coords["width"] / image_size[0], "height": coords["height"] / image_size[1],
                "coordinate_space": "normalized",
            }
        # Some OpenAI-compatible vision providers emit 0..1000 coordinates but
        # label them as image pixels. Only reinterpret a declared pixel box when
        # it is otherwise impossible for the supplied image dimensions.
        if maximum <= 1000:
            divisor = 1000.0
        else:
            return None
    else:
        return None
    normalised = {key: coords[key] / divisor for key in _BBOX_KEYS}
    if normalised["width"] <= 0 or normalised["height"] <= 0:
        return None
    if any(number < 0 or number > 1 for number in normalised.values()):
        return None
    if normalised["x"] + normalised["width"] > 1 or normalised["y"] + normalised["height"] > 1:
        return None
    normalised["coordinate_space"] = "normalized"
    return normalised


def _bbox_area(bbox: dict[str, float]) -> float:
    return bbox["width"] * bbox["height"]


def _valid_panel_bbox(bbox: dict[str, float] | None) -> bool:
    return bool(bbox and 0.01 <= _bbox_area(bbox) < 0.99)


def _uid(*parts: str) -> str:
    return "pmov3_" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _scope_label_conflict(scope: str, label: str) -> str:
    normalized = label.lower()
    if scope == "product" and any(cue in normalized for cue in _PACKAGING_LABEL_CUES):
        return "packaging_scope_required"
    if scope == "product" and any(cue in normalized for cue in _COMPONENT_LABEL_CUES):
        return "component_scope_required"
    return ""


@dataclass(frozen=True)
class ProductMediaObservationV3:
    observation_uid: str
    media_asset_id: int
    product_identity: dict[str, str]
    subject_scope: str
    subject_ref: str
    subject_label: str
    panel_ref: str
    panel_bbox: dict[str, float] | None
    panel_title: str
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
            "review_status": "pending_review", "direct_answer_allowed": False,
            "used_for_generation": False, "can_change_can_send": False,
        })
        return data


class ProductMediaObservationV3Extractor:
    """Runs staged grounding and validates only bound, low-risk observations."""

    def __init__(self, stage_runner: Callable[[str, Any, bytes, str, int, dict[str, Any]], dict[str, Any]]):
        self._stage_runner = stage_runner

    def extract_asset(
        self, asset: Any, *, expected_product_identity: dict[str, Any] | None = None, timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        result = {"media_asset_id": asset_id, "observations": [], "rejected_evidence": [], "warnings": [], "stage_diagnostics": []}
        reasons = media_asset_eligibility(asset)
        scope_issue = identity_scope_issue(_asset_identity(asset), expected_product_identity)
        if scope_issue:
            reasons.append(scope_issue)
        if reasons:
            result["rejected_evidence"].append({"media_asset_id": asset_id, "reason": reasons[0]})
            result["warnings"].extend(reasons)
            return result
        image = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
        result["media_resolution"] = {
            key: value for key, value in image.items() if key not in {"data"}
        }
        if not image.get("ok"):
            result["rejected_evidence"].append({"media_asset_id": asset_id, "reason": "image_read_failed", "detail": image.get("reason", "image_read_failed")})
            return result
        parsed, diagnostics, failure_reason = self._run_stages(asset, image["data"], image["extension"], timeout_seconds)
        result["stage_diagnostics"] = diagnostics
        if parsed is None:
            result["rejected_evidence"].append({"media_asset_id": asset_id, "reason": failure_reason or "schema_validation_failed"})
            return result
        result.update(self._parse(asset, parsed, image["observed_media_sha256"]))
        result["stage_diagnostics"] = diagnostics
        return result

    def _run_stages(self, asset: Any, image: bytes, extension: str, timeout_seconds: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
        panel_proposal = propose_panel_layout(image)
        context: dict[str, Any] = {"panel_proposal": panel_proposal}
        diagnostics: list[dict[str, Any]] = []
        diagnostics.append({
            "stage": "panel_proposal", "execution_status": "success",
            "schema_status": "valid" if panel_proposal.get("status") == "ready" else "skipped",
            "proposal_status": panel_proposal.get("status"), "reason": panel_proposal.get("reason", ""),
            "result_count": len(panel_proposal.get("panels") or []),
            "geometric_diagnostics": panel_proposal.get("geometric_diagnostics", {}),
        })
        try:
            with Image.open(io.BytesIO(image)) as source:
                image_size: tuple[int, int] | None = source.size
        except (UnidentifiedImageError, OSError):
            image_size = None
        for stage in STAGES:
            try:
                raw = self._stage_runner(stage, asset, image, extension, timeout_seconds, context)
            except Exception as exc:  # external VLM boundary: record without exposing prompt/image output
                diagnostics.append({"stage": stage, "execution_status": "error", "error_type": type(exc).__name__})
                return None, diagnostics, "provider_error"
            valid, compact, detail = self._validate_stage(stage, raw, image_size=image_size, panel_proposal=panel_proposal)
            diagnostics.append(detail)
            if not valid:
                return None, diagnostics, detail.get("reason", "schema_validation_failed")
            if stage == "image_classification" and compact.pop("needs_panel_repair", False):
                try:
                    repair_raw = self._stage_runner(PANEL_BBOX_REPAIR_STAGE, asset, image, extension, timeout_seconds, compact)
                except Exception as exc:
                    diagnostics.append({"stage": PANEL_BBOX_REPAIR_STAGE, "execution_status": "error", "error_type": type(exc).__name__})
                    return None, diagnostics, "provider_error"
                repaired, repaired_compact, repair_detail = self._validate_panel_repair(
                    repair_raw, image_size=image_size, expected_panels=compact["panels"], panel_proposal=panel_proposal,
                )
                diagnostics.append(repair_detail)
                if not repaired:
                    return None, diagnostics, repair_detail.get("reason", "panel_bbox_missing")
                compact["panels"] = repaired_compact["panels"]
            context[stage] = compact
            if stage in {"object_localization", "label_localization"}:
                collection = "subjects" if stage == "object_localization" else "labels"
                panels_by_ref = {item["panel_ref"]: item for item in context["image_classification"]["panels"]}
                for item in compact[collection]:
                    if not item.get("panel_ref") and len(panels_by_ref) == 1:
                        item["panel_ref"] = next(iter(panels_by_ref))
                    if item.get("panel_ref") not in panels_by_ref:
                        diagnostics.append({"stage": stage, "execution_status": "success", "schema_status": "invalid", "reason": "panel_ref_missing"})
                        return None, diagnostics, "schema_validation_failed"
                    panel = panels_by_ref[item["panel_ref"]]
                    box_key = "object_bbox" if stage == "object_localization" else "label_bbox"
                    if bbox_containment_ratio(item[box_key], panel["panel_bbox"]) < 0.80:
                        diagnostics.append({"stage": stage, "execution_status": "success", "schema_status": "invalid", "reason": "schema_validation_failed", "detail": f"{box_key}_outside_panel"})
                        return None, diagnostics, "schema_validation_failed"
                    if stage == "object_localization":
                        if panel["state_or_mode"] and not item["state_or_mode"]:
                            item["state_or_mode"] = panel["state_or_mode"]
        subjects = {item["subject_ref"]: item for item in context["object_localization"]["subjects"]}
        labels = {item["label_ref"]: item for item in context["label_localization"]["labels"]}
        observations: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        panels_by_ref = {item["panel_ref"]: item for item in context["image_classification"]["panels"]}
        for item in context["measurement_binding"]["observations"]:
            subject = subjects.get(_text(item.get("subject_ref")))
            label = labels.get(_text(item.get("label_ref")))
            if subject is None or label is None:
                rejected.append({"reason": "schema_validation_failed", "subject_ref": _text(item.get("subject_ref")), "label_ref": _text(item.get("label_ref"))})
                continue
            if subject["panel_ref"] != label["panel_ref"]:
                rejected.append({"reason": "cross_panel_binding_rejected", "subject_ref": subject["subject_ref"], "label_ref": label["label_ref"]})
                continue
            panel = panels_by_ref[subject["panel_ref"]]
            observations.append({
                "subject_scope": subject["subject_scope"], "subject_ref": subject["subject_ref"],
                "subject_label": subject["subject_label"], "state_or_mode": subject["state_or_mode"],
                "parent_subject_ref": subject["parent_subject_ref"], "panel_ref": subject.get("panel_ref", ""),
                "observation_type": item["observation_type"], "attribute_key": item["attribute_key"],
                "measurement_axis": item["measurement_axis"], "raw_observation": item["raw_observation"],
                "value": item["value"], "unit": item["unit"], "evidence_text": label["evidence_text"],
                "object_bbox": subject["object_bbox"], "label_bbox": label["label_bbox"],
                "panel_bbox": panel["panel_bbox"], "panel_title": panel["panel_title"],
                "confidence": min(subject["confidence"], label["confidence"], item["confidence"]),
            })
        return {"schema_version": V3_SCHEMA_VERSION, "model_version": "staged", "observations": observations, "stage_rejected_evidence": rejected}, diagnostics, ""

    def _validate_stage(
        self, stage: str, raw: Any, *, image_size: tuple[int, int] | None, panel_proposal: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        base = {"stage": stage, "execution_status": "success", "schema_status": "invalid"}
        if not isinstance(raw, dict) or raw.get("schema_version") != V3_SCHEMA_VERSION or raw.get("stage") != stage:
            return False, {}, {**base, "field_presence": {"schema_version": bool(isinstance(raw, dict) and raw.get("schema_version")), "stage": bool(isinstance(raw, dict) and raw.get("stage"))}}
        if stage == "image_classification":
            panels = raw.get("panels", [])
            image_primary_type = _text(raw.get("image_primary_type")).lower()
            if image_primary_type in _LEGACY_SINGLE_PANEL_TYPES:
                image_primary_type = "single_panel"
            if image_primary_type not in IMAGE_PRIMARY_TYPES or not isinstance(panels, list):
                return False, {}, {**base, "reason": "schema_validation_failed"}
            if image_primary_type != "multi_panel":
                return True, {"image_primary_type": image_primary_type, "panels": [{"panel_ref": "root", "panel_title": "", "panel_bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "coordinate_space": "normalized"}, "state_or_mode": "", "synthetic_root": True}]}, {
                    **base, "schema_status": "valid", "result_count": 1, "warnings": ["synthetic_root_panel"],
                }
            candidate_panels = []
            repair_required = False
            for item in panels:
                if not isinstance(item, dict) or not _text(item.get("panel_ref")):
                    return False, {}, {**base, "reason": "schema_validation_failed"}
                bbox = _normalised_bbox(item.get("panel_bbox"), image_size=image_size)
                title = _text(item.get("panel_title") or item.get("visible_heading"))
                if not title:
                    return False, {}, {**base, "reason": "schema_validation_failed", "field_presence": {"panel_title": False}}
                if not _valid_panel_bbox(bbox):
                    repair_required = True
                candidate_panels.append({"panel_ref": _text(item["panel_ref"]), "panel_title": title, "panel_bbox": bbox, "state_or_mode": _text(item.get("state_or_mode")) or title})
            if not candidate_panels:
                return False, {}, {**base, "reason": "panel_bbox_missing"}
            geometry = panel_geometry_diagnostics(candidate_panels, layout_axis=panel_proposal.get("layout_axis", "unknown")) if not repair_required else {}
            if repair_required or not geometry.get("valid"):
                return True, {"image_primary_type": image_primary_type, "panels": candidate_panels, "needs_panel_repair": True}, {
                    **base, "schema_status": "valid", "result_count": len(candidate_panels),
                    "warnings": ["panel_bbox_repair_required"], "geometric_diagnostics": geometry,
                }
            alignment = panel_proposal_alignment(candidate_panels, panel_proposal)
            if not alignment["accepted"]:
                return False, {}, {**base, "reason": alignment["reason"], "geometric_diagnostics": geometry, "proposal_alignment": alignment}
            for item, match in zip(candidate_panels, alignment["matches"]):
                item["proposal_ids"] = match["proposal_ids"]
            return True, {"image_primary_type": image_primary_type, "panels": candidate_panels}, {
                **base, "schema_status": "valid", "result_count": len(candidate_panels),
                "geometric_diagnostics": geometry, "proposal_alignment": alignment,
            }
        collection = "subjects" if stage == "object_localization" else "labels" if stage == "label_localization" else "observations"
        rows = raw.get(collection)
        if not isinstance(rows, list):
            return False, {}, base
        clean: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                return False, {}, base
            if stage == "object_localization":
                scope = _text(item.get("subject_scope")).lower()
                bbox = _normalised_bbox(item.get("object_bbox"), image_size=image_size)
                if scope not in SUBJECT_SCOPES or not _text(item.get("subject_ref")) or not _text(item.get("subject_label")) or bbox is None:
                    return False, {}, {**base, "reason": "object_bbox_missing", "field_presence": {"object_bbox": bbox is not None}, "returned_fields": sorted(item.keys()), "bbox_shape": _bbox_shape(item.get("object_bbox"))}
                clean.append({"subject_ref": _text(item["subject_ref"]), "subject_scope": scope, "subject_label": _text(item["subject_label"]), "parent_subject_ref": _text(item.get("parent_subject_ref")), "state_or_mode": _text(item.get("state_or_mode")), "panel_ref": _text(item.get("panel_ref")), "object_bbox": bbox, "confidence": _confidence(item.get("confidence"))})
            elif stage == "label_localization":
                bbox = _normalised_bbox(item.get("label_bbox"), image_size=image_size)
                if not _text(item.get("label_ref")) or bbox is None or not _text(item.get("evidence_text")):
                    return False, {}, {**base, "reason": "label_bbox_missing", "field_presence": {"label_bbox": bbox is not None}, "returned_fields": sorted(item.keys()), "bbox_shape": _bbox_shape(item.get("label_bbox"))}
                clean.append({"label_ref": _text(item["label_ref"]), "panel_ref": _text(item.get("panel_ref")), "label_bbox": bbox, "evidence_text": _text(item["evidence_text"]), "confidence": _confidence(item.get("confidence"))})
            else:
                axis = _text(item.get("measurement_axis")).lower()
                observation_type = _text(item.get("observation_type")).lower()
                if not _text(item.get("subject_ref")) or not _text(item.get("label_ref")) or observation_type not in OBSERVATION_TYPES:
                    return False, {}, base
                clean.append({"subject_ref": _text(item["subject_ref"]), "label_ref": _text(item["label_ref"]), "observation_type": observation_type, "attribute_key": _text(item.get("attribute_key")).lower(), "measurement_axis": axis, "raw_observation": _text(item.get("raw_observation")), "value": _text(item.get("value")), "unit": _text(item.get("unit")), "confidence": _confidence(item.get("confidence"))})
        return True, {collection: clean}, {**base, "schema_status": "valid", "result_count": len(clean)}

    def _validate_panel_repair(
        self, raw: Any, *, image_size: tuple[int, int] | None, expected_panels: list[dict[str, Any]], panel_proposal: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        base = {"stage": PANEL_BBOX_REPAIR_STAGE, "execution_status": "success", "schema_status": "invalid"}
        if not isinstance(raw, dict) or raw.get("schema_version") != V3_SCHEMA_VERSION or raw.get("stage") != PANEL_BBOX_REPAIR_STAGE:
            return False, {}, {**base, "reason": "schema_validation_failed"}
        rows = raw.get("panels")
        if not isinstance(rows, list):
            return False, {}, {**base, "reason": "panel_bbox_missing"}
        expected_by_ref = {item["panel_ref"]: item for item in expected_panels}
        repaired_by_ref: dict[str, dict[str, Any]] = {}
        for item in rows:
            if not isinstance(item, dict):
                return False, {}, {**base, "reason": "schema_validation_failed"}
            panel_ref = _text(item.get("panel_ref"))
            bbox = _normalised_bbox(item.get("panel_bbox"), image_size=image_size)
            if not panel_ref or panel_ref not in expected_by_ref:
                return False, {}, {**base, "reason": "schema_validation_failed"}
            if bbox is None:
                return False, {}, {**base, "reason": "panel_bbox_missing"}
            if not _valid_panel_bbox(bbox):
                return False, {}, {**base, "reason": "invalid_panel_bbox"}
            repaired_by_ref[panel_ref] = {**expected_by_ref[panel_ref], "panel_bbox": bbox}
        if set(repaired_by_ref) != set(expected_by_ref):
            return False, {}, {**base, "reason": "panel_bbox_missing"}
        repaired = [repaired_by_ref[item["panel_ref"]] for item in expected_panels]
        geometry = panel_geometry_diagnostics(repaired, layout_axis=panel_proposal.get("layout_axis", "unknown"))
        alignment = panel_proposal_alignment(repaired, panel_proposal)
        if not geometry["valid"]:
            return False, {}, {**base, "reason": "invalid_panel_bbox", "geometric_diagnostics": geometry, "proposal_alignment": alignment}
        if not alignment["accepted"]:
            return False, {}, {**base, "reason": alignment["reason"], "geometric_diagnostics": geometry, "proposal_alignment": alignment}
        for item, match in zip(repaired, alignment["matches"]):
            item["proposal_ids"] = match["proposal_ids"]
        return True, {"panels": repaired}, {**base, "schema_status": "valid", "result_count": len(repaired), "geometric_diagnostics": geometry, "proposal_alignment": alignment}

    def _parse(self, asset: Any, raw: Any, observed_media_sha256: str) -> dict[str, Any]:
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        accepted: list[ProductMediaObservationV3] = []
        rejected: list[dict[str, Any]] = []
        warnings: list[str] = []
        rejected.extend(raw.get("stage_rejected_evidence", []))
        for index, item in enumerate(raw["observations"]):
            observation, reason = self._validate(asset, item, observed_media_sha256, _text(raw.get("model_version")))
            if observation is None:
                rejected.append({"media_asset_id": asset_id, "observation_index": index, "reason": reason})
            else:
                accepted.append(observation)
                warnings.extend(observation.warning_reasons)
        accepted.sort(key=lambda item: item.observation_uid)
        return {"observations": [item.to_dict() for item in accepted], "rejected_evidence": rejected, "warnings": sorted(set(warnings))}

    def _validate(self, asset: Any, item: dict[str, Any], observed_media_sha256: str, model_version: str) -> tuple[ProductMediaObservationV3 | None, str]:
        scope = _text(item.get("subject_scope")).lower()
        subject_ref, subject_label = _text(item.get("subject_ref")), _text(item.get("subject_label"))
        panel_ref = _text(item.get("panel_ref"))
        panel_bbox = _normalised_bbox(item.get("panel_bbox"))
        panel_title = _text(item.get("panel_title"))
        state_or_mode, parent_ref = _text(item.get("state_or_mode")), _text(item.get("parent_subject_ref"))
        observation_type = _text(item.get("observation_type")).lower()
        attribute_key, axis = _text(item.get("attribute_key")).lower(), _text(item.get("measurement_axis")).lower()
        raw_observation, value, unit = _text(item.get("raw_observation")), _text(item.get("value")), _text(item.get("unit"))
        evidence_text = _text(item.get("evidence_text"))
        object_bbox, label_bbox = _normalised_bbox(item.get("object_bbox")), _normalised_bbox(item.get("label_bbox"))
        if scope not in SUBJECT_SCOPES or not subject_ref or not subject_label or not panel_ref or panel_bbox is None or not raw_observation:
            return None, "subject_binding_missing"
        scope_conflict = _scope_label_conflict(scope, subject_label)
        if scope_conflict:
            return None, scope_conflict
        if parent_ref == subject_ref:
            return None, "subject_parent_self_reference"
        if observation_type not in OBSERVATION_TYPES or _high_risk_attribute(subject_label, state_or_mode, attribute_key, raw_observation, evidence_text):
            return None, "out_of_scope_high_risk" if _high_risk_attribute(subject_label, state_or_mode, attribute_key, raw_observation, evidence_text) else "observation_type_not_allowed"
        if observation_type == "visible_text":
            return None, "visible_text_reference_only"
        if object_bbox is None:
            return None, "object_bbox_required"
        if observation_type == "labelled_measurement":
            if axis == "unknown":
                return None, "ambiguous_axis"
            if axis not in MEASUREMENT_AXES - {"count", "unknown"} or not value or not unit or label_bbox is None:
                return None, "measurement_target_binding_missing"
        elif observation_type == "count":
            if axis != "count" or not value:
                return None, "count_binding_invalid"
        elif axis:
            return None, "measurement_axis_not_allowed"
        confidence = _confidence(item.get("confidence"))
        if confidence < 0.75:
            return None, "low_confidence"
        identity = _asset_identity(asset)
        asset_id = int(_asset_value(asset, "id") or _asset_value(asset, "asset_id") or 0)
        warnings = [f"{scope}_measurement_not_product_dimension"] if observation_type == "labelled_measurement" and scope != "product" else []
        provenance = {"schema_version": V3_SCHEMA_VERSION, "model_version": model_version, "media_asset_id": asset_id, "observed_media_sha256": observed_media_sha256, "asset_content_hash": _media_content_hash(asset), "identity_scope": [{"namespace": key, "value": value} for key, value in identity.items() if value]}
        return ProductMediaObservationV3(
            observation_uid=_uid(observed_media_sha256, scope, subject_ref, state_or_mode, observation_type, attribute_key, axis, value, unit), media_asset_id=asset_id, product_identity=identity,
            subject_scope=scope, subject_ref=subject_ref, subject_label=subject_label, panel_ref=panel_ref, panel_bbox=panel_bbox, panel_title=panel_title, state_or_mode=state_or_mode, parent_subject_ref=parent_ref,
            observation_type=observation_type, attribute_key=attribute_key, measurement_axis=axis, raw_observation=raw_observation, value=value, unit=unit, evidence_text=evidence_text,
            object_bbox=object_bbox, label_bbox=label_bbox, confidence=confidence, provenance=provenance, warning_reasons=warnings,
        ), ""


def _confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if 0.0 <= parsed <= 1.0 else 0.0


def _bbox_shape(value: Any) -> dict[str, Any]:
    """Sanitised diagnostic metadata; intentionally never retains model text."""
    if isinstance(value, dict):
        numeric_values = []
        for key in _BBOX_KEYS:
            try:
                numeric_values.append(float(value[key]))
            except (KeyError, TypeError, ValueError):
                pass
        return {
            "kind": "object", "keys": sorted(str(key) for key in value),
            "coordinate_space": _text(value.get("coordinate_space")),
            "numeric_min": min(numeric_values) if numeric_values else None,
            "numeric_max": max(numeric_values) if numeric_values else None,
        }
    if isinstance(value, list):
        return {"kind": "array", "length": len(value)}
    return {"kind": type(value).__name__}


def build_product_understanding_graph(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a read-only graph from validated v3 observations in two passes."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    warnings: list[str] = []
    ordered = sorted(observations, key=lambda item: _text(item.get("observation_uid")))
    for item in ordered:
        ref = _text(item.get("subject_ref"))
        if ref:
            nodes.setdefault(ref, {"subject_ref": ref, "subject_scope": _text(item.get("subject_scope")), "subject_label": _text(item.get("subject_label")), "state_or_mode": _text(item.get("state_or_mode"))})
        if _text(item.get("panel_ref")):
            nodes.setdefault(f"panel:{item['panel_ref']}", {
                "subject_ref": f"panel:{item['panel_ref']}", "subject_scope": "panel",
                "subject_label": _text(item.get("panel_title")) or _text(item["panel_ref"]),
                "state_or_mode": _text(item.get("state_or_mode")), "panel_bbox": item.get("panel_bbox"),
            })
        if _text(item.get("state_or_mode")):
            nodes.setdefault(f"mode:{item['subject_ref']}:{item['state_or_mode']}", {"subject_ref": f"mode:{item['subject_ref']}:{item['state_or_mode']}", "subject_scope": "mode", "subject_label": _text(item["state_or_mode"]), "state_or_mode": _text(item["state_or_mode"])})
    for item in ordered:
        ref, parent, uid = _text(item.get("subject_ref")), _text(item.get("parent_subject_ref")), _text(item.get("observation_uid"))
        if parent:
            if parent in nodes:
                edges.append({"from": ref, "to": parent, "relation": "part_of"})
            else:
                warnings.append("parent_subject_unresolved")
        if _text(item.get("panel_ref")):
            edges.append({"from": ref, "to": f"panel:{item['panel_ref']}", "relation": "visible_in"})
        if _text(item.get("state_or_mode")):
            edges.append({"from": ref, "to": f"mode:{ref}:{item['state_or_mode']}", "relation": "active_in_mode"})
        if _text(item.get("observation_type")) in {"labelled_measurement", "count"}:
            measurement_ref = f"measurement:{uid}"
            label_ref = f"label:{uid}"
            nodes[measurement_ref] = {"subject_ref": measurement_ref, "subject_scope": "measurement", "subject_label": _text(item.get("raw_observation")), "state_or_mode": ""}
            nodes[label_ref] = {"subject_ref": label_ref, "subject_scope": "label", "subject_label": _text(item.get("evidence_text")), "state_or_mode": ""}
            edges.extend(({"from": ref, "to": measurement_ref, "relation": "measured_as"}, {"from": ref, "to": label_ref, "relation": "labelled_by"}))
    return {"nodes": list(nodes.values()), "edges": edges, "warnings": sorted(set(warnings)), "shadow_only": True, "used_for_final_reply": False, "can_change_can_send": False}


def select_bound_observations(observations: list[dict[str, Any]], *, requested_subject_scope: str, requested_measurement_axis: str) -> list[dict[str, Any]]:
    """Select exact structured scope and axis matches; never parse buyer text."""
    if requested_subject_scope not in SUBJECT_SCOPES or requested_measurement_axis not in MEASUREMENT_AXES:
        return []
    return [item for item in observations if _text(item.get("subject_scope")) == requested_subject_scope and _text(item.get("measurement_axis")) == requested_measurement_axis and _text(item.get("observation_type")) in {"labelled_measurement", "count"}]
