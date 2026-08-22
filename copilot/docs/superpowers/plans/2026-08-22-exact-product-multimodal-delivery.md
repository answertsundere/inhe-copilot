# Exact Product Multimodal Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the existing Pipeline answer from exact Product Data Hub facts and attach one matching Hub image/video when the existing Final and Delivery contracts allow it.

**Architecture:** Extend the existing read-only Hub adapter with an exact bundle projection, feed its facts and media into the existing Product Context Pack, and reuse the existing media asset and reply-block contracts. No new graph node, reply owner, retriever, or delivery path is created.

**Tech Stack:** Python 3, urllib read-only Hub client, SQLite-backed Product Data Hub HTTP API, existing Product Context Pack, existing media asset service, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-exact-product-multimodal-delivery-design.md`

## Global Constraints

- Active priority remains P1 Gold Conversation Quality.
- Hub access is read-only and exact-identity only.
- Vector ranking is restricted to the resolved product/SKU asset pool.
- No fact or media candidate may cross product or SKU scope.
- High-risk safety, compliance, age, load, medical, refund, replacement, and write actions retain existing gates.
- No Graph node, second Pipeline, second Composer, new model call, retry, repair, or fallback is introduced.
- One default-off flag reverts the feature to reference-only Hub behavior.
- Preserve unrelated dirty frontend files and do not commit them.

---

### Task 1: Exact Hub bundle contract

**Files:**
- Modify: `app/integrations/product_data_hub/read_client.py`
- Test: `tests/test_product_data_hub_read_client.py`

**Interfaces:**
- Consumes: resolved exact Hub product/SKU identity and Hub `/facts` plus product-detail endpoints.
- Produces: `lookup_product_data_hub_bundle(i_id, sku_id)` with `facts` and `assets` projections, or a deterministic unavailable/ambiguous result.

- [ ] Write tests for exact identity, fact filtering, SKU applicability, preview URL construction, unavailable Hub, and no write request.
- [ ] Run the new tests and confirm they fail before the bundle projection exists.
- [ ] Add bounded GET-only helpers, size limits, canonical field projections, and a fact/asset bundle that preserves Hub provenance.
- [ ] Run adapter tests and verify all pass.

### Task 2: Product Context Pack admission

**Files:**
- Modify: `app/services/product_context_pack_service.py`
- Modify: `app/config.py`
- Test: `tests/test_product_context_pack_service.py`
- Test: `tests/test_product_data_hub_read_client.py`

**Interfaces:**
- Consumes: exact Hub bundle and existing resolved product identity.
- Produces: canonical fact candidates and media candidates inside the existing Product Context Pack only when `COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED` is true.

- [ ] Write tests proving fact-type mapping, package/component scope rejection for product dimensions, pending/conflict exclusion, exact-SKU-only variant facts, and flag-off compatibility.
- [ ] Run tests and confirm the Hub projection does not yet create candidates.
- [ ] Implement deterministic Hub fact mapping and Hub media candidate projection without changing existing database fact ownership.
- [ ] Run Product Context Pack and adjacent evidence tests.

### Task 3: Label-first media selection and block eligibility

**Files:**
- Modify: `app/services/media_asset_service.py`
- Test: `tests/test_media_asset.py`
- Test: `tests/test_media_asset_style_scope.py`

**Interfaces:**
- Consumes: Product Context Pack Hub media candidates with exact identity, labels, notes, spec references, and URLs.
- Produces: at most one auto-sendable `reply_block` whose purpose matches the requested claim.

- [ ] Write tests for dimensions, installation, color, certificate/report, award, wrong product, wrong SKU, missing preview, wrong purpose, and two similarly labelled assets.
- [ ] Run tests and confirm unrecognized Hub asset labels cannot be selected.
- [ ] Add label mapping and deterministic text-overlap/rerank scoring within the existing candidate selector; preserve existing media identity and delivery eligibility checks.
- [ ] Run media tests and verify one matching asset is selected without a cross-product attachment.

### Task 4: Final/Demand delivery behavior

**Files:**
- Modify: `app/services/final_answer_auditor.py` only if the existing validator lacks Hub provenance validation.
- Modify: `app/services/analysis_pipeline_service.py` only if the existing block builder is not invoked with Hub candidates.
- Test: `tests/test_analysis_pipeline_entrypoints.py`
- Test: `tests/test_final_answer_auditor_canonical_truth.py`

**Interfaces:**
- Consumes: the existing reply blocks and Hub-derived candidate provenance.
- Produces: unchanged final response fields with media blocks and `can_send` only when the current Delivery Gate accepts them.

- [ ] Write tests proving a matching text/image block can be auto-send-ready, unsupported high-risk safety wording is blocked, and flag-off output remains text-only/reference-only.
- [ ] Run tests and confirm the new cases fail before provenance validation is present.
- [ ] Add only the minimal Hub provenance checks needed by the existing Final/Delivery path.
- [ ] Run final auditor and pipeline entrypoint regressions.

### Task 5: Governance, replay, and documentation

**Files:**
- Create: `docs/adr/0010-product-hub-facts-and-exact-media-delivery.md`
- Modify: `docs/index.md`
- Modify: `docs/architecture-overview.md`
- Modify: `docs/module-index.md`
- Modify: `docs/agent-core-priority-plan.md`
- Test: `tests/test_docs_governance.py`

**Interfaces:**
- Consumes: implemented exact Hub fact/media projection and existing delivery gates.
- Produces: a durable ownership decision and a reproducible flag-off/flag-on replay report without Hub writes.

- [ ] Document ownership, scope, rollout flag, rollback, automatic-media conditions, and high-risk boundaries.
- [ ] Run targeted adapter/context/media/final tests, documentation governance, compilation, and a same-input off/on workbench replay.
- [ ] Verify HTTP requests are GET-only, Hub writes are zero, formal knowledge DML is zero, and unrelated dirty files are absent from the staged diff.
- [ ] Commit only this feature's code, tests, ADR, and documentation after the real-dataset change gate is reported.
