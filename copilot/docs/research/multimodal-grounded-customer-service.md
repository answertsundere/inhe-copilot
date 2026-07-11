# Multimodal Grounded Customer Service

## Status

Architecture research and gap assessment as of 2026-07-11. This document
defines direction and acceptance boundaries. It does not mean that product-media
understanding or grounded composition is active in the formal answer path.

## Business Problem

Customers rarely ask questions using the same wording as a knowledge-base
field. A useful Agent must combine the current product identity, reviewed facts,
described media, conversation context, and low-risk reasoning. It must not
require a dedicated FAQ for every possible sentence.

For example, when a customer asks how much a three-tier cabinet can hold and the
only relevant source is a dimension image, the system should be able to:

1. resolve the exact product and variant;
2. inspect the product-scoped image and extract observable facts such as tier
   count and labelled dimensions;
3. preserve the image, region, OCR text, confidence, and product identity as
   provenance;
4. make only an explicitly allowed estimate, with its assumptions visible; and
5. refuse to infer a weight limit, child safety, toxicity, certification, or
   structural guarantee from dimensions alone.

The target is not unrestricted common-sense answering. It is flexible language
understanding and bounded reasoning over attributable evidence.

## Mature Product Patterns

The maintained products reviewed for this direction converge on the same broad
pattern:

- Intercom Fin combines multiple knowledge sources, conversation context,
  reranking, clarification, uncertainty, and answer inspection. Its documented
  image support can extract text and product details from customer screenshots.
- Rasa CALM uses an LLM for flexible language understanding while keeping
  business logic, required data, tools, and branching in structured flows.
- Salesforce Agentforce separates deterministic actions from domain reasoning
  and places grounding, audit, feedback, and human review in a trust layer.
- Zendesk recommends making image content text-searchable and treats generated
  procedures as drafts that require review before publication.

Primary sources:

- https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained
- https://www.intercom.com/help/en/articles/7837535-fin-ai-agent-faqs
- https://rasa.com/docs/learn/concepts/calm/
- https://rasa.com/docs/reference/primitives/flows/
- https://developer.salesforce.com/docs/ai/agentforce/guide/trust.html
- https://developer.salesforce.com/docs/ai/agentforce/guide/get-started-actions.html
- https://support.zendesk.com/hc/en-us/articles/4408845739162-Optimizing-your-knowledge-content-for-generative-AI
- https://support.zendesk.com/hc/en-us/articles/10140109521178-Reviewing-and-publishing-AI-generated-procedures-for-auto-assist

The reusable lesson is not a specific vendor workflow. It is the separation of
model interpretation, evidence retrieval, deterministic actions, bounded
reasoning, claim-level safety, and observable handoff.

## Verified Current Gaps

The project direction is aligned with that pattern, but the formal implementation
does not yet complete it:

- `exact_faq_answer` and `product_fact_answer` are rendered before the current
  LLM composition branch, so formal product answers mainly concatenate facts.
- text product questions with known product or order context can skip customer
  image VLM analysis, including dimensions, installation, and load questions;
- product media are role-labelled, but the current local media corpus has no
  queryable visual descriptions, OCR observations, regions, or layer/dimension
  facts;
- the customer-image reply path consumes coarse image categories rather than
  detailed structured observations;
- Grounded Reasoning has strong shadow evidence-admission tests but is not a
  formal answer composer and cannot change the delivered reply;
- fact-type, policy, audit, and fallback keyword sets remain distributed, which
  encourages rule accumulation instead of improving evidence composition.

There is no confirmed production branching on a fixed SKU, order, run ID, or
sample sentence in this review. The larger maintainability risk is soft
hardcoding: overlapping keyword lists and templates spread across multiple
formal modules.

## Target Capability Boundary

### Evidence acquisition

Product media understanding must be product-scoped and produce structured,
reviewable observations. Each observation needs:

- product and variant identity;
- source media ID, role, status, and region or timestamp;
- observed text or visual fact;
- confidence and extraction method;
- review state and risk class.

Model-derived observations must enter a staging/review state. They must not be
written directly into published product facts, especially for high-risk fields.

### Claim classes

Every planned answer claim must be classified before generation:

1. `direct_observation`: explicitly present in eligible structured facts, OCR,
   or a product-scoped image.
2. `bounded_derivation`: a low-risk calculation or comparison whose inputs,
   method, assumptions, and uncertainty are recorded.
3. `general_guidance`: non-product-specific advice that does not imply an
   unverified product property or platform action.
4. `high_risk_fact_or_action`: certification, toxicity, food grade, child
   suitability, load limit, anti-tip safety, order state, refund, replacement,
   compensation, or platform execution. This requires an approved direct source
   or an authoritative tool result.

### Example boundary

From a reviewed dimension image, the Agent may state that the image shows three
tiers and repeat labelled internal dimensions. Given a customer-supplied box
size, it may provide a clearly labelled geometric estimate of how many boxes fit.
It may not infer kilograms of load, structural safety, pinch safety, or child
suitability from tier count or dimensions.

### Final validation

The final gate should validate claims, not only the reply as one text blob. Each
factual clause must retain evidence IDs or a declared derivation. The gate must
reject unsupported identity, incompatible media roles, conflicting facts,
undeclared derivations, high-risk common-sense upgrades, and media promises that
do not match actual reply blocks.

## Convergence Recommendation

Do not promote the current Grounded Reasoning shadow directly and do not add
more reply templates for isolated questions. The recommended order is:

1. define a versioned Product Media Observation contract and review workflow;
2. run offline product-media OCR/VLM extraction into staging only;
3. expose eligible observations through the Product Evidence Pack;
4. add a shadow Claim Plan that separates direct observations, bounded
   derivations, general guidance, and prohibited claims;
5. evaluate image grounding, identity isolation, derivation correctness,
   conflict handling, naturalness, and high-risk blocking;
6. record an ADR before any shadow output is allowed into formal generation;
7. promote by risk tier and feature flag, with replay and human review.

The first implementation phase should prove one narrow vertical slice:
product-scoped dimension and structure images for low-risk spatial questions.
It must not include load capacity, child safety, material toxicity,
certification, installation prescriptions, or automatic send promotion.

## Shadow Observation MVP

Phase 0.4D adds an offline `ProductMediaObservation` extractor. It reuses the
existing OpenAI-compatible VLM configuration but is not connected to the
Analysis Pipeline, Product Evidence Pack, Grounded Reasoning inputs, or any
formal persistence path. The extractor reads only approved, agent-usable media
that has an internal `i_id` and stable media content hash, then writes a
sanitized JSON report under `outputs/`.

Each candidate remains `pending_review`, `direct_answer_allowed=false`,
`used_for_generation=false`, and `can_change_can_send=false`. Its provenance
contains the source media ID, media hash, product identity namespaces, role,
model/version, confidence, and optional region. No model result is written to
`KBProduct`, published knowledge, or a review state in this phase.

When a future caller supplies a target product identity, the extractor requires
at least one common namespace with an exact matching value. An explicit value
mismatch is rejected, and `i_id`/SKU/product-ID namespaces are never guessed
to be equivalent.

The only accepted observation types are `layer_count`, `compartment_count`,
`labelled_dimension`, `visible_structure`, and `visible_text`. A labelled
dimension must come from a `size_image` and preserve raw OCR plus a normalized
metric-length value. A role alone never proves content: a `sku_image` cannot
become a dimension fact merely because a scenario asks about size. High-risk
signals such as load capacity, child safety, toxicity, certification,
stability, or installation prescriptions are rejected as out of scope.

The command is deliberately bounded and read-only:

```powershell
python scripts\extract_product_media_observations.py --media-role size_image --limit 30 --json-output outputs\product_media_observations_shadow.json
```

Missing VLM configuration, unreadable media, malformed model output, incomplete
identity, low confidence, or missing provenance fail closed and are reported as
diagnostics. A future staging/review workflow requires its own ownership
decision and ADR before observations can enter any formal evidence path.
