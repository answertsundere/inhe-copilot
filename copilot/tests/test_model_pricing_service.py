from app.services.model_pricing_service import estimate_model_cost


def test_known_provider_model_estimates_cost(monkeypatch):
    monkeypatch.delenv("COPILOT_MODEL_PRICING_JSON", raising=False)

    result = estimate_model_cost(
        provider="test_provider",
        model="cheap-test",
        prompt_tokens=1000,
        completion_tokens=500,
    )

    assert result["estimated_cost"] == 0.002
    assert result["currency"] == "USD"
    assert result["cost_unknown"] is False


def test_unknown_provider_model_returns_cost_unknown(monkeypatch):
    monkeypatch.delenv("COPILOT_MODEL_PRICING_JSON", raising=False)

    result = estimate_model_cost(
        provider="unknown_provider",
        model="unknown_model",
        prompt_tokens=1000,
        completion_tokens=1000,
    )

    assert result["estimated_cost"] == 0.0
    assert result["cost_unknown"] is True


def test_empty_tokens_do_not_error(monkeypatch):
    monkeypatch.delenv("COPILOT_MODEL_PRICING_JSON", raising=False)

    result = estimate_model_cost(
        provider="test_provider",
        model="cheap-test",
        prompt_tokens=0,
        completion_tokens=0,
    )

    assert result["estimated_cost"] == 0.0
    assert result["cost_unknown"] is False


def test_env_pricing_overrides_builtin(monkeypatch):
    monkeypatch.setenv(
        "COPILOT_MODEL_PRICING_JSON",
        '[{"provider":"test_provider","model":"cheap-test","prompt_per_1k_tokens":1,"completion_per_1k_tokens":2,"currency":"TST"}]',
    )

    result = estimate_model_cost(
        provider="test_provider",
        model="cheap-test",
        prompt_tokens=1000,
        completion_tokens=1000,
    )

    assert result["estimated_cost"] == 3.0
    assert result["currency"] == "TST"
    assert result["cost_unknown"] is False
