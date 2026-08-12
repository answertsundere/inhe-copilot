# Knowledge Snapshot Recovery Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a repeatable, read-only admission report that decides whether a historical SQLite knowledge snapshot can enter a separately governed recovery workflow.

**Architecture:** The utility is a script only. It opens both databases with SQLite read-only URIs and `PRAGMA query_only=ON`, reports only hashes, counts, controlled enums, and field names, and never copies rows or changes Agent behavior. The existing evidence-admission and final-delivery contracts remain the only formal consumers of imported knowledge.

**Tech Stack:** Python standard library `sqlite3`, `hashlib`, `json`, and pytest.

## Global Constraints

- Active priority: `P1 Gold Conversation Quality`; this supports the earliest upstream knowledge-data gap without changing reply logic.
- No production database writes, no Agent/Pipeline/Composer changes, no `can_send` change, and no new runtime service.
- No product text, customer text, URLs, credentials, order identifiers, or other raw snapshot values in the report.
- A historical snapshot is a recovery candidate only; it cannot directly establish current formal evidence or auto-send authority.

---

### Task 1: Add an executable recovery-audit contract test

**Files:**
- Create: `tests/test_knowledge_snapshot_recovery_audit.py`
- Create later: `scripts/diagnose_knowledge_snapshot_recovery.py`

**Interfaces:**
- Consumes: two SQLite paths, one historical source and one current target schema.
- Produces: `build_snapshot_recovery_report(snapshot_path, target_path)` and `write_json_report(path, report)`.

- [x] **Step 1: Write failing tests**

```python
report = module.build_snapshot_recovery_report(snapshot, target)
assert report["source"]["query_only_verified"] is True
assert report["recovery_decision"]["direct_database_copy_allowed"] is False
assert "13800138000" not in json.dumps(report)
```

- [x] **Step 2: Run the targeted test and confirm it fails because the script does not yet exist.**

Run: `python -m pytest tests/test_knowledge_snapshot_recovery_audit.py -q`

### Task 2: Implement the read-only script

**Files:**
- Create: `scripts/diagnose_knowledge_snapshot_recovery.py`
- Test: `tests/test_knowledge_snapshot_recovery_audit.py`

**Interfaces:**
- `build_snapshot_recovery_report(snapshot_path: Path | str, target_path: Path | str) -> dict`
- `write_json_report(path: Path | str, report: dict) -> None`

- [x] **Step 1: Open both inputs with `mode=ro` and `PRAGMA query_only=ON`; reject an identical source/target path.**
- [x] **Step 2: Profile schema compatibility, integrity, reviewed/identity-matched evidence candidates, media mismatch quarantine counts, risk distributions, and potential sensitive-pattern counts without returning raw data.**
- [x] **Step 3: Return a fail-closed recovery decision requiring a separate candidate database and review; never emit an import action.**
- [x] **Step 4: Run the targeted tests until green.**

### Task 3: Document and verify the recovery boundary

**Files:**
- Modify: `docs/architecture-overview.md`
- Modify: `docs/module-index.md`
- Modify: `docs/index.md`

- [x] **Step 1: Record that historical runtime snapshots require a read-only audit and governed candidate import, not direct replacement of `data/knowledge_base.db`.**
- [x] **Step 2: Run the recovery-audit test, formal knowledge guard tests, docs governance, `compileall`, JSON parsing, and scoped diff checks.**
- [ ] **Step 3: Stage only the script, its tests, and the three documentation files; commit locally.**

## Self-Review

- The report cannot change databases or call the Agent.
- Candidate counts are structural and are not evidence admission results.
- Any sensitive-pattern detection forces manual governance; it does not redact or silently pass data.
- The recovery path remains separate from production enablement and Autonomous Send.
