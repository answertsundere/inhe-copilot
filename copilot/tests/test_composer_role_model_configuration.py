from __future__ import annotations

import pytest

from app import config
import app.llm.client as llm_client


_COMPOSER_FIELDS = (
    "COPILOT_COMPOSER_LLM_API_BASE",
    "COPILOT_COMPOSER_LLM_API_KEY",
    "COPILOT_COMPOSER_LLM_MODEL",
    "COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS",
    "COPILOT_COMPOSER_LLM_TRANSPORT_THINKING",
    "COPILOT_COMPOSER_LLM_MIN_OUTPUT_TOKENS",
    "COPILOT_COMPOSER_LLM_QUALIFIED",
    "COPILOT_COMPOSER_LLM_QUALIFICATION_FINGERPRINT",
)


def _set_override(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_base: str = "",
    api_key: str = "",
    model: str = "",
    timeout_seconds: int = 30,
    transport_thinking: str = "",
    minimum_output_tokens: int = 0,
    qualified: bool = False,
    qualification_fingerprint: str = "",
) -> None:
    values = {
        "COPILOT_COMPOSER_LLM_API_BASE": api_base,
        "COPILOT_COMPOSER_LLM_API_KEY": api_key,
        "COPILOT_COMPOSER_LLM_MODEL": model,
        "COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS": timeout_seconds,
        "COPILOT_COMPOSER_LLM_TRANSPORT_THINKING": transport_thinking,
        "COPILOT_COMPOSER_LLM_MIN_OUTPUT_TOKENS": minimum_output_tokens,
        "COPILOT_COMPOSER_LLM_QUALIFIED": qualified,
        "COPILOT_COMPOSER_LLM_QUALIFICATION_FINGERPRINT": qualification_fingerprint,
    }
    for field in _COMPOSER_FIELDS:
        monkeypatch.setattr(config, field, values[field], raising=False)


def test_composer_role_uses_the_unchanged_formal_client_without_override(
    monkeypatch: pytest.MonkeyPatch,
):
    expected = object()
    _set_override(monkeypatch)
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: expected)

    assert llm_client.get_composer_llm_client() is expected


def test_composer_role_uses_only_a_complete_qualified_override(
    monkeypatch: pytest.MonkeyPatch,
):
    fingerprint = llm_client.composer_role_configuration_fingerprint(
        api_base="https://api.deepseek.com/v1",
        model="deepseek-chat",
        timeout_seconds=45,
    )
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        timeout_seconds=45,
        qualified=True,
        qualification_fingerprint=fingerprint,
    )

    client = llm_client.get_composer_llm_client()

    assert client.api_base == "https://api.deepseek.com/v1"
    assert client.api_key == "test-composer-key"
    assert client.model == "deepseek-chat"
    assert client.timeout_seconds == 45
    assert client.provider_name == "deepseek"


@pytest.mark.parametrize(
    ("api_base", "api_key", "model"),
    [
        ("https://api.deepseek.com/v1", "", ""),
        ("", "test-composer-key", ""),
        ("", "", "deepseek-chat"),
    ],
)
def test_composer_role_rejects_partial_override(
    monkeypatch: pytest.MonkeyPatch,
    api_base: str,
    api_key: str,
    model: str,
):
    _set_override(
        monkeypatch,
        api_base=api_base,
        api_key=api_key,
        model=model,
        qualified=True,
    )

    with pytest.raises(
        llm_client.ComposerRoleConfigurationError,
        match="composer_role_provider_incomplete",
    ):
        llm_client.get_composer_llm_client()


def test_composer_role_rejects_unqualified_override(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        qualified=False,
    )

    with pytest.raises(
        llm_client.ComposerRoleConfigurationError,
        match="composer_role_provider_not_qualified",
    ):
        llm_client.get_composer_llm_client()


def test_composer_qualification_can_use_a_complete_unqualified_override(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        qualified=False,
    )

    client = llm_client.get_composer_llm_client(allow_unqualified=True)

    assert client.provider_name == "deepseek"


def test_composer_role_bounds_its_override_timeout(
    monkeypatch: pytest.MonkeyPatch,
):
    fingerprint = llm_client.composer_role_configuration_fingerprint(
        api_base="https://api.deepseek.com/v1",
        model="deepseek-chat",
        timeout_seconds=120,
    )
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        timeout_seconds=999,
        qualified=True,
        qualification_fingerprint=fingerprint,
    )

    assert llm_client.get_composer_llm_client().timeout_seconds == 120


def test_composer_role_rejects_a_qualified_override_without_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
):
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        qualified=True,
    )

    with pytest.raises(
        llm_client.ComposerRoleConfigurationError,
        match="composer_role_qualification_fingerprint_missing",
    ):
        llm_client.get_composer_llm_client()


def test_composer_role_rejects_a_changed_model_after_qualification(
    monkeypatch: pytest.MonkeyPatch,
):
    fingerprint = llm_client.composer_role_configuration_fingerprint(
        api_base="https://api.deepseek.com/v1",
        model="deepseek-chat",
        timeout_seconds=30,
    )
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="another-model",
        qualified=True,
        qualification_fingerprint=fingerprint,
    )

    with pytest.raises(
        llm_client.ComposerRoleConfigurationError,
        match="composer_role_configuration_changed",
    ):
        llm_client.get_composer_llm_client()


def test_composer_role_binds_explicit_transport_capabilities_to_qualification(
    monkeypatch: pytest.MonkeyPatch,
):
    fingerprint = llm_client.composer_role_configuration_fingerprint(
        api_base="https://api.example.test/v1",
        model="candidate-model",
        timeout_seconds=30,
        transport_thinking="disabled",
        minimum_output_tokens=1200,
    )
    _set_override(
        monkeypatch,
        api_base="https://api.example.test/v1",
        api_key="test-composer-key",
        model="candidate-model",
        qualified=True,
        qualification_fingerprint=fingerprint,
        transport_thinking="disabled",
        minimum_output_tokens=1200,
    )

    client = llm_client.get_composer_llm_client()

    assert client.transport_thinking == "disabled"
    assert client.minimum_output_tokens == 1200


def test_composer_role_fingerprint_changes_when_transport_capabilities_change():
    baseline = llm_client.composer_role_configuration_fingerprint(
        api_base="https://api.example.test/v1",
        model="candidate-model",
        timeout_seconds=30,
    )
    configured = llm_client.composer_role_configuration_fingerprint(
        api_base="https://api.example.test/v1",
        model="candidate-model",
        timeout_seconds=30,
        transport_thinking="disabled",
        minimum_output_tokens=1200,
    )

    assert configured != baseline
