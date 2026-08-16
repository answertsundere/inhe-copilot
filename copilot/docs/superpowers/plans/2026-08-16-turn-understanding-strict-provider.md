# Turn Understanding Strict Provider Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-disabled, qualification-bound strict Provider path to the existing Turn Understanding owner and validate it through synthetic, `1x1`, `3x1`, and authorized E2 gates.

**Architecture:** `SemanticFactTypeService` keeps semantic ownership and all existing normalization/provenance checks. It may call the existing `StrictDecisionProviderService` only when a complete role-specific configuration and matching qualification fingerprint are present. Evaluation reuses the exact production schema and prompt and does not create a second runtime service.

**Tech Stack:** Python 3.11, pytest, OpenAI-compatible transport, existing strict Provider service, SQLite query-only snapshots.

## Global Constraints

- No new Graph node, service, reply owner, retry, repair, fallback, or keyword classifier.
- Strict role is default-disabled and independent of all other Provider roles.
- No Gold labels, expected replies, or real customer text enter qualification prompts.
- Formal knowledge remains query-only; `can_send=false`; human review remains mandatory.
- Runtime reports, credentials, databases, and outputs are never committed.

---

### Task 1: Role-Scoped Configuration

**Files:**
- Modify: `app/config.py`
- Modify: `app/services/strict_decision_provider_service.py`
- Test: `tests/test_strict_decision_provider_service.py`

**Interfaces:**
- Produces: `StrictDecisionProviderConfig.from_turn_understanding_environment()`
- Produces: a qualification status bound to `role_name="turn_understanding"`

- [ ] Add failing tests proving the role does not inherit other credentials,
  rejects missing fingerprints, and remains disabled by default.
- [ ] Run the tests and confirm the expected failures.
- [ ] Add the minimal config fields and role constructor.
- [ ] Run the tests and confirm they pass.

### Task 2: Strict Transport In Existing Turn Understanding Owner

**Files:**
- Modify: `app/services/semantic_fact_type_service.py`
- Test: `tests/test_semantic_fact_type_service.py`
- Test: `tests/test_turn_understanding_failure_diagnostics.py`

**Interfaces:**
- Consumes: `StrictDecisionProviderConfig.from_turn_understanding_environment()`
- Produces: the existing `_classify_with_llm()` normalized result and diagnostics

- [ ] Add failing tests for disabled parity, qualified strict invocation,
  unqualified fail-closed behavior, historical-source rejection, and current
  exact-span acceptance.
- [ ] Run the tests and confirm the expected failures.
- [ ] Route the Provider request through the existing strict service only when
  enabled; reuse the current schema, prompt, payload, normalizer, and validator.
- [ ] Run the tests and confirm they pass.

### Task 3: Synthetic Qualification Script

**Files:**
- Create: `scripts/qualify_turn_understanding_provider.py`
- Create: `tests/test_qualify_turn_understanding_provider.py`

**Interfaces:**
- Consumes: existing strict Provider service, Turn Understanding prompt/schema,
  normalizer, and current-source validator
- Produces: `turn-understanding-provider-qualification/v1` JSON report

- [ ] Add failing tests for a qualified matrix, historical-source rejection,
  timeout/truncation/schema counts, repeat stability, safe metadata, zero DML,
  and zero send changes.
- [ ] Run tests and confirm the expected failures.
- [ ] Implement the fictional matrix and deterministic report aggregation.
- [ ] Run tests and confirm they pass.

### Task 3A: Canonical Repeatability Closure

**Files:**
- Modify: `app/services/semantic_fact_type_service.py`
- Modify: `scripts/qualify_turn_understanding_provider.py`
- Test: `tests/test_atomic_goal_span_contract.py`
- Test: `tests/test_qualify_turn_understanding_provider.py`

**Interfaces:**
- Consumes: exact current-message source substrings and canonical goal kind
- Produces: deterministic clause-bounded provenance and role-aware stability

- [ ] Add failing tests proving equivalent unique substrings in one clause
  normalize to the same provenance while multiple goals in one clause retain
  independent exact spans.
- [ ] Add failing tests proving non-authoritative `service_action.semantic_key`
  variation cannot fail semantic stability, while unmapped customer goals and
  contextual constraints remain strict.
- [ ] Keep history-only, repeated ambiguous, paraphrased, and cross-turn source
  mutations fail-closed.
- [ ] Implement the smallest owner-local normalization and qualifier projection.
- [ ] Re-run the fixed fictional matrix once; do not retry for an accidental
  Provider pass.

### Task 4: Provider And Runtime Gates

**Files:**
- Runtime only: `D:\\桌面文件\\客服\\.codex-runtime\\p1-turn-understanding-provider-qualification\\`

**Interfaces:**
- Consumes: safe process-only Provider configuration and the qualification script
- Produces: qualification, `1x1`, `3x1`, and optional 20-case reports outside Git

- [ ] Run the synthetic matrix against each genuinely configured candidate,
  beginning with `glm-4.6` because official documentation advertises Function
  Call and structured output support.
- [ ] Stop if no candidate reaches 100% qualification.
- [ ] If qualified, bind the fingerprint to isolated 5013 and run `1x1` once.
- [ ] If `1x1` passes, run fixed `3x1` once.
- [ ] Only if `3/3` passes, run the authorized 20 conversations once.

### Task 5: Regression, Documentation, And Integration

**Files:**
- Modify: `docs/agent-core-priority-plan.md`
- Modify: `docs/architecture-overview.md`
- Modify: `docs/module-index.md`
- Modify: `docs/index.md`

**Interfaces:**
- Produces: durable status without embedding runtime reports or customer text

- [ ] Run strict Provider, Turn Understanding, Pipeline, Final, Replay, and docs
  tests.
- [ ] Run `py_compile`, `git diff --check`, versioned smoke `5/5`, and full
  `22/22` when smoke passes.
- [ ] Verify query-only knowledge hash, `can_send=0`, and no runtime artifacts in
  Git.
- [ ] Update existing documents with the actual highest completed gate.
- [ ] Commit scoped changes and push the feature branch.
