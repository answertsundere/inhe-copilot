from __future__ import annotations

import json

from scripts import diagnose_semantic_object_runtime as script


def test_readiness_reports_missing_runtime_without_private_model_paths(monkeypatch):
    monkeypatch.setattr(script, "semantic_object_runtime_status", lambda: {
        "modules": {"groundingdino": False, "transformers": False, "torch": False},
        "cuda_available": False,
        "model_paths": {"groundingdino_config": "", "groundingdino_checkpoint": "", "florence2_model": ""},
    })
    report = script.build_readiness_report()
    assert report["provider_route"] == "provider_not_configured"
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send"] is False
    assert "D:/AIModels" not in json.dumps(report)


def test_readiness_prefers_groundingdino_when_runtime_is_present(monkeypatch):
    monkeypatch.setattr(script, "semantic_object_runtime_status", lambda: {
        "modules": {"groundingdino": False, "transformers": True, "torch": True, "pillow": True},
        "cuda_available": True,
        "model_paths": {"groundingdino_config": "", "groundingdino_checkpoint": "", "groundingdino_model": "D:/AIModels/model", "florence2_model": "configured"},
    })
    assert script.build_readiness_report()["provider_route"] == "groundingdino"
