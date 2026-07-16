import json
import sqlite3
import sys

from app.services.real_derived_evidence_fixture_service import build_real_derived_fixture
from scripts.run_real_derived_evidence_vertical_slice import _load, main


def _source_db(tmp_path):
    path = tmp_path / "formal.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE kb_product (id INTEGER PRIMARY KEY, i_id TEXT, sku_list_json TEXT, specs_json TEXT, logistics_json TEXT, warranty_json TEXT, status TEXT)"
    )
    for index in range(1, 6):
        connection.execute(
            "INSERT INTO kb_product VALUES (?, ?, ?, ?, ?, ?, 'published')",
            (
                index,
                f"internal-{index}",
                json.dumps([{"sku_code": f"sku-{index}"}]),
                json.dumps({"material": "PP", "size": "80cm"}),
                json.dumps({"gross_weight_kg": "1.2"}),
                json.dumps({"detachable": "yes"}),
            ),
        )
    connection.commit()
    connection.close()
    return path


def test_runner_loads_only_a_manifest_matched_real_derived_fixture(tmp_path):
    fixture, manifest = build_real_derived_fixture(_source_db(tmp_path), pseudonymization_key="test-key")
    fixture_path = tmp_path / "fixture.json"
    manifest_path = tmp_path / "manifest.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = _load(str(fixture_path), str(manifest_path))

    assert loaded["source_kind"] == "real_derived"


def test_runner_returns_two_for_synthetic_or_missing_manifest(monkeypatch, tmp_path):
    fixture, manifest = build_real_derived_fixture(_source_db(tmp_path), pseudonymization_key="test-key")
    fixture["source_kind"] = "synthetic"
    fixture["real_derived"] = False
    fixture_path = tmp_path / "fixture.json"
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "result.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_real_derived_evidence_vertical_slice.py",
            "--fixture", str(fixture_path),
            "--manifest", str(manifest_path),
            "--work-db", str(tmp_path / "work.sqlite"),
            "--json-output", str(output_path),
        ],
    )

    assert main() == 2
    assert not output_path.exists()

    monkeypatch.setattr(sys, "argv", [
        "run_real_derived_evidence_vertical_slice.py",
        "--fixture", str(fixture_path),
        "--manifest", str(tmp_path / "missing.json"),
        "--work-db", str(tmp_path / "work.sqlite"),
        "--json-output", str(output_path),
    ])
    assert main() == 2
