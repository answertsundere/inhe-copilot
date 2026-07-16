from __future__ import annotations

import json
import logging
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Blueprint, Flask, jsonify

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


def test_verified_access_jwt_rejects_unmapped_identity(access_token_factory):
    with pytest.raises(admin_auth.AdminAuthError) as error:
        admin_auth.CloudflareAccessJwtVerifier().verify_assertion(
            access_token_factory(email="unmapped@example.test", sub="unmapped-subject")
        )

    assert error.value.code == "identity_not_authorized"
    assert error.value.status_code == 403


def test_verified_access_jwt_only_grants_explicit_mapped_roles(monkeypatch, access_token_factory):
    monkeypatch.setenv(
        "COPILOT_CF_ACCESS_ROLE_MAP_JSON",
        json.dumps({
            "operator": {"emails": ["operator@example.test"]},
            "reviewer": {"emails": ["operator@example.test"]},
        }),
    )

    principal = admin_auth.CloudflareAccessJwtVerifier().verify_assertion(
        access_token_factory(email="operator@example.test")
    )

    assert principal.roles == frozenset({"operator", "reviewer"})


def test_service_claim_requires_service_mapping(monkeypatch):
    monkeypatch.setenv(
        "COPILOT_CF_ACCESS_ROLE_MAP_JSON",
        json.dumps({"service": {"service_token_ids": ["service-1"]}}),
    )
    principal = admin_auth._principal_from_claims({"sub": "service-subject", "service_token_id": "service-1"})
    assert principal.is_service is True
    assert principal.roles == frozenset({"service"})

    monkeypatch.setenv("COPILOT_CF_ACCESS_ROLE_MAP_JSON", json.dumps({"operator": {"subjects": ["service-subject"]}}))
    with pytest.raises(admin_auth.AdminAuthError) as error:
        admin_auth._principal_from_claims({"sub": "service-subject", "service_token_id": "service-1"})
    assert error.value.code == "service_identity_not_authorized"


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


def test_rbac_policy_metadata_enforces_operator_reviewer_supervisor_admin(monkeypatch):
    app = Flask(__name__)
    policy_bp = Blueprint("policy", __name__)

    @policy_bp.get("/read")
    @admin_auth.require_authenticated
    def read():
        return jsonify({"ok": True})

    @policy_bp.post("/review")
    @admin_auth.require_reviewer
    def review():
        return jsonify({"ok": True})

    @policy_bp.post("/supervisor")
    @admin_auth.require_supervisor
    def write_task():
        return jsonify({"ok": True})

    @policy_bp.post("/admin")
    @admin_auth.require_admin
    def admin_task():
        return jsonify({"ok": True})

    app.register_blueprint(policy_bp)
    admin_auth.install_admin_access_control(app)

    def set_role(role):
        monkeypatch.setattr(
            admin_auth,
            "_verified_principal",
            lambda: admin_auth.AdminPrincipal(role, role, frozenset({role}), "test"),
        )

    client = app.test_client()
    set_role("operator")
    assert client.get("/read").status_code == 200
    assert client.post("/review").status_code == 403
    assert client.post("/supervisor").status_code == 403
    assert client.post("/admin").status_code == 403

    set_role("reviewer")
    assert client.post("/review").status_code == 200
    assert client.post("/supervisor").status_code == 403

    set_role("supervisor")
    assert client.post("/supervisor").status_code == 200
    assert client.post("/admin").status_code == 403

    set_role("admin")
    assert client.post("/admin").status_code == 200


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


def test_route_inventory_distinguishes_manifest_decorator_and_default_protection():
    from app.main import create_app

    rows = admin_auth.inventory_route_policies(create_app())
    assert rows
    assert all(row["policy"] != "unclassified" for row in rows)
    config_rows = [row for row in rows if row["rule"] == "/api/config/llm"]
    assert {(row["policy"], row["policy_source"]) for row in config_rows} == {("admin_only", "manifest")}
    assert admin_auth.route_policy("health.api_health", "GET") == ("public_runtime", "manifest")
    assert admin_auth.route_policy("analyze.api_analyze", "POST") == ("customer_runtime", "manifest")
    assert any(row["policy"] == "default_protected" and not row["explicit_policy"] for row in rows)


@pytest.mark.parametrize(
    ("rule", "method", "expected_policy", "expected_source"),
    [
        ("/api/analyze", "POST", "customer_runtime", "manifest"),
        ("/api/kb/analyze", "POST", "default_protected", "default"),
        ("/api/copilot/context", "POST", "supervisor_write", "manifest"),
        ("/api/copilot/feedback", "POST", "supervisor_write", "manifest"),
        ("/api/copilot/metrics", "GET", "authenticated_read", "manifest"),
        ("/api/feedback", "POST", "customer_runtime", "manifest"),
        ("/api/feedback", "GET", "authenticated_read", "manifest"),
        ("/api/feedback/stats", "GET", "authenticated_read", "manifest"),
        ("/api/live/product/<sku_id>", "GET", "authenticated_read", "manifest"),
        ("/api/live/order/<order_id>", "GET", "authenticated_read", "manifest"),
        ("/api/live/sku/<sku_id>", "GET", "authenticated_read", "manifest"),
        ("/api/live/search", "GET", "authenticated_read", "manifest"),
        ("/api/order/<order_id>", "GET", "authenticated_read", "manifest"),
        ("/api/product/<i_id>", "GET", "authenticated_read", "manifest"),
        ("/api/sku/<sku_id>", "GET", "authenticated_read", "manifest"),
        ("/api/sku/search", "GET", "authenticated_read", "manifest"),
        ("/api/stats", "GET", "authenticated_read", "manifest"),
    ],
)
def test_previous_customer_runtime_routes_have_reviewed_explicit_contract(
    rule,
    method,
    expected_policy,
    expected_source,
):
    from app.main import create_app

    rows = admin_auth.inventory_route_policies(create_app())
    matches = [row for row in rows if row["rule"] == rule and row["method"] == method]
    assert [(row["policy"], row["policy_source"]) for row in matches] == [(expected_policy, expected_source)]


def test_unregistered_routes_are_default_protected_not_public(monkeypatch):
    app = Flask(__name__)

    @app.get("/new-read")
    def new_read():
        return jsonify({"ok": True})

    @app.post("/new-write")
    def new_write():
        return jsonify({"ok": True})

    admin_auth.install_admin_access_control(app)
    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: (_ for _ in ()).throw(admin_auth.AdminAuthError("access_assertion_missing")),
    )
    client = app.test_client()
    assert client.get("/new-read").status_code == 401
    assert client.post("/new-write").status_code == 401
    rows = admin_auth.inventory_route_policies(app)
    assert {(row["method"], row["policy"], row["explicit_policy"]) for row in rows} == {
        ("GET", "default_protected", False),
        ("POST", "default_protected", False),
    }


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


@pytest.mark.parametrize(
    "path",
    [
        "/api/feedback",
        "/api/feedback/stats",
        "/api/copilot/metrics",
        "/api/metrics",
        "/api/stats",
        "/api/order/test-order",
        "/api/product/test-product",
        "/api/sku/test-sku",
        "/api/sku/search?q=test",
        "/api/live/product/test-sku",
        "/api/live/order/test-order",
        "/api/live/sku/test-sku",
        "/api/live/search?q=test",
    ],
)
def test_sensitive_customer_order_and_metrics_reads_require_verified_identity(monkeypatch, path):
    from app.main import create_app

    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: (_ for _ in ()).throw(admin_auth.AdminAuthError("access_assertion_missing")),
    )
    response = create_app().test_client().get(path, headers={"X-User-Role": "admin", "X-User-Name": "spoofed"})
    assert response.status_code == 401


def test_copilot_context_requires_verified_identity(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: (_ for _ in ()).throw(admin_auth.AdminAuthError("access_assertion_missing")),
    )
    assert create_app().test_client().post("/api/copilot/context", json={"message": "test"}).status_code == 401


def test_customer_feedback_post_remains_explicit_customer_entry(monkeypatch):
    from app.main import create_app

    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: (_ for _ in ()).throw(admin_auth.AdminAuthError("access_assertion_missing")),
    )
    response = create_app().test_client().post("/api/feedback", json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "action must be accepted/edited/rejected/escalated"


def test_development_loopback_rejects_tunnel_proxy_and_public_host(monkeypatch):
    app = Flask(__name__)
    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "development_loopback")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "development")
    monkeypatch.setenv("COPILOT_ADMIN_DEV_SUBJECT", "local-dev")
    monkeypatch.setenv("COPILOT_ADMIN_DEV_ROLE", "admin")

    with app.test_request_context("/", base_url="http://127.0.0.1:5011", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert admin_auth._development_principal().roles == frozenset({"admin"})

    for headers, base_url in (
        ({"Cf-Connecting-Ip": "203.0.113.1"}, "http://127.0.0.1:5011"),
        ({"X-Forwarded-For": "203.0.113.1"}, "http://127.0.0.1:5011"),
        ({"Forwarded": "for=203.0.113.1"}, "http://127.0.0.1:5011"),
        ({}, "https://public.example.test"),
    ):
        with app.test_request_context("/", base_url=base_url, headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}):
            with pytest.raises(admin_auth.AdminAuthError) as error:
                admin_auth._development_principal()
            assert error.value.code == "development_auth_not_allowed"

    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "production")
    with app.test_request_context("/", base_url="http://127.0.0.1:5011", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        with pytest.raises(admin_auth.AdminAuthError):
            admin_auth._development_principal()


def test_audit_uses_hmac_actor_id_without_identity_or_credentials(monkeypatch, caplog):
    app = Flask(__name__)
    monkeypatch.setenv("COPILOT_ADMIN_AUDIT_HMAC_KEY", "test-audit-key")
    caplog.set_level(logging.INFO, logger=admin_auth.__name__)
    principal = admin_auth.AdminPrincipal(
        subject="raw-subject-should-not-log",
        display_name="raw-email@example.test",
        roles=frozenset({"admin"}),
        auth_type="cloudflare_access",
        service_token_id="raw-service-token",
    )
    with app.test_request_context(
        "/api/config/llm",
        headers={"Cf-Access-Jwt-Assertion": "raw.jwt.value", "Cookie": "CF_Authorization=raw-cookie"},
    ):
        admin_auth._audit("privileged_action", principal=principal, result="allowed", reason="test")

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "actor_" in message
    assert "raw-subject-should-not-log" not in message
    assert "raw-email@example.test" not in message
    assert "raw-service-token" not in message
    assert "raw.jwt.value" not in message
    assert "raw-cookie" not in message


def test_readiness_requires_allowlist_origins_and_audit_redaction(monkeypatch):
    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "cloudflare_access")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "production")
    monkeypatch.setenv("COPILOT_CF_ACCESS_TEAM_DOMAIN", "access.example.test")
    monkeypatch.setenv("COPILOT_CF_ACCESS_AUD", "test-audience")
    monkeypatch.setenv("COPILOT_CF_ACCESS_ROLE_MAP_JSON", json.dumps({"operator": {"emails": ["op@example.test"]}}))
    monkeypatch.delenv("COPILOT_ADMIN_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("COPILOT_ADMIN_AUDIT_HMAC_KEY", raising=False)

    readiness = admin_auth.admin_auth_readiness()

    assert readiness["admin_auth_ready"] is False
    assert readiness["role_map_configured"] is True
    assert readiness["browser_origin_configured"] is False
    assert readiness["audit_actor_redaction_ready"] is False


def test_readiness_reports_route_governance_only_as_boolean(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "cloudflare_access")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "production")
    monkeypatch.setenv("COPILOT_CF_ACCESS_TEAM_DOMAIN", "access.example.test")
    monkeypatch.setenv("COPILOT_CF_ACCESS_AUD", "test-audience")
    monkeypatch.setenv("COPILOT_CF_ACCESS_ROLE_MAP_JSON", json.dumps({"admin": {"emails": ["admin@example.test"]}}))
    monkeypatch.setenv("COPILOT_ADMIN_ALLOWED_ORIGINS", "https://admin.example.test")
    monkeypatch.setenv("COPILOT_ADMIN_AUDIT_HMAC_KEY", "test-audit-key")

    with create_app().app_context():
        readiness = admin_auth.admin_auth_readiness()

    assert readiness["admin_auth_ready"] is True
    assert readiness["route_policy_ready"] is True
    assert "admin_auth_mode" not in readiness
    assert "access.example.test" not in str(readiness)
    assert "test-audience" not in str(readiness)


def test_production_never_reports_development_loopback_as_ready(monkeypatch):
    monkeypatch.setenv("COPILOT_ADMIN_AUTH_MODE", "development_loopback")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "production")
    monkeypatch.setenv("COPILOT_ADMIN_DEV_SUBJECT", "local-dev")
    monkeypatch.setenv("COPILOT_ADMIN_DEV_ROLE", "admin")

    readiness = admin_auth.admin_auth_readiness()

    assert readiness["admin_auth_ready"] is False
    assert readiness["reason"] == "development_auth_forbidden_in_production"
