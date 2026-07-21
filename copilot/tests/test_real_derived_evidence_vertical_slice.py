import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def test_vertical_slice_uses_pack_convergence_and_keeps_preview_review_only(tmp_path):
    fixture = {
        "dataset_id": "real-derived-product-evidence-v1",
        "dataset_version": "1.0.0",
        "schema_version": "real-derived-evidence-fixture-v2",
        "source_kind": "real_derived",
        "real_derived": True,
        "sanitization_version": "hmac-sha256-v1",
        "source_snapshot_hash": "0" * 64,
        "source_type": "published_kb_product_structured_fields",
        "query_only": True,
        "source_database_mutated": False,
        "qualification": {
            "minimum_product_count": 1,
            "minimum_facts_per_product": 1,
            "minimum_total_fact_count": 1,
            "minimum_fact_type_count": 1,
            "product_count": 1,
            "fact_count": 1,
            "fact_type_count": 1,
            "passed": True,
        },
        "products": [{
            "identity": {"i_id": "fixture-iid-a", "sku_code": "fixture-sku-a"},
            "facts": [{
                "evidence_uid": "real-a",
                "fact_type": "material",
                "attribute_key": "material",
                "content": "PP",
                "provenance_hash": "a" * 64,
            }],
        }],
    }
    fixture_hash = hashlib.sha256(
        json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        key: fixture[key]
        for key in (
            "dataset_id", "dataset_version", "schema_version", "source_kind", "real_derived",
            "source_type", "source_snapshot_hash", "sanitization_version", "query_only",
            "source_database_mutated",
        )
    }
    manifest.update({"fixture_sha256": fixture_hash, "privacy_scan": {"passed": True}})
    manifest["qualification"] = fixture["qualification"]
    fixture_path = tmp_path / "fixture.json"
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "report.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_real_derived_evidence_vertical_slice.py",
            "--fixture", str(fixture_path),
            "--manifest", str(manifest_path),
            "--work-db", str(tmp_path / "vertical.sqlite"),
            "--json-output", str(output_path),
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project), "PYTHONUTF8": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["passed"] == 1
    assert report["negative_controls"]["case_count"] == 7
    assert report["negative_controls"]["passed_count"] == 7
    assert report["negative_controls"]["leak_count"] == 0
    conflict = next(
        item for item in report["negative_controls"]["cases"]
        if item["kind"] == "conflicting_value"
    )
    assert conflict["selected_count"] == 0
    assert "conflicting_evidence" in conflict["rejection_reasons"]
    assert report["safety"] == {
        "can_send_change_count": 0,
        "formal_reply_mutation_count": 0,
        "requires_human_review_count": 1,
        "used_for_final_reply_count": 0,
    }
