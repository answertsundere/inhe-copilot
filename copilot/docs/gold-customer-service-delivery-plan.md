# Gold Customer Service Agent Delivery Plan

## Purpose

This is the execution plan for a top-tier, platform-neutral customer-service
Agent. It supplements the project charter and priority plan. The charter,
architecture overview, module index, and accepted ADRs remain authoritative if
they conflict with this document.

The target is a capable human-service outcome: understand every buyer need,
preserve context, obtain current facts from the right source, answer supported
parts naturally, expose unsupported parts honestly, and hand off only the
unresolved or high-risk part. It is not a static FAQ bot or an uncontrolled
auto-reply bot.

## Hard Boundaries

- One canonical conversation contract and one formal `AnalysisPipeline` serve
  every channel. Platform-native fields stop at adapters.
- The model may understand, organize, and write. It is never the source of
  product, order, price, inventory, logistics, policy, delivery, or completed
  action truth.
- Every buyer-visible claim needs an eligible source, identity scope, and
  freshness class. Missing, ambiguous, stale, failed, or unauthorized data
  fails closed to a stated limitation or durable human handoff.
- `can_send` remains false until delivery, audit, real-accuracy, and operational
  gates pass. Supervisor Assist is not Autonomous Send.
- Evaluation labels and expected answers stay outside Agent input. Synthetic
  results are regression evidence only, never a real-accuracy claim.
- No production branch may depend on a sample sentence, product name, SKU,
  order ID, scenario ID, or expected reply.

## Dynamic Truth Policy

Product data changes. Source selection follows volatility and risk, not whether
a local knowledge card exists.

| Fact class | Examples | Answer-time source | Failure behavior |
|---|---|---|---|
| Live operational truth | order, logistics, refund, stock, price, promotion | typed read-only JST, platform, or approved operational tool | do not assert; request the minimum identifier or hand off |
| Changeable product truth | SKU variant, enabled state, color, dimensions, package, current media, installation material | exact product/SKU identity plus approved live source, timestamp, and provenance | state that current data cannot be confirmed and hand off only that part |
| Governed stable knowledge | policy, approved safety boundary, durable SOP | versioned reviewed knowledge or policy pack | unresolved or handoff; do not infer a stronger claim |
| Conversation context | current request, supplied photo, confirmed identifier, preference | canonical provenance-bearing conversation context | ask only for missing context; never repeat a confirmed request |

Local knowledge is a reviewed cache, policy source, or retrieval hint. It cannot
override a required live source. A live result must not be silently persisted as
permanent product truth. Freshness, timestamp, identity scope, authority, and
failure reason must survive into trace and final admission.

## P0: Runtime and Safety Baseline

**Outcome:** one reproducible, observable, fail-closed runtime.

**Scope:** canonical `/api/analyze`, source identity, readiness, secret
injection outside Git, trace persistence, deterministic final gate, and
rollback.

**Exit:** clean runtime identity, configured provider identity, explicit feature
flags, read-only evaluation snapshot, no secret leakage, and verified rollback.
An unready store reports `not_ready`.

## P1: Gold Conversation Quality (Active)

**Customer outcome:** every explicit buyer need becomes an atomic goal; relevant
open goals and supplied context continue across turns; the reply covers every
supported goal and makes the unresolved remainder clear.

**Allowed owners:** existing Turn Understanding, canonical conversation-goal
lifecycle, Claim Resolution, formal P1 runner, and their contract tests.

**Work order:**

1. Preserve atomic goals with exact current-message provenance. Keep customer
   goals separate from evidence dependencies, media requests, and side effects.
2. Continue goals only through server-owned opaque aliases and only where a new
   current-message span has the same identity.
3. Rebuild requested-claim projections only from canonical goals. Claim
   Resolution must account for every renderable goal as supported, unresolved,
   prohibited, tool-pending, or handoff-required.
4. Measure omissions, duplicates, unexpected goals, repeated-known-context,
   and partial answers through the same pipeline as `/api/analyze`.
5. Run E0 contract/mutation tests, E1 reconstructed Fixed-8, then approved E2
   long conversations. Keep every P1 candidate review-only.

**Current item:** `P1-MULTIGOAL-001` repaired one deterministic Turn
Understanding scope conflict: a dimension goal with an exact source span that
unambiguously names packaging, the complete product, a component, an
accessory, or an included item now retains that scope instead of trusting a
conflicting model declaration. A mixed span remains ambiguous and is not
guessed. The existing `/api/analyze` diagnostic verified that an unavailable
packaging dimension stays unavailable while the reviewed product dimension is
used only for the product. Composer, Audit, Graph, Delivery, product data, and
`can_send` remain out of scope.

**Current diagnostic:** the follow-up reconstructed E1 completed `8/8` through
the same review-only Pipeline. Dimension-scope attribution improved from
`3/4` to `4/4`; goal-clause coverage stayed `16/16`; formal knowledge was
unchanged with zero DML attempts; `can_send=true` stayed zero; and every
candidate required human review. It remains a dirty-candidate reconstructed
engineering diagnostic. Its standalone eight-case offline review is
contract-valid, explicitly not supervisor approval, and selects
`multi-goal_completion` as the next owner; the r9 technical summary itself
remains marked `awaiting_codex_expert_review`. It has one unsupported high-risk
case and unqualified advisory Unified Audit. It does not establish real
customer accuracy or authorize P2-P7 work.

**Current evidence and blockers:** the latest frozen reconstructed eight-case
Supervisor Assist review is development-only. A contract-validated offline
expert review records factual correctness `2.0/2`, goal completion `1.25/2`,
naturalness `1.25/2`, empathy/politeness `0.625/2`, and business helpfulness
`0.75/2`; it selects `multi-goal_completion` as the earliest owner. It is not
supervisor approval, real-customer accuracy, or permission to change Composer,
Delivery, `can_send`, or handoff ownership. The r9 diagnostic used temporary
approved provider credentials and an ephemeral P1 HMAC; no persistent secret
is recorded, and the runner correctly fails closed when formal runtime
prerequisites are absent. The frozen reconstructed fixture and manifest are
present, but it cannot be relabeled as the separately missing original Fixed-8
asset bundle.

The current compound after-sales diagnostic preserves its condition,
outcome-selection, and compensation requests as three unresolved customer goals
without executing any action. The remaining weakness is therefore not goal
loss: it is the lack of approved current policy/service evidence and durable
handoff receipt for customer-visible next steps. P1 does not bypass the frozen
Composer contract to invent those steps. See
`docs/p1-multigoal-completion-boundary.md` for the required P3/P4
reauthorization boundary.

**Next gate:** `P1-E2-001` evaluates the existing formal Pipeline on an
authorized, deidentified long-conversation review set. It measures goal
coverage, context continuity, factual restraint, unresolved handling, and
human-review safety without importing static product facts or enabling sending.
The governing plan is `docs/p1-e2-long-conversation-evaluation-plan.md`.

**Exit:** E0, E1, and E2 have comparable before/after reports showing improved
goal completion, continuity, or unnecessary handoff without a safety regression.
E1 must use a configured formal runtime and a valid, explicitly identified
frozen dataset; E2 requires approved long-conversation review. This still does
not establish real customer accuracy.

## P2: Dynamic Evidence and Live Tool Convergence

**Customer outcome:** volatile questions use current, identity-scoped, read-only
evidence instead of static product records.

**Entry:** P1 has a qualified E2 result and a source-of-truth ADR is accepted.

**Work order:**

1. Inventory JST and DingTalk live-read field authority, TTL, identity
   requirements, rate limits, and customer-visible disclosure rules.
2. Define typed product/SKU live-read contracts in the existing Tool Registry;
   do not add a parallel Agent path.
3. Require volatile goals to have exact identity, timestamp, freshness,
   provenance, and least-privilege output filtering. Internal cost and
   operational-only fields are not customer-visible by default.
4. Test timeout, stale data, identity mismatch, partial response, unavailable
   platform, permission error, and source disagreement. Every case becomes a
   bounded unresolved result or handoff, never a guessed fact.

**Exit:** live evidence is read-only, traceable, redacted, and consumed by the
formal Pipeline. Static knowledge cannot override required live evidence.

## P3: Evidence-Grounded Service Resolution

**Customer outcome:** ordinary questions receive a progressive answer from the
correct combination of product, policy, and live operational evidence.

**Work:** exact identity resolution, evidence role separation, policy-bound
reasoning, partial-answer rendering, media delivery matching, and service
outcome assessment without claiming unexecuted refunds, replacements,
compensation, or platform actions.

**Exit:** approved real-Gold thresholds for supported-claim correctness,
evidence attribution, tool completion, and unresolved coverage.

## Cross-Cutting Customer Experience Contract (P3-P4)

**Customer outcome:** the Agent sounds considerate and capable while it solves
the buyer's actual problem first. It may offer one relevant next product only
when the buyer's need, candidate eligibility, and stated benefit are all
traceable. Empathy and commercial judgment must not manufacture facts or turn a
complaint into a sales opportunity.

**Scope boundary:** this is a design and acceptance contract, not a second
reply owner and not a P1 runtime change. P1 remains restricted to multi-goal
understanding and Claim Resolution. Runtime work starts only after P2 current
evidence and P4 durable handoff prerequisites are accepted.

**Service strategy:** persist a provenance-bearing, non-factual service
strategy beside the canonical goals. `customer_emotion` is an interaction
signal, never a diagnosis, buyer profile, product fact, or evidence admission
override. It may select only a bounded response mode: resolve, clarify,
offer_handoff, direct_handoff, or suppress_recommendation. A direct request
for a human, a high-risk/action case, or a configured severe complaint creates
or updates a `HandoffTask`; it cannot be represented by a customer-facing
sentence alone. Repeated unresolved goals must be detected from canonical
conversation state, not keyword matching or a sample phrase.

**Natural response rules:** acknowledge the concrete inconvenience without
claiming an unverified outcome, avoid internal-engine wording, answer supported
parts before asking for only the missing identifier or evidence, and preserve
the buyer's confirmed context. A reply cannot state that a refund, replacement,
compensation, delivery, escalation, or follow-up has happened unless a typed
tool or durable task gives that completion receipt.

**Controlled recommendation rules:** recommendations are permitted only when
the buyer explicitly asks for options, or the primary service goal is resolved
and the buyer's expressed need creates a relevant opportunity. Every displayed
candidate requires: exact current identity; a live, customer-visible catalog
result; active/eligible availability; evidence-backed benefit and compatibility
rationale; and live price or promotion terms whenever either is mentioned.
Present a small configured maximum (default no more than two) and explain the
specific need it addresses. Do not infer a child's age, health, development,
family circumstance, budget, or suitability from tone, history, or a broad
product category. Do not recommend during an unresolved complaint, safety or
after-sales risk, direct human request, identity ambiguity, missing live
evidence, or an opt-out. Failed/stale catalog or promotion reads suppress the
recommendation rather than falling back to static copy.

**Evidence and review:** store the service-strategy reason, goal IDs, source
timestamps, candidate IDs, eligibility result, stated claims, promotion terms,
and suppression/handoff reason in trace. Recommendation and empathy wording
remain review-only until E3/E4 evidence is accepted; neither can widen
`can_send`.

**Exit:** contract and mutation tests cover human requests, anger/negative
feedback, repeated unresolved goals, direct shopping requests, complaint
suppression, stale or ineligible candidates, promotion expiry, opt-out, and
sensitive-attribute non-inference. Approved real-Gold review must separately
measure respectful resolution, inappropriate recommendation rate, candidate
relevance, unsupported commercial claims, handoff correctness, and latency.

## P4: Supervisor Assist and Durable Handoff

**Customer outcome:** the supervisor sees context, atomic goals, evidence,
unresolved reasons, proposed reply, and a real handoff task.

**Work:** formal `HandoffTask` ownership, assignment, SLA, acknowledgement,
status, audit history, minimal context projection, reviewer feedback, and
outcome capture. Feedback never becomes product truth automatically.

**Exit:** high-risk, missing-live-data, identity-ambiguous, and action cases
produce traceable work, not a sentence-only handoff.

## P5: Real Evaluation and Continuous Improvement

**Customer outcome:** improvements are measured on real customer outcomes, not
internal demonstrations.

**Work:** privacy-safe de-identification, approved real-Gold labels, daily
read-only replay, error taxonomy, cohort scorecards, regression review, and
rollback.

**Exit:** approved E3 labels support a scoped real-accuracy claim. Every model,
prompt, tool, data, and flag change has comparable before/after evidence.

## P6: Omnichannel Adapters

**Customer outcome:** the same qualified Agent serves QianNiu, Pinduoduo, JD,
and later channels without platform-specific Agent reasoning.

**Exit:** all channels use the same AnalysisPipeline and evaluation suite; each
has explicit delivery capability and independent rollback.

## P7: Bounded Automation

**Customer outcome:** only an approved low-risk, evidence-complete scope may
auto-send. All other cases remain Supervisor Assist or Handoff.

**Entry and exit:** E4 Supervisor Assist acceptance, E5 scoped automation
canary, independent audit, delivery receipts, incident response, kill switch,
and product-owner approval. Results never generalize beyond the approved intent,
channel, tool, and freshness policy.

## Evaluation Ladder

| Gate | Required evidence | Permitted conclusion |
|---|---|---|
| E0 | unit, contract, mutation, and safety tests | local behavior is protected |
| E1 | same-pipeline Fixed-8 | development diagnostic only |
| E2 | approved long conversations | P1 capability progress only |
| E3 | approved real Gold set | real accuracy for measured scope |
| E4 | Supervisor Assist canary | operational reviewer acceptance |
| E5 | bounded automation canary | automation only for that exact scope |

Every behavior change records dataset approval state, runtime source hash,
provider/model identity, feature flags, entry point, scorable/excluded counts,
goal completion, evidence/tool coverage, unresolved/handoff behavior,
unsupported claims, latency, DML, `can_send`, and delivery outcome. Without an
approved real dataset, report `real_accuracy=null` and
`optimization_unverified=true`.

## Immediate Queue

1. **P1-MULTIGOAL-001, in progress:** record the completed eight-case
   development diagnostic and preserve its review-only boundaries. Its validated
   offline review selected `multi-goal_completion`; it is not a supervisor
   acceptance or an accuracy claim.
2. **P1-MULTIGOAL-002, pending:** restore a qualified formal Provider/HMAC
   runtime, verify the present frozen reconstructed E1 manifest/binding, and
   complete the required human-quality review. Do not relabel the reconstructed
   fixture as the missing original dataset or retry hidden provider failures.
3. **P1-MULTIGOAL-003, pending:** after E1 identifies the earliest generic
   continuation or omission defect, repair only that owner and add regression
   and mutation tests. Composer, Audit, Graph, Delivery, live products, and
   `can_send` remain frozen.
4. **P1-MULTIGOAL-004, pending:** rerun E1 after the repair, then prepare the
   independently reviewed 26-conversation E2 gate. Do not claim real accuracy.
5. **P2-DYNAMIC-EVIDENCE-DESIGN, pending:** research and ADR for promotion of
   existing JST/DingTalk live reads into the formal Tool Registry and evidence
   admission chain. Start only after the P1 entry gate.
6. **P3-CUSTOMER-EXPERIENCE-CONTRACT, planned:** after P2/P4 prerequisites,
   design the typed service-strategy, durable handoff linkage, and controlled
   live-catalog recommendation contract. Do not implement a marketing reply
   path from emotion or static knowledge.


## Stop Conditions

Stop downstream work and return to the owning phase when a provider is
unconfigured, a live source lacks authority or freshness, identity is ambiguous,
evidence is missing or contradictory, an action lacks a typed completion receipt,
a handoff contract is absent, or a candidate would enable unsupported delivery.
Do not solve these conditions with static facts, prompt-only certainty, or silent
fallbacks.
