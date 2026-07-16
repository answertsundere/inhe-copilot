"""Cloudflare Access authentication and application RBAC for management routes.

The origin never trusts caller-supplied role or user-name headers.  Cloudflare
Access proves identity with ``Cf-Access-Jwt-Assertion``; this module verifies
that assertion and maps verified claims to local, least-privilege roles.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

import jwt
from flask import Response, g, jsonify, request


logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ADMIN_ROLES = frozenset({"admin"})
SUPERVISOR_ROLES = frozenset({"supervisor", "admin"})
REVIEWER_ROLES = frozenset({"reviewer", "supervisor", "admin"})
ALL_HUMAN_ROLES = frozenset({"operator", "reviewer", "supervisor", "admin"})
_ASSERTION_HEADER = "Cf-Access-Jwt-Assertion"
_JWK_CLIENTS: dict[tuple[str, str], jwt.PyJWKClient] = {}


@dataclass(frozen=True)
class AdminPrincipal:
    subject: str
    display_name: str
    roles: frozenset[str]
    auth_type: str
    service_token_id: str = ""

    @property
    def is_service(self) -> bool:
        return self.auth_type == "service"


@dataclass(frozen=True)
class AdminAuthError(Exception):
    code: str
    status_code: int = 401


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_team_domain() -> str:
    value = _text(os.environ.get("COPILOT_CF_ACCESS_TEAM_DOMAIN"))
    return value.removeprefix("https://").removeprefix("http://").rstrip("/")


def _expected_issuer() -> str:
    explicit = _text(os.environ.get("COPILOT_CF_ACCESS_ISSUER"))
    if explicit:
        return explicit.rstrip("/")
    domain = _normalized_team_domain()
    return f"https://{domain}" if domain else ""


def _role_mapping() -> dict[str, dict[str, set[str]]]:
    """Parse a local allowlist without accepting a caller-provided role."""
    raw = _text(os.environ.get("COPILOT_CF_ACCESS_ROLE_MAP_JSON"))
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    mapping: dict[str, dict[str, set[str]]] = {}
    for role, selectors in payload.items():
        if role not in ALL_HUMAN_ROLES | {"service"} or not isinstance(selectors, dict):
            continue
        mapping[role] = {
            key: {_text(item).lower() for item in values if _text(item)}
            for key, values in selectors.items()
            if key in {"emails", "groups", "subjects", "service_token_ids"}
            and isinstance(values, list)
        }
    return mapping


def _claim_groups(claims: dict[str, Any]) -> set[str]:
    values = claims.get("groups") or claims.get("group") or []
    if isinstance(values, str):
        values = [values]
    return {_text(value).lower() for value in values if _text(value)}


def _service_token_id(claims: dict[str, Any]) -> str:
    for key in ("service_token_id", "serviceTokenId"):
        value = _text(claims.get(key))
        if value:
            return value
    return ""


def _principal_from_claims(claims: dict[str, Any]) -> AdminPrincipal:
    subject = _text(claims.get("sub"))
    email = _text(claims.get("email")).lower()
    service_token_id = _service_token_id(claims)
    if not subject and not email:
        raise AdminAuthError("identity_claim_missing")

    mapping = _role_mapping()
    groups = _claim_groups(claims)
    roles: set[str] = set()
    for role, selectors in mapping.items():
        if (
            email and email in selectors.get("emails", set())
        ) or (
            subject and subject.lower() in selectors.get("subjects", set())
        ) or (
            service_token_id and service_token_id.lower() in selectors.get("service_token_ids", set())
        ) or groups.intersection(selectors.get("groups", set())):
            roles.add(role)

    if service_token_id:
        if "service" not in roles:
            raise AdminAuthError("service_identity_not_authorized", 403)
        return AdminPrincipal(
            subject=subject or service_token_id,
            display_name=subject or "service",
            roles=frozenset({"service"}),
            auth_type="service",
            service_token_id=service_token_id,
        )

    # A verified human remains a least-privilege operator unless the allowlist
    # grants a stronger role.
    human_roles = roles.intersection(ALL_HUMAN_ROLES) or {"operator"}
    return AdminPrincipal(
        subject=subject or email,
        display_name=email or subject,
        roles=frozenset(human_roles),
        auth_type="cloudflare_access",
    )


class CloudflareAccessJwtVerifier:
    """Use PyJWT's maintained JWK client with a bounded in-process cache."""

    def _client(self, team_domain: str, jwks_url: str) -> jwt.PyJWKClient:
        key = (team_domain, jwks_url)
        client = _JWK_CLIENTS.get(key)
        if client is None:
            client = jwt.PyJWKClient(
                jwks_url,
                cache_keys=True,
                max_cached_keys=16,
                cache_jwk_set=True,
                lifespan=300,
                timeout=5,
            )
            _JWK_CLIENTS[key] = client
        return client

    def verify_assertion(self, assertion: str) -> AdminPrincipal:
        team_domain = _normalized_team_domain()
        audience = _text(os.environ.get("COPILOT_CF_ACCESS_AUD"))
        issuer = _expected_issuer()
        if not team_domain or not audience or not issuer:
            raise AdminAuthError("access_configuration_missing")
        if not assertion:
            raise AdminAuthError("access_assertion_missing")

        jwks_url = f"https://{team_domain}/cdn-cgi/access/certs"
        try:
            signing_key = self._client(team_domain, jwks_url).get_signing_key_from_jwt(assertion)
            claims = jwt.decode(
                assertion,
                signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                options={"require": ["exp", "nbf", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AdminAuthError("access_assertion_expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise AdminAuthError("access_assertion_not_yet_valid") from exc
        except jwt.InvalidAudienceError as exc:
            raise AdminAuthError("access_assertion_audience_invalid") from exc
        except jwt.InvalidIssuerError as exc:
            raise AdminAuthError("access_assertion_issuer_invalid") from exc
        except jwt.PyJWKClientError as exc:
            raise AdminAuthError("access_assertion_key_unavailable") from exc
        except jwt.InvalidTokenError as exc:
            raise AdminAuthError("access_assertion_invalid") from exc
        except (OSError, ValueError) as exc:
            raise AdminAuthError("access_assertion_verification_failed") from exc
        return _principal_from_claims(claims)


def _development_principal() -> AdminPrincipal:
    runtime_env = _text(os.environ.get("COPILOT_RUNTIME_ENV")).lower()
    remote_addr = _text(request.remote_addr)
    if runtime_env not in {"development", "test"} or remote_addr not in {"127.0.0.1", "::1"}:
        raise AdminAuthError("development_auth_not_allowed")
    subject = _text(os.environ.get("COPILOT_ADMIN_DEV_SUBJECT"))
    role = _text(os.environ.get("COPILOT_ADMIN_DEV_ROLE")).lower()
    if not subject or role not in ALL_HUMAN_ROLES:
        raise AdminAuthError("development_auth_configuration_missing")
    return AdminPrincipal(subject=subject, display_name=subject, roles=frozenset({role}), auth_type="development")


def _verified_principal() -> AdminPrincipal:
    cached = getattr(g, "_admin_principal", None)
    if cached is not None:
        return cached

    mode = _text(os.environ.get("COPILOT_ADMIN_AUTH_MODE") or "cloudflare_access").lower()
    if mode == "cloudflare_access":
        principal = CloudflareAccessJwtVerifier().verify_assertion(_text(request.headers.get(_ASSERTION_HEADER)))
    elif mode == "development_loopback":
        principal = _development_principal()
    else:
        raise AdminAuthError("admin_auth_mode_invalid")
    g._admin_principal = principal
    return principal


def _audit(event: str, *, principal: AdminPrincipal | None = None, result: str, reason: str = "") -> None:
    """Emit a token-free audit event for the existing application log sink."""
    logger.info(
        "admin_security_audit event=%s result=%s subject=%s roles=%s path=%s method=%s trace_id=%s reason=%s",
        event,
        result,
        (principal.subject if principal else "anonymous")[:128],
        ",".join(sorted(principal.roles)) if principal else "",
        request.path,
        request.method,
        _text(request.headers.get("X-Request-Id"))[:128],
        reason[:96],
    )


def _denied(error: AdminAuthError) -> Response:
    _audit("authentication_failed", result="denied", reason=error.code)
    return jsonify({"error": "authentication_required", "reason": error.code}), error.status_code


def _allowed_origins() -> set[str]:
    configured = _text(os.environ.get("COPILOT_ADMIN_ALLOWED_ORIGINS"))
    origins = {part.strip().rstrip("/") for part in configured.split(",") if part.strip()}
    if _text(os.environ.get("COPILOT_RUNTIME_ENV")).lower() in {"development", "test"}:
        origins.update({"http://127.0.0.1:5011", "http://127.0.0.1:5012", "http://127.0.0.1:5173", "http://127.0.0.1:5174"})
    return origins


def _request_origin() -> str:
    origin = _text(request.headers.get("Origin"))
    if origin:
        return origin.rstrip("/")
    referer = _text(request.headers.get("Referer"))
    if not referer:
        return ""
    parsed = urlparse(referer)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _csrf_allowed(principal: AdminPrincipal) -> bool:
    if request.method in SAFE_METHODS or principal.is_service or principal.auth_type == "test":
        return True
    origin = _request_origin()
    return bool(origin and origin in _allowed_origins())


def _roles_allow(principal: AdminPrincipal, allowed_roles: frozenset[str]) -> bool:
    return bool(principal.roles.intersection(allowed_roles))


def current_principal() -> AdminPrincipal:
    return _verified_principal()


def current_role() -> str:
    principal = current_principal()
    for role in ("admin", "supervisor", "reviewer", "service", "operator"):
        if role in principal.roles:
            return role
    return "operator"


def current_user_name() -> str:
    return current_principal().display_name


def has_any_role(*roles: str) -> bool:
    return _roles_allow(current_principal(), frozenset(roles))


def _require(allowed_roles: frozenset[str], privilege: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            try:
                principal = current_principal()
            except AdminAuthError as error:
                return _denied(error)
            if not _roles_allow(principal, allowed_roles):
                _audit("authorization_denied", principal=principal, result="denied", reason=privilege)
                return jsonify({"error": "authorization_denied"}), 403
            if not _csrf_allowed(principal):
                _audit("authorization_denied", principal=principal, result="denied", reason="csrf_origin_invalid")
                return jsonify({"error": "csrf_validation_failed"}), 403
            _audit("privileged_action", principal=principal, result="allowed", reason=privilege)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_authenticated(fn: Callable) -> Callable:
    return _require(ALL_HUMAN_ROLES, "authenticated_read")(fn)


def require_reviewer(fn: Callable) -> Callable:
    return _require(REVIEWER_ROLES, "manual_review")(fn)


def require_supervisor(fn: Callable) -> Callable:
    return _require(SUPERVISOR_ROLES, "supervisor_operation")(fn)


def require_admin(fn: Callable) -> Callable:
    return _require(ADMIN_ROLES, "system_administration")(fn)


def admin_auth_readiness() -> dict[str, Any]:
    mode = _text(os.environ.get("COPILOT_ADMIN_AUTH_MODE") or "cloudflare_access").lower()
    runtime_env = _text(os.environ.get("COPILOT_RUNTIME_ENV") or "production").lower()
    access_audience_configured = bool(_text(os.environ.get("COPILOT_CF_ACCESS_AUD")))
    access_domain_configured = bool(_normalized_team_domain())
    insecure_header_auth_disabled = True
    development_mode_valid = (
        mode == "development_loopback"
        and runtime_env in {"development", "test"}
        and bool(_text(os.environ.get("COPILOT_ADMIN_DEV_SUBJECT")))
        and _text(os.environ.get("COPILOT_ADMIN_DEV_ROLE")).lower() in ALL_HUMAN_ROLES
    )
    cloudflare_ready = mode == "cloudflare_access" and access_audience_configured and access_domain_configured
    ready = cloudflare_ready or development_mode_valid
    reason = ""
    if not ready:
        reason = "admin_auth_configuration_missing" if mode == "cloudflare_access" else "admin_auth_mode_not_ready"
    if mode == "development_loopback" and runtime_env == "production":
        ready = False
        reason = "development_auth_forbidden_in_production"
    return {
        "admin_auth_mode": mode,
        "admin_auth_ready": ready,
        "access_audience_configured": access_audience_configured,
        "insecure_header_auth_disabled": insecure_header_auth_disabled,
        "reason": reason,
    }


_PUBLIC_ENDPOINTS = {"health.api_health", "runtime.runtime_version", "runtime.runtime_readiness"}
_CUSTOMER_ENDPOINT_PREFIXES = ("analyze.", "copilot.", "order.", "feedback.", "live_query.")
_ADMIN_ONLY_ENDPOINT_PREFIXES = ("config.",)
_REVIEW_ENDPOINT_FRAGMENTS = ("review", "approve", "reject", "decision")
_SYSTEM_ADMIN_PATHS = {"/api/kb/ai-center/rebuild-rag"}


def route_policy(endpoint: str | None, path: str, method: str) -> str:
    """Classify every matched route without using caller-controlled input."""
    if endpoint in _PUBLIC_ENDPOINTS:
        return "public_runtime"
    if endpoint and endpoint.startswith(_CUSTOMER_ENDPOINT_PREFIXES):
        return "customer_runtime"
    if endpoint and endpoint.startswith(_ADMIN_ONLY_ENDPOINT_PREFIXES):
        return "admin_only"
    if path in _SYSTEM_ADMIN_PATHS:
        return "admin_only"
    if method in SAFE_METHODS:
        return "authenticated_read"
    if any(fragment in (endpoint or "") for fragment in _REVIEW_ENDPOINT_FRAGMENTS):
        return "reviewer_write"
    return "supervisor_write"


def _service_path_allowed(path: str) -> bool:
    allowed = [part.strip() for part in _text(os.environ.get("COPILOT_ADMIN_SERVICE_ALLOWED_PATHS")).split(",") if part.strip()]
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in allowed)


def enforce_management_route_policy() -> Response | None:
    endpoint = request.endpoint
    if endpoint is None:
        return None
    policy = route_policy(endpoint, request.path, request.method)
    g.admin_route_policy = policy
    if policy in {"public_runtime", "customer_runtime"}:
        return None
    try:
        principal = current_principal()
    except AdminAuthError as error:
        return _denied(error)

    if principal.is_service and _service_path_allowed(request.path):
        if not _csrf_allowed(principal):
            return jsonify({"error": "csrf_validation_failed"}), 403
        _audit("service_identity_used", principal=principal, result="allowed", reason=policy)
        return None

    allowed_roles = {
        "authenticated_read": ALL_HUMAN_ROLES,
        "reviewer_write": REVIEWER_ROLES,
        "supervisor_write": SUPERVISOR_ROLES,
        "admin_only": ADMIN_ROLES,
    }[policy]
    if not _roles_allow(principal, allowed_roles):
        _audit("authorization_denied", principal=principal, result="denied", reason=policy)
        return jsonify({"error": "authorization_denied"}), 403
    if not _csrf_allowed(principal):
        _audit("authorization_denied", principal=principal, result="denied", reason="csrf_origin_invalid")
        return jsonify({"error": "csrf_validation_failed"}), 403
    if policy != "authenticated_read":
        _audit("privileged_action", principal=principal, result="allowed", reason=policy)
    return None


def install_admin_access_control(app: Any) -> None:
    """Install one app-level policy so missed decorators fail closed."""
    app.before_request(enforce_management_route_policy)


def inventory_route_policies(app: Any) -> list[dict[str, Any]]:
    """Return a deterministic, read-only inventory for tests and diagnostics."""
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: (item.rule, item.endpoint)):
        methods = sorted(rule.methods.difference({"HEAD", "OPTIONS"}))
        if not methods:
            continue
        rows.append({
            "rule": rule.rule,
            "endpoint": rule.endpoint,
            "methods": methods,
            "policy": route_policy(rule.endpoint, rule.rule, methods[0]),
        })
    return rows
