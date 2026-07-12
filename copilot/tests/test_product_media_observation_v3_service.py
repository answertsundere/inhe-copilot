from __future__ import annotations

import hashlib

from app.services.product_media_observation_v3_service import (
    ProductMediaObservationV3Extractor, parse_v3_model_json, v3_model_prompt,
    build_product_understanding_graph,
    select_bound_observations,
)


def _asset():
    return {
        "id": 1, "i_id": "IID-1", "sku_code": "SKU-1", "asset_type": "size_image",
        "status": "approved", "usable_for_agent": 1, "asset_url": "https://example.test/source.png",
        "content_hash": hashlib.sha256(b"image").hexdigest(),
    }


def _bbox(x=10):
    return {"x": x, "y": 10, "width": 100, "height": 100}


def _measurement(scope="product", axis="width", value="80", unit="cm", subject_ref="product-1"):
    return {
        "subject_scope": scope, "subject_ref": subject_ref, "subject_label": "observed object",
        "state_or_mode": "", "parent_subject_ref": "", "observation_type": "labelled_measurement",
        "attribute_key": axis, "measurement_axis": axis, "raw_observation": f"{value}{unit}",
        "value": value, "unit": unit, "evidence_text": f"{value}{unit}",
        "object_bbox": _bbox(), "label_bbox": _bbox(120), "confidence": 0.9,
    }


def _response(*observations):
    return {"schema_version": "product_media_observation_v3", "model_version": "fixture", "observations": list(observations)}


def _extractor(response):
    return ProductMediaObservationV3Extractor(lambda *_args: response)


def _patch_image(monkeypatch):
    monkeypatch.setattr("app.services.product_media_observation_v3_service.resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))


def test_product_measurement_is_bound_to_product_and_axis(monkeypatch):
    _patch_image(monkeypatch)
    result = _extractor(_response(_measurement())).extract_asset(_asset(), expected_product_identity={"i_id": "IID-1"})
    assert result["rejected_evidence"] == []
    item = result["observations"][0]
    assert item["subject_scope"] == "product"
    assert item["measurement_axis"] == "width"
    assert item["direct_answer_allowed"] is False
    assert select_bound_observations(result["observations"], requested_subject_scope="product", requested_measurement_axis="width") == result["observations"]


def test_packaging_and_component_measurements_cannot_be_selected_as_product_dimensions(monkeypatch):
    _patch_image(monkeypatch)
    result = _extractor(_response(_measurement("packaging"), _measurement("component", subject_ref="part-1"))).extract_asset(_asset())
    assert select_bound_observations(result["observations"], requested_subject_scope="product", requested_measurement_axis="width") == []
    assert {warning for item in result["observations"] for warning in item["warning_reasons"]} == {
        "packaging_measurement_not_product_dimension", "component_measurement_not_product_dimension",
    }


def test_measurement_requires_object_and_label_binding(monkeypatch):
    _patch_image(monkeypatch)
    row = _measurement()
    row["label_bbox"] = None
    result = _extractor(_response(row)).extract_asset(_asset())
    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "measurement_target_binding_missing"


def test_visible_text_and_high_risk_content_are_not_v3_facts(monkeypatch):
    _patch_image(monkeypatch)
    visible_text = _measurement()
    visible_text.update({"observation_type": "visible_text", "measurement_axis": "", "value": "", "unit": "", "label_bbox": None})
    risky = _measurement()
    risky.update({"attribute_key": "load_capacity", "raw_observation": "20kg"})
    result = _extractor(_response(visible_text, risky)).extract_asset(_asset())
    assert {item["reason"] for item in result["rejected_evidence"]} == {"visible_text_reference_only", "out_of_scope_high_risk"}


def test_graph_preserves_part_and_measurement_relationships(monkeypatch):
    _patch_image(monkeypatch)
    product = _measurement(subject_ref="product")
    component = _measurement("component", "height", "12", "cm", "drawer")
    component["parent_subject_ref"] = "product"
    result = _extractor(_response(product, component)).extract_asset(_asset())
    graph = build_product_understanding_graph(result["observations"])
    assert {node["subject_ref"] for node in graph["nodes"]} == {"product", "drawer"}
    assert {edge["relation"] for edge in graph["edges"]} == {"part_of", "measured_as"}
    assert graph["can_change_can_send"] is False


def test_selection_does_not_infer_from_unstructured_request(monkeypatch):
    _patch_image(monkeypatch)
    result = _extractor(_response(_measurement())).extract_asset(_asset())
    assert select_bound_observations(result["observations"], requested_subject_scope="", requested_measurement_axis="width") == []


def test_v3_transport_prompt_requires_subject_and_measurement_bindings():
    prompt = v3_model_prompt(max_observations=5)
    assert "subject_scope" in prompt
    assert "object_bbox" in prompt
    assert "label_bbox" in prompt
    assert parse_v3_model_json('```json\n{"schema_version":"product_media_observation_v3","observations":[]}\n```')["observations"] == []
