# Customer-Conditional Space-Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the review-only Agent distinguish a requested space-fit conclusion from a measurement lookup and provide a conditional comparison from explicit buyer-supplied values without promoting those values to product evidence.

**Architecture:** Extend the existing model-visible FactType candidate contract with a concise semantic boundary for `dimensions` and `space_fit`. Keep customer turns in their existing non-factual channel and narrowly permit the existing Composer to state a direct consequence under an explicit customer-condition boundary while the actual product fact remains unresolved. Existing Deterministic Final, Unified Audit, human review, and no-send rules remain authoritative.

**Tech Stack:** Python 3, pytest, existing strict-schema Turn Understanding, existing ModelFirstAnswerComposerService, existing Final Answer Auditor.

## Global Constraints

- Do not add a Graph node, service, model call, reply owner, retry, repair, fallback, registry, or delivery condition.
- Do not add customer-phrase, product, SKU, order, scenario, or fixed-value branches.
- Customer-supplied or hypothetical values are not admitted evidence and receive no evidence UID.
- Conditional clauses remain review-only and cannot change `can_send`.
- Synthetic fixtures prove regression behavior only; `real_customer_accuracy=null` remains unchanged.

---

### Task 1: FactType Semantic Boundary

**Files:**
- Modify: `app/services/semantic_fact_type_service.py`
- Test: `tests/test_semantic_fact_type_service.py`

**Interfaces:**
- Consumes: `_canonical_fact_type_candidates() -> list[dict[str, Any]]`
- Produces: candidate dictionaries with an optional server-owned `classification_boundary` string; the Provider output schema remains unchanged.

- [ ] **Step 1: Write the failing contract test**

Add a test that indexes `_canonical_fact_type_candidates()` by `fact_type_id` and asserts:

```python
assert "measurement value" in candidates["dimensions"]["classification_boundary"]
assert "fit conclusion" in candidates["space_fit"]["classification_boundary"]
assert "supplied measurements are premises" in candidates["space_fit"]["classification_boundary"]
```

- [ ] **Step 2: Run the focused test and observe RED**

Run:

```powershell
python -m pytest tests/test_semantic_fact_type_service.py -k "fact_type_candidate_semantic_boundary" -q
```

Expected: failure because `classification_boundary` is absent.

- [ ] **Step 3: Implement the minimal server-owned boundary**

Add a constant keyed only by canonical FactType IDs:

```python
_FACT_TYPE_CLASSIFICATION_BOUNDARIES = {
    "dimensions": "A request for a product measurement value; not a conclusion about whether it fits a supplied space.",
    "space_fit": "A request for a fit conclusion; supplied product or space measurements are premises, not separate requested measurement values.",
}
```

Project this field only when the canonical FactType has a declared boundary.
Do not add buyer terms or deterministic reclassification.

- [ ] **Step 4: Run the semantic tests and observe GREEN**

Run:

```powershell
python -m pytest tests/test_semantic_fact_type_service.py tests/test_atomic_goal_span_contract.py -q
```

- [ ] **Step 5: Commit the independently reviewable change**

```powershell
git add -- app/services/semantic_fact_type_service.py tests/test_semantic_fact_type_service.py
git commit -m "fix: distinguish fit conclusions from dimensions"
```

### Task 2: Conditional Unresolved Composer Contract

**Files:**
- Modify: `app/services/model_first_answer_composer_service.py`
- Test: `tests/test_model_first_answer_composer_service.py`
- Test: `tests/test_composer_decision_input_contract.py`

**Interfaces:**
- Consumes: existing `current_customer_question`, `recent_conversation_turns`, unresolved Claim Resolution, and zero admitted evidence.
- Produces: one ordinary Composer clause whose server-owned canonical kind remains `unresolved`, with empty evidence and policy references.

- [ ] **Step 1: Write failing prompt and authority tests**

Use the existing `_response()` and `_compose()` helpers. Set one unresolved
`space_fit` goal, no admitted evidence, a current question containing one
measurement, and one recent customer turn containing the available-space
measurement. Assert the Provider prompt preserves both turns and contains the
conditional-authority rule. Return a conditionally framed clause and assert:

```python
assert result["status"] == "accepted"
assert result["clauses"][0]["clause_kind"] == "unresolved"
assert result["clauses"][0]["evidence_refs"] == []
assert updated["requires_human_review"] is True
assert updated["can_send"] is False
```

Also assert the serialized Composer decision input contains the buyer turns but
does not contain a fabricated `evidence_uid` for either measurement.

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```powershell
python -m pytest tests/test_model_first_answer_composer_service.py tests/test_composer_decision_input_contract.py -k "customer_conditional" -q
```

Expected: the conditional authority text is absent.

- [ ] **Step 3: Add the narrow Composer instruction**

Extend the existing `_system_prompt()` unresolved-clause contract, without a
Python reply template:

```text
When the current question and recent customer turns explicitly supply the
quantities or conditions being compared, an unresolved clause may state only
their direct logical consequence under an explicit customer-condition boundary.
Do not present a customer-supplied or hypothetical value as an admitted product
fact, infer a missing dimension, or remove the unresolved actual-product boundary.
```

Do not change the response schema or clause reconstruction.

- [ ] **Step 4: Run Composer tests and observe GREEN**

Run:

```powershell
python -m pytest tests/test_model_first_answer_composer_service.py tests/test_composer_decision_input_contract.py -q
```

- [ ] **Step 5: Commit the independently reviewable change**

```powershell
git add -- app/services/model_first_answer_composer_service.py tests/test_model_first_answer_composer_service.py tests/test_composer_decision_input_contract.py
git commit -m "fix: allow review-only conditional comparisons"
```

### Task 3: Final Boundary And Regression Qualification

**Files:**
- Test: `tests/test_final_answer_auditor.py`
- Modify only if an existing generic final-audit contract demonstrably fails: `app/services/final_answer_auditor.py`
- Modify: `docs/architecture-overview.md`
- Modify: `docs/module-index.md`
- Modify: `docs/project-execution-ledger.md`
- Modify: `docs/index.md`

**Interfaces:**
- Consumes: a review-only unresolved conditional clause with zero evidence.
- Produces: audit evidence that conditional framing is allowed but an unconditional product measurement assertion remains blocked.

- [ ] **Step 1: Add positive and negative final-boundary tests**

Construct two responses with zero selected/admitted evidence. The positive
response explicitly says the result applies only if the customer-supplied
measurements are accurate and leaves the actual product value unconfirmed. The
negative response states the product measurement as an established fact. Assert
the positive remains human-review/no-send and the negative audit fails.

- [ ] **Step 2: Run the tests and classify any failure**

Run:

```powershell
python -m pytest tests/test_final_answer_auditor.py -k "customer_conditional" -q
```

If the positive already passes and the negative already fails, do not modify
production audit code. If either contract fails, modify only the earliest
generic unsupported-fact/conditional boundary; do not add sample wording.

- [ ] **Step 3: Run the focused P1 suite**

Run:

```powershell
python -m pytest tests/test_semantic_fact_type_service.py tests/test_atomic_goal_span_contract.py tests/test_claim_resolution_service.py tests/test_model_first_answer_composer_service.py tests/test_composer_decision_input_contract.py tests/test_final_answer_auditor.py tests/test_regression_order_intent.py -q
```

- [ ] **Step 4: Run compile and diff integrity checks**

Run:

```powershell
python -m compileall -q app tests
git diff --check
```

- [ ] **Step 5: Update durable documentation**

Record that customer-provided conditions remain non-factual and may support only
review-only conditional consequences. State that no new owner, send authority,
or accuracy claim was introduced. Add the new spec and plan to the existing
documentation index.

- [ ] **Step 6: Run governance and broader regression**

Run the repository's docs-governance tests and the broad test suite. Compare any
failure with the parent baseline before attributing it to this change.

- [ ] **Step 7: Commit and push**

```powershell
git add -- tests/test_final_answer_auditor.py docs/architecture-overview.md docs/module-index.md docs/project-execution-ledger.md docs/index.md docs/superpowers/plans/2026-08-14-customer-conditional-space-fit.md
git commit -m "docs: record customer conditional comparison contract"
git push -u origin codex/p1-customer-conditional-space-fit
```
