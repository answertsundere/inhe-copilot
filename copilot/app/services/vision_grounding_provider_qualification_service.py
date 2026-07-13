"""Read-only qualification metrics for shadow visual-grounding providers.

The qualifier consumes already shadow-only staged observation results.  It does
not alter provider output, evidence admission, knowledge tables, or Agent
decisions.  Its job is to make provider failures and grounding quality
comparable before any provider is considered for a wider shadow evaluation.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import Counter
from typing import Any


_REQUIRED_BBOX_KEYS = {"x", "y", "width", "height"}
_HIGH_RISK_REJECTION = "out_of_scope_high_risk"


def _rate(numerator: int, denominator: int) -> dict[str, float | int]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_normalized_bbox(value: Any) -> bool:
    """Validate the common 0..1 top-left bbox contract without coercion."""
    if not isinstance(value, dict) or not _REQUIRED_BBOX_KEYS.issubset(value):
        return False
    try:
        x, y, width, height = (float(value[key]) for key in ("x", "y", "width", "height"))
    except (TypeError, ValueError):
        return False
    return (
        _text(value.get("coordinate_space")) == "normalized"
        and 0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1
        and x + width <= 1 and y + height <= 1
    )


def bbox_iou(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    if not is_normalized_bbox(left) or not is_normalized_bbox(right):
        return None
    left_x, left_y = float(left["x"]), float(left["y"])
    right_x, right_y = float(right["x"]), float(right["y"])
    overlap_width = max(0.0, min(left_x + float(left["width"]), right_x + float(right["width"])) - max(left_x, right_x))
    overlap_height = max(0.0, min(left_y + float(left["height"]), right_y + float(right["height"])) - max(left_y, right_y))
    overlap = overlap_width * overlap_height
    union = float(left["width"]) * float(left["height"]) + float(right["width"]) * float(right["height"]) - overlap
    return min(1.0, max(0.0, overlap / union)) if union else None


def normalize_stage_outcomes(
    *, provider_name: str, model_name: str, media_asset_id: int, image_sha256: str, stage_diagnostics: list[dict[str, Any]], latency_ms: float | None,
) -> list[dict[str, Any]]:
    """Project V3 diagnostics into a provider-neutral, sanitized stage schema."""
    request_seed = f"{provider_name}|{model_name}|{media_asset_id}|{image_sha256}"
    outcomes: list[dict[str, Any]] = []
    for index, diagnostic in enumerate(stage_diagnostics):
        stage = _text(diagnostic.get("stage"))
        if stage not in {"panel_proposal", "image_classification", "panel_bbox_repair", "object_localization", "label_localization", "measurement_binding"}:
            continue
        execution_status = _text(diagnostic.get("execution_status"))
        schema_status = _text(diagnostic.get("schema_status"))
        request_id = hashlib.sha256(f"{request_seed}|{index}|{stage}".encode("utf-8")).hexdigest()[:24]
        outcomes.append({
            "provider_name": provider_name,
            "model_name": model_name,
            "request_id": request_id,
            "image_sha256": image_sha256,
            "stage": stage.replace("image_classification", "panel").replace("object_localization", "object").replace("label_localization", "label").replace("measurement_binding", "binding"),
            "raw_success": execution_status == "success",
            "schema_success": schema_status == "valid",
            "execution_error": _text(diagnostic.get("error_type")) if execution_status == "error" else "",
            "schema_error": _text(diagnostic.get("reason")) if schema_status not in {"valid", "skipped"} else "",
            "normalized_bbox": None,
            "object_type": "",
            "label_text": "",
            "attribute_key": "",
            "value": "",
            "unit": "",
            "normalized_value": "",
            "relation": "",
            "confidence": None,
            "rejection_reason": _text(diagnostic.get("reason")),
            "latency_ms": latency_ms,
            "token_estimate": None,
            "cost_estimate": None,
        })
    return outcomes


def _observation_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _text(item.get("observation_uid")), _text(item.get("subject_scope")),
        _text(item.get("attribute_key")), _text(item.get("value")), _text(item.get("unit")),
    )


def _repeatability(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_asset: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        by_asset.setdefault(int(record.get("media_asset_id") or 0), []).append(record)
    comparable = [rows for rows in by_asset.values() if len(rows) > 1]
    uid_matches = 0
    semantic_matches = 0
    iou_matches = 0
    iou_comparable = 0
    for rows in comparable:
        baseline = rows[0].get("observations") or []
        baseline_by_uid = {_text(item.get("observation_uid")): item for item in baseline}
        baseline_set = sorted(_observation_signature(item) for item in baseline)
        uid_stable = True
        semantic_stable = True
        bbox_stable = True
        for row in rows[1:]:
            observations = row.get("observations") or []
            if sorted(_observation_signature(item) for item in observations) != baseline_set:
                uid_stable = False
                semantic_stable = False
            current_by_uid = {_text(item.get("observation_uid")): item for item in observations}
            for uid, baseline_item in baseline_by_uid.items():
                current_item = current_by_uid.get(uid)
                if current_item is None:
                    bbox_stable = False
                    continue
                for key in ("object_bbox", "label_bbox"):
                    overlap = bbox_iou(baseline_item.get(key), current_item.get(key))
                    if overlap is None:
                        continue
                    iou_comparable += 1
                    if overlap < 0.8:
                        bbox_stable = False
                    else:
                        iou_matches += 1
        uid_matches += int(uid_stable)
        semantic_matches += int(semantic_stable)
        # Empty or unavailable boxes are not silently counted as stable bboxes.
        if bbox_stable and baseline_by_uid:
            iou_matches += 0
    return {
        "repeated_asset_count": len(comparable),
        "repeated_uid_stability_rate": _rate(uid_matches, len(comparable)),
        "repeated_semantic_stability_rate": _rate(semantic_matches, len(comparable)),
        "repeated_bbox_iou_stability_rate": _rate(iou_matches, iou_comparable),
    }


def build_qualification_report(
    *, provider_name: str, model_name: str, records: list[dict[str, Any]], database_query_only: bool, formal_kb_write_attempt_count: int,
) -> dict[str, Any]:
    """Build a strict 10-image gate from sanitized shadow extraction records."""
    observations = [item for record in records for item in record.get("observations", [])]
    rejected = [item for record in records for item in record.get("rejected_evidence", [])]
    stage_outcomes = [item for record in records for item in record.get("stage_outcomes", [])]
    model_outcomes = [item for item in stage_outcomes if item["stage"] in {"panel", "object", "label", "binding"}]
    image_read = sum(1 for record in records if (record.get("media_resolution") or {}).get("ok"))
    execution_success = sum(1 for item in model_outcomes if item["raw_success"])
    schema_success = sum(1 for item in model_outcomes if item["schema_success"])
    object_bbox = [item for item in observations if is_normalized_bbox(item.get("object_bbox"))]
    label_bbox = [item for item in observations if is_normalized_bbox(item.get("label_bbox"))]
    binding = [item for item in observations if is_normalized_bbox(item.get("object_bbox")) and is_normalized_bbox(item.get("label_bbox"))]
    panel_assigned = [item for item in observations if _text(item.get("panel_ref")) and is_normalized_bbox(item.get("panel_bbox"))]
    package_leaks = [item for item in observations if _text(item.get("subject_scope")) == "product" and "packaging_measurement_not_product_dimension" in (item.get("warning_reasons") or [])]
    component_leaks = [item for item in observations if _text(item.get("subject_scope")) == "product" and "component_measurement_not_product_dimension" in (item.get("warning_reasons") or [])]
    high_risk = [item for item in observations if _text(item.get("risk_class")) == "high"]
    latencies = [float(item["latency_ms"]) for item in stage_outcomes if item.get("latency_ms") is not None]
    repeatability = _repeatability(records)
    image_total = len({int(record.get("media_asset_id") or 0) for record in records})
    summary = {
        "image_read_success_rate": _rate(image_read, len(records)),
        "execution_success_rate": _rate(execution_success, len(model_outcomes)),
        "schema_success_rate": _rate(schema_success, len(model_outcomes)),
        "bbox_valid_rate": _rate(len(object_bbox) + len(label_bbox), len(observations) * 2),
        "object_bbox_rate": _rate(len(object_bbox), len(observations)),
        "label_bbox_rate": _rate(len(label_bbox), len(observations)),
        "object_label_binding_rate": _rate(len(binding), len(observations)),
        "panel_assignment_rate": _rate(len(panel_assigned), len(observations)),
        "package_product_leakage_count": len(package_leaks),
        "component_overall_leakage_count": len(component_leaks),
        "high_risk_admission_count": len(high_risk),
        "rejected_reason_counts": dict(sorted(Counter(_text(item.get("reason")) for item in rejected).items())),
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": sorted(latencies)[max(0, int((len(latencies) - 1) * 0.95))] if latencies else None,
        "formal_kb_write_attempt_count": formal_kb_write_attempt_count,
        "can_change_can_send_count": sum(1 for item in observations if item.get("can_change_can_send")),
        **repeatability,
    }
    gates = {
        "fixed_10_image_set": image_total == 10,
        "image_read_success": summary["image_read_success_rate"]["rate"] == 1.0,
        "execution_success": summary["execution_success_rate"]["rate"] >= 0.95,
        "schema_success": summary["schema_success_rate"]["rate"] >= 0.95,
        "object_bbox": summary["object_bbox_rate"]["rate"] >= 0.95,
        "label_bbox": summary["label_bbox_rate"]["rate"] >= 0.90,
        "object_label_binding": summary["object_label_binding_rate"]["rate"] >= 0.90,
        "no_package_product_leakage": not package_leaks,
        "no_component_overall_leakage": not component_leaks,
        "no_high_risk_admission": not high_risk,
        "no_formal_kb_write": formal_kb_write_attempt_count == 0,
        "no_can_send_change": summary["can_change_can_send_count"] == 0,
    }
    return {
        "schema_version": "vision_grounding_provider_qualification_v1",
        "shadow_only": True,
        "provider_name": provider_name,
        "model_name": model_name,
        "database_query_only": database_query_only,
        "records": records,
        "stage_outcomes": stage_outcomes,
        "summary": summary,
        "qualification_gates": gates,
        "qualified_for_30_image": all(gates.values()),
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }
