# Answer Memory Layer

## Positioning

Answer Memory Layer stores reviewed answer patterns for evaluation and grounded reasoning reference. It sits after product fact retrieval and before grounded reasoning:

```text
product identity resolution
-> fact_type / scenario_type
-> verified product facts and media evidence
-> Answer Memory retrieval
-> grounded reasoning
-> final gate / sendable contract
```

It must not replace verified product facts. A historical reply can show how a strong customer-service response should be structured, but it is not evidence that a product has a material, size, load capacity, certificate, installation video, discount, refund state, or any other factual property.

## Data Sources

MVP sources are limited to reviewed or curated artifacts:

- reviewed training sample `correct_answer`
- gold customer-service historical replies after review
- active benchmark `expected_reply`
- repaired failure sample standard answers after review

Raw customer-service replies, unreviewed chat history, and low-quality greetings are not eligible as direct answer memory.

## Usability Levels

- `verified_answer`: strong reference answer reviewed by a supervisor or benchmark curator. It still requires fact binding before auto-send.
- `reference_reply`: wording, tone, and handling-step reference only.
- `scenario_pattern`: scenario strategy such as aftersales collection, promotion check, or installation handoff.
- `forbidden_pattern`: counterexample or forbidden claim pattern for final gate.

## Risk Levels

- `low`: service process or low-risk action guidance.
- `medium`: ordinary product or aftersales handling that still requires context.
- `high`: child suitability, safety, material, certification, load capacity, stability, or similar high-risk factual claims.

High-risk answer memories always require human review unless independent verified facts and final gate allow otherwise.

## Auto-Send Rule

Default:

```text
can_auto_send = false
requires_human_review = true
```

An Answer Memory hit alone must never make a response auto-sendable. Auto-send requires all of the following:

- verified product/order/policy facts for the requested fact type
- the answer memory is reviewed and compatible with the current scenario
- media evidence, if any, is approved, usable, and role-matched
- final gate passes

## MVP Data Model

`AgentAnswerMemory` stores:

- product identity hints: `product_i_id`, `sku_code`, `product_title`, `product_family`
- scenario and fact routing: `scenario_type`, `query_fact_type`
- reference content: `approved_answer`, `reference_reply`, `customer_question_pattern`
- gating metadata: `required_fact_types`, `required_evidence_roles`, `forbidden_claims`, `risk_level`
- review metadata: `review_status`, `answer_quality`, `reviewer`
- safety defaults: `can_auto_send=false`, `requires_human_review=true`
- provenance: `source_type`, `source_id`, `source_conversation_id`, `source_order_id_hash`

Plain order numbers are not stored. Only `source_order_id_hash` is retained.

## MVP Scripts

Import reviewed training samples:

```powershell
python scripts\import_answer_memory_from_training_samples.py --input outputs\training_samples_reviewed_snapshot_20260709.json --json-output outputs\answer_memory_import_dry_run_20260709.json
python scripts\import_answer_memory_from_training_samples.py --input outputs\training_samples_reviewed_snapshot_20260709.json --apply --json-output outputs\answer_memory_import_apply_20260709.json
```

Shadow trace reviewed samples:

```powershell
python scripts\trace_answer_memory_for_training_samples.py --input outputs\training_samples_reviewed_snapshot_20260709.json --json-output outputs\answer_memory_shadow_trace_20260709.json
```

The trace script is diagnostic only and does not change `can_send`.

## Shadow-to-Draft Adapter

`app/services/answer_memory_adapter_service.py` converts Answer Memory search hits into generation guidance:

```json
{
  "enabled": true,
  "reference_only": true,
  "used_for_fact": false,
  "can_change_can_send": false,
  "matched_memories": [],
  "style_hints": [],
  "action_hints": [],
  "forbidden_claims": [],
  "required_fact_types": [],
  "risk_level": "",
  "draft_guidance": ""
}
```

The adapter is controlled by `COPILOT_ANSWER_MEMORY_SHADOW_ENABLED`.
Default is disabled. When enabled, `/ask/api/analyze` appends:

- `response.answer_memory_guidance`
- `response.evidence_debug.answer_memory_guidance`
- `response.answer_trace.answer_memory_guidance`

The adapter does not:

- enter `selected_evidence`
- change `suggested_reply`
- change `sendable_reply`
- change `can_send`
- change `requires_human_review`
- replace verified product facts

`verified_answer` memories are stronger style/action references, but they still are not product facts. `reference_reply` memories provide only tone and handling steps. High-risk memories remain human-review guidance.

Adapter trace script:

```powershell
python scripts\trace_answer_memory_adapter_for_training_samples.py --input outputs\training_samples_reviewed_snapshot_20260709.json --json-output outputs\answer_memory_adapter_trace_20260709.json
```

The expected invariant is:

```text
can_change_can_send_count = 0
used_for_fact_count = 0
non_reference_count = 0
```

Future grounded reasoning work can decide how to consume `style_hints`, `action_hints`, `required_fact_types`, and `forbidden_claims`, but final gate and verified evidence remain authoritative.

## Non-Goals

- No formal knowledge-base writes.
- No product facts inferred from historical replies.
- No direct integration into `generate_reply` in MVP.
- No auto-send enablement from answer memory alone.
- No matching by hardcoded sample id, SKU, order id, run id, or exact buyer text.
