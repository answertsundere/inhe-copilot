"""Conservative object-proposal adapters for the composable vision shadow PoC."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import time
from typing import Any

import cv2
import numpy as np

from app.services.product_media_observation_v3_service import _normalised_bbox


_PACKAGING_HINTS = ("包装", "纸箱", "外箱", "发货", "carton", "package", "box")
_DISPLAY_PROP_HINTS = ("背景", "装饰", "道具", "手持", "background", "decorative", "prop")
_SCOPES = {"packaging", "product", "component", "accessory", "included_item", "display_prop"}
_MIN_OBJECT_AREA = 0.04


def _text(value: Any) -> str:
    return str(value or "").strip()


def installed_object_runtimes() -> dict[str, bool]:
    """Inventory optional runtimes; availability is not provider qualification."""
    return {
        "groundingdino": importlib.util.find_spec("groundingdino") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
        "onnxruntime": importlib.util.find_spec("onnxruntime") is not None,
        "cv2": importlib.util.find_spec("cv2") is not None,
    }


def preferred_object_provider(*, requested_provider: str = "auto") -> dict[str, Any]:
    runtimes = installed_object_runtimes()
    requested = _text(requested_provider).lower() or "auto"
    if requested in {"auto", "deterministic", "deterministic_primary_subject"} and runtimes["cv2"]:
        return {
            "configured": True,
            "provider_name": "deterministic_primary_subject_proposal",
            "model_name": "none",
            "runtime_name": "OpenCV contours",
            "scope_limit": "packaging_only_or_unknown",
            "runtimes": runtimes,
        }
    return {
        "configured": False,
        "provider_name": requested,
        "reason": "provider_not_configured",
        "minimum_install_guidance": "配置 GroundingDINO 或 Florence-2 的权重和运行时后重新运行对象资格评测。",
        "runtimes": runtimes,
    }


def classify_object_scope(*, panel_text: str) -> tuple[str, str]:
    """Classify only explicit low-risk visual-scope hints; never assume product."""
    normalized = _text(panel_text).lower()
    if any(hint in normalized for hint in _PACKAGING_HINTS):
        return "packaging", "packaging_text_hint"
    if any(hint in normalized for hint in _DISPLAY_PROP_HINTS):
        return "display_prop", "display_prop_text_hint"
    return "unknown_object_scope", "scope_not_semantically_verified"


def _root_panel() -> dict[str, Any]:
    return {
        "panel_ref": "root",
        "panel_bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "coordinate_space": "normalized"},
    }


def _contains(panel_bbox: dict[str, Any], box: dict[str, Any]) -> bool:
    px, py, pw, ph = (float(panel_bbox[key]) for key in ("x", "y", "width", "height"))
    bx, by, bw, bh = (float(box[key]) for key in ("x", "y", "width", "height"))
    return px <= bx and py <= by and bx + bw <= px + pw and by + bh <= py + ph


def _panel_text(panel: dict[str, Any], labels: list[dict[str, Any]]) -> str:
    panel_bbox = panel.get("panel_bbox") or {}
    return " ".join(
        _text(item.get("text"))
        for item in labels
        if isinstance(item.get("bbox"), dict) and _contains(panel_bbox, item["bbox"])
    )


def _primary_content_bbox(image: np.ndarray, panel_bbox: dict[str, Any]) -> dict[str, Any] | None:
    height, width = image.shape[:2]
    x0 = max(0, min(width - 1, round(float(panel_bbox["x"]) * width)))
    y0 = max(0, min(height - 1, round(float(panel_bbox["y"]) * height)))
    x1 = max(x0 + 1, min(width, round((float(panel_bbox["x"]) + float(panel_bbox["width"])) * width)))
    y1 = max(y0 + 1, min(height, round((float(panel_bbox["y"]) + float(panel_bbox["height"])) * height)))
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = cv2.threshold(gray, 242, 255, cv2.THRESH_BINARY_INV)[1]
    kernel = np.ones((max(3, crop.shape[0] // 100), max(3, crop.shape[1] // 100)), np.uint8)
    merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    points = cv2.findNonZero(merged)
    if points is None:
        return None
    x, y, box_width, box_height = cv2.boundingRect(points)
    raw_bbox = {
        "x": x0 + x,
        "y": y0 + y,
        "width": box_width,
        "height": box_height,
        "coordinate_space": "pixel",
    }
    normalized = _normalised_bbox(raw_bbox, image_size=(width, height))
    if normalized is None or float(normalized["width"]) * float(normalized["height"]) < _MIN_OBJECT_AREA:
        return None
    return normalized


def propose_deterministic_objects(*, image_data: bytes, image_sha256: str, panels: list[dict[str, Any]] | None, ocr_items: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Return primary visual-region candidates without inferring a sellable item."""
    started = time.perf_counter()
    decoded = cv2.imdecode(np.frombuffer(image_data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        return {"provider_name": "deterministic_primary_subject_proposal", "model_name": "none", "runtime_name": "OpenCV contours", "image_sha256": image_sha256, "objects": [], "diagnostics": [{"reason": "image_decode_failed"}], "execution_error": "image_decode_failed", "schema_error": "", "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
    height, width = decoded.shape[:2]
    active_panels = list(panels or []) or [_root_panel()]
    objects: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for panel in active_panels:
        panel_ref = _text(panel.get("panel_ref") or panel.get("proposal_id")) or "root"
        panel_bbox = panel.get("panel_bbox")
        if _normalised_bbox(panel_bbox, image_size=None) is None:
            diagnostics.append({"panel_id": panel_ref, "reason": "invalid_panel_bbox"})
            continue
        bbox = _primary_content_bbox(decoded, panel_bbox)
        if bbox is None:
            diagnostics.append({"panel_id": panel_ref, "reason": "primary_subject_not_detected"})
            continue
        object_type, scope_reason = classify_object_scope(panel_text=_panel_text(panel, list(ocr_items or [])))
        scope = object_type if object_type in _SCOPES else ""
        object_id = hashlib.sha256(f"{image_sha256}|{panel_ref}|{bbox['x']:.6f}|{bbox['y']:.6f}|{bbox['width']:.6f}|{bbox['height']:.6f}".encode("utf-8")).hexdigest()[:24]
        objects.append({
            "object_id": f"object_{object_id}",
            "provider_name": "deterministic_primary_subject_proposal",
            "model_name": "none",
            "runtime_name": "OpenCV contours",
            "image_sha256": image_sha256,
            "object_type": object_type,
            "object_label": "primary_visual_subject",
            "subject_scope": scope,
            "bbox": bbox,
            "confidence": 0.5 if scope else 0.25,
            "panel_id": panel_ref,
            "source_image_size": {"width": width, "height": height},
            "scope_reason": scope_reason,
            "execution_error": "",
            "schema_error": "",
            "observation_eligible": False,
            "used_for_generation": False,
            "can_change_can_send": False,
        })
        if object_type == "unknown_object_scope":
            diagnostics.append({"panel_id": panel_ref, "reason": "unknown_object_scope"})
    diagnostics.append({"reason": "component_not_supported"})
    return {
        "provider_name": "deterministic_primary_subject_proposal",
        "model_name": "none",
        "runtime_name": "OpenCV contours",
        "image_sha256": image_sha256,
        "objects": objects,
        "diagnostics": diagnostics,
        "execution_error": "",
        "schema_error": "",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def geometry_eligible_object_items(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose only semantically scoped candidates to a future geometry stage."""
    return [item for item in objects if item.get("subject_scope") in _SCOPES and item.get("object_type") != "display_prop"]
