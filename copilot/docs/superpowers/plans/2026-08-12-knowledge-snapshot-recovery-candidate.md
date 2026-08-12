# Knowledge Snapshot Recovery Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert only identity-matched, historically reviewed product facts into an isolated current-schema candidate database that requires fresh review and cannot affect the formal knowledge database or customer replies.

**Architecture:** The recovery tool reads the historical SQLite snapshot with `mode=ro` and `PRAGMA query_only=ON`. It seeds a new, explicitly non-formal SQLite candidate from the current schema database, empties all seed data in the candidate, then copies only eligible `kb_product` and `knowledge_entries` rows with reset review states. It never copies QA, media, chunks, Answer Memory, or change logs, and it emits a content-free manifest.

**Tech Stack:** Python standard library `sqlite3`, existing formal knowledge backup guard, pytest, JSON.

## Global Constraints

- The active priority remains P1 Gold Conversation Quality; this is recovery work for its earliest data/identity dependency, not an Agent behavior change.
- Snapshot and formal schema source stay read-only; the candidate is an isolated local file and is never used by runtime configuration.
- Copy only product facts where both product and fact were published and `knowledge_entries.product_id == kb_product.i_id` exactly.
- Candidate products and facts must reset to `pending_review` / `needs_human_review`, with `auto_reply_allowed=0`, `human_review_required=1`, no chunks, and no automatic admission.
- Do not copy `kb_qa`, `kb_media_asset`, `knowledge_chunks`, `agent_answer_memory`, `kb_change_log`, credentials, URLs, or external source payloads.
- Do not add graph nodes, services, reply owners, model calls, retries, fallbacks, or changes to `can_send`.
- Candidate databases and manifests are runtime artifacts and must remain untracked.

---

### Task 1: Define the recovery candidate contract with failing tests

**Files:**
- Create: `tests/test_knowledge_snapshot_recovery_candidate.py`
- Create: `scripts/build_knowledge_snapshot_recovery_candidate.py`

**Interfaces:**
- Consumes: `build_snapshot_recovery_candidate(snapshot_path, schema_path, candidate_path, apply=False) -> dict[str, object]`
- Produces: a dry-run manifest or one isolated candidate SQLite file plus a manifest without raw source text.

- [x] **Step 1: Write the failing tests**

```python
def test_dry_run_reports_only_eligible_counts_and_never_creates_candidate(tmp_path):
    report = module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=False)
    assert report["candidate_created"] is False
    assert report["eligible_fact_count"] == 1
    assert not candidate.exists()

def test_apply_resets_review_state_and_excludes_other_knowledge_roles(tmp_path):
    report = module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)
    assert report["candidate_created"] is True
    assert candidate_rows(candidate, "kb_product") == 1
    assert candidate_rows(candidate, "knowledge_entries") == 1
    assert candidate_rows(candidate, "kb_qa") == 0
    assert candidate_rows(candidate, "knowledge_chunks") == 0
    assert candidate_rows(candidate, "kb_media_asset") == 0
```

- [x] **Step 2: Run the tests to verify they fail because the recovery builder does not exist**

Run:

```powershell
& $env:CODEX_BUNDLED_PYTHON -m pytest tests/test_knowledge_snapshot_recovery_candidate.py -q
```

Expected: import or attribute failure for `build_snapshot_recovery_candidate`.

- [x] **Step 3: Implement the minimum safe builder**

```python
def build_snapshot_recovery_candidate(snapshot_path, schema_path, candidate_path, *, apply=False):
    # Validate distinct non-formal paths, read source query-only, and select only
    # reviewed product facts whose product_id exactly equals a published product i_id.
    # With apply=False return only structural counts and hashes.
    # With apply=True create a new candidate from the schema seed, clear it, and
    # insert reset-review product and fact rows in a single candidate transaction.
```

- [x] **Step 4: Run the focused tests to verify the builder passes**

Run:

```powershell
& $env:CODEX_BUNDLED_PYTHON -m pytest tests/test_knowledge_snapshot_recovery_candidate.py -q
```

Expected: all tests pass.

### Task 2: Add candidate safety and determinism tests

**Files:**
- Modify: `tests/test_knowledge_snapshot_recovery_candidate.py`
- Modify: `scripts/build_knowledge_snapshot_recovery_candidate.py`

**Interfaces:**
- Consumes: the Task 1 builder.
- Produces: fail-closed path validation, stable batch provenance, and a content-free manifest.

- [x] **Step 1: Write failing safety tests**

```python
def test_builder_refuses_formal_target_or_existing_candidate(tmp_path):
    with pytest.raises(ValueError, match="candidate_path_not_isolated"):
        module.build_snapshot_recovery_candidate(snapshot, schema, schema, apply=True)

def test_source_and_formal_schema_checksums_remain_unchanged(tmp_path):
    before = (sha256(snapshot), sha256(schema))
    module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)
    assert (sha256(snapshot), sha256(schema)) == before

def test_manifest_contains_hashes_and_counts_but_not_source_content(tmp_path):
    report = module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)
    rendered = json.dumps(report, ensure_ascii=False)
    assert "private source sentence" not in rendered
    assert report["formal_knowledge_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
```

- [x] **Step 2: Run the added tests to verify they fail for the missing safeguards**

Run:

```powershell
& $env:CODEX_BUNDLED_PYTHON -m pytest tests/test_knowledge_snapshot_recovery_candidate.py -q
```

Expected: safety assertions fail before the safeguards exist.

- [x] **Step 3: Implement only the required safeguards**

```python
def _validate_candidate_path(schema_path: Path, candidate_path: Path) -> None:
    if candidate_path == schema_path or candidate_path.name == "knowledge_base.db" or candidate_path.exists():
        raise ValueError("candidate_path_not_isolated")
```

- [x] **Step 4: Re-run the focused suite**

Run:

```powershell
& $env:CODEX_BUNDLED_PYTHON -m pytest tests/test_knowledge_snapshot_recovery_candidate.py tests/test_knowledge_snapshot_recovery_audit.py tests/test_formal_knowledge_database_guard_service.py -q
```

Expected: all tests pass.

### Task 3: Run the historical snapshot recovery candidate and verify isolation

**Files:**
- Modify: `scripts/build_knowledge_snapshot_recovery_candidate.py`
- Runtime only: `recovery/candidates/*.db`, `recovery/candidates/*.manifest.json` (ignored; never commit)

**Interfaces:**
- Consumes: historical runtime snapshot and rebuilt current schema database.
- Produces: a review-only candidate database and a safe manifest.

- [x] **Step 1: Run a real dry run**

```powershell
& $env:CODEX_BUNDLED_PYTHON scripts/build_knowledge_snapshot_recovery_candidate.py `
  --snapshot-db <historical-runtime-db> --schema-db data/knowledge_base.db `
  --candidate-db recovery/candidates/<batch>.db --json-output recovery/candidates/<batch>.manifest.json
```

Expected: source query-only true; no candidate file; eligible count present; `formal_knowledge_write_attempt_count=0`.

- [x] **Step 2: Create one isolated candidate explicitly**

```powershell
& $env:CODEX_BUNDLED_PYTHON scripts/build_knowledge_snapshot_recovery_candidate.py `
  --snapshot-db <historical-runtime-db> --schema-db data/knowledge_base.db `
  --candidate-db recovery/candidates/<batch>.db --apply --json-output recovery/candidates/<batch>.manifest.json
```

Expected: only candidate path changes; formal schema source checksum unchanged; candidate rows are pending review and unindexed.

- [x] **Step 3: Validate the manifest without exposing business content**

```powershell
& $env:CODEX_BUNDLED_PYTHON -c "import json; json.load(open(r'<manifest>', encoding='utf-8')); print('python_json_ok')"
Get-Content -Raw <manifest> | ConvertFrom-Json | Out-Null; Write-Output powershell_json_ok
```

Expected: both parsers succeed; Git status contains no candidate artifacts.

### Task 4: Document and commit the recovery tool

**Files:**
- Modify: `docs/architecture-overview.md`
- Modify: `docs/module-index.md`
- Modify: `docs/index.md`
- Modify: `docs/superpowers/plans/2026-08-12-knowledge-snapshot-recovery-candidate.md`

**Interfaces:**
- Consumes: verified candidate run outcome.
- Produces: a documented recovery path that remains separate from formal evidence admission.

- [x] **Step 1: Update durable documentation**

Record that snapshot recovery is an isolated review-only candidate source; it does not restore production truth, media delivery, Answer Memory, or autonomous send eligibility.

- [x] **Step 2: Run focused verification**

Run:

```powershell
& $env:CODEX_BUNDLED_PYTHON -m pytest tests/test_knowledge_snapshot_recovery_candidate.py tests/test_knowledge_snapshot_recovery_audit.py tests/test_formal_knowledge_database_guard_service.py tests/test_docs_governance.py -q
& $env:CODEX_BUNDLED_PYTHON -m compileall -q app scripts
git diff --check
```

Expected: all targeted tests pass, compilation succeeds, and candidate artifacts are untracked/ignored.

- [x] **Step 3: Commit only source, tests, and documentation**

```powershell
git add copilot/scripts/build_knowledge_snapshot_recovery_candidate.py copilot/tests/test_knowledge_snapshot_recovery_candidate.py copilot/docs/superpowers/plans/2026-08-12-knowledge-snapshot-recovery-candidate.md copilot/docs/index.md copilot/docs/architecture-overview.md copilot/docs/module-index.md
git commit -m "feat: stage historical knowledge recovery candidates"
```

Expected: no candidate database, manifest, outputs, credentials, or cache enters the commit.

## Self-Review

- Each copied fact is constrained by exact product identity and historical review state; no text, SKU, scenario, or product-specific condition controls eligibility.
- Candidate status reset is explicit and excludes every formal evidence or delivery route.
- The builder has no model, graph, service, RAG, Composer, Final Audit, or delivery dependencies.
- The candidate artifact is local-only and formal databases are checksummed before and after every write-capable execution.
