import os


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_ENV_FILE", str(tmp_path / ".env"))

    import app.config as cfg

    monkeypatch.setattr(cfg, "LLM_API_KEY", "sk-existing-test-key")
    monkeypatch.setattr(cfg, "LLM_API_BASE", "https://api.example.com")
    monkeypatch.setattr(cfg, "LLM_MODEL", "demo-model")

    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_llm_config_is_masked(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.get("/api/config/llm")

    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "sk-existing-test-key" not in text
    data = resp.get_json()
    assert data["configured"] is True
    assert data["api_key_masked"].startswith("sk-e")


def test_update_llm_config_requires_admin_role(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.put("/api/config/llm", json={
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "sk-new-test-key-123456",
    })

    assert resp.status_code == 403


def test_update_llm_config_saves_env_and_does_not_return_raw_key(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    client = _client(monkeypatch, tmp_path)

    resp = client.put(
        "/api/config/llm",
        headers={"X-User-Role": "supervisor"},
        json={
            "api_base": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "sk-new-test-key-123456",
        },
    )

    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "sk-new-test-key-123456" not in text
    data = resp.get_json()
    assert data["ok"] is True
    assert data["configured"] is True
    assert data["api_key_masked"].startswith("sk-n")

    saved = env_path.read_text(encoding="utf-8")
    assert "COPILOT_LLM_API_BASE=https://api.deepseek.com" in saved
    assert "COPILOT_LLM_MODEL=deepseek-chat" in saved
    assert "COPILOT_LLM_API_KEY=sk-new-test-key-123456" in saved
    assert os.environ["COPILOT_LLM_API_KEY"] == "sk-new-test-key-123456"


def test_update_without_api_key_keeps_existing_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.put(
        "/api/config/llm",
        headers={"X-User-Role": "admin"},
        json={
            "api_base": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "",
        },
    )

    assert resp.status_code == 200
    saved = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "COPILOT_LLM_API_KEY=sk-existing-test-key" in saved


def test_clear_llm_api_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    resp = client.put(
        "/api/config/llm",
        headers={"X-User-Role": "admin"},
        json={
            "api_base": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "clear_api_key": True,
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["configured"] is False
    saved = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "COPILOT_LLM_API_KEY=" in saved
