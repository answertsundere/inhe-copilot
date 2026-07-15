import json
import sqlite3

import pytest

from app.services.real_derived_evidence_fixture_service import (
    RealDerivedFixtureError,
    build_real_derived_fixture,
    scan_fixture_privacy,
    source_inventory,
)


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


def test_inventory_and_export_are_read_only_and_pseudonymous(tmp_path):
    source = _source_db(tmp_path)
    before = source.read_bytes()

    inventory = source_inventory(source)
    fixture, manifest = build_real_derived_fixture(source, pseudonymization_key="test-key")

    assert inventory["query_only"] is True
    assert manifest["product_count"] == 5
    assert manifest["fact_count"] == 20
    assert manifest["source_database_mutated"] is False
    assert source.read_bytes() == before
    assert all(item["identity"]["i_id"].startswith("fixture-iid-") for item in fixture["products"])
    assert "internal-1" not in json.dumps(fixture)
    assert scan_fixture_privacy(fixture)["passed"] is True


def test_export_requires_a_key_and_rejects_sensitive_customer_data(tmp_path):
    source = _source_db(tmp_path)
    with pytest.raises(RealDerivedFixtureError, match="pseudonymization_key_required"):
        build_real_derived_fixture(source, pseudonymization_key="")

    connection = sqlite3.connect(source)
    connection.execute("UPDATE kb_product SET specs_json=? WHERE id=1", (json.dumps({"material": "call 13800138000"}),))
    connection.commit()
    connection.close()
    fixture, _manifest = build_real_derived_fixture(source, pseudonymization_key="test-key", limit_products=4)
    assert len(fixture["products"]) == 4


def test_missing_source_fails_closed(tmp_path):
    with pytest.raises(RealDerivedFixtureError, match="source_database_unavailable"):
        source_inventory(tmp_path / "missing.sqlite")


def test_mixed_packaging_dimension_candidate_is_not_exported(tmp_path):
    source = _source_db(tmp_path)
    connection = sqlite3.connect(source)
    connection.execute(
        "UPDATE kb_product SET specs_json=?",
        (json.dumps({"size": "80cm", "carton_length_cm": "90cm"}),),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RealDerivedFixtureError, match="no_eligible_real_derived_products"):
        build_real_derived_fixture(source, pseudonymization_key="test-key")
