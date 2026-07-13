from __future__ import annotations

from app.services.product_media_annotation_schema_service import (
    OBJECT_LABELS,
    PROHIBITED_FACT_LABELS,
    annotation_schema,
    build_label_studio_task,
    validate_label_studio_task,
)


def _asset(**overrides):
    asset = {
        "id": 7,
        "asset_url": "https://media.example.test/spec.png",
        "product_id": 11,
        "i_id": "IID-TEST",
        "sku_code": "SKU-TEST",
        "asset_type": "size_image",
        "scene_tags": ["multi_panel"],
        "source_raw": {},
    }
    asset.update(overrides)
    return asset


def test_schema_has_general_object_categories_and_keeps_risk_labels_out_of_facts():
    schema = annotation_schema()

    assert {"product_overall", "packaging", "component", "accessory", "included_item", "display_prop", "label_text_region", "dimension_label_region", "mode_panel", "product_panel"}.issubset(OBJECT_LABELS)
    assert {"load_capacity", "non_toxic", "food_grade", "certification", "child_safety", "anti_tip", "wall_mounting"} == PROHIBITED_FACT_LABELS
    assert schema["can_change_can_send"] is False
    assert not PROHIBITED_FACT_LABELS.intersection(schema["object_labels"])


def test_label_studio_task_keeps_ocr_as_shadow_prediction_not_product_fact():
    task = build_label_studio_task(
        _asset(),
        ocr_items=[{
            "text": "80cm",
            "bbox": {"x": 0.1, "y": 0.2, "width": 0.2, "height": 0.1, "coordinate_space": "normalized"},
            "confidence": 0.9,
            "classification": {"dimension_text": True},
            "source_image_size": {"width": 1000, "height": 800},
        }],
        model_candidates=[{
            "object_type": "unknown_object_scope",
            "observation_eligible": False,
            "bbox": {"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.4},
            "raw_payload": "not_for_annotation_export",
            "api_key": "not-for-export",
        }],
    )

    assert validate_label_studio_task(task) == []
    assert task["predictions"][0]["result"][0]["value"]["rectanglelabels"] == ["dimension_label_region"]
    assert task["meta"]["current_model_candidates"][0]["observation_eligible"] is False
    assert "raw_payload" not in task["meta"]["current_model_candidates"][0]
    assert "api_key" not in task["meta"]["current_model_candidates"][0]
    assert task["meta"]["used_for_generation"] is False
    assert task["meta"]["can_change_can_send"] is False


def test_high_risk_ocr_text_is_only_a_high_risk_text_region():
    task = build_label_studio_task(
        _asset(),
        ocr_items=[{
            "text": "承重 20kg",
            "bbox": {"x": 0.2, "y": 0.2, "width": 0.2, "height": 0.1, "coordinate_space": "normalized"},
            "confidence": 0.9,
            "classification": {"high_risk_text": True},
        }],
    )

    label = task["predictions"][0]["result"][0]["value"]["rectanglelabels"]
    assert label == ["high_risk_text_region"]
    assert "load_capacity" not in label
