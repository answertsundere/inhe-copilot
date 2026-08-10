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

P0-R1 qualified the existing Agent Core correctness slice. P1.4 then ran one
native, non-intercepted fixed-eight comparison through the same formal
Pipeline. After preserving trusted Composer control metadata and making
bounded-option selection required only for semantically nominated restricted
alternatives, Composer acceptance reached `8/8`. Six cases reached Delivery;
two stopped fail-closed at Unified Audit because the current Provider violated
the audit output schema. Pipeline p50/p95 were `26.432s/29.705s`, formal
knowledge content and DML were unchanged, `can_send=true` remained zero, and
all eight cases still required human review.

The same P1 gate identified a separate RAG evidence-plumbing defect: a
published structured-product material chunk was retrieved but its formal
source metadata was dropped before admission. Repository, Filter, and Evidence
Builder now preserve the reviewed chunk's source type, review state, and
confidence without relaxing the existing Evidence Gate. A single prospective
blind case changed the material goal from unresolved/no evidence to
supported/direct evidence and correctly answered `PP/TPE`; odor and boiling-
water sterilization remained unresolved. This is a targeted capability proof,
not a new fixed-eight result or real-accuracy claim.

The Unified Audit role has independent default-off configuration and reuses the
existing one-shot strict structured-output transport. It cannot inherit the
formal Agent/Composer or decision-shadow model, and missing or unqualified
configuration fails before a request with no fallback. MiniMax and the existing
DeepSeek credential remain unqualified. A loopback Ollama native-schema adapter
now preserves the same provider-neutral schema and local Validator.

P1 has two deliberately separate release tracks. **Supervisor Assist** may run
the existing Composer candidate through Deterministic Final and expose only a
review-only draft to a human seat: every such result keeps
`requires_human_review=true`, `can_send=false`, and no delivery authority. An
unqualified Unified Audit is recorded as advisory quality evidence in this
track; it cannot approve, rewrite, or send a candidate. **Autonomous Send**
remains blocked until an independent Unified Audit role, real-accuracy evidence,
Safety, and Delivery are all qualified. This distinction does not create a new
reply owner or a second Pipeline.

The first native Supervisor Assist Fixed-8 on clean commit `451be614` closed
that pending baseline. The current DeepSeek V4 Flash Composer role first passed
its frozen qualification `5/5`, then the formal HTTP Pipeline accepted all
eight candidates and Deterministic Final passed `8/8`. Unified Audit remained
explicitly unqualified and made zero model calls; every candidate stayed
`requires_human_review=true` and `can_send=false`. Formal knowledge and DML did
not change, and Pipeline p50/p95 were `10.688s/11.925s`. Post-run expert review
was `3 pass / 3 partial / 1 fail / 1 not scorable`. The only clear factual
failure followed an authoritative goal that collapsed gross weight and load
capacity into an unmapped claim before Claim Resolution. P1 therefore returns
to Turn Understanding atomic-goal completeness and canonicalization; it does
not add another Auditor, Graph node, or Validator. `real_accuracy=null`.

The recovered P1.4i checkpoint adds only the existing Pipeline's
default-disabled, HMAC-addressed projection of open owner-stamped goals. It
does not add a Graph node, model call, reply owner, evidence source, or send
authority. The semantic call can receive an opaque alias and typed identity
metadata, and the server accepts a continuation only when the new current-turn
goal exactly matches the existing open goal. No candidate, review, or feedback
path can complete a goal. Deterministic and full-suite regression checks passed
for this checkpoint. The explicit Composer role then requalified on the
recovered source with DeepSeek V4 Flash `5/5`, one Provider call per attempt,
and zero retry, repair, fallback, formal-knowledge DML, or send authority.
The remaining gate is a fresh blind Fixed-8, not another component fixture. Its
immutable dataset, manifest, query-only knowledge snapshot, and runtime binding
are absent from the recovered source, local Git history, and recovery inventory.
Until the exact asset bundle is restored and its hashes validate, P1 quality and
`real_customer_accuracy` remain unqualified.

P1.4F found that the previous negative Audit fixture was itself too strict: it
treated ordinary impact variables and a brief care suggestion as unsafe even
though those are required for the approved humanlike answer. Domain Pack
`maternal_child_home@1.4.0` permits height, angle, surface, severity,
frequency, and handling-pattern variability plus one concise care suggestion,
while retaining the absolute-guarantee, test, child-safety, warranty, and other
unsupported-claim prohibitions. With a truly unsafe absolute-guarantee
counterexample, local `Qwen3.6:35b` passed safe `5/5` and unsafe `5/5` with one
strict call per attempt, no retry/repair/fallback, and stable attribution. This
qualifies that exact role for the next isolated Fixed-8 only; it does not enable
production or change `can_send`.

A later native Fixed-8 exposed two ordinary-care gaps rather than a need for a
new reasoning service. Domain Pack `maternal_child_home@1.6.1` therefore adds
review-only cleaning-care and incidental-moisture budgets grounded in an
admitted material premise. It permits concise mild-cleaning, spot-test,
prompt-drying, ventilation, and splash-versus-immersion guidance while
retaining chemical-compatibility, waterproof, sterilization, safety, and
certification prohibitions. A fully supported goal without an explicit policy
nomination now remains direct-only; unresolved goals receive only the safe
offered set for their owner-stamped goal family, and an explicitly nominated
supported practical goal may still receive its exact option. The existing
Composer, Deterministic Final, and
loopback Unified Audit passed cleaning `5/5` plus moisture `5/5` with one call
per role, no retry/repair/fallback, stable policy attribution, and no send
authority. This is a component qualification; the new native Fixed-8 remains
the next gate.

That native Fixed-8 has now run once on clean commit `eca4ca40`: all eight
requests completed, formal knowledge and DML stayed unchanged, and all eight
remained review-only. It exposed two different blockers. First, turns with zero
renderable customer goals were incorrectly treated as accepted model-first
candidates and sent through an empty deterministic/textual audit contract. The
general contract now makes those turns no-op Composer requests with zero
Composer model calls and keeps them on the legacy orchestration path. Second,
one real three-goal turn selected a bounded option but omitted its admitted
premise reference, which the existing Validator correctly rejected.

The premise failure is now closed without adding repair. Since evidence and
premise references are already fixed by the validated resolution or selected
option, Composer no longer echoes them in model output; the server restores
them deterministically. Claim Resolution also refuses to offer policies when
the authoritative goal has no goal-family binding, instead of exposing every
policy that happens to share a material premise. The exact frozen three-goal
case passed Composer, Deterministic Final, and Unified Audit `5/5`, with one
call per role and zero retry/repair/fallback. The expanded high-temperature
case then passed the same full chain `5/5`; the loopback Audit role separately
accepted the safe semantic budget `5/5` and rejected its prohibited
heat-resistance and sterilization counterexample `5/5`, with one call per
attempt and zero retry/repair/fallback. The cleaning-care component gate is
therefore closed for the next isolated conversation run.

That next native Fixed-8 ran once on clean commit `0c301046`, with no transport
interception or replacement run. Execution was `8/8`, Composer acceptance was
`6/8`, formal knowledge and DML stayed unchanged, `can_send=true` remained
zero, and all eight results required human review. Pipeline p50/p95 were
`51.554s/62.825s`. Expert post-run review rated two replies pass, three partial,
and three fail. The recurring earliest quality owner was Turn Understanding,
not the downstream Composer or Audit: explicit material or suitability goals
could be marked as dependencies, product identity could leak into
`attribute_key`, and a matching practical policy family could be omitted.

The general Turn Understanding contract now keeps every explicit buyer request
as a customer goal, reserves attributes for the requested property, and
separates direct facts from practical guidance. A canonical customer goal with
no selected intent may inherit only an exact goal-family match from the trusted
Domain Pack candidate set. The server does not select a policy or infer a
family from customer keywords, related FactTypes, product names, or fixture
values. The frozen bathroom-moisture, material-plus-toxicity, and material-plus-
cleaning inputs each passed five independent understanding calls (`15/15`)
with valid provenance and zero retry, repair, or fallback. This is a component
qualification only; the next gate is a fresh clean native Fixed-8 through the
same full Pipeline.

The fresh gate on clean commit `7096269d` completed `8/8` with no transport
interception or replacement requests. Composer acceptance improved from `6/8`
to `7/8`; formal knowledge and DML were unchanged, `can_send=true` remained
zero, and all eight cases remained review-only. Expert review moved from
`2 pass / 3 partial / 3 fail` to `2 pass / 6 partial / 0 fail`, because the
former generic-handoff cases now preserved supported material facts and their
unresolved customer goals. Pipeline p50/p95 were `45.958s/96.480s`, so this is
not a performance qualification or production promotion.

The bathroom-moisture case exposed the next exact contract break. Turn
Understanding correctly derived `policy_goal_family=moisture_resistance`, but
left `policy_intent_kind` empty, so Claim Resolution rejected the otherwise
eligible practical policy with `bounded_inference_intent_kind_mismatch`. The
owner projection now copies the kind only when all trusted candidates in the
exact family expose one identical non-empty kind. It still does not select a
policy; multiple kinds remain ambiguous and fail closed. The frozen moisture
input passed this contract `5/5` with one model call per attempt and no retry,
repair, fallback, knowledge access, or send authority. A new native gate remains
mandatory before declaring the full reply improved.

The subsequent customer-outcome owner was oral-exposure safety handling. The
Pack now keeps the requested toxicity or ingestion-safety fact high-risk and
unresolved while offering only a review-only practical response: stop oral
contact, inspect for damage or fragments, and seek medical help after ingestion
or symptoms. It does not infer product safety from material and does not use
Domain Policy as evidence. The oral-safety-only and compound
material-plus-oral-safety cases passed Composer, Deterministic Final, and
Unified Audit three times each (`6/6`). Four frozen responses were retained;
only the two missing attempts were called after correcting an evaluator
denominator that had counted a supporting-only dependency as a second customer
material goal. Formal knowledge and DML were unchanged and send authority
remained zero. This closes the component gate, not the full conversation gate.

The required native Fixed-8 then ran once on clean commit `1ed24db5` with no
transport interception or replacement requests. Composer, Deterministic Final,
Unified Audit, and Delivery all completed `8/8`; formal knowledge, DML, and
send authority were unchanged. Expert review rated `2 pass / 4 partial / 0
fail / 2 not scorable`, with both oral-exposure cases now passing. Pipeline
p50/p95 improved to `26.256s/36.480s`, although seat-scale latency remains
unqualified. The earliest new defect is textual factual fidelity: a durability
reply asserted that the product had not undergone impact testing when the
authoritative budget only established that direct test evidence was absent.
The existing Unified Audit should reject this `no_test_claim` violation
without adding a keyword classifier, reply repair, or product-specific rule.

Unified Textual Audit v4 now projects the complete `required_qualifiers` set
and `prohibited_extensions` separately. Every applicable clause must return
independent `qualifier_status` and `prohibited_extension_status` decisions;
the latter is a semantic comparison against the governing policy families, not
a Python keyword match. The local Validator remains strict and fail-closed.
Composer also receives the general epistemic constraint that missing direct
evidence is not proof that a test or event never occurred. These changes
preserve the existing owners and add no model call, retry, repair, fallback,
evidence, or send authority.

The engineering contract passed its deterministic and adjacent regressions,
but the model gates did not qualify. Non-thinking local Qwen3.6 35B and Qwen3
30B each accepted the safe evidence-availability wording `5/5`, then accepted
the first unsupported product test-status counterexample. Their thinking
modes and the available Qwen3-VL 32B did not expose a usable strict structured
channel. MiniMax-M3 strict tool use accepted the safe side `5/5` but failed at
the first unsafe request and had about `17.766s/19.094s` p50/p95 latency.
DeepSeek V4 Pro passed the safe half `5/5`, then accepted the first unsafe
test-status counterexample under the v4 prohibited-extension contract, so it
is not qualified for the Audit role.

The current-input Composer-only check then accepted two replies that no longer
invented a product test history, but both extended variability factors beyond
the offered budget and attempt three failed `composer_internal_language`.
Because the Audit and Composer frozen prerequisites both failed, no replacement
Fixed-8 was run. Repeated Prompt additions are not the next owner.

Formal Evidence Convergence and the Model-first Composer remain disabled by
default, the candidate remains review-only, and no production promotion or
real-accuracy claim follows. The immediate work is now:

1. qualify one stronger, approved or BYOK model independently for the Unified
   Audit and Composer roles against the frozen semantic and structure gates;
   do not weaken the schema, Validator, evidence budget, or one-call contract;
2. after both role gates pass, run one new native Fixed-8 through the same
   formal Pipeline and judge the customer-visible replies;
3. after the next complete gate is clean, run the documented cognitive-consolidation
   shadow comparison before deleting or merging any LangGraph node;
4. preserve the P0 owner and safety boundaries while locating the earliest
   remaining quality gap; and
5. keep unapproved provider matrices, protocol validators, Fast Path work, frontend
   expansion, vision work, and platform adapters frozen unless P1 evidence
   makes one of them the earliest blocker.

P1.2b adds a disabled bounded-low-risk inference contract to the existing
owners. Domain Packs declare premise families, qualitative scope, risk ceiling,
required qualifiers, prohibited extensions, and mandatory review. Claim
Resolution originally required an already nominated intent and therefore
produced no bounded denominator in the representative gate.

The single permitted provider preflight succeeded, but the four-case live gate
stopped at `0/4`: all four requests completed with one selected evidence item,
three Composer candidates were accepted and passed both audits, but no case
produced a policy nomination or bounded-inference denominator; the comparison
case additionally failed on an unknown goal reference. The 16-case and
synthetic suites were therefore not started. This is a reviewable disabled
checkpoint, not a qualified capability and not a real-accuracy result.

P1.2c corrects that earliest ownership break without adding another reasoning
owner. Claim Resolution now computes a deterministic
`eligible_policy_options` intersection from the trusted Domain Pack, admitted
direct premises, authoritative customer goal family, risk ceiling, context
capabilities, and conflict state. A trusted exact intent may narrow this set;
missing goal-family authority forces the set to zero and never selects a
policy. The Composer may choose zero or one offered option for each goal; the
server restores the selected policy, admitted premises, and exact scope in the
clause. Deterministic Final revalidates the offered-set membership, Domain Pack
identity, premises, scope, risk, review-only marker, qualifiers, and
prohibitions. Unified Textual Audit remains the only textual audit.

The path remains default-off, review-only, and non-sendable. The P1.2c live
gate stopped after the first representative request: Provider execution,
Composer acceptance, direct-fact preservation, goal coverage, and both audits
succeeded, but `eligible_policy_options` remained `0/0`. Persisted context
showed that the trusted Domain Pack was not propagated into
`AdmittedAnswerContext`, so Claim Resolution had no bounded policies to filter.
The other three representative cases, the 16-case gate, and synthetic
benchmark were not run, and the failed case was not retried. The next earliest
owner is the existing Answer Eligibility owner-context propagation into
Evidence Builder; no new service or reasoning owner is warranted. Current
status is `bounded_inference_shadow_not_qualified`, not a real-accuracy result.

P1.2d reuses that ownership chain and fixes the propagation boundary.
`AnalysisPipelineService` resolves one server-owned
`trusted-domain-policy-context/v1` from deployment configuration, a verified
server mapping, or an isolated evaluation fixture. The projection carries an
anonymous binding summary, Pack reference and canonical content hash, and has
no evidence, fact-support, reply, or send authority. `FilePolicyRepository`
remains the sole loader and revalidates the reference and hash before Evidence
Builder passes the control context separately from admitted facts. Claim
Resolution, Composer, and Deterministic Final cross-check the same Pack
identity. Missing, invalid, stale, or public-injected context yields no options
while already admitted direct facts remain usable. The path remains
default-off and not qualified until its gated live sequence passes.

The first P1.2d live request was not retried. Its Snapshot shows successful
context selection, Pack hash preservation and reload, nine policies in Minimal
Decision Context, one preserved direct fact, and no evidence pollution. The
gate still produced zero options because upstream Understanding marked both
goals high-risk and nominated an absolute guarantee for the unmapped durability
goal; Claim Resolution correctly failed closed. The next earliest owner is
goal-level risk/policy nomination, not Domain Context propagation. The
remaining live and Synthetic gates are pending, so this is not a qualification
or accuracy result.

P1.2e keeps the same owners and separates two semantics that P1.2d had coupled:
the customer may request a prohibited absolute guarantee while the Agent may
still offer a review-only practical explanation derived from an admitted
premise and the trusted Pack. Claim Resolution retains one unresolved
restricted boundary and separately exposes a low/medium answer strategy;
Composer may select only from that offered set, and Final/Audit must preserve
both risk levels and all premise/policy/scope/Pack attribution.

The single P1.2e live request was not retried. The restricted boundary and risk
separation each scored `1/1`, but Composer supplied a policy reference outside
the goal-scoped offered set, so validation failed closed. The remaining three
representative cases, Gold 16, and Synthetic benchmark were not started. A
deterministic correction prevents an already-supported direct-fact goal with
unrelated high request risk from receiving a practical option. Current status
remains `bounded_inference_shadow_not_qualified`; no production flag or send
authority is enabled.

P1.2f removes the next Composer ambiguity without adding another owner. The
existing Composer now receives only per-goal offered option projections with
short request aliases. Exact server-side bindings preserve goal, policy,
premise, scope, requested risk, answer-strategy risk, restricted boundary, and
Pack identity for Final and Audit. Full Pack policy lists and canonical policy
identifiers are not exposed to the Provider, and no output repair, retry, or
guessing is allowed.

The prior failed input is not eligible for Frozen 5x replay because the raw
returned reference and exact historical prompt/schema/source hashes were not
persisted and the source changed after the run. Deterministic projection,
mutation, and related P1.2 tests pass; no new live Provider call was made.
Frozen 5x and all later qualification gates remain pending, so the candidate
is still default-off and not qualified.

P1.2h adds no owner. The existing Composer derives `forbidden`, `optional`, or
`required` selection completeness from the existing resolution status and
goal-local offered options, while the model remains responsible for choosing
the option and wording. Frozen Composer qualification passed `5/5` with one
call per attempt and no retry, repair, or fallback. The first fresh full-chain
case then stopped once, without rerun: the authoritative understanding
contained only one of the two current-message goals, which removed the
supported direct-fact clause before Composer. Later live and Synthetic gates
remain unrun, so the candidate is still default-off and not qualified. The
next owner must be proven at the authoritative goal-completeness boundary,
not patched in Composer output.

P1.2k.6i separates engineering preservation from model capability. The
accumulated Domain Policy, Claim Resolution, Composer, Deterministic Final,
and Unified Audit v2 contracts passed their deterministic, mutation,
Pipeline, Replay, documentation, and versioned synthetic-safety gates and are
saved as a default-off engineering checkpoint. The checkpoint does not satisfy
the P1 customer-outcome gate and does not authorize deployment.

The available MiniMax M3/M2.x models failed the old Unified Audit v2 model
qualification. Local model comparison then exposed a rubric defect: the old
negative candidate was a reasonable bounded answer under the product-owner's
approved conversational target. After correcting the Domain Pack budget and
using a true absolute-guarantee counterexample, loopback `Qwen3.6:35b` passed
the frozen `5+5` gate. Fixed-8 is now the next allowed gate; production flags
stay off and `real_customer_accuracy=null`.

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

The first P1.1a 26-call attempt is retained as an integrity-blocked diagnostic,
not a baseline: report projection omitted the canonical history position and
the finalization failure prevented persistence of the start knowledge
fingerprint. The evaluator contract is being corrected without rerunning the
Agent in the same phase. No P1.2 owner may be selected until one new,
fully-attributed split report passes all integrity gates.

The subsequent P1.1b attempt stopped on its second response because trusted
reference projection failed before the raw response shape could be diagnosed.
P1.1d therefore adds the final permitted evaluator-infrastructure change: a
private, privacy-checked projection failure capsule is atomically persisted
before case projection. It records only field shapes, counts, allowlisted enum
codes, HMAC/Base32 reference aliases, relationships, hashes, and a safe failure
code. It is never used for scoring, Agent input, delivery, or a business result.
After this checkpoint, evaluator expansion is frozen; the next clean 26-case
run must either establish the baseline or identify one concrete production
owner from the capsule.

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

**Release-track boundary**

- Supervisor Assist development and human review require the existing Composer,
  Deterministic Final, and review-only Delivery boundary. A deterministic Final
  failure remains blocked; an unavailable or unqualified Unified Audit is
  reported as advisory quality evidence and never grants delivery authority.
- Autonomous Send additionally requires a qualified independent Unified Audit,
  approved real-accuracy evidence, Safety and Delivery qualification, and a
  separately approved low-risk rollout. P1 does not enable it.

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
| P1 Gold Conversation Quality | active; recovered Fixed-8 assets blocked; Autonomous Send provider-blocked | The recovered P1.4i deterministic contract passes, and DeepSeek V4 Flash Composer requalified `5/5` with one call per attempt, no retry/repair/fallback, zero formal-knowledge DML, and no send authority. The required immutable Fixed-8 dataset, manifest, query-only knowledge snapshot, and runtime binding are absent from the recovered source, local Git history, and recovery inventory. `real_accuracy=null` | Restore the exact versioned Fixed-8 asset bundle, validate all hashes, then rerun the same blind gate. Keep Autonomous Send blocked until independent Audit, real accuracy, Safety, and Delivery qualify |
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
