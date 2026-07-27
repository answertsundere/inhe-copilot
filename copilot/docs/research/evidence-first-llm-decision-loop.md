# Evidence-First LLM Decision Loop

## Scope

Phase 0.5A evaluates an evidence-first decision loop after the existing Agent
graph has returned. It is a shadow comparison, not a replacement for the
formal response path. The current graph still executes identity resolution,
retrieval, and tools. The shadow loop separately proposes a bounded read-only
tool plan, lets the application execute only registered local lookup tools,
admits the returned candidates, and then asks for a reply proposal.

## Reusable provider principles

OpenAI Structured Outputs can constrain a model response or function arguments
to a supplied JSON Schema with strict schema adherence. OpenAI function calling
still leaves function execution to the application, which returns tool output
for a later model turn. See the official [Structured Outputs
guide](https://platform.openai.com/docs/guides/structured-outputs) and
[function calling guide](https://platform.openai.com/docs/guides/function-calling).

Anthropic client tools likewise declare an `input_schema`; the model emits a
`tool_use` block, the client executes the named tool, and a later user message
returns a matching `tool_result`. Tool choice is a model proposal, not tool
execution or authorization. See Anthropic's official [tool-use implementation
guide](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use).

The reusable principles are provider-neutral:

1. Model understanding, tool selection, evidence selection, and reply planning
   cross strict structured boundaries.
2. The application executes tools and owns identity, authorization, review
   state, evidence eligibility, conflicts, and external actions.
3. Raw retrieval candidates are not answer context. Tool results pass a
   deterministic admission contract before another model turn can use them.
4. A proposal never grants `can_send`, issues refunds or replacements, or proves
   safety, certification, suitability, load, order state, or media delivery.
5. Schema errors, unsupported structured-output providers, and unknown evidence
   references fail closed. Free text is not used as a fallback decision.

## Phase 0.5A implementation

The application performs two strict schema calls when
`COPILOT_LLM_DECISION_SHADOW_ENABLED=true`:

1. `DecisionIntake` separates a compound customer message into claim requests
   and proposes which tool classes would be needed.
2. The application executes the eligible local read-only part of that plan.
   Product resolution and RAG lookup use the existing tool registry. Order and
   media requests are recorded as deferred until bounded shadow adapters exist;
   they are never treated as successful lookups.
3. `AdmittedAnswerContextService` compiles current graph and shadow-tool
   candidates into direct
   product facts, direct policy facts, handoff actions, media candidates,
   rejected evidence, unresolved claims, and conflicts.
4. `AgentDecisionProposal` may cite only admitted evidence UIDs and actual reply
   block references. Any unknown UID, unsupported assertion, extra send field,
   or invalid schema becomes a review-only empty proposal.

This remains post-graph and shadow-only. It may duplicate a local read-only
product or retrieval lookup for comparison, but cannot execute order actions,
media delivery, refunds, replacements, or platform writes. Moving the loop
before formal retrieval still requires parity evaluation across API, copilot,
replay, and benchmark.

## Strict Provider Qualification

Decision Shadow does not reuse `COPILOT_LLM_*`, which belongs to the formal
reply model. It uses a separately configured strict provider and remains
fail-closed unless `COPILOT_DECISION_LLM_QUALIFIED=true` for an independently
qualified `strict_json_schema` or `tool_call_schema` transport. JSON-object and
prompt-only JSON modes are not fallbacks. See
[`strict-decision-provider-qualification.md`](strict-decision-provider-qualification.md).
Truncated model responses are explicit qualification failures; the client never
repairs or extracts a partial JSON payload.

## Evidence roles

- `product_fact_direct` and eligible scoped `faq_direct` may enter direct product
  facts only after identity, review, gate, placeholder, claim-type, and conflict
  checks.
- `policy_fact_direct` remains a separate direct policy role.
- `service_action`, `fallback_only`, and generic rules are action guidance.
- Answer Memory remains tone and action guidance outside product truth.
- `media_reference` and recommended assets remain candidates. They do not prove
  media delivery.
- Product Media Observation and annotation artifacts remain shadow inputs and
  are not collected by the admission service.

## Compound claims

A question about material, safety, and moisture is three claim requests:
`material_composition`, `material_safety`, and `moisture_resistance`. A reviewed
material name can support the first request. It does not resolve the other two.
The unresolved items remain visible to the proposal and semantic judge so a
natural controlled handoff can distinguish confirmed facts from pending facts.

## Partial Answer Contract

Admission produces one stable `claim_uid` for every requested claim. A
resolution is `supported`, `unresolved`, `conflicting`, or explicitly
`prohibited`, with admitted or conflicting evidence UIDs and the review reason.
A proposal must copy those resolutions exactly, render one confirmed clause for
every supported claim, and retain one pending or conflicting clause for every
other claim.

This prevents a missing high-risk fact from erasing an independently supported
low-risk fact, without allowing a material name to imply safety, moisture
resistance, certification, or suitability. The application validates clause
evidence UIDs and fails the shadow proposal closed on an omitted supported claim
or an assertion for an unresolved claim. The contract remains diagnostic: it
cannot modify the formal reply, delivery blocks, or `can_send`.

The supervisor preview is provider-independent. When the provider is
unqualified, deterministic rendering may compose only the same admitted
confirmed clauses and controlled pending/conflict wording. It does not parse
free text or repair JSON. Fixture scoring separately measures claim resolution,
supported coverage, pending/conflict retention, evidence citations, identity
leakage, internal jargon, mojibake, unsupported media promises, and
formal-field mutation. The fixture supplies raw requested claims, admitted
facts, conflicts, and context, never precomputed claim resolutions. Expected
outcomes remain scorer-only. Attribute-qualified claims may use only the same
canonical evidence attribute; missing attributes stay unresolved, and an
unqualified request with several attribute candidates is selection-ambiguous.
The isolated audit diagnostic is fail-closed: final-audit/semantic failures or
diagnostic errors make the preview evaluation fail.

## Formal Claim And Media Evaluation

Formal delivery evaluation compares requested claims with evidence admitted for
those same claims. Related context is not sufficient for a stronger safety,
certification, child, or performance conclusion. The runtime records evidence
UIDs and deterministic reasons rather than private reasoning. The read-only
`scripts/run_full_answer_validation.py` runner records dataset/API metadata,
deduplicated selected evidence, high-risk delivery failures, and media-role
mismatches without sending expected outcomes to the Agent. The formal QA input
uses `formal-answer-validation-dataset-v1`: every case declares a nonempty
query fact type, explicit boolean handoff boundary, and canonical high-risk
claim list. Legacy expected fields are rejected rather than silently ignored.
The runner returns `0` only for an all-pass/all-response run, `1` for any
case, transport, parsing, safety, media, or response-contract failure, and
`2` for invalid datasets or unmet preconditions. Its report distinguishes
runner source metadata from API runtime metadata and records only sanitized,
read-only diagnostics. The canonical high-risk registry is shared with
admission and the final auditor; ordinary material composition never proves a
safety claim.

The runner first reads the runtime readiness endpoint. It must stop with exit
code `2` before calling `/api/analyze` when the formal knowledge database is
missing, unreadable, incomplete, empty, changed during fingerprint, or
inconsistent with an explicitly supplied local `content_sha256`. The runner
compares the runtime `content_sha256` (actual file content) with the local copy
and reports `runtime_database_content_sha256`,
`local_database_content_sha256`, `schema_fingerprint`, `counts`, and
`comparison_status`. This prevents an empty placeholder database from being
measured as an ordinary retrieval miss.

## Evidence convergence diagnostics

The Product Context Pack, formal `selected_evidence`, admission context, and
decision-model context are separate stages. A reviewed structured product field
can be an eligible Product Context Pack candidate even if the current formal
response did not select it. `AdmittedAnswerContextService` normalizes only
structured-profile protocol candidates that already declare verified status,
direct-answer permission, and an explicit matching product or SKU scope. It
does not promote ordinary retrieved chunks, generic rules, Answer Memory, or
media references.

The resulting `evidence_convergence` trace records the source containers,
identity scope, formal-selection state, shadow-admission state, and the reason
for any rejection. This makes a generic handoff diagnosable without treating a
single product question as a new routing rule. The trace is shadow-only and
cannot change the formal reply, delivery, review decision, or `can_send`.

### Phase 0.8C evidence-role findings

The fixed 68-turn funnel supports a narrower root-cause statement than “RAG did
not retrieve.” The 31 role-ineligible turns split into 23 structured-field
protocol metadata losses, seven unsafe high-risk promotion candidates, and one
correctly rejected non-fact. The 37 source gaps split into 13 missing sidecar
contexts and 24 order/live-state requirements. These categories are mutually
exclusive, report pseudonymous diagnostic UIDs, and assign an owner without
using customer text, product names, or identities as routing rules.

Preserving explicit protocol metadata during Pack compaction allowed a
query-only real-derived slice to select and admit 15/15 reviewed facts from 12
products across material, dimensions, and gross weight. The underlying inventory
contained 393 products with at least one eligible fact and 428 eligible facts;
the fixture selected the smallest deterministic coverage set that met the
five-product, 15-fact, three-type minimum. Seven negative controls remained
rejected. Only two selected dimension facts were available and canonical
dimension attributes remain absent. This proves evidence plumbing, not answer
accuracy: the questions are labelled capability probes, the production flag is
still off, and the real-accuracy numerator and denominator remain unchanged.

The API closure confirms why evidence and delivery must be assessed separately.
Product media records are emitted as `media_reference`, never as direct product
facts. A candidate or recommended asset is not an attached asset. Delivery also
requires approval, usability, fact-type compatibility, and an exact shared
identity namespace. The final state normaliser makes blocked, unresolved
high-risk, audit-failed, and non-fact-only results non-sendable and review-only.

After this correction, the isolated 5012 1x1 gate passed 3/3 and the 5-product
by 3-question slice passed 15/15. Direct facts were admitted, mixed questions
kept supported and unresolved claims separate, and non-fact-only requests had
zero selected facts and zero media blocks. Protected table counts did not
change. The versioned safety benchmark remained 5/5 and 22/22 with zero
auto-send cases. These results validate evidence plumbing and fail-closed
delivery only; they do not create a real-customer accuracy denominator or
authorise the production feature flag.

## Material provenance and review staging

AWS Ground Truth review batches and Label Studio review workflows both keep a
review decision separate from the original training or source record. This
project reuses that narrower principle rather than introducing a second
knowledge platform: material remediation is grouped in an independent staging
store, records reviewer decisions with optimistic locking, and has no apply
operation to formal knowledge in this phase. A `published` product status is
not field provenance. Direct material composition additionally requires an
explicit non-placeholder source, matching identity, a reviewed/direct evidence
contract, and a value that does not mix safety or compliance claims. The
real-derived Shadow QA keeps scoring expectations outside admission payloads
and evaluates only pseudonymous composition evidence plus unresolved claim
preservation.

## Automated gold customer-service validation

Material answer review no longer requires a person to score every candidate.
The deterministic evaluator separates objective gates from future subjective
model review:

- objective gates verify that admitted composition is actually answered, every
  unresolved high-risk claim remains unresolved, bite/toxicity wording includes
  an immediate safety action, media promises match reply blocks, and formal
  delivery state remains safe;
- copy checks reject internal jargon, mojibake, generic handoff-only replies,
  irrelevant topics, and unnecessarily long customer text;
- a negative mutation suite removes or changes supported material, asserts
  unsupported safety/certification, enables unsupported cleaning delivery,
  injects washing/soaking/alcohol/temperature/detergent instructions, removes
  either bite-safety action, replaces the answer with generic handoff, promises
  unattached media, leaks an internal identity, drops a supported clause after
  semantic fallback, or treats a service/action/media role as product fact.
  Every mutation must fail.

This follows the mature evaluation split between deterministic/custom metrics
and optional LLM judges. DeepEval documents G-Eval as useful but non-
deterministic for subjective criteria and recommends deterministic DAG/custom
metrics when reproducibility is required. OpenAI Evals similarly supports
model-graded evals, but this project does not use an unqualified provider as an
authority. A future qualified judge may assess tone as a second opinion; it
cannot override evidence or safety failures.

The formal `/api/analyze` runner is deliberately separate from the Shadow
renderer. It uses real identities internally, emits only HMAC identities, and
does not send scorer expectations to the Agent. A dated 2026-07-18 baseline
showed that process-only Evidence Convergence made an ordinary composition
answer traceable, while material-safety, bite/toxicity, odour, cleaning, and
certification still failed the gold-CSR contract. The formal partial-answer
path now retains a supported composition clause while unresolved derived claims
stay non-sendable; its real-runtime results remain separate from Shadow metrics
and never approve knowledge or alter the evaluation fixture.

## Promotion gates

Promotion requires real traces with valid strict structured output, stable
claim decomposition, eligible evidence references only, no unsupported claims,
no formal-field mutation, and parity across every formal entry point. Phase
0.5A is not promoted merely because synthetic tests or active benchmark pass.

## Real-derived validation fixture

`export_real_derived_evidence_fixture.py` reads an explicit SQLite source in
`PRAGMA query_only=ON` mode and exports only published, low-risk structured
product facts. Product identities are HMAC-pseudonymised with an environment
key that is neither emitted nor stored in the fixture. The exporter excludes
mixed product/packaging dimension candidates rather than treating carton values
as product dimensions. A real-derived fixture and its manifest both declare
`source_kind=real_derived`, source snapshot identity, sanitization version,
privacy-scan status, query-only access, and no source-database mutation.
Synthetic fixtures use a distinct source kind and dataset identity.

`run_real_derived_evidence_vertical_slice.py` requires both fixture and manifest
and rejects a missing manifest, hash mismatch, source-kind conflict, missing
source snapshot, failed privacy scan, or source mutation before calling any
Agent code. It replays a validated sanitised fixture through an isolated fixture
database and the real Product Context Pack -> convergence -> admitted context
-> claim-resolution -> supervisor-preview chain. Expected results are scored
after this chain; they are never input to a builder. This validates factual
provenance and contract parity, not a customer delivery path or a `can_send`
decision.

## Canonical context and model-led candidate boundary

Effective context is a curated representation of the active task, not a
concatenated transcript. The formal Pipeline therefore normalizes prior
conversation into bounded role-aware turns before understanding and keeps the
current customer message separate. Evaluation inputs reject malformed context
instead of silently degrading into an empty string history; ordinary legacy
callers expose a degraded-context diagnostic.

The candidate-composition experiment receives only requested claims, admitted
evidence, unresolved/conflicting claim state, compact recent turns, non-factual
service/media options, channel capability, and deterministic safety limits. It
does not receive full traces, raw candidate stores, Answer Memory text, Gold
labels, or benchmark rubrics. A model candidate is supervisor-only and must
preserve precomputed clauses plus pass the existing audit. It cannot establish
facts, change `can_send`, or replace the formal response. Strict structured
action selection remains blocked pending provider qualification; no JSON repair
or free-text parser is used to pretend otherwise.

Canonical formal turns are not evaluation-sanitized in place: local identity
and read-only tools consume the operational structure they need. Before any
external-model call, a dedicated privacy projection removes inline phone,
address, and order-reference text and omits content-derived turn identifiers.
The same sanitized view is used for traces and evaluation output. Sidecar
history is not flattened into `customer_message`; only an exact trailing copy
of the current buyer turn is removed from structured history.

Tier D remains exploratory. Buyer-simulator `observed_action_ids` are
diagnostic only; a strict-schema transcript grader reads rendered Agent replies
for action coverage. Reports must include runtime commit/readiness, feature
flags, source-database fingerprint, formal model, simulator model, and grader
identity. A matching formal and simulator model is a degraded independence
condition, not independent AI evaluation.

### External-model privacy and Tier D identity

External-model prompts use a field-aware privacy projection. It projects plain
text, fenced or embedded JSON, multiple JSON blocks, and labelled identifier
lines. Valid JSON is projected by field name; malformed JSON is never repaired
into a trusted structure, but its raw text still has explicit identifiers and
PII removed. Product titles, categories, admitted evidence, and ordinary room
descriptions remain readable. Structured customer identifiers are replaced by
stable anonymous references before serialization; local read-only tools retain
the original structured identity outside the model prompt. This prevents broad
address matching from erasing product context.

The downstream evaluation/trace sanitizer uses the same semantic-preservation
boundary. A natural-language address must have an explicit address label,
administrative chain, or road/street plus a number; suffixes such as bedroom,
bathroom, living room, or room alone are not address evidence. This boundary
keeps usage, moisture, material, size, and colour questions intact while phone,
email, concrete address, account, order, tracking, URL, and credential values
remain redacted. Any redaction marker that reaches customer-visible reply text
is still rejected by the Final Auditor.

Tier D action coverage is not a keyword counter. It requires an independently
qualified strict-schema transcript grader that sees only customer-visible Agent
replies and action definitions after the response is produced. A missing or
unqualified grader yields `action_coverage=null` and invalidates the run.
Internal action events must agree with the visible transcript but cannot grant
credit by themselves. The transcript-grader qualification records provider,
model, capability, repeated schema stability, local enum/missing/extra-field
and truncation rejection, without reporting credentials. A configured candidate
can run that read-only matrix before human approval, using positive actions and
negative refusal, denial, noun-only, and vague-future examples; this is not the
same as `qualified_for_evaluation` and cannot update configuration. Provider
matrix results and local validator checks have separate metrics. Runtime identity
freezes boot commit/hash/worktree/model/flags and reports current-disk hash
separately; any source drift invalidates Tier D. A dirty candidate requires an
explicit matching boot hash and is never presented as a committed runtime result.

The Tier D runner also treats model independence as an execution precondition,
not a report annotation. It compares a safe identity made from the provider-host
fingerprint and model for the formal Agent, buyer simulator, and transcript
grader. Any unknown identity or pairwise collision exits before a trial. A shared
model name on different hosts is observable risk information, but is not an
identity collision. The host fingerprint is computed from canonical origin only:
scheme, lower-case hostname, and effective port. Paths, query strings, fragments,
and userinfo cannot create a distinct identity or leak into a report.
Qualification persists one safe attempt record at a time (case ID, expected
category, repeat index, result, citation validity, error category, and measured
latency); neither reply text nor endpoint credentials are written to the report.
Timeout, truncation, schema, and free-text counts are calculated directly from
attempt records, while case-level stability keeps separately deduplicated reason
summaries. The latency percentiles use only successful strict calls.

### Provider capability check

The [MiniMax OpenAI-compatible API documentation](https://platform.minimax.io/docs/api-reference/text-openai)
documents compatible chat completion and tool-call interfaces, while its
[text generation reference](https://platform.minimax.io/docs/api-reference/text-post)
limits documented `json_schema` response formatting to specific model support.
Consequently, OpenAI compatibility or a model name alone is insufficient proof
of this project's strict-schema contract. A separately configured candidate must
pass the repeated live qualification matrix before a human can mark it eligible
for Tier D; qualification never changes `.env` or formal Agent configuration.

### Tier D observation and long-load qualification

Tier D scoring no longer reads a wider raw response than the persisted report.
One privacy-projected turn observation is created immediately after the formal
HTTP response and reused by the deterministic scorer, independent transcript
grader, atomic checkpoint, report, and offline consistency pass. Media-send
language without an actual image/video block is therefore reproducibly marked
`unsupported_media_promise`; selected evidence contains only a pseudonymous UID
plus role, fact type, source type, gate, and placeholder state.

Short strict-schema probes are insufficient. The grader must pass positive,
denial, citation, exact-action-schema, serial long-transcript, and runner-
concurrency cases with zero timeout, truncation, schema, or free-text failures.
Its p95 must stay below 80 percent of the configured timeout. The buyer
simulator separately proves long-context state-machine validity and repeat
stability under serial and concurrent calls. A simulator may naturally continue
with a relevant buyer question or accept a handoff; it is not forced to produce
one preferred terminal sentence. `continue` requires a non-empty next message,
while terminal states require an empty one.

Provider identity and schema qualification do not prove that the formal Agent
credential can execute. Before dataset access, the runner performs a minimal
non-customer completion against the exact formal provider identity.
Authentication, quota, rate-limit, timeout, truncation, or response-contract
failure stops the run with a safe reason code. Deterministic Pipeline fallback
after a failed formal-model request cannot be reported as a valid formal-model
Tier D baseline.

The MiniMax M3 candidate subsequently passed the formal transport probe and
completed an infrastructure-valid 9x2 run. The independent buyer and grader
also passed their serial/concurrent qualifications, all nine sources resolved,
and the final checkpoint matched the classified report. The baseline was 0/18
overall, with 50 percent contract pass, 11.11 percent buyer-outcome pass, 75
percent mean action coverage, no selected evidence, and 44 percent consecutive
reply repetition. All 68 formal turns remained `can_send=false` and
`requires_human_review=true`. These measurements prioritize evidence use,
contextual action completion, and reply progression as the next product work;
they do not measure Tier A accuracy and do not justify provider cutover.
After the evaluator provider change, this report was retained with
`superseded_by_provider_change`; it is historical rather than the current
provider baseline.

## Phase 0.8B: evidence use and dialogue progression

The 0.8A report recorded zero selected-evidence turns, but its v1 Turn
Observation did not retain the upstream candidate and admission stages.
Therefore zero selection alone cannot distinguish missing source coverage from
identity/type mismatch, formal admission rejection, disabled convergence, or a
later selection drop. Phase 0.8B adds a read-only turn funnel at the existing
`AdmittedAnswerContextService` owner. It reads the same candidate containers and
admission result; it does not retrieve again or define another eligibility
policy. Persisted records contain pseudonymous UIDs, source roles, fact and
attribute types, and identity namespaces only. Evidence text and identity
values are excluded.

The funnel reports candidate, reviewed-direct, identity-matched,
fact-compatible, non-conflicting, formally-admissible, and formally-selected
counts. It also identifies the earliest observed breakpoint and classifies the
turn as source coverage, identity/fact type, formal admission, or
generation/action usage. When admissible evidence exists but formal convergence
is disabled, the result is explicitly `convergence_disabled`; it is not
misreported as a source gap.

Phase 0.8B.1 narrows this work to one report-safe evidence funnel. Dialogue
State, Action Policy, and counterfactual preview are paused and are not attached
by the formal Pipeline. Runtime reports the Action experiment as
`paused_not_qualified`; stale enablement flags cannot reactivate it. This keeps
the failure analysis at the earliest evidence breakpoint rather than adding a
second reply planner before source coverage is understood.

This design follows four reusable official patterns:

- Anthropic's [context engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  recommends the smallest high-signal context and progressive disclosure rather
  than growing prompts into brittle rule lists.
- Anthropic's [tool design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents)
  keeps tools narrow and application-owned, and its [agent eval guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  evaluates complete multi-turn trajectories rather than one final sentence.
- [LangGraph](https://langchain-ai.github.io/langgraph/index.html) provides
  durable state, checkpointing, and human-in-the-loop orchestration; it does not
  replace this project's admission registry or deterministic delivery gates.
- Rasa's [dialogue management](https://rasa.com/docs/learn/concepts/dialogue-management/)
  and [FlowPolicy](https://rasa.com/docs/reference/config/policies/flow-policy/)
  separate model-proposed commands from deterministic business execution. The
  project reuses that boundary without adding a second dialogue engine.
- OpenAI's [Evals API](https://platform.openai.com/docs/api-reference/evals)
  reinforces typed evaluation data and explicit graders. Phase 0.8B keeps its
  new diagnostics outside the existing Tier D pass score until a versioned
  evaluation contract approves them.

The fixed nine-scenario capture contains 68 formal turns and 68 funnel rows.
No row reached formal selected evidence. Earliest-breakpoint classification is
`source_coverage_gap=37` and `evidence_role_ineligible=31`; there were no missing
funnel rows, formal writes, or `can_send` changes. This locates the current loss
before graph selection and does not by itself measure answer accuracy.

Tier D now uses deterministic per-turn checks and at most one transcript grader
call per trial. If that grader is unavailable, semantic action coverage and the
overall result are `null`; deterministic safety diagnostics are still emitted.
The buyer qualification gate precedes 1x1, 3x1, and 9x2. MiniMax
M2.7-highspeed produced zero valid attempts in both strict-schema and tool-call
modes across short and long/concurrent probes, with only structured-output
parse/truncation failures. The run therefore stopped before grader
qualification or any live trial. No free-text repair, timeout increase, local
Qwen fallback, or scenario change was used.

### Phase 0.9A model-first answer organization

The reply-ownership trace showed that graph generation, style, response
building, polishing, no-evidence policy, and final orchestration could all
rewrite the same customer-facing text. In the ten-scenario diagnostic,
canonical selected evidence was still empty with convergence disabled, making
the earliest useful correction evidence convergence rather than another reply
template or graph branch.

The Phase 0.9A candidate reuses the existing Minimal Decision Context. One
MiniMax-M3 call receives the current goal, bounded recent turns, projected
admitted evidence, claim resolutions, non-factual service/media candidates,
and deterministic safety constraints. It returns only the reply, used evidence
references, and unresolved claim types. All supported evidence references and
unresolved claim types are required; unknown references, process language, or
unsupported media promises reject the candidate. Product identity and
evidence UIDs are not exposed as raw operational identifiers.

Low-risk reasoning is bounded to spatial explanation from confirmed
dimensions, comparison of confirmed variants, use explanation from confirmed
structure/layers, and non-promissory comparison of ordinary plastic with glass.
It cannot infer load, toxicity, food grade, certification, child safety,
anti-tip behavior, installation prescriptions, or order/refund/logistics
state. Final audit, semantic fit, tools, media delivery, and `can_send` remain
application-owned.

The fixed 26-scenario OFF/ON development diagnostic completed without
execution errors, formal-knowledge writes, unsafe high-risk claims, unsupported
media promises, unsupported service actions, or `can_send=true`. ON selected
23 evidence items across 18 scenarios, removed the measured system-tone hits,
and reduced duplicate replies from nine to seven. It also exposed incomplete
answer quality: only 14/23 runtime supported claims survived evidence
attribution plus final audit, four candidates were rejected for process
language, partial-answer success remained 0/8 under the conservative
post-response matcher, and semantic-audit passes fell from 15 to 9. The
candidate is therefore not ready for production promotion.

### P0.2d Composer input eligibility

Resolution status alone is not reply eligibility. The Composer now accepts
customer-visible goals only when the current server Turn Understanding owns a
valid `customer_goal` reference with complete provenance and Claim Resolution
maps it uniquely. Inputs are kept in five explicit partitions:
`renderable_customer_goals`, `supporting_dependencies`, `service_actions`,
`media_context`, and `contextual_constraints`. They are not recombined into a
broad goals list.

Dependencies may supply admitted evidence only through an explicit
`supporting_for_goal_ref` link to a renderable customer goal. They never receive
a customer-visible clause. Service, media, and context entries likewise remain
non-factual. Missing or unknown kinds, degraded compatibility claims, duplicate
references, invalid provenance, unbound dependencies, omitted customer goals,
and extra model clauses fail closed without retry, repair, clause deletion, or
Python-authored fallback.

The frozen anonymous qualification passed five consecutive single-call
attempts. The subsequent fixed-eight run accepted all eight Composer outputs,
covered 15/15 renderable customer goals, rendered zero non-customer goals, made
no formal knowledge writes, and left `can_send=false` for all cases. Final audit
passed 7/8 and semantic audit 4/8, with partial-answer success 3/4; therefore the
durable P0.2d status was `composer_input_qualified_audit_stack_blocked`, not
production qualification.

P0.2e then consolidated the disabled candidate into:

```text
Composer
-> Deterministic Final Contract
-> One Unified Textual Audit
-> Delivery Gate
```

The deterministic Final Contract makes no model call. Unified Textual Audit is
the candidate's sole textual LLM audit, and orchestration only sequences and
synchronizes fail-closed state. The P0.2e.2 fixed-eight diagnostic reached
Composer `7/8` and Unified Textual Audit `7/8`; the remaining unknown reference
was attributed to provider/transport behavior. P0.2f correctly stopped rather
than adding another validator or retry. These are historical diagnostics. The
feature-disabled checkpoint is reviewable but not production-qualified, and
latency remains disclosed rather than treated as a P0 correctness gate.

P0-R1 made the bounded Provider decision without another protocol layer. The
current MiniMax-M3 OpenAI-compatible `json_object` transport passed three fixed,
privacy-safe Composer inputs (`1` supported goal, `2` supported goals, and
supported plus unresolved) in exactly three calls. All returned short goal
references matched the dynamic allowed set, and retry, repair, free-text
fallback, timeout, schema failure, and formal knowledge writes were zero.
Because the current transport passed `3/3`, no forced-tool or strict-schema
alternative was tested.

The sole follow-up fixed-eight run used dataset
`hq-long-conversation-real-derived-v4` version `1.3.2-draft`, content SHA-256
`610c6078ae14118451bee8852ab669208cf824ff809a2c506260bbe80e10f1cf`.
Execution and non-empty replies were `8/8`; Composer, Deterministic Final
Contract, and Unified Textual Audit were `8/8`; customer-goal coverage was
`14/14`, supported attribution `5/5`, unresolved declaration `9/9`, and
eligible Partial Answer `4/4`. Unknown/duplicate/wrong-kind references,
non-customer clauses, unsupported high-risk/media/service claims, fallback,
automatic send, formal knowledge changes, DML, retry, and repair were zero.
Pipeline p50/p95 were `20.411s/28.634s`, Composer `1.986s/3.176s`, and Unified
Audit `2.372s/8.365s`. This qualifies P0 correctness while leaving real
conversation quality, production enablement, and latency optimization to later
gates.

### Phase 0.8G fixed real-turn replay

Phase 0.8G removes the buyer simulator from the OFF/ON comparison. Nine uniquely
resolved, privacy-checked conversations provide four fixed real buyer text
turns each. Every turn sees only the bounded real history available before it;
future historical agent replies, Gold labels, reference answers, and rubrics
are excluded. This is an exploratory long-conversation capability replay, not
Tier A accuracy.

`scripts/build_fixed_long_conversation_replay_set.py` owns the versioned replay
manifest. `scripts/run_fixed_long_conversation_replay.py` pins dataset, source
database, formal knowledge database, runtime commit/source hash, MiniMax M3,
timeout, runner hash, and Pipeline entry point. OFF and ON differ only in
`COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED`. One report-safe Turn Observation
is shared by deterministic scoring, evidence funnel, checkpoint, final report,
and offline recomputation. A missing independent qualified grader leaves action
completion, semantic pass, overall pass, and customer accuracy `null`.

An initial diagnostic completed 1-scenario and 3-scenario OFF/ON pairs. At
three scenarios, OFF selected no evidence while ON selected ten evidence items
across twelve turns. Offline recomputation found one ON
`unsupported_media_claim`, classified as `media_role_mismatch`. The evaluator
was then corrected to rebuild OFF admission through the shared admission owner
and to fingerprint formal knowledge tables rather than the entire mixed-use
SQLite file. The validated rerun stopped at the first OFF tier because
`kb_product` content changed during four Agent turns; row count and schema were
stable, and the other formal tables were unchanged. Nine scenarios were not
started. The earlier three-scenario pair remains a superseded diagnostic, not
an authoritative acceptance result. Neither result proves answer accuracy or
canary readiness.
