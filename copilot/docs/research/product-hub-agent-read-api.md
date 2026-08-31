# Product Hub Agent Read API Review

## Scope

This note evaluates the existing Product Hub read API as a narrow source of
reviewed product facts for the customer-service Agent. It does not evaluate the
Hub as a reply generator, RAG replacement, media sender, or knowledge writer.

## Existing Capability

The maintained Product Hub source already exposes a versioned, read-only
`/api/agent/*` boundary. Its documented lookup keys are `productCode`,
`skuCode`, and barcode. The product facts endpoint is intended to return
confirmed structured facts for one exact product, while SKU identity remains a
separate natural-key contract. This is the correct reuse point: the Agent must
not scrape the Hub UI, query the Hub database, or match a customer title to a
product name.

The live service currently exposes the capability endpoint and product passport
endpoint. A read-only runtime probe found a response-shape defect in
`GET /api/agent/products/:code/facts`: the array was spread into numeric JSON
keys instead of being returned under `facts`. A release-compatible fix has been
verified in an isolated copy: return `facts: [...]` and add the stable
`skuCode` natural key to every SKU-bound fact. The Copilot bridge depends on
that stable contract and stays disabled until the Hub release is deployed.

## Integration Rules

1. Resolve trusted JST/internal identity through the existing Product Identity
   Resolver before any Hub request. When JST supplies an exact `sku_id`, use it
   only as the Hub `skuCode` natural key.
2. Read `GET /api/agent/skus/:skuCode`, require the returned `skuCode` to match
   exactly, and use its returned `productCode` for the facts request. A JST
   `i_id` must never be treated as a Hub `productCode` without that exact SKU
   mapping. A direct product-code lookup remains limited to an established
   non-JST internal/Hub product-code contract.
3. Read only the documented Agent endpoint with an explicit bounded timeout and
   normal TLS verification. The bridge uses the Python standard-library HTTP
   transport already used by strict provider code, so no new HTTP dependency or
   background sync is introduced. The same explicit-timeout principle is also
   documented by [Requests](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts).
4. Accept only `status=confirmed`, `conflict=false`, exact returned
   `productCode`, and an exact `skuCode` when a fact is SKU-scoped.
5. Preserve immutable provenance identifiers and structured type/scope fields;
   omit unstructured `sourceDetail` from model-facing evidence.
6. Convert accepted rows into the existing Product Context Pack candidate
   contract. Existing admission remains the only owner that can make a fact
   available to a reply.
7. Treat images, captions, notes, and semantic asset search as reference-only
   follow-up work. They do not become facts or delivered media in this slice.

## Rejected Alternatives

- Bulk copying Hub rows into the formal knowledge database: creates stale,
  duplicated truth and bypasses the established review lifecycle.
- Product-title or fuzzy product search: can select the wrong product.
- Passing all Hub facts or raw product passports to the model: violates the
  minimal-context contract and exposes unrelated facts.
- Sending Hub images merely because they were retrieved: violates the existing
  media delivery contract.

## Rollback

The Agent-side reader is guarded by
`COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED=false` by default. Disabling that
single flag removes Hub facts before Product Context Pack candidate construction
without changing JST identity, local retrieval, evidence admission, media, or
delivery behavior.
