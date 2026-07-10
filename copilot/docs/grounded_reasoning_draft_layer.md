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
  "rejected_evidence": [],
  "admission_warnings": [],
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

- direct product facts or direct FAQ evidence that pass evidence admission
- reviewed, identity-scoped, fact-type-compatible product context entries

Evidence admission rejects `blocked`, `reference_only`, `fallback_only`,
`service_action`, `media_reference`, pending/provisional content, Answer
Memory, expected answers, rubrics, incompatible fact types, mismatched product
identity, and conflicting numeric facts. Rejected candidates remain diagnostic
metadata only and never enter `used_facts`.

Direct-looking source labels are not enough: product facts require explicit
direct eligibility, an allowed gate, reviewed/verified/published status, and a
matching identity namespace (`sku_code`, `i_id`, or `product_id`). Global FAQ
must declare `fact_scope=global` or `product_scope=all`. Numeric candidates are
deduplicated and compared by structured attribute key and normalized value.
Product facts require at least one identity key in the same namespace; unrelated
identity namespaces are not guessed or cross-mapped inside this layer. Only an
explicit global FAQ may omit product identity.

Conflict handling is order-independent and runs after evidence admission:

1. Candidates are admitted with their source, role, fact type, identity, raw
   value, structured attribute key, unit domain, and normalized value.
2. Candidates are grouped by the structured attribute key. Equivalent values in
   one unit domain are deduplicated, while every candidate in a conflicting group
   is excluded and retained in `rejected_evidence` with provenance.

`kg`, `公斤`, `千克`, `g`, and `克` normalize to a metric-mass domain. Metric
length units normalize separately. `斤` remains a separate domain until the
project declares a trusted conversion contract. Values in incomparable domains
are excluded as `incomparable_unit_domain`, not mislabeled as numeric conflicts.
Width, height, length, gross weight, and load capacity remain distinct attribute
slots. Missing slots or values that cannot be normalized do not participate in
deduplication or conflict comparison; they are recorded in `admission_warnings`
as `conflict_check_skipped` rather than being mislabeled as rejected evidence.

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
answer_leakage_count = 0
```

`generic_handoff_only_count` is tracked to avoid producing drafts that are only generic "check and confirm" wording.

Forbidden-claim diagnostics use the same claim-polarity helper as the formal
unsafe-promise scanner. Affirmative unsupported claims are flagged, while safe
negation and uncertainty such as "不能确认是否无毒" or "这不代表无毒" are not.
This diagnostic remains shadow-only and cannot change the final reply or
sendability.

Reviewed training-sample `correct_answer` is an offline comparison reference.
It must never be injected into selected evidence, product facts, prompts, or
Grounded Reasoning `used_facts`. Image-only, link-only, unreadable, and missing
context samples are counted as skipped instead of being treated as text QA.

## Non-Goals

- No official reply generation.
- No auto-send enablement.
- No final gate bypass.
- No product facts inferred from Answer Memory.
- No knowledge-base, media-library, or product-library writes.
- No matching by hardcoded sample id, SKU, order id, run id, or exact buyer text.
