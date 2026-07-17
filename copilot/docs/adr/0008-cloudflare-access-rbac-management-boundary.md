# ADR 0008: Cloudflare Access And RBAC Management Boundary

## Status

Accepted, 2026-07-16.

## Context

The public `/ask/*` Tunnel reaches the local Flask origin, but a Tunnel is
transport only: it does not prove who requested a management endpoint. The
origin previously trusted `X-User-Role` and `X-User-Name`, so any client able
to reach it could claim a privileged role. Configuration reads were also
available without authentication.

## Decision

Cloudflare Access is the identity provider for management requests. The origin
accepts only a verified `Cf-Access-Jwt-Assertion`: PyJWT verifies the RS256
signature using the configured Access JWKS endpoint, issuer, application
audience, expiry, not-before time, key ID, and required subject claim. JWKS
keys use PyJWT's bounded cache; missing configuration, unknown keys, network
errors, and parse errors deny access.

The application maps verified email, group, subject, or verified service-token
claims through an environment-only allowlist to `operator`, `reviewer`,
`supervisor`, `admin`, or `service`. An Access-authenticated human that does
not match this allowlist is denied; there is no implicit `operator` fallback.
Request role/name headers are never an identity source. Management routes use
an endpoint-and-method registry, with decorator metadata for already-decorated
handlers and a `default_protected` supervisor boundary for new or unlisted
routes. The registry distinguishes an explicit policy from the default rather
than treating a non-empty fallback as route review. Policies are:

- public runtime health and version/readiness;
- only the formal customer analysis POST and feedback POST entry points;
- authenticated read;
- reviewer write for review decisions;
- supervisor write for operational changes; and
- admin-only configuration and system management.

`/api/copilot/context` and `/api/copilot/feedback` are supervisor operations;
an approved service identity may use them only through the explicit local path
allowlist. Order, product, SKU, live-query, metric, feedback-list, and stats
endpoints require a verified identity and cannot be anonymous customer routes.

Browser write methods require a configured same-site Origin or Referer. A
verified service identity bypasses this browser-only check only when its route
is explicitly allowed by configuration. A loopback development mode is allowed
only in a development/test runtime with explicit local subject and role, a
loopback remote address and Host, and no Cloudflare or forwarded-client header;
it is not a Tunnel or production fallback.

Readiness reports non-sensitive authentication status and fails closed when a
production Access configuration is absent, including a non-empty role map,
browser-origin allowlist, and audit HMAC key. Security events are token-free
and record an HMAC-pseudonymised actor ID, role set, route, method, trace ID,
result, and reason code; they never record the raw subject, email, service
token ID, assertion, or cookie.

Public health, version, and readiness endpoints are liveness-only. They return
no database filename, size, fingerprint, schema detail, knowledge count,
feature flag, process metadata, Access configuration detail, or role-map
detail. `GET /api/admin/runtime/diagnostics` is explicitly `admin_only` in the
endpoint-and-method registry and owns detailed, still secret-free runtime
diagnostics. QA database consistency checks must use authenticated diagnostics
or a local read-only readiness service, never an anonymous public response.

For the current mixed caller model, the preferred external Access deployment is
path-scoped management protection rather than a blanket `/ask/*` policy: the
SPA/admin paths and management APIs require Access, while the two explicitly
reviewed customer POST endpoints retain their application-layer contract. Both
public hostnames must receive equivalent Access policies until a separately
reviewed canonical-domain migration occurs.

## Alternatives Considered

- Trust Cloudflare-added role headers: rejected because direct-origin or Tunnel
  requests can forge them.
- Trust only the assertion header's presence: rejected because an assertion
  must have a valid signature and registered claims.
- Add an application password or `AUTH_DISABLED` switch: rejected because it
  creates a second, easily misconfigured identity authority.
- Move access checks into LangGraph: rejected because authentication and RBAC
  are HTTP/application boundary concerns, not Agent reasoning.

## Business And Safety Consequences

- Configuration reads, model connection tests, review data, media operations,
  and evaluation operations no longer accept anonymous or self-declared roles.
- Customer analysis contracts, Evidence Convergence, Agent reply generation,
  `can_send`, and delivery blocks are unchanged.
- Public liveness remains available, but it cannot claim runtime readiness when
  the management authentication configuration is unsafe.
- Cloudflare Access policy configuration remains an external deployment step;
  source code cannot create or validate a dashboard application by itself.

## Migration And Rollback

Set `COPILOT_ADMIN_AUTH_MODE=cloudflare_access` with the local team-domain,
audience, role-map, and allowed-origin configuration before exposing management
routes. Configure a Cloudflare self-hosted Access application to protect the
management path and a minimal service token policy for approved automation.

Rollback is limited to disabling the Access application only after the origin
is no longer publicly reachable. Do not roll back to trusted role headers. The
local development mode is not a public rollback mechanism.

## Verification

- Route inventory reports endpoint/method policy, source (`manifest`,
  `decorator`, or `default`), and explicitness; unregistered routes remain
  protected rather than becoming public.
- Tests cover valid and invalid signed assertions, unknown key IDs, forged role
  headers, RBAC, service allowlists, CSRF, config protection, and readiness.
- Public runtime endpoints remain reachable without management credentials;
  `/api/analyze` retains its existing business-authentication behavior.
- The public readiness projection contains only `ready`, `status`, and redacted
  reason codes; detailed database diagnostics require an admin identity.

## References

- Cloudflare Access JWT validation:
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- Cloudflare service tokens:
  https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- OWASP Authorization Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- OWASP CSRF Prevention Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
