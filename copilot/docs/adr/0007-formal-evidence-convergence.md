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
deterministic canonical `selected_evidence` list from admitted direct product
and direct policy facts only.

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
