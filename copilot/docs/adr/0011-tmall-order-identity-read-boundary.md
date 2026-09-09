# ADR 0011: Tmall Order Identity Read Boundary

## Status

Accepted, 2026-08-31.

## Context

The sidecar can supply a Tmall external order reference while the Copilot needs
an exact JST SKU before Product Hub facts can enter the existing Product Context
Pack. The standard JST OpenAPI order endpoint excludes Taobao and Tmall online
order data. The sales-outbound endpoint can expose external order or item
identifiers for some account and fulfillment paths, but its `so_ids` parameter
is only a retrieval hint: a result is usable only when a returned order-level
or item-level identifier exactly equals the requested value. A real read-only
check with the configured account confirmed that the existing exact paths can
also return a safe miss for a valid sidebar reference.

The JST documentation makes the boundary explicit:

- [Order query](https://open.jushuitan.com/document/2125.html) excludes Taobao
  and Tmall order data from the standard OpenAPI.
- [Sales outbound query](https://open.jushuitan.com/document/2227.html) may
  expose outbound fields that can carry an exact external order or item
  identifier, subject to account and channel permissions. Its filter cannot be
  trusted without validating the returned field.

Treating a non-empty response, a nearby title, a substring, a first result, or
an internal `i_id` as identity proof can associate one customer's question with
another order or product. That is worse than an explicit unresolved result.

## Decision

The existing `lookup_order_by_identifier` boundary remains the only order
identity entry used by the current Pipeline. Every OpenAPI result must contain
exactly one exact match in the requested identity field before it is usable.
No list result, title match, substring, approximate date window, or first row
may promote product identity.

A Sidecar may preserve an explicit `shop_name` or `shop_id` as channel-routing
context. It is not order identity, product identity, or evidence. When paired
with an explicit order reference, an exact unique enabled JST shop ID may
constrain a direct outbound lookup and permit a bounded recent outbound scan.
A display name must first resolve through `shops/query` to exactly one enabled
shop ID before it can constrain or expand a lookup. A zero, multiple-match, or
temporarily unavailable display label is not a usable scan scope: it may not
select a shop or enable an unscoped row-list scan, but it also cannot suppress
the existing exact `o_id`/`so_id` and direct outbound identifier queries. Those
queries still require a returned exact identifier-field match; after they miss,
the resolver returns the scope reason instead of expanding its search. Shop
context alone can never trigger a query, select a product, widen a global scan,
or infer an SKU.

For a Tmall external order reference, there are four supported identity
sources:

1. The existing sales-outbound API returns one exact verified order-level or
   item-level external identifier. A direct `so_ids` query is attempted first;
   only an explicit order reference plus exact unique shop scope may permit the
   bounded recent scan after a direct miss. A single integration-verified exact
   outbound-item match may project only that returned item's exact SKU through
   the existing order-item policy; it never selects a neighboring item in a
   multi-item order. The scan has a fixed page limit and returns an explicit
   incomplete result rather than an unbounded search or a false miss.
2. The channel adapter provides a trusted JST internal order ID or exact SKU.
   The existing JST resolver and Product Hub bridge consume it unchanged.
3. A default-disabled, offline-built JST snapshot projection may expose one
   exact external order-item reference only when its identity-only manifest,
   schema, record count, and content hash validate at runtime. The projection
   is generated outside this repository from a historical export and includes
   only an opaque record UID plus exact `outer_oi_id`, SKU, and internal product
   code. Its v2 schema may also include an HMAC-SHA256 of a typed JST internal
   order reference; the raw reference and secret are never stored in the
   projection. A v2 match remains valid only when it resolves exactly one
   eligible item. It never exposes buyer data, shipping status, tracking
   fields, notes, titles, raw payloads, or the historical export itself. A
   unique exact item or v2 HMAC reference match may seed only the existing
   exact-SKU -> Product Hub fact-read path; it is not a current-order,
   logistics, service-action, or delivery source. Repeated historical rows with
   the same exact item/SKU/internal-code tuple are deterministically
   deduplicated; a reference with more than one distinct SKU/internal-code tuple
   remains ambiguous. Malformed, absent, ambiguous, or hash-mismatched data is
   rejected.
4. A future, default-disabled channel adapter may query an already
   user-authenticated JST web session in read-only mode and return a compact,
   schema-validated exact identity result. It may run only with an explicit
   feature flag and a live user session. It must not store passwords, cookies,
   browser profiles, raw order payloads, or page responses in this repository.

The optional snapshot and web-session adapters are channel/identity adapters,
not Graph
node, reply owner, evidence registry, retriever, or delivery path. It may
return only the minimal order identity and, for a live session only, the live
logistics fields needed by the existing resolver. Product facts still require the existing exact SKU ->
Product Hub natural-key -> Product Context Pack -> admission flow. It may not
use title search, free-text notes, images, semantic similarity, or model
inference to fill a missing SKU.

## Alternatives Considered

- Continue unscoped or unbounded OpenAPI scans: rejected. They can neither
  prove an identity nor fit the interactive request budget. The accepted
  bounded scan is available only after an explicit reference and exact shop
  scope, then still requires a returned exact identity-field match.
- Reuse an old web script with embedded credentials: rejected. Credentials and
  persisted browser state are not valid Copilot configuration or an auditable
  runtime boundary.
- Treat JST `i_id` as a Product Hub product code: rejected by ADR 0010 because
  the namespaces are different.
- Match product titles or SKU notes heuristically: rejected because it does
  not prove the customer's ordered variant.

## Business And Safety Consequences

- A customer may receive an explicit review-only unresolved response when no
  trusted order identity is available, but never an answer grounded on another
  customer's order or product.
- The optional adapter is read-only and feature-disabled by default.
- Formal Evidence Convergence, media delivery, reply blocks, Safety Gate, and
  `can_send` are unchanged. Missing identity cannot be hidden by fluent model
  output.
- Sidecar improvements should prioritize structured `order_identifier_type`,
  exact shop scope, JST internal order ID, and exact SKU extraction at the
  channel boundary.

## Migration And Rollback

### Manual Native Conversation Preview Addendum (2026-09-09)

The owner approved a local manual QianNiu import into the existing real-test
page. The existing desktop adapter owns native UIA traversal and message/card
boundaries; the existing Sidecar blueprint owns its opt-in transport. It uses
`COPILOT_QIANNIU_MANUAL_READ_ENABLED=false` by default, existing human
authentication and CSRF checks, and an additional direct-loopback boundary.
Forwarded/public calls and service identities cannot capture the desktop.
No per-platform Agent, new Graph node, model call, or send owner is added.

The endpoint returns only the selected conversation's bounded preview to the
requesting local seat with no-store caching. It never updates the legacy global
Sidecar status/latest cache, persists a transcript, or calls analyze. Native
window/conversation bindings must survive the read; missing/ambiguous speaker
or body metadata remains an explicit error. Historical staff may be recognized
only from the platform speaker header within the bound shop namespace, not
from buyer message content or a fixed nickname whitelist. An operator must
confirm the preview; no historical customer tail is treated as a new event.

Native buyer/shop binding requires selected controls, not list membership.
Multiple order documents are ambiguous; a single document is still not evidence
of buyer ownership. The current native reader omits its order/product identifiers
until a platform ownership binding is available. The generic preview contract
can retain verified-origin but identity-unverified candidates from future
qualified captures, without giving them evidence status. The page
requires explicit order selection before copying an order reference into its
existing manual input; it does not promote a sidebar specification label or
native product code into an exact SKU. Generation remains a separate user
action through the existing canonical Pipeline with mandatory human review.
Rollback disables the flag; existing Agent/JST/Hub behavior is unchanged.

### Assisted Document Review Addendum (2026-09-09)

The owner-approved manual import may explicitly request
`mode=manual_document_review`. Omitted mode remains `native_selection`;
there is no automatic fallback from a failed native binding.

- The same default-off flag, authenticated direct-loopback boundary, CSRF
  protection, bounded private subprocess and canonical parser apply.
- A stable single message document supplies historical speaker labels, not
  verified current-customer identity. Conflicting native selection, mixed
  speakers/shops, unknown content and changed snapshots remain blocked.
- The seat must re-enter the displayed buyer and shop and acknowledge the
  document before importing. This is manual context selection, not platform
  authentication, a native inbound event or an authoritative Gold approval.
- All captured turns remain historical; a fresh local conversation replaces
  prior context, and the current question stays empty for manual entry.
- Unbound orders/products are never offered. Buyer labels remain transient
  local preview data, not Agent payload or stored identity. Import never
  generates, fills or sends a reply; existing Safety/Delivery owners remain.

Rollback uses the existing default-off manual-read flag. Automatic current-client
binding and customer-switch/reconnect qualification remain unresolved.

No snapshot or runtime web-session lookup is enabled by this ADR. The offline
snapshot lookup remains controlled by
`COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED=false` by default; rollback sets it
to false and removes its projection directory from the candidate runtime. A
future web-session lookup must be controlled by
`COPILOT_JST_WEB_ORDER_LOOKUP_ENABLED=false` by default. Either rollback leaves
the existing exact OpenAPI lookup and Product Hub reader unchanged.

## Verification

- Unit tests prove that `o_id`, `so_id`, outbound identifiers, and outer
  transaction identifiers reject nonmatching or ambiguous rows; scoped scans
  can reach a later page only after direct lookup misses and reject ambiguous
  shop labels before querying orders.
- A live OpenAPI diagnostic records only success/miss classifications, field
  presence counts, and paths; it does not retain raw order or customer data.
- Before an optional web-session adapter can be enabled, it needs a manually
  authenticated-session canary, exact-match/multi-match/session-missing tests,
  privacy projection checks, and a formal Pipeline review-only candidate with
  `can_send=false`.
- Snapshot fallback tests prove manifest/hash/schema rejection, duplicate exact
  item fail-closed behavior, identity-only state propagation, and exact SKU
  scoping before a Product Hub read. The builder is an offline tool and the
  runtime never opens its raw input export.
