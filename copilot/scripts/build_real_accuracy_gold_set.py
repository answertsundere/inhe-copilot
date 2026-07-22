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
    build_gold_dataset_v2,
    load_reviewed_training_samples,
    upgrade_gold_dataset_v2,
    validate_gold_dataset,
)


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-db", help="Read-only SQLite source database")
    source.add_argument("--source-gold-set", help="Authoritative v0.1 Gold artifact used to derive v0.2")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--manual-queue-output", required=True)
    parser.add_argument("--hmac-env", default="COPILOT_GOLD_SET_HMAC_KEY")
    parser.add_argument("--dataset-version", choices=("0.1", "0.2"), default="0.1")
    args = parser.parse_args(argv)
    secret = os.environ.get(args.hmac_env, "")
    if not secret:
        print(json.dumps({"error": "gold_set_hmac_key_missing", "env": args.hmac_env}, ensure_ascii=False))
        return 2
    if args.source_gold_set:
        if args.dataset_version != "0.2":
            print(json.dumps({"error": "source_gold_set_requires_dataset_v0_2"}, ensure_ascii=False))
            return 2
        source_dataset = json.loads(Path(args.source_gold_set).read_text(encoding="utf-8"))
        dataset, queue = upgrade_gold_dataset_v2(secret, source_dataset)
    else:
        samples = load_reviewed_training_samples(args.source_db)
        builder = build_gold_dataset_v2 if args.dataset_version == "0.2" else build_gold_dataset
        dataset, queue = builder(secret, samples)
    findings = validate_gold_dataset(dataset)
    if findings:
        print(json.dumps({"error": "gold_set_validation_failed", "findings": findings}, ensure_ascii=False))
        return 2
    write_json(Path(args.json_output), dataset)
    write_json(Path(args.manual_queue_output), {
        "schema_version": (
            "real-accuracy-manual-label-queue-v2"
            if args.dataset_version == "0.2"
            else "real-accuracy-manual-label-queue-v1"
        ),
        "dataset_id": dataset["dataset_id"],
        "dataset_hash": dataset["manifest"]["content_sha256"],
        "items": queue,
    })
    print(json.dumps({"summary": dataset["summary"], "dataset_status": dataset["dataset_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
