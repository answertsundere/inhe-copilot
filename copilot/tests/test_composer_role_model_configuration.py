from __future__ import annotations

import pytest

from app import config
import app.llm.client as llm_client


_COMPOSER_FIELDS = (
    "COPILOT_COMPOSER_LLM_API_BASE",
    "COPILOT_COMPOSER_LLM_API_KEY",
    "COPILOT_COMPOSER_LLM_MODEL",
    "COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS",
    "COPILOT_COMPOSER_LLM_QUALIFIED",
)


def _set_override(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_base: str = "",
    api_key: str = "",
    model: str = "",
    timeout_seconds: int = 30,
    qualified: bool = False,
) -> None:
    values = {
        "COPILOT_COMPOSER_LLM_API_BASE": api_base,
        "COPILOT_COMPOSER_LLM_API_KEY": api_key,
        "COPILOT_COMPOSER_LLM_MODEL": model,
        "COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS": timeout_seconds,
        "COPILOT_COMPOSER_LLM_QUALIFIED": qualified,
    }
    for field in _COMPOSER_FIELDS:
        monkeypatch.setattr(config, field, values[field])


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
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        timeout_seconds=45,
        qualified=True,
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
    _set_override(
        monkeypatch,
        api_base="https://api.deepseek.com/v1",
        api_key="test-composer-key",
        model="deepseek-chat",
        timeout_seconds=999,
        qualified=True,
    )

    assert llm_client.get_composer_llm_client().timeout_seconds == 120
