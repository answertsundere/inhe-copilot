from types import SimpleNamespace


def test_v3_summary_counts_conditional_panel_repair_and_image_resolution():
    from scripts.extract_product_media_observations_v3 import _summary

    report = _summary([
        {
            "media_resolution": {"ok": True, "source_kind": "original_path"},
            "observations": [{"observation_type": "labelled_measurement", "object_bbox": {"x": 0}, "label_bbox": {"x": 0}, "panel_ref": "left", "panel_bbox": {"x": 0}, "subject_scope": "product", "can_change_can_send": False}],
            "rejected_evidence": [],
            "stage_diagnostics": [
                {"stage": "image_classification", "execution_status": "success", "schema_status": "valid", "result_count": 2},
                {"stage": "panel_bbox_repair", "execution_status": "success", "schema_status": "valid"},
                {"stage": "object_localization", "execution_status": "success", "schema_status": "valid"},
                {"stage": "label_localization", "execution_status": "success", "schema_status": "valid"},
                {"stage": "measurement_binding", "execution_status": "success", "schema_status": "valid"},
            ],
        },
    ], SimpleNamespace(enabled=True, write_attempt_count=0))

    assert report["image_read_success_rate"]["rate"] == 1.0
    assert report["execution_success_rate"] == {"numerator": 5, "denominator": 5, "rate": 1.0}
    assert report["panel_bbox_repair_attempt_count"] == 1
    assert report["panel_bbox_coverage_rate"]["rate"] == 1.0
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
