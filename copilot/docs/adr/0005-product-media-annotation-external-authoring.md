# ADR 0005: Product Media Annotation External Authoring

## Status

Accepted, 2026-07-13.

## Context

The local OCR provider qualifies only as text-box extraction. OpenCV,
Grounding DINO Tiny, and Florence-2 Base do not meet the semantic object-scope
gate. Continuing to tune generic prompts or relax visual scope rules would
allow packaging, component, or mode dimensions to be mistaken for overall
product facts.

## Decision

Use a read-only Label Studio task export as the first annotation authoring
format. Tasks contain image references, durable product identity metadata,
shadow OCR/model suggestions, Chinese annotation instructions, and prohibited
fact labels. Human annotations remain external to the formal knowledge base.

The future training target, if a calibrated pilot supports it, is a specialized
detector for visual scope regions only. Object-to-label relationships and all
high-risk text remain review data, not detector-derived answer facts. COCO is
the portable downstream training interchange; a YOLO derivative may be used
only for a detector experiment.

## Alternatives considered

1. Keep tuning general VLM bounding-box prompts: rejected because three
   providers already failed the same strict gate.
2. Build a custom annotation editor in the admin application: rejected because
   established annotation tools already handle editable box suggestions,
   review, and dataset export.
3. Train directly from OCR and model candidates: rejected because they are
   unreviewed shadow signals and would reinforce their own errors.

## Business and safety consequences

The decision creates no formal fact, customer reply, delivery block, or
`can_send` change. The existing observation and review contracts still reject
high-risk visual claims and scope leakage. Any future training output must pass
the same shadow qualification before Geometry Binding or a review workflow is
considered.

## Migration and rollback

The export and diagnostic scripts are additive and query-only. Removing them
requires no database migration, model deletion, or customer-path rollback.

## Verification

Tests validate the category schema, Label Studio JSON shape, prohibited
high-risk labels, read-only guard metrics, and unchanged sendability. Exports
are validated with standard JSON parsers before external import.

## Phase 0.4H.1 Pilot boundary

The first pilot is a reproducible batch of twenty approved, agent-usable image
assets whose actual source bytes were read before export. Each task records a
stable task UID, source-byte SHA-256, image dimensions, media identity scope,
and an external authoring reference. The authoring package includes a Chinese
Label Studio configuration and keeps OCR only as editable predictions.

Label Studio annotations remain external review artifacts. The read-only export
validator requires task UID and source-hash continuity, legal rectangles,
allowed labels, legal relation endpoints, a completed human annotation, and
annotator/time metadata. It reports rework errors per task and does not create
an observation, pending review, product fact, or delivery change.

## Phase 0.4H.2 Profiled authoring and visual descriptions

New tasks no longer use the broad `visual_layout` palette. The exporter chooses
one of four profiles from explicit annotation task type, media role, and exact
scene tags: `packaging_dimension`, `mode_dimension`,
`product_specification`, or `compliance_document`. The legacy palette remains
readable only so an existing Label Studio manifest and completed annotation are
not rewritten.

Each profile exposes only its relevant Chinese labels and image-scope choices.
In particular, a packaging task cannot mark the product illustration printed
on a carton as a product instance, a compliance-document task only offers the
document scope, and a mode task cannot mark packaging, included items, or
display props. High-risk copy remains a dedicated text region rather than a
fact label.

The read-only validator compiles completed regions, controlled fields, and
relations into a structured visual-description result. Product context, image
scope, panels, objects, dimensions, visible text, and high-risk text retain the
source image SHA-256 and region bounding-box provenance. A dimension is tied to
its measured object and may remain packaging-, component-, or mode-scoped; it
is not promoted to an overall product dimension. The compiled description is
an external review result only. It is not stored in the knowledge base and is
not consumed by Product Evidence Pack, Grounded Reasoning, customer replies,
or sendability decisions.
