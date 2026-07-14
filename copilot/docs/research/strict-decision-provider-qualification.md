# Strict Decision Provider Qualification

## Purpose

The Evidence-First Decision Loop is a shadow diagnostic. Its provider must be
qualified independently from the formal customer-reply model before any live
shadow request runs. A provider that merely returns parseable JSON is not
qualified.

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
