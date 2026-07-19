from types import SimpleNamespace

import pytest

from app import config
from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
    safe_provider_identity,
)


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _result(content='{"ok": true}', finish_reason="stop"):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=[]),
        finish_reason=finish_reason,
    )])


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


def test_non_thinking_mode_is_an_explicit_provider_option():
    client = _Client(_result())
    provider = StrictDecisionProviderService(
        config=_config(disable_thinking=True),
        client_factory=lambda **_: client,
    )

    provider.request(name="sample", schema={"type": "object"}, system_prompt="x", payload={}, max_tokens=1)

    assert client.calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert provider.metadata()["disable_thinking"] is True


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


def test_truncated_structured_response_fails_without_repair():
    client = _Client(_result('{"ok":', finish_reason="length"))
    provider = StrictDecisionProviderService(config=_config(), client_factory=lambda **_: client)
    with pytest.raises(StrictDecisionProviderError, match="structured_output_truncated"):
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


def test_safe_provider_identity_uses_host_fingerprint_and_model_without_endpoint_or_key():
    identity = safe_provider_identity(
        provider_name="candidate-grader",
        api_base="https://private.example.invalid/v1",
        model="strict-model",
    )

    assert identity["configured"] is True
    assert identity["identity"] == f"{identity['host_fingerprint']}:strict-model"
    assert "private.example.invalid" not in str(identity)
    assert "https://" not in str(identity)


def test_safe_provider_identity_canonicalizes_origin_without_exposing_url_parts():
    baseline = safe_provider_identity(
        provider_name="candidate-grader",
        api_base="https://private.example.invalid/v1",
        model="strict-model",
    )
    variants = [
        "https://private.example.invalid/v1/",
        "https://private.example.invalid/openai/v1?region=cn#ignored",
        "https://user:password@private.example.invalid:443/another/path",
    ]

    assert all(
        safe_provider_identity(
            provider_name="candidate-grader", api_base=api_base, model="strict-model"
        )["host_fingerprint"] == baseline["host_fingerprint"]
        for api_base in variants
    )
    assert "user" not in str(baseline)
    assert "password" not in str(baseline)


@pytest.mark.parametrize(
    "api_base",
    ["", "/v1", "https:///v1", "https://private.example.invalid:bad/v1"],
)
def test_safe_provider_identity_rejects_invalid_or_relative_api_base(api_base):
    identity = safe_provider_identity(
        provider_name="candidate-grader", api_base=api_base, model="strict-model"
    )

    assert identity["configured"] is False
    assert identity["identity"] == ""


def test_safe_provider_identity_distinguishes_scheme_host_and_non_default_port():
    baseline = safe_provider_identity(
        provider_name="candidate-grader",
        api_base="https://private.example.invalid/v1",
        model="strict-model",
    )
    equivalent_default_port = safe_provider_identity(
        provider_name="candidate-grader",
        api_base="https://PRIVATE.EXAMPLE.INVALID:443/openai/v1",
        model="strict-model",
    )
    variants = [
        "http://private.example.invalid/v1",
        "https://other.example.invalid/v1",
        "https://private.example.invalid:8443/v1",
    ]

    assert equivalent_default_port["host_fingerprint"] == baseline["host_fingerprint"]
    assert all(
        safe_provider_identity(
            provider_name="candidate-grader", api_base=api_base, model="strict-model"
        )["host_fingerprint"] != baseline["host_fingerprint"]
        for api_base in variants
    )
