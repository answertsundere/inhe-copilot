# ADR 0010: Product Hub Reviewed Fact and Review-Only Media Read Bridge

## Status

Accepted, 2026-08-29.

## Context

The Product Hub contains reviewed, structured product facts and SKU/media
metadata, but the Copilot's formal Product Context Pack currently reads only
the local formal knowledge database and Dynamic JST identity profile. The
result is a real context gap: a correctly resolved order or product identity
does not expose reviewed Hub dimensions, material, installation, or other
structured facts to the existing evidence admission path.

The Hub already owns a stable read-only Agent API based on natural product and
SKU keys. The Hub remains the mutable product-data owner. The Copilot remains a
read-only consumer and cannot infer facts from Hub notes, titles, images, or
unreviewed rows.

## Decision

### Isolated Source Readiness Candidate (2026-09-08)

The default local-knowledge readiness contract is unchanged. A separately
selected `COPILOT_KNOWLEDGE_SOURCE_MODE=product_hub_review_only` candidate may
use the already accepted live Hub bridge without populating local knowledge
with historical or synthetic rows. This is an existing-source configuration,
not a new retrieval or reply owner. It is not approved for runtime promotion.

This mode requires query-only knowledge, reviewed Hub facts, evidence
convergence and the existing model-first Composer review boundary. The local
runtime environment must explicitly be development or test. The local
database must have the required schema and contain no application rows; any
nonempty table, missing schema, changing file or benchmark fixture blocks it.
Unknown source modes also fail closed.

An operator-configured `COPILOT_PRODUCT_HUB_READINESS_SKU` is a connectivity
probe only. The existing exact-SKU reader and field adapter must find at least
one eligible ordinary product-fact candidate. A probe never supplies customer
identity, evidence or reply text, and every actual request still repeats its
own identity, live-source, admission and final checks. No positive result is
cached. Only a loopback Hub is permitted in this initial candidate.

`ready_product_hub_review_only` means limited product-source infrastructure
readiness, not legacy RAG restoration or universal answerability. The public
status remains explicit; full diagnostics contain counts and reason codes, not
probe SKU, fact values, URLs or credentials. Policy, logistics, service actions,
manual interpretation and delivery are not qualified by this probe. Formal
promotion still requires a pinned release and user-facing Pipeline acceptance.

### Exact Identity In Empty-Store Review Mode (2026-09-08)

The same explicit source mode must not route a provided natural SKU through an
empty legacy catalog. The existing ProductIdentityResolver and Hub reader may
prove its current binding using GET /api/agent/skus/:skuCode followed by GET
/api/agent/products/:productCode. Both records must be active, have exact
matching keys and nonempty record IDs. This returns identity only, not facts.

Only an explicit exact SKU is accepted. Canonical repeated SKU candidates must
all agree; a supplied title may only exactly equal the returned name or code.
Other identifiers or a conflicting title are blocked, not silently ignored.
There is no historical/sample catalog, fuzzy title, order or tracking fallback
in this initial candidate mode. Those paths retain separate qualification.
SKU-prefix helpers do not synthesize a JST i_id in this mode; Hub product code
and record ID stay separate from JST/local IDs. Default local mode is unchanged.
Every request repeats live resolution, so a revoked binding is not cached as
valid. Product Context Pack still fetches facts and applies the existing field
and evidence contracts independently. This addendum creates no reply owner,
fact exception, action, handoff, delivery capability or automatic send.

Candidate and native regressions each passed 270 tests; native in-process HTTP
and independent real SKU Context Pack checks passed with no knowledge writes.
Full generated replies and production promotion remain unqualified; synthetic
tests and source checks do not establish real customer accuracy.

### Product-Manual Reference Addendum (2026-09-08)

The user-approved installation correctness slice extends the review-only
media transport below, not fact admission or delivery. For an explicit
`installation` query, the existing reader may resolve an active exact SKU,
read the returned exact active product record, and request only that product's
manual assets through `/api/agent/assets?productCode=...&type=manual`.
This is an exact natural-key filter, not title search or an unfiltered catalog.

Only approved/live PDF records are candidates. Each asset must match the
verified product record ID; a nonempty SKU binding must match the exact Hub
SKU record ID. Lists must be complete within 200 rows, with unique IDs.
Original URLs are constrained to the configured Hub origin, `/api/asset`,
`scope=normalized` and one relative PDF path without traversal, drive/UNC,
double-encoding or arbitrary query parameters. Design sources and videos do
not enter this narrow PDF path.

Before projecting a reference, the same reader checks a five-byte PDF prefix
through the validated original URL, without redirects. PDF MIME and returned
total length must match the catalog contract. A 206 response must describe
exactly bytes 0-4; a 200 fallback is bounded to the same five-byte read. Failed
files are excluded independently. At most three checks start in deterministic
asset-ID order, with a five-second scheduling budget and the existing bounded
per-request timeout; this is not a strict full-chain wall-clock deadline.
Unchecked counts and file failures remain explicit. A nonempty eligible catalog
with no checked file returns unavailable, not successful absence of manuals.
The timestamped header_verified state proves only observed prefix and size,
not whole-file hash integrity, PDF parseability, current applicability or the
continued availability of a mutable source. No content is cached or promoted.

The existing Context Pack uses `product_manual` / `media_reference` and keeps
unbound documents product-scoped. `resolved_sku_code` records lookup provenance,
not universal variant fit. `applicability=needs_review` and
`availability=header_verified` remain explicit. PDF filenames label review
references only; no text, installation steps or factual claims are extracted.
References have no image thumbnail and remain unusable for automatic sending,
canonical selected facts or reply blocks. Other queries retain the prior
exact-SKU image path. This changes no owner, background job or dependency.

Rollback is the two-file source backup or disabling the existing
`COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED` flag. A live file read, appropriate
variant review and formal-pipeline acceptance are still required before
runtime promotion; passing candidate tests or source status alone is not enough.

### Shadow Transport Addendum (2026-09-08)

`answer-context-v1` may be read by the same client under the default-off
`COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED` flag. It is a candidate
transport comparison only: existing identity, field-tuple and media adapters
are reused, and only aggregate counts enter pack stats. No shadow row is merged
into formal evidence or delivery. Unknown optional media types are excluded
without suppressing independently valid facts; identity/review contract errors
remain fail-closed. This adds no owner, registry, node, model call or knowledge
write. The formal two-request read path below remains unchanged.

Add one default-off read-only source inside the existing
`ProductContextPackService`:

```text
trusted identity proof
-> exact Product Hub SKU request when a resolved SKU is available
-> exact Product Hub Agent facts request for the returned product code
-> Product Context Pack candidate
-> existing AdmittedAnswerContextService
-> existing Claim Resolution / Final / Delivery
```

When the existing Product Identity Resolver provides an exact SKU, the bridge first calls only
`GET /api/agent/skus/:skuCode`, requires the returned `sku.skuCode` to equal
the requested SKU exactly, and then uses that response's `productCode` for
`GET /api/agent/products/:productCode/facts`. A JST `i_id` is not assumed to
be a Product Hub `productCode`; when a JST identity has no exact SKU, the Hub
reader produces no candidate. The existing direct product-code request remains
available only for an already-established non-JST internal/Hub product-code
contract. The bridge does not call title search, aliases, bulk snapshots,
product-passport text, semantic search, or knowledge-AI endpoints. SKU-bound
rows normally carry a Hub `skuCode` and are eligible only when it exactly
matches the resolved SKU. The Hub Agent API represents SKU-bound
`parts/配置说明/配件` rows with a record `skuId` plus an `applies` SKU code: such a
row is eligible only when the record ID is present and `applies` exactly matches
the resolved SKU. The record ID is provenance only; it is never treated as a
SKU code or forwarded to model context. Product-level rows may apply to all
variants of that exact product.

The existing order resolver is also an identity proof only for an unambiguous
live JST order item: `status=resolved`, source `jst_order_items`, an exact
non-empty `sku_id`, confidence at least `0.95`, and either the existing
single-item/single-primary-item-with-gifts selection outcome or a single
integration-verified exact outbound-item identifier match. The Product Context
Pack reuses that exact SKU for the Hub SKU request rather than re-mapping it
through the local catalog first. A context-selected multi-item order, a
conflicting SKU signal, or any missing condition remains outside this bypass and
continues through the normal resolver/fail-closed path.

Only confirmed, non-conflicting rows with an exact published field tuple can
become candidates. The initial direct slice is intentionally limited to these
source tuples: material (`material/材质/商品整体/empty unit`), overall dimensions
(`size/尺寸/商品整体/cm`), installation (`installation/安装说明/商品整体/empty
unit`), catalog color options (`color/颜色/商品整体/empty unit`), age range
(`age/适用年龄/商品整体/empty unit`), product load capacity
(`load/承重/商品整体/empty unit`), packaging gross weight (`weight/毛重/包装/kg`), and
SKU-bound catalog configuration (`parts/配置说明/配件/empty unit`). The configuration row must carry either an exact
Hub SKU code and `applies`, or the Agent API's non-empty SKU record ID and an
`applies` value exactly equal to the resolved SKU; it describes the catalog
configuration only and cannot establish shipment completeness. A
type name alone is never enough: a
component dimension, a product-width scalar, a packaging measurement, net
weight, or a nearby free-text field cannot inherit a different tuple's
customer-facing meaning. Multiple eligible color rows from that exact returned
product form one deterministic product-level color-options candidate, with
every source fact retained as provenance. This describes catalog color options
only; it does not assert real-time stock or delivery availability. Component
claims other than the exact SKU-bound catalog configuration, policy, live order
state, images, captions, and free-text source detail remain
outside this direct fact bridge. They retain their
existing owners and must not be inferred from a nearby Hub field.

One narrowly scoped aggregate is also allowed for an authoritative customer
goal whose canonical dimension subject is `packaging`: the three exact Hub
tuples `pack_size/纸箱长/包装/cm`, `pack_size/纸箱宽/包装/cm`, and
`pack_size/纸箱高/包装/cm` may form one deterministic carton-dimensions
candidate. All three rows must be confirmed, non-conflicting, identity-safe,
and agree per axis; missing or disagreeing axes produce no candidate. The
aggregate retains every source fact UID and remains `subject_scope=packaging`.
It can never satisfy a product-overall, component, accessory, or unscoped
dimension goal, and it does not decompose into an individual axis claim.

Each accepted candidate preserves Hub fact UID, source, original confirmation
status, exact identity scope, type, attribute, value, unit, and timestamp. It
maps confirmation to the existing reviewed evidence protocol but keeps the raw
source status as provenance. It never exposes raw source-detail text to the
model. Existing Product Context Pack and
`AdmittedAnswerContextService` eligibility, placeholder, conflict, identity,
claim-type, and risk checks remain authoritative. No second evidence registry,
Graph node, pipeline, reply owner, model call, retry, fallback, or delivery path
is added.

The exact product-overall dimensions tuple is projected as the canonical
`overall_dimensions` attribute while retaining its raw Hub field tuple in
provenance. For an unscoped dimensions request, Claim Resolution may select
that exact product-scoped attribute when every competing admitted legacy record
is unattributed. An explicit product axis, product-overall fact without product
scope, or conflict remains ambiguous or blocked. Packaging/component/accessory
measurements stay outside this unscoped product selection; the bridge never
treats source preference as a universal override.

For a product-level Hub fact reached through an exact SKU lookup, the candidate
also carries that verified SKU as its effective admission scope. This is a
binding assertion, not a rewrite of the source fact: the original Hub product
scope and any original fact SKU scope remain in provenance. No effective SKU
scope is added when the Hub product code was not obtained from the same exact
resolved SKU.

The Hub Agent API must return a stable `facts` array and additive `skuCode` for
SKU-bound rows. The isolated Hub release patch proves that contract before the
Copilot flag is enabled in any runtime.

### Review-only media projection

The same trusted identity proof may independently enable
`COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED=true`. It never falls back to a
product code, title, catalog search, semantic asset search, product passport,
notes, or a bulk asset list. It first verifies the exact natural SKU through
`GET /api/agent/skus/:skuCode`, then calls only
`GET /api/agent/skus/:skuCode/assets`, and requires the response `skuCode` to
equal that resolved SKU exactly. The preceding SKU record binds the returned
assets to one Hub product code; a JST `i_id` is never used as a Hub media key.

Only source statuses `approved` and `live`, known image asset types, and the
Hub's canonical preview route for that exact asset ID are projected. The bridge
does not expose an original download URL, relative file path, canonical source
name, unsupported type, unknown status, video, or an arbitrary external URL.
The narrow type mapping supplies only the existing media-role vocabulary; it
does not derive a fact type from an image label or scene tag.

Every projected item is an existing `media_reference` role with
`reference_only=true`, `can_direct_answer=false`, `usable_for_agent=false`,
`auto_send_level=review`, and `needs_human_review=true`. It is visible to a
reviewer as an exact-SKU candidate only. It cannot enter canonical
`selected_evidence`, answerability, `recommended_assets`, a reply block, or a
delivery plan. Existing media delivery eligibility remains the sole path that
can attach a customer-facing asset; this slice deliberately does not satisfy
that eligibility.

## Consequences

- Ordinary supported product questions can eventually receive exact reviewed
  facts through the same formal evidence flow rather than a model-only fallback.
- Product Hub availability or contract errors produce no Hub candidate and do
  not cause title fallback or a synthetic fact.
- A wrong or missing exact SKU mapping fails closed rather than treating a JST
  internal product identifier as a Hub product code.
- The default flag is off. This ADR does not enable Formal Evidence Convergence,
  change `can_send`, send media, write either knowledge database, or authorize
  autonomous replies.
- The separate media flag can surface only review-only candidates after exact
  SKU proof; it does not grant media delivery, fact admission, or a new owner.

## Rollback

Set `COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED=false`. This removes the Hub
reader at the Product Context Pack boundary and leaves all existing identity,
retrieval, admission, safety, media, and delivery behavior unchanged.

Set `COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED=false`. This separately removes
only the review-only Hub image candidates. It does not affect Hub fact reads,
local media assets, evidence, reply blocks, or delivery behavior.
