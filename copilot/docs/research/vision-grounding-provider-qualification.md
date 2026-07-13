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

The local environment on 2026-07-13 had OpenCV but no PaddleOCR, Tesseract,
EasyOCR, Transformers, Torch, GroundingDINO, or configured external OCR/object
provider.  The 10-image composable run therefore reported
`provider_not_configured`, did not emit observations, did not qualify for 30
images, and recorded zero formal writes and `can_send` changes.  This is the
correct fail-closed result, not a lower score to be repaired with synthetic
boxes.

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

## Qualification gate

The script runs a fixed, ordered set of up to ten approved `size_image` assets
and repeats each image by default.  It stops at this gate: a failed 10-image
run must not advance to a 30-image run or create pending-review data.

Required gate results are:

- source image reads: 100%;
- execution and schema success: at least 95%;
- object boxes: at least 95%; label boxes and object-label bindings: at least
  90%;
- no package-as-product, component-as-overall, or high-risk admissions;
- zero formal knowledge write attempts and zero `can_send` changes.

Repeatability is reported separately for stable observation UIDs, semantic
signatures, and matched-box IoU.  It is diagnostic evidence, not a reason to
relax any gate.  Provider timeout or malformed schema is an execution failure,
not business `rejected_evidence`.
