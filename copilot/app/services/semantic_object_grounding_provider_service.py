"""Fail-closed semantic object grounding adapters for the shadow-only media PoC."""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Any, Callable

from app.services.composable_vision_object_provider_service import classify_object_scope
from app.services.product_media_observation_v3_service import _normalised_bbox
from app.services.vision_grounding_provider_qualification_service import bbox_iou


SEMANTIC_OBJECT_PROVIDER_VERSION = "semantic_object_grounding_provider_v1"
GENERIC_CLASS_QUERIES = {
    "product": ("product", "item", "main object"),
    "packaging": ("box", "carton", "package", "shipping box"),
    "component": ("shelf", "step", "drawer", "door", "lid", "handle", "panel", "board", "rack", "frame", "compartment"),
    "accessory": ("screw", "tool", "accessory", "fitting"),
}
_OBJECT_TYPES = {"product", "packaging", "component", "accessory", "included_item", "display_prop", "unknown"}
_SCOPED_TYPES = _OBJECT_TYPES - {"unknown"}
_SCOPE_OVERLAP_MAX = 0.70
_COMPONENT_PRODUCT_AREA_MAX = 0.85


def _text(value: Any) -> str:
    return str(value or "").strip()


def _path_from_env(name: str) -> str:
    value = _text(os.getenv(name))
    return value if value and Path(value).exists() else ""


def semantic_object_runtime_status() -> dict[str, Any]:
    """Report availability without importing optional model packages or loading weights."""
    modules = {
        "groundingdino": importlib.util.find_spec("groundingdino") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
    }
    cuda_available = False
    if modules["torch"]:
        try:
            import torch
            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    model_paths = {
        "groundingdino_config": _path_from_env("COPILOT_GROUNDINGDINO_CONFIG"),
        "groundingdino_checkpoint": _path_from_env("COPILOT_GROUNDINGDINO_CHECKPOINT"),
        "florence2_model": _path_from_env("COPILOT_FLORENCE2_MODEL_PATH"),
    }
    return {"modules": modules, "cuda_available": cuda_available, "model_paths": model_paths}


def preferred_semantic_object_provider(*, requested_provider: str = "auto") -> dict[str, Any]:
    """Select only a fully configured semantic provider; never fall back to contours."""
    requested = _text(requested_provider).lower() or "auto"
    status = semantic_object_runtime_status()
    modules, paths = status["modules"], status["model_paths"]
    grounding_ready = modules["groundingdino"] and modules["torch"] and bool(paths["groundingdino_config"]) and bool(paths["groundingdino_checkpoint"])
    florence_ready = modules["transformers"] and modules["torch"] and bool(paths["florence2_model"])
    if requested in {"auto", "groundingdino"} and grounding_ready:
        return {
            "configured": True, "provider_name": "groundingdino", "model_name": "GroundingDINO",
            "runtime_name": "PyTorch", "class_queries": GENERIC_CLASS_QUERIES,
            "runtime_status": status,
        }
    if requested in {"auto", "florence2"} and florence_ready:
        return {
            "configured": True, "provider_name": "florence2", "model_name": "Florence-2",
            "runtime_name": "Transformers/PyTorch", "class_queries": GENERIC_CLASS_QUERIES,
            "runtime_status": status,
        }
    missing = []
    if requested in {"auto", "groundingdino"}:
        missing.extend(name for name, present in (("groundingdino", modules["groundingdino"]), ("torch", modules["torch"]), ("COPILOT_GROUNDINGDINO_CONFIG", bool(paths["groundingdino_config"])), ("COPILOT_GROUNDINGDINO_CHECKPOINT", bool(paths["groundingdino_checkpoint"]))) if not present)
    if requested == "florence2":
        missing.extend(name for name, present in (("transformers", modules["transformers"]), ("torch", modules["torch"]), ("COPILOT_FLORENCE2_MODEL_PATH", bool(paths["florence2_model"]))) if not present)
    return {
        "configured": False, "provider_name": requested, "reason": "provider_not_configured",
        "missing_requirements": sorted(set(missing)), "runtime_status": status,
        "minimum_install_guidance": [
            "Install a PyTorch build compatible with the local CUDA driver.",
            "Install one provider runtime and obtain its official model weights.",
            "Set only the provider configuration and checkpoint/model-path environment variables, then rerun the 10-image shadow qualification.",
        ],
        "class_queries": GENERIC_CLASS_QUERIES,
    }


def _area(box: dict[str, Any]) -> float:
    return float(box["width"]) * float(box["height"])


def _contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    return (
        float(outer["x"]) <= float(inner["x"])
        and float(outer["y"]) <= float(inner["y"])
        and float(inner["x"]) + float(inner["width"]) <= float(outer["x"]) + float(outer["width"])
        and float(inner["y"]) + float(inner["height"]) <= float(outer["y"]) + float(outer["height"])
    )


def _panel_for(box: dict[str, Any], panels: list[dict[str, Any]]) -> str:
    matches = [
        _text(panel.get("panel_ref") or panel.get("proposal_id"))
        for panel in panels
        if isinstance(panel.get("panel_bbox"), dict) and _contains(panel["panel_bbox"], box)
    ]
    return matches[0] if len(matches) == 1 else ""


def _panel_text(panel_id: str, panels: list[dict[str, Any]], ocr_items: list[dict[str, Any]]) -> str:
    panel = next((item for item in panels if _text(item.get("panel_ref") or item.get("proposal_id")) == panel_id), None)
    if not panel:
        return ""
    panel_bbox = panel.get("panel_bbox") or {}
    return " ".join(_text(item.get("text")) for item in ocr_items if isinstance(item.get("bbox"), dict) and _contains(panel_bbox, item["bbox"]))


def normalize_semantic_object_items(
    *, raw_items: list[dict[str, Any]], image_sha256: str, image_size: tuple[int, int] | None,
    panels: list[dict[str, Any]] | None, ocr_items: list[dict[str, Any]] | None, provider: dict[str, Any],
) -> dict[str, Any]:
    """Normalize and contract-check provider boxes without creating observations."""
    active_panels = list(panels or []) or [{"panel_ref": "root", "panel_bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "coordinate_space": "normalized"}}]
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items):
        bbox = _normalised_bbox(raw.get("bbox"), image_size=image_size)
        object_type = _text(raw.get("object_type")).lower()
        if object_type not in _OBJECT_TYPES:
            object_type = "unknown"
        if bbox is None:
            rejected.append({"candidate_index": index, "reason": "invalid_object_bbox"})
            continue
        panel_id = _panel_for(bbox, active_panels)
        if not panel_id:
            rejected.append({"candidate_index": index, "reason": "object_panel_ambiguous"})
            continue
        try:
            confidence = float(raw.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        if not 0.0 <= confidence <= 1.0:
            rejected.append({"candidate_index": index, "reason": "invalid_object_confidence"})
            continue
        candidate = {
            "object_id": _text(raw.get("object_id")) or f"semantic_object_{index + 1}",
            "provider_name": _text(provider.get("provider_name")), "model_name": _text(provider.get("model_name")),
            "runtime_name": _text(provider.get("runtime_name")), "image_sha256": image_sha256,
            "class_query": _text(raw.get("class_query")), "object_type": object_type,
            "object_label": _text(raw.get("object_label")) or object_type, "bbox": bbox,
            "confidence": confidence, "panel_id": panel_id,
            "source_image_size": {"width": image_size[0], "height": image_size[1]} if image_size else {},
            "execution_error": "", "schema_error": "", "observation_eligible": False,
            "used_for_generation": False, "can_change_can_send": False,
        }
        if object_type == "packaging":
            scope, _reason = classify_object_scope(panel_text=_panel_text(panel_id, active_panels, list(ocr_items or [])))
            if scope != "packaging":
                rejected.append({"candidate_index": index, "reason": "packaging_text_evidence_required"})
                continue
        candidates.append(candidate)

    invalid_ids: set[str] = set()
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1:]:
            if left["panel_id"] != right["panel_id"]:
                continue
            overlap = bbox_iou(left["bbox"], right["bbox"])
            pair = {left["object_type"], right["object_type"]}
            if overlap is not None and overlap >= _SCOPE_OVERLAP_MAX and pair == {"product", "packaging"}:
                invalid_ids.update({left["object_id"], right["object_id"]})
    products = [item for item in candidates if item["object_type"] == "product"]
    for item in candidates:
        if item["object_type"] != "component":
            continue
        parents = [product for product in products if product["panel_id"] == item["panel_id"] and _contains(product["bbox"], item["bbox"])]
        if not parents:
            invalid_ids.add(item["object_id"])
            continue
        if any(_area(item["bbox"]) / max(_area(parent["bbox"]), 0.000001) >= _COMPONENT_PRODUCT_AREA_MAX for parent in parents):
            invalid_ids.add(item["object_id"])

    objects = []
    for item in candidates:
        if item["object_id"] not in invalid_ids:
            objects.append(item)
            continue
        reason = "product_packaging_scope_conflict" if item["object_type"] in {"product", "packaging"} else "component_covers_or_lacks_parent_product"
        rejected.append({"object_id": item["object_id"], "reason": reason, "object_type": item["object_type"]})
    return {"objects": objects, "rejected": rejected, "diagnostics": [{"reason": "component_not_supported"}] if not any(item["object_type"] == "component" for item in objects) else []}


def execute_semantic_object_provider(
    *, provider: dict[str, Any], image_data: bytes, image_sha256: str, image_size: tuple[int, int] | None,
    panels: list[dict[str, Any]] | None, ocr_items: list[dict[str, Any]] | None,
    infer: Callable[[bytes, dict[str, tuple[str, ...]]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run an injected provider implementation, or fail closed until one is configured."""
    started = time.perf_counter()
    if not provider.get("configured"):
        return {"objects": [], "rejected": [], "diagnostics": [{"reason": "provider_not_configured"}], "execution_error": "provider_not_configured", "schema_error": "", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    if infer is None:
        return {"objects": [], "rejected": [], "diagnostics": [{"reason": "provider_adapter_not_implemented"}], "execution_error": "provider_adapter_not_implemented", "schema_error": "", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    try:
        raw_items = infer(image_data, GENERIC_CLASS_QUERIES)
    except Exception as exc:
        return {"objects": [], "rejected": [], "diagnostics": [{"reason": "provider_execution_error", "error_type": type(exc).__name__}], "execution_error": "provider_execution_error", "schema_error": "", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    if not isinstance(raw_items, list) or not all(isinstance(item, dict) for item in raw_items):
        return {"objects": [], "rejected": [], "diagnostics": [{"reason": "provider_schema_error"}], "execution_error": "", "schema_error": "provider_schema_error", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    result = normalize_semantic_object_items(
        raw_items=raw_items, image_sha256=image_sha256, image_size=image_size, panels=panels,
        ocr_items=ocr_items, provider=provider,
    )
    result.update({"execution_error": "", "schema_error": "", "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
    return result
