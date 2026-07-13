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


def test_valid_manual_annotation_requires_dimension_to_be_related_to_its_object():
    task = _task()
    results = [
        _rectangle("product", "product_overall", 5, 5, 70, 80),
        _rectangle("mode", "mode_panel", 0, 0, 100, 50),
        _rectangle("dimension", "dimension_label_region", 80, 20, 10, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "product", "labels": ["测量对象"]},
        {"type": "relation", "from_id": "product", "to_id": "mode", "labels": ["可见于面板"]},
    ]

    report = validate_annotation_tasks([_completed(task, results)], [task])

    assert report["passed_task_count"] == 1
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0


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
    assert "relation_scope_invalid" in errors


def test_validator_requires_dimension_subject_and_panel_scope_when_panels_exist():
    task = _task()
    results = [
        _rectangle("product", "product_overall", 5, 5, 70, 80),
        _rectangle("mode", "mode_panel", 0, 0, 100, 50),
        _rectangle("dimension", "dimension_label_region", 80, 20, 10, 10),
        {"type": "relation", "from_id": "dimension", "to_id": "product", "labels": ["测量对象"]},
    ]

    report = validate_annotation_tasks([_completed(task, results)], [task])

    assert "dimension_panel_scope_missing" in report["tasks"][0]["errors"]


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
