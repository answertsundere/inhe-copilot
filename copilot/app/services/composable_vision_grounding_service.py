"""Composable, shadow-only OCR/object/geometry/verifier grounding PoC.

Each provider supplies only its own bounded output.  Geometry can propose a
relation but never upgrades it to a product fact; a verifier may accept or
reject that exact proposal, but cannot introduce or alter any bounding box.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from app.services.product_media_observation_service import _high_risk_attribute
from app.services.product_media_observation_v3_service import _normalised_bbox


_SCOPES = {"product", "packaging", "component", "accessory", "included_item", "display_prop"}
_MEASUREMENT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|毫米|厘米|米)", re.IGNORECASE)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _center(box: dict[str, float]) -> tuple[float, float]:
    return float(box["x"]) + float(box["width"]) / 2, float(box["y"]) + float(box["height"]) / 2


def _distance(left: dict[str, float], right: dict[str, float]) -> float:
    left_center, right_center = _center(left), _center(right)
    return ((left_center[0] - right_center[0]) ** 2 + (left_center[1] - right_center[1]) ** 2) ** 0.5


def _panel_for(box: dict[str, Any], panels: list[dict[str, Any]]) -> str:
    center_x, center_y = _center(box)
    matches = [item for item in panels if item.get("panel_bbox") and float(item["panel_bbox"]["x"]) <= center_x <= float(item["panel_bbox"]["x"]) + float(item["panel_bbox"]["width"]) and float(item["panel_bbox"]["y"]) <= center_y <= float(item["panel_bbox"]["y"]) + float(item["panel_bbox"]["height"])]
    return _text(matches[0].get("panel_ref")) if len(matches) == 1 else ""


def normalize_ocr_items(items: list[dict[str, Any]], *, image_size: tuple[int, int] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        bbox = _normalised_bbox(item.get("bbox"), image_size=image_size)
        text = _text(item.get("text"))
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        if bbox is not None and text and 0.0 <= confidence <= 1.0:
            result.append({"label_id": _text(item.get("label_id")) or f"ocr_{index + 1}", "text": text, "bbox": bbox, "confidence": confidence, "source": _text(item.get("source")) or "ocr"})
    return result


def normalize_object_items(items: list[dict[str, Any]], *, image_size: tuple[int, int] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        bbox = _normalised_bbox(item.get("bbox"), image_size=image_size)
        scope = _text(item.get("subject_scope")).lower()
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        if bbox is not None and scope in _SCOPES and 0.0 <= confidence <= 1.0:
            result.append({"object_id": _text(item.get("object_id")) or f"object_{index + 1}", "object_type": _text(item.get("object_type")) or scope, "subject_scope": scope, "bbox": bbox, "confidence": confidence, "source": _text(item.get("source")) or "object_provider", "mode_or_state": _text(item.get("mode_or_state"))})
    return result


def build_geometry_candidates(*, ocr_items: list[dict[str, Any]], object_items: list[dict[str, Any]], panels: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Bind only an unambiguous same-panel OCR measurement to one object."""
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for label in ocr_items:
        risk = _high_risk_attribute(label["text"])
        if risk:
            rejected.append({"label_id": label["label_id"], "reason": "out_of_scope_high_risk"})
            continue
        parsed = _MEASUREMENT.search(label["text"])
        if not parsed:
            continue
        label_panel = _panel_for(label["bbox"], panels)
        if not label_panel and len(panels) > 1:
            rejected.append({"label_id": label["label_id"], "reason": "label_panel_ambiguous"})
            continue
        options = []
        for subject in object_items:
            subject_panel = _panel_for(subject["bbox"], panels)
            if label_panel and subject_panel != label_panel:
                continue
            distance = _distance(label["bbox"], subject["bbox"])
            if distance <= 0.35:
                options.append((distance, subject, subject_panel or label_panel))
        options.sort(key=lambda row: (row[0], row[1]["object_id"]))
        if not options:
            rejected.append({"label_id": label["label_id"], "reason": "no_same_panel_object_candidate"})
            continue
        if len(options) > 1 and options[1][0] - options[0][0] < 0.03:
            rejected.append({"label_id": label["label_id"], "reason": "object_binding_ambiguous"})
            continue
        distance, subject, panel_ref = options[0]
        candidate_id = hashlib.sha256(f"{label['label_id']}|{subject['object_id']}|{parsed.group('value')}|{parsed.group('unit')}".encode("utf-8")).hexdigest()[:24]
        candidates.append({
            "candidate_id": candidate_id, "relation": "labelled_by", "measurement_relation": "measured_as",
            "label": label, "object": subject, "panel_ref": panel_ref,
            "value": parsed.group("value"), "unit": parsed.group("unit"), "normalized_value": parsed.group("value"),
            "mode_or_state": subject["mode_or_state"], "geometry_distance": distance,
            "provenance": {"ocr_source": label["source"], "object_source": subject["source"], "binding_source": "same_panel_nearest_geometry", "verifier_source": ""},
        })
    return {"candidates": candidates, "rejected": rejected}


def verify_candidates(candidates: list[dict[str, Any]], verifier: Callable[[dict[str, Any]], dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if verifier is None:
        return {"observations": observations, "rejected": rejected, "diagnostics": [{"stage": "verifier", "reason": "verifier_not_configured"}]}
    for candidate in candidates:
        try:
            verdict = verifier(candidate)
        except Exception as exc:
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": "verifier_execution_error", "error_type": type(exc).__name__})
            continue
        if not isinstance(verdict, dict) or verdict.get("candidate_id") != candidate["candidate_id"] or not isinstance(verdict.get("accept"), bool):
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": "verifier_schema_error"})
            continue
        if any(key in verdict for key in ("bbox", "object_bbox", "label_bbox", "panel_bbox")):
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": "verifier_bbox_not_allowed"})
            continue
        if not verdict["accept"]:
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": _text(verdict.get("reason")) or "verifier_rejected"})
            continue
        attribute_key = _text(verdict.get("attribute_key")).lower()
        scope = candidate["object"]["subject_scope"]
        if scope == "component" and attribute_key in {"overall_dimension", "product_dimension"}:
            rejected.append({"candidate_id": candidate["candidate_id"], "reason": "component_overall_scope_rejected"})
            continue
        provenance = dict(candidate["provenance"])
        provenance["verifier_source"] = _text(verdict.get("source")) or "verifier"
        observations.append({
            "observation_uid": "composable_" + candidate["candidate_id"], "subject_scope": scope,
            "object_type": candidate["object"]["object_type"], "object_bbox": candidate["object"]["bbox"],
            "label_bbox": candidate["label"]["bbox"], "panel_ref": candidate["panel_ref"],
            "attribute_key": attribute_key, "value": candidate["value"], "unit": candidate["unit"],
            "normalized_value": candidate["normalized_value"], "mode_or_state": candidate["mode_or_state"],
            "relation": candidate["relation"], "confidence": min(candidate["label"]["confidence"], candidate["object"]["confidence"]),
            "provenance": provenance, "review_status": "pending_review", "direct_answer_allowed": False,
            "used_for_generation": False, "can_change_can_send": False,
            "warning_reasons": ["mode_specific_not_global"] if candidate["mode_or_state"] else [],
        })
    return {"observations": observations, "rejected": rejected, "diagnostics": []}
