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

1. Resolve trusted JST/internal identity before any Hub request. A normal
   Product Identity Resolver result is accepted; an existing live JST order
   identity is accepted only when the order resolver already selected one
   unambiguous single item or primary item with gifts, has a confident exact
   `sku_id`, and has no conflicting SKU signal. In either case, use a JST SKU
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
   omit unstructured `sourceDetail` from model-facing evidence. A product-level
   fact reached by an exact SKU lookup may use that verified SKU as its
   admission scope, but retains its original Hub product and fact scopes in
   provenance; no such binding is created without the exact mapping.
6. Convert accepted rows into the existing Product Context Pack candidate
   contract. Existing admission remains the only owner that can make a fact
   available to a reply.
   The current low-risk mapping is deliberately narrow and requires the full
   published tuple, not merely a fact type: `material/材质/商品整体/empty unit`,
   `size/尺寸/商品整体/cm`, `installation/安装说明/商品整体/empty unit`,
   `color/颜色/商品整体/empty unit`, `age/适用年龄/商品整体/empty unit`,
   `load/承重/商品整体/empty unit`, `weight/毛重/包装/kg`, and
   `parts/配置说明/配件/empty unit`. The parts tuple is accepted only when both
   its Hub SKU and `applies` exactly match the resolved SKU; it describes the
   catalog configuration and cannot prove a customer received every part. A
   component or packaging field cannot be reinterpreted as a product-level
   field, and an axis value cannot be reinterpreted as overall dimensions. Color is not
   inferred from a title, free-text note, variant label, or image. A load field
   with another unit or scope, and an age field outside the published tuple,
   remain unavailable rather than being normalized by name. Multiple
   eligible variant rows are aggregated deterministically into one
   product-level options fact; that fact does not claim current stock or
   fulfillment availability. Product net weight and untyped weight are
   rejected rather than being relabeled as a shipping fact.
7. Treat images, captions, notes, and semantic asset search as reference-only
   follow-up work. They do not become facts or delivered media in this slice.

## Answer Context Shadow Transport (2026-09-08)

The same reader optionally calls `GET /api/agent/answer-context?skuCode=` once,
after the existing resolver proves an exact SKU. Enable only with
`COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED=true`; absence/false gives
zero extra HTTP requests and no new pack field. This does not enable or replace
the existing reviewed facts/media readers. The same base URL, bounded timeout,
response byte limit and TLS verification apply; an error has no retry or legacy
transport fallback.

The versioned payload must declare `readOnly=true`, exact SKU identity, active
product/SKU status, per-fact confirmation, source product/SKU binding and
`conflict=false`. Missing or mismatched metadata invalidates the response.
Known media types reuse the existing safe media projection; an unknown media
type is excluded and counted, not allowed to discard otherwise valid facts.
Media is never a fact. Raw source details, image notes and passport text do not
enter the returned projection.

The pack reuses its existing field-tuple and media adapters for comparison and
exposes only `stats.product_hub_answer_context_shadow`: state/reason, source
counts, mapped candidate count, unsupported media type count, review-only image
count, and `formal_merge_count=0`. No candidate values, identities or URLs are
added to diagnostics. Formal facts, evidence pack, recommended assets and reply
fields remain identical to the flag-off result. Candidate count is not admission
count or customer accuracy. Disable this flag to remove the shadow read.

The 2026-09-08 local HTTP probe used an existing SQLite snapshot, not the live
Hub database: three exact SKUs resolved; 13 source facts, 104 review-only media
and nine excluded unsupported media types. Only two color-options candidates
mapped among dimensions/material/color/installation queries. Snapshot SHA-256
was unchanged and SQLite `query_only=1`, `total_changes=0`; model calls were zero.
This slice does not broaden fact semantics to manufacture missing dimensions.

Two separately reported, deterministic contract-positive probes mapped two
material candidates and one overall-dimensions candidate. They supplement, not
replace, the original three products. A read-only source-field inventory found
18,945 confirmed non-conflicting rows, including 341 dimension tuples and 670
material tuples understood by the existing field mapper. 12,361 rows did not
match that mapper; this is not a missing-data count or an admission failure
rate, because exact identity, grouping, requested claims and admission were
not evaluated for every inventory row. Further source coverage must be audited
without guessing meaning from labels or removing existing AI annotations.

## Care Source Gap Audit (2026-09-10)

A bounded read-only audit of the same native-test product found related
board-erasure annotations and two matching detail images, but no established
whole-product cleaning method. Its 64 product-wide fact rows contain no
cleaning_care record; the separate extraction-state table has no entry for that
product. Four FAQs and the current SKU attributes add no care method. Zero
cataloged manuals does not establish absence of external/off-catalog documents.

The existing Hub StructuredFactSource/Contract components already support
cleaning_care with product/component/accessory scopes, source references and
provenance. A local source-only invocation selects 43 deduplicated notes, of
which 36 have eligible cleaning-source labels. This does not mean 36 cleaning
facts, that the live extractor is enabled, or that its Provider is qualified.
No model call, fact generation or persistence was performed.

The live Copilot reader receives 54 confirmed rows and its mapper preserves
the two frozen material UIDs. Cleaning candidates are zero. The direct field
tuple map currently has no cleaning_care entry, so a future source record also
requires an explicit compatible boundary; a blanket type-only mapping is unsafe.

Next work should reuse those existing components to bind the exact subject
(writing surface, frame or accessory), property versus cleaning action,
applicability, conditions, and original source. Board-mark erasability does not
prove wet-cloth compatibility, washing, chemicals or no-disassembly cleaning.
Marketing safety/durability language cannot be bundled into a low-risk fact.
Existing labels/notes remain untouched. The Agent must consume a valid typed
fact through ordinary admission, never raw notes or a hand-written response.
Run generic scope/identity/conflict mutations before any narrow bridge change,
and exercise the same native Pipeline only after valid source facts exist.
This is a data/contract finding, not a new registry, evaluator or quality score.

## Care Subject Selection Guard (2026-09-10)

Before enabling any care tuple, a generic test exposed a downstream gap:
Claim Resolution applied subject selection to dimensions only, so an admitted
component instruction could satisfy an unscoped cleaning question. The existing
owner now restricts the three established care types to product/product_overall
facts. Missing/non-product subjects produce care_subject_scope_unbound; the
customer goal is not rewritten to product scope. Existing attribute matching,
conflicts, other supported claims and no-care-fact bounded options remain intact.

This is a prerequisite restriction, not care-source completion. No Hub tuple is
added, no annotation is promoted, and the Hub source files and data are untouched.
The current extractor has label/source/applicability checks, but a source-label
match is not independent proof that a note is an instruction or of its subject.
Before its output can enter this bridge, the source contract must establish the
specific method versus property, applicable subject, conditions and provenance;
the Agent must not guess these from a broad type or attribute label. Named-part
care remains unsupported until the canonical goal can bind that same subject.

Regression 1047 passed; 65 new tests cover missing/other scope, order changes,
property-versus-method attributes, retained material, conservative conflicts,
admission projection and the still-closed Hub care mapping. Independent review
found that multi-attribute conflict selection ambiguity could disappear after
direct-subject filtering; six additional red/green cases close that combination
by preserving the conflicting records rather than accepting a narrowed answer.
Frozen native-context
Claim Resolution recomputation is identical before/after: two material records,
one care option, unresolved cleaning. It is not a new native reply, independent
semantic assessment or real-accuracy improvement. See ROADMAP for provenance.

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
