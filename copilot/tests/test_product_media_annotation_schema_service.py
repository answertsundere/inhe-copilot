from __future__ import annotations

from xml.etree import ElementTree

from app.services.product_media_annotation_schema_service import (
    OBJECT_LABELS,
    PROHIBITED_FACT_LABELS,
    annotation_schema,
    annotation_profile,
    authoring_labels,
    build_label_studio_task,
    canonical_annotation_relation,
    label_studio_config_xml,
    task_authoring_labels,
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

    assert {"product_overall", "packaging", "component", "accessory", "included_item", "display_prop", "label_text_region", "dimension_label_region", "mode_panel", "product_panel", "compliance_document_region"}.issubset(OBJECT_LABELS)
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
    assert task["predictions"][0]["result"][0]["value"]["rectanglelabels"] == ["尺寸标注（数值和线）"]
    assert task["meta"]["current_model_candidates"][0]["observation_eligible"] is False
    assert "raw_payload" not in task["meta"]["current_model_candidates"][0]
    assert "api_key" not in task["meta"]["current_model_candidates"][0]
    assert task["meta"]["used_for_generation"] is False
    assert task["meta"]["can_change_can_send"] is False
    assert "媒体角色：尺寸/规格图" in task["data"]["annotation_context"]
    assert "size_image" not in task["data"]["annotation_context"]


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
    assert label == ["高风险文字"]
    assert "load_capacity" not in label


def test_certificate_media_uses_document_only_authoring_profile():
    task = build_label_studio_task(
        _asset(asset_type="certificate_image"),
        ocr_items=[{
            "text": "80cm",
            "bbox": {"x": 0.1, "y": 0.2, "width": 0.2, "height": 0.1, "coordinate_space": "normalized"},
            "confidence": 0.9,
            "classification": {"dimension_text": True},
        }],
    )

    assert task["data"]["annotation_profile"] == "compliance_document"
    assert task_authoring_labels(task) == {
        "compliance_document_region",
        "label_text_region",
        "high_risk_text_region",
    }
    assert "packaging" not in task_authoring_labels(task)
    assert "不能标为商品事实" in task["data"]["annotation_profile_instruction"]
    assert task["predictions"] == []


def test_task_profiles_use_durable_metadata_and_never_fall_back_to_broad_palette():
    packaging = _asset(asset_type="size_image", scene_tags=["packaging"])
    mode = _asset(asset_type="size_image", scene_tags=["mode"])
    product = _asset(asset_type="size_image", scene_tags=[])

    assert annotation_profile(packaging) == "packaging_dimension"
    assert annotation_profile(mode) == "mode_dimension"
    assert annotation_profile(product) == "product_specification"
    assert annotation_profile(_asset(asset_type="certificate_image")) == "compliance_document"

    packaging_labels = {item["value"] for item in authoring_labels("packaging_dimension")}
    assert packaging_labels == {"包装/纸箱", "图片说明文字", "尺寸标注（数值和线）", "高风险文字"}
    mode_labels = {item["value"] for item in authoring_labels("mode_dimension")}
    assert "包装/纸箱" not in mode_labels
    assert "随附物" not in mode_labels
    assert "展示道具" not in mode_labels
    product_labels = {item["value"] for item in authoring_labels("product_specification")}
    assert "包装/纸箱" not in product_labels
    assert "模式面板" not in product_labels


def test_explicit_annotation_task_type_has_priority_without_using_title_or_sku():
    asset = _asset(
        asset_type="sku_image",
        product_name="标题不参与 profile 决策",
        sku_code="SKU-NOT-A-BRANCH",
        source_raw={"annotation_task_type": "mode_dimension"},
    )

    assert annotation_profile(asset) == "mode_dimension"


def test_label_studio_config_is_chinese_and_uses_only_shared_schema_labels():
    config = label_studio_config_xml()

    assert ElementTree.fromstring(config).tag == "View"
    assert 'value="$authoring_labels"' in config
    assert "<Label value=" not in config
    assert 'name="dimension_attribute"' in config
    assert 'name="dimension_scope"' in config
    assert 'name="image_scope"' in config
    assert 'name="reviewed_visual_summary"' in config
    assert 'name="object_representation"' in config
    assert 'name="dimension_evidence_status"' in config
    assert 'whenTagName="region_label"' in config
    assert 'whenLabelValue="尺寸标注（数值和线）"' in config
    assert "测量对象" in config
    assert canonical_annotation_relation("测量对象") == "dimension_measures_object"
    assert "load_capacity" not in config
