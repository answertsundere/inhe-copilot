# Strict Decision Provider Qualification

## Purpose

Strict model roles, including the Evidence-First Decision Loop and Unified
Textual Audit, must be qualified independently from the formal customer-reply
model before any live request runs. A provider that merely returns parseable
JSON is not qualified.

## Research Findings

- OpenAI Structured Outputs supports a JSON Schema response format with
  `strict: true`; JSON mode is a weaker format guarantee and is not sufficient
  for the decision contract. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- DeepSeek documents JSON Output as `json_object`, which may return empty
  content; this is not a strict-schema fallback. Its Function Calling guide
  documents strict function schemas, so it can be considered only when the
  configured endpoint passes the same live qualification through the
  `tool_call_schema` transport. [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/), [DeepSeek Function Calling](https://api-docs.deepseek.com/guides/function_calling/)
- vLLM 0.12 documents OpenAI-compatible `json_schema` support and its
  structured-output configuration. A local server remains unqualified until
  the exact model, server settings, and schema suite pass. [vLLM Structured Outputs](https://docs.vllm.ai/en/v0.12.0/features/structured_outputs/)
- Tool use is an application loop: the model proposes a tool call, the
  application executes it, and returns a tool result. It does not grant the
  model authority to execute customer-facing actions. [Claude Tool Use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)

## Capability Classes

| Capability | Decision-shadow status |
|---|---|
| `strict_json_schema` | Eligible for qualification |
| `tool_call_schema` | Eligible for qualification only when the provider enforces the function schema |
| `json_object_only` | Rejected: valid JSON is not a strict contract |
| `plain_json_prompt` | Rejected: prompt-following is not a strict contract |
| `unsupported` | Rejected |

## Configuration Boundary

`COPILOT_DECISION_LLM_*` is independent from `COPILOT_LLM_*`. The latter remains
the formal reply-model configuration and must never be copied into decision
shadow implicitly. The provider report contains only provider name, model name,
capability, configured status, and a one-way host fingerprint. It never records
an API key or complete API base.

## Qualification Contract

`scripts/qualify_strict_decision_provider.py` is read-only. It makes the intake
and proposal calls repeatedly, validates both with the production Pydantic
schemas, and verifies local rejection of extra fields, missing required fields,
invalid enums, and the two literal `false` fields. No JSON-object, regular
expression, Markdown, or free-text parsing fallback exists.

The provider is not eligible for live shadow until all live schema calls and
repeatability checks pass and a local operator explicitly sets
`COPILOT_DECISION_LLM_QUALIFIED=true` for that exact configuration. Qualification
never sets this switch and never changes formal reply, evidence, delivery, or
`can_send` behavior.

## Unified Audit Provider Check: 2026-08-04

The independent Unified Audit role was checked against the frozen
`unified-textual-audit-v2` Candidate 1/2 matrix without customer or Gold data.
MiniMax-M3 accepted one strict tool preflight. Its generic strict transport then
used the full 800-token completion budget and failed local top-level validation.
Reusing the project's MiniMax compatibility controls (positive minimum
temperature, separated reasoning, optional M3 thinking disablement, and a 1600
token ceiling) produced one fully valid diagnostic response, but the first new
frozen Candidate 1 attempt returned a normal completion instead of the forced
tool call. The run stopped immediately. MiniMax-M3 therefore remains
unqualified for Unified Audit even though its provider-specific request shape
is now represented in the shared strict transport.

DeepSeek officially documents beta strict tool schemas at the `/beta` endpoint
and excludes `minItems` and `maxItems` for arrays. A preflight projected only
unsupported provider-schema keywords while leaving the local Validator
unchanged, but the existing project credential failed authentication before a
model result. No DeepSeek model was qualified and no production role was
switched. [DeepSeek strict tool calls](https://api-docs.deepseek.com/guides/tool_calls)

DeepSeek V4 enables thinking by default. The bounded Composer JSON request
explicitly disables thinking at the existing provider-compatibility boundary so
the configured completion budget is reserved for the validated reply contract.
This is a transport setting, not a reduction of the model's evidence, context,
or reasoning authority elsewhere in the Pipeline. [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)
The independent DeepSeek strict-tool Audit request uses that same official
non-thinking parameter; it never receives a local-model-specific transport
option. DeepSeek V4 Pro with thinking enabled rejected the first strict-tool
qualification schema before model output, so that mode is not a supported Audit
candidate under the current schema contract.

DeepSeek V4 Flash passed the isolated Composer five-run contract with the
non-thinking JSON transport: all five responses preserved the direct fact,
selected the required bounded option, and retained the restricted boundary in
one request without retry, repair, or fallback. It remains disabled until a
secure deployment configuration supplies the matching non-secret
qualification fingerprint. The same model must not serve as the independent
Unified Audit role: it accepted all five safe audit fixtures but also accepted
the first unsupported test-status counterexample. Its strict-tool transport is
working, but its Audit semantic qualification is not.

DeepSeek V4 Pro later passed the same isolated Composer five-run contract. A
query-only reconstructed Fixed-8 comparison kept the formal Agent on V4 Flash
and changed only the explicit Composer override. V4 Pro removed an unsupported
history-derived product fact, improved Unified Audit advisory from `5/8` to
`7/8`, supported attribution from `3/4` to `4/4`, and Partial Answer from `1/2`
to `2/2`. Pipeline p50/p95 increased from about `11.1s/14.0s` to
`13.6s/18.7s`. The sole remaining Audit failure was invalid judge schema, not a
candidate-content rejection. This establishes a stronger review-only Composer
candidate, not production enablement or real-customer accuracy; selected
evidence still covered only `3/8` scenarios and `can_send` remained false.

Initial loopback candidates then used Ollama's native `/api/chat` JSON Schema
format through the same role boundary. Gemma4 12B, Qwen3-VL 8B/32B, Qwen3 30B,
and Qwen3.6 35B either failed structure or the old semantic matrix. Enabling
Qwen3.6 thinking exhausted a 3200-token output budget, so longer hidden
reasoning was not treated as automatic quality.

Review of the old negative fixture found a policy error rather than a model
capability requirement: the candidate mentioned ordinary impact variables and
one conservative care suggestion, both consistent with the product owner's
approved humanlike answer, while the Pack simultaneously required an
avoid-high-or-repeated-impact qualifier and declared `advice_mode=none`.
`maternal_child_home@1.4.0` resolves that contradiction by allowing impact
height, angle, surface, severity, frequency, handling pattern, and one concise
care suggestion. Absolute guarantees, tests, child-safety claims, warranties,
and unsupported extensions remain prohibited.

Under the corrected budget, loopback `Qwen3.6:35b` with native JSON Schema,
thinking disabled, temperature zero, and the existing local Validator accepted
the bounded candidate `5/5` and rejected a true absolute-guarantee/unsafe-use
candidate `5/5`. Every attempt used one call with no retry, repair, or fallback;
the decision vectors and clause attribution were stable, with provider p50/p95
about `2.775s/3.749s`. This exact local role is qualified for isolated P1
Fixed-8 evaluation. It is not a production enablement, and it does not justify
JSON-object fallback, output repair, a second Audit call, or any change to
`can_send`.

`maternal_child_home@1.5.0` adds two further reviewed semantic budgets for
ordinary cleaning care and incidental moisture exposure. The same loopback
role first passed a safe/unsafe cleaning and moisture matrix `20/20`, then the
existing Composer, Deterministic Final, and Unified Audit chain passed each
live-shaped care input `5/5`. Every role invocation remained single-shot with
no retry, repair, or fallback. This demonstrates component-level budget and
language stability only; the native Fixed-8 still decides whether the combined
Pipeline qualifies.

## Unified Audit v4 Qualifier And Prohibited-Extension Check: 2026-08-08

The P1.4 native Fixed-8 found a narrower counterexample than the corrected
durability matrix: missing direct test evidence was verbalized as an affirmative
claim that the product had not been tested. Unified Audit v4 keeps the same
role and finding ontology but separates `qualifier_status` from
`prohibited_extension_status` for every applicable clause. This makes the
policy's prohibited semantic families independently auditable without a phrase
matcher, extra model call, or reply rewrite.

No available model passed the frozen safe/unsafe gate. With thinking disabled,
loopback Qwen3.6 35B and Qwen3 30B each accepted the safe candidate `5/5` and
then wrongly accepted the first unsafe test-status candidate. Their thinking
modes and Qwen3-VL 32B did not provide a qualifying strict structured channel.
MiniMax-M3 strict tool mode accepted the safe side `5/5`, then returned a
Provider error on the first unsafe request; its observed p50/p95 were about
`17.766s/19.094s`. DeepSeek V4 Pro reached the beta strict-tool endpoint under
the v4 contract, accepted the safe side `5/5`, then accepted the first unsafe
test-status counterexample with `prohibited_extension_status=absent`; observed
p50/p95 were `2787.41/3842.95ms`. These are separate transport or semantic
failures; none authorizes schema weakening, JSON repair, model fallback, or
production role selection.

Provider portability remains role-specific. An approved or tenant-supplied
credential may be connected without changing Agent business owners, but the
exact Provider/model/privacy configuration must pass strict preflight, the
frozen semantic matrix, and the current Composer gate independently before a
new native Fixed-8. Vendor identity never substitutes for qualification.

## Turn Understanding Provider Check: 2026-08-16

The separate Turn Understanding role reuses the production Prompt, strict tool
schema, exact-current-source validator, and canonical normalizer on eight
fictional cases. GLM-4.6 and GLM-5-Turbo were transport-blocked by account rate
limits. DeepSeek V4 Flash was callable but passed only `7/8` semantic contracts:
its material response populated a dimension-only subject scope and was rejected
by the existing canonical contract.

DeepSeek V4 Pro passed an initial `8/8` gate and completed a repeated `24/24`
run with `100%` execution, schema, current-source, and semantic success. Repeat
stability was only `22/24`. A privacy-safe v2 diagnostic records anonymous case
aliases, signature-variant counts, stable-attempt counts, and changed field
names without model output or field values. One material case varied its exact
current-message source span; one carrier-action case varied `semantic_key`.
The role already used temperature zero and disabled thinking. The result is a
real provenance/semantic stability failure, not a reason to weaken validation,
retry for a lucky pass, or invalidate the separately qualified Composer role.
The follow-up authority audit showed that the exact values were not equally
authoritative: one unique source substring could be normalized to the same
current-message clause, and a non-renderable action's free semantic label never
reached action, evidence, reply, or delivery decisions. The strict-role-only
normalizer now canonicalizes only exact unique current-message clauses and
retains exact spans when several atomic goals share one clause. Qualification
v3 also treats unbound unmapped semantic-key wording as diagnostic while still
requiring stable presence and exact trusted policy/context keys. One fixed
post-change `8x3` passed all `24/24` execution, schema, current-source,
semantic, combined-repeat, semantic-repeat, and source-repeat checks, with zero
timeout, truncation, schema failure, knowledge write, or send change. No strict
Turn Understanding runtime has been promoted; isolated gates remain required.

`scripts/qualify_unified_audit_role.py` is the reusable, read-only command for
that Audit-side `5+5` gate. It reads only `COPILOT_UNIFIED_AUDIT_*`, invokes the
existing strict role transport with `allow_unqualified=true` only inside the
qualification process, and writes a report with safe provider metadata, hashes,
validation categories, and latency. It never sets
`COPILOT_UNIFIED_AUDIT_QUALIFIED`, changes a feature flag, reads formal
knowledge, generates a customer reply, or changes `can_send`. The same command
works for an approved hosted provider or a compatible tenant/BYOK provider;
each exact role identity still needs its own report.

A passing Unified Audit report emits a non-secret qualification fingerprint.
`COPILOT_UNIFIED_AUDIT_QUALIFIED=true` is insufficient by itself: production
also requires the report fingerprint to match the configured provider, base,
model, strict capability, timeout, and thinking setting. A mismatch blocks
before the first Audit request. This binding applies only to the independent
Unified Audit role; it does not retroactively alter decision-shadow roles.

The Composer role has the same deployment-level isolation through
COPILOT_COMPOSER_LLM. It preserves the current formal LLM when the override is
absent, but an explicit override must contain API base, key, model, timeout,
and a completed Composer qualification marker. An incomplete or unqualified
override blocks before its first Provider request and never falls back to the
formal model. This keeps a future DeepSeek or tenant/BYOK experiment scoped to
reply composition while the existing exact input, local Validator, and
evidence/delivery contracts remain unchanged.

`scripts/qualify_model_first_composer_role.py` is the corresponding read-only
Composer gate. It reads only the explicit `COPILOT_COMPOSER_LLM_*` override and
uses `allow_unqualified=true` solely while running five identical synthetic
fact-plus-bounded-inference requests. Each request must make exactly one
Composer Provider call and preserve presentation order, direct-fact rendering,
the required option, and the restricted boundary. Any first failure stops the
run. The command records only hashes and structural projections, never raw
customer text or credentials, and never sets `COPILOT_COMPOSER_LLM_QUALIFIED`.
Its passing report emits a non-secret `qualification_fingerprint`; production
requires that fingerprint alongside `COPILOT_COMPOSER_LLM_QUALIFIED=true`.
Changing the base URL, model, or effective timeout causes Composer to block
before the first Provider request until the exact new role is qualified.

## Local Runtime Check: 2026-07-14

The host keeps its vLLM 0.11 vision worker at localhost port 8001 on
`Qwen/Qwen3-VL-8B-Instruct`. It remains outside the Decision Provider boundary
and was not stopped or reconfigured. A separate vLLM 0.12 candidate at
localhost port 8002 ran `Qwen/Qwen3-4B` from the model cache on `D:` with a
short context window and conservative GPU allocation.

The candidate passed the strict transport and Pydantic schema checks, including
the literal `false` contract fields. It failed the semantic qualification: in
five repeated compound-claim intakes it did not produce the required distinct
material-composition, material-safety, and moisture-resistance claims. Turning
off the Qwen thinking mode improved latency but did not fix that decomposition.
The candidate is therefore **not qualified**. `COPILOT_DECISION_LLM_QUALIFIED`
and the live Decision Shadow flag must remain disabled. This records a semantic
provider failure, not a justification to use JSON-object mode, prompt parsing,
or an unqualified model for live shadow.

## Phase 0.5C provider boundary and convergence diagnostics

The configured formal Model Studio reply provider is not implicitly reused for
Decision Shadow. Model Studio's current OpenAI-compatible documentation shows
`json_object` structured output, not an independently verified strict-schema
contract. JSON-object validity cannot prove required fields, literal safety
flags, or claim-resolution fidelity, so it remains outside the Decision
Provider boundary until an explicit strict-capability qualification succeeds.
See the official [structured-output guide](https://help.aliyun.com/en/model-studio/qwen-structured-output)
and [OpenAI-compatible API reference](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions).

`scripts/trace_evidence_convergence.py` is a provider-free, read-only
diagnostic. It shows whether each candidate existed in Product Context Pack,
was formally selected, was admitted for shadow use, and would be included in
the decision-model context. A persisted API snapshot may compact candidate
fields for response size; the script reports that condition and can rebuild the
current scoped context explicitly for diagnosis. Rebuilding is labelled as a
current-context read, not as proof of the historic response.
