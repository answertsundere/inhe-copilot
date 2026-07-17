"""Build a sanitized, read-only Gold Set from reviewed training samples."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    build_gold_dataset,
    load_reviewed_training_samples,
    validate_gold_dataset,
)


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, help="Read-only SQLite source database")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--manual-queue-output", required=True)
    parser.add_argument("--hmac-env", default="COPILOT_GOLD_SET_HMAC_KEY")
    args = parser.parse_args(argv)
    secret = os.environ.get(args.hmac_env, "")
    if not secret:
        print(json.dumps({"error": "gold_set_hmac_key_missing", "env": args.hmac_env}, ensure_ascii=False))
        return 2
    samples = load_reviewed_training_samples(args.source_db)
    dataset, queue = build_gold_dataset(secret, samples)
    findings = validate_gold_dataset(dataset)
    if findings:
        print(json.dumps({"error": "gold_set_validation_failed", "findings": findings}, ensure_ascii=False))
        return 3
    write_json(Path(args.json_output), dataset)
    write_json(Path(args.manual_queue_output), {
        "schema_version": "real-accuracy-manual-label-queue-v1",
        "dataset_id": dataset["dataset_id"],
        "dataset_hash": dataset["manifest"]["content_sha256"],
        "items": queue,
    })
    print(json.dumps({"summary": dataset["summary"], "dataset_status": dataset["dataset_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
