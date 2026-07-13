from __future__ import annotations

import json

from scripts.diagnose_product_media_annotation_feasibility import build_report
from scripts.export_product_media_annotation_tasks import build_tasks


class _Asset:
    def __init__(self, **values):
        self.__dict__.update(values)

    def get_source_raw(self):
        return self.source_raw

    def get_scene_tags(self):
        return self.scene_tags


def _asset(**overrides):
    values = {
        "id": 8,
        "asset_url": "https://media.example.test/image.png",
        "product_id": 1,
        "i_id": "IID-1",
        "sku_code": "SKU-1",
        "asset_type": "size_image",
        "scene_tags": ["multi_panel"],
        "source_raw": {"ocr_items": []},
    }
    values.update(overrides)
    return _Asset(**values)


def test_export_uses_media_role_not_product_or_image_names():
    first = _asset(id=9, asset_type="sku_image", product_name="anything", asset_title="unrelated-name.png")
    second = _asset(id=8, asset_type="size_image", product_name="different", asset_title="another-name.png")

    tasks = build_tasks([first, second])

    assert [task["meta"]["media_asset_id"] for task in tasks] == ["8", "9"]
    assert tasks[0]["meta"]["suggested_task_type"] == "尺寸标注与对象范围"
    assert tasks[0]["meta"]["can_change_can_send"] is False
    assert json.loads(json.dumps(tasks, ensure_ascii=False))[0]["data"]["image"]


def test_export_excludes_video_roles_from_image_annotation_tasks():
    tasks = build_tasks([_asset(id=1, asset_type="install_video"), _asset(id=2, asset_type="size_image")])

    assert [task["meta"]["media_asset_id"] for task in tasks] == ["2"]


def test_feasibility_report_is_metadata_only_and_does_not_claim_object_facts():
    report = build_report([
        _asset(asset_type="size_image", scene_tags=["multi_panel"]),
        _asset(id=9, asset_type="accessory_image", scene_tags=["packaging", "mode"]),
    ])

    assert report["total_media_count"] == 2
    assert report["dimension_image_count"] == 1
    assert report["packaging_image_count"] == 1
    assert report["mode_image_count"] == 1
    assert report["multi_panel_image_count"] == 1
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
