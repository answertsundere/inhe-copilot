from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from app.services import composable_vision_object_provider_service as service


def _image_bytes() -> bytes:
    image = Image.new("RGB", (200, 120), "white")
    ImageDraw.Draw(image).rectangle((25, 20, 175, 100), fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _panel(panel_ref: str = "root", x: float = 0.0, width: float = 1.0) -> dict:
    return {"panel_ref": panel_ref, "panel_bbox": {"x": x, "y": 0.0, "width": width, "height": 1.0, "coordinate_space": "normalized"}}


def test_explicit_packaging_hint_scopes_primary_visual_region_as_packaging():
    result = service.propose_deterministic_objects(
        image_data=_image_bytes(), image_sha256="a" * 64, panels=[_panel()],
        ocr_items=[{"text": "纸箱发货", "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1, "coordinate_space": "normalized"}}],
    )
    item = result["objects"][0]
    assert item["object_type"] == "packaging"
    assert item["subject_scope"] == "packaging"
    assert item["bbox"]["coordinate_space"] == "normalized"
    assert item["observation_eligible"] is False
    assert item["can_change_can_send"] is False


def test_unknown_primary_visual_region_is_not_promoted_to_product():
    result = service.propose_deterministic_objects(image_data=_image_bytes(), image_sha256="b" * 64, panels=[_panel()], ocr_items=[])
    assert result["objects"][0]["object_type"] == "unknown_object_scope"
    assert result["objects"][0]["subject_scope"] == ""
    assert {item["reason"] for item in result["diagnostics"]} >= {"unknown_object_scope", "component_not_supported"}
    assert service.geometry_eligible_object_items(result["objects"]) == []


def test_display_prop_hint_is_not_geometry_eligible():
    result = service.propose_deterministic_objects(
        image_data=_image_bytes(), image_sha256="c" * 64, panels=[_panel()],
        ocr_items=[{"text": "背景装饰", "bbox": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1, "coordinate_space": "normalized"}}],
    )
    assert result["objects"][0]["object_type"] == "display_prop"
    assert service.geometry_eligible_object_items(result["objects"]) == []


def test_panel_candidates_remain_inside_their_panels():
    image = Image.new("RGB", (200, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 20, 80, 100), fill="black")
    draw.rectangle((120, 20, 190, 100), fill="black")
    buffer = BytesIO(); image.save(buffer, format="PNG")
    result = service.propose_deterministic_objects(
        image_data=buffer.getvalue(), image_sha256="d" * 64,
        panels=[_panel("left", 0.0, 0.5), _panel("right", 0.5, 0.5)], ocr_items=[],
    )
    assert {item["panel_id"] for item in result["objects"]} == {"left", "right"}
    assert all(item["object_type"] == "unknown_object_scope" for item in result["objects"])


def test_unconfigured_provider_has_explicit_diagnosis(monkeypatch):
    monkeypatch.setattr(service, "installed_object_runtimes", lambda: {"groundingdino": False, "transformers": False, "torch": False, "onnxruntime": True, "cv2": False})
    result = service.preferred_object_provider(requested_provider="auto")
    assert result["configured"] is False
    assert result["reason"] == "provider_not_configured"
