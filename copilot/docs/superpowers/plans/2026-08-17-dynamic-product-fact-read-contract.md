# Dynamic Product Fact Read Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Product Context Pack faithfully reread mutable product and SKU facts with versioned provenance and exact variant scope.

**Architecture:** Keep `ProductContextPackService` as the only product-first read owner and `ProductStructuredEvidenceService` as the existing structured-field evidence owner. Add no cache or integration; enrich each fresh profile with source version/update time, bind evidence identity to the current value, and filter SKU-list values by the resolved SKU.

**Tech Stack:** Python 3.11, SQLAlchemy, pytest, existing `KBProduct` and Product Context Pack contracts.

## Global Constraints

- No new Graph node, service, model call, reply owner, router, planner, registry, retry, repair, or fallback.
- Do not alter Evidence Admission, Safety, media, Delivery, or `can_send`.
- Do not branch on sample text, product name, SKU value, order ID, or scenario UID.
- Formal knowledge and test source databases remain read-only outside isolated fixtures.
- Synthetic tests prove the read contract only; `real_customer_accuracy=null`.

---

### Task 1: Fresh Value And Versioned Provenance

**Files:**
- Modify: `tests/test_product_context_pack_service.py`
- Modify: `app/services/product_context_pack_service.py`
- Modify: `app/services/product_structured_evidence_service.py`

**Interfaces:**
- Consumes: `build_product_context_pack(state, query, query_fact_type)` and `KBProduct.version/updated_at`.
- Produces: profile fields `source_version`, `source_updated_at`, `requested_sku`; evidence fields `source_version`, `source_updated_at`, `value_sha256`.

- [ ] **Step 1: Write the failing fresh-read test**

Add a test that creates one published product with `package_weight=7.5kg`, reads it, updates the same row directly to `8.2kg` with `version=2`, reads again, and asserts:

```python
assert "7.5kg" in first["facts"][0]["chunk_text"]
assert "8.2kg" in second["facts"][0]["chunk_text"]
assert first_fact["evidence_id"] != second_fact["evidence_id"]
assert first_fact["value_sha256"] != second_fact["value_sha256"]
assert second_fact["source_version"] == 2
assert second_fact["source_updated_at"]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
& 'D:\桌面文件\客服\.codex-runtime\venvs\copilot-rebuild\Scripts\python.exe' -m pytest tests\test_product_context_pack_service.py -k "rereads_mutable_product_fact" -q
```

Expected: FAIL because current profiles and facts lack versioned provenance and value-sensitive evidence identity.

- [ ] **Step 3: Implement minimal profile provenance**

Change `_build_structured_profile(product, requested_sku="")` to include:

```python
"source_version": int(product.version or 0),
"source_updated_at": product.updated_at.isoformat() if product.updated_at else "",
"requested_sku": str(requested_sku or "").strip(),
```

Call it from `build_product_context_pack` with `identity.get("sku", "")`.

- [ ] **Step 4: Implement value-sensitive evidence provenance**

In `build_product_spec_evidence_candidates`, compute:

```python
value_sha256 = hashlib.sha256(
    json.dumps(
        {"fields": source_field_keys, "value": value_text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
```

Include the source version and digest in `evidence_id`, and return all three provenance fields. Project them unchanged through `_profile_facts_for_query`.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 6: Add and pass the deletion test**

After the first read, clear `logistics_json`, increment the row version, and assert the next pack has no direct fact and reports `missing_product_fact`. Run both fresh-read tests and expect PASS.

### Task 2: Exact SKU Fact Scope

**Files:**
- Modify: `tests/test_product_context_pack_service.py`
- Modify: `app/services/product_structured_evidence_service.py`
- Modify: `app/services/product_context_pack_service.py`

**Interfaces:**
- Consumes: profile field `requested_sku` and existing `sku_list` rows.
- Produces: protocol and pack field `sku_scope: list[str]` containing only the selected SKU rows.

- [ ] **Step 1: Write the failing exact-variant tests**

Create a product with two distinct SKU rows and weights. Assert an exact request for SKU A returns only A's weight and `sku_scope == ["SKU-A"]`; assert an unknown SKU returns no direct gross-weight evidence rather than B's value.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& 'D:\桌面文件\客服\.codex-runtime\venvs\copilot-rebuild\Scripts\python.exe' -m pytest tests\test_product_context_pack_service.py -k "exact_sku_weight or unknown_sku_weight" -q
```

Expected: exact request currently includes both variants or borrows unrelated SKU data.

- [ ] **Step 3: Implement exact row selection**

Add a private helper that case-insensitively compares `requested_sku` against complete values from `sku_code`, `sku_id`, and `sku_variant_key`. If a requested SKU exists, `_pick_sku_values` may use only exact matching rows. If no row matches, return no SKU value. Do not use substring or title matching.

- [ ] **Step 4: Preserve base-product multi-variant behavior**

When `requested_sku` is empty, retain the existing explicit multi-variant output. When all selected rows explicitly share the same requested base `sku_code`, they may remain a multi-variant result.

- [ ] **Step 5: Project exact scope and verify GREEN**

Return `sku_scope` from the structured evidence protocol and use it in `_profile_facts_for_query` instead of projecting every SKU in the product. Run the tests from Step 2 and the existing gross-weight tests; expect PASS.

### Task 3: Regression, Documentation, And Commit

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/project-execution-ledger.md`
- Modify: `docs/module-index.md`

**Interfaces:**
- Consumes: verified Tasks 1-2 behavior.
- Produces: durable status showing dynamic values are database-owned and the Agent is a fresh, exact-scope reader.

- [ ] **Step 1: Run focused and adjacent regression**

Run:

```powershell
& 'D:\桌面文件\客服\.codex-runtime\venvs\copilot-rebuild\Scripts\python.exe' -m pytest tests\test_product_context_pack_service.py tests\test_product_structured_evidence_service.py tests\test_admitted_answer_context_service.py tests\test_formal_evidence_convergence.py tests\test_docs_governance.py -q
```

Expected: all pass.

- [ ] **Step 2: Run compile and diff checks**

Run:

```powershell
& 'D:\桌面文件\客服\.codex-runtime\venvs\copilot-rebuild\Scripts\python.exe' -m compileall -q app tests
git diff --check
```

Expected: exit code 0.

- [ ] **Step 3: Update durable status**

Record fresh per-request reads, versioned evidence provenance, exact SKU scope,
no new owner/call/cache, formal DML `0`, and unchanged `can_send`. Mark the prior
30-item shortlist as non-blocking diagnostic input rather than a publication
gate.

- [ ] **Step 4: Review the scoped diff**

Confirm no outputs, databases, credentials, generated frontend files, sample-specific branches, or unrelated worktree files are staged.

- [ ] **Step 5: Commit**

```powershell
git add app/services/product_context_pack_service.py app/services/product_structured_evidence_service.py tests/test_product_context_pack_service.py ROADMAP.md docs/CHANGELOG.md docs/project-execution-ledger.md docs/module-index.md docs/superpowers/plans/2026-08-17-dynamic-product-fact-read-contract.md
git commit -m "feat: bind mutable product facts to current source version"
```

