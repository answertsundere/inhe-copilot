from copy import deepcopy

import pytest
from flask import Flask, g

from app.api import admin_auth, sidecar_routes

_REAL_VERIFIED_PRINCIPAL = admin_auth._verified_principal


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


@pytest.mark.parametrize("mode", ["manual_document_review", None, True, "", "automatic"])
def test_explicit_capture_mode_is_validated_before_native_read(client, monkeypatch, mode):
    calls = []
    def read(payload):
        calls.append(payload)
        return {"ok": True, "status": "manual_confirmation_required"}
    monkeypatch.setattr(sidecar_routes, "_native_preview", read)
    body = {"window_handle": 42, "mode": mode}
    response = client.post("/api/sidecar/qianniu/preview", base_url="http://127.0.0.1:5030",
                           json=body, headers={"Origin": "http://127.0.0.1:5030"})
    if mode == "manual_document_review":
        assert response.status_code == 200
        assert calls == [body]
        assert "no-store" in response.headers["Cache-Control"]
    else:
        assert response.status_code == 422
        assert response.get_json()["error"] == "capture_mode_invalid"
        assert calls == []


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


@pytest.fixture
def application_client(monkeypatch):
    """Use real routing/auth; replace I/O only, never the app access policy."""
    import app.main as main
    import app.tracing.repository as tracing

    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "development")
    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "development_loopback")
    monkeypatch.setenv("COPILOT_ADMIN_DEV_SUBJECT", "local-integration-fixture")
    monkeypatch.setenv("COPILOT_ADMIN_DEV_ROLE", "operator")
    monkeypatch.setenv("COPILOT_ADMIN_ALLOWED_ORIGINS", "http://127.0.0.1:5030")
    monkeypatch.setenv("COPILOT_QIANNIU_MANUAL_READ_ENABLED", "true")
    monkeypatch.setattr(admin_auth, "_verified_principal", _REAL_VERIFIED_PRINCIPAL)
    for name in ("_init_db", "_init_services", "_start_daily_sync_thread", "_start_media_auto_refresh_thread"):
        monkeypatch.setattr(main, name, lambda: None)
    monkeypatch.setattr(tracing, "init_trace_tables", lambda: None)
    monkeypatch.setattr(tracing, "load_conversation_goal_lifecycle_context", lambda _: ({}, "disabled"))
    app = main.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def application_post(client, body, *, headers=None):
    return client.post(
        "/ask/api/sidecar/qianniu/preview", json=body,
        base_url="http://127.0.0.1:5030",
        headers={"Origin": "http://127.0.0.1:5030", **(headers or {})},
    )


def test_full_app_preview_uses_loopback_auth_and_existing_canonical_entry(application_client, monkeypatch):
    from test_qianniu_manual_capture import capture
    from scripts.sidecar.uia_sidebar_extractor import build_native_preview
    from app.api import analyze_routes
    from app.services.analysis_pipeline_service import AnalysisPipelineService

    calls, prepared = [], []
    nodes = capture()
    nodes[1]["selected"] = nodes[2]["selected"] = False

    def native(payload):
        calls.append(payload)
        return build_native_preview(nodes, deepcopy(nodes), 42, mode=payload["mode"])

    def at_pipeline_boundary(self, request):
        prepared.append(self._prepare_request(request))
        # No substitute customer reply: stop this test at the actual canonical
        # input owner, before any Graph, provider, database or delivery work.
        return {"can_send": False, "requires_human_review": True, "evidence_debug": {}}

    monkeypatch.setattr(sidecar_routes, "_native_preview", native)
    monkeypatch.setattr(analyze_routes, "get_services", lambda: None)
    monkeypatch.setattr(AnalysisPipelineService, "run", at_pipeline_boundary)
    response = application_post(application_client, {"window_handle": 42, "mode": "manual_document_review"})
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    preview = response.get_json()
    assert preview["status"] == "manual_confirmation_required"
    assert preview["diagnostics"]["current_customer_binding_verified"] is False
    assert prepared == []

    # This is the payload shape produced by the existing human-confirmed page.
    history = preview["context"]["conversation_history"]
    payload = {"message": "当前另一个问题", "conversation_id": "manual-fixture-session-a",
               "shop_name": preview["shop_name"], "copilot_context": {
                   "source": "real_test_panel", "shop_name": preview["shop_name"],
                   "conversation_history": history, "latest_customer_message": "",
                   "previous_agent_message": "请看图片 [IMAGE]"}}
    result = application_client.post("/ask/api/analyze", json=payload,
                                    base_url="http://127.0.0.1:5030",
                                    headers={"Origin": "http://127.0.0.1:5030"})
    assert result.status_code == 200
    assert len(prepared) == 1
    actual = prepared[0]
    assert actual.customer_message == payload["message"]
    assert actual.conversation_id == payload["conversation_id"]
    assert actual.source == "api"
    assert [(t["role"], t["content"]) for t in actual.copilot_context["conversation_history"]] == [
        (t["role"], t["content"]) for t in history]
    assert actual.copilot_context["conversation_context_contract"]["status"] == "valid"
    assert not actual.order_id and not actual.product_candidates
    assert preview["buyer_name"] not in repr(actual.copilot_context)
    assert result.get_json()["can_send"] is False
    assert result.get_json()["requires_human_review"] is True
    assert len(calls) == 1, "analysis must not implicitly recapture the desktop"


@pytest.mark.parametrize("role", ["operator", "reviewer", "supervisor"])
def test_full_app_human_preview_roles_do_not_require_admin(application_client, monkeypatch, role):
    monkeypatch.setenv("COPILOT_ADMIN_DEV_ROLE", role)
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda _: {"ok": True, "status": "window_selection_required", "windows": []})
    assert application_post(application_client, {}).status_code == 200


@pytest.mark.parametrize("role,status", [("operator", 403), ("reviewer", 403), ("supervisor", 200), ("admin", 200)])
def test_full_app_workbench_retains_stronger_page_policy(application_client, monkeypatch, role, status):
    import app.main as main
    from pathlib import Path
    # The workbench may display local reviewed examples. Do not read these in a
    # synthetic route test; page authorization itself remains real.
    original_exists = main.os.path.exists
    monkeypatch.setattr(main.os.path, "exists", lambda path: False if Path(path).name in {
        "premium_manual_cases.json", "real_jst_demo_test_results.json"} else original_exists(path))
    monkeypatch.setenv("COPILOT_ADMIN_DEV_ROLE", role)
    response = application_client.get("/ask/real-test", base_url="http://127.0.0.1:5030")
    assert response.status_code == status
    if status == 200:
        assert 'id="qianniuAssistedButton"' in response.get_data(as_text=True)
        assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("mutation,expected", [
    ("disabled", 404), ("no_subject", 401), ("cloudflare_missing", 401),
    ("wrong_origin", 403), ("missing_allowed_origin", 403),
    ("forwarded", 401), ("public_open", 403),
])
def test_full_app_auth_blocks_before_capture(application_client, monkeypatch, mutation, expected):
    headers = {}
    if mutation == "disabled":
        monkeypatch.delenv("COPILOT_QIANNIU_MANUAL_READ_ENABLED")
    elif mutation == "no_subject":
        monkeypatch.delenv("COPILOT_ADMIN_DEV_SUBJECT")
    elif mutation == "cloudflare_missing":
        monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "cloudflare_access")
        headers.update({"X-User-Role": "admin", "X-User-Name": "not-authentication"})
    elif mutation == "wrong_origin":
        headers["Origin"] = "https://untrusted.example"
    elif mutation == "missing_allowed_origin":
        monkeypatch.delenv("COPILOT_ADMIN_ALLOWED_ORIGINS")
    elif mutation == "forwarded":
        headers["X-Forwarded-For"] = "127.0.0.1"
    elif mutation == "public_open":
        monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "public_open")
        monkeypatch.setenv("COPILOT_PUBLIC_OPEN_ACKNOWLEDGED", "true")
    monkeypatch.setattr(sidecar_routes, "_native_preview", lambda _: pytest.fail("must not read desktop"))
    assert application_post(application_client, {}, headers=headers).status_code == expected


def test_full_app_empty_current_question_never_uses_old_buyer_turn(application_client, monkeypatch):
    from app.api import analyze_routes
    monkeypatch.setattr(analyze_routes, "get_services", lambda: pytest.fail("must not call Agent"))
    response = application_client.post("/ask/api/analyze", base_url="http://127.0.0.1:5030", json={
        "message": "", "conversation_id": "manual-fixture-session-b", "copilot_context": {
            "conversation_history": [{"role": "customer", "content": "旧问题", "turn_index": 0}]}})
    assert response.status_code == 400
