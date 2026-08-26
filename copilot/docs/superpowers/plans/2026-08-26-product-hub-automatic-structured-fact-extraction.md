# Product Hub Automatic Structured Fact Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert approved Product Hub asset notes into deterministic, source-owned structured facts offline, keep them fresh after asset edits, and admit only a narrow low-risk subset through the existing Copilot evidence path.

**Architecture:** Product Hub remains the sole owner of source selection, strict extraction, validation, invalidation, and persistence in its existing `product_facts` registry. Copilot continues to read one exact product bundle and adds only a source-specific default-off gate inside the existing Product Context Pack; the Graph, Composer, Final, Safety, Delivery, and `can_send` contracts are unchanged.

**Tech Stack:** Node.js 24 built-in `node:sqlite`, native `fetch`, strict OpenAI-compatible tool calling, SHA-256 canonical JSON, Python 3, pytest, existing Product Data Hub read adapter, existing Product Context Pack and benchmark runners.

**Spec:** `docs/superpowers/specs/2026-08-26-product-hub-automatic-structured-fact-extraction-design.md`

## Global Constraints

- Active product priority remains `P1 Gold Conversation Quality`; this work supplies formal facts and does not add reply wording rules.
- Product Hub extraction is offline and disabled by default with `PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED=false`.
- Copilot admission is independently disabled by default with `COPILOT_PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED=false`.
- The only fact registry is Product Hub `product_facts`; `product_fact_extraction_state` is operational state and is never queried as evidence.
- The initial generated source is exactly `ai-structured-label-v1`.
- Direct-answer types for that source are exactly `detachable`, `placement_scene`, `structure_function`, `cleaning_care`, and `included_items`.
- `certification_report` remains non-direct and cannot prove safety, toxicity, compliance, age, medical suitability, or certification outcome.
- Existing deterministic installation, dimensions, material, color, packaging, SKU, DingTalk, and manual fact generation is unchanged.
- No customer conversation, order, price, credential, path, URL, historical reply, chain of thought, or unrelated product content enters extraction input or persisted provenance.
- Strict forced tool calling is mandatory. `json_object`, Markdown JSON, regex extraction, repair prompts, hidden retries, and free-text fallback are forbidden.
- No Graph node, runtime model call, second Pipeline, second evidence registry, reply owner, Router, Planner, retry, repair, fallback, media promise, Delivery condition, or automatic-send authority is added.
- `can_send` remains false and `requires_human_review` remains true for Supervisor Assist.
- Product Hub historical changes in `scripts/label-assets-ai.cjs`, `src/static.js`, and `public-v2/dept-card.html` must not be modified, staged, reverted, or committed.
- Copilot historical changes in `frontend/components.d.ts`, `web/static/kb-admin/index.html`, `.gitattributes`, and `frontend/node_modules.locked-backup/` must not be modified, staged, reverted, or committed.
- No live database, copied database, report output, `.env`, credential, cache, model, or frontend build artifact may be committed.
- Product Hub has no configured remote at plan time. Commit its work locally; do not invent or push to a remote without explicit authorization.

---

## File And Responsibility Map

### Product Hub repository

Repository root: `D:\codex\intranet-product-data-hub-v2.1`

- Create `src/services/structuredFactSource.js`: select eligible approved/live asset notes, anonymize source/SKU references, chunk deterministically, and compute source hashes.
- Create `src/services/structuredFactContract.js`: own the forced-tool schema, strict decoding, deterministic validation, deduplication, conflict grouping, fact IDs, and canonical provenance.
- Create `src/services/structuredFactProvider.js`: make exactly one strict transport request per chunk and expose sanitized attempt diagnostics.
- Create `src/services/structuredFactRefresh.js`: own the bounded in-process debounce set, state reconciliation, per-product rebuild, and fail-closed error transition.
- Create `scripts/extract-product-facts-ai.cjs`: expose explicit `qualify`, `rebuild`, and cost-authorized `bootstrap` commands without changing service startup semantics.
- Modify `lib/db.js`: add the operational state table and atomic source-owned dirty/replace methods; connect qualifying asset mutations to same-transaction invalidation.
- Modify `src/config.js`: parse default-off extractor settings without printing credentials.
- Modify `src/context.js`: construct one refresh coordinator and attach the post-commit dirty listener.
- Modify `server.js`: start reconciliation only when the default-off worker flag is enabled; never bootstrap the legacy catalog.
- Create focused Node tests under `tests/structured-fact-*.test.js`.
- Modify `README.md` and `docs/项目推进手册.md`: document qualification, explicit bootstrap, rollback, and state semantics.

### Copilot repository

Repository root: `D:\桌面文件\客服\.codex-runtime\p1-service-action-context-verify-f1c2f34\worktree\copilot`

- Modify `app/config.py`: add the independent default-off generated-fact admission flag.
- Modify `app/services/product_context_pack_service.py`: fetch a bundle when either existing Hub media delivery or generated-fact admission requires it, preserve source provenance, and apply the exact source-specific allowlist.
- Test `app/integrations/product_data_hub/read_client.py` without broadening it: its current `product_data_hub:<source>` projection is the canonical source marker.
- Extend `tests/test_product_data_hub_read_client.py`, `tests/test_product_context_pack_service.py`, `tests/test_admitted_answer_context_service.py`, and `tests/test_analysis_pipeline_entrypoints.py`.
- Amend `docs/adr/0010-exact-product-hub-fact-and-media-projection.md`, `docs/architecture-overview.md`, `docs/module-index.md`, `docs/runtime-operation.md`, `docs/agent-core-priority-plan.md`, and `docs/index.md` only after behavior is verified.

---

### Task 1: Create Isolated Execution Worktrees And Freeze Baselines

**Files:**
- No production file changes.
- Record runtime-only baseline data under ignored `.codex-runtime` directories.

**Interfaces:**
- Consumes: Product Hub HEAD `361bea44436ddcb7127d61122c00fa93958f31e2` and Copilot HEAD `6495c06a6d73624421ec514b238bb9811c657153`.
- Produces: two isolated branches whose source trees exclude the unrelated dirty files listed in Global Constraints.

- [ ] **Step 1: Load the isolation skill before creating worktrees**

Read `superpowers:using-git-worktrees` and follow its directory and safety checks. Do not create either worktree by guessing a path before the skill check completes.

- [ ] **Step 2: Verify both source repositories before isolation**

Run:

```powershell
git -C 'D:\codex\intranet-product-data-hub-v2.1' status --short
git -C 'D:\codex\intranet-product-data-hub-v2.1' rev-parse HEAD
git -C 'D:\桌面文件\客服\.codex-runtime\p1-service-action-context-verify-f1c2f34\worktree\copilot' status --short
git -C 'D:\桌面文件\客服\.codex-runtime\p1-service-action-context-verify-f1c2f34\worktree\copilot' rev-parse HEAD
```

Expected: the two HEAD values above; only the explicitly listed historical files are dirty.

- [ ] **Step 3: Create feature branches in isolated worktrees**

Use the worktree skill to create:

```text
Product Hub branch: codex/product-hub-structured-facts
Copilot branch: codex/p1-product-hub-structured-facts
```

Expected: both new worktrees are clean and based on the frozen HEADs. The original dirty repositories remain byte-for-byte unchanged.

- [ ] **Step 4: Run baseline tests before edits**

Product Hub:

```powershell
node --test --import .\tests\test-env.js .\tests\product-fact-builder.test.js .\tests\asset-move.test.js .\tests\auth-contract.test.js
```

Copilot:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_data_hub_read_client.py tests\test_product_context_pack_service.py tests\test_admitted_answer_context_service.py -q
```

Expected: PASS. Record exact counts and elapsed time in the execution ledger; do not write reports into Git-tracked paths.

---

### Task 2: Deterministic Eligible Source Snapshot

**Files:**
- Create: `src/services/structuredFactSource.js`
- Create: `tests/structured-fact-source.test.js`

**Interfaces:**
- Consumes: `buildProductFactSourceSnapshot({ product, skus, assets, enabledLabels, maxChunkChars })` input objects from Product Hub DB reads.
- Produces: `{ schemaVersion, productRef, sourceHash, sources, chunks, sourceMap, skuMap }`, where model-visible refs are anonymous and ordering is stable.

- [ ] **Step 1: Write failing selection and ordering tests**

Add tests with this contract shape:

```javascript
const snapshot = buildProductFactSourceSnapshot({
  product: { id: "product-a", status: "active" },
  skus: [{ id: "sku-a", productId: "product-a", status: "active" }],
  enabledLabels: ["产品信息图", "卖点海报"],
  assets: [
    { id: "asset-b", productId: "product-a", skuId: null, status: "live", labels: ["卖点海报"], labelNote: "可拆分收纳", updatedAt: "2026-08-26T02:00:00Z" },
    { id: "asset-a", productId: "product-a", skuId: "sku-a", status: "approved", labels: ["产品信息图"], labelNote: "适合卧室摆放", updatedAt: "2026-08-26T01:00:00Z" },
  ],
  maxChunkChars: 4000,
});
assert.deepEqual(snapshot.sources.map((row) => row.source_ref), ["source_001", "source_002"]);
assert.equal(snapshot.sources[0].note, "适合卧室摆放");
assert.match(snapshot.sourceHash, /^[0-9a-f]{64}$/);
assert.equal(JSON.stringify(snapshot.modelInput).includes("product-a"), false);
```

Also cover pending/rejected assets, empty notes, disabled labels, cross-product SKU bindings, duplicate normalized notes, private-price/order-like metadata fields, reverse input order, and fixed-shuffle input order.

- [ ] **Step 2: Run the source tests and verify the expected failure**

Run:

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-source.test.js
```

Expected: FAIL with `MODULE_NOT_FOUND` for `structuredFactSource.js`.

- [ ] **Step 3: Implement closed source selection**

Implement and export these exact symbols:

```javascript
const STRUCTURED_FACT_SOURCE_SCHEMA_VERSION = "ProductHubStructuredFactSource/v1";
const INITIAL_SOURCE_LABEL_MATRIX = Object.freeze({
  detachable: Object.freeze(["产品信息图", "卖点海报", "安装说明"]),
  placement_scene: Object.freeze(["使用场景", "产品信息图", "卖点海报"]),
  structure_function: Object.freeze(["产品信息图", "卖点海报", "安装说明"]),
  cleaning_care: Object.freeze(["产品信息图", "材质说明", "卖点海报"]),
  included_items: Object.freeze(["包装清单", "产品信息图", "安装说明"]),
  certification_report: Object.freeze(["合格证质检"]),
});

function buildProductFactSourceSnapshot({ product, skus, assets, enabledLabels, maxChunkChars = 12000 }) {
  // Return only anonymous refs, controlled labels, normalized notes, and anonymous SKU refs.
}

module.exports = {
  STRUCTURED_FACT_SOURCE_SCHEMA_VERSION,
  INITIAL_SOURCE_LABEL_MATRIX,
  buildProductFactSourceSnapshot,
};
```

Canonical hash input must be UTF-8 JSON with recursively sorted object keys and stable array order. `modelInput`, `sources`, and `chunks` contain anonymous refs only. Keep the real asset/SKU mapping only in host-side `sourceMap` and `skuMap`; neither mapping is serialized into provider messages.

- [ ] **Step 4: Verify determinism and privacy**

Run the test once with normal order and once with `assets.reverse()`. Expected: identical `sourceHash`, model-visible sources, and chunks.

- [ ] **Step 5: Commit the source contract**

```powershell
git add src/services/structuredFactSource.js tests/structured-fact-source.test.js
git commit -m "feat: define structured fact source snapshots"
```

---

### Task 3: Strict Candidate Schema, Validation, And Canonical Facts

**Files:**
- Create: `src/services/structuredFactContract.js`
- Create: `tests/structured-fact-contract.test.js`

**Interfaces:**
- Consumes: one Task 2 chunk plus a provider tool call.
- Produces: `STRUCTURED_FACT_TOOL`, `decodeStrictFactToolCall(response)`, `validateFactCandidates({ envelope, snapshot })`, and `canonicalizeValidatedFacts({ productId, sourceHash, providerIdentity, contractVersion, candidates })`.

- [ ] **Step 1: Write failing strict-schema and mutation tests**

Use this valid envelope as the positive fixture:

```javascript
const envelope = {
  candidates: [{
    fact_type: "detachable",
    attribute_key: "可拆卸结构",
    value: "层板可拆卸",
    unit: "",
    scope: "component",
    applies_ref: "",
    source_refs: ["source_001"],
    confidence: 0.96,
  }],
};
```

Create one mutation per forbidden condition: missing field, extra field, bad enum, unknown/duplicate source ref, unknown SKU ref, empty source list, disallowed source-label/type pair, cross-product source, stronger polarity, control character, identifier leakage, service action, media action, high-risk assertion, unsupported value, and conflicting applicability.

- [ ] **Step 2: Run the contract tests and verify failure**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-contract.test.js
```

Expected: FAIL with `MODULE_NOT_FOUND`.

- [ ] **Step 3: Define the exact forced-tool schema**

Export a tool named `submit_product_hub_fact_candidates` with `strict: true`. Its parameters must require `candidates`; every candidate must require all eight fields; every object must set `additionalProperties: false`; all enums must be closed to the values in the approved spec.

Strict decoding must accept only this transport shape:

```javascript
function decodeStrictFactToolCall(response) {
  const calls = response?.choices?.[0]?.message?.tool_calls;
  if (!Array.isArray(calls) || calls.length !== 1) throw contractError("tool_call_count_invalid");
  const fn = calls[0]?.function;
  if (fn?.name !== "submit_product_hub_fact_candidates") throw contractError("tool_name_invalid");
  if (typeof fn.arguments !== "string") throw contractError("tool_arguments_missing");
  const envelope = JSON.parse(fn.arguments);
  assertExactEnvelope(envelope);
  return envelope;
}
```

Do not inspect `message.content`, remove code fences, run a regex, infer missing fields, or issue another model request.

- [ ] **Step 4: Implement deterministic validation and conflict grouping**

Use these exact canonical keys:

```javascript
const ownershipKey = ({ factType, attributeKey, scope, applies }) =>
  [factType, attributeKey, scope, applies].map(normalizeContractText).join("\u001f");

const deterministicFactId = ({ productId, factType, attributeKey, scope, applies, value, sourceAssetIds }) =>
  `ai-structured-label-v1:${sha256Hex(canonicalJson({
    productId, factType, attributeKey, scope, applies, value,
    sourceAssetIds: [...sourceAssetIds].sort(),
  }))}`;

const sourceDetail = canonicalJson({
  schema_version: "ProductHubStructuredFactProvenance/v1",
  source_asset_ids: [...sourceAssetIds].sort(),
  source_snapshot_sha256: sourceHash,
  provider_host_fingerprint: providerIdentity.hostFingerprint,
  provider_model: providerIdentity.model,
  extraction_contract_version: contractVersion,
});
```

For one ownership key with multiple normalized values, emit all members as `status="pending"` and `conflict=true`. Otherwise emit `status="confirmed"` and `conflict=false`. Canonical output ordering is by ownership key, normalized value, then deterministic ID.

- [ ] **Step 5: Verify all mutations fail closed and ordering is stable**

Run:

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-contract.test.js
```

Expected: PASS; every invalid mutation returns a sanitized reason code and zero canonical facts.

- [ ] **Step 6: Commit the strict contract**

```powershell
git add src/services/structuredFactContract.js tests/structured-fact-contract.test.js
git commit -m "feat: validate strict structured fact candidates"
```

---

### Task 4: Operational State And Atomic Source-Owned Persistence

**Files:**
- Modify: `lib/db.js`
- Create: `tests/structured-fact-persistence.test.js`

**Interfaces:**
- Consumes: canonical facts from Task 3.
- Produces: `hub.getStructuredFactSourceInput`, `hub.getProductFactExtractionState`, `hub.listProductFactExtractionStates`, `hub.listStructuredFactProductIds`, `hub.markStructuredFactsRunning`, `hub.markStructuredFactsError`, `hub.markStructuredFactsDirty`, and `hub.replaceStructuredFacts`.

- [ ] **Step 1: Write failing migration and persistence tests**

Assert that a fresh DB contains:

```sql
CREATE TABLE product_fact_extraction_state (
  product_id TEXT NOT NULL,
  source TEXT NOT NULL,
  source_hash TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL,
  contract_version TEXT NOT NULL,
  last_error_code TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (product_id, source)
)
```

Test `getStructuredFactSourceInput(productId)` returns all matching assets without pagination and only the narrow source fields (`id`, `productId`, `skuId`, `status`, `labels`, `labelNote`, `updatedAt`) plus active product/SKU identity and enabled labels. Also test ready-with-zero-facts, source-owned replacement, manual/DingTalk/SKU/installation preservation, rollback on an invalid row, deterministic repeated replacement, and source-specific list operations.

- [ ] **Step 2: Run the persistence test and verify failure**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-persistence.test.js
```

Expected: FAIL because the state table and methods do not exist.

- [ ] **Step 3: Add an internal synchronous transaction helper**

Implement this exact behavior inside `lib/db.js`:

```javascript
function withImmediateTransaction(db, operation) {
  db.exec("BEGIN IMMEDIATE");
  try {
    const result = operation();
    db.exec("COMMIT");
    return result;
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}
```

Do not expose raw SQL or a second persistence layer.

- [ ] **Step 4: Implement source-owned state transitions**

Use exact source `ai-structured-label-v1` by default. `replaceStructuredFacts` must, in one transaction:

1. verify every row belongs to the exact `productId` and source;
2. delete only that source's rows for that product;
3. insert the canonical replacement rows;
4. upsert `state="ready"`, the exact source hash, contract version, and empty error code.

Create one private `markStructuredFactsDirtyRows(productIds, source, now)` helper that assumes the caller already owns a transaction. Public `markStructuredFactsDirty` wraps that helper in `withImmediateTransaction`; asset mutators in Task 5 call the private helper from their existing transaction so nested transactions cannot occur. The helper sets only source-owned rows to `pending` and upserts `state="dirty"`. `markStructuredFactsError` leaves rows non-confirmed and stores only an allowlisted reason code.

- [ ] **Step 5: Run persistence plus existing fact-builder tests**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-persistence.test.js .\tests\product-fact-builder.test.js
```

Expected: PASS and existing deterministic generators remain unchanged.

- [ ] **Step 6: Commit the persistence contract**

```powershell
git add lib/db.js tests/structured-fact-persistence.test.js
git commit -m "feat: persist structured fact extraction state"
```

---

### Task 5: Same-Transaction Asset Invalidation

**Files:**
- Modify: `lib/db.js`
- Create: `tests/structured-fact-invalidation.test.js`
- Test: `tests/asset-move.test.js`
- Test: `tests/auth-contract.test.js`

**Interfaces:**
- Consumes: asset mutations already owned by `createHub(db)`.
- Produces: immediate pending facts plus dirty state in the same transaction, followed by `hub.setStructuredFactDirtyListener(listener)` notification only after commit.

- [ ] **Step 1: Write failing mutation matrix tests**

For each mutator below, seed one confirmed generated fact and one manual fact, apply the mutation, then assert generated=`pending`, manual unchanged, state=`dirty`:

```text
insertAsset
setAssetStatus
bindAssetSku
moveAssetProduct (old and new product IDs)
setAssetLabel (label, label_note, spec_ref)
deleteAsset
```

Also assert a failed DB mutation fires no listener, repeated edits collapse duplicate product IDs in the listener payload, and `updateAssetType`/`renameAsset` do not invalidate because they do not change the approved source contract.

- [ ] **Step 2: Run tests and confirm stale facts remain confirmed before the fix**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-invalidation.test.js
```

Expected: FAIL on the first stale confirmed fact assertion.

- [ ] **Step 3: Wrap each qualifying mutation with atomic invalidation**

Inside `createHub`, add one private `invalidateStructuredFacts(productIds)` helper and one listener setter:

```javascript
let structuredFactDirtyListener = () => {};

function notifyStructuredFactDirty(productIds) {
  const unique = [...new Set(productIds.filter(Boolean))].sort();
  if (unique.length) structuredFactDirtyListener(unique);
}
```

Each mutator must read old identity before mutation, perform the asset change plus private `markStructuredFactsDirtyRows` in one `BEGIN IMMEDIATE` transaction, commit, then call `notifyStructuredFactDirty`. Do not call the public transaction-opening method or the listener from inside the transaction.

- [ ] **Step 4: Verify all mutations and existing routes**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-invalidation.test.js .\tests\asset-move.test.js .\tests\auth-contract.test.js
```

Expected: PASS; auth and route responses are unchanged.

- [ ] **Step 5: Commit invalidation**

```powershell
git add lib/db.js tests/structured-fact-invalidation.test.js
git commit -m "feat: invalidate generated facts with asset changes"
```

---

### Task 6: Strict Provider Transport And Qualification Gate

**Files:**
- Create: `src/services/structuredFactProvider.js`
- Create: `scripts/extract-product-facts-ai.cjs`
- Modify: `src/config.js`
- Create: `tests/structured-fact-provider.test.js`
- Create: `tests/structured-fact-provider-qualification.test.js`

**Interfaces:**
- Consumes: Task 2 chunks and Task 3 `STRUCTURED_FACT_TOOL`.
- Produces: `createStructuredFactProvider(config)`, `qualifyStructuredFactProvider({ provider, cases })`, `writeQualificationReport(path, report)`, and `loadQualifiedProviderReport({ path, providerIdentity })`.

- [ ] **Step 1: Write failing fake-transport tests**

Use a local fake `fetchImpl` and assert the request includes:

```javascript
{
  stream: false,
  tools: [STRUCTURED_FACT_TOOL],
  tool_choice: {
    type: "function",
    function: { name: "submit_product_hub_fact_candidates" },
  },
}
```

Assert one call per attempt, no retry after timeout/429/500/truncation/schema failure, no content fallback, no credential/base URL in reports, and `latency_ms=null` for failed attempts.

- [ ] **Step 2: Run tests and verify failure**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-provider.test.js .\tests\structured-fact-provider-qualification.test.js
```

Expected: FAIL because provider symbols are missing.

- [ ] **Step 3: Add exact default-off configuration**

Extend `loadConfig()` with:

```javascript
aiStructuredFactsEnabled: /^(1|true|yes|on)$/i.test(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED || "false"),
aiStructuredFactsApiBase: String(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_API_BASE || "").trim(),
aiStructuredFactsApiKey: String(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_API_KEY || ""),
aiStructuredFactsModel: String(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_MODEL || "").trim(),
aiStructuredFactsQualificationReport: String(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_QUALIFICATION_REPORT || "").trim(),
aiStructuredFactsTimeoutMs: Number(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_TIMEOUT_MS || 30000),
aiStructuredFactsDebounceMs: Number(process.env.PRODUCT_HUB_AI_STRUCTURED_FACTS_DEBOUNCE_MS || 750),
```

No route or health response may serialize the key or full base URL.

- [ ] **Step 4: Implement one-attempt strict transport**

Normalize the endpoint with `new URL("chat/completions", apiBaseWithTrailingSlash)`. Reject a non-HTTP(S) URL, missing host, userinfo, query, fragment, key, or model. Send one request with `AbortSignal.timeout(timeoutMs)`, decode only the forced tool call through Task 3, and return sanitized identity `{ hostFingerprint, model, configured }`.

- [ ] **Step 5: Implement the fixed qualification matrix**

The matrix must cover all six candidate types, negative polarity, ambiguous/no-fact input, invalid citation, SKU/scope mutation, extra field, repeated identical inputs, timeout, truncation, schema failure, and free-text response. Qualification is `qualified` only when positive, negative, schema, citation, and repeat-stability rates are 100% and all infrastructure error counts are zero.

The report schema must contain only model name, host fingerprint, contract version, case/attempt counts, p50/p95 successful latency, error counts, semantic hashes, and `qualified`; it must never contain source notes, provider output, URL, or credentials.

`loadQualifiedProviderReport` must recalculate the report SHA-256, require `qualified=true`, and require exact provider host fingerprint, model, and contract version equality. It returns only `{ reportSha256, providerIdentity, contractVersion }`; mismatch fails before a source snapshot or provider request is created.

- [ ] **Step 6: Wire the explicit `qualify` command**

```powershell
node scripts\extract-product-facts-ai.cjs qualify --output D:\桌面文件\客服\.codex-runtime\structured-facts\provider-qualification.json
```

Expected without a configured provider: exit code `2`, `qualified=false`, zero DB writes. Expected with an approved credential injected only into this process: qualification runs once and produces a parseable report.

- [ ] **Step 7: Run tests and commit**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-provider.test.js .\tests\structured-fact-provider-qualification.test.js
git add src/config.js src/services/structuredFactProvider.js scripts/extract-product-facts-ai.cjs tests/structured-fact-provider.test.js tests/structured-fact-provider-qualification.test.js
git commit -m "feat: qualify strict structured fact provider"
```

---

### Task 7: Bounded Refresh Coordinator, Reconciliation, And Explicit Bootstrap

**Files:**
- Create: `src/services/structuredFactRefresh.js`
- Modify: `src/context.js`
- Modify: `server.js`
- Modify: `scripts/extract-product-facts-ai.cjs`
- Create: `tests/structured-fact-refresh.test.js`
- Create: `tests/structured-fact-startup.test.js`

**Interfaces:**
- Consumes: Task 4 DB state, Task 5 dirty notifications, Task 2 snapshots, Task 6 provider, and Task 3 canonical facts.
- Produces: `createStructuredFactRefreshCoordinator({ config, hub, provider, clock, setTimer, clearTimer })` with `enqueue`, `start`, `drain`, `reconcile`, and `stop`.

- [ ] **Step 1: Write failing coordinator tests**

Cover:

```text
flag off -> no provider call and no state mutation
qualification missing/mismatched -> no provider call
ten repeated edits -> one product rebuild
two product IDs -> deterministic sorted processing
successful zero facts -> ready with current source hash
provider error -> generated rows pending and state error
interrupted running state -> queued by reconciliation
hash mismatch -> queued
ready matching hash -> skipped
startup with products lacking state -> no legacy bootstrap
newly inserted eligible asset -> dirty and queued
```

- [ ] **Step 2: Run tests and verify failure**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-refresh.test.js .\tests\structured-fact-startup.test.js
```

Expected: FAIL with the coordinator module missing.

- [ ] **Step 3: Implement bounded queue semantics**

Use a `Set` capped at 1000 product IDs. When capacity is reached, leave excess products `dirty` in SQLite; after each drain, refill from `hub.listProductFactExtractionStates({ state: "dirty", limit: 1000 })`. This preserves work without adding a queue service.

The per-product sequence is exact. `hub.getStructuredFactSourceInput` must run before `buildProductFactSourceSnapshot`; the qualified report must be loaded before the first provider request:

```javascript
const sourceInput = hub.getStructuredFactSourceInput(productId);
const snapshot = buildProductFactSourceSnapshot(sourceInput);
loadQualifiedProviderReport({ path: config.aiStructuredFactsQualificationReport, providerIdentity });
hub.markStructuredFactsRunning(productId, snapshot.sourceHash, contractVersion);
const envelopes = await extractEveryChunkOnce(snapshot.chunks);
const candidates = envelopes.flatMap((envelope) =>
  validateFactCandidates({ envelope, snapshot })
);
const facts = canonicalizeValidatedFacts({
  productId,
  sourceHash: snapshot.sourceHash,
  providerIdentity,
  contractVersion,
  candidates,
});
hub.replaceStructuredFacts({ productId, sourceHash: snapshot.sourceHash, contractVersion, facts });
```

On any failure, call `hub.markStructuredFactsError(productId, allowlistedReasonCode)` and make no further provider call.

- [ ] **Step 4: Wire context and startup without catalog bootstrap**

`createContext(config)` creates one coordinator, registers `hub.setStructuredFactDirtyListener(ids => coordinator.enqueue(ids))`, and returns it on `ctx`. `server.js` calls `ctx.structuredFactRefresh.start()` only after listen and only when enabled. `start()` reconciles only existing state rows and products already carrying `ai-structured-label-v1` rows.

- [ ] **Step 5: Add explicit rebuild and bootstrap CLI modes**

Commands must require explicit provider cost authorization:

```powershell
node scripts\extract-product-facts-ai.cjs rebuild --product-id product-uuid --allow-provider-cost
node scripts\extract-product-facts-ai.cjs bootstrap --all-products --allow-provider-cost
```

Without `--allow-provider-cost`, exit `2` before provider creation. `bootstrap --all-products` must never be called from `server.js`; its first qualification run must use `HUB_DB` pointing to a consistent copied database.

- [ ] **Step 6: Verify startup and failure behavior**

```powershell
node --test --import .\tests\test-env.js .\tests\structured-fact-source.test.js .\tests\structured-fact-contract.test.js .\tests\structured-fact-persistence.test.js .\tests\structured-fact-invalidation.test.js .\tests\structured-fact-provider.test.js .\tests\structured-fact-provider-qualification.test.js .\tests\structured-fact-refresh.test.js .\tests\structured-fact-startup.test.js
```

Expected: PASS with provider call count zero in every flag-off/startup-no-bootstrap test.

- [ ] **Step 7: Commit refresh coordination**

```powershell
git add src/context.js server.js src/services/structuredFactRefresh.js scripts/extract-product-facts-ai.cjs tests/structured-fact-refresh.test.js tests/structured-fact-startup.test.js
git commit -m "feat: refresh structured facts after source changes"
```

---

### Task 8: Copilot Source-Specific Admission Gate

**Files:**
- Modify: `app/config.py`
- Modify: `app/services/product_context_pack_service.py`
- Test: `tests/test_product_data_hub_read_client.py`
- Modify: `tests/test_product_context_pack_service.py`
- Modify: `tests/test_admitted_answer_context_service.py`
- Modify: `tests/test_analysis_pipeline_entrypoints.py`

**Interfaces:**
- Consumes: exact Hub fact projection with `source="product_data_hub:ai-structured-label-v1"`.
- Produces: ordinary fact candidates in the existing Product Context Pack only when the new source flag is enabled and the requested FactType is compatible.

- [ ] **Step 1: Write failing flag and source matrix tests**

Test these rows independently:

```python
AI_DIRECT_TYPES = {
    "detachable",
    "placement_scene",
    "structure_function",
    "cleaning_care",
    "included_items",
}
```

For the generated source, each allowed type must enter only for exact product/SKU identity, confirmed status, no conflict, non-empty value, and a compatible requested claim. Unknown types, `certification_report`, all existing high-risk types, pending/conflicting rows, wrong SKU/product, and flag-off rows must not enter direct context. Existing trusted sources must behave identically before and after the change.

- [ ] **Step 2: Run the focused tests and verify expected failures**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_data_hub_read_client.py tests\test_product_context_pack_service.py -q
```

Expected: new generated-source cases fail because only the existing multimodal flag can fetch/admit a bundle.

- [ ] **Step 3: Add the independent Copilot flag**

```python
COPILOT_PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED = _env_bool(
    "COPILOT_PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED", False
)
```

- [ ] **Step 4: Separate bundle fetching from per-source eligibility**

In `build_product_context_pack` compute:

```python
hub_multimodal_enabled = bool(config.COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED)
hub_ai_structured_enabled = bool(config.COPILOT_PRODUCT_HUB_AI_STRUCTURED_FACTS_ENABLED)
hub_bundle_enabled = hub_multimodal_enabled or hub_ai_structured_enabled
catalog_lookup = lookup_product_data_hub_bundle if hub_bundle_enabled else lookup_product_data_hub_reference
```

Pass both booleans into `_hub_bundle_facts_for_query`. Existing sources require `hub_multimodal_enabled`; exact generated source requires `hub_ai_structured_enabled` and membership in `AI_DIRECT_TYPES`. Media projection continues to require only the existing multimodal flag.

- [ ] **Step 5: Preserve source provenance in the existing fact channel**

Add `product_hub_fact_source` to candidate metadata and copy the exact projected source string. Keep `source_type="product_facts"`, `protocol_source_type="product_data_hub"`, and `source_table="product_data_hub"`; do not introduce another evidence channel.

- [ ] **Step 6: Verify admission, Final, and flag-off behavior**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_data_hub_read_client.py tests\test_product_context_pack_service.py tests\test_admitted_answer_context_service.py tests\test_analysis_pipeline_entrypoints.py -q
```

Expected: PASS; flag off preserves current formal reply, `reply_blocks`, `can_send`, and Delivery fields.

- [ ] **Step 7: Commit Copilot admission**

```powershell
git add app/config.py app/services/product_context_pack_service.py tests/test_product_data_hub_read_client.py tests/test_product_context_pack_service.py tests/test_admitted_answer_context_service.py tests/test_analysis_pipeline_entrypoints.py
git commit -m "feat: admit approved Product Hub generated facts"
```

---

### Task 9: Database-Copy Qualification And End-To-End Safety Gates

**Files:**
- No committed data or reports.
- Runtime outputs: `D:\桌面文件\客服\.codex-runtime\structured-facts\` only.

**Interfaces:**
- Consumes: committed Product Hub and Copilot feature branches, an approved strict-provider credential in process memory, an SQLite Product Hub backup, and the existing versioned benchmark fixture.
- Produces: privacy-safe provider, database, canary, Fixed-8, and synthetic benchmark reports that are excluded from Git.

- [ ] **Step 1: Create a consistent Product Hub database copy**

Use SQLite backup API or Product Hub's existing safe backup procedure. Store the copy under:

```text
D:\桌面文件\客服\.codex-runtime\structured-facts\hub-candidate.db
```

Record pre-run HMAC/SHA fingerprints and row counts for `products`, `skus`, `assets`, and `product_facts` grouped by source. Never print field values.

- [ ] **Step 2: Run real provider qualification before any fact write**

Inject the approved key into this process only and run:

```powershell
node scripts\extract-product-facts-ai.cjs qualify --output D:\桌面文件\客服\.codex-runtime\structured-facts\provider-qualification.json
```

Expected: `qualified=true`, all semantic/schema/citation/stability rates 100%, timeout/truncation/schema/free-text counts zero. Otherwise stop this task with zero fact writes and keep both feature flags off.

- [ ] **Step 3: Run one exact-product canary on the DB copy**

Set `HUB_DB` to the copied DB and run one anonymous product ID:

```powershell
node scripts\extract-product-facts-ai.cjs rebuild --product-id $env:PRODUCT_HUB_CANARY_PRODUCT_ID --allow-provider-cost
```

Expected: source hash is stable, only `ai-structured-label-v1` rows and operational state change, protected table fingerprints remain identical, and every generated fact cites eligible current assets.

- [ ] **Step 4: Run the three-product gate**

Select deterministically from the copied DB: one product with an allowed direct fact, one whose eligible notes produce zero facts, and one with contradictory candidate values. Run each once. Expected: confirmed fact, ready-zero state, and pending conflict group respectively; no cross-product/SKU fact and no stale confirmed row.

- [ ] **Step 5: Run ten-product order invariance**

Run at least ten anonymous exact products spanning all available initial FactTypes and both product/SKU scope. Replay source order normal, reverse, and fixed shuffle through the pure source/contract path without extra provider calls. Expected: canonical fact hashes are identical for all three orders.

- [ ] **Step 6: Run Copilot exact-product integration with both flags isolated**

Start an isolated Copilot candidate against a query-only knowledge DB and the copied Product Hub API. Verify these configurations independently:

```text
generated flag OFF, multimodal flag unchanged -> current behavior byte-compatible
generated flag ON, multimodal flag OFF -> generated low-risk facts only, no Hub media
generated flag ON, multimodal flag ON -> same fact behavior plus existing separately gated media candidates
```

Expected for every request: `can_send=false`, `requires_human_review=true`, Product Hub HTTP writes zero, formal knowledge DML zero.

- [ ] **Step 7: Run reconstructed Fixed-8 once**

Preflight the frozen dataset/manifest hashes and the exact runtime commit/source hash. Run `scripts/run_p1_gold_conversation_baseline.py` once with the existing Fixed-8 dataset, current candidate `/api/analyze`, explicit query-only DB snapshot, expected commit/hash/model, DML diagnostics, and ignored output directory.

Expected gate: no wrong-product fact, no unsupported high-risk assertion, no media promise, no `can_send` increase, supported facts retain evidence UID/source provenance, and unresolved claims remain unresolved. Record business-quality scores honestly; do not rerun for generation variance.

- [ ] **Step 8: Run versioned synthetic benchmark smoke then full**

Initialize an isolated benchmark DB:

```powershell
.\.venv\Scripts\python.exe scripts\init_agent_benchmark_fixture_db.py --fixture tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.json --manifest tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.manifest.json --output-db D:\桌面文件\客服\.codex-runtime\structured-facts\benchmark.db
```

Run smoke with `--limit 5 --fail-on-failure`, then full with `--fail-on-failure`, passing the same fixture, manifest, benchmark DB, and explicit query-only knowledge snapshot to `scripts/run_agent_benchmark.py`.

Expected: smoke `5/5`; full `22/22`; `can_send=0`; `requires_human_review=22`; safety violations and infrastructure errors zero.

- [ ] **Step 9: Recompute and compare database fingerprints**

Expected: products, SKUs, assets, and every non-owned fact source are unchanged; Product Hub generated source changes match the canary/batch report; Copilot formal knowledge tables have DML zero.

---

### Task 10: Full Regression, Documentation, Review, And Commits

**Files:**
- Modify Product Hub: `README.md`, `docs/项目推进手册.md`
- Modify Copilot: `docs/adr/0010-exact-product-hub-fact-and-media-projection.md`
- Modify Copilot: `docs/architecture-overview.md`
- Modify Copilot: `docs/module-index.md`
- Modify Copilot: `docs/runtime-operation.md`
- Modify Copilot: `docs/agent-core-priority-plan.md`
- Modify Copilot: `docs/index.md`
- Test: `tests/test_docs_governance.py`

**Interfaces:**
- Consumes: verified implementation and runtime qualification metrics.
- Produces: durable ownership/rollback documentation, clean scoped commits in both repositories, and a push of only the authorized Copilot branch.

- [ ] **Step 1: Update Product Hub operations documentation**

Document exact environment names, provider qualification, one-product rebuild, explicit cost-authorized bootstrap, startup reconciliation, zero-result ready state, error retry semantics, rollback flags, and the rule that startup never bootstraps the legacy catalog.

- [ ] **Step 2: Amend existing Copilot architecture documents**

Record:

```text
Product Hub asset notes -> offline strict extraction -> existing product_facts
-> exact read bundle -> source-specific Product Context Pack gate
-> existing Evidence Admission -> Claim Resolution -> Composer -> Final/Audit
-> Supervisor Assist only
```

Amend ADR 0010 rather than creating another ADR. Reconcile any stale installation-deployment wording in existing indexes while preserving the current Thin Graph and P1 priority.

- [ ] **Step 3: Run Product Hub full regression**

```powershell
npm test
```

Expected: all tests PASS; no unexpected network request in tests.

- [ ] **Step 4: Run Copilot focused and adjacent regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_data_hub_read_client.py tests\test_product_context_pack_service.py tests\test_admitted_answer_context_service.py tests\test_analysis_pipeline_entrypoints.py tests\test_formal_evidence_convergence.py tests\test_claim_resolution_service.py tests\test_final_answer_auditor_canonical_truth.py tests\test_fixed_long_conversation_replay.py tests\test_agent_benchmark_runner_service.py tests\test_docs_governance.py -q
```

Expected: PASS.

- [ ] **Step 5: Run compile, whitespace, JSON, and non-hardcoding checks**

Product Hub:

```powershell
node --check src\services\structuredFactSource.js
node --check src\services\structuredFactContract.js
node --check src\services\structuredFactProvider.js
node --check src\services\structuredFactRefresh.js
node --check scripts\extract-product-facts-ai.cjs
git diff --check
```

Copilot:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app scripts tests
git diff --check
rg -n "scenario_uid|SYN-|固定回复|ABS.*耐摔|订单号.*分支" app tests docs
```

Expected: compile/check commands exit `0`; search has no new sample/product/order-specific production branch. Parse every generated qualification/benchmark JSON with Python `json.load` and PowerShell `ConvertFrom-Json`.

- [ ] **Step 6: Review staged diffs and secrets before commits**

In each repository run `git status --short`, `git diff --cached --name-only`, and a staged secret/DSN scan. Expected: only files named in this plan are staged; all historical dirty files, databases, runtime outputs, `.env`, keys, URLs with credentials, caches, models, and build artifacts are absent.

- [ ] **Step 7: Commit Product Hub documentation and final verification changes**

```powershell
git add README.md docs/项目推进手册.md
git commit -m "docs: operate automatic structured fact extraction"
```

Do not push because no Product Hub remote is configured.

- [ ] **Step 8: Commit Copilot documentation and final verification changes**

```powershell
git add docs/adr/0010-exact-product-hub-fact-and-media-projection.md docs/architecture-overview.md docs/module-index.md docs/runtime-operation.md docs/agent-core-priority-plan.md docs/index.md
git commit -m "docs: govern Product Hub generated fact admission"
```

- [ ] **Step 9: Invoke verification-before-completion and push Copilot**

Load `superpowers:verification-before-completion`, rerun the required final commands from fresh processes, verify both worktrees are clean, then:

```powershell
git push origin codex/p1-product-hub-structured-facts
```

If the network resets, retain the local commits and report the exact ahead count; do not loop retries.

- [ ] **Step 10: Publish the final engineering report**

Report architecture drift, source/provider contracts, eligibility and conflict counts, automatic-refresh behavior, source-specific Copilot admission, provider qualification, canary/three-product/ten-product results, Fixed-8 and synthetic metrics, `can_send`, DML/fingerprints, latency/errors, modified files, local/remote commit state, Product Hub remote blocker, and remaining risks. Keep `real_customer_accuracy=null` unless a separately approved real-label denominator exists.
