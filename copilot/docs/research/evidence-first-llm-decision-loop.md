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
mismatches without sending expected outcomes to the Agent.

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
as product dimensions. The manifest records source and fixture hashes, table
fingerprints, privacy-scan status, and coverage gaps.

`run_real_derived_evidence_vertical_slice.py` replays the sanitised fixture
through an isolated fixture database and the real Product Context Pack ->
convergence -> admitted context -> claim-resolution -> supervisor-preview
chain. Expected results are scored after this chain; they are never input to a
builder. This validates factual provenance and contract parity, not a customer
delivery path or a `can_send` decision.
