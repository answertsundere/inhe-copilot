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

## Positive Capability Evaluation

Phase 0.4A adds a read-only positive evaluation baseline. It keeps synthetic
contract fixtures separate from the current production knowledge inventory,
because historical training traces often carry sidecar identity but not formal
direct/scoped facts. The fixtures are never written to the knowledge base and
their expected facts, draft terms, rejection expectations, and claim rules are
only used after the shadow draft is built.

The evaluation tiers are:

- `L0`: direct reviewed facts;
- `L1`: low-risk combinations of compatible facts from one product;
- `L2`: bounded explanation with an explicit condition or limit;
- `L3`: high-risk controls that must stay review-only without explicit evidence.

The runner reports fact admission, invalid-fact rejection, draft-fact coverage,
answer relevance, declared unsupported claims, identity and Answer Memory
leakage, conflict blocking, high-risk handoff, forbidden claims, and the
unchanged `can_change_can_send` invariant. Every rate contains an explicit
numerator and denominator. It is an offline diagnostic and cannot alter the
formal reply, evidence selection, media blocks, or sendability.

The first integrity baseline contains 37 synthetic scenarios (`L0=12`, `L1=8`,
`L2=5`, `L3=12`). It intentionally reports the L1 multi-fact gap instead of
masking it: admission can be correct while the draft presents only one required
fact. It is reported separately from the read-only knowledge inventory: a
reviewed product or FAQ row is not automatically an eligible direct fact until
it has the role, gate, structured attribute, and identity metadata required by
this layer. Real training trace counts remain their own input-quality signal and
must not be replaced by synthetic results.

Current real-input baseline (2026-07-11) scanned 147 reviewed training samples:
45 produced a shadow draft, 102 were skipped for link/image-only input, zero
formal direct facts were admitted, and 17 reference-only candidates were
rejected. Answer leakage and `can_change_can_send` were both zero. This is an
input-evidence coverage result, not a positive-capability score.

## Multi-Fact Composition Plan

The shadow layer owns a deterministic `fact_coverage_plan`; it is not a second
formal reply engine. The plan only consumes `used_facts` that already passed
admission and emits at most three same-scope, fact-type-compatible clauses.
Each clause carries its `evidence_uid`, attribute key, fact type, source, text,
and identity scope. Conflicting, rejected, service-action, media-reference, and
Answer Memory entries cannot enter the plan because they cannot enter
`used_facts`.

The plan records candidate, selected, omitted, and rendered evidence UIDs plus
coverage warnings. The renderer joins only missing clause text and adds no
causal, safety, suitability, performance, delivery, or order conclusion. This
keeps L1 as a parallel statement of verified facts; L2 inference is unchanged.

The positive evaluator separately reports plan coverage, rendered coverage,
unattributed clauses, irrelevant inclusions, and order instability. All remain
shadow diagnostics and cannot alter the final reply or `can_send`.

### Requested Attribute And Draft Integrity Contract

The planner accepts only upstream structured request metadata:
`requested_attribute_keys`, `requested_fact_types`, `request_scope`, and
`requested_attribute_source`. It does not derive requested attributes from the
buyer text. When the upstream contract is `explicit`, only admitted clauses
whose structured attribute keys match the requested keys may be selected. A
broad or unavailable request may include all compatible candidates only when
their count is within the plan limit; otherwise the plan records
`selection_ambiguous` instead of choosing alphabetically. Missing explicit
attributes are reported as `requested_fact_missing`.

Request-contract candidates are collected from the response and its allowed
turn-understanding containers, then selected by reliability: explicit with
non-empty attributes, explicit without attributes, broad, then unavailable.
Within one reliability level, the documented container precedence is stable.
Conflicting same-level contracts are never widened or merged; the selected
container and `request_contract_conflict` diagnostic remain in the shadow plan.
`width`, `height`, `gross_weight`, and `load_capacity` stay separate canonical
attribute keys.

Real inputs do not yet consistently populate `requested_attribute_keys`. The
trace therefore reports coverage and source counts as an upstream-contract gap;
it must not compensate by guessing attributes from customer wording.

The shadow draft is rendered deterministically from `draft_segments`:

- `customer_copy` may contain only handling actions, conditions, or safety
  boundaries;
- each `factual_clause` must carry one selected `evidence_uid` and its
  structured attribute key;
- `safety_boundary` may state a limit but cannot introduce a product fact.

The evaluator re-renders these segments and compares the result with
`grounded_draft`. It separately counts a factual clause without evidence, a
clause outside the plan, and a planned fact missing from the rendered segments.
This is an integrity check for the structured shadow draft, not a claim that it
detects every possible natural-language hallucination.

For explicit requests, selection coverage has a declared denominator: unique
requested attributes with at least one admitted fact. The numerator is those
available attributes selected by the plan. Requested-but-unavailable attributes
are counted separately as no-evidence/missing diagnostics; an empty plan never
passes by vacuous truth. Real traces expose numerator, denominator, scope
counts, and contract-conflict counts without treating zero coverage as success.

Available-evidence coverage and explicit-request completeness are intentionally
different metrics. Coverage can be `1.0` when every available requested fact was
selected, even if another requested attribute has no evidence. Completeness is
only true when there is available evidence, all available attributes are
selected, no requested attribute lacks evidence, and no unrequested attribute
was selected. The evaluator records `requested_attribute_not_selected`,
`requested_attribute_no_evidence`, and `unexpected_attribute_selected` as
offline failure reasons. Positive fixtures remain separate from evaluator-only
negative mutations that prove these cases fail.

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
