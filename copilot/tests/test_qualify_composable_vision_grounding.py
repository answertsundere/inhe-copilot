from __future__ import annotations

from scripts import qualify_composable_vision_grounding as script


def test_composable_provider_status_requires_ocr_and_object_capability():
    assert script.provider_status({"paddleocr": False, "groundingdino": True, "transformers": True}) == "provider_not_configured"
    assert script.provider_status({"paddleocr": True, "groundingdino": False, "transformers": False}) == "provider_not_configured"
    assert script.provider_status({"paddleocr": True, "groundingdino": True, "transformers": False}) == "adapter_wiring_required"
