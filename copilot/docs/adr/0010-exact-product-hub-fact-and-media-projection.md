# ADR 0010: Exact Product Hub Fact And Media Projection

## Status

Accepted, 2026-08-22.

## Context

The Product Data Hub already holds SKU-scoped product fields and labeled media
for the catalog. Treating that system only as a display-name directory leaves
the formal answer path without exact, current facts after a JST/order lookup
has resolved the product identity. Copying those values into a second customer
service database would create a stale, competing source of product truth.

The Hub also contains labels such as size image, material explanation, and
certificate image. A label is useful for selecting a matching media candidate,
but it is not a product claim and must not promote certification, safety, or
other high-risk assertions.

## Decision

`ProductDataHubReadClient` may make a read-only exact bundle request only when
the existing exact product/SKU resolver has selected one active parent and, if
a SKU is supplied, that exact SKU belongs to the same parent. The bundle
projects only confirmed, non-conflicting fields whose product/SKU scope matches
that identity into the existing `ProductContextPackService` product-fact
channel. It preserves the original field UID, Hub source marker, identity
scope, value, unit, and controlled subject scope.

The existing Evidence Filter, Evidence Builder, and
`AdmittedAnswerContextService` remain the only evidence/admission owners.
Material fields carry a dedicated `product_data_hub_confirmed` provenance token
only after this exact confirmed projection. High-risk categories remain outside
direct answer admission. Packaging, component, accessory, included-item, and
product-overall measurements retain their declared subject scope and are not
interchanged.

For a directly admitted Hub fact, its customer-facing attribute label and
value remain one evidence unit. Deterministic rendering and grounding retain
the admitted `title`/`attribute_key` beside its value so a direct dimension
answer is not misclassified as an unsupported assertion. Labels still cannot
become facts before the existing admission checks.

Labeled media is selected only after exact identity resolution and only for a
compatible requested fact type. The label controls media role selection; it
does not create a fact. Media still must pass the existing approval, usability,
identity, and role checks before a reply block can attach it.

The change is disabled by default behind
`COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED` and additionally requires the
existing Product Hub adapter flag. It adds no graph node, model call, reply
owner, sender, or `can_send` authority. Existing deterministic Final and
Delivery contracts retain their authority.

## Alternatives Considered

- Continue using the Hub only as an identity directory: rejected because it
  cannot answer exact SKU facts already present in the catalog.
- Copy Hub fields and media into the formal knowledge database: rejected because
  it creates synchronization drift and a second publication owner.
- Use media/OCR labels as product truth: rejected because labels cannot prove
  certification, safety, scope, or current product values.

## Business And Safety Consequences

Exact product questions can use the Hub's confirmed current fields through the
same admitted-evidence contract as other product facts. Unsupported/high-risk
questions remain unresolved. A missing, ambiguous, conflicting, malformed, or
unavailable Hub result fails closed and leaves existing behavior unchanged.

This decision does not authorize channel delivery or automatic sending. A
future send promotion must prove a real platform delivery capability and pass
the existing Final, Safety, media, and Delivery requirements separately.

## Migration And Rollback

Enable only in a canary runtime with both Product Hub flags set. Roll back by
disabling `COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED`; no Hub data is
written, cached as formal truth, or migrated.

## Verification

- exact parent/SKU matching, confirmed/non-conflicting projection, and malformed
  result rejection;
- material provenance, source provenance, and existing admission checks;
- product/packaging/component scope isolation;
- role-compatible labeled-media selection;
- no Product Hub writes, formal knowledge DML, or `can_send` change.
