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

## Promotion gates

Promotion requires real traces with valid strict structured output, stable
claim decomposition, eligible evidence references only, no unsupported claims,
no formal-field mutation, and parity across every formal entry point. Phase
0.5A is not promoted merely because synthetic tests or active benchmark pass.
