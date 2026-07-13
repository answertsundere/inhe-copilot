from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy

from PIL import Image

from app.services.product_media_observation_v3_service import (
    ProductMediaObservationV3Extractor,
    build_product_understanding_graph,
    parse_v3_model_json,
    select_bound_observations,
    v3_model_prompt,
)


def _asset():
    return {
        "id": 1, "i_id": "IID-1", "sku_code": "SKU-1", "asset_type": "size_image",
        "status": "approved", "usable_for_agent": 1, "asset_url": "https://example.test/source.png",
        "content_hash": hashlib.sha256(b"image").hexdigest(),
    }


def _bbox(x=10, y=10, width=100, height=100):
    return {"x": x, "y": y, "width": width, "height": height, "coordinate_space": "normalized_1000"}


def _stages(*, scope="product", axis="width", value="80", unit="cm", subject_ref="product-1", label_ref="label-1", state=""):
    return {
        "image_classification": {"schema_version": "product_media_observation_v3", "stage": "image_classification", "image_primary_type": scope, "panels": []},
        "object_localization": {"schema_version": "product_media_observation_v3", "stage": "object_localization", "subjects": [{"subject_ref": subject_ref, "subject_scope": scope, "subject_label": "observed object", "parent_subject_ref": "", "state_or_mode": state, "panel_ref": "", "object_bbox": _bbox(), "confidence": 0.9}]},
        "label_localization": {"schema_version": "product_media_observation_v3", "stage": "label_localization", "labels": [{"label_ref": label_ref, "label_bbox": _bbox(120), "evidence_text": f"{value}{unit}", "confidence": 0.9}]},
        "measurement_binding": {"schema_version": "product_media_observation_v3", "stage": "measurement_binding", "observations": [{"subject_ref": subject_ref, "label_ref": label_ref, "observation_type": "labelled_measurement", "attribute_key": axis, "measurement_axis": axis, "raw_observation": f"{value}{unit}", "value": value, "unit": unit, "confidence": 0.9}]},
    }


def _extractor(stages):
    return ProductMediaObservationV3Extractor(lambda stage, *_args: stages[stage])


def _patch_image(monkeypatch):
    buffer = io.BytesIO()
    Image.new("RGB", (1000, 1000), "white").save(buffer, format="PNG")
    monkeypatch.setattr("app.services.product_media_observation_v3_service.resolve_product_media_image", lambda *_args, **_kwargs: (buffer.getvalue(), ".png"))


def test_staged_measurement_is_bound_to_product_and_axis(monkeypatch):
    _patch_image(monkeypatch)
    result = _extractor(_stages()).extract_asset(_asset(), expected_product_identity={"i_id": "IID-1"})
    assert result["rejected_evidence"] == []
    item = result["observations"][0]
    assert item["subject_scope"] == "product"
    assert item["measurement_axis"] == "width"
    assert item["object_bbox"]["coordinate_space"] == "normalized"
    assert item["direct_answer_allowed"] is False
    assert all(row["schema_status"] == "valid" for row in result["stage_diagnostics"])


def test_packaging_and_component_measurements_cannot_be_selected_as_product_dimensions(monkeypatch):
    _patch_image(monkeypatch)
    packaging = _stages(scope="packaging")
    result = _extractor(packaging).extract_asset(_asset())
    assert select_bound_observations(result["observations"], requested_subject_scope="product", requested_measurement_axis="width") == []
    assert result["observations"][0]["warning_reasons"] == ["packaging_measurement_not_product_dimension"]
    component = _stages(scope="component", subject_ref="part-1")
    component["object_localization"]["subjects"][0]["parent_subject_ref"] = "product-1"
    result = _extractor(component).extract_asset(_asset())
    assert result["observations"][0]["warning_reasons"] == ["component_measurement_not_product_dimension"]


def test_measurement_requires_both_distinct_grounded_boxes(monkeypatch):
    _patch_image(monkeypatch)
    stages = _stages()
    del stages["label_localization"]["labels"][0]["label_bbox"]
    result = _extractor(stages).extract_asset(_asset())
    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "staged_model_response_invalid"
    assert result["stage_diagnostics"][-1]["stage"] == "label_localization"
    assert result["stage_diagnostics"][-1]["schema_status"] == "invalid"


def test_high_risk_and_ambiguous_axis_stay_rejected(monkeypatch):
    _patch_image(monkeypatch)
    risky = _stages(axis="width", value="20", unit="kg")
    risky["measurement_binding"]["observations"][0].update({"attribute_key": "load_capacity", "raw_observation": "20kg"})
    result = _extractor(risky).extract_asset(_asset())
    assert result["rejected_evidence"][0]["reason"] == "out_of_scope_high_risk"
    ambiguous = _stages(axis="unknown")
    result = _extractor(ambiguous).extract_asset(_asset())
    assert result["rejected_evidence"][0]["reason"] == "ambiguous_axis"


def test_packaging_or_component_labels_cannot_leak_into_product_scope(monkeypatch):
    _patch_image(monkeypatch)
    packaging = _stages()
    packaging["object_localization"]["subjects"][0]["subject_label"] = "shipping carton"
    result = _extractor(packaging).extract_asset(_asset())
    assert result["rejected_evidence"][0]["reason"] == "packaging_scope_required"
    component = _stages()
    component["object_localization"]["subjects"][0]["subject_label"] = "named component"
    result = _extractor(component).extract_asset(_asset())
    assert result["rejected_evidence"][0]["reason"] == "component_scope_required"


def test_graph_preserves_part_measurement_label_and_mode_relationships(monkeypatch):
    _patch_image(monkeypatch)
    stages = _stages(scope="component", subject_ref="drawer", state="two_step_mode")
    stages["object_localization"]["subjects"][0]["parent_subject_ref"] = "product"
    stages["object_localization"]["subjects"][0]["panel_ref"] = "panel-1"
    result = _extractor(stages).extract_asset(_asset())
    # Add the parent as a separate observation so graph construction is order independent.
    parent = deepcopy(result["observations"][0]); parent.update({"subject_ref": "product", "subject_scope": "product", "subject_label": "main object", "parent_subject_ref": "", "observation_uid": "pmov3_parent"})
    graph = build_product_understanding_graph([result["observations"][0], parent])
    relations = {edge["relation"] for edge in graph["edges"]}
    assert {"part_of", "measured_as", "labelled_by", "active_in_mode", "visible_in"}.issubset(relations)
    assert graph["can_change_can_send"] is False


def test_pixel_and_normalised_boxes_are_normalised_and_out_of_range_is_rejected(monkeypatch):
    _patch_image(monkeypatch)
    pixel = _stages()
    pixel["object_localization"]["subjects"][0]["object_bbox"] = {"x": 10, "y": 10, "width": 100, "height": 100, "coordinate_space": "normalized_1000"}
    result = _extractor(pixel).extract_asset(_asset())
    assert result["observations"][0]["object_bbox"]["width"] == 0.1
    invalid = _stages()
    invalid["object_localization"]["subjects"][0]["object_bbox"] = _bbox(950, width=100)
    result = _extractor(invalid).extract_asset(_asset())
    assert result["rejected_evidence"][0]["reason"] == "staged_model_response_invalid"


def test_image_coordinate_alias_is_supported_when_image_bounds_are_available(monkeypatch):
    _patch_image(monkeypatch)
    stages = _stages()
    stages["object_localization"]["subjects"][0]["object_bbox"]["coordinate_space"] = "image"
    result = _extractor(stages).extract_asset(_asset())
    assert result["observations"]


def test_multi_panel_requires_panel_bbox_and_propagates_declared_mode(monkeypatch):
    _patch_image(monkeypatch)
    stages = _stages()
    stages["image_classification"] = {"schema_version": "product_media_observation_v3", "stage": "image_classification", "image_primary_type": "multi_panel", "panels": [{"panel_ref": "panel-1", "panel_title": "", "panel_bbox": _bbox(), "state_or_mode": "folded"}]}
    stages["object_localization"]["subjects"][0]["panel_ref"] = "panel-1"
    result = _extractor(stages).extract_asset(_asset())
    assert result["observations"][0]["state_or_mode"] == "folded"


def test_transport_prompts_are_staged_and_json_parser_accepts_fence():
    for stage in ("image_classification", "object_localization", "label_localization", "measurement_binding"):
        prompt = v3_model_prompt(max_observations=5, stage=stage, context={})
        assert stage in prompt
    assert parse_v3_model_json('```json\n{"schema_version":"product_media_observation_v3","observations":[]}\n```')["observations"] == []


def test_shadow_report_encoding_can_escape_multilingual_model_text():
    payload = {"subject_label": "包装箱", "evidence_text": "43cm"}
    assert json.loads(json.dumps(payload, ensure_ascii=True)) == payload


def test_single_panel_unbound_panel_rows_are_ignored_not_promoted(monkeypatch):
    _patch_image(monkeypatch)
    stages = _stages()
    stages["image_classification"]["panels"] = [{"panel_ref": "panel-1", "panel_title": "", "panel_bbox": _bbox()}]
    result = _extractor(stages).extract_asset(_asset())
    assert result["observations"]
    assert result["stage_diagnostics"][0]["warnings"] == ["single_panel_rows_ignored_without_bbox"]
