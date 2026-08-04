from types import SimpleNamespace

import pytest

from app import config
from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
    _ollama_native_request,
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


def test_unified_audit_config_is_independent_from_formal_and_decision_roles(
    monkeypatch,
):
    monkeypatch.setattr(config, "LLM_API_KEY", "formal-secret")
    monkeypatch.setattr(
        config,
        "COPILOT_DECISION_LLM_API_KEY",
        "decision-secret",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_PROVIDER",
        "audit-provider",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_API_BASE",
        "https://audit.example.invalid/v1",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_API_KEY",
        "audit-secret",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_MODEL",
        "audit-model",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_CAPABILITY",
        "strict_json_schema",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_TIMEOUT_SECONDS",
        17,
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_QUALIFIED",
        True,
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_DISABLE_THINKING",
        True,
    )

    audit = StrictDecisionProviderConfig.from_unified_audit_environment()

    assert audit.provider_name == "audit-provider"
    assert audit.api_base == "https://audit.example.invalid/v1"
    assert audit.api_key == "audit-secret"
    assert audit.model == "audit-model"
    assert audit.capability == "strict_json_schema"
    assert audit.timeout_seconds == 17
    assert audit.qualified is True
    assert audit.disable_thinking is True
    assert audit.api_key not in {
        config.LLM_API_KEY,
        config.COPILOT_DECISION_LLM_API_KEY,
    }


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


def test_minimax_strict_transport_uses_reasoning_safe_request_options():
    client = _Client(_result())
    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="openai_compatible",
            api_base="https://api.minimaxi.com/v1",
            disable_thinking=True,
        ),
        client_factory=lambda **_: client,
    )

    provider.request(
        name="sample",
        schema={"type": "object"},
        system_prompt="x",
        payload={},
        max_tokens=800,
    )

    request = client.calls[0]
    assert request["temperature"] == 0.1
    assert request["max_tokens"] == 1600
    assert request["extra_body"] == {
        "reasoning_split": True,
        "thinking": {"type": "disabled"},
    }


def test_minimax_provider_name_applies_output_budget_without_disabling_thinking():
    client = _Client(_result())
    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="minimax",
            api_base="https://gateway.example.invalid/v1",
            disable_thinking=False,
        ),
        client_factory=lambda **_: client,
    )

    provider.request(
        name="sample",
        schema={"type": "object"},
        system_prompt="x",
        payload={},
        max_tokens=2000,
    )

    request = client.calls[0]
    assert request["temperature"] == 0.1
    assert request["max_tokens"] == 2000
    assert request["extra_body"] == {"reasoning_split": True}


def test_generic_strict_transport_preserves_requested_output_budget():
    client = _Client(_result())
    provider = StrictDecisionProviderService(
        config=_config(disable_thinking=False),
        client_factory=lambda **_: client,
    )

    provider.request(
        name="sample",
        schema={"type": "object"},
        system_prompt="x",
        payload={},
        max_tokens=37,
    )

    request = client.calls[0]
    assert request["temperature"] == 0
    assert request["max_tokens"] == 37
    assert "extra_body" not in request


def test_ollama_native_transport_uses_schema_without_openai_compatibility():
    calls = []

    def native_request(**kwargs):
        calls.append(kwargs)
        return {
            "done_reason": "stop",
            "message": {"content": '{"ok": true}'},
        }

    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="ollama_native",
            api_base="http://127.0.0.1:11434/v1",
            model="local-model",
            disable_thinking=True,
        ),
        client_factory=lambda **_: pytest.fail(
            "OpenAI-compatible client must not be used"
        ),
        native_request=native_request,
    )

    assert provider.request(
        name="sample",
        schema={"type": "object", "additionalProperties": False},
        system_prompt="system",
        payload={"candidate": "safe"},
        max_tokens=41,
    ) == {"ok": True}

    assert len(calls) == 1
    request = calls[0]
    assert request["api_base"] == "http://127.0.0.1:11434/v1"
    assert request["timeout_seconds"] == 3
    assert request["payload"] == {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": '{"candidate": "safe"}'},
        ],
        "stream": False,
        "format": {"type": "object", "additionalProperties": False},
        "think": False,
        "options": {"temperature": 0, "num_predict": 1600},
    }


def test_ollama_native_transport_can_keep_thinking_enabled():
    calls = []
    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="ollama",
            api_base="http://localhost:11434/api",
            disable_thinking=False,
        ),
        native_request=lambda **kwargs: (
            calls.append(kwargs)
            or {
                "done_reason": "stop",
                "message": {"content": '{"ok": true}'},
            }
        ),
    )

    provider.request(
        name="sample",
        schema={"type": "object"},
        system_prompt="system",
        payload={},
        max_tokens=12,
    )

    assert calls[0]["payload"]["think"] is True


def test_ollama_native_transport_preserves_larger_output_budget():
    calls = []
    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="ollama_native",
            api_base="http://127.0.0.1:11434/api",
        ),
        native_request=lambda **kwargs: (
            calls.append(kwargs)
            or {
                "done_reason": "stop",
                "message": {"content": '{"ok": true}'},
            }
        ),
    )

    provider.request(
        name="sample",
        schema={"type": "object"},
        system_prompt="system",
        payload={},
        max_tokens=2400,
    )

    assert calls[0]["payload"]["options"]["num_predict"] == 2400


def test_ollama_native_transport_rejects_non_schema_capability_before_call():
    calls = []
    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="ollama_native",
            api_base="http://127.0.0.1:11434/api",
            capability="tool_call_schema",
        ),
        native_request=lambda **kwargs: calls.append(kwargs),
    )

    with pytest.raises(
        StrictDecisionProviderError,
        match="strict_capability_not_supported",
    ):
        provider.request(
            name="sample",
            schema={},
            system_prompt="system",
            payload={},
            max_tokens=1,
        )

    assert calls == []


def test_ollama_native_transport_fails_closed_on_truncation():
    provider = StrictDecisionProviderService(
        config=_config(
            provider_name="ollama_native",
            api_base="http://127.0.0.1:11434/api",
        ),
        native_request=lambda **_: {
            "done_reason": "length",
            "message": {"content": '{"ok":'},
        },
    )

    with pytest.raises(
        StrictDecisionProviderError,
        match="structured_output_truncated",
    ):
        provider.request(
            name="sample",
            schema={},
            system_prompt="system",
            payload={},
            max_tokens=1,
        )


def test_ollama_native_transport_rejects_non_local_origin_before_network():
    with pytest.raises(
        StrictDecisionProviderError,
        match="provider_origin_not_allowed",
    ):
        _ollama_native_request(
            api_base="https://remote.example.invalid/api",
            payload={},
            timeout_seconds=1,
        )


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
