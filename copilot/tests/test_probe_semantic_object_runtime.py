from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import probe_semantic_object_runtime as script


def _provider() -> dict:
    return {"configured": True, "provider_name": "groundingdino", "model_name": "GroundingDINO", "runtime_name": "PyTorch"}


def test_probe_queries_must_stay_in_generic_category_vocabulary():
    assert script.parse_generic_queries("product, packaging, carton, screw") == ("product", "packaging", "carton", "screw")
    with pytest.raises(ValueError, match="generic_category"):
        script.parse_generic_queries("specific product name")


def test_probe_returns_sanitized_not_configured_diagnostic(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "preferred_semantic_object_provider", lambda **_kwargs: {
        "configured": False, "provider_name": "groundingdino", "missing_requirements": ["torch", "COPILOT_GROUNDINGDINO_CHECKPOINT"],
    })
    report = script.run_probe(provider_name="groundingdino", image_path=tmp_path / "private.png", queries=("product",))
    assert report["execution_success"] is False
    assert report["error_type"] == "provider_not_configured"
    assert str(tmp_path) not in report["error_message_sanitized"]
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send"] is False


def test_probe_normalizes_provider_output_and_uses_selected_generic_queries(monkeypatch, tmp_path):
    image = tmp_path / "probe.png"
    image.write_bytes(b"probe-image")
    monkeypatch.setattr(script, "preferred_semantic_object_provider", lambda **_kwargs: _provider())
    seen: dict = {}

    def infer(_bytes, queries):
        seen.update(queries)
        return [{"object_type": "product", "object_label": "main object", "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5, "coordinate_space": "normalized"}, "confidence": 0.9}]

    report = script.run_probe(provider_name="groundingdino", image_path=image, queries=("product", "accessory"), infer=infer)
    assert report["execution_success"] is True
    assert report["normalized_bbox_count"] == 1
    assert seen == {"probe": ("product", "accessory")}
    assert json.loads(json.dumps(report))["labels"] == ["main object"]
