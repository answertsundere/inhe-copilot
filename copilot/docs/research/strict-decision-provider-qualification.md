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

The host has a running vLLM 0.11 vision worker at localhost port 8001 using
`Qwen/Qwen3-VL-8B-Instruct`. Its model cache is on `D:` and it remains outside
the Decision Provider boundary. A separate vLLM 0.12 image and the same local
model were tested at localhost port 8002 with a short context length and eager
execution. The process loaded approximately 16.64 GiB of weights, then failed
before serving because no KV-cache capacity remained while the vision worker
was resident. No model was downloaded, the vision worker was not stopped, and
the Decision endpoint remains unconfigured and unqualified.

This is a GPU-capacity failure, not proof that vLLM 0.12 or its strict schema
transport is incompatible. Do not enable Shadow or substitute JSON-object mode
until a separate capacity plan or a smaller qualified local text model exists.
