from __future__ import annotations

from copy import deepcopy

from app.services.product_media_annotation_schema_service import build_label_studio_task, label_studio_display_label
from scripts.validate_product_media_annotations import validate_annotation_tasks


def _task():
    return build_label_studio_task(
        {
            "id": 7,
            "asset_url": "https://media.example.test/spec.png",
            "product_id": 11,
            "i_id": "IID-TEST",
            "sku_code": "SKU-TEST",
            "product_name": "测试商品",
            "source": "fixture",
            "asset_type": "size_image",
        },
        image_details={"observed_media_sha256": "a" * 64, "source_image_size": {"width": 1000, "height": 800}},
    )


def _rectangle(region_id: str, label: str, x: float, y: float, width: float, height: float):
    return {
        "id": region_id,
        "type": "rectanglelabels",
        "value": {"x": x, "y": y, "width": width, "height": height, "rectanglelabels": [label_studio_display_label(label)]},
    }


def _completed(task, results):
    exported = deepcopy(task)
    exported["annotations"] = [{"completed_by": 9, "created_at": "2026-07-13T10:00:00Z", "updated_at": "2026-07-13T10:01:00Z", "result": results}]
    return exported


def _choice(name: str, value: str, region_id: str = ""):
    result = {"type": "choices", "from_name": name, "value": {"choices": [value]}}
    if region_id:
        result["id"] = region_id
    return result


def _text_value(name: str, value: str, region_id: str = ""):
    result = {"type": "textarea", "from_name": name, "value": {"text": [value]}}
    if region_id:
        result["id"] = region_id
    return result


def _image_context(scope: str = "商品"):
    return [
        _choice("image_scope", scope),
        _text_value("reviewed_visual_summary", "图片展示商品结构和可见尺寸标注"),
    ]


def test_valid_manual_annotation_requires_dimension_to_be_related_to_its_object():
    task = _task()
    results = [
        _rectangle("product", "product_overall", 5, 5, 70, 80),
        _rectangle("dimension", "dimension_label_region", 80, 20, 10, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "product", "labels": ["测量对象"]},
        _choice("object_representation", "实际可见对象", "product"),
        _choice("dimension_attribute", "宽度", "dimension"),
        _choice("dimension_scope", "商品整体", "dimension"),
        _choice("dimension_evidence_status", "仅图片可见", "dimension"),
        _text_value("dimension_visible_value", "80cm", "dimension"),
        _text_value("dimension_unit", "cm", "dimension"),
        *_image_context(),
    ]

    report = validate_annotation_tasks([_completed(task, results)], [task])

    assert report["passed_task_count"] == 1
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
    description = report["tasks"][0]["structured_visual_description"]
    assert description["product_context"]["product_identity"]["i_id"] == "IID-TEST"
    assert description["objects"][0]["is_actual_product_object"] is True
    assert description["dimensions"][0]["measured_object_id"] == "product"
    assert description["dimensions"][0]["provenance"]["bbox"] == (80.0, 20.0, 10.0, 10.0)


def test_validator_rejects_scope_leakage_unknown_labels_out_of_bounds_and_hash_mismatch():
    task = _task()
    exported = _completed(task, [
        _rectangle("packaging", "packaging", 5, 5, 70, 80),
        _rectangle("product", "product_overall", 10, 10, 70, 70),
        _rectangle("bad", "product_overall", 90, 90, 20, 20),
        {"id": "unknown", "type": "rectanglelabels", "value": {"x": 1, "y": 1, "width": 10, "height": 10, "rectanglelabels": ["不存在标签"]}},
        {"type": "relation", "from_id": "packaging", "to_id": "product", "labels": ["属于"]},
    ])
    exported["meta"]["source_image_sha256"] = "b" * 64

    report = validate_annotation_tasks([exported], [task])

    errors = report["tasks"][0]["errors"]
    assert "source_image_sha256_mismatch" in errors
    assert "bbox_invalid_or_out_of_bounds" in errors
    assert "unknown_label" in errors
    assert "task_profile_label_not_allowed" in errors
    assert "relation_endpoint_missing" in errors


def test_validator_requires_dimension_subject_and_panel_scope_when_panels_exist():
    task = build_label_studio_task(
        {
            "id": 8,
            "asset_url": "https://media.example.test/mode-panel.png",
            "asset_type": "size_image",
            "scene_tags": ["mode"],
        },
        image_details={"observed_media_sha256": "e" * 64},
    )
    results = [
        _rectangle("product", "product_overall", 5, 5, 70, 80),
        _rectangle("mode", "mode_panel", 0, 0, 100, 50),
        _rectangle("dimension", "dimension_label_region", 80, 20, 10, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "product", "labels": ["测量对象"]},
    ]

    report = validate_annotation_tasks([_completed(task, results)], [task])

    assert "dimension_panel_scope_missing" in report["tasks"][0]["errors"]


def test_validator_rejects_packaging_label_in_certificate_task_profile():
    task = build_label_studio_task(
        {
            "id": 9,
            "asset_url": "https://media.example.test/certificate.png",
            "asset_type": "certificate_image",
        }
    )
    exported = _completed(task, [_rectangle("packaging", "packaging", 5, 5, 70, 80)])

    report = validate_annotation_tasks([exported], [task])

    assert "task_profile_label_not_allowed" in report["tasks"][0]["errors"]


def test_packaging_profile_rejects_printed_product_instance_and_non_packaging_scope():
    task = build_label_studio_task(
        {
            "id": 10,
            "asset_url": "https://media.example.test/package.png",
            "asset_type": "size_image",
            "scene_tags": ["packaging"],
        },
        image_details={"observed_media_sha256": "c" * 64},
    )
    exported = _completed(task, [
        _rectangle("product-print", "product_overall", 10, 10, 30, 30),
        _rectangle("box", "packaging", 5, 5, 80, 80),
        _rectangle("dimension", "dimension_label_region", 70, 70, 15, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "box", "labels": ["测量对象"]},
        _choice("dimension_attribute", "高度", "dimension"),
        _choice("dimension_scope", "商品整体", "dimension"),
        _choice("dimension_evidence_status", "仅图片可见", "dimension"),
        _text_value("dimension_visible_value", "71cm", "dimension"),
        _text_value("dimension_unit", "cm", "dimension"),
        *_image_context("包装/纸箱"),
    ])

    report = validate_annotation_tasks([exported], [task])
    errors = report["tasks"][0]["errors"]
    assert "task_profile_label_not_allowed" in errors
    assert "dimension_scope_object_mismatch" in errors
    assert "packaging_dimension_scope_invalid" in errors


def test_mode_profile_rejects_packaging_and_requires_mode_specific_relation():
    task = build_label_studio_task(
        {
            "id": 11,
            "asset_url": "https://media.example.test/mode.png",
            "asset_type": "size_image",
            "scene_tags": ["mode"],
        },
        image_details={"observed_media_sha256": "d" * 64},
    )
    exported = _completed(task, [
        _rectangle("packaging", "packaging", 1, 1, 20, 20),
        _rectangle("mode", "mode_panel", 1, 1, 90, 90),
        _rectangle("product", "product_overall", 10, 10, 60, 60),
        _rectangle("dimension", "dimension_label_region", 70, 60, 15, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "product", "labels": ["测量对象"]},
        {"type": "relation", "from_id": "product", "to_id": "mode", "labels": ["可见于面板"]},
        _choice("object_representation", "实际可见对象", "product"),
        _choice("dimension_attribute", "宽度", "dimension"),
        _choice("dimension_scope", "当前模式专属", "dimension"),
        _choice("dimension_evidence_status", "仅图片可见", "dimension"),
        _text_value("dimension_visible_value", "27cm", "dimension"),
        _text_value("dimension_unit", "cm", "dimension"),
        _text_value("mode_or_state", "二层模式", "mode"),
        *_image_context(),
    ])

    report = validate_annotation_tasks([exported], [task])
    errors = report["tasks"][0]["errors"]
    assert "task_profile_label_not_allowed" in errors
    assert "mode_specific_relation_missing" in errors


def test_product_specification_requires_age_and_safety_copy_to_be_high_risk_text():
    task = _task()
    exported = _completed(task, [
        _rectangle("claim", "label_text_region", 5, 5, 40, 10),
        _text_value("label_visible_text", "适用年龄 3 岁以上，安全无毒", "claim"),
        *_image_context(),
    ])

    report = validate_annotation_tasks([exported], [task])
    assert "high_risk_text_must_use_high_risk_region" in report["tasks"][0]["errors"]


def test_printed_representation_cannot_be_confirmed_as_product_instance():
    task = _task()
    exported = _completed(task, [
        _rectangle("product", "product_overall", 5, 5, 70, 80),
        _choice("object_representation", "印刷或屏幕中的图像", "product"),
        *_image_context(),
    ])

    report = validate_annotation_tasks([exported], [task])
    description = report["tasks"][0]["structured_visual_description"]
    assert "product_instance_not_confirmed_actual" in report["tasks"][0]["errors"]
    assert description["objects"][0]["is_printed_representation"] is True
    assert description["objects"][0]["is_actual_product_object"] is False


def test_component_dimension_cannot_be_exported_as_product_overall_dimension():
    task = _task()
    exported = _completed(task, [
        _rectangle("component", "component", 10, 10, 50, 50),
        _rectangle("dimension", "dimension_label_region", 65, 40, 20, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "component", "labels": ["测量对象"]},
        _choice("dimension_attribute", "厚度", "dimension"),
        _choice("dimension_scope", "商品整体", "dimension"),
        _choice("dimension_evidence_status", "待进一步审核", "dimension"),
        _text_value("dimension_visible_value", "3.5cm", "dimension"),
        _text_value("dimension_unit", "cm", "dimension"),
        *_image_context(),
    ])

    report = validate_annotation_tasks([exported], [task])
    assert "dimension_scope_object_mismatch" in report["tasks"][0]["errors"]


def test_free_description_cannot_add_safety_or_suitability_conclusions():
    task = _task()
    exported = _completed(task, [
        _choice("image_scope", "商品"),
        _text_value("reviewed_visual_summary", "这款适合儿童，安全可靠"),
    ])

    report = validate_annotation_tasks([exported], [task])
    assert "reviewed_visual_summary_contains_unsupported_claim" in report["tasks"][0]["errors"]


def test_validation_does_not_mutate_existing_human_annotation():
    task = _task()
    exported = _completed(task, [*_image_context()])
    original = deepcopy(exported)

    validate_annotation_tasks([exported], [task])

    assert exported == original


def test_predictions_are_not_manual_annotations_and_duplicates_fail_quality_gate():
    task = _task()
    missing = validate_annotation_tasks([task], [task])
    assert missing["all_tasks_have_manual_annotations"] is False
    assert "manual_annotation_missing" in missing["tasks"][0]["errors"]

    duplicated = _completed(task, [
        _rectangle("product-1", "product_overall", 5, 5, 70, 80),
        _rectangle("product-2", "product_overall", 5, 5, 70, 80),
    ])
    report = validate_annotation_tasks([duplicated, duplicated], [task])
    assert report["failed_task_count"] == 2
    assert "duplicate_task_uid" in report["error_counts"]
    assert "duplicate_region" in report["error_counts"]
