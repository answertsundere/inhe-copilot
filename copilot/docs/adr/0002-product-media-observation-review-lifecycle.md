# ADR 0002: Product Media Observation Review Lifecycle

## Status

Accepted, 2026-07-12.

## Context

The offline Product Media Observation worker can extract low-risk visual
observations from approved product media. A model extraction is neither a
reviewed product fact nor a media-delivery instruction. Writing it directly to
`KBProduct`, `KnowledgeEntry`, or `KBMediaAsset` would blur model output,
human approval, and published knowledge.

## Decision

Use dedicated staging tables for immutable model candidates and append-only
review events. Candidate state is limited to `pending_review`,
`approved_shadow`, `rejected`, `invalidated`, and `superseded`.

- Model output, media hash, model/prompt/schema versions, and original payload
  hash are immutable candidate provenance.
- A supervisor may approve as-is, edit-and-approve, reject, or invalidate.
  Human edits are separate review fields and every action creates an audit
  event.
- Approval re-reads media bytes and requires the observed SHA-256, current
  media status, and product identity to still match. A changed asset is
  invalidated and cannot be overridden.
- `approved_shadow` remains review-only. It has no `published`,
  `direct_answer_allowed`, `used_for_generation`, or `can_change_can_send`
  state and is not queried by Product Evidence Pack, Grounded Reasoning, or
  reply delivery.
- The local Qwen worker remains an offline bounded extractor. Its latency and
  model output never enter a synchronous customer request.

## Rationale

Label Studio separates imported model predictions from human annotations, and
Argilla separates suggestions from human responses. Their shared lesson is to
keep versioned machine output inspectable while retaining a distinct human
decision record. The project reuses its existing supervisor RBAC and
knowledge-review audit conventions, but not the formal knowledge tables:
those tables own publishable customer-facing facts, while this lifecycle owns
untrusted visual observations.

## Alternatives Considered

1. **Write observations directly to `KBProduct.specs_json`**: rejected because
   it would make unreviewed model output look like formal truth.
2. **Reuse `KnowledgeEntry` drafts**: rejected because its lifecycle includes
   publication and retrieval semantics that this shadow workflow must not have.
3. **Keep only JSON reports**: rejected because there is no durable reviewer,
   optimistic-locking, invalidation, or append-only audit history.
4. **Auto-approve high-confidence or repeatable output**: rejected because
   model stability is not human verification.

## Consequences

The review UI can inspect candidates and history without changing the formal
knowledge base. A later ADR is required before `approved_shadow` observations
can enter a Product Evidence Pack shadow trace, and another promotion decision
is required before any formal generation use. The first lifecycle introduces
two staging tables, not a new service or queue.

## Migration And Rollback

The tables are additive SQLite staging tables. Rollback consists of removing
the API/UI exposure and, after retaining required audit evidence, deleting only
the staging tables. No formal knowledge row or customer decision needs rollback
because this phase never writes or reads those tables from the formal pipeline.

## Verification

Verification requires table-level DML protection, SHA-256 invalidation tests,
RBAC and optimistic-lock tests, staging-import idempotency tests, and a
pipeline-isolation regression. Repeatability remains an explicit promotion
block: a model must meet the documented extraction stability threshold before
any later shadow-evidence integration is considered.

Execution, completion/schema, and semantic admission are separate diagnostic
layers. Transport failures and malformed completions never become
`rejected_evidence`; they block the batch independently and keep the worker in
offline shadow mode.

The runtime qualification is also isolated from the lifecycle. The existing
vLLM 0.11.0 worker failed the bounded plain-JSON stability gate, while an
independent vLLM 0.12.0 image pinned by digest passed the ten-image single and
paired qualification. That result makes the candidate suitable for further
offline shadow operation; selecting it as a default worker is a separate
operational change and cannot alter candidate state, approval, or publication.
