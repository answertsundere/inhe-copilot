# Vision Grounding Provider Qualification

## Purpose and boundary

Product Media Observation v3 remains a shadow-only diagnostic.  This document
defines how visual providers are compared before a wider shadow run.  A passing
qualification does not make a provider a product-fact source, does not create
review candidates, and cannot alter customer replies, `can_send`, media blocks,
Grounded Reasoning, Product Evidence Pack, or formal RAG.

The 10-image gate is deliberately strict.  A provider that cannot reliably
produce valid object and label regions must not be compensated for by looser
prompts, guessed panel splitting, or post-processing that invents bindings.

## Reuse research

- [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL) documents relative-coordinate
  grounding.  It is the local baseline, not proof that its boxes are stable on
  product specification images.
- [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) is an
  open-set, text-guided object detector.  It is a plausible object-box
  candidate, but it does not itself bind a product object to a specific printed
  label.
- [Florence-2 in Transformers](https://huggingface.co/docs/transformers/model_doc/florence2)
  supports OCR with regions, object detection, and phrase grounding through
  explicit task prompts.  It is a candidate for a later local adapter, not an
  installed dependency in this phase.
- [PaddleOCR text detection](https://www.paddleocr.ai/v3.4.1/en/version3.x/module_usage/text_detection.html)
  produces text-region boxes.  It can complement object grounding, but it
  cannot establish object-label or product-identity binding by itself.
- [InternVL grounding guidance](https://internvl.readthedocs.io/en/latest/tutorials/faqs.html)
  documents a referring-expression bounding-box prompt.  It remains a provider
  candidate until a configured model passes the same qualification contract.

No new model runtime is installed for a qualification framework.  This avoids
claiming a detector has been evaluated merely because its package can be
installed.  The current local Qwen vLLM worker is the executable baseline;
external grounding and OCR/layout entries remain configuration diagnostics until
their adapter and credentials are explicitly supplied.

## Composable grounding PoC

Phase 0.4G.1 separates OCR, object proposals, deterministic geometry, and VLM
verification.  This is not an attempt to reconstruct a full product fact from
one model response.  OCR must provide a text box; an object provider must
provide a scoped object box; geometry only considers same-panel, unambiguous
nearest candidates; and the verifier can only accept or reject that supplied
candidate.  A verifier-provided bbox is a schema failure.

The local environment on 2026-07-13 has OpenCV and Windows OCR, but no
PaddleOCR, Tesseract, EasyOCR, Transformers, Torch, GroundingDINO, or
configured external OCR/object provider. Windows OCR is the first executable
OCR-only candidate: it returns recognised text and line positions through
`Windows.Media.Ocr.OcrEngine`. The adapter normalises those pixel boxes to the
project 0..1 contract and records them only as label candidates. It does not
create observations, review records, formal facts, reply blocks, or delivery
decisions.

The prior 10-image composable run still correctly reported
`provider_not_configured` for the full OCR-plus-object pipeline. OCR-only
qualification is a separate strict gate. It must achieve source reads of
100%, OCR execution/schema/text-box rates of at least 95%, repeated text and
text-box IoU stability of at least 90%, and zero high-risk observation admissions, formal
writes, or `can_send` changes before an OCR-only 30-image shadow scan is
permitted. Passing OCR does not qualify an object provider or object-label
binding. The expanded scan reports its own mode and does not re-evaluate or
overwrite the completed 10-image gate.

PaddleOCR is the preferred first OCR adapter because its documented general OCR
pipeline produces text regions and recognition output.  Grounding DINO is a
candidate object adapter because it produces text-guided object boxes; it does
not establish printed-label binding itself.  Florence-2 remains an alternative
candidate because its documented tasks include OCR with regions and phrase
grounding.  Each requires its own configured adapter and the same 10-image
gate before a real comparison is meaningful.

## Common provider adapter contract

Every stage outcome is normalized without keeping image bytes, signed URLs,
credentials, prompts, chain-of-thought, or raw model text.  It records:

- provider/model/request identifier and image SHA-256;
- `panel`, `object`, `label`, or `binding` stage;
- execution and schema status with a sanitized error category;
- a normalized 0..1 bounding box when one is valid;
- object type, label/value/unit/attribute/relation fields when the provider
  supplies them; and
- confidence, rejection reason, latency, and optional provider token/cost
  estimates.

V3 remains the owner of the actual panel/object/label validation.  The
qualification adapter only projects its diagnostics into the common comparison
schema and never modifies accepted or rejected observations.

### OCR-only adapter contract

The composable OCR adapter returns provider/model/runtime identity, image
SHA-256, recognised `text`, a normalized text bbox, confidence, language or
script, source image dimensions, latency, and sanitized execution/schema
errors. OCR text is a label candidate only. Dimension, mode, packaging, and
high-risk terms are counted for qualification diagnostics; high-risk text can
be recorded but cannot become an observation. The adapter uses a temporary
local file only because the Windows runtime API requires a file-backed image;
the file is removed after each request and no image bytes are written to a
knowledge table.

### Object-proposal adapter contract

The composable object adapter is a separate shadow stage. It returns a
normalised primary visual-region box, panel reference, candidate scope,
confidence, image provenance, runtime identity, and sanitised execution or
schema errors. It does not create an observation, invoke geometry binding, or
write a review candidate.

The first local adapter uses OpenCV contours only to find a primary visual
region. OpenCV contour primitives are geometric, not semantic: an explicit OCR
packaging cue can classify that region as `packaging`; a display cue can
classify it as `display_prop`; every other region is
`unknown_object_scope`. An unknown region must not be upgraded to `product`.
Component detection is explicitly reported as unsupported. A configured
Grounding DINO or Florence-2 adapter remains the next candidate for semantic
object scopes, subject to this same gate.

On 2026-07-13, the deterministic adapter read, executed, validated, and boxed
all 20 repeated runs from the fixed ten-image set. Its object type and box IoU
were stable for 10/10 assets, and it produced no scope leakage, knowledge write
attempt, or sendability change. It resolved only 4/20 object candidates as
explicit packaging and left 16/20 as unknown. The resulting 20% object-scope
resolution rate intentionally failed the 90% semantic-scope gate. The run did
not advance to a thirty-image scan.

### Semantic object-provider qualification

The next provider candidate is Grounding DINO because its official project is
an open-set detector that accepts an image and generic text categories and
returns scored boxes. Florence-2 remains an alternative because its documented
Transformers tasks include detection and phrase grounding. Neither category
detector establishes object-to-label binding or product identity, so both stay
behind the existing panel, OCR, geometry, and review contracts.

The semantic adapter uses only generic category queries such as `product`,
`box`, `carton`, `drawer`, `door`, `panel`, and `screw`; it cannot receive a
specific product title or test phrase. Every provider result is normalised
before use. A packaging result requires same-panel OCR packaging wording; a
product and packaging box with high overlap are both rejected; a component must
be inside a same-panel product box and cannot cover nearly all of it; display
props and unknown objects remain their supplied scope. Conflicting output fails
closed. These are shadow diagnostics only and never create observations.

The local runtime inventory on 2026-07-13 found an NVIDIA RTX A6000 and
ONNX Runtime, but no PyTorch, Transformers, Grounding DINO, model cache, or
configured model paths. The ten-image semantic qualification therefore read
20/20 repeated source images but returned `provider_not_configured` for all 20
semantic attempts: execution, schema, bbox, and semantic-scope rates were 0%.
Formal-write and `can_send` changes remained zero. Its OpenCV comparison still
completed 20/20 boxes but only resolved 4/20 scopes. The semantic run did not
advance to thirty images. Empty provider output is not reported as repeatable
object detection.

Minimum future preparation is a CUDA-compatible PyTorch runtime, one official
provider runtime plus its official model weights, and explicit model-path
configuration. Installation alone is not qualification evidence; the same
fixed ten-image gate must pass before geometry binding is enabled.

### Runtime readiness and minimal probe

Phase 0.4G.5 adds a read-only runtime readiness report and a one-image probe
before any semantic ten-image run. The readiness report records Python and
provider module availability, CUDA visibility through PyTorch when installed,
model-cache presence, configured model-path presence, and aggregate disk space
without exposing tokens or full private paths. The probe permits only generic
category terms such as `product`, `packaging`, `component`, and `accessory`.
It reports provider/runtime/weight availability, normalised box counts, labels,
confidence, latency, and a sanitised error category. It never writes
observations, staging records, or formal knowledge.

On 2026-07-13, readiness found Python 3.11.9, an RTX A6000, and sufficient
local disk space, but no PyTorch, Transformers, Grounding DINO, Florence-2, or
recognised model cache. The Grounding DINO minimal probe therefore stopped
before image/model inference with `provider_not_configured`. This is the
correct precondition failure, not a zero-box model result. Qualification was
not run; no thirty-image scan, Geometry Binding, review candidate, formal write,
or `can_send` change is permitted.

## Qualification gate

The script runs a fixed, ordered set of up to ten approved `size_image` assets
and repeats each image by default.  It stops at this gate: a failed 10-image
run must not advance to a 30-image run or create pending-review data.

Required gate results are:

- source image reads: 100%;
- execution and schema success: at least 95%;
- object boxes: at least 90%; label boxes and object-label bindings: at least
  90%;
- object semantic-scope resolution: at least 90%; a geometry-only unknown box
  cannot pass as a product candidate;
- no package-as-product, component-as-overall, or high-risk admissions;
- zero formal knowledge write attempts and zero `can_send` changes.

Repeatability is reported separately for stable observation UIDs, semantic
signatures, and matched-box IoU.  It is diagnostic evidence, not a reason to
relax any gate.  Provider timeout or malformed schema is an execution failure,
not business `rejected_evidence`.
