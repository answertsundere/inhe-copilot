import json
import os
import subprocess
import sys
from pathlib import Path


def test_vertical_slice_uses_pack_convergence_and_keeps_preview_review_only(tmp_path):
    fixture = {
        "dataset_id": "real-derived-test",
        "real_derived": True,
        "products": [{
            "identity": {"i_id": "fixture-iid-a", "sku_code": "fixture-sku-a"},
            "facts": [{
                "evidence_uid": "real-a",
                "fact_type": "material",
                "attribute_key": "material",
                "content": "PP",
                "provenance_hash": "hash-a",
            }],
        }],
    }
    fixture_path = tmp_path / "fixture.json"
    output_path = tmp_path / "report.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    project = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(project), "PYTHONUTF8": "1"}
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_real_derived_evidence_vertical_slice.py",
            "--fixture", str(fixture_path),
            "--work-db", str(tmp_path / "vertical.sqlite"),
            "--json-output", str(output_path),
        ],
        cwd=project,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["passed"] == 1
    assert report["safety"] == {
        "can_send_change_count": 0,
        "formal_reply_mutation_count": 0,
        "requires_human_review_count": 1,
        "used_for_final_reply_count": 0,
    }
