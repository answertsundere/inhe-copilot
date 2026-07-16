from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, jsonify

from app.api import admin_auth
from app.api.config_routes import config_bp


class _SigningKeyClient:
    def __init__(self, public_key):
        jwk = jwt.PyJWK.from_dict(json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key)))
        self._key = type("SigningKey", (), {"key": jwk.key})()

    def get_signing_key_from_jwt(self, _assertion):
        return self._key


@pytest.fixture()
def access_token_factory(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    team = "access.example.test"
    audience = "test-audience"
    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "cloudflare_access")
    monkeypatch.setenv("COPILOT_CF_ACCESS_TEAM_DOMAIN", team)
    monkeypatch.setenv("COPILOT_CF_ACCESS_AUD", audience)
    monkeypatch.setenv(
        "COPILOT_CF_ACCESS_ROLE_MAP_JSON",
        json.dumps({"admin": {"emails": ["admin@example.test"]}, "reviewer": {"groups": ["reviewers"]}}),
    )
    monkeypatch.setattr(
        admin_auth.CloudflareAccessJwtVerifier,
        "_client",
        lambda _self, _team, _url: _SigningKeyClient(private_key.public_key()),
    )

    def issue(**overrides):
        now = int(time.time())
        claims = {
            "sub": "subject-1",
            "email": "admin@example.test",
            "iss": f"https://{team}",
            "aud": audience,
            "nbf": now - 1,
            "exp": now + 300,
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-kid"})

    return issue


def test_verified_access_jwt_maps_roles_from_claims(access_token_factory):
    principal = admin_auth.CloudflareAccessJwtVerifier().verify_assertion(access_token_factory())

    assert principal.roles == frozenset({"admin"})
    assert principal.display_name == "admin@example.test"


@pytest.mark.parametrize(
    ("claims", "expected_code"),
    [
        ({"iss": "https://wrong.example.test"}, "access_assertion_issuer_invalid"),
        ({"aud": "wrong-audience"}, "access_assertion_audience_invalid"),
        ({"exp": 1}, "access_assertion_expired"),
        ({"nbf": int(time.time()) + 3600}, "access_assertion_not_yet_valid"),
    ],
)
def test_access_jwt_rejects_invalid_registered_claims(access_token_factory, claims, expected_code):
    with pytest.raises(admin_auth.AdminAuthError) as error:
        admin_auth.CloudflareAccessJwtVerifier().verify_assertion(access_token_factory(**claims))

    assert error.value.code == expected_code


def test_access_jwt_rejects_unknown_kid(monkeypatch, access_token_factory):
    class _UnknownKeyClient:
        def get_signing_key_from_jwt(self, _assertion):
            raise jwt.PyJWKClientError("unknown kid")

    monkeypatch.setattr(
        admin_auth.CloudflareAccessJwtVerifier,
        "_client",
        lambda *_args: _UnknownKeyClient(),
    )
    with pytest.raises(admin_auth.AdminAuthError) as error:
        admin_auth.CloudflareAccessJwtVerifier().verify_assertion(access_token_factory())

    assert error.value.code == "access_assertion_key_unavailable"


def test_fake_role_header_does_not_authenticate_config_route(monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: (_ for _ in ()).throw(admin_auth.AdminAuthError("access_assertion_missing")),
    )
    app = Flask(__name__)
    app.register_blueprint(config_bp)
    admin_auth.install_admin_access_control(app)

    response = app.test_client().get("/api/config/llm", headers={"X-User-Role": "admin", "X-User-Name": "spoofed"})

    assert response.status_code == 401
    assert response.get_json()["reason"] == "access_assertion_missing"


def test_rbac_and_csrf_apply_to_management_writes(monkeypatch):
    app = Flask(__name__)

    @app.post("/api/maintenance/task")
    def write_task():
        return jsonify({"ok": True})

    admin_auth.install_admin_access_control(app)
    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: admin_auth.AdminPrincipal("reviewer", "reviewer", frozenset({"reviewer"}), "cloudflare_access"),
    )
    assert app.test_client().post("/api/maintenance/task").status_code == 403

    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: admin_auth.AdminPrincipal("supervisor", "supervisor", frozenset({"supervisor"}), "cloudflare_access"),
    )
    monkeypatch.setenv("COPILOT_ADMIN_ALLOWED_ORIGINS", "https://admin.example.test")
    assert app.test_client().post("/api/maintenance/task").status_code == 403
    assert app.test_client().post("/api/maintenance/task", headers={"Origin": "https://admin.example.test"}).status_code == 200


def test_service_identity_requires_explicit_path_allowlist(monkeypatch):
    principal = admin_auth.AdminPrincipal("service", "service", frozenset({"service"}), "service", "svc-1")
    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: principal)
    app = Flask(__name__)

    @app.post("/api/automation/rebuild")
    def automation():
        return jsonify({"ok": True})

    admin_auth.install_admin_access_control(app)
    assert app.test_client().post("/api/automation/rebuild").status_code == 403
    monkeypatch.setenv("COPILOT_ADMIN_SERVICE_ALLOWED_PATHS", "/api/automation")
    assert app.test_client().post("/api/automation/rebuild").status_code == 200


def test_route_inventory_has_an_explicit_policy_for_every_route():
    from app.main import create_app

    rows = admin_auth.inventory_route_policies(create_app())
    assert rows
    assert all(row["policy"] for row in rows)
    config_rows = [row for row in rows if row["rule"] == "/api/config/llm"]
    assert {row["policy"] for row in config_rows} == {"admin_only"}
    assert admin_auth.route_policy("health.api_health", "/health", "GET") == "public_runtime"
    assert admin_auth.route_policy("analyze.api_analyze", "/api/analyze", "POST") == "customer_runtime"


def test_public_runtime_endpoints_do_not_require_management_auth(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args: {"ready": True, "status": "ready", "reasons": [],
                        "knowledge": {"entries": 1, "chunks": 1, "kb_qa": 1},
                        "database": {"basename": "runtime.db"}},
    )
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    assert client.get("/api/runtime/version").status_code == 200
    readiness = client.get("/api/runtime/readiness")
    assert readiness.status_code != 401
    assert readiness.get_json()["insecure_header_auth_disabled"] is True


def test_production_readiness_fails_closed_without_access_configuration(monkeypatch):
    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "cloudflare_access")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "production")
    monkeypatch.delenv("COPILOT_CF_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("COPILOT_CF_ACCESS_AUD", raising=False)

    readiness = admin_auth.admin_auth_readiness()

    assert readiness["admin_auth_ready"] is False
    assert readiness["insecure_header_auth_disabled"] is True
    assert readiness["reason"] == "admin_auth_configuration_missing"
