from __future__ import annotations

from scripts.qualify_semantic_object_provider import _summary_aliases
from scripts.qualify_composable_object_provider import build_report


def _record(asset_id: int, attempt: int, object_type: str = "product") -> dict:
    return {
        "media_asset_id": asset_id, "attempt": attempt, "media_resolution": {"ok": True},
        "object_result": {
            "objects": [{
                "object_label": "main object", "panel_id": "root", "object_type": object_type,
                "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5, "coordinate_space": "normalized"},
                "latency_ms": 10.0,
            }], "execution_error": "", "schema_error": "", "latency_ms": 10.0,
        },
    }


def test_semantic_qualification_exposes_required_metric_aliases():
    records = [record for asset_id in range(1, 11) for record in (_record(asset_id, 1), _record(asset_id, 2))]
    report = build_report(
        provider={"configured": True, "provider_name": "groundingdino"}, records=records,
        database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True,
    )
    _summary_aliases(report)
    assert report["summary"]["execution_success_rate"]["rate"] == 1.0
    assert report["summary"]["object_semantic_scope_resolution_rate"]["rate"] == 1.0
    assert report["summary"]["formal_kb_write_attempt_count"] == 0
    assert report["summary"]["can_change_can_send_count"] == 0


def test_semantic_qualification_rejects_unresolved_object_scope():
    records = [record for asset_id in range(1, 11) for record in (_record(asset_id, 1, "unknown"), _record(asset_id, 2, "unknown"))]
    report = build_report(
        provider={"configured": True, "provider_name": "groundingdino"}, records=records,
        database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True,
    )
    _summary_aliases(report)
    assert report["summary"]["object_semantic_scope_resolution_rate"]["rate"] == 0.0
    assert report["qualified_for_30_image"] is False


def test_empty_provider_output_is_not_misreported_as_repeatable_object_type():
    records = [
        {"media_asset_id": asset_id, "attempt": attempt, "media_resolution": {"ok": True}, "object_result": {"objects": [], "execution_error": "provider_not_configured", "schema_error": "", "latency_ms": 0.0}}
        for asset_id in range(1, 11)
        for attempt in (1, 2)
    ]
    report = build_report(
        provider={"configured": False, "provider_name": "auto"}, records=records,
        database_query_only=True, formal_kb_write_attempt_count=0, formal_kb_state_unchanged=True,
    )
    assert report["summary"]["repeatable_object_asset_count"] == 0
    assert report["summary"]["repeat_object_type_stability_rate"]["rate"] == 0.0
