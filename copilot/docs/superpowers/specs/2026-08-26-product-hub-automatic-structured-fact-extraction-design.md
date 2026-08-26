# Product Hub Automatic Structured Fact Extraction Design

## Status

Approved in principle by the user on 2026-08-26. This written specification is
pending final review before implementation planning. It does not enable a
runtime model call, change the formal Agent, write the live Product Hub, or
change delivery authority.

## Problem

Product Hub already owns exact product/SKU identity, approved customer-facing
assets, labels, short asset notes, and the canonical `product_facts` table.
Copilot can read confirmed, non-conflicting Hub facts through the existing exact
bundle adapter and formal Evidence Admission path. The installation vertical
slice proved that this path works when an upstream fact exists.

The remaining gap is upstream materialization. Approved labels and notes often
describe detachability, placement, structure, ordinary care, included items, or
the existence of a certificate, but most of those descriptions are not stored
as structured facts. Labels and notes cannot be passed directly to the runtime
Composer as truth: a label is a media role, free-form notes may combine several
subjects, and neither has an explicit fact scope.

The capability must also remain current. Relabeling an asset, editing a note,
unapproving or deleting an asset, or moving it between a product and SKU must
invalidate affected generated facts without a full-catalog rebuild or a
Copilot restart.

## Goals

- Materialize a narrow set of ordinary product facts from approved Product Hub
  asset notes through a qualified strict-schema offline extractor.
- Keep `product_facts` as the only Hub fact registry and preserve exact product,
  SKU, asset, and extraction provenance. A non-factual operational checkpoint
  may record source hashes and rebuild state, but never fact values.
- Automatically invalidate and incrementally rebuild generated facts after a
  relevant source mutation.
- Preserve the existing formal path:

  ```text
  exact product/SKU identity
  -> Product Hub current confirmed facts
  -> Product Context Pack
  -> Evidence Admission
  -> Claim Resolution
  -> Composer
  -> Deterministic Final / Unified Audit
  -> Supervisor Assist only
  ```

- Improve factual coverage without adding customer-text keyword rules, a new
  Graph node, a second retriever, a second evidence registry, or a runtime model
  call.

## Non-Goals

- No autonomous sending and no change to `can_send`.
- No extraction from customer conversations, historical replies, order data,
  private pricing, or the enterprise-wide semantic database.
- No direct use of arbitrary Enterprise KB chunks as formal evidence.
- No conversion of an image label or media reference into a factual claim.
- No inference of toxicity, child safety, load, medical suitability,
  certification outcome, or other high-risk conclusions.
- No replacement of manual, DingTalk, SKU, or existing installation facts.
- No model-generated product identity, fact UID, source UID, or review status.

## Considered Approaches

### A. Offline strict extraction into existing Product Hub facts (selected)

Read only approved/live notes for one exact Product Hub product, submit bounded
chunks to a strict-schema extractor, validate every output deterministically,
and transactionally replace only facts owned by this extractor.

This keeps the model outside the customer request path, reuses the canonical Hub
fact table and current Copilot admission chain, and supports deterministic
invalidation and rollback.

### B. Add Enterprise KB as another Copilot retriever

Rejected for this phase. Enterprise KB has useful hybrid retrieval, but its
chunks do not carry sufficient per-chunk answer eligibility, review state,
sensitivity, authority, and exact product/SKU scope. Direct admission would make
internal, confidential, and reference material compete with reviewed product
truth.

### C. Send all Product Hub notes to the runtime Composer

Rejected. This increases request latency and token cost, makes source scope
implicit, exposes irrelevant product content to the model, and bypasses the
existing formal evidence contract.

### D. Extract facts with Python/JavaScript keyword matching

Rejected. Product copy varies by category and author. Keyword rules would turn
sample wording into business logic and cannot reliably establish subject,
polarity, or scope.

## Ownership

### Product Hub

- Owns eligible asset selection, source snapshot hashing, strict extraction,
  deterministic validation, conflict handling, invalidation, rebuilding, and
  persistence in `product_facts`.
- Binds product/SKU identity and source asset references. The model never owns
  identity or review status.
- Keeps generated fact media provenance, but does not authorize media delivery.

### Copilot

- Reads exact current facts through the existing read-only Product Hub client.
- Applies a source-specific FactType allowlist before a generated Hub fact can
  become a direct-answer candidate.
- Retains all existing admission, Claim Resolution, reply, audit, Safety, and
  Delivery owners.

### Model

- Proposes zero or more structured fact candidates from already eligible,
  customer-facing notes.
- Cannot publish, confirm, invalidate, merge, send, or invent source references.

## Eligible Source Contract

Only assets satisfying every condition are eligible:

- exact `product_id` exists and the product is active;
- asset status is `approved` or `live`;
- `label_note` is non-empty after whitespace normalization;
- every selected label is an enabled Product Hub registry label;
- optional SKU binding belongs to the same exact product;
- the asset is not deleted, pending, rejected, or cross-product;
- the note is customer-facing product content, not an internal price, order,
  credential, customer identity, or private operational record.

The initial source-label to candidate-type matrix is:

| Candidate FactType | Eligible source labels |
|---|---|
| `detachable` | `产品信息图`, `卖点海报`, `安装说明` |
| `placement_scene` | `使用场景`, `产品信息图`, `卖点海报` |
| `structure_function` | `产品信息图`, `卖点海报`, `安装说明` |
| `cleaning_care` | `产品信息图`, `材质说明`, `卖点海报` |
| `included_items` | `包装清单`, `产品信息图`, `安装说明` |
| `certification_report` | `合格证质检` |

This matrix selects possible source material; it does not prove that a fact is
present. The extractor must return no candidate when the note does not state the
fact or states only an ambiguous, conditional, or negative relationship.

Existing deterministic installation, dimensions, material, color, packaging,
and SKU fact generation remains separate and unchanged.

## Extraction Input

The offline job operates per exact product. It normalizes and deduplicates notes,
then sorts them by registry label, source update time, and stable asset ID.
Large products are split into deterministic bounded chunks; no chunk is created
from customer text or a runtime query.

Each model-visible source receives an anonymous local reference such as
`source_001`. The host retains the mapping to the real asset ID. Input contains:

- schema version;
- allowed FactTypes and scopes;
- anonymous source reference;
- controlled source label;
- normalized customer-facing note;
- anonymous optional SKU reference.

Raw database paths, URLs, credentials, customer/order identifiers, private
pricing, and unrelated product fields are excluded.

## Strict Output Contract

The extractor must call one forced strict function. `json_object`, Markdown
JSON, regex extraction, field guessing, repair prompts, and free-text fallback
are forbidden.

Schema `ProductHubStructuredFactCandidates/v1` contains an array of candidates.
Every candidate has exactly these required fields:

- `fact_type`: enum of the six initial FactTypes;
- `attribute_key`: concise customer-facing attribute name;
- `value`: the stated product fact, preserving polarity and qualifications;
- `unit`: explicit unit or an empty string;
- `scope`: one of `product`, `component`, `accessory`, `included_item`, or
  `packaging`;
- `applies_ref`: an input SKU reference or an empty string;
- `source_refs`: non-empty unique array of input source references;
- `confidence`: number from 0 to 1.

All nested objects set `additionalProperties=false`. The output contains no
product ID, asset ID, fact ID, status, conflict decision, safety verdict,
direct-answer verdict, reply text, or chain of thought.

## Provider Qualification

Provider support is proven, not assumed. The candidate provider must pass a
separate fixed strict-tool qualification before any database write:

- exact schema and required forced tool call;
- positive facts across every allowed type;
- explicit negative statements preserved as negative or omitted, never flipped;
- ambiguous and unsupported notes produce no fact;
- invalid source, SKU, scope, enum, extra field, and citation mutations fail;
- repeated identical input produces semantically identical candidates;
- timeout, truncation, schema error, empty output, and free-text fallback are
  all zero;
- reasoning content is neither persisted nor exposed.

Each qualification attempt is one provider request. Hidden retry, repair, or
model fallback is forbidden. A transport failure leaves the provider
unqualified and performs zero fact writes.

DeepSeek strict tool mode is a candidate transport, not an architectural
dependency. Credentials are read only from an approved untracked runtime source
and injected into the isolated process. No key, full URL, or secret-derived hash
is logged or persisted.

## Deterministic Validation

The host validates every candidate after strict decoding:

1. `source_refs` must exist in the exact request chunk and resolve to eligible
   assets under the same product.
2. `applies_ref` must be empty or resolve to an active SKU under that product.
3. FactType must be allowed for every cited source label.
4. Scope and SKU applicability must be compatible with the FactType and source.
5. Attribute, value, and unit must be non-placeholder, bounded, and free of
   control characters or unprojected identifiers.
6. A candidate cannot assert a stronger polarity or scope than all cited notes.
7. High-risk claim types and service/media actions are rejected.
8. Canonical normalization is used only for deduplication and conflict
   detection; customer-visible values preserve source meaning.
9. Unknown or duplicate references, cross-product references, conflicting
   applicability, and unsupported values fail closed.

Candidates are merged across chunks only after validation. Input order must not
change the final canonical set.

## Persistence And Provenance

No new fact registry is introduced. Valid candidates use the existing
`product_facts` table with:

- `source = ai-structured-label-v1`;
- deterministic fact ID derived from product, FactType, attribute, scope,
  applicability, normalized value, and sorted source asset IDs;
- `source_detail` as canonical compact JSON containing schema version, sorted
  source asset IDs, source snapshot SHA-256, provider/model fingerprint, and
  extraction-contract version;
- `status = confirmed` only after all deterministic validators pass;
- `conflict = 0` only when no incompatible generated or authoritative current
  fact exists.

When two generated candidates for the same product, FactType, attribute, scope,
and applicability have different normalized values, all members of that group
remain `pending` with `conflict=1`. A conflicting generated candidate never
changes an existing manual or deterministic fact.

The write transaction replaces only rows owned by
`ai-structured-label-v1` for the exact product. Manual, DingTalk, SKU,
installation, and other generated sources are preserved.

Reliable zero-result and restart semantics require one small operational state
table. `product_fact_extraction_state` stores only:

- exact `product_id` and extractor source name;
- current eligible-source SHA-256;
- `dirty`, `running`, `ready`, or `error` state;
- extraction-contract version;
- sanitized last error reason code;
- update time.

It stores no fact value, note, model response, customer data, credential, or
reply. It is not queried by Evidence Admission and cannot become product truth.
Its sole purpose is to distinguish a successfully processed product with zero
facts from a product that was never processed or whose rebuild was interrupted.

## Automatic Invalidation And Incremental Rebuild

Automatic refresh is part of the contract, not a later enhancement.

Any mutation to an asset's label, note, approval state, deletion state,
`product_id`, or `sku_id` invalidates generated facts for the old and new product
identities in the same database transaction. Invalidation changes only
`ai-structured-label-v1` rows to `pending` and upserts the operational state as
`dirty`; stale rows are therefore invisible to Copilot immediately. This also
persists work for a newly added product that has no prior generated fact rows.

After commit, the existing Product Hub process places affected product IDs in a
bounded in-memory debounce set. Repeated edits collapse into one product rebuild.
The worker recomputes the complete current eligible source snapshot for that
product, extracts and validates a complete replacement set, then replaces the
source-owned rows in one transaction.

No separate queue service is added. Restart safety comes from the operational
state and source-hash reconciliation:

- every generated set carries a source snapshot hash;
- startup compares current eligible-source hashes with confirmed generated sets;
- `dirty`, `running`, `error`, missing, or hash-mismatched products are queued
  for rebuild;
- a successful extraction that produces zero facts still records `ready` with
  the current source hash;
- model or transport failure leaves facts pending and records only a sanitized
  reason code;
- the next successful run replaces the pending set.

This gives fail-closed current-value behavior without a full-catalog model run,
a second scheduler service, or stale fact reuse.

The first legacy-catalog backfill is never triggered merely by starting Product
Hub. It requires an explicit, cost-authorized bootstrap command after provider
qualification and first runs against a database copy. Once a product has an
operational state, ordinary asset mutations and startup reconciliation keep it
current automatically. Newly ingested eligible assets create a `dirty` state in
their normal write transaction.

## Copilot Admission Boundary

The existing Product Hub exact bundle remains the only adapter. It must retain
the Hub fact source marker in its projection.

For `source=ai-structured-label-v1`, only the initial ordinary FactType allowlist
may become a direct-answer candidate:

- `detachable`;
- `placement_scene`;
- `structure_function`;
- `cleaning_care`;
- `included_items`.

`certification_report` remains blocked from direct answer. It can identify a
reviewed supporting document or media candidate, but it cannot prove a safety,
toxicity, compliance, age, medical, or certification-outcome claim.

Unknown types from this source are rejected even if they are absent from the
existing high-risk blocklist. Existing trusted Hub sources keep their current
behavior; this change does not rewrite their eligibility rules.

All candidates still require exact identity, confirmed/non-conflicting status,
requested FactType compatibility, Evidence Admission, Claim Resolution, and
Final/Audit acceptance. Product Hub confirmation alone is not send authority.

## Media Boundary

Source asset IDs in fact provenance do not attach or promise media. Media remains
a separate non-factual role selected from Product Hub's approved labeled-images
endpoint. A media block may be attached only through the existing role,
identity, usability, channel, Final, and Supervisor Assist contracts.

The extractor cannot turn `certification_report` or any other fact into an
automatic image send. `can_send` remains false in this phase.

## Feature Flags And Rollback

Product Hub extraction and reconciliation are disabled by default through a
source-side worker flag. Copilot admission of `ai-structured-label-v1` is
separately disabled by default through one narrow answer-behavior rollback flag:

`COPILOT_PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED=false`

Disabling the Copilot flag immediately removes this source from generation
without deleting data. Disabling the Product Hub worker stops new extraction
and rebuild work. Existing pending rows remain non-answerable. Rollback requires
no Graph change, database replacement, or service migration.

## Verification

### Product Hub deterministic tests

- eligible label/status/product/SKU selection;
- schema acceptance and every invalid/extra/missing field mutation;
- source-label/FactType matrix enforcement;
- cross-product, cross-SKU, unknown, duplicate, and empty references;
- conflict grouping, stable ordering, deterministic IDs, and repeated rebuild;
- zero-result `ready` checkpoint and first-time product `dirty` persistence;
- manual and every non-owned fact source preserved;
- label, note, approval, deletion, product move, and SKU move invalidation;
- debounce collapse and startup reconciliation after an interrupted rebuild;
- startup does not silently bootstrap the legacy catalog or create unapproved
  provider spend;
- provider failure leaves zero confirmed stale facts;
- no customer, order, private-price, credential, or path leakage.

### Candidate database qualification

- run only against a consistent database copy;
- record eligible product/asset counts, generated types, confirmed/pending and
  conflict counts, source snapshot hash, and protected-table fingerprints;
- require Product, SKU, asset, manual fact, and every non-owned fact fingerprint
  to remain unchanged;
- validate at least ten anonymous exact products spanning all available initial
  FactTypes and both product/SKU scopes;
- reverse and fixed-shuffle source order must produce the same canonical facts.

### Copilot tests

- source marker and provenance survive the read-only adapter;
- allowed generated types can enter the existing Product Context Pack only for
  an exact identity and compatible requested FactType;
- unknown, high-risk, stale, pending, conflicting, mismatched, placeholder, or
  disabled-source facts cannot enter direct answer context;
- `certification_report` remains non-direct and media remains separate;
- API, Copilot context, replay, benchmark, trace, and snapshot use the same
  contract;
- formal knowledge DML and Product Hub writes from Copilot remain zero;
- formal reply, `reply_blocks`, Delivery, and `can_send` remain unchanged while
  the flag is off.

### Quality gates

After deterministic and provider qualification:

1. one anonymous exact-product canary;
2. three products covering a direct fact, an unresolved fact, and a conflict;
3. the comparable reconstructed Fixed-8 once;
4. versioned Synthetic smoke `5/5` and full `22/22` only after smoke passes;
5. the fixed long-conversation set only after exact product identity coverage is
   proven.

Report supported-claim coverage, unresolved preservation, wrong-product facts,
unsupported high-risk claims, media promises, human review, `can_send`, errors,
timeouts, and p50/p95. Synthetic results remain regression evidence;
`real_customer_accuracy` remains `null` without approved real labels.

## Architecture Drift Gate

Implementation is invalid if it adds a Graph node, runtime model call, new
evidence registry, direct Enterprise KB admission, customer-text keyword rule,
reply owner, safety bypass, media promise, delivery path, or automatic-send
authority.

The intended change is limited to:

- one offline Product Hub extraction command plus pure contract/validation code;
- existing Product Hub asset-mutation invalidation, one non-factual extraction
  checkpoint table, and startup reconciliation;
- existing `product_facts` persistence;
- existing Product Hub read projection and Product Context Pack source gate;
- direct tests, an ADR 0010 amendment, and current architecture/module/runbook
  documentation.

## Implementation Boundaries

The historical Product Hub changes in `scripts/label-assets-ai.cjs`,
`src/static.js`, and `public-v2/dept-card.html` are unrelated and must not be
overwritten, reverted, or committed.

The Copilot historical generated/frontend changes are also excluded. No live
database, output report, credential file, `.env`, cache, model, or frontend
build artifact may be committed.
