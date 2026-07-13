"""Read-only annotation schema for product-media detector feasibility work.

The schema deliberately describes visual regions and their relationships.  It
does not turn OCR, model predictions, or annotations into product facts.
"""

from __future__ import annotations

import hashlib
from typing import Any


ANNOTATION_SCHEMA_VERSION = "product_media_annotation_v1"
LABEL_STUDIO_MODEL_VERSION = "copilot_shadow_candidates_v1"

OBJECT_LABELS = (
    "product_overall",
    "packaging",
    "component",
    "accessory",
    "included_item",
    "display_prop",
    "label_text_region",
    "dimension_label_region",
    "mode_panel",
    "product_panel",
    "high_risk_text_region",
)
PROHIBITED_FACT_LABELS = {
    "load_capacity",
    "non_toxic",
    "food_grade",
    "certification",
    "child_safety",
    "anti_tip",
    "wall_mounting",
}
RELATION_TYPES = {
    "panel_contains_object",
    "label_describes_object",
    "dimension_measures_object",
    "object_part_of_product",
    "object_active_in_mode",
}
ATTRIBUTE_KEYS = {
    "width",
    "height",
    "depth",
    "length",
    "diameter",
    "thickness",
    "layer_count",
    "compartment_count",
}

_CACHE_FIELDS = ("original_path", "cache_path", "local_cache_path", "cached_path", "download_path", "file_path")
_ROLE_PRIORITY = {
    "size_image": 0,
    "pack_guide_image": 1,
    "accessory_image": 2,
    "sku_image": 3,
}
_HIGH_RISK_TERMS = ("承重", "无毒", "食品级", "认证", "检测", "儿童安全", "防倾倒", "固定墙", "墙面固定")
_MODEL_CANDIDATE_FIELDS = (
    "provider_name",
    "model_name",
    "object_type",
    "object_label",
    "subject_scope",
    "panel_id",
    "bbox",
    "confidence",
    "rejection_reason",
    "observation_eligible",
    "used_for_generation",
    "can_change_can_send",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _raw(asset: Any) -> dict[str, Any]:
    if isinstance(asset, dict):
        value = asset.get("source_raw")
    elif hasattr(asset, "get_source_raw"):
        value = asset.get_source_raw()
    else:
        value = getattr(asset, "source_raw", None)
    return value if isinstance(value, dict) else {}


def _value(asset: Any, key: str) -> Any:
    return asset.get(key) if isinstance(asset, dict) else getattr(asset, key, None)


def _scene_tags(asset: Any) -> list[str]:
    if isinstance(asset, dict):
        value = asset.get("scene_tags")
    elif hasattr(asset, "get_scene_tags"):
        value = asset.get_scene_tags()
    else:
        value = getattr(asset, "scene_tags", None)
    return [str(item).strip().lower() for item in value] if isinstance(value, list) else []


def image_reference(asset: Any) -> tuple[str, str]:
    """Return the existing source reference without downloading or rewriting it."""
    url = _text(_value(asset, "asset_url"))
    if url:
        return url, "asset_url"
    raw = _raw(asset)
    for field in _CACHE_FIELDS:
        value = _text(raw.get(field))
        if value:
            return value, field
    return "", "missing"


def product_identity(asset: Any) -> dict[str, str]:
    return {
        "product_id": _text(_value(asset, "product_id")),
        "i_id": _text(_value(asset, "i_id")),
        "sku_code": _text(_value(asset, "sku_code")),
    }


def suggested_task_type(asset: Any) -> str:
    """Use durable media metadata only; filenames and product text are excluded."""
    role = _text(_value(asset, "asset_type")).lower()
    if role == "size_image":
        return "尺寸标注与对象范围"
    if role == "pack_guide_image":
        return "安装资料中的对象与文字区域"
    if role == "accessory_image":
        return "配件、随附物与对象范围"
    if role == "sku_image":
        return "商品整体、包装或展示道具范围"
    return "对象范围与文字区域"


def annotation_priority(asset: Any) -> tuple[int, str]:
    role = _text(_value(asset, "asset_type")).lower()
    tags = set(_scene_tags(asset))
    if role in _ROLE_PRIORITY:
        return _ROLE_PRIORITY[role], role
    if {"packaging", "mode", "multi_panel"}.intersection(tags):
        return 4, "scene_tagged_visual_layout"
    return 9, "other_media_role"


def is_annotation_image_asset(asset: Any) -> bool:
    """Accept explicit image roles only; videos are not Label Studio image tasks."""
    return _text(_value(asset, "asset_type")).lower().endswith("_image")


def annotation_instructions() -> list[str]:
    return [
        "框选商品整体、包装、部件、配件、随附物、展示道具及文字区域；无法确认时不标为商品整体。",
        "尺寸文字必须同时标注文字区域和被测对象；包装尺寸、部件尺寸和模式尺寸不得标为商品整体尺寸。",
        "多面板图片先标模式或商品面板，再在同一面板内标对象和文字。",
        "承重、无毒、食品级、认证、儿童安全、防倾倒和墙面固定仅可标为高风险文字区域，不标为可回答事实。",
    ]


def _normalized_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if bbox["width"] <= 0 or bbox["height"] <= 0:
        return None
    if any(number < 0 or number > 1 for number in bbox.values()):
        return None
    if bbox["x"] + bbox["width"] > 1 or bbox["y"] + bbox["height"] > 1:
        return None
    return bbox


def _is_high_risk_text(text: str, classification: dict[str, Any] | None = None) -> bool:
    if isinstance(classification, dict) and classification.get("high_risk_text"):
        return True
    normalized = _text(text).lower()
    return any(term in normalized for term in _HIGH_RISK_TERMS)


def _ocr_prediction(asset_id: str, item: dict[str, Any], index: int) -> dict[str, Any] | None:
    bbox = _normalized_bbox(item.get("bbox"))
    text = _text(item.get("text"))
    if not bbox or not text:
        return None
    classification = item.get("classification") if isinstance(item.get("classification"), dict) else {}
    label = "high_risk_text_region" if _is_high_risk_text(text, classification) else (
        "dimension_label_region" if classification.get("dimension_text") else "label_text_region"
    )
    original_size = item.get("source_image_size") if isinstance(item.get("source_image_size"), dict) else {}
    width = int(original_size.get("width") or 1)
    height = int(original_size.get("height") or 1)
    result_id = hashlib.sha256(f"{asset_id}|ocr|{index}|{text}|{bbox}".encode("utf-8")).hexdigest()[:20]
    return {
        "id": f"ocr_{result_id}",
        "type": "rectanglelabels",
        "from_name": "region_label",
        "to_name": "image",
        "original_width": width,
        "original_height": height,
        "image_rotation": 0,
        "score": float(item.get("confidence") or 0.0),
        "value": {
            "x": round(bbox["x"] * 100, 4),
            "y": round(bbox["y"] * 100, 4),
            "width": round(bbox["width"] * 100, 4),
            "height": round(bbox["height"] * 100, 4),
            "rotation": 0,
            "rectanglelabels": [label],
        },
        "meta": {"text": text, "source": _text(item.get("source") or item.get("provider_name") or "ocr")},
    }


def _safe_model_candidates(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep review-relevant geometry/provenance, never provider raw payloads."""
    safe: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        item = {field: candidate[field] for field in _MODEL_CANDIDATE_FIELDS if field in candidate}
        bbox = _normalized_bbox(item.get("bbox"))
        if "bbox" in item:
            item["bbox"] = bbox
        safe.append(item)
    return safe


def build_label_studio_task(
    asset: Any,
    *,
    ocr_items: list[dict[str, Any]] | None = None,
    model_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an importable Label Studio task with shadow suggestions only."""
    asset_id = _text(_value(asset, "id") or _value(asset, "asset_id"))
    reference, reference_kind = image_reference(asset)
    priority, priority_reason = annotation_priority(asset)
    predictions = [
        prediction
        for index, item in enumerate(ocr_items or [])
        if isinstance(item, dict)
        for prediction in [_ocr_prediction(asset_id, item, index)]
        if prediction is not None
    ]
    return {
        "data": {"image": reference},
        "meta": {
            "schema_version": ANNOTATION_SCHEMA_VERSION,
            "media_asset_id": asset_id,
            "image_reference_kind": reference_kind,
            "product_identity": product_identity(asset),
            "media_role": _text(_value(asset, "asset_type")),
            "suggested_task_type": suggested_task_type(asset),
            "priority": priority,
            "priority_reason": priority_reason,
            "annotation_instructions_zh": annotation_instructions(),
            "prohibited_fact_labels": sorted(PROHIBITED_FACT_LABELS),
            "current_model_candidates": _safe_model_candidates(model_candidates),
            "shadow_only": True,
            "used_for_generation": False,
            "can_change_can_send": False,
        },
        "predictions": [{"model_version": LABEL_STUDIO_MODEL_VERSION, "result": predictions}] if predictions else [],
    }


def validate_label_studio_task(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(task, dict) or not isinstance(task.get("data"), dict) or not _text(task["data"].get("image")):
        errors.append("image_reference_required")
    meta = task.get("meta") if isinstance(task, dict) else None
    if not isinstance(meta, dict) or meta.get("schema_version") != ANNOTATION_SCHEMA_VERSION:
        errors.append("annotation_schema_version_invalid")
    elif set(meta.get("prohibited_fact_labels") or ()) != PROHIBITED_FACT_LABELS:
        errors.append("prohibited_fact_labels_invalid")
    for prediction in task.get("predictions") or []:
        for result in prediction.get("result") or []:
            labels = ((result.get("value") or {}).get("rectanglelabels") or [])
            if len(labels) != 1 or labels[0] not in OBJECT_LABELS:
                errors.append("annotation_label_invalid")
    return errors


def annotation_schema() -> dict[str, Any]:
    return {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "object_labels": list(OBJECT_LABELS),
        "relation_types": sorted(RELATION_TYPES),
        "attribute_keys": sorted(ATTRIBUTE_KEYS),
        "prohibited_fact_labels": sorted(PROHIBITED_FACT_LABELS),
        "shadow_only": True,
        "used_for_generation": False,
        "can_change_can_send": False,
    }
