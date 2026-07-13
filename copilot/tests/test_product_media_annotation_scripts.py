from __future__ import annotations

import json

import scripts.export_product_media_annotation_tasks as export_tasks

from scripts.diagnose_product_media_annotation_feasibility import build_report
from scripts.export_product_media_annotation_tasks import build_pilot_tasks, build_tasks, select_balanced_pilot_assets


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


def test_pilot_selection_round_robins_metadata_buckets_without_names():
    assets = [
        _asset(id=1, asset_type="size_image", scene_tags=[]),
        _asset(id=2, asset_type="size_image", scene_tags=[]),
        _asset(id=3, asset_type="pack_guide_image", scene_tags=[]),
        _asset(id=4, asset_type="sku_image", scene_tags=["packaging"]),
    ]

    selected = select_balanced_pilot_assets(assets, candidate_scan_limit=3)

    assert {bucket for _asset_item, bucket in selected} == {"pack_guide_image", "size_image", "structured_layout"}


def test_pilot_tasks_require_readable_bytes_and_keep_media_local_to_external_runtime(tmp_path, monkeypatch):
    asset = _asset(status="approved", usable_for_agent=True, product_name="name-must-not-drive-selection")
    monkeypatch.setattr(export_tasks, "_image_metadata", lambda _asset, timeout_seconds: ({
        "data": b"image-bytes", "extension": ".png", "observed_media_sha256": "a" * 64,
        "source_image_size": {"width": 100, "height": 50}, "source_kind": "fixture",
    }, ""))

    report = build_pilot_tasks([asset], limit=1, candidate_scan_limit=1, timeout_seconds=1, materialize_dir=tmp_path)

    task = report["tasks"][0]
    assert report["task_count"] == 1
    assert task["meta"]["source_image_sha256"] == "a" * 64
    assert task["data"]["image"] == "/data/local-files/?d=media/" + "a" * 64 + ".png"
    assert (tmp_path / ("a" * 64 + ".png")).read_bytes() == b"image-bytes"
