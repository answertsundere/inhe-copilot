# ADR 0009: Agent Core Capability Mainline

## Status

Accepted, 2026-07-23.

## Context

The project has established useful contracts for one formal Pipeline, evidence
roles, product identity, final safety, media delivery, replay isolation, runtime
readiness, and shadow-module containment. These contracts reduced unsafe
delivery risk.

Development nevertheless became dominated by qualification matrices, review
workbenches, synthetic pass rates, and successive shadow layers. Most candidate
capabilities remain disabled, real-customer accuracy is still unknown, formal
evidence convergence is disabled in production, and the answer path still has
multiple text owners. Passing another evaluator does not by itself improve a
customer conversation.

Mature customer-service systems separate channel operations and control-plane
work from the answering core. Strong model-agent systems likewise keep
orchestration thin, provide compact task context and typed tools, and measure
complete task outcomes rather than graph size or one preferred sentence. The
existing research notes already record these patterns; no new framework is
required.

## Decision

The active development mainline is one end-to-end Agent Core capability loop:

```text
canonical customer turn
-> compact conversation/product/order context
-> model-led customer goals
-> identity plus read-only knowledge/live tools
-> admitted evidence and unresolved claims
-> one model-first customer reply
-> deterministic safety/delivery gate
-> reply or durable handoff
```

Near-term development must improve this loop on pinned, privacy-safe real
conversations. The primary scorecard is:

- supported-claim correctness and evidence attribution;
- customer goal and service-action completion;
- unnecessary handoff rate;
- unsupported high-risk or media claims;
- non-empty, progressive, human-sounding replies;
- tool success and context continuity; and
- p50/p95 latency and error rate.

Synthetic benchmarks remain regression evidence. They cannot establish real
accuracy or justify a capability claim.

LangGraph remains the stateful orchestration runtime, but no new graph node is
allowed unless durable state, retry, branching, pause/resume, or recovery
requires it. Reasoning, context construction, evidence admission, reply
composition, safety, and delivery retain their existing application owners.

Turn understanding uses the existing single semantic-classification call to
produce atomic, typed goals. Explicit customer needs become `customer_goal`
items and feed canonical `requested_claims`; supporting facts remain
`evidence_dependency`, while actions and contextual constraints retain their
own kinds. The deterministic boundary validates, deduplicates, and orders these
items without inventing a new FactType. Each customer goal is anchored to a
verified span of the current customer turn; downstream diagnostics retain only
the span position and hash, not another copy of customer text. Missing or
invalid goal structure is observable and fails closed for that goal.

The model-first composer projects customer goals and admitted evidence to
anonymous stable references. Its strict output is one clause per customer goal:
`goal_ref`, `clause_kind`, `text`, and `evidence_refs`. Supported clauses must
cite exactly their admitted evidence; unresolved, conflicting, or prohibited
goals must return an unresolved clause without evidence. Supporting-only
evidence dependencies are not customer goals. The application validates the
complete goal set and renders the verified clauses in stable order without
adding fallback wording. This remains one model call and review-only; it cannot
change `can_send`, delivery, evidence admission, or final safety ownership.

The disabled model-first candidate has four explicit reply-stage owners:

1. `ModelFirstAnswerComposerService` is the only model-first customer-reply
   generator.
2. `FinalAnswerAuditor` applies the deterministic Final Contract. It validates
   goal/clause/evidence references, canonical truth, high-risk boundaries,
   service-action completion, media eligibility, privacy/process leakage, and
   prerequisites for `can_send`. This candidate branch makes zero model calls.
3. `FinalSemanticQualityService` owns the candidate's one Unified Textual Audit.
   It evaluates factual faithfulness, unresolved polarity, goal coverage,
   conversation continuity, query/reply fit, serious repetition, and internal
   process language against `canonical_truth` plus bounded
   `conversation_continuity`. Provider or schema failure blocks the candidate.
4. `FinalResponseOrchestrator` owns sequence, state synchronization, and
   fail-closed delivery only. It does not generate or rewrite a model-first
   candidate reply.

Historical agent turns remain non-authoritative for product, policy, order, and
action-completion facts. A historical factual conflict cannot override
canonical truth, while a candidate that relies on unsupported history still
fails closed.

The legacy production path is retained as `legacy`: it may still use its
existing deterministic/LLM polish and fallback behavior. That compatibility
path is not the target ownership model and must not be cited as evidence that
the candidate has multiple reply generators.

This boundary does not promote the Composer or change delivery permission.
Formal Evidence Convergence and the model-first Composer remain disabled by
default. A reviewable, feature-disabled candidate checkpoint is not production
qualification. After P0 correctness is established, development moves to real
long-conversation customer quality rather than more protocol qualification
layers.

P0-R1 established that correctness boundary. The existing MiniMax-M3
`json_object` transport passed a three-input, one-call-per-input preflight, and
the only permitted fixed-eight run passed Composer, Deterministic Final
Contract, and Unified Textual Audit `8/8` with complete goal, supported, and
unresolved coverage. No alternative transport, retry, repair, new model call,
or new owner was introduced. Formal feature flags remain disabled; the next
decision gate is P1 Gold Conversation Quality, not production promotion.

Phase 1.9 adds a canonical answer-eligibility projection without adding a
router, graph node, model call, or safety gate. Owner boundaries are fixed:
Turn Understanding owns goal status; canonical context resolution owns
reference status; Tool Router and Executor own tool requirement/completion;
Claim Resolution owns support and inference requirement; and deterministic
Claim/Safety code combines a versioned Domain Policy Pack with canonical risk
rules. Minimal Decision Context only projects those verdicts. Missing output is
`unknown`, never implicitly safe.

Domain Policy Packs are strict data files selected only by explicit structured
metadata. They may contain claim-level risk, inference, direct-fact, and
freshness policy. They may not contain product facts, identities, customer
text, scenario identifiers, or reply templates. Product truth continues to
come from admitted evidence. The diagnostic
`fast_path_preconditions_complete` field does not enable Fast Path; every
request still follows the existing Pipeline and final gate.

Phase 1.9.1 closes the eligibility trust boundary without changing that
decision. A qualifying customer goal must retain canonical goal identity,
claim type, valid Turn Understanding status, and current-message source-span
provenance. `query_fact_type` compatibility fallbacks are degraded retrieval
inputs, not customer goals. Public `copilot_context` cannot assert canonical
conversation resolution or select a Domain Pack: the Pipeline strips its
reserved owner key and accepts only a separate versioned internal contract with
an allowed source and fixed provenance boundary. Domain Packs remain trusted
deployment/evaluation data plugins rather than Agent routing rules.

Phase 1.9.2 closes the remaining customer-goal injection path. Public
`copilot_context.turn_understanding` is removed in full and cannot assert
requested claims, customer goals, reply controls, goal status, query fact type,
or required fact types. The current server
classifier creates a fresh owner result and deterministically writes an empty
`requested_claims` list when it finds no customer goal, so old public state
cannot survive. Eligibility also requires the owner provenance and recomputes
the source-span SHA-256 from the exact slice of the current normalized buyer
message. A well-formed digest from another message, an out-of-range span, or an
extra claim field fails closed. This is provenance validation only; it adds no
semantic inference or model call.

`ToolSpec.freshness_class` remains deterministic registry metadata consumed by
eligibility. It is excluded from LLM Tool Planner metadata, preserving the
pre-Phase-1.9 planner prompt and tool-selection behavior. No graph node, model
call, router, safety gate, or delivery permission is added by this closure.

Phase 1.10.1 qualifies the conservative eligibility contract without promoting
Fast Path. `source_span_sha256` is parsed only as an exact 64-character
hexadecimal field and is recomputed from the canonical current-message span;
the free-text privacy sanitizer is unchanged. Any requested or resolved
supporting evidence dependency blocks eligibility. A single canonical customer
goal must bind through its supported resolution to exactly one admitted direct
fact after the existing origin deduplication, with claim type, attribute, and
identity scope aligned. Zero facts fail with
`single_direct_evidence_not_verified`; multiple independent facts fail with
`multiple_direct_evidence_present`.

The frozen qualification dataset remains version `1.0.0` with 30 positive and
40 negative cases and a fixed dataset hash. It must pass original, reverse, and
fixed-seed ordering with no formal knowledge DML. This is an eligibility
precondition only: it adds no Composer, graph branch, model call, final-gate
bypass, formal reply mutation, or `can_send` authority.

P1.2b keeps bounded low-risk inference inside the same ownership chain. Domain
Pack data defines eligible premise families, qualitative scope, maximum
`low`/`medium` risk, required qualifiers, prohibited extensions, and mandatory
human review. Its representative gate showed that requiring Turn
Understanding to nominate a policy before Claim Resolution could expose any
candidate made the option denominator zero.

P1.2c preserves the ownership chain but separates option eligibility from
semantic selection. Claim Resolution owns the deterministic intersection of
trusted Domain Pack policies, admitted direct premises, authoritative goal,
risk, context capabilities, and conflict state. It emits goal-scoped
`eligible_policy_options` and does not select one. A valid trusted intent may
narrow the set; a missing intent leaves the safe set available without
authorizing inference. The existing Composer owns the zero-or-one selection
and language. Deterministic Final validates the selected policy against the
offered set, policy provenance, premises, scope, risk ceiling, review-only
metadata, qualifiers, and prohibitions; Unified Textual Audit validates textual
faithfulness. Service, media, dependency, contextual, conflicting, and
high-risk goals remain ineligible.

This does not add a service, graph node, model call, reply owner, safety gate,
or production flag. P1.2c made one live representative request without a
separate preflight or retry. Provider execution, one Composer call, goal
coverage, direct-fact preservation, and both audits succeeded, but the formal
context contained no bounded inference policies. Claim Resolution therefore
reported `bounded_inference_policy_reference_missing` and produced an option
denominator of `0/0`. The gate stopped before the remaining three cases, the
16-case set, or synthetic benchmark. The implementation is a disabled,
review-only contract checkpoint with status
`bounded_inference_shadow_not_qualified`; the next earliest owner is existing
Domain Pack owner-context propagation into Evidence Builder, not a new
reasoning component or policy-intent generator.

P1.2d resolves that owner boundary without changing the mainline. The Analysis
Pipeline creates one `trusted-domain-policy-context/v1` from a trusted
deployment selector, verified server mapping, or explicit isolated evaluation
fixture. The projection stores only anonymous binding presence, Pack reference,
schema, canonical content hash, and owner provenance, with evidence,
fact-support, and send authority fixed false. Public request context cannot
select or override it. `FilePolicyRepository` remains the sole loader and
revalidates the Pack reference and hash before Claim Resolution receives the
control input beside admitted facts. Composer and Deterministic Final validate
the same Pack identity. Missing, invalid, stale, or mismatched control context
produces no eligible options and cannot alter direct-evidence support. No Graph
node, service, model call, reply owner, safety gate, registry, or production
flag is added.

P1.2e separates the risk of the requested assertion from the risk of an
answer strategy. Claim Resolution keeps an absolute-guarantee, test, or
liability request unresolved under one
`restricted-request-boundary/v1`. Only an absolute-guarantee boundary may also
offer a same-goal-family `practical_guidance` option whose admitted premise,
Pack identity, scope, qualifiers, prohibitions, review-only marker, and
`low`/`medium` answer-strategy risk are all deterministic. The request risk is
not lowered, the boundary is not a second goal, and Domain Policy remains
control data rather than evidence. Composer may select only an offered option;
Deterministic Final and Unified Textual Audit preserve the boundary and
attribution.

The first P1.2e live case was consumed once and not retried. Request-boundary
preservation and answer-strategy risk separation were both `1/1`, but the
Composer returned a policy reference outside the goal-scoped offered set.
Validation failed closed before Final and Unified Audit. A deterministic
follow-up also removed an unrelated high-risk practical option from an
already-supported direct-fact goal. The remaining 3, Gold 16, and Synthetic
gates were not run. P1.2e therefore remains default-off and not qualified; it
does not alter the production reply or delivery contract.

P1.2f keeps those owners and narrows the existing Composer boundary. Before
the single Composer call, each eligible option receives a deterministic,
request-scoped alias bound to the authoritative goal, canonical policy,
admitted premises, scope, both risk levels, and trusted Pack identity. The
Composer sees only the alias and that goal's offered projection; canonical
policy and Pack identifiers remain server-side. Validation accepts only an
exact current-goal alias lookup and rejects canonical, unknown, stale,
cross-goal, duplicate, or mutated references without retry or repair. The
accepted clause restores canonical provenance for Deterministic Final and
Unified Audit.

The original P1.2e completion retained envelope, finish reason, length,
latency, one-call, and error-path diagnostics, but not the raw returned
reference or the exact prompt/schema/source hashes. Source changed after that
run, so its full Composer input cannot be proven byte-identical. P1.2f
therefore does not manufacture the required Frozen 5x result. Deterministic
Composer and mutation tests pass, but Frozen 5x, the fixed four, Gold 16, and
Synthetic gates remain unrun. Status remains
`bounded_inference_shadow_not_qualified`.

P1.2g later captured a fresh authoritative Composer capsule instead of
reconstructing the historical completion. P1.2h derives one selection mode
from the existing resolution and goal-local offered set: no option is
`forbidden`, a fully supported goal with an explicitly nominated option is
`optional`, and an
unresolved/conflicting/prohibited goal with options is `required`. The model
still chooses the option and wording; the existing Composer Validator only
enforces zero-or-one completeness and exact binding. Frozen Composer replay
passed `5/5`, including required selection and restricted-boundary
preservation. The single permitted live full-chain request was not retried:
Turn Understanding exposed only one of the two current-message goals, so the
supported direct-fact goal disappeared before Composer projection. The fixed
four, Gold 16, and Synthetic gates were not run. Status remains
`bounded_inference_shadow_not_qualified`.

P1 later tightened eligibility without changing that ownership: an
already-supported goal with no explicit policy nomination is direct-only and
does not receive unrelated options merely because it shares a premise family.
Unresolved goals may still receive the safe offered set, and an explicitly
nominated supported practical goal may still receive its exact option. This
prevents optional advice on a completed fact goal while preserving model-led
selection on the customer's actual unresolved request.

P1.2k subsequently tightened the same disabled owners around a canonical
Composer Decision Input, minimal output reconstruction, semantic-budget
metadata, and Unified Audit v2. P1.2k.6i records these changes as an
engineering checkpoint after deterministic, mutation, Pipeline, Replay, and
synthetic-safety verification. The checkpoint adds no Graph node, reply owner,
model call, retry, repair, fallback, send authority, or production flag.

The currently configured MiniMax M3/M2.x candidates did not meet the frozen
Unified Audit v2 structural and semantic qualification contract. No newly
approved Audit Provider/model or role-level production configuration exists,
so live Audit capability remains `provider_blocked`. The Composer and bounded
inference remain default-off and review-only, production behavior is not
promoted, and `real_customer_accuracy=null`.

The following work is frozen unless a failure in the active vertical slice
proves it is the earliest blocker:

- new supervisor/review pages;
- new shadow reasoning, memory, vision, or decision subsystems;
- new evaluator/provider qualification frameworks;
- new claim taxonomies created only to fit a small benchmark;
- platform-specific Agent branches; and
- microservice, queue, or framework migration.

Existing shadow modules are preserved. They may run diagnostics, but they do
not receive additional scope until they have a named production consumer,
promotion metric, rollback boundary, and real-conversation evidence.

## Alternatives Considered

### Continue phase-by-phase evaluator closure

Rejected as the mainline. Evaluation integrity matters, but repeated evaluator
changes were consuming the same effort needed to improve context, evidence,
tools, reply ownership, and real conversation outcomes.

### Replace LangGraph

Rejected. Current failures are evidence readiness, overlapping reply ownership,
context quality, and disabled capability paths. Replacing the runtime would not
fix those failures and would create a second migration problem.

### Enable every candidate capability together

Rejected. It would make attribution and rollback impossible. The mainline uses
one bounded vertical slice and changes one capability boundary at a time.

## Business And Safety Consequences

- Safety, evidence, identity, media, and delivery gates remain unchanged.
- Low-risk supported facts should be answered before unresolved items are
  handed off; safety does not require hiding verified information.
- `can_send` remains application-owned. Initial capability slices are
  supervisor-assist only.
- Knowledge gaps are product-data work, not reasons to add reply templates.
- Evaluation work must state whether it measures infrastructure, safety,
  capability, or real accuracy.

## Migration And Rollback

The previous experimental worktree remains intact and uncommitted. The active
mainline starts from the last committed Phase 0.9A baseline on a separate
branch. No production flag or runtime is changed by this decision.

Rollback is documentation-only: return development priority to the prior branch.
Production behavior is unaffected because the candidate composer and formal
evidence convergence remain disabled by default.

## Verification

Before a behavior change is promoted, run one comparable real-conversation
before/after slice through the formal Pipeline and report the scorecard above.
The slice must also show zero formal-knowledge writes and no regression in the
existing deterministic safety benchmark.

The first mainline slice must use existing context, evidence admission, composer,
and final gate owners. It must not add a Graph node, evidence registry, review
UI, or evaluation framework.
