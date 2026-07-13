from __future__ import annotations

from scripts.qualify_composable_ocr_provider import build_report


def _item(text: str, x: float = 0.1):
    return {
        "text": text,
        "bbox": {"x": x, "y": 0.1, "width": 0.2, "height": 0.1, "coordinate_space": "normalized"},
        "classification": {"dimension_text": text.endswith("cm"), "mode_text": False, "packaging_text": False, "high_risk_text": False},
    }


def _record(asset_id: int, attempt: int, items: list[dict]):
    return {"media_asset_id": asset_id, "attempt": attempt, "media_resolution": {"ok": True}, "ocr_result": {"items": items, "execution_error": "", "schema_error": "", "latency_ms": 10.0}}


def test_report_tracks_repeatability_and_never_admits_observations():
    records = []
    for asset_id in range(1, 11):
        records.extend([_record(asset_id, 1, [_item("80cm")]), _record(asset_id, 2, [_item("80cm")])])
    report = build_report(provider={"configured": True, "provider_name": "windows_ocr"}, records=records, database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True)
    assert report["qualification_gates"]["text_bbox"] is True
    assert report["summary"]["repeat_text_stability_rate"]["rate"] == 1.0
    assert report["summary"]["high_risk_observation_admission_count"] == 0
    assert report["pending_review_candidate_count"] == 0
    assert report["can_change_can_send"] is False


def test_repeat_bbox_instability_is_measured_without_creating_observations():
    records = []
    for asset_id in range(1, 11):
        records.extend([_record(asset_id, 1, [_item("80cm", 0.1)]), _record(asset_id, 2, [_item("80cm", 0.6)])])
    report = build_report(provider={"configured": True, "provider_name": "windows_ocr"}, records=records, database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True)
    assert report["summary"]["repeat_bbox_iou_stability_rate"]["rate"] == 0.0
    assert report["qualified_for_30_image"] is False


def test_expanded_scan_is_not_misreported_as_a_new_10_image_gate():
    records = []
    for asset_id in range(1, 31):
        records.extend([_record(asset_id, 1, [_item("80cm")]), _record(asset_id, 2, [_item("80cm")])])
    report = build_report(provider={"configured": True, "provider_name": "windows_ocr"}, records=records, database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True, qualification_run=False)
    assert report["scan_mode"] == "expanded_ocr_only_shadow_scan"
    assert report["qualified_for_30_image"] is None
