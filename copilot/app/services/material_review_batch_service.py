"""Independent, supervisor-only staging for material review decisions.

The store is deliberately separate from formal knowledge.  A recorded decision
is an auditable review instruction, never a batch KB update.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


MATERIAL_REVIEW_ACTIONS = frozenset({
    "confirm_composition_source",
    "reject_untrusted_source",
    "split_composition_and_strong_claim",
    "replace_placeholder",
    "downgrade_to_human_review",
    "keep_composition_only",
})


class MaterialReviewBatchError(ValueError):
    """Raised when staging input or an optimistic-lock decision is invalid."""


def build_material_review_batches(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Group review work by reusable evidence characteristics, never product ID."""
    source = report if isinstance(report, dict) else {}
    rows = list((source.get("summary") or {}).get("direct_entry_review_candidates") or [])
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    dimensions = (
        "classification", "source_type", "provenance_kind", "fact_type",
        "review_status", "direct_answer_state", "strong_claim_mixed", "identity_scope_quality",
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = tuple(str(row.get(name) or "") for name in dimensions)
        groups[key].append(row)

    batches = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda item: str(item.get("entry_uid") or ""))
        scope = dict(zip(dimensions, key, strict=True))
        encoded_scope = json.dumps(scope, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        batch_uid = "material-batch-" + hashlib.sha256(encoded_scope.encode("utf-8")).hexdigest()[:16]
        batches.append({
            "batch_uid": batch_uid,
            "decision_scope": scope,
            "impacted_count": len(members),
            "status_distribution": dict(sorted(Counter(str(item.get("review_status") or "unknown") for item in members).items())),
            "sample_entry_uids": [str(item.get("entry_uid")) for item in members[:10]],
            "available_actions": sorted(MATERIAL_REVIEW_ACTIONS),
            "dry_run": {
                "formal_kb_writes": 0,
                "creates_formal_observations": 0,
                "can_change_can_send": False,
                "fields_not_modified": ["kb_product", "knowledge_entries", "knowledge_chunks", "kb_qa"],
            },
            "version": 1,
        })
    return batches


class MaterialReviewStagingStore:
    """Small SQLite store for review instructions and immutable audit events."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS material_review_batches (
                  batch_uid TEXT PRIMARY KEY,
                  batch_json TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  decision TEXT NOT NULL DEFAULT '',
                  reviewer_uid TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS material_review_audit (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  batch_uid TEXT NOT NULL,
                  action TEXT NOT NULL,
                  reviewer_uid TEXT NOT NULL,
                  prior_version INTEGER NOT NULL,
                  new_version INTEGER NOT NULL
                );
            """)

    def seed(self, batches: list[dict[str, Any]]) -> int:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            for batch in batches:
                connection.execute(
                    "INSERT OR IGNORE INTO material_review_batches(batch_uid, batch_json, version) VALUES (?, ?, 1)",
                    (batch["batch_uid"], json.dumps(batch, ensure_ascii=False, sort_keys=True)),
                )
        return len(batches)

    def list_batches(self) -> list[dict[str, Any]]:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT batch_json, version, decision, reviewer_uid FROM material_review_batches ORDER BY batch_uid"
            ).fetchall()
        result = []
        for payload, version, decision, reviewer_uid in rows:
            batch = json.loads(payload)
            batch.update({"version": version, "decision": decision, "reviewer_uid": reviewer_uid})
            result.append(batch)
        return result

    def decide(self, *, batch_uid: str, action: str, reviewer_uid: str, expected_version: int) -> dict[str, Any]:
        if action not in MATERIAL_REVIEW_ACTIONS:
            raise MaterialReviewBatchError("unsupported_material_review_action")
        if not reviewer_uid:
            raise MaterialReviewBatchError("reviewer_uid_required")
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "UPDATE material_review_batches SET decision=?, reviewer_uid=?, version=version+1 "
                "WHERE batch_uid=? AND version=?",
                (action, reviewer_uid, batch_uid, expected_version),
            )
            if cursor.rowcount != 1:
                raise MaterialReviewBatchError("optimistic_lock_conflict")
            connection.execute(
                "INSERT INTO material_review_audit(batch_uid, action, reviewer_uid, prior_version, new_version) VALUES (?, ?, ?, ?, ?)",
                (batch_uid, action, reviewer_uid, expected_version, expected_version + 1),
            )
        return {"batch_uid": batch_uid, "action": action, "version": expected_version + 1, "formal_kb_writes": 0}
