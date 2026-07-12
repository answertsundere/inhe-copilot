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
  object box and a label box.
- Product, packaging, and component measurements remain distinct. A packaging
  or component value is never selected as a product dimension.
- Visible text is reference-only. High-risk safety, load, certification,
  toxicity, child-suitability, and installation-prescription content is
  rejected before graph construction.
- The Product Understanding Graph records only direct subject/relationship and
  measurement edges. It is shadow-only and cannot change formal evidence,
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
state/parent edges, high-risk rejection, structured selection, and unchanged
sendability. A later phase must qualify the v3 worker, scan source media, and
introduce a human-review persistence contract before real v3 observations can
be evaluated.
