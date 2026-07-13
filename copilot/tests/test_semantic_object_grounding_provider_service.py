from __future__ import annotations

from app.services import semantic_object_grounding_provider_service as service


def _box(x: float = 0.1, y: float = 0.1, width: float = 0.4, height: float = 0.4) -> dict:
    return {"x": x, "y": y, "width": width, "height": height, "coordinate_space": "normalized"}


def _panel() -> list[dict]:
    return [{"panel_ref": "root", "panel_bbox": _box(0.0, 0.0, 1.0, 1.0)}]


def _provider() -> dict:
    return {"configured": True, "provider_name": "groundingdino", "model_name": "GroundingDINO", "runtime_name": "PyTorch"}


def test_unconfigured_provider_reports_requirements_without_contour_fallback(monkeypatch):
    monkeypatch.setattr(service, "semantic_object_runtime_status", lambda: {"modules": {"groundingdino": False, "transformers": False, "torch": False, "pillow": False}, "cuda_available": False, "model_paths": {"groundingdino_config": "", "groundingdino_checkpoint": "", "groundingdino_model": "", "florence2_model": ""}})
    result = service.preferred_semantic_object_provider(requested_provider="auto")
    assert result["configured"] is False
    assert result["reason"] == "provider_not_configured"
    assert "transformers" in result["missing_requirements"]
    assert result["provider_name"] == "auto"


def test_unconfigured_florence_provider_reports_its_local_model_requirement(monkeypatch):
    monkeypatch.setattr(service, "semantic_object_runtime_status", lambda: {
        "modules": {"groundingdino": False, "transformers": True, "torch": True, "pillow": True},
        "cuda_available": True,
        "model_paths": {"groundingdino_config": "", "groundingdino_checkpoint": "", "groundingdino_model": "", "florence2_model": ""},
    })
    result = service.preferred_semantic_object_provider(requested_provider="florence2")
    assert result["configured"] is False
    assert "COPILOT_FLORENCE2_MODEL_PATH" in result["missing_requirements"]


def test_prefers_local_transformers_groundingdino_when_runtime_and_model_exist(monkeypatch):
    monkeypatch.setattr(service, "semantic_object_runtime_status", lambda: {
        "modules": {"groundingdino": False, "transformers": True, "torch": True, "pillow": True},
        "cuda_available": True,
        "model_paths": {"groundingdino_config": "", "groundingdino_checkpoint": "", "groundingdino_model": "D:/AIModels/model", "florence2_model": ""},
    })
    result = service.preferred_semantic_object_provider(requested_provider="groundingdino")
    assert result["configured"] is True
    assert result["runtime_name"] == "Transformers/PyTorch"
    assert result["model_path"] == "D:/AIModels/model"


def test_prefers_local_transformers_florence2_when_model_exists(monkeypatch):
    monkeypatch.setattr(service, "semantic_object_runtime_status", lambda: {
        "modules": {"groundingdino": False, "transformers": True, "torch": True, "pillow": True},
        "cuda_available": True,
        "model_paths": {"groundingdino_config": "", "groundingdino_checkpoint": "", "groundingdino_model": "", "florence2_model": "D:/AIModels/florence"},
    })
    result = service.preferred_semantic_object_provider(requested_provider="florence2")
    assert result["configured"] is True
    assert result["provider_name"] == "florence2"
    assert result["model_path"] == "D:/AIModels/florence"


def test_composed_generic_detection_label_keeps_a_single_scope():
    assert service._object_type_for_detected_label(
        "package shipping box", {"package": "packaging", "shipping box": "packaging", "product": "product"},
    ) == "packaging"
    assert service._object_type_for_detected_label(
        "product box", {"product": "product", "box": "packaging"},
    ) == "unknown"


def test_normalizes_generic_semantic_product_output_without_promotion_side_effects():
    result = service.normalize_semantic_object_items(
        raw_items=[{"object_type": "product", "object_label": "main object", "class_query": "product", "bbox": _box(), "confidence": 0.9}],
        image_sha256="a" * 64, image_size=None, panels=_panel(), ocr_items=[], provider=_provider(),
    )
    item = result["objects"][0]
    assert item["object_type"] == "product"
    assert item["class_query"] == "product"
    assert item["bbox"]["coordinate_space"] == "normalized"
    assert item["observation_eligible"] is False
    assert item["used_for_generation"] is False
    assert item["can_change_can_send"] is False


def test_packaging_requires_matching_ocr_context():
    result = service.normalize_semantic_object_items(
        raw_items=[{"object_type": "packaging", "bbox": _box(), "confidence": 0.9}],
        image_sha256="b" * 64, image_size=None, panels=_panel(), ocr_items=[], provider=_provider(),
    )
    assert result["objects"] == []
    assert result["rejected"][0]["reason"] == "packaging_text_evidence_required"


def test_packaging_with_ocr_context_is_kept_as_packaging_not_product():
    result = service.normalize_semantic_object_items(
        raw_items=[{"object_type": "packaging", "bbox": _box(), "confidence": 0.9}],
        image_sha256="c" * 64, image_size=None, panels=_panel(),
        ocr_items=[{"text": "纸箱发货", "bbox": _box(0.15, 0.15, 0.1, 0.1)}], provider=_provider(),
    )
    assert result["objects"][0]["object_type"] == "packaging"


def test_product_packaging_overlap_fails_closed():
    result = service.normalize_semantic_object_items(
        raw_items=[
            {"object_id": "product", "object_type": "product", "bbox": _box(), "confidence": 0.9},
            {"object_id": "package", "object_type": "packaging", "bbox": _box(0.12, 0.12, 0.4, 0.4), "confidence": 0.9},
        ],
        image_sha256="d" * 64, image_size=None, panels=_panel(),
        ocr_items=[{"text": "包装盒", "bbox": _box(0.15, 0.15, 0.1, 0.1)}], provider=_provider(),
    )
    assert result["objects"] == []
    assert {item["reason"] for item in result["rejected"]} == {"product_packaging_scope_conflict"}


def test_component_requires_smaller_parent_product_in_same_panel():
    rejected = service.normalize_semantic_object_items(
        raw_items=[{"object_type": "component", "bbox": _box(), "confidence": 0.9}],
        image_sha256="e" * 64, image_size=None, panels=_panel(), ocr_items=[], provider=_provider(),
    )
    assert rejected["objects"] == []
    assert rejected["rejected"][0]["reason"] == "component_covers_or_lacks_parent_product"

    accepted = service.normalize_semantic_object_items(
        raw_items=[
            {"object_type": "product", "bbox": _box(), "confidence": 0.9},
            {"object_type": "component", "bbox": _box(0.2, 0.2, 0.1, 0.1), "confidence": 0.9},
        ],
        image_sha256="f" * 64, image_size=None, panels=_panel(), ocr_items=[], provider=_provider(),
    )
    assert {item["object_type"] for item in accepted["objects"]} == {"product", "component"}


def test_unknown_and_display_prop_never_upgrade_to_product():
    result = service.normalize_semantic_object_items(
        raw_items=[
            {"object_type": "unknown", "bbox": _box(), "confidence": 0.9},
            {"object_type": "display_prop", "bbox": _box(0.55, 0.1, 0.2, 0.2), "confidence": 0.9},
        ],
        image_sha256="g" * 64, image_size=None, panels=_panel(), ocr_items=[], provider=_provider(),
    )
    assert {item["object_type"] for item in result["objects"]} == {"unknown", "display_prop"}


def test_cross_panel_object_box_is_rejected():
    panels = [
        {"panel_ref": "left", "panel_bbox": _box(0.0, 0.0, 0.5, 1.0)},
        {"panel_ref": "right", "panel_bbox": _box(0.5, 0.0, 0.5, 1.0)},
    ]
    result = service.normalize_semantic_object_items(
        raw_items=[{"object_type": "product", "bbox": _box(0.3, 0.1, 0.4, 0.4), "confidence": 0.9}],
        image_sha256="h" * 64, image_size=None, panels=panels, ocr_items=[], provider=_provider(),
    )
    assert result["objects"] == []
    assert result["rejected"][0]["reason"] == "object_panel_ambiguous"


def test_provider_schema_error_has_no_object_output():
    result = service.execute_semantic_object_provider(
        provider=_provider(), image_data=b"image", image_sha256="h" * 64, image_size=None,
        panels=_panel(), ocr_items=[], infer=lambda *_args: {"not": "a list"},
    )
    assert result["objects"] == []
    assert result["schema_error"] == "provider_schema_error"


def test_configured_transformers_provider_uses_local_infer_without_promotion(monkeypatch):
    monkeypatch.setattr(service, "_infer_transformers_groundingdino", lambda *_args, **_kwargs: [
        {"object_type": "product", "object_label": "product", "class_query": "product", "bbox": _box(), "confidence": 0.9},
    ])
    provider = {**_provider(), "model_path": "D:/AIModels/model"}
    result = service.execute_semantic_object_provider(
        provider=provider, image_data=b"image", image_sha256="i" * 64, image_size=None,
        panels=_panel(), ocr_items=[],
    )
    assert result["execution_error"] == ""
    assert result["objects"][0]["observation_eligible"] is False
    assert result["objects"][0]["can_change_can_send"] is False


def test_configured_florence_provider_uses_local_infer_without_promotion(monkeypatch):
    monkeypatch.setattr(service, "_infer_transformers_florence2", lambda *_args, **_kwargs: [
        {"object_type": "unknown", "object_label": "generic object", "class_query": "generic_object_detection", "bbox": _box(), "confidence": 0.5},
    ])
    provider = {"configured": True, "provider_name": "florence2", "model_name": "Florence-2", "runtime_name": "Transformers/PyTorch", "model_path": "D:/AIModels/florence"}
    result = service.execute_semantic_object_provider(
        provider=provider, image_data=b"image", image_sha256="j" * 64, image_size=None,
        panels=_panel(), ocr_items=[],
    )
    assert result["execution_error"] == ""
    assert result["objects"][0]["object_type"] == "unknown"
    assert result["objects"][0]["can_change_can_send"] is False
