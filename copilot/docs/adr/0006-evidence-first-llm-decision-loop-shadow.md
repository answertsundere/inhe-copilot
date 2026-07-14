# ADR 0006: Evidence-First LLM Decision Loop Shadow

## Status

Accepted for shadow evaluation, 2026-07-14.

## Context

The current response and optional semantic audit can observe a mixed product
pack containing reviewed facts, reference-only FAQ, placeholders, service
actions, media candidates, and shadow guidance. Candidate presence is not a
safe answer qualification. Compound questions can also be compressed into one
fact type, which hides evidence gaps for safety or moisture claims.

## Decision

Introduce one deterministic `AdmittedAnswerContextService` as the owner of
answer-context role separation and direct-fact eligibility. Grounded Reasoning
reuses its direct-product admission and final semantic payloads expose only its
admitted direct facts and unresolved claims.

Add a post-graph `AgentDecisionProposalService` behind
`COPILOT_LLM_DECISION_SHADOW_ENABLED`. The service uses a separately configured
and qualification-gated strict JSON Schema or strict tool-call provider for
claim understanding plus tool planning and for the final proposal. Between the
two schema calls, the application may execute only existing registered local
read-only product-resolution and retrieval tools. Order and media requests are
explicitly deferred until bounded shadow adapters exist. The proposal is recorded under
evidence debug and answer trace, but it cannot change the formal reply,
delivery, review decision, media blocks, or `can_send`. The Pipeline's existing
shadow mutation guard remains authoritative.

Phase 0.5A remains post-graph and can use both the existing graph's candidates
and the bounded shadow lookup results. A pre-retrieval model-directed formal
tool loop is a separate future decision because it would change formal stage
ownership and latency.

The shadow proposal uses a Partial Answer Contract. The application computes a
claim resolution for every requested claim before the proposal call. A
supported resolution requires admitted direct evidence and a confirmed clause;
an unresolved or conflicting resolution requires a pending clause and cannot be
rendered as a positive fact. The provider must copy the deterministic
resolutions, so it cannot use fluent wording to conceal an evidence gap or let
one unresolved claim suppress an unrelated supported fact.

## Alternatives considered

1. Pass the complete product pack to the model: rejected because candidate,
   reference, action, and media roles can be mistaken for direct facts.
2. Let prompts enforce evidence safety: rejected because prompts cannot replace
   identity, review-state, conflict, authorization, and delivery checks.
3. Replace the current formal generation path immediately: rejected because the
   shadow has no real-trace promotion evidence and structured-output provider
   compatibility can fail.
4. Add more phrase-specific fallback templates: rejected because paraphrases
   and compound claims require structured understanding rather than sample
   branching.

## Consequences

- Direct product facts, policy facts, service actions, and media candidates have
  explicit non-interchangeable output buckets.
- Material composition cannot resolve material safety or moisture resistance.
- Invalid or truncated schemas and unknown evidence references produce no free-text proposal.
- An unqualified provider records its blocking reason for the internal preview
  and produces no candidate reply.
- The optional final semantic model no longer receives `matched_facts` as if
  every candidate were selected evidence.
- Strict structured output adds two optional model calls and, when requested,
  bounded local read-only lookups while the shadow flag is enabled. Formal
  latency is unchanged while the flag is disabled.

## Safety and rollback

The formal decision fields are frozen before the shadow call and restored if a
shadow implementation mutates them. Disabling the environment flag removes the
new model calls. The admission helper is read-only and performs no retrieval,
database writes, delivery, refunds, replacements, or platform actions.

The provider client rejects a `finish_reason=length` response rather than
attempting to repair or parse its partial content.

## Verification

Tests cover scoped reviewed facts, ineligible roles, placeholders, identity
mismatch, unreviewed FAQ, conflicts, compound claims, invalid schemas, send
field injection, unknown evidence UIDs, unsupported assertions, paraphrases,
semantic payload isolation, and formal-field mutation restoration.
