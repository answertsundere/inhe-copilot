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

### Object-bound visual observations

Qwen3-VL documents OCR, object grounding, spatial understanding, and explicit
image pixel budgets. AliMe MKG describes a multimodal product cognitive profile
for product discovery and question answering. Amazon's attribute-extraction
research treats e-commerce attributes as a joint product-type, attribute, text,
and image problem rather than a collection of isolated fields. These sources
support an object-binding contract, but none removes the need for product scope,
human review, or high-risk claim controls.

The project therefore uses v3 shadow observations with a generic subject scope
(`product`, `packaging`, `component`, `accessory`, `included_item`, or
`display_prop`), optional state, parent relationship, measurement axis, and
object/label boxes. A packaging or component measurement is not a product
dimension; visible text remains reference-only. The extractor now uses staged
classification, object localisation, label localisation, and object-label
binding. It normalises accepted boxes into one `0..1` coordinate system while
recording only sanitised field-shape diagnostics for model failures. The
resulting Product Understanding Graph records direct `part_of`, `measured_as`,
`labelled_by`, `visible_in`, and `active_in_mode` edges only. It does not infer
load, safety, toxicity, certification, child suitability, wall fixing,
drilling, modification, or customer-specific geometry.

The composable follow-up keeps OCR deliberately narrower than visual
understanding. The local Windows OCR runtime may expose text and text regions,
but those are only label candidates. A dimension label still needs an
independently qualified product, packaging, component, or accessory box plus a
same-panel binding before it can be reviewed as an observation. This prevents
OCR text such as a carton measurement or a safety claim from being promoted to
a product fact merely because its characters were readable.

The matching object-proposal stage is equally narrow. OpenCV contour geometry
can propose a primary visible region inside a panel, but it cannot prove that
the region is the sellable product rather than a carton, component, accessory,
or display prop. The current adapter therefore accepts an explicit OCR
packaging cue only for a `packaging` candidate and reports all other contour
regions as unknown. It has no component classifier. That fail-closed result is
diagnostic evidence for a future qualified semantic object provider, not a
reason to treat a large visual region as a product or to weaken the
product/package/component separation.

Semantic grounding is a separate provider responsibility, not a semantic label
added to contour output. Its input categories must stay product-neutral, such
as product, packaging, component, and accessory classes. A semantic box then
passes the same panel and scope contract: packaging needs packaging evidence,
component needs a bounded product parent, and high-overlap product/packaging
predictions fail closed. No provider output is a reviewed observation or a
customer-facing fact. This keeps an unavailable or unstable model from turning
an unscoped large region into a product dimension.

Runtime availability is also a product-safety boundary. A present GPU or an
installed image library does not prove that a semantic detector, compatible
weights, or a provider adapter exists. The project therefore performs a
single-image generic-category probe before a ten-image qualification. Missing
runtime or weights returns a sanitised diagnostic and stops; it does not turn
into an empty detection result, an OpenCV fallback, or an observation.

A successful runtime probe is only a precondition, not qualification. The
provider still needs to meet the fixed repeated-image object-box and semantic
scope gates. A detector that is stable but covers too few assets remains
shadow-only and stops before geometry binding or review-candidate creation.
Likewise, a detector that consistently returns broad visual labels must keep
them as `unknown`; stable boxes alone do not prove product, packaging, or
component scope.

Primary sources:

- https://github.com/QwenLM/Qwen3-VL
- https://arxiv.org/abs/2109.07411
- https://assets.amazon.science/fd/40/a7e49bb0418392466e9f6c6f4744/large-scale-generative-multimodal-attribute-extraction-for-e-commerce-attributes.pdf

The first bounded v3 qualification on 2026-07-12 scanned ten approved source
images with the qualified offline vLLM 0.12.0 candidate. It admitted zero
observations: 32 candidates lacked required object boxes, 12 were
reference-only visible text, one was high-risk, and one source image could not
be read. This is a contract failure, not a reason to relax object binding. The
30-image scan was deliberately not run. V2's 105 pending candidates remain
legacy read-only data and do not count toward any v3 review or evaluation gate.

The follow-up staged v3 preflight on 2026-07-13 demonstrated why object
binding must remain strict: the model initially emitted no usable boxes, then
returned image-coordinate boxes after the four stages were separated. One
source image contained `43`, `16.5`, and `71` centimetre labels bound to a
packaging box. The extractor classified these as `packaging`, marked them as
non-product dimensions, and kept every result pending review. A full ten-image
gate is only valid after the same staged implementation completes; no v3 result
is a product fact or customer-sendable evidence in the meantime.

The staged ten-image gate on 2026-07-13 produced 28 pending-review,
double-box-bound measurements. All accepted measurements retained
`can_change_can_send=false`; packaging/product leakage, component/overall
leakage, and high-risk admission were each zero. However, the gate did **not**
qualify for a thirty-image scan: stage execution was 30/40 (75%) and schema
success was 28/40 (70%). Two multi-panel classifications omitted required panel
boxes and one approved source image could not be read. These are observed VLM
or source-media failures, not grounds to relax localisation, scope, or review
requirements. The system therefore remains shadow-only with no v3 review queue
or formal evidence promotion.

### Multi-panel and source-media qualification follow-up

The next bounded v3 retest repaired a generic source-resolution defect: ORM
assets whose raw source is exposed through `get_source_raw()` must resolve the
original file before a cache, upload URL, thumbnail, or remote URL. The reader
computes SHA-256 from the bytes it actually opens; a legacy database hash is
diagnostic comparison data only. This restored all ten source images without
changing the SQLite records.

Multi-panel images now have a three-level localisation contract: panel, object,
and label. A multi-panel classification requires a titled panel and a bounded
panel box. If classification identifies panels but a box is missing or invalid,
a dedicated repair call may return only the existing panel references and their
boxes. It cannot return measurements or substitute the whole image. Objects and
labels both retain `panel_ref`; an object-label binding across panels is
rejected. Single-panel images use one synthetic root panel solely to make the
same binding contract explicit.

On 2026-07-13, the same ten-image candidate scan reached source-read success
of 10/10, but not the expansion gate: one image produced two near-full-image
repair boxes with unreasonable overlap and was rejected as
`invalid_panel_bbox`. The result was 9/10 completed staged images, not a
qualified thirty-image run. No v3 pending-review candidates were created, no
formal table was written, and no reply or `can_send` field was changed. This is
the intended fail-closed outcome; future work must improve the provider's panel
localisation reliability rather than weaken panel/object/label grounding.

### Deterministic panel proposal qualification

Phase 0.4E.3 adds a conservative, deterministic panel-proposal step before
multi-panel VLM grounding. It uses grayscale whitespace projection already
available through Pillow, so it adds no layout model or resident service.
Reliable proposals contain only normalised geometry, layout axis, confidence,
and diagnostics; they do not describe products, parts, modes, measurements, or
claims. The proposal step supports strong vertical, horizontal, and regular-grid
separators. A continuous specification sheet remains a single panel even when
it contains multiple product images, measurements, and text blocks.

Qwen documents relative-coordinate visual grounding, while OpenCV documents
standard image-processing primitives such as segmentation and contours. The
project deliberately uses neither model coordinates nor a contour heuristic as
formal truth: VLM boxes may accept, make small proposal-aligned adjustments, or
merge proposal regions. A large proposal drift, cross-panel object/label
binding, near-duplicate full-image boxes, or an out-of-panel child box fails
closed. Adjacent non-overlapping panels may cover the full canvas; duplicate
near-full-image panels remain blocked by IoU and center-separation checks.

The 2026-07-13 qualification set did not contain reliable whitespace layouts,
so no proposal was used to override a VLM result. The final ten-image replay
read all images and preserved zero scope leakage, high-risk admissions, formal
writes, and sendability changes, but the local VLM varied in object/label box
validity and reached only 30/43 stage execution and 23/43 schema validity.
The gate therefore remains blocked: no thirty-image scan, review candidates,
formal evidence integration, or delivery change is permitted. This is useful
negative evidence that the current local model needs a separately qualified
layout/grounding strategy before promotion.

Primary sources used for this design:

- https://docs.opencv.org/master/d7/da8/tutorial_table_of_content_imgproc.html
- https://github.com/QwenLM/Qwen3-VL
- https://qwen.ai/blog?from=research.research-list&id=b550154aa5ba6b812cdebba2b9dc1156c4369d40

### Model prediction review lifecycle

For the Product Media Observation review lifecycle, the project also reviewed
the official Label Studio and Argilla documentation. Label Studio treats an
imported prediction as model-versioned, read-only input and keeps human
annotations distinct. Argilla presents model suggestions to annotators while
recording the resulting human response separately. The reusable contract is
immutable machine provenance plus human review and audit history, not a second
published knowledge source. See ADR 0002.

Primary sources:

- https://labelstud.io/guide/predictions.html
- https://docs.argilla.io/v2.0/reference/argilla/records/suggestions/
- https://docs.argilla.io/v2.2/how_to_guides/annotate/

### Offline VLM execution boundary

The local Qwen worker is an offline Docker-hosted vLLM service. vLLM documents
`/health`, `/v1/models`, `/load`, and `/metrics` as server observability
endpoints, and documents JSON Schema structured output for supported OpenAI
compatible servers. Qwen's model card documents the `image_url` chat message
format used by the worker. The current worker is pinned to vLLM 0.11.0, so a
JSON Schema request must be qualified against that running version before it
can replace the existing strict JSON-object transport. A slow or malformed
completion is an execution/completion failure, not a semantic observation
rejection.

Qwen's official documentation confirms Qwen3-VL support from vLLM 0.11.0 and
pixel-budget controls. The local vLLM 0.11.0 worker did not qualify: with the
same ten-image set, raw plain JSON reached 6/10 execution success and bounded
pixels reached 4/10; neither profile produced a complete JSON response. An
independent vLLM 0.12.0 candidate container, pinned to
`sha256:6766ce0c459e24b76f3e9ba14ffc0442131ef4248c904efdcbf0d89e38be01fe`,
then completed the bounded-pixel plain-JSON qualification at 10/10 single
extractions and 20/20 paired extractions. The pairwise fact, attribute,
normalized-value, identity, region, and high-risk rejection comparisons were
all stable, with no high-risk leakage. This qualifies the candidate runtime
for continued offline shadow use only; it does not change the default worker,
the JSON parser, evidence admission, or any customer-facing decision.

Additional official sources:

- https://github.com/QwenLM/Qwen3-VL
- https://docs.vllm.ai/en/v0.11.0/api/vllm/model_executor/models/qwen3_vl.html

Primary sources:

- https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
- https://docs.vllm.ai/en/stable/features/structured_outputs/
- https://docs.vllm.ai/en/latest/usage/metrics/
- https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct

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

Phase 0.4D adds an offline `ProductMediaObservation` extractor. It loads the
existing project `.env` without overriding exported process variables, then
reuses the OpenAI-compatible VLM configuration. It is not connected to the
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

The contract uses a positive `(observation_type, attribute_key)` allowlist plus
a canonical high-risk deny registry. The only accepted observation types are
`layer_count`, `compartment_count`, `labelled_dimension`,
`visible_structure`, and `visible_text`; unknown attributes fail closed. A
labelled dimension must come from a `size_image` and preserve raw OCR plus a
normalized metric-length value. `visible_text` is OCR only and cannot bypass
the attribute restriction. A role alone never proves content: a `sku_image`
cannot become a dimension fact merely because a scenario asks about size.
Age/child suitability, pinch safety, load, toxicity, food grade,
certification, stability, wall fixing, drilling, expansion screws, and
structural modification are rejected as out of scope in English and Chinese.

The extractor computes SHA-256 from the actual bytes sent to the VLM. Candidate
UIDs use that observed hash, while the legacy asset hash is retained separately.
Comparable 64-character SHA-256 values must match; legacy or non-comparable
asset hashes create an explicit warning, and a mismatch rejects the asset. No
base64 image body or signed URL is persisted in the report.

SQLite is opened with `PRAGMA query_only=ON` for inventory, preflight, and
extraction. An internal before/after fingerprint covers `KBProduct`,
`KnowledgeEntry`, and `KBMediaAsset` without exporting their contents. The
report records query-only state, state-unchanged status, and measured SQL write
attempts rather than a hardcoded mutation count.

The command is deliberately bounded and read-only:

```powershell
python scripts\extract_product_media_observations.py --media-role size_image --limit 30 --json-output outputs\product_media_observations_shadow.json
```

Use `--preflight` first. It verifies only configuration booleans and one bounded
visual request; it creates no observation. A companion read-only provider
diagnosis compares the response-format and plain-JSON transport profiles using
the same readable asset, but records only hashes, booleans, token counts, finish
reasons, and sanitized error categories. It never stores model text, reasoning
content, image data, signed URLs, or credentials.

The transport contract permits exactly one plain-JSON retry only when the
provider explicitly reports that `response_format` is unsupported. Authentication,
permission, rate-limit, timeout, connection, and server failures do not retry.
Only whitespace and one complete outer JSON code fence can be normalized. Empty,
truncated, natural-language, or schema-invalid responses produce no observation;
reasoning content is never used as an answer.

On 2026-07-11 the local configuration loaded successfully and current media
were readable, but the compatibility probe saw bounded timeouts and the formal
single-image preflight returned `truncated_response`. This is a provider
completion block, not a successful extraction. No 30-image scan or manual
review was started, and no candidate was generated.

### Local Qwen3-VL qualification

The offline shadow extractor can also use a locally hosted, OpenAI-compatible
visual model through process-local configuration. This does not replace the
project's configured formal VLM connection, and it does not connect model
output to the Analysis Pipeline, product evidence pack, Grounded Reasoning, or
delivery path.

`Qwen/Qwen3-VL-8B-Instruct` was qualified locally on 2026-07-11 with five
bounded image requests, a 45-second request limit, a 1024-token completion
cap, and at most five observations per image. All five responses were
schema-valid JSON, with no timeout, truncation, empty response, or high-risk
admission. The median request time was about 22 seconds. The model card and
the maintained Qwen repository document visual input and OpenAI-compatible
vLLM serving; they do not grant any product-claim authority by themselves:

- https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
- https://github.com/QwenLM/Qwen3-VL

The subsequent 30-image `size_image` shadow scan completed 29 model calls and
produced 107 pending-review candidates. It rejected five high-risk observations
and 33 dimensions that had multiple values for the same attribute but no
variant scope. A ten-image visual review found no unsupported pixel claim in
the sampled low-risk output, three correct strong-claim rejections, and one
correct ambiguous-variant rejection. All candidates stayed
`direct_answer_allowed=false`, `used_for_generation=false`, and
`can_change_can_send=false`.

The extractor prompt declares exact observation type/key pairs and requires a
structured region object or `null`; the parser remains fail-closed. Short age
claims such as an age threshold and formaldehyde-free claims are high-risk even
when a model splits them into short OCR fragments. Multiple different
dimensions for the same attribute in one image are rejected as
`ambiguous_variant_dimension_scope` until an explicit variant-level scope
exists.

The long scan reported zero SQL write attempts but an unstable before/after
formal-table fingerprint while the local application remained active. That is
an external-concurrency diagnostic, not evidence that the extractor wrote
knowledge. A stable snapshot or paused concurrent writer is required before a
future run can use that fingerprint as a formal no-change acceptance proof.

### Provider qualification status

Phase 0.4G adds a provider-neutral, read-only qualification report for the
same V3 panel/object/label/binding contract.  It makes execution, schema,
normalized-box, object-label binding, leakage, high-risk, repeatability, and
read-only database metrics comparable without treating a provider result as
formal product knowledge.  The 10-image gate must pass before any 30-image
provider run; a failed provider remains a diagnostic only.  See
`docs/research/vision-grounding-provider-qualification.md` for the current
candidate boundaries and official-source reuse assessment.

The local `Qwen/Qwen3-VL-8B-Instruct` baseline was run through that 10-image
gate on 2026-07-13 with two attempts per image.  Source reads and transport
execution were 100%, but only 36 of 51 V3 model stages were schema-valid
(70.59%, below the 95% gate).  The rejected stages were primarily missing
object or label boxes.  The observations that did pass still had zero
package/product leakage, component/overall leakage, high-risk admission,
formal knowledge write attempts, and `can_send` changes.  The provider did not
qualify for a 30-image run; the box rate among the smaller successful subset is
not a qualification result.

Phase 0.4G.1 adds a composable shadow PoC rather than broadening Qwen prompts.
It keeps OCR text boxes, object boxes, same-panel geometry, and verifier
acceptance separate.  On the current machine, no OCR/object runtime was
available, so its own 10-image run correctly stopped at
`provider_not_configured`; it created no observations, made no formal writes,
and did not change `can_send`.  It must receive real OCR and object adapters
before it can be compared against the local Qwen baseline.

Phase 0.4D.1 adds a bounded qualification matrix whose candidate connection is
supplied only through command-line environment-variable names. It uses one
readable, identity-scoped image and records no credentials, endpoints, image
bytes, model text, or reasoning content. A candidate must complete all three
initial requests with parseable schema-valid JSON and no timeout or truncation
before it can receive a five-request confirmation run.

The current configured OpenAI-compatible visual model did not qualify on
2026-07-11. Its response-format profile timed out on all three requests. Its
plain-JSON profile completed one of three requests but timed out twice, so its
stable JSON rate was only one-third. No five-request confirmation, 30-image
extraction, or manual sampling was run.
The project's existing DeepSeek text connection is also excluded as a visual
candidate: its official API documentation confirms OpenAI-compatible chat and
JSON Output, but does not document image input support. A future visual
candidate requires official image-input documentation and an already configured
credential; the project does not create keys, change providers, or spend money
automatically.

Official references used for that exclusion:

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/guides/json_mode/

### Agnes image-model probe

The configured Agnes-compatible model list can be authenticated and includes
models whose names contain `image`. A model-list name is not capability proof:
there is no verified official documentation establishing that the listed image
model accepts an OpenAI Chat Completions image-message request for visual
understanding. A single bounded plain-JSON probe against the listed image model
returned a 4xx not-found response under that contract. It is therefore not a
direct VLM candidate for this application. The project does not guess a
different endpoint, treat an image-generation model as a vision-understanding
model, or add a provider-specific client without official API evidence.

Missing VLM configuration, unreadable media, malformed model output, incomplete
identity, low confidence, or missing provenance fail closed and are reported as
diagnostics. A future staging/review workflow requires its own ownership
decision and ADR before observations can enter any formal evidence path.
