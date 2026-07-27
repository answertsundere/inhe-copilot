# Agent Core Gold-Service Priority Plan

## Authority

This document is the operational priority contract for the customer-service
Copilot. It translates the Project Charter, architecture overview, and ADR 0009
into a strict delivery order.

It does not replace those documents:

- `docs/PROJECT_CHARTER.md` owns the mission and quality definition.
- `docs/architecture-overview.md` owns the durable architecture.
- `docs/module-index.md` owns behavior and module ownership.
- ADRs own changes to production flow or ownership.
- This document owns which approved work happens next and which work stays
  frozen.

Every implementation task must name one priority ID from this document before
code changes begin. Work outside the active priority is allowed only for a
production incident, security issue, data-integrity issue, or an explicit plan
change approved by the project owner.

## North-Star Outcome

Build one platform-neutral Agent Core that behaves like a strong human customer
service representative:

- understands all current customer goals and relevant conversation context;
- resolves product, order, policy, and media identity before answering;
- answers every supported part directly and progressively;
- uses bounded domain knowledge and common-sense inference without inventing
  strong safety, compliance, order, or platform claims;
- performs approved live actions through typed tools;
- sounds natural, concise, considerate, and commercially capable;
- asks for human help only for the unresolved part that genuinely needs it; and
- remains auditable, reversible, and safe to deliver.

The goal is not a larger graph, a stricter benchmark harness, or a reply that
matches one preferred sentence. The goal is a better customer outcome.

## Architecture Guardrails

The active architecture remains:

```text
canonical conversation
-> compact working context
-> model-led atomic customer goals
-> identity, reviewed knowledge, and typed tools
-> admitted evidence plus unresolved claims
-> one model-first reply owner
-> deterministic safety and delivery gate
-> send, supervisor assist, or durable handoff
```

The following rules are non-negotiable:

1. LangGraph stays a thin stateful runtime, not the reasoning engine.
2. There is one formal reply owner. A formatter, auditor, or fallback may not
   become another reply engine.
3. The model may organize reasoning and language; it is not a source of product,
   order, policy, certification, or completed-action truth.
4. Product facts, policy facts, live tool results, service actions, media, and
   Answer Memory retain separate evidence roles.
5. Domain expertise is supplied through reviewed knowledge, typed tools, and
   versioned Domain Packs, not Agent Core branches.
6. Deterministic code owns identity, provenance, admission, high-risk policy,
   media delivery, side-effect authority, and `can_send`.
7. Missing evidence remains visible. Fluent wording may not hide it.
8. No production branch may depend on a sample sentence, SKU, product name,
   order ID, scenario ID, run ID, or expected-answer phrase.
9. A new Graph node, service, registry, retriever, queue, or framework requires
   a demonstrated state/control owner and an ADR.
10. Synthetic benchmarks are safety regression only. They never establish real
    customer accuracy.

## Current Active Priority

**Active priority: P1 - Gold Conversation Quality.**

P0-R1 qualified the existing Agent Core vertical slice without changing its
business logic. The current MiniMax-M3 `json_object` transport passed the
bounded three-case protocol preflight with one call per input. The single
fixed-eight run then reached execution, Composer, Deterministic Final Contract,
and Unified Textual Audit `8/8`; customer-goal coverage was `14/14`, supported
attribution `5/5`, unresolved declaration `9/9`, and eligible Partial Answer
`4/4`. Unsupported evidence references and explicit high-risk/media/service
claim violations, `can_send=true`, formal knowledge changes, DML, retry, and
repair were all zero.

This closes P0 correctness only. Formal Evidence Convergence and the
Model-first Composer remain disabled by default, the candidate remains
review-only, and no production promotion or real-accuracy claim follows. The
immediate work is now:

1. run the pinned high-quality long-conversation set through the same formal
   Pipeline;
2. score customer outcome, naturalness, continuity, and useful progress rather
   than internal finding-code wording;
3. preserve the P0 owner and safety boundaries while locating the earliest
   quality gap; and
4. keep new provider matrices, protocol validators, Fast Path work, frontend
   expansion, vision work, and platform adapters frozen unless P1 evidence
   makes one of them the earliest blocker.

## Priority Selection Rules

When choosing the next task, apply these rules in order:

1. **Protect production.** A security incident, credential leak, data corruption,
   unsafe delivery, or outage may preempt the plan.
2. **Fix the earliest customer-outcome blocker.** Prefer missing goal, context,
   evidence, tool, action, or reply completion over the final visible wording.
3. **Keep one owner per change.** Do not modify Understanding, Composer, Auditor,
   and delivery in one experiment.
4. **Prefer outcome work over protocol work.** Once a bounded transport contract
   safely accepts the provider's documented envelope, return to conversation
   quality.
5. **Prefer existing owners and mature libraries.** Do not create a parallel
   subsystem for a local defect.
6. **Use real comparable conversations.** Component tests qualify a contract;
   only the formal Pipeline measures Agent improvement.
7. **Do not skip a gate.** A later priority cannot begin because an earlier task
   is inconvenient or slow.

If two tasks have equal priority, choose the smaller change with the clearer
before/after metric and rollback.

## Protocol Stabilization Budget

Provider and schema reliability are necessary, but they are not the product.
Apply this budget to JSON envelopes, field types, schema variants, source spans,
and similar transport defects:

- Use one shared, bounded transport rule for equivalent model calls.
- A single complete JSON object or a single complete JSON code fence may be
  deterministically unwrapped when the local strict schema still validates.
- Envelope removal is allowed; semantic JSON repair, substring extraction,
  type coercion, missing-field invention, and free-text fallback are not.
- Each distinct protocol defect gets one diagnosis and one minimal correction
  before the comparable customer-outcome suite is rerun.
- After two consecutive non-semantic failures at the same boundary, stop adding
  validators. Reuse the approved adapter contract, change the provider
  integration, or mark the provider blocked.
- Do not obtain acceptance by repeating an unchanged stochastic call until it
  happens to pass.
- Do not create a new phase, framework, or qualification matrix merely to wait
  for a stochastic `5/5`.
- A protocol fix is complete when the customer-outcome suite can run. It is not
  a reason to delay that suite indefinitely.

## Priority Roadmap

### P0 - Agent Core Closure

**Customer outcome**

A compound question receives one answer that states every supported fact,
keeps every unsupported goal visible, avoids false media or action promises,
and remains review-only.

**In scope**

- atomic goal and provenance correctness;
- admitted evidence and Claim Resolution alignment;
- strict goal-bound Composer clauses;
- Canonical Truth versus conversation continuity in final audit;
- final response preservation;
- bounded provider-envelope handling required by those owners; and
- comparable fixed-eight and real-pipeline evaluation.

**Out of scope**

- new UI or annotation systems;
- new vision, memory, decision, or reasoning shadows;
- Fast Path;
- model training;
- new platform adapters;
- runtime decomposition;
- auto-send enablement; and
- broad style redesign before factual completion is stable.

**Exit gate**

- fixed-eight execution and non-empty replies: `8/8`;
- customer-goal coverage: `100%`;
- supported-claim evidence attribution: `100%`;
- unresolved/conflicting/prohibited goal declaration: `100%`;
- deterministic Final Contract and Unified Textual Audit acceptance: `8/8`;
- unsupported evidence references and explicit high-risk, media, and
  completed-action claim violations: `0`;
- unknown or duplicate goal/evidence references: `0`;
- `can_send=true`: `0`;
- formal knowledge writes: `0`;
- no hard-coded sample behavior; and
- one clean, reviewable commit deployed to an isolated candidate runtime.

Passing P0 proves a core capability slice. It does not prove real accuracy or
gold-service quality. Raw finding codes, secondary diagnostic labels, and
literal stability of internal diagnostic wording are observable data, not
business exit gates. Latency must be disclosed, but it is not a P0 hard stop;
latency optimization follows correctness and real-conversation quality.

### P1 - Gold Conversation Quality

**Customer outcome**

The Agent handles realistic, multi-turn customer conversations naturally,
answers the useful part first, avoids unnecessary handoff, and progresses the
customer toward a resolution.

**Required evaluation**

- the pinned 26-case high-quality long-conversation development set;
- an approved claim-level real Gold set when available;
- fixed real replay through the same formal Pipeline;
- supervisor naturalness review that does not expose labels to the Agent; and
- the synthetic safety benchmark as a separate regression suite.

**Work order**

1. Correct missing or incomplete customer goals.
2. Correct context, identity, evidence, and live-tool gaps.
3. Add bounded low-risk inference only when premises, domain policy, limits, and
   customer-visible uncertainty are explicit. It must not infer safety,
   compliance, load, medical, order, refund, replacement, compensation, or
   media delivery facts.
4. Remove unnecessary handoff while preserving genuine unresolved claims.
5. Improve naturalness, empathy, commercial clarity, and answer progression.
6. Remove duplicated wording and internal-process language.
7. Measure and reduce end-to-end latency after correctness is stable.

**Initial exit gate**

- formal execution and non-empty replies: `100%`;
- supported-claim correctness and attribution: `100%` on the approved scorable
  denominator;
- customer-goal and required-action coverage: at least `90%`;
- unresolved high-risk claims incorrectly asserted: `0`;
- unsupported media or completed service actions: `0`;
- unnecessary handoff: at most `10%` of cases with sufficient context;
- supervisor naturalness acceptance: at least `80%`;
- repeated/internal-process replies: at most `5%`;
- full-path p95: at most `25s`, with a documented path toward the P3 target; and
- `real_accuracy=null` whenever approved labels remain insufficient.

These thresholds may be tightened after the first valid baseline. They may not
be lowered during a run to create a pass.

### P2 - Domain Expertise And Portability

**Customer outcome**

The same Agent Core becomes a professional representative for a domain by
loading that domain's reviewed facts, policies, tools, and bounded inference
pack, without product-category branches in Agent Core.

**Domain Pack contents**

- domain ontology and attribute definitions;
- claim risk and evidence requirements;
- allowed low-risk inference policies with explicit premises and scope;
- prohibited strong conclusions;
- tool requirements and freshness rules;
- service-policy actions;
- terminology and communication guidance; and
- evaluation cases for domain-specific decisions.

Domain Packs may not contain customer-specific rules, product truth, reply
templates, `can_send` decisions, or benchmark answers.

**First domain**

Close the maternal-child/home domain already represented by the current pack:
materials, dimensions, modes, structure, ordinary care, installation, media,
and bounded everyday-use questions.

**Portability proof**

Add one isolated second-domain pack, such as badminton equipment, covering:

- weight class;
- balance point;
- shaft stiffness;
- frame material;
- string tension;
- singles/doubles and attacking/defensive preferences;
- beginner suitability;
- stringing and after-sales tools;
- allowed parameter-based recommendation; and
- prohibited injury-prevention or durability guarantees.

**Exit gate**

- switching domains changes data/configuration/tool bindings, not Agent Core
  branches;
- no sample, product, or category hard-coding in Agent Core;
- domain risk and inference mutations are all blocked or allowed as declared;
- each domain passes its approved real conversation slice;
- unsupported strong safety or performance guarantees remain `0`; and
- a missing Domain Pack fails closed without corrupting the generic core.

### P3 - Latency And Fast Path

**Customer outcome**

Simple, low-risk, directly supported questions receive a fast natural answer;
complex, live-tool, ambiguous, inferred, or risky questions retain the full
path.

**Entry conditions**

- P1 quality gate passed;
- P2 current-domain policy is complete enough to classify risk and inference;
- the existing answer-eligibility contract remains qualified; and
- the full path is the correctness baseline.

**Work**

- measure stage latency before removing work;
- remove duplicate retrieval and duplicate model calls;
- implement Fast Path in shadow using the existing eligibility projection;
- compare exact customer outcomes against the full path;
- retain the same evidence and final delivery authority; and
- add caching only for identity-safe, freshness-safe read results.

**Exit gate**

- simple direct-fact p95: at most `8s`;
- complex or live-tool p95: at most `20s`;
- Fast Path outcome parity with the qualified full path: `100%` on its eligible
  slice;
- false Fast Path eligibility: `0`;
- safety, evidence attribution, media, and delivery regressions: `0`; and
- one model call for eligible simple replies unless a documented provider
  constraint prevents it.

### P4 - Supervisor-Assist Canary And Durable Handoff

**Customer outcome**

Real staff can accept, edit, reject, or hand off Agent suggestions, and every
handoff becomes a durable operational task rather than a sentence.

**Work**

- deploy the qualified candidate as supervisor assist;
- record accept/edit/reject/handoff and handling time;
- implement durable `HandoffTask` with assignment, reason, SLA, status,
  acknowledgement, and audit;
- expose the smallest supervisor workflow required to operate the canary; and
- close evidence and tool gaps from real edits.

Frontend work is allowed here because it has a named production consumer and
outcome metric. It remains out of scope before this priority.

**Exit gate**

- enough real canary volume to cover the supported business domains;
- supported-fact correctness at least `98%`;
- unsafe suggestion or unsupported action rate: `0`;
- supervisor acceptance without factual edit reaches an agreed baseline and
  improves over the previous candidate;
- handling time improves without increasing handoff;
- every required handoff creates a valid task; and
- rollback to the previous candidate is tested.

### P5 - Low-Risk Automation

**Customer outcome**

Only explicitly bounded, well-evidenced, operationally deliverable requests may
be sent without human approval.

**Entry conditions**

- P4 canary evidence is sufficient;
- reliable channel delivery and tool behavior are verified;
- domain-specific auto-send scope is explicitly approved; and
- rollback and monitoring are active.

**Exit gate**

- auto-send is limited to an enumerated policy scope, not a broad FactType;
- evidence, final audit, channel capability, and delivery block all agree;
- high-risk, live-action uncertainty, identity ambiguity, and missing context
  always block;
- post-send audit and incident rollback are operational; and
- no auto-send expansion is justified by synthetic benchmark results alone.

### P6 - Omnichannel Expansion

**Customer outcome**

The same qualified Agent Core operates through QianNiu, Pinduoduo, JD, and
future channels without platform-specific reasoning branches.

**Work**

- canonical inbound and outbound adapters;
- platform capability descriptors;
- live tool bindings;
- durable queue, SLA, notification, and health operations; and
- channel-specific delivery tests outside Agent Core.

**Exit gate**

- platform-native fields stop at adapter boundaries;
- the same canonical Pipeline and evaluation suite run for every channel;
- delivery capability and action authority are explicit;
- channel rollout does not change Agent truth or safety policy; and
- each channel has an independent rollback.

## Evaluation Ladder

Use each evaluation level only for its declared purpose:

| Level | Dataset | Purpose | Cannot prove |
|---|---|---|---|
| E0 | Unit and mutation tests | Local contract and fail-closed behavior | Agent quality |
| E1 | Fixed eight-case slice | Fast end-to-end development gate | Real accuracy |
| E2 | 26 long conversations | Multi-turn capability and naturalness diagnosis | Production accuracy without approval |
| E3 | Approved real Gold set | Claim/action accuracy on a scorable real denominator | Live operational acceptance |
| E4 | Supervisor-assist canary | Real acceptance, edit, handoff, and handling outcomes | Broad auto-send safety |
| E5 | Bounded automation canary | Delivery reliability in an approved low-risk scope | Other domains or channels |

Rules:

- E0 must pass before E1.
- E1 must pass before E2.
- E2 must pass before P1 completion.
- E3 is required before any accuracy claim.
- E4 is required before auto-send.
- E5 results apply only to the exact approved domain, intent, tool, and channel
  scope.

## Scorecard

Every behavior-affecting change reports the same scorecard:

- dataset ID, version, content hash, and approval state;
- runtime commit/source hash, feature flags, provider/model, and entry point;
- scorable, excluded, context-gap, error, empty, and timeout counts;
- customer-goal recall and required-action coverage;
- supported-claim correctness and evidence attribution;
- unresolved/conflicting/prohibited goal coverage;
- tool requirement and completion;
- unnecessary handoff;
- unsupported factual, high-risk, media, and service-action claims;
- naturalness acceptance, repetition, and internal-process language;
- p50/p95 stage and end-to-end latency;
- `can_send` and actual delivery changes;
- formal knowledge writes and DML attempts; and
- synthetic safety regression as a separate result.

If approved labels are insufficient, report `real_accuracy=null` and
`optimization_unverified`.

Evaluators observe customer-visible outcomes and authoritative structured
events. Their finding codes and expected labels may not become new Agent rules,
reply templates, or production routing inputs.

## Model And Training Strategy

The default strategy is strong foundation models plus compact context, tools,
reviewed knowledge, and Domain Packs.

Do not start pretraining or fine-tuning to compensate for:

- missing or low-quality product data;
- an unclear tool contract;
- duplicated reply ownership;
- an overlong prompt;
- broken evidence admission;
- an unstable evaluator; or
- a provider transport defect.

Consider supervised fine-tuning or distillation only after:

- the formal Pipeline and reply owner are stable;
- at least several hundred approved, privacy-safe conversations exist;
- labels distinguish facts, actions, tone, and handoff;
- the target model behavior is already demonstrated by a stronger model;
- a held-out real Gold set exists; and
- rollback to the foundation-model path is available.

Training data may teach style, domain terminology, goal decomposition, and tool
selection. It may not replace current product facts, policies, or live state.

## Work Allocation

While P0-P3 are active, planned engineering capacity should approximately favor:

- `70%` customer-visible Agent Core outcomes;
- `20%` domain knowledge, tools, and real evaluation data; and
- `10%` runtime, protocol, and evaluation infrastructure.

This is a priority guard, not a time-accounting requirement. A production
incident may temporarily override it. Repeated protocol or UI work that exceeds
this balance requires an explicit plan update.

## Required Task Header

Every implementation prompt or issue must begin with:

```text
Priority ID:
Customer outcome:
Earliest failing owner:
Comparable dataset and baseline:
One target metric:
Allowed modules:
Forbidden modules:
Hard stop:
Safety and delivery invariants:
Documentation impact:
```

If any field is missing, the task remains analysis-only until the header is
complete.

## Architecture Drift Gate

Before editing, answer:

1. Does this task serve the current active priority?
2. Is the failing module the earliest authoritative owner?
3. Can the change be made in an existing owner?
4. Does it improve a customer-outcome metric rather than only an internal pass
   rate?
5. Will the same formal Pipeline be evaluated before and after?
6. Does it preserve evidence, safety, media, action, and `can_send` authority?
7. Is any new UI, service, graph node, taxonomy, provider matrix, or shadow
   capability truly required by the current exit gate?

If answers 1, 2, 3, 4, or 5 are no, stop and revise the task. If answer 7 is
yes, record an ADR or explicit plan amendment before implementation.

## Exceptions And Plan Changes

Only these conditions may preempt the active priority:

- production outage or severe reliability regression;
- credential or privacy exposure;
- unsafe auto-send or unsupported side effect;
- formal knowledge corruption or unexpected DML;
- a legal/compliance requirement; or
- an explicit project-owner decision.

After the exception is resolved, work returns to the active priority.

Changing priority order requires:

1. a written reason tied to customer or operational outcome;
2. current gate evidence;
3. the proposed new active priority and exit gate;
4. affected architecture/ADR analysis; and
5. updates to this document and `docs/index.md`.

## Progress Ledger

| Priority | Status | Current evidence | Next gate |
|---|---|---|---|
| P0 Agent Core Closure | qualified | P0-R1 current transport preflight `3/3`; single fixed-eight execution/Composer/Final/Unified Audit `8/8`, goal coverage `14/14`, supported `5/5`, unresolved `9/9`, Partial Answer `4/4`, zero unsafe/send/write/retry/repair findings | Keep feature flags disabled and preserve these boundaries during later work |
| P1 Gold Conversation Quality | active | Long-conversation assets exist, but no valid production-quality result | Run the pinned 26-case set and evaluate customer outcomes rather than internal finding codes |
| P2 Domain Expertise And Portability | planned | Maternal-child/home policy pack exists; second-domain portability is unproven | Current-domain quality, then a data-only second-domain proof |
| P3 Latency And Fast Path | planned | Eligibility is diagnostic; Fast Path disabled; latency remains high | P1 quality and P2 policy readiness |
| P4 Supervisor-Assist And Handoff | planned | Review infrastructure exists, but Agent capability is not promoted | Qualified candidate plus durable handoff |
| P5 Low-Risk Automation | planned | `can_send` remains application-owned and disabled for candidate work | Real canary evidence |
| P6 Omnichannel Expansion | planned | Architecture defined; adapters and operations incomplete | Qualified Agent Core and handoff operations |

Update this ledger only when a gate changes. Dated run details remain in
evaluation outputs, not in this durable plan.

## Definition Of Project Progress

The project has progressed only when at least one of these becomes true without
a safety regression:

- more real customer goals are correctly completed;
- more supported claims are correctly attributed;
- fewer sufficient-context conversations require handoff;
- more approved service actions complete correctly;
- replies become more natural without hiding uncertainty;
- latency or error rate improves on the same customer outcomes;
- a domain becomes portable without Agent Core code branches; or
- a qualified capability is safely promoted to real staff or a bounded
  automation scope.

More tests, schemas, pages, providers, graph nodes, or reports are not progress
unless they directly enable one of those outcomes.
