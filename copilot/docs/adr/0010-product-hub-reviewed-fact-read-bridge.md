# ADR 0010: Product Hub Reviewed Fact Read Bridge

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
rows must carry a Hub `skuCode` and are eligible only when it exactly matches
the resolved SKU; product-level rows may apply to all variants of that exact
product.

The existing order resolver is also an identity proof only for an unambiguous
live JST order item: `status=resolved`, source `jst_order_items`, an exact
non-empty `sku_id`, confidence at least `0.95`, and the existing single-item or
single-primary-item-with-gifts selection outcome. The Product Context Pack
reuses that exact SKU for the Hub SKU request rather than re-mapping it through
the local catalog first. A context-selected multi-item order, a conflicting SKU
signal, or any missing condition remains outside this bypass and continues
through the normal resolver/fail-closed path.

Only confirmed, non-conflicting rows with a supported structured type and a
recognized structural scope can become candidates. The first slice maps only
unambiguous low-risk fact families already represented by existing FactTypes:
material composition, product dimensions, and installation. Gross weight is
deferred until its fact-type and subject-scope semantics have an explicit
bridge. Packaging, component, accessory, color, age, load, policy, live order
state, images, captions, and free-text source detail remain outside this initial
direct fact bridge. They retain their existing owners and must not be inferred
from a nearby Hub field.

Each accepted candidate preserves Hub fact UID, source, original confirmation
status, exact identity scope, type, attribute, value, unit, and timestamp. It
maps confirmation to the existing reviewed evidence protocol but keeps the raw
source status as provenance. It never exposes raw source-detail text to the
model. Existing Product Context Pack and
`AdmittedAnswerContextService` eligibility, placeholder, conflict, identity,
claim-type, and risk checks remain authoritative. No second evidence registry,
Graph node, pipeline, reply owner, model call, retry, fallback, or delivery path
is added.

For a product-level Hub fact reached through an exact SKU lookup, the candidate
also carries that verified SKU as its effective admission scope. This is a
binding assertion, not a rewrite of the source fact: the original Hub product
scope and any original fact SKU scope remain in provenance. No effective SKU
scope is added when the Hub product code was not obtained from the same exact
resolved SKU.

The Hub Agent API must return a stable `facts` array and additive `skuCode` for
SKU-bound rows. The isolated Hub release patch proves that contract before the
Copilot flag is enabled in any runtime.

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
- A later media vertical slice must separately prove reference, approval,
  identity, usability, and delivery-block contracts.

## Rollback

Set `COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED=false`. This removes the Hub
reader at the Product Context Pack boundary and leaves all existing identity,
retrieval, admission, safety, media, and delivery behavior unchanged.
