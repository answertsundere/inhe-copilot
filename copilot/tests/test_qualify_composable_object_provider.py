from __future__ import annotations

from scripts.qualify_composable_object_provider import build_report


def _box(x: float = 0.1) -> dict:
    return {"x": x, "y": 0.1, "width": 0.5, "height": 0.5, "coordinate_space": "normalized"}


def _record(asset_id: int, attempt: int, object_type: str = "packaging", x: float = 0.1, scope_reason: str = "packaging_text_hint") -> dict:
    return {
        "media_asset_id": asset_id, "attempt": attempt, "media_resolution": {"ok": True},
        "object_result": {"objects": [{"object_label": "primary_visual_subject", "panel_id": "root", "object_type": object_type, "scope_reason": scope_reason, "bbox": _box(x), "latency_ms": 10.0}], "execution_error": "", "schema_error": "", "latency_ms": 10.0},
    }


def _report(records: list[dict]):
    return build_report(provider={"configured": True, "provider_name": "deterministic_primary_subject_proposal"}, records=records, database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True)


def test_report_qualifies_stable_scoped_object_candidates_without_writes():
    records = [record for asset_id in range(1, 11) for record in (_record(asset_id, 1), _record(asset_id, 2))]
    report = _report(records)
    assert report["qualification_gates"]["object_bbox"] is True
    assert report["qualification_gates"]["object_scope_resolution"] is True
    assert report["qualified_for_30_image"] is True
    assert report["formal_kb_state_unchanged"] is True
    assert report["pending_review_candidate_count"] == 0


def test_unscoped_candidates_fail_scope_gate_instead_of_passing_on_geometry_only():
    records = [record for asset_id in range(1, 11) for record in (_record(asset_id, 1, "unknown_object_scope", scope_reason="scope_not_semantically_verified"), _record(asset_id, 2, "unknown_object_scope", scope_reason="scope_not_semantically_verified"))]
    report = _report(records)
    assert report["summary"]["object_scope_resolution_rate"]["rate"] == 0.0
    assert report["qualification_gates"]["object_scope_resolution"] is False
    assert report["qualified_for_30_image"] is False


def test_package_as_product_leakage_blocks_qualification():
    records = [record for asset_id in range(1, 11) for record in (_record(asset_id, 1, "product"), _record(asset_id, 2, "product"))]
    report = _report(records)
    assert report["summary"]["package_product_leakage_count"] == 20
    assert report["qualification_gates"]["no_package_product_leakage"] is False


def test_repeat_bbox_instability_is_measured():
    records = [record for asset_id in range(1, 11) for record in (_record(asset_id, 1, x=0.1), _record(asset_id, 2, x=0.5))]
    report = _report(records)
    assert report["summary"]["repeat_bbox_iou_stability_rate"]["rate"] == 0.0
    assert report["qualified_for_30_image"] is False
