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

The Final Auditor evaluates accepted model-first candidates against two
separate inputs. `canonical_truth` contains only admitted evidence and claim
resolution state, with anonymous evidence and provenance references.
`conversation_continuity` retains bounded customer and historical agent turns
for referent, prior-question, already-provided-information, and service
commitment continuity. Historical agent turns are explicitly non-authoritative
for product, policy, order, and action-completion facts. A historical factual
conflict therefore cannot override canonical truth or reject a candidate that
uses canonical truth, while a candidate that actually relies on an unsupported
historical fact must still fail closed. The strict audit remains one model call;
provider or schema failure blocks the candidate. Style and harmless repetition
remain the Semantic Quality owner's concern rather than a second Final Auditor
policy.

This boundary does not promote the composer or change delivery permission.
Composer acceptance and Final Auditor acceptance are necessary but not
sufficient for final orchestration or production enablement.

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
