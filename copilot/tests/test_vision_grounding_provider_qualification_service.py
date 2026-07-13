from __future__ import annotations

from app.services.vision_grounding_provider_qualification_service import (
    bbox_iou,
    build_qualification_report,
    is_normalized_bbox,
    normalize_stage_outcomes,
)


def _bbox(x=0.1, y=0.1):
    return {"x": x, "y": y, "width": 0.2, "height": 0.2, "coordinate_space": "normalized"}


def _observation(uid="obs-1", scope="product"):
    return {
        "observation_uid": uid, "subject_scope": scope, "attribute_key": "width", "value": "80", "unit": "cm",
        "object_bbox": _bbox(), "label_bbox": _bbox(0.5, 0.5), "panel_ref": "root", "panel_bbox": _bbox(0, 0),
        "warning_reasons": [], "risk_class": "low", "can_change_can_send": False,
    }


def _record(asset_id=1, observation=None, diagnostics=None):
    return {
        "media_asset_id": asset_id, "media_resolution": {"ok": True, "observed_media_sha256": "a" * 64},
        "observations": [] if observation is None else [observation], "rejected_evidence": [],
        "stage_outcomes": normalize_stage_outcomes(
            provider_name="test", model_name="test-model", media_asset_id=asset_id, image_sha256="a" * 64, latency_ms=10,
            stage_diagnostics=diagnostics or [
                {"stage": "image_classification", "execution_status": "success", "schema_status": "valid"},
                {"stage": "object_localization", "execution_status": "success", "schema_status": "valid"},
                {"stage": "label_localization", "execution_status": "success", "schema_status": "valid"},
                {"stage": "measurement_binding", "execution_status": "success", "schema_status": "valid"},
            ],
        ),
    }


def test_adapter_outcomes_are_sanitized_and_bbox_contract_is_strict():
    outcomes = normalize_stage_outcomes(
        provider_name="local", model_name="qwen", media_asset_id=1, image_sha256="a" * 64, latency_ms=12,
        stage_diagnostics=[{"stage": "object_localization", "execution_status": "error", "schema_status": "invalid", "error_type": "TimeoutError", "reason": "provider_error"}],
    )
    assert outcomes[0]["stage"] == "object"
    assert outcomes[0]["execution_error"] == "TimeoutError"
    assert is_normalized_bbox(_bbox())
    assert not is_normalized_bbox({"x": 0, "y": 0, "width": 2, "height": 1, "coordinate_space": "normalized"})
    assert bbox_iou(_bbox(), _bbox()) == 1.0


def test_timeout_and_schema_errors_are_not_business_rejections():
    record = _record(observation=None, diagnostics=[{"stage": "object_localization", "execution_status": "error", "schema_status": "invalid", "error_type": "TimeoutError"}])
    report = build_qualification_report(provider_name="test", model_name="model", records=[record], database_query_only=True, formal_kb_write_attempt_count=0)
    assert report["records"][0]["rejected_evidence"] == []
    assert report["summary"]["execution_success_rate"]["rate"] == 0.0
    assert not report["qualified_for_30_image"]


def test_leakage_high_risk_and_shadow_invariants_are_reported():
    packaged = _observation(scope="product")
    packaged["warning_reasons"] = ["packaging_measurement_not_product_dimension"]
    risky = _observation(uid="obs-2")
    risky["risk_class"] = "high"
    report = build_qualification_report(
        provider_name="test", model_name="model", records=[_record(observation=packaged), _record(asset_id=2, observation=risky)],
        database_query_only=True, formal_kb_write_attempt_count=0,
    )
    assert report["summary"]["package_product_leakage_count"] == 1
    assert report["summary"]["high_risk_admission_count"] == 1
    assert report["can_change_can_send"] is False
    assert report["summary"]["can_change_can_send_count"] == 0
    assert report["summary"]["formal_kb_write_attempt_count"] == 0


def test_repeatability_is_measured_from_observation_uids_and_boxes():
    report = build_qualification_report(
        provider_name="test", model_name="model", records=[_record(observation=_observation()), _record(observation=_observation())],
        database_query_only=True, formal_kb_write_attempt_count=0,
    )
    assert report["summary"]["repeated_uid_stability_rate"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert report["summary"]["repeated_bbox_iou_stability_rate"] == {"numerator": 2, "denominator": 2, "rate": 1.0}
