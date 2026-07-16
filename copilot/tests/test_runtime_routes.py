from __future__ import annotations


def test_runtime_version_exposes_sanitized_deployment_metadata(monkeypatch):
    from flask import Flask
    from app.api import runtime_routes

    monkeypatch.setattr(runtime_routes, "_git_metadata", lambda *args: "test-value")
    monkeypatch.setattr(runtime_routes, "_feature_flags", lambda: {"formal_evidence_convergence": False})
    monkeypatch.setattr(
        "app.api.admin_auth.admin_auth_readiness",
        lambda: {"admin_auth_mode": "cloudflare_access", "admin_auth_ready": True,
                 "access_audience_configured": True, "insecure_header_auth_disabled": True, "reason": ""},
    )
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args: {"ready": True, "status": "ready", "reasons": [], "knowledge": {"entries": 1, "chunks": 1, "kb_qa": 1}, "database": {"basename": "runtime.db"}},
    )

    app = Flask(__name__)
    with app.app_context():
        response = runtime_routes.runtime_version()
        payload = response.get_json()

    assert payload["runtime_commit"] == "test-value"
    assert payload["branch"] == "test-value"
    assert payload["feature_flags"] == {"formal_evidence_convergence": False}
    assert payload["readiness"]["ready"] is True
    assert "DATABASE_URL" not in payload


def test_runtime_readiness_uses_503_without_exposing_database_path(monkeypatch):
    from flask import Flask
    from app.api import runtime_routes

    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args: {"ready": False, "status": "not_ready", "reasons": ["knowledge_db_missing"], "knowledge": {"entries": 0, "chunks": 0, "kb_qa": 0}, "database": {"basename": "knowledge_base.db"}},
    )
    monkeypatch.setattr(
        "app.api.admin_auth.admin_auth_readiness",
        lambda: {"admin_auth_mode": "cloudflare_access", "admin_auth_ready": True,
                 "access_audience_configured": True, "insecure_header_auth_disabled": True, "reason": ""},
    )
    app = Flask(__name__)
    app.register_blueprint(runtime_routes.runtime_bp)

    response = app.test_client().get("/api/runtime/readiness")

    assert response.status_code == 503
    assert response.get_json()["reasons"] == ["knowledge_db_missing"]
    assert "D:\\" not in response.get_data(as_text=True)
