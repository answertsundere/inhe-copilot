from __future__ import annotations


def test_runtime_version_exposes_sanitized_deployment_metadata(monkeypatch):
    from flask import Flask
    from app.api import runtime_routes

    monkeypatch.setattr(runtime_routes, "_git_metadata", lambda *args: "test-value")
    monkeypatch.setattr(runtime_routes, "_feature_flags", lambda: {"formal_evidence_convergence": False})

    app = Flask(__name__)
    with app.app_context():
        response = runtime_routes.runtime_version()
        payload = response.get_json()

    assert payload["runtime_commit"] == "test-value"
    assert payload["branch"] == "test-value"
    assert payload["feature_flags"] == {"formal_evidence_convergence": False}
    assert "DATABASE_URL" not in payload
