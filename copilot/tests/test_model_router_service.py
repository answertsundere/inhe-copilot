from app.services.model_router_service import get_fallback_chain, resolve_model, resolve_model_api_key


def _clear_model_env(monkeypatch):
    for prefix in (
        "COPILOT_FAST_MODEL",
        "COPILOT_STRONG_MODEL",
        "COPILOT_JUDGE_MODEL",
        "COPILOT_VISION_MODEL",
        "COPILOT_EMBEDDING_MODEL",
    ):
        for suffix in ("PROVIDER", "NAME", "API_BASE", "API_KEY", "TIMEOUT_SECONDS", "MAX_RETRIES"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    for name in (
        "COPILOT_LLM_MODEL",
        "COPILOT_LLM_API_BASE",
        "COPILOT_LLM_API_KEY",
        "COPILOT_VLM_MODEL",
        "COPILOT_VLM_API_BASE",
        "COPILOT_VLM_API_KEY",
        "COPILOT_EMBEDDING_MODEL",
        "COPILOT_EMBEDDING_API_BASE",
        "COPILOT_EMBEDDING_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_alias_config_takes_priority(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("COPILOT_FAST_MODEL_PROVIDER", "test_provider")
    monkeypatch.setenv("COPILOT_FAST_MODEL_NAME", "fast-test")
    monkeypatch.setenv("COPILOT_FAST_MODEL_API_BASE", "https://fast.example/v1")
    monkeypatch.setenv("COPILOT_FAST_MODEL_API_KEY", "fast-key")
    monkeypatch.setenv("COPILOT_LLM_MODEL", "legacy-model")
    monkeypatch.setenv("COPILOT_LLM_API_BASE", "https://legacy.example/v1")
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "legacy-key")

    resolved = resolve_model("fast_model")

    assert resolved["alias"] == "fast_model"
    assert resolved["provider"] == "test_provider"
    assert resolved["model"] == "fast-test"
    assert resolved["api_base"] == "https://fast.example/v1"
    assert resolved["api_key_env"] == "COPILOT_FAST_MODEL_API_KEY"
    assert resolved["enabled"] is True
    assert resolve_model_api_key("fast_model") == "fast-key"


def test_missing_alias_falls_back_to_legacy_llm(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("COPILOT_LLM_MODEL", "legacy-model")
    monkeypatch.setenv("COPILOT_LLM_API_BASE", "https://legacy.example/v1")
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "legacy-key")

    resolved = resolve_model("fast_model")

    assert resolved["source"] == "legacy_llm"
    assert resolved["model"] == "legacy-model"
    assert resolved["api_key_env"] == "COPILOT_LLM_API_KEY"
    assert resolved["enabled"] is True
    assert resolve_model_api_key("fast_model") == "legacy-key"


def test_judge_and_fast_aliases_resolve(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("COPILOT_LLM_MODEL", "legacy-model")
    monkeypatch.setenv("COPILOT_LLM_API_BASE", "https://legacy.example/v1")
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "legacy-key")

    assert resolve_model("judge_model")["enabled"] is True
    assert resolve_model("fast_model")["enabled"] is True


def test_fallback_chain_has_no_cycles():
    assert get_fallback_chain("judge_model") == ["strong_model"]
    assert get_fallback_chain("fast_model") == ["strong_model"]
    assert get_fallback_chain("strong_model") == []
