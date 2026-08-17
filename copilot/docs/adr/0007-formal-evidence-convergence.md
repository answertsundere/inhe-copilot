# ADR 0007: Formal Evidence Convergence

## Status

Accepted, 2026-07-15.

## Context

`ProductContextPackService` can assemble reviewed, product-scoped structured
facts, but the formal graph previously treated the pack only as a candidate
source. Retrieval and evidence filtering could gate those candidates without
ever emitting canonical `selected_evidence`. Consequently generation, final
audit, trace, and snapshot could not consistently identify the facts eligible
for the current reply.

## Decision

`AdmittedAnswerContextService` remains the single reusable admission contract.
The existing `evidence_builder` node may opt in through
`COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED`. It passes already-gated retrieval
candidates and Product Context Pack candidates to that service, then emits a
deterministic canonical `selected_evidence` list from admitted direct product,
direct policy, and completed read-only operational facts. Operational facts are
restricted to explicit `order` or `logistics` scope and remain a distinct role;
they are not promoted into product knowledge.

The canonical selection is the only additional factual input that formal
generation may consume while the flag is enabled. It preserves evidence UID,
source, review status, identity scope, fact type, attribute key, original value,
and provenance. Existing RAG and Pack duplicates deduplicate by their shared
origin evidence key, falling back to evidence UID, in a stable order.

The following roles or states never enter canonical selected evidence:

- `service_action`, `fallback_only`, `media_reference`, and Answer Memory;
- placeholder, reference-only, blocked, or non-direct candidates;
- missing, mismatched, or namespace-incompatible product identity;
- insufficient review status; and
- candidates blocked by an attribute conflict.

A live tool result enters only as `operational_fact_direct` when the tool
execution is completed and read-only, the scope is exactly `order` or
`logistics`, the claim type is compatible, the value is non-placeholder, and
direct-answer permission is explicit. A planned, failed, write-capable, or
unscoped tool result remains excluded. This amendment does not admit service
actions or media references and does not grant delivery authority.

The same service also produces a bounded `minimal_decision_context` for the
strict Decision Proposal shadow. It contains requested claims, compact
conversation summary, resolved identity, admitted evidence, unresolved or
conflicting claims, non-factual actions/media, read-only tools, channel
capabilities, and safety constraints. It excludes full traces, full candidate
stores, historical Answer Memory copy, benchmark answers/rubrics, and private
reasoning.

The supervisor partial-answer preview is review-only by default. With explicit
`COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED` opt-in, final orchestration may
promote the same bounded preview to a formal partial answer. That narrow path
remains fixed to `can_send=false` and `requires_human_review=true`. It consumes only the
Minimal Decision Context and records a stable claim UID for every supported,
unresolved, conflicting, or explicitly prohibited claim. A supported clause
must cite admitted evidence; unresolved and conflicting clauses remain visible
without being turned into facts. When the strict provider is unqualified, the
application renders the same admitted claim outcomes deterministically rather
than fabricating structured or free-text model output. A promoted answer may
retain a supported clause while keeping unresolved or conflicting clauses
visible for review; it cannot make the reply sendable or alter evidence
eligibility. Language or semantic fallback must preserve frozen supported
clause text and its evidence UID, then rerun final and semantic audit. If that
preservation fails, the response stays fail-closed rather than replacing the
fact with a generic handoff.

Claim/evidence selection is attribute-aware: an explicit `attribute_key` can
only use evidence or conflicts with the same canonical key. A missing evidence
attribute does not satisfy an explicit request. When an unqualified request has
multiple attribute candidates, the result is `selection_ambiguous` rather than
an arbitrary combination. The preview evaluator accepts raw requested claims,
admitted facts, conflicts, and context only; expected outcomes are scored after
the actual claim-resolution and Minimal Decision Context path completes. Its
copy and safety checks fail closed on final-audit failure, semantic-fit failure,
diagnostic exceptions, mojibake, internal jargon, identity leakage, or a media
promise without an attached reply block.

## Consequences

- LangGraph keeps orchestration responsibility; it does not become an Evidence
  Registry or a second Pipeline.
- Final orchestration remains the sole owner of final delivery decisions.
- This decision does not relax `can_send`, media, identity, review, or conflict
  requirements.
- Read-only operational facts can support an order/logistics clause but cannot
  write formal knowledge, satisfy a product fact, or authorize a side effect.
- API, copilot, replay, and benchmark reach the same graph stage through the
  existing AnalysisPipeline.

## Rollback

Set `COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=false` or remove the variable.
The evidence-builder node then emits no canonical selection and formal
generation retains its preceding behavior. No data migration or knowledge-base
write is involved.

## Verification

Tests cover direct Pack/RAG admission, role and gate rejection, identity and
review rejection, whole-group conflict blocking, deterministic deduplication,
minimal-context exclusion, partial claim resolution, and feature-flag-off
behavior. Trace and snapshot persistence observe the selected evidence emitted
by the graph response.

## Claim And Media Fail-Closed Boundaries

Material composition is a separate claim from material safety. A reviewed
direct composition field can support only composition; safety, non-toxicity,
food-grade, formaldehyde, certification, child suitability, child safety,
pinch safety, stability, and load claims each require reviewed, direct,
identity-matched evidence for that same claim. An unresolved high-risk claim
keeps the formal response in human review with an empty sendable reply.

Cleaning and moisture are product-specific operational claims, not material
aliases. A composition field, generic service action, Answer Memory,
unreviewed FAQ, or media reference cannot authorize washing, soaking, alcohol,
temperature, detergent, mould, or moisture conclusions. Those operations need
reviewed, direct, identity-matched evidence whose fact type and attribute slot
match the requested claim.

For accidental bite or ingestion, composition remains only a supporting
clause. Without dedicated safety evidence, the response says to stop use or
contact, directs swallowing or symptoms to a doctor, and does not diagnose
toxicity or assert non-toxicity.

Media remains a delivery reference, not a product fact. For dimensions and
space fit, an automatically attached image must be approved/usable, share an
exact identity namespace with the current product, declare a size-chart or
dimension-reference role, and appear in the current reply blocks. Appearance,
SKU, packaging, component, and display images cannot satisfy that contract.

## Formal QA Gate

`app.services.fact_type_alias_service` owns the canonical high-risk claim
registry and its aliases. Admission, final auditing, and the read-only formal
answer evaluator normalize through that same registry; ordinary `material`
remains a composition claim and cannot support a safety, toxicity, food-grade,
formaldehyde, suitability, certification, load, stability, electrical, or
small-parts assertion.

The evaluator accepts only the versioned
`formal-answer-validation-dataset-v1` schema. Its expected outcomes are
scorer-only and never enter an Agent API payload. Invalid, empty, legacy, or
unknown-risk datasets fail before any request with exit code `2`. A completed
run exits `0` only when every request succeeds and every case passes; safety,
HTTP, timeout, parse, or response-contract failures exit `1` while preserving
a structured report.

Reports identify the runner and deployed runtime independently, including
dataset hash/version, sanitized API URL, UTC timestamps, public feature-flag
states, and an optional read-only SQLite schema fingerprint. They deduplicate
mirrored `selected_evidence` containers by evidence UID, but retain a duplicate
within one source container as a contract error. The QA gate evaluates safety
and delivery contracts; it is not a general product-accuracy claim.

Formal QA also requires a ready runtime before it issues any Agent request. The
runtime reports its configured knowledge database through a read-only readiness
contract: required tables, non-empty knowledge/chunk/KBQA counts, a
`content_sha256` of the actual database file, and a `schema_fingerprint` of the
sorted table names. `content_sha256` is the authoritative identity check;
`schema_fingerprint` only detects schema differences. A false readiness state,
an optional local `content_sha256` mismatch, a missing runtime
`content_sha256`, or a changed-during-scan result is a precondition failure
with exit code `2`, not a synthetic `rag_miss` result.

## Real-Derived Positive Validation Gate

Synthetic fixtures prove only the deterministic contract. Before any supervisor
preview can be considered for promotion, a query-only export must derive a
versioned, pseudonymous fixture from published direct product fields. A
real-derived fixture and manifest both declare `source_kind=real_derived`, a
non-empty source snapshot hash, sanitization version, `query_only=true`, and
`source_database_mutated=false`. The vertical slice validates both files,
including fixture SHA-256, before it creates an isolated database. A synthetic
fixture must declare `source_kind=synthetic` and is rejected by this runner.
The export records table fingerprints before and after the read, provenance
hashes, and a privacy scan; it never copies source identities, titles, URLs,
row IDs, or source-database contents into Git.

The vertical slice seeds an isolated temporary fixture database and executes
the same Product Context Pack, formal convergence, admitted context, claim
resolution, and preview path. It is not allowed to inject a fixture fact into
admitted evidence directly. Every confirmed preview clause must cite a selected
evidence UID, while the preview remains review-only with `can_send=false`.
Missing attribute scope or packaging-contaminated dimensions are data-quality
gaps, not grounds to relax evidence admission.

Real-derived fixture export and Product-first generation reuse the same
placeholder semantics before a fact reaches formal admission. The filter rejects
verification copy, pending values, detail-page or physical-item disclaimers,
and spread variants where explanatory words appear between a negation and a
claim. It does not reject concrete values such as a material, dimension, gross
weight, or either detachable state. A product whose only value for a low-risk
fact is a placeholder is not eligible for the fixture, because the fixture must
demonstrate reviewed product truth.

As of 2026-07-16, the current runtime inventory does not contain five products
with all four required reviewed low-risk facts. The real-derived promotion gate
is blocked by product data. A synthetic 5-by-4 fixture may prove the convergence
and preview code path only; it must never be reported as real-derived success
or used to enable the formal production flag.

## Phase 0.8C Contract Clarification

Product Context Pack compaction must preserve an already explicit structured
field protocol: field review/verification, direct-answer permission, product or
SKU scope, fact and attribute identity, and provenance. Compaction may not infer
that protocol from `source_type`, a table name, product publication status, or
text. `AdmittedAnswerContextService` still performs the authoritative role,
review, identity, claim, placeholder, and conflict checks.

A query-only runtime snapshot contained 393 products with at least one eligible
fact and 428 eligible facts. The Phase 0.8C fixture applies a minimum contract of
five products, one fact per product, 15 facts total, and three fact types. Its
deterministic coverage selection produced 12 products and 15 facts across
material, dimensions, and gross weight. It records the reduced coverage
honestly: `detachable` is absent and dimension attribute-slot coverage remains
incomplete. The isolated vertical slice passed 15/15 and all seven
invalid-evidence controls without mutating formal knowledge or changing a formal
reply.

The API closure keeps non-factual roles outside canonical selected evidence.
`service_action` remains action guidance and `media_reference` remains a media
candidate; neither can support a product claim or create an actual image/video
reply block. An actual media block additionally requires an approved, usable,
fact-type-compatible asset with an exact shared identity namespace. Recommended
assets alone never prove delivery. Blocked, unresolved high-risk, audit-failed,
or non-fact-only responses are normalised to `can_send=false`,
`requires_human_review=true`, and an empty sendable reply.

The isolated 5012 gate then passed all three 1x1 probes and the 5-product by
3-question slice passed 15/15. Direct low-risk facts were selected and admitted;
mixed questions retained supported clauses plus unresolved high-risk claims;
media/service-only questions selected no factual evidence and attached no media.
All 18 probes remained review-only, protected database counts were unchanged,
and the versioned benchmark remained 5/5 and 22/22 with zero auto-send cases.
This is a capability and delivery-contract result, not real-customer accuracy.
The rollback boundary remains
`COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=false`; 5011 keeps that value, and
Evidence Action remains paused and unqualified.

## Formal Knowledge Read Boundary

Formal Evidence Convergence consumes published knowledge but does not own any
knowledge mutation. Agent API, Analysis Pipeline, Product Context Pack,
admission, final audit, readiness, and evaluation replay are read owners.
Explicit governance and synchronization workflows are the writable owners.

Phase 0.8G.1 found that an evaluation application boot also launched the
resident DingTalk media refresh. That background path explicitly invokes the
database-updating media synchronization script and commits `kb_product` rows.
The earliest owner classification is therefore `application_background_write`,
not `analyze_request_write` and not a fingerprint false positive.

Isolated evaluation runtimes enforce `PRAGMA query_only=ON` on every pooled
formal-knowledge connection and do not launch resident media refresh/sync.
Optional DML observation is diagnostic-only and excludes SQL text, parameters,
and business values. Any DML attempt is a failed evaluation contract even when
SQLite blocks the statement.

Formal-table mutation checks use SQLite backup snapshots and canonical
row-level keyed fingerprints. They include schema and row counts and report only
pseudonymous row identities, changed column names, and before/after hashes.
Whole-file SQLite hashes are not accepted as evidence of a knowledge-content
change because storage pages, WAL state, statistics, and unrelated tables can
change independently. This read boundary does not alter evidence admission,
reply generation, safety gates, or the production feature flag.
