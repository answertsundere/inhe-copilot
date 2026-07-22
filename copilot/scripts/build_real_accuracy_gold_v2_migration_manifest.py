"""Build a content-free v0.1 to v0.2 Gold label migration manifest.

The script opens the historical label database read-only.  It never writes a
v0.2 label and never carries an approved status across dataset versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import scan_sensitive_data, validate_gold_dataset  # noqa: E402


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_label_snapshot(path: Path, dataset_version: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError("historical_label_db_missing")
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        labels = [
            {
                "case_uid": row["case_uid"],
                "dataset_version": row["dataset_version"],
                "label": json.loads(row["label_json"]),
                "review_status": row["review_status"],
                "optimistic_lock_version": row["optimistic_lock_version"],
            }
            for row in connection.execute(
                "SELECT case_uid,dataset_version,label_json,review_status,optimistic_lock_version "
                "FROM real_accuracy_case_label WHERE dataset_version=? ORDER BY case_uid",
                (dataset_version,),
            )
        ]
        event_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(real_accuracy_label_event)")}
        selected = ["case_uid", "dataset_version", "event_type", "actor_hash", "actor_role", "claim_uid", "version", "created_at"]
        selected = [column for column in selected if column in event_columns]
        events = [
            dict(row)
            for row in connection.execute(
                f"SELECT {','.join(selected)} FROM real_accuracy_label_event "
                "WHERE dataset_version=? ORDER BY event_id",
                (dataset_version,),
            )
        ]
        return labels, events
    finally:
        connection.close()


def _case_source_digest(case: dict[str, Any]) -> str:
    source = case.get("source") or {}
    kind = str(source.get("kind") or "")
    pseudonymous_id = str(source.get("pseudonymous_id") or "")
    return _stable_hash({"kind": kind, "pseudonymous_id": pseudonymous_id}) if kind and pseudonymous_id else ""


def _old_target(case: dict[str, Any], target_uids: list[str]) -> tuple[str, str]:
    turns = {
        str(turn.get("turn_uid") or ""): turn
        for turn in (case.get("conversation") or {}).get("turns") or []
    }
    selected = [turns.get(uid) for uid in target_uids]
    if not target_uids or any(not turn or turn.get("speaker_role") != "BUYER" for turn in selected):
        return "", "target_missing"
    if len(selected) != 1:
        return "", "manual_target_remap_required"
    return hashlib.sha256(str(selected[0].get("text") or "").encode("utf-8")).hexdigest(), ""


def build_migration_manifest(
    v1: dict[str, Any],
    v2: dict[str, Any],
    labels: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    label_db_sha256: str,
) -> dict[str, Any]:
    v1_cases = {str(case.get("case_uid") or ""): case for case in v1.get("cases") or []}
    v2_by_source = {
        _case_source_digest(case): case
        for case in v2.get("cases") or []
        if _case_source_digest(case)
    }
    events_by_case: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        events_by_case.setdefault(str(event.get("case_uid") or ""), []).append(event)

    candidates: list[dict[str, Any]] = []
    rejected_history: list[dict[str, Any]] = []
    classifications: Counter[str] = Counter()
    old_approved_claim_count = 0
    for label in labels:
        case_uid = str(label.get("case_uid") or "")
        claims = list((label.get("label") or {}).get("claims") or [])
        if label.get("review_status") == "rejected":
            for claim in claims:
                rejected_history.append({
                    "v1_case_uid": case_uid,
                    "v1_claim_uid": str(claim.get("claim_uid") or ""),
                    "history_status": "rejected",
                    "old_audit_event_hash": _stable_hash(events_by_case.get(case_uid, [])),
                })
            continue
        if label.get("review_status") != "approved":
            continue
        old_approved_claim_count += len(claims)
        old_case = v1_cases.get(case_uid)
        source_digest = _case_source_digest(old_case or {})
        new_case = v2_by_source.get(source_digest) if source_digest else None
        old_target_digest, old_target_issue = _old_target(
            old_case or {},
            [str(uid) for uid in (label.get("label") or {}).get("target_turn_uids") or []],
        )
        explicit = (new_case or {}).get("explicit_target") or {}
        if not source_digest:
            classification = "source_provenance_insufficient"
        elif not new_case or not explicit:
            classification = "target_missing"
        elif (new_case or {}).get("target_status") == "target_ambiguous":
            classification = "target_ambiguous"
        elif old_target_issue:
            classification = old_target_issue
        elif old_target_digest == explicit.get("target_text_digest"):
            classification = "exact_target_reusable"
        else:
            classification = "manual_target_remap_required"
        for claim in claims:
            classifications[classification] += 1
            candidates.append({
                "v1_case_uid": case_uid,
                "v1_claim_uid": str(claim.get("claim_uid") or ""),
                "v1_target_turn_uids": list((label.get("label") or {}).get("target_turn_uids") or []),
                "v1_approval_event_hash": _stable_hash(events_by_case.get(case_uid, [])),
                "source_identity_digest": source_digest,
                "v2_case_uid": str((new_case or {}).get("case_uid") or ""),
                "v2_target_turn_uid": str(explicit.get("target_turn_uid") or ""),
                "v2_target_text_digest": str(explicit.get("target_text_digest") or ""),
                "classification": classification,
                "migration_status": "migration_pending",
            })

    manifest = {
        "schema_version": "real-accuracy-gold-v2-migration-v1",
        "source_dataset_id": v1.get("dataset_id"),
        "source_dataset_version": v1.get("dataset_version"),
        "source_dataset_hash": (v1.get("manifest") or {}).get("content_sha256"),
        "target_dataset_id": v2.get("dataset_id"),
        "target_dataset_version": v2.get("dataset_version"),
        "target_dataset_hash": (v2.get("manifest") or {}).get("content_sha256"),
        "historical_label_db_sha256": label_db_sha256,
        "summary": {
            "total_old_approved_claims": old_approved_claim_count,
            "reusable_candidates": classifications["exact_target_reusable"],
            "manual_remap_required": classifications["manual_target_remap_required"],
            "missing_target": classifications["target_missing"],
            "ambiguous_target": classifications["target_ambiguous"],
            "incompatible_claim": classifications["claim_not_applicable_to_new_target"],
            "source_provenance_insufficient": classifications["source_provenance_insufficient"],
            "historical_rejected_claims": len(rejected_history),
            "migration_candidate_count": len(candidates),
            "migrated_approved_count": 0,
            "formal_kb_writes": 0,
            "can_send_changes": 0,
        },
        "candidates": sorted(candidates, key=lambda item: (item["v1_case_uid"], item["v1_claim_uid"])),
        "rejected_history": sorted(rejected_history, key=lambda item: (item["v1_case_uid"], item["v1_claim_uid"])),
    }
    manifest["migration_manifest_sha256"] = _stable_hash(manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-gold-set", required=True)
    parser.add_argument("--v2-gold-set", required=True)
    parser.add_argument("--v1-label-db", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    try:
        v1 = json.loads(Path(args.v1_gold_set).read_text(encoding="utf-8"))
        v2 = json.loads(Path(args.v2_gold_set).read_text(encoding="utf-8"))
        if validate_gold_dataset(v1) or validate_gold_dataset(v2):
            raise ValueError("gold_dataset_validation_failed")
        label_path = Path(args.v1_label_db)
        labels, events = _read_label_snapshot(label_path, str(v1.get("dataset_version") or ""))
        manifest = build_migration_manifest(
            v1,
            v2,
            labels,
            events,
            label_db_sha256=_file_sha256(label_path),
        )
        if scan_sensitive_data(manifest):
            raise ValueError("migration_manifest_privacy_validation_failed")
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest["summary"], ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
