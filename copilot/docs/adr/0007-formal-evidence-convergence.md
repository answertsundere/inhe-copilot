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

The supervisor partial-answer preview remains review-only. It is fixed to
`can_send=false` and `requires_human_review=true`. It consumes only the
Minimal Decision Context and records a stable claim UID for every supported,
unresolved, conflicting, or explicitly prohibited claim. A supported clause
must cite admitted evidence; unresolved and conflicting clauses remain visible
without being turned into facts. When the strict provider is unqualified, the
application renders the same admitted claim outcomes deterministically rather
than fabricating structured or free-text model output. The preview is never
passed into final orchestration and cannot alter a formal response.

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

## Real-Derived Positive Validation Gate

Synthetic fixtures prove only the deterministic contract. Before any supervisor
preview can be considered for promotion, a query-only export must derive a
versioned, pseudonymous fixture from published direct product fields. The
export records a source snapshot hash, table fingerprints before and after the
read, provenance hashes, and a privacy scan; it never copies source identities,
titles, URLs, row IDs, or source-database contents into Git.

The vertical slice seeds an isolated temporary fixture database and executes
the same Product Context Pack, formal convergence, admitted context, claim
resolution, and preview path. It is not allowed to inject a fixture fact into
admitted evidence directly. Every confirmed preview clause must cite a selected
evidence UID, while the preview remains review-only with `can_send=false`.
Missing attribute scope or packaging-contaminated dimensions are data-quality
gaps, not grounds to relax evidence admission.
