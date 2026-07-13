from __future__ import annotations

import json

from scripts import qualify_vision_grounding_providers as script


def test_unconfigured_provider_is_diagnosed_without_connecting_or_writing(monkeypatch, tmp_path):
    monkeypatch.delenv("COPILOT_VISION_GROUNDING_BASE_URL", raising=False)
    monkeypatch.delenv("COPILOT_VISION_GROUNDING_MODEL", raising=False)
    monkeypatch.delenv("COPILOT_VISION_GROUNDING_API_KEY", raising=False)
    output = tmp_path / "qualification.json"
    assert script.main(["--provider", "configured_grounding", "--json-output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["provider_status"] == "provider_not_configured"
    assert payload["qualified_for_30_image"] is False
    assert payload["summary"]["formal_kb_write_attempt_count"] == 0
    assert payload["can_change_can_send"] is False


def test_configured_candidate_without_an_adapter_is_not_misreported_as_qualified(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_VISION_GROUNDING_BASE_URL", "https://provider.test/v1")
    monkeypatch.setenv("COPILOT_VISION_GROUNDING_MODEL", "grounding-model")
    monkeypatch.setenv("COPILOT_VISION_GROUNDING_API_KEY", "test-key")
    output = tmp_path / "configured.json"
    assert script.main(["--provider", "configured_grounding", "--json-output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["provider_status"] == "provider_adapter_not_implemented"
    assert payload["qualified_for_30_image"] is False
