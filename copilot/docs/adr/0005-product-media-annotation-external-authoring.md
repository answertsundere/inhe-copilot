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
