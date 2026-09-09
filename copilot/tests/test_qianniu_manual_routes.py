from copy import deepcopy

import pytest
from flask import Flask, g

from app.api import admin_auth, sidecar_routes


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(sidecar_routes.sidecar_bp)
    monkeypatch.setenv("COPILOT_QIANNIU_MANUAL_READ_ENABLED", "true")
    monkeypatch.setenv("COPILOT_ADMIN_ALLOWED_ORIGINS", "http://127.0.0.1:5030")
    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: g.test_principal)

    @app.before_request
    def principal():
        g.test_principal = admin_auth.AdminPrincipal(
            subject="fixture", display_name="fixture", roles=frozenset({"operator"}), auth_type="development")

    return app.test_client()


def post(client, **kwargs):
    return client.post("/api/sidecar/qianniu/preview", base_url="http://127.0.0.1:5030",
                       json={}, headers={"Origin": "http://127.0.0.1:5030", **kwargs.pop("headers", {})}, **kwargs)


def test_manual_route_is_local_no_store_and_never_shared_cache(client, monkeypatch):
    cached = deepcopy(sidecar_routes._status)
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda p: {"ok": True, "status": "window_selection_required", "windows": []})
    result = post(client)
    assert result.status_code == 200
    assert "no-store" in result.headers["Cache-Control"]
    assert sidecar_routes._status == cached


def test_default_off_never_reads_desktop(client, monkeypatch):
    monkeypatch.delenv("COPILOT_QIANNIU_MANUAL_READ_ENABLED")
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda p: pytest.fail("must not capture"))
    assert post(client).status_code == 404


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.example"}, {"Origin": "null"},
    {"Forwarded": "for=127.0.0.1"}, {"X-Forwarded-Host": "localhost"},
    {"X-Forwarded-For": "127.0.0.1"}, {"Cf-Connecting-Ip": "127.0.0.1"},
])
def test_remote_or_forwarded_request_cannot_read_desktop(client, monkeypatch, headers):
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda p: pytest.fail("must not capture"))
    assert post(client, headers=headers).status_code in {401, 403}


def test_non_loopback_peer_rejected(client, monkeypatch):
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda p: pytest.fail("must not capture"))
    assert post(client, environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code == 403


@pytest.mark.parametrize("auth_type", ["public_open", "service"])
def test_shared_or_service_identity_rejected(client, monkeypatch, auth_type):
    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal(
        subject="fixture", display_name="fixture", roles=frozenset({"admin"}), auth_type=auth_type))
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda p: pytest.fail("must not capture"))
    assert post(client).status_code == 403


def test_unauthenticated_and_forged_role_rejected(client, monkeypatch):
    def denied():
        raise admin_auth.AdminAuthError("access_assertion_missing")
    monkeypatch.setattr(admin_auth, "_verified_principal", denied)
    assert post(client, headers={"X-User-Role": "admin"}).status_code == 401


def test_capture_error_does_not_expose_exception_or_context(client, monkeypatch):
    def failed(p):
        raise RuntimeError("private customer content")
    monkeypatch.setattr(sidecar_routes, "_native_preview", failed)
    response = post(client)
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)


def test_capture_subprocess_has_no_model_or_erp_credentials(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret")
    monkeypatch.setenv("JUSHUITAN_ACCESS_TOKEN", "fixture-secret")
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return type("Result", (), {"stdout": '{"ok":true,"status":"window_selection_required","windows":[]}'})()
    monkeypatch.setattr(sidecar_routes.subprocess, "run", run)
    sidecar_routes._native_preview({})
    args, options = calls[0]
    assert args[-1] == "--manual-native-stdin"
    assert options["timeout"] == 20
    assert "DEEPSEEK_API_KEY" not in options["env"]
    assert "JUSHUITAN_ACCESS_TOKEN" not in options["env"]
    assert options["env"]["COPILOT_KNOWLEDGE_DB_PATH"] == ":memory:"


def test_busy_and_timeout_release_only_capture_lock(client, monkeypatch):
    sidecar_routes._manual_capture_lock.acquire()
    try:
        assert post(client).status_code == 503
    finally:
        sidecar_routes._manual_capture_lock.release()
    def timeout(payload):
        raise sidecar_routes.subprocess.TimeoutExpired("private", 20)
    monkeypatch.setattr(sidecar_routes, "_native_preview", timeout)
    assert post(client).get_json()["error"] == "native_capture_timeout"
    assert not sidecar_routes._manual_capture_lock.locked()


@pytest.mark.parametrize("body", [{"window_handle": True}, {"window_handle": -1}, {"script": "bad"}, []])
def test_unexpected_request_never_reaches_native_reader(client, monkeypatch, body):
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda p: pytest.fail("must not capture"))
    response = client.post("/api/sidecar/qianniu/preview", base_url="http://127.0.0.1:5030",
                           headers={"Origin": "http://127.0.0.1:5030"}, json=body)
    assert response.status_code == 422
