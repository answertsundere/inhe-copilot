"""Inventory real-accuracy source readiness without emitting source records."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    _sqlite_readonly,
    classify_sample,
    load_reviewed_training_samples,
)


def _count(connection: sqlite3.Connection, query: str, params: tuple = ()) -> int:
    return int(connection.execute(query, params).fetchone()[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    samples = load_reviewed_training_samples(args.source_db)
    classifications = Counter(classify_sample(sample) for sample in samples)
    connection = _sqlite_readonly(args.source_db)
    try:
        inventory = {
            "reviewed_training_samples": {
                "count": len(samples),
                "customer_text_count": sum(1 for sample in samples if str(sample.get("customer_quote") or "").strip()),
                "conversation_context_count": sum(1 for sample in samples if str(sample.get("full_context") or "").strip()),
                "product_title_count": sum(1 for sample in samples if str(sample.get("product_title") or "").strip()),
                "sku_count": sum(1 for sample in samples if str(sample.get("sku") or "").strip()),
                "order_count": sum(1 for sample in samples if str(sample.get("order_no") or "").strip()),
                "reviewed_reference_answer_count": sum(1 for sample in samples if str(sample.get("correct_answer") or "").strip()),
                "media_requested_count": sum(1 for sample in samples if bool(sample.get("need_media"))),
                "classification_counts": dict(sorted(classifications.items())),
            },
            "formal_knowledge": {
                "published_product_count": _count(connection, "SELECT count(*) FROM kb_product WHERE status='published'"),
                "products_with_nonempty_specs": _count(connection, "SELECT count(*) FROM kb_product WHERE status='published' AND trim(coalesce(specs_json,'')) NOT IN ('', '{}', '[]')"),
                "published_kbqa_count": _count(connection, "SELECT count(*) FROM kb_qa WHERE status='published'"),
                "approved_media_count": _count(connection, "SELECT count(*) FROM kb_media_asset WHERE status='approved'"),
                "usable_media_count": _count(connection, "SELECT count(*) FROM kb_media_asset WHERE status='approved' AND usable_for_agent=1"),
                "published_knowledge_entry_count": _count(connection, "SELECT count(*) FROM knowledge_entries WHERE status='published'"),
                "ready_knowledge_chunk_count": _count(connection, "SELECT count(*) FROM knowledge_chunks"),
            },
            "privacy": {
                "source_records_emitted": 0,
                "raw_customer_text_emitted": False,
                "raw_identity_emitted": False,
                "access_mode": "sqlite_read_only",
            },
        }
    finally:
        connection.close()
    report = {
        "schema_version": "real-accuracy-source-inventory-v1",
        "source_kind": "runtime_sqlite_read_only",
        "inventory": inventory,
        "next_gate": "manual_claim_labeling_required" if classifications["accuracy_scorable"] < 30 else "claim_label_validation_required",
    }
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"reviewed": len(samples), "classification_counts": dict(classifications)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
