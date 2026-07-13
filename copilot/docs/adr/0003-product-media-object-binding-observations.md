# ADR 0003: Product Media Object-Binding Observations

## Status

Accepted, 2026-07-12.

## Context

The v2 Product Media Observation contract extracted isolated layer counts,
dimensions, visible structure, and OCR. It did not model whether a label applied
to the product, packaging, a component, an accessory, or a display prop. An
isolated dimension therefore cannot safely support product understanding.

## Decision

Create a separate v3 shadow contract. Every visual observation binds a visible
subject, optional state, parent relationship, and measurement target before it
can be inspected in shadow diagnostics.

- Subject scope is one of `product`, `packaging`, `component`, `accessory`,
  `included_item`, or `display_prop`.
- Measurements use a generic axis (`length`, `width`, `height`, `depth`,
  `thickness`, `diameter`, `capacity`, or `count`) and must include both an
  object box and a label box. The extractor performs classification, object
  localisation, label localisation, then binding as separate model stages and
  normalises accepted boxes to `0..1` coordinates.
- Product, packaging, and component measurements remain distinct. A packaging
  or component value is never selected as a product dimension.
- Visible text is reference-only. High-risk safety, load, certification,
  toxicity, child-suitability, and installation-prescription content is
  rejected before graph construction.
- The Product Understanding Graph records only direct subject/relationship and
  measurement edges (`part_of`, `measured_as`, `labelled_by`, `visible_in`, and
  `active_in_mode`). It is shadow-only and cannot change formal evidence,
  replies, delivery, or sendability.

The v2 candidate rows remain immutable legacy staging data. They are not
deleted, auto-approved, or accepted as v3 review input. Re-extraction creates
new v3 observations from the current source media and links any future
supersession by source-media SHA-256 and provenance.

## Alternatives Considered

1. Add more product-specific dimension fields to v2: rejected because this
   preserves the missing object target.
2. Treat every size-image label as a product size: rejected because labels can
   describe packaging, parts, or another displayed object.
3. Promote visual observations to formal product facts: rejected because human
   review and shadow evaluation are still required.

## Business And Safety Consequences

This decision enables object-bound shadow diagnostics, not automatic customer
answers. It cannot infer load capacity, safety, toxicity, certification,
child suitability, wall fixing, drilling, modification, or a customer-specific
fit calculation from a visual observation.

## Migration And Rollback

The v3 service is additive and has no database write path in this phase. A
read-only migration plan reports v2 inventory without changing any row. Rollback
removes the v3 shadow service and leaves v2 staging and formal knowledge intact.

## Verification

Synthetic tests prove object/label binding, packaging/component separation,
state/panel/parent edges, high-risk rejection, structured selection, and
unchanged sendability. The staged source-media reader resolves original bytes
before validated cache or URL fallback and records the observed SHA-256 only as
shadow provenance. Multi-panel classification uses panel/object/label bounding
boxes; a repair call may repair missing panel boxes but cannot create facts.
Cross-panel bindings and near-duplicate full-image panel boxes are rejected.
The v3 preflight may additionally create deterministic layout proposals from
image geometry. Proposals are localisation-only, and a VLM may only verify,
make a bounded alignment, merge compatible regions, or reject them. A proposal
does not create a product fact or bypass object/label scope and containment.

A ten-image retest on 2026-07-13 restored source reads to 10/10 but rejected
one image whose two repaired panels overlapped as near-full-image duplicates.
The execution/schema threshold was therefore still not met. A later phase must
stabilise the worker contract before any v3 review persistence or
evidence-promotion contract is introduced.

The follow-up deterministic proposal qualification also failed the ten-image
gate because the corpus did not yield reliable whitespace proposals and the
local VLM's object/label boxes were not stable. The system remains shadow-only;
this does not authorize a thirty-image scan or candidate persistence.
