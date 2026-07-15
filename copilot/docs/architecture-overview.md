# INHE Customer-Service Copilot Architecture

## Status And Authority

This document is the authoritative system-architecture overview as of
2026-07-15. It describes the current production path, the intended target, and
the order in which the system may converge. Historical delivery reports and
node inventories are implementation evidence, not architecture authority.

The project remains a modular monolith. No microservice split, message queue, or
platform-specific Agent fork is justified until the canonical contracts and one
formal answering path are stable.

## Architecture Decision In One Sentence

Use LangGraph as a thin stateful orchestration runtime; build the answering
ability around compact context, admitted evidence, model-led claim reasoning,
deterministic safety, and durable human handoff.

LangGraph is not the reasoning engine. The LLM is not the source of truth. The
knowledge base is not the reply composer. Each layer has one responsibility.

## Business Goal

The system must support QianNiu, Pinduoduo, JD, and future channels through one
platform-neutral customer-service core. For every customer turn it should:

1. resolve the correct conversation, product, order, and channel capabilities;
2. retrieve the smallest useful set of reviewed facts and live tool results;
3. separate supported, unresolved, conflicting, and prohibited claims;
4. answer supported parts naturally instead of hiding them behind a generic
   handoff;
5. block unsupported high-risk claims and actions;
6. deliver through the channel or create a durable human task;
7. persist enough provenance to reproduce the decision.

## Non-Negotiable Truth Flow

```text
channel event
-> canonical conversation context
-> external identity
-> JST/internal product or order identity
-> reviewed facts, live tool results, policies, or reviewed visual observations
-> evidence admission and conflict handling
-> bounded claim reasoning
-> final safety and delivery decision
-> outbound adapter or durable HandoffTask
```

Product facts, policy facts, service actions, media references, and Answer
Memory are different roles. Presence in a candidate pack never proves that a
claim may be answered.

## Target Architecture

```mermaid
flowchart LR
    A["Channel adapters<br/>QianNiu / PDD / JD"] --> B["Canonical ConversationEvent"]
    B --> C["AnalysisPipeline"]
    C --> D["Thin LangGraph runtime"]
    D --> E["Context Builder"]
    E --> F["Identity and read-only tools"]
    F --> G["Evidence Admission"]
    G --> H["LLM Claim Decision"]
    H --> I["Reply Composition"]
    I --> J["Deterministic Safety and Delivery Gate"]
    J --> K["Canonical AgentDecision"]
    K --> L["Outbound adapter"]
    K --> M["Durable HandoffTask"]
    K --> N["Trace / Replay / Benchmark / Supervisor"]
```

The desired center of gravity is **context-first reasoning**, not graph-node
count. The runtime should expose clear tool and state boundaries while the model
receives only high-signal context for the current claims.

## Layer Responsibilities

### 1. Channel Adapters

Adapters translate platform payloads and capabilities into canonical contracts.
They may not introduce QianNiu-, PDD-, or JD-specific branching into Agent
reasoning. They own authentication, platform field mapping, outbound formatting,
and delivery capability reporting.

Status: planned; QianNiu is the first adapter, not the core.

### 2. AnalysisPipeline

`AnalysisPipelineService` is the only formal application execution path for
`/api/analyze`, `/api/copilot/context`, replay, and benchmark. It owns stage
order and failure isolation:

```text
canonical input
-> graph execution
-> media delivery preparation
-> final orchestration
-> isolated shadow diagnostics
-> final persistence
-> response
```

Routes keep HTTP, authorization, request normalization, metrics, and
presentation only. `AnalysisExecutionService` owns trace lifecycle and final
persistence. A formal stage must not run again after persistence.

Status: formal; ADR 0001.

### 3. Thin LangGraph Runtime

LangGraph should retain only work that benefits from explicit state and control
flow:

- conversation state transitions;
- identity and tool routing;
- bounded retries and timeouts;
- pause/resume for human approval;
- recoverable execution and traceable node boundaries;
- selection between product, order, policy, clarification, and handoff flows.

LangGraph should not become the owner of:

- duplicate fact, risk, or evidence registries;
- platform-native fields;
- repeated reply polishing;
- phrase-specific business rules;
- large prompt payloads or complete traces;
- a second final-response pipeline.

The current graph contains overlapping understanding, routing, guard, and
generation responsibilities. It must be reduced incrementally after contract
tests exist; a big-bang rewrite is prohibited. See
`docs/langgraph-architecture.md` for the runtime boundary and current debt.

Status: formal but overweight.

### 4. Context Builder

The Context Builder is the working-memory boundary for the model. A decision
context should contain only:

- current customer goal and requested claims;
- necessary recent turns plus a compact conversation summary;
- resolved product and order identity;
- admitted evidence with stable evidence UIDs and provenance;
- unresolved and conflicting claims;
- available service actions and media candidates, explicitly labelled as
  non-factual roles;
- allowed tools and channel capabilities;
- applicable safety constraints.

It must not contain the complete trace, all retrieved chunks, unfiltered Answer
Memory, entire product catalogs, or every historical rule. Context size and
source counts must be observable.

Status: converging. `AdmittedAnswerContextService` is the admission reuse point.
When `COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED` is enabled, the existing
evidence-builder node emits deterministic admitted-only `selected_evidence` and
a bounded decision context; the final delivery contract remains unchanged.

### 5. Identity, Retrieval, And Tools

External titles resolve through JST/internal identity before product-scoped
facts are selected. Order, logistics, refund, replacement, and other live-state
claims require the relevant live tool or approved policy source.

Retrieval returns candidates. Admission decides eligibility. Tools return typed
results rather than customer-facing prose. A tool set should be small,
non-overlapping, and understandable to the model.

Status: SQLite retrieval and JST paths are formal; pgvector remains shadow.

### 6. Evidence Admission

One versioned contract must decide whether evidence may support a claim. Direct
product evidence requires:

- reviewed, approved, verified, or published state;
- direct-answer permission and an eligible evidence role;
- matching identity in at least one shared namespace;
- compatible requested fact type or attribute;
- no unresolved conflict or placeholder status.

`service_action`, `fallback_only`, `media_reference`, Answer Memory, rejected
visual observations, and unreviewed FAQ cannot become product facts.

Status: shared admission exists. Formal convergence is opt-in behind
`COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED`; it reuses admission rather than
creating a second evidence registry and does not alter final delivery.

### 7. LLM Claim Decision And Reply Composition

The model should understand compound questions, select bounded read-only tools,
associate evidence with individual claims, and compose natural replies. It must
return a structured decision rather than private chain-of-thought:

- requested claims;
- evidence UIDs used for each confirmed claim;
- unresolved or conflicting claims;
- requested human action;
- candidate reply;
- concise decision reason codes.

Supported claims should be answered even when another claim is unresolved. The
model may connect verified facts only through declared low-risk reasoning. It
may not derive toxicity, certification, age suitability, load limits, order
status, refunds, replacements, compensation, or installation-safety promises
without the required evidence or tool result.

Status: Grounded Reasoning and the Evidence-First Decision Loop are shadow-only.
The strict provider is not qualified for formal use. The formal path still
leans on deterministic rendering and broad handoff fallback.

### 8. Deterministic Safety And Delivery

The final gate verifies claim support, product identity, high-risk policy,
actual media blocks, platform capability, and delivery status. It alone may set
the final `can_send` and `requires_human_review` contract.

Safety should inspect the final answer once. A fallback may replace an unsafe
reply, but resolved pre-fallback failures must not contaminate the final audit.
Polishing may improve customer-facing language but cannot add facts, promises,
media, or actions.

Status: formal and intentionally conservative; currently stronger than reply
composition.

### 9. Human Handoff And Supervisor Control Plane

A handoff is a durable task with shop, channel, conversation, reason, evidence,
priority, SLA, assignment, acknowledgement, status, and audit history. A toast
or customer-facing sentence is not a handoff task.

Status: planned/P1. The absence of this layer blocks true omnichannel operation.

### 10. Data, Evaluation, And Operations

Replay and benchmark must use the same canonical context and final Pipeline as
user-facing requests. Benchmark pass rate is not production readiness when all
cases are review-only or real samples lack sidecar context.

SQLite currently mixes knowledge, operations, traces, evaluation, and memory.
Web and resident workers also share process ownership. These are later runtime
separation tasks, not reasons to split the domain into microservices now.

The runtime exposes liveness separately from readiness. Liveness confirms that
the Flask process can serve diagnostics. Readiness verifies the configured
formal knowledge database through read-only SQLite access, including required
tables and non-empty knowledge, chunk, and KBQA counts. Product-scoped analysis
fails closed before graph execution when readiness is false; formal QA performs
the same preflight and does not manufacture a RAG-miss evaluation run.

## Formal, Shadow, And Planned Boundaries

| Capability | Status | May affect final reply or `can_send` |
|---|---|---|
| AnalysisPipeline and final orchestration | formal | yes, through final contract |
| SQLite retrieval, identity and eligible tools | formal | yes, after admission |
| Final audit and delivery gate | formal | yes |
| pgvector retrieval | shadow | no |
| Answer Memory | shadow/reference | no; style and handling only |
| Grounded Reasoning Draft | shadow | no |
| Product Media Observation and annotation | shadow | no |
| Evidence-First Decision Proposal | shadow/qualification-gated | no |
| Platform adapters and durable HandoffTask | planned | not implemented |

Shadow modules may write diagnostics only. They must freeze formal decision
fields and pass an explicit promotion gate before joining production decisions.

## Current Architecture Assessment

### What Is Strong

- One formal Pipeline is shared by API, copilot, replay, and benchmark.
- Final response, snapshot, and trace contracts are aligned.
- Product identity, evidence roles, media delivery, and high-risk boundaries are
  explicit and fail closed.
- Replay, benchmark, provider qualification, visual review, and shadow mutation
  guards provide useful observability.
- The modular-monolith decision avoids premature distributed-system overhead.

### What Is Blocking Business Value

1. Eligible structured facts can exist in Product Context Pack without reaching
   formal `selected_evidence`.
2. The formal generator cannot reliably produce claim-level partial answers.
3. Context construction is fragmented across graph state, packs, policies, and
   shadow payloads.
4. Multiple guard, fallback, semantic, and polishing services can rewrite the
   same response and produce robotic handoff language.
5. Visual understanding, Answer Memory, pgvector, and LLM decision capabilities
   have accumulated in shadow without a promoted vertical slice.
6. Real replay often lacks per-sample product/order context.
7. Durable handoff and platform adapter contracts are not implemented.

The primary risk is now **shadow accumulation**, not lack of experimental
capability. New shadow subsystems should be frozen unless they unblock the next
formal vertical slice.

## Convergence Plan

### Phase A: Formal Evidence Convergence

- merge eligible Product Context Pack facts into one canonical selected/admitted
  evidence contract;
- keep role, identity, review, conflict, and provenance checks fail closed;
- verify the same result across API, replay, benchmark, trace, and snapshot.

### Phase B: Context-First Supervised Partial Answer

- build the minimal Decision Context;
- split compound questions into claim-level supported/unresolved/conflicting
  states;
- answer confirmed claims and defer only unresolved claims;
- expose the candidate to supervisors first with `can_send=false`;
- qualify a strict provider before model output can affect formal decisions.

The first Phase B slice is a deterministic supervisor preview. It consumes only
the Minimal Decision Context, preserves claim-level evidence references, and
always remains review-only; it cannot update the formal reply, delivery blocks,
or `can_send`.

Phase B evaluation runs Claim Resolution from raw requested claims and admitted
facts rather than accepting precomputed resolutions. Attribute-qualified claims
select only compatible evidence and conflicts. A preview fails closed when its
isolated final-audit or semantic-fit diagnostic fails, and synthetic success is
not treated as a real positive-evidence promotion result.

### Phase C: Simplify The Runtime

- inventory duplicate understanding, routing, guard, and reply-rewrite nodes;
- consolidate only after behavior and trace equivalence tests exist;
- keep a small set of macro graph stages and move reusable contracts into one
  tested owner each;
- do not rewrite the graph and the answering contract in the same change.

### Phase D: Omnichannel Operations

- implement canonical platform ports;
- add durable HandoffTask, assignment, SLA, acknowledgement, and audit;
- connect QianNiu first, then PDD and JD without changing Agent-domain logic.

### Phase E: Runtime And Data Separation

- separate web and workers;
- introduce managed migrations and CI enforcement;
- separate operational and analytical workloads when measured contention or
  deployment needs justify it.

## Anti-Drift Rules

Before changing architecture or adding a module:

1. identify the earliest broken contract and its current owner;
2. verify whether a maintained tool or existing project service already solves
   it;
3. avoid new policy, fallback, shadow, or index modules when an owner exists;
4. declare the capability `formal`, `shadow`, `legacy`, or `planned`;
5. state whether it changes evidence eligibility, final reply, `can_send`, media
   delivery, or handoff;
6. test API, copilot, replay, benchmark, trace, and persistence where relevant;
7. update this overview only for durable responsibility or data-flow changes;
8. record production ownership changes in an ADR before implementation.

## Formal Delivery Fail-Closed

The formal path treats requested claims independently. A supported material
composition clause does not imply a material-safety, certification, child, or
performance conclusion. Any unresolved requested high-risk claim remains
human-review-only even when another low-risk claim is supported.

Visual delivery is fact-type scoped. Dimensions and space-fit delivery may use
only an actual reply block built from an identity-matched dimension reference;
an appearance or SKU image is not promoted by title text, retrieval score, or
an answer scenario label. This boundary is enforced before final delivery and
does not change the shadow decision layers.

## External Design References

- Anthropic, *Building effective agents*: prefer simple composable patterns and
  add complexity only when evaluation demonstrates value.
  https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *Effective context engineering for AI agents*: treat context as a
  finite resource and provide the smallest high-signal set of instructions,
  tools, history, and external data.
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- LangGraph overview: use the runtime for durable execution, persistence,
  streaming, and human-in-the-loop rather than as a replacement for model and
  tool design.
  https://docs.langchain.com/oss/python/langgraph/overview

These references support the target direction; project business invariants and
verified code behavior remain authoritative.
