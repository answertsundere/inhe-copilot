# ADR 0004: Composable Vision Grounding Shadow PoC

## Status

Accepted, 2026-07-13.

## Context

The local Qwen3-VL-8B worker completed visual requests but did not meet the
V3 10-image schema gate for stable object and label bounding boxes.  Asking one
VLM to classify panels, read labels, locate objects, and bind measurements
couples independent failure modes and makes a missing box look like a prompt
problem.

## Decision

Introduce a shadow-only composable PoC with four explicit contracts:

1. OCR supplies text, normalized text boxes, confidence, and source.
2. An object provider supplies normalized object boxes, scope, confidence, and
   source.
3. Deterministic geometry proposes only unambiguous same-panel label/object
   bindings.
4. A VLM verifier may accept or reject one supplied candidate.  It may not add
   or modify a panel, object, or label box.

The resulting observation remains pending review, cannot be used for
generation, and cannot change sendability.  Packaging, component, accessory,
and mode-scoped measurements remain their own scopes.  The PoC never writes a
knowledge table.

## Alternatives Considered

1. Relax V3 bounding-box rules: rejected because it would conceal unreliable
   grounding and allow packaging/component leakage.
2. Treat deterministic panel proposals as product-object boxes: rejected
   because a panel is a canvas region, not proof of the complete sellable item.
3. Install several heavy OCR/detection runtimes immediately: rejected because
   installed packages are not qualification evidence and would consume the
   existing local visual GPU before an adapter has been measured.

## Verification and rollback

The first real run is configuration-only when OCR/object runtimes are absent;
it records a failed 10-image qualification and cannot advance to 30 images.
Synthetic adapter tests cover normalized boxes, same-panel-only binding,
packaging/component/mode separation, high-risk rejection, verifier schema
failure, and unchanged sendability.  Removing the additive service and script
rolls back the PoC without data migration or effect on formal customer paths.
