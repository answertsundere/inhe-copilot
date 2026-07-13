from __future__ import annotations

from app.services.composable_vision_grounding_service import build_geometry_candidates, normalize_object_items, normalize_ocr_items, verify_candidates


def _box(x, y, width, height):
    return {"x": x, "y": y, "width": width, "height": height, "coordinate_space": "normalized"}


def _panel(ref="left", box=None):
    return {"panel_ref": ref, "panel_bbox": box or _box(0, 0, 0.5, 1)}


def _items(*, scope="product", mode=""):
    labels = normalize_ocr_items([{"text": "80cm", "bbox": _box(0.3, 0.2, 0.1, 0.05), "confidence": 0.9, "source": "test"}], image_size=None)
    objects = normalize_object_items([{"subject_scope": scope, "object_type": scope, "bbox": _box(0.1, 0.1, 0.25, 0.4), "confidence": 0.9, "source": "test", "mode_or_state": mode}], image_size=None)
    return labels, objects


def _accept(candidate, attribute_key="width"):
    return {"candidate_id": candidate["candidate_id"], "accept": True, "attribute_key": attribute_key, "source": "fake_verifier"}


def test_ocr_and_object_bboxes_normalize_then_bind_within_one_panel():
    labels, objects = _items()
    candidates = build_geometry_candidates(ocr_items=labels, object_items=objects, panels=[_panel()])
    assert len(candidates["candidates"]) == 1
    verified = verify_candidates(candidates["candidates"], _accept)
    assert verified["observations"][0]["relation"] == "labelled_by"
    assert verified["observations"][0]["can_change_can_send"] is False


def test_cross_panel_and_ambiguous_bindings_fail_closed():
    labels, objects = _items()
    right_object = dict(objects[0]); right_object["bbox"] = _box(0.6, 0.1, 0.25, 0.4)
    result = build_geometry_candidates(ocr_items=labels, object_items=[right_object], panels=[_panel(), _panel("right", _box(0.5, 0, 0.5, 1))])
    assert result["candidates"] == []
    assert result["rejected"][0]["reason"] == "no_same_panel_object_candidate"


def test_packaging_component_and_mode_boundaries_are_preserved():
    labels, packaging = _items(scope="packaging")
    candidate = build_geometry_candidates(ocr_items=labels, object_items=packaging, panels=[_panel()])["candidates"]
    package_observation = verify_candidates(candidate, _accept)["observations"][0]
    assert package_observation["subject_scope"] == "packaging"
    labels, component = _items(scope="component", mode="folded")
    candidate = build_geometry_candidates(ocr_items=labels, object_items=component, panels=[_panel()])["candidates"]
    rejected = verify_candidates(candidate, lambda item: _accept(item, "overall_dimension"))
    assert rejected["observations"] == []
    assert rejected["rejected"][0]["reason"] == "component_overall_scope_rejected"
    mode_specific = verify_candidates(candidate, lambda item: _accept(item, "width"))["observations"][0]
    assert mode_specific["warning_reasons"] == ["mode_specific_not_global"]


def test_high_risk_and_verifier_schema_errors_do_not_become_observations():
    labels = normalize_ocr_items([{"text": "load_capacity 20kg", "bbox": _box(0.3, 0.2, 0.1, 0.05), "confidence": 0.9}], image_size=None)
    _, objects = _items()
    rejected = build_geometry_candidates(ocr_items=labels, object_items=objects, panels=[_panel()])
    assert rejected["rejected"][0]["reason"] == "out_of_scope_high_risk"
    labels, objects = _items()
    candidates = build_geometry_candidates(ocr_items=labels, object_items=objects, panels=[_panel()])["candidates"]
    invalid = verify_candidates(candidates, lambda _item: {"accept": True})
    assert invalid["observations"] == []
    assert invalid["rejected"][0]["reason"] == "verifier_schema_error"
