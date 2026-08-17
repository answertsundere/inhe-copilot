# Dynamic Product Fact Read Contract Design

## Status

Approved direction for P1 formal-evidence supply. This design does not enable
Autonomous Send and does not add a new Graph node, service, model call, reply
owner, cache, or writable integration.

## Problem

Color, weight, dimensions, package data, and SKU attributes are mutable business
data. Reviewing a copied list of values proves only one historical snapshot and
does not prove that the Agent will read the current value later. The reusable
capability is a strict read contract around the authoritative product container:
resolve one durable identity, read the current record, preserve its version and
scope, and fail closed when the requested value is absent or ambiguous.

The existing `ProductContextPackService` already opens a new database session
for every request and is the formal product-first retrieval owner. It therefore
remains the only entry point for this slice. The design closes observability and
scope gaps inside that path instead of introducing another retriever.

## Considered Approaches

### 1. Strengthen the existing Product Context Pack read contract (selected)

Read the current published `KBProduct` on every request, carry record version,
update time, exact product/SKU scope, and a value digest into structured
evidence, and make evidence identity change when the source value changes.

This is the smallest change, preserves current owners, and provides a stable
contract that a future approved live-source adapter can satisfy.

### 2. Query JST or another external product API for every product question

This can be fresher, but current JST support is focused on orders and logistics,
does not authoritatively expose every product attribute, adds latency and
availability failure, and belongs to the separately gated P2 live-source work.
It is not selected for this P1 slice.

### 3. Periodically copy all external values into local knowledge

This is operationally simple but turns freshness into an implicit scheduler
contract and can make stale values appear current. It remains a possible source
adapter implementation, not the Agent read contract.

## Ownership And Data Flow

```text
canonical product/SKU identity
-> ProductContextPackService
-> exact published KBProduct lookup
-> current structured profile snapshot
-> ProductStructuredEvidenceService
-> versioned, scope-bound evidence candidate
-> existing Evidence Admission / Claim Resolution / Composer / Final / Audit
-> Supervisor Assist only (can_send=false)
```

- Product identity resolution owns `i_id` and SKU selection.
- `ProductContextPackService` owns the current database read and profile
  projection. It must not cache facts across requests.
- `ProductStructuredEvidenceService` owns field selection and immutable evidence
  provenance. It does not infer missing values.
- Existing downstream owners retain admission, reasoning, reply, audit, and
  delivery authority.

## Read Contract

1. Product identity uses exact `i_id` or an exact SKU belonging to one published
   product. Product title is not authoritative when a durable identity exists.
2. Every request reads a fresh database session. A changed source value must be
   visible on the next request without a process restart.
3. The structured profile carries `source_version` and `source_updated_at` from
   the selected row. Model-facing evidence also carries those fields plus a
   SHA-256 value digest; it does not expose database paths.
4. Evidence identity includes the source version and value digest. Two values
   cannot share a canonical evidence UID merely because they came from the same
   product field.
5. Product-level fields may answer product-level claims. SKU-list fields may
   answer only the selected SKU or, when the request contains only the base
   product identity, return an explicit multi-variant result.
6. An exact variant request that has no matching SKU row must not borrow another
   variant's value.
7. Missing, deleted, placeholder, conflicting, unpublished, or identity-mismatched
   data produces no direct-answer evidence.
8. High-risk fields keep their existing evidence and safety rules. This design
   does not make every database field answerable merely because it exists.

## Mutable-Data Semantics

The database container is responsible for business truth and publication. The
Agent is responsible for faithfully reading the current published state. A
write that returns a record to `pending_review` remains unavailable until the
existing lifecycle republishes it; this is a source-authority state, not an
Agent-side value review.

The prior 30-item color/weight shortlist is therefore diagnostic only. It is not
a prerequisite for this read-contract qualification and no row is auto-approved.

## Failure And Safety Behavior

- Database/import failure: return the existing unavailable pack; do not reuse a
  previous value.
- Missing exact product identity: return `no_product_identity`.
- Missing requested field: return `missing_product_fact`.
- Exact SKU absent or ambiguous: emit no SKU-scoped direct evidence.
- Source value changes during separate requests: each request remains internally
  consistent; the newer request receives a different evidence UID.
- Formal knowledge writes, Product Context Pack cache writes, and `can_send`
  changes remain zero.

## Qualification

Deterministic tests must prove:

- value A is read, then an authoritative database update to value B is visible
  on the next request without restart;
- value deletion removes direct evidence rather than returning A;
- evidence UID and value digest change from A to B;
- exact `i_id` and exact SKU scope are preserved;
- a different SKU cannot satisfy the requested variant;
- base-product queries can still describe multiple explicit variants;
- unpublished and identity-mismatched records remain unavailable;
- source version/update time survive into the evidence candidate;
- no database write, cache, Graph, model call, reply owner, or send authority is
  added.

Synthetic tests prove only the read contract. Real customer accuracy remains
`null`, and Supervisor Assist remains review-only.

## Rollback

The change is limited to additional profile/evidence provenance and stricter SKU
field selection inside the two existing services. Reverting that commit restores
the previous projection. No schema migration or feature flag is required.
