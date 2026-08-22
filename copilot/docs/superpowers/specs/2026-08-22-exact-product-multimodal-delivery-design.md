# Exact Product Multimodal Delivery Design

## Goal

Make the existing customer-service Pipeline answer product questions from the
Product Data Hub's exact product/SKU facts and, when appropriate, automatically
attach the matching product image or video as an actual reply block.

## Decision

The Product Data Hub becomes an opt-in, read-only product evidence and media
source after an exact product or SKU match. It does not replace the existing
Product Context Pack, Evidence Admission, Composer, Final Answer Auditor, or
Delivery Gate.

The request path is:

```text
JST/order/sidebar identity
-> exact Hub product and SKU resolution
-> confirmed, non-conflicting scoped Hub facts
-> exact-product asset pool
-> label/purpose filter then local semantic rerank
-> existing Product Context Pack
-> existing evidence admission and Composer
-> existing Final Auditor and reply-block Delivery Gate
```

Vector similarity ranks only assets already constrained to one resolved Hub
product and compatible SKU scope. It never resolves a product, creates a fact,
or allows a cross-product asset.

## Product Facts

The project owner has explicitly accepted Hub `ai-label` facts as usable product
facts. A Hub fact is eligible only when all of the following are true:

- the Hub identity is exact and not ambiguous;
- `status` is `confirmed` and `conflict` is false;
- its `applies` field is empty or exactly matches the resolved SKU;
- its scope is compatible with the requested claim;
- its fact type maps to an existing canonical claim type.

The initial mapping is `size -> dimensions`, `color -> color_options`,
`material -> material`, `parts -> accessories`, `pack_size -> packaging`, and
`weight -> gross_weight` only when the Hub scope explicitly identifies gross
weight. `age`, `load`, and any certification/safety conclusion remain governed
by the existing high-risk policy and cannot be inferred from a broad material
or image label.

Hub facts retain the Hub fact ID, source, source detail, update time, scope,
SKU applicability, and a value-sensitive digest as provenance. The Hub remains
query-only; no fact, image, embedding, or review state is written back to it.

## Product Media

The Hub product endpoint already exposes its exact product assets, labels,
notes, spec references, status, SKU scope, SHA-256, and preview availability.
The adapter projects only assets that are approved/live, have a usable preview
or original delivery URL, and match the resolved product/SKU.

The existing media purpose model is reused:

- dimensions: `尺寸参数图`;
- installation: `安装说明`;
- accessories/packaging: `包装清单` or matching accessory material;
- product appearance/color: `产品信息图` or `白底单品图`;
- material: `材质说明`;
- certificate/report: `合格证质检`;
- brand recognition: `平台榜单图`.

Label and scope filtering happen before semantic ranking. Ranking input is the
customer question plus the asset's Chinese label, label note, spec reference,
canonical name, and product/SKU identity. The maximum automatic attachment is
one asset per reply. The selected asset becomes a `media_reference`, never a
product fact.

An award or listing image may support a statement about that award/listing only.
A report image may be attached for the exact product, but safety, certification,
non-toxicity, age suitability, load capacity, or medical conclusions must still
be directly supported by an eligible fact or the report's explicit structured
description. An image must not expand a conclusion beyond its stated scope.

## Automatic Delivery

The existing `build_reply_blocks()` path remains the sole block builder. Its
existing auto-delivery result may be true only when:

- the final text is non-empty;
- the asset is an eligible exact-identity media candidate;
- the asset purpose matches the requested claim type;
- the asset URL is available;
- no requested high-risk claim remains unsupported or conflicting;
- the deterministic Final Contract accepts text and blocks; and
- the channel reports media delivery capability.

This feature is controlled by one default-off runtime flag:
`COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED`. Disabling it restores the
current identity-reference-only Hub behavior. It does not change JST tooling,
formal knowledge writes, model ownership, Graph structure, or platform adapters.

## Validation

Tests cover exact product/SKU matching, scoped fact mapping, package-versus-
product dimensions, conflict exclusion, label-before-vector ranking, media
identity/purpose checks, high-risk conclusion boundaries, reply-block delivery,
flag-off compatibility, and no Hub writes. A real workbench replay compares
the same cases with the flag off and on, reports evidence/media attachment,
can-send, safety blocks, and latency, and does not claim real-customer accuracy
without approved labels.

## References

- Shopify Inbox: product catalog, knowledge files, automatic answers, and
  image sending.
- Gorgias AI Agent: product-information sources and condition-based actions.
- Intercom Fin: source-aware retrieval, reranking, inspection, and escalation.
