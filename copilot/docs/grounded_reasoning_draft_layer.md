# Grounded Reasoning Draft Layer

## Positioning

Grounded Reasoning Draft Layer is a shadow-only experiment between evidence retrieval and future reply generation. It prepares a fact-bound draft that is easier to inspect than raw retrieval output, but it does not enter the official reply path yet.

Current status:

- Controlled by `COPILOT_GROUNDED_REASONING_SHADOW_ENABLED`.
- Default is disabled.
- When enabled, `/ask/api/analyze` appends `grounded_reasoning_draft` to the response, `evidence_debug`, and `answer_trace`.
- It does not change `suggested_reply`, `draft_reply`, `sendable_reply`, `can_send`, `requires_human_review`, `selected_evidence`, or `reply_blocks`.

## Contract

The layer output keeps an explicit machine contract:

```json
{
  "enabled": true,
  "shadow_only": true,
  "used_for_final_reply": false,
  "can_change_can_send": false,
  "grounded_draft": "",
  "used_facts": [],
  "inferred_points": [],
  "safety_boundaries": [],
  "forbidden_claims": [],
  "missing_confirmations": [],
  "requires_human_review": true,
  "risk_level": "high",
  "reasoning_mode": "fact_bound_safe_inference"
}
```

## Evidence Boundary

`used_facts` can only come from:

- `selected_evidence`
- `product_context_pack`
- `product_first_evidence_pack`

Answer Memory can only provide style and action hints. It must never become a product fact. A remembered reply can suggest how to handle an installation, aftersales, or promotion conversation, but it cannot prove a material, weight, size, certificate, age range, discount, refund state, or media asset.

## Safe Inference

The layer may make safe action inferences inside factual boundaries:

- For child safety or age questions, ask to check structure, material, and official suitability notes; do not claim a specific age or absolute safety.
- For material and odor questions, cite verified material facts when present; do not claim non-toxic, certified, or test-report availability unless explicit evidence exists.
- For installation questions, guide around steps, screw holes, accessory positions, and stuck points; do not promise replacement or media unless matching reply blocks exist.
- For visual structure questions, ask for the relevant screenshot or page area when current facts are insufficient.

## Media Boundary

The draft cannot promise pictures or videos unless the current response already contains matching `reply_blocks`:

- `video` block for video wording.
- `image` block for image wording.

Product pack media availability alone is not enough. The current reply must actually attach the block before any media-send wording is allowed.

## Diagnostics

Trace script:

```powershell
python scripts\trace_grounded_reasoning_for_training_samples.py --input outputs\training_samples_reviewed_snapshot_20260709.json --json-output outputs\grounded_reasoning_shadow_trace_20260709.json
```

Expected invariant counts:

```text
can_change_can_send_count = 0
used_answer_memory_as_fact_count = 0
forbidden_claim_violation_count = 0
unsupported_media_claim_count = 0
```

`generic_handoff_only_count` is tracked to avoid producing drafts that are only generic "check and confirm" wording.

## Non-Goals

- No official reply generation.
- No auto-send enablement.
- No final gate bypass.
- No product facts inferred from Answer Memory.
- No knowledge-base, media-library, or product-library writes.
- No matching by hardcoded sample id, SKU, order id, run id, or exact buyer text.
