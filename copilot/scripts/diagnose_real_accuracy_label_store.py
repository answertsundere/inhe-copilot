"""Report a content-free identity and count summary for a Gold label store."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def diagnose(path: Path, dataset_version: str) -> dict:
    result = {
        "file_name": path.name,
        "exists": path.is_file(),
        "sha256": _sha256(path) if path.is_file() else None,
        "dataset_version": dataset_version,
        "record_count": 0,
        "claim_counts": {status: 0 for status in ("draft", "reviewed", "approved", "rejected")},
        "event_count": 0,
    }
    if not path.is_file():
        return result
    resolved = path.resolve()
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        labels = connection.execute(
            "SELECT review_status,label_json FROM real_accuracy_case_label WHERE dataset_version=?",
            (dataset_version,),
        ).fetchall()
        result["record_count"] = len(labels)
        for status, label_json in labels:
            claims = json.loads(label_json).get("claims") or []
            if status in result["claim_counts"]:
                result["claim_counts"][status] += len(claims)
        result["event_count"] = int(connection.execute(
            "SELECT count(*) FROM real_accuracy_label_event WHERE dataset_version=?",
            (dataset_version,),
        ).fetchone()[0])
        return result
    finally:
        connection.close()


def diagnose_config(path: Path, dataset_version: str) -> dict:
    """Resolve Gold paths without exposing their directory or any other env value."""
    keys = {
        "COPILOT_REAL_ACCURACY_GOLD_SET_PATH": [],
        "COPILOT_REAL_ACCURACY_LABEL_DB": [],
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in keys:
            keys[key].append(value.strip().strip('"').strip("'"))

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else path.parent / candidate

    gold_values = keys["COPILOT_REAL_ACCURACY_GOLD_SET_PATH"]
    label_values = keys["COPILOT_REAL_ACCURACY_LABEL_DB"]
    gold_path = resolve(gold_values[0]) if len(gold_values) == 1 else None
    label_path = resolve(label_values[0]) if len(label_values) == 1 else None
    gold_summary = {
        "file_name": gold_path.name if gold_path else None,
        "exists": bool(gold_path and gold_path.is_file()),
        "sha256": _sha256(gold_path) if gold_path and gold_path.is_file() else None,
    }
    if gold_path and gold_path.is_file():
        payload = json.loads(gold_path.read_text(encoding="utf-8"))
        gold_summary.update({
            "dataset_id": payload.get("dataset_id"),
            "dataset_version": payload.get("dataset_version"),
            "content_sha256": (payload.get("manifest") or {}).get("content_sha256"),
            "case_count": len(payload.get("cases") or []),
        })
    label_summary = diagnose(label_path, dataset_version) if label_path else {
        "file_name": None,
        "exists": False,
        "sha256": None,
        "dataset_version": dataset_version,
        "record_count": 0,
        "claim_counts": {status: 0 for status in ("draft", "reviewed", "approved", "rejected")},
        "event_count": 0,
    }
    definition_counts = {key: len(values) for key, values in keys.items()}
    return {
        "config_file_name": path.name,
        "config_status": (
            "ready"
            if all(count == 1 for count in definition_counts.values())
            and gold_summary["exists"]
            and label_summary["exists"]
            else "invalid"
        ),
        "definition_counts": definition_counts,
        "gold_set": gold_summary,
        "label_store": label_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--label-db")
    source.add_argument("--env-file")
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--json-output")
    args = parser.parse_args(argv)
    try:
        result = (
            diagnose_config(Path(args.env_file), args.dataset_version)
            if args.env_file
            else diagnose(Path(args.label_db), args.dataset_version)
        )
        if args.json_output:
            output = Path(args.json_output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        available = result.get("config_status") == "ready" if args.env_file else result["exists"]
        return 0 if available else 2
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
