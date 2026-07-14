from types import SimpleNamespace

import pytest

from app import config
from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
)


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _result(content='{"ok": true}'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))])


def _config(**overrides):
    values = {
        "provider_name": "test-provider",
        "api_base": "https://decision.example.invalid/v1",
        "api_key": "secret-value",
        "model": "strict-model",
        "capability": "strict_json_schema",
        "timeout_seconds": 3,
        "qualified": True,
    }
    values.update(overrides)
    return StrictDecisionProviderConfig(**values)


def test_formal_llm_config_is_not_reused_when_decision_provider_missing(monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "formal-secret")
    provider = StrictDecisionProviderService(config=StrictDecisionProviderConfig(
        provider_name="", api_base="", api_key="", model="", capability="unsupported", timeout_seconds=3, qualified=False,
    ))
    assert provider.metadata()["configured"] is False
    with pytest.raises(StrictDecisionProviderError, match="provider_not_configured"):
        provider.request(name="x", schema={}, system_prompt="x", payload={}, max_tokens=1)


def test_strict_json_schema_request_never_uses_json_object():
    client = _Client(_result())
    provider = StrictDecisionProviderService(config=_config(), client_factory=lambda **_: client)
    assert provider.request(name="sample", schema={"type": "object"}, system_prompt="x", payload={}, max_tokens=1) == {"ok": True}
    request = client.calls[0]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert "tools" not in request


def test_unqualified_provider_cannot_run_shadow_but_can_be_qualified():
    client = _Client(_result())
    provider = StrictDecisionProviderService(config=_config(qualified=False), client_factory=lambda **_: client)
    with pytest.raises(StrictDecisionProviderError, match="provider_not_qualified"):
        provider.request(name="sample", schema={}, system_prompt="x", payload={}, max_tokens=1)
    assert provider.request(name="sample", schema={}, system_prompt="x", payload={}, max_tokens=1, allow_unqualified=True) == {"ok": True}


def test_strict_tool_call_transport_requires_one_named_strict_call():
    tool_call = SimpleNamespace(function=SimpleNamespace(name="sample", arguments='{"ok": true}'))
    client = _Client(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[tool_call]))]))
    provider = StrictDecisionProviderService(
        config=_config(capability="tool_call_schema"),
        client_factory=lambda **_: client,
    )
    assert provider.request(name="sample", schema={"type": "object"}, system_prompt="x", payload={}, max_tokens=1) == {"ok": True}
    tool = client.calls[0]["tools"][0]["function"]
    assert tool["strict"] is True
    assert tool["parameters"] == {"type": "object"}
    assert "response_format" not in client.calls[0]


def test_provider_error_is_safely_categorized():
    class TimeoutClient(_Client):
        def create(self, **kwargs):
            raise TimeoutError("https://sensitive.example.invalid timed out")

    provider = StrictDecisionProviderService(config=_config(), client_factory=lambda **_: TimeoutClient(_result()))
    with pytest.raises(StrictDecisionProviderError, match="timeout"):
        provider.request(name="sample", schema={}, system_prompt="x", payload={}, max_tokens=1)


def test_unsupported_capability_fails_without_plain_json_fallback():
    provider = StrictDecisionProviderService(config=_config(capability="json_object_only"))
    with pytest.raises(StrictDecisionProviderError, match="strict_capability_not_supported"):
        provider.request(name="sample", schema={}, system_prompt="x", payload={}, max_tokens=1)


def test_safe_metadata_never_contains_api_base_or_key():
    provider = StrictDecisionProviderService(config=_config())
    text = str(provider.metadata())
    assert "decision.example.invalid" not in text
    assert "secret-value" not in text
    assert provider.metadata()["host_fingerprint"]
