from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.services import composable_vision_ocr_provider_service as service


def _image_bytes() -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_normalizes_windows_ocr_line_boxes_and_preserves_provenance(monkeypatch):
    monkeypatch.setattr(service, "windows_ocr_status", lambda **_kwargs: {"available": True, "language": "zh-Hans-CN"})
    monkeypatch.setattr(service, "_run_powershell", lambda *_args, **_kwargs: {"ok": True, "payload": {"language": "zh-Hans-CN", "items": [{"text": "80cm", "x": 20, "y": 10, "width": 60, "height": 20}]}})
    result = service.recognize_windows_ocr(image_data=_image_bytes(), extension=".png", image_sha256="a" * 64)
    assert result["execution_error"] == ""
    assert result["items"][0]["bbox"]["coordinate_space"] == "normalized"
    assert result["items"][0]["classification"]["dimension_text"] is True
    assert result["items"][0]["observation_eligible"] is False
    assert result["items"][0]["image_sha256"] == "a" * 64


def test_not_configured_provider_has_explicit_diagnosis(monkeypatch):
    monkeypatch.setattr(service, "installed_ocr_runtimes", lambda **_kwargs: {"windows_ocr": {"available": False}, "paddleocr": {"available": False}, "tesseract": {"available": False}, "easyocr": {"available": False}})
    result = service.preferred_ocr_provider(requested_provider="auto")
    assert result["configured"] is False
    assert result["reason"] == "provider_not_configured"
    assert "PaddleOCR" in result["minimum_install_guidance"]


def test_dimension_mode_and_packaging_text_are_recorded_but_high_risk_is_not_observation():
    assert service.classify_ocr_text("80cm")["dimension_text"] is True
    assert service.classify_ocr_text("折叠模式")["mode_text"] is True
    assert service.classify_ocr_text("纸箱发货")["packaging_text"] is True
    assert service.classify_ocr_text("承重 20kg")["high_risk_text"] is True
