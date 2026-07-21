import json
import re
import sqlite3

import pytest

from app.services.real_derived_evidence_fixture_service import (
    RealDerivedFixtureError,
    build_real_derived_fixture,
    scan_fixture_privacy,
    source_inventory,
    validate_real_derived_fixture,
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
    assert manifest["qualification"]["passed"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["fixture_sha256"])
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", fact["provenance_hash"])
        for product in fixture["products"]
        for fact in product["facts"]
    )
    assert manifest["source_database_mutated"] is False
    assert source.read_bytes() == before
    assert all(item["identity"]["i_id"].startswith("fixture-iid-") for item in fixture["products"])
    assert "internal-1" not in json.dumps(fixture)
    assert scan_fixture_privacy(fixture)["passed"] is True
    assert fixture["source_kind"] == "real_derived"
    assert fixture["query_only"] is True
    assert validate_real_derived_fixture(fixture, manifest)["dataset_id"] == fixture["dataset_id"]


@pytest.mark.parametrize(
    ("fixture_change", "manifest_change", "reason"),
    [
        ({"source_kind": "synthetic", "real_derived": False, "dataset_id": "synthetic-product-evidence-v1"}, {}, "real_derived_source_kind_required"),
        ({"source_kind": "synthetic"}, {"source_kind": "synthetic"}, "real_derived_source_kind_required"),
        ({"source_snapshot_hash": ""}, {"source_snapshot_hash": ""}, "source_snapshot_hash_required"),
        ({"qualification": {"passed": False}}, {"qualification": {"passed": False}}, "fixture_qualification_failed"),
        ({}, {"fixture_sha256": "0" * 64}, "fixture_hash_mismatch"),
        ({}, {"privacy_scan": {"passed": False}}, "manifest_privacy_scan_failed"),
        ({"source_database_mutated": True}, {"source_database_mutated": True}, "source_database_mutation_detected"),
    ],
)
def test_real_derived_validation_rejects_synthetic_and_invalid_provenance(
    tmp_path, fixture_change, manifest_change, reason
):
    fixture, manifest = build_real_derived_fixture(_source_db(tmp_path), pseudonymization_key="test-key")
    fixture.update(fixture_change)
    manifest.update(manifest_change)

    with pytest.raises(RealDerivedFixtureError, match=reason):
        validate_real_derived_fixture(fixture, manifest)


def test_real_derived_validation_requires_manifest(tmp_path):
    fixture, _manifest = build_real_derived_fixture(_source_db(tmp_path), pseudonymization_key="test-key")

    with pytest.raises(RealDerivedFixtureError, match="manifest_required"):
        validate_real_derived_fixture(fixture, {})


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

    fixture, manifest = build_real_derived_fixture(source, pseudonymization_key="test-key")

    assert manifest["qualification"]["passed"] is False
    assert "dimensions" not in manifest["fact_type_counts"]
    assert all(
        fact["fact_type"] != "dimensions"
        for product in fixture["products"]
        for fact in product["facts"]
    )


def test_placeholder_values_are_not_exported_as_positive_evidence(tmp_path):
    source = _source_db(tmp_path)
    connection = sqlite3.connect(source)
    placeholder = "未在现有结构资料中明确尺寸"
    connection.execute(
        "UPDATE kb_product SET specs_json=? WHERE id=1",
        (json.dumps({"material": "PP", "size": placeholder}),),
    )
    connection.commit()
    connection.close()

    fixture, manifest = build_real_derived_fixture(source, pseudonymization_key="test-key")
    assert manifest["product_count"] == 5, manifest
    assert manifest["fact_count"] == 19, manifest
    for product in fixture["products"]:
        for fact in product["facts"]:
            assert "未在现有结构资料" not in fact["content"]
            assert "以详情页为准" not in fact["content"]


def test_sparse_real_fact_distribution_can_meet_dataset_minimum_without_placeholder_promotion(tmp_path):
    source = _source_db(tmp_path)
    connection = sqlite3.connect(source)
    placeholder = "已收录尺寸图，具体尺寸以尺寸图或商品详情页标注为准"
    connection.execute("UPDATE kb_product SET warranty_json=?", (json.dumps({}),))
    for index in range(2, 6):
        connection.execute(
            "UPDATE kb_product SET specs_json=? WHERE id=?",
            (json.dumps({"material": "PP", "size": placeholder}), index),
        )
    for index in range(6, 9):
        connection.execute(
            "INSERT INTO kb_product VALUES (?, ?, ?, ?, ?, ?, 'published')",
            (
                index,
                f"internal-{index}",
                json.dumps([{"sku_code": f"sku-{index}"}]),
                json.dumps({"material": "PP", "size": placeholder}),
                json.dumps({"gross_weight_kg": "1.2"}),
                json.dumps({}),
            ),
        )
    connection.commit()
    connection.close()

    fixture, manifest = build_real_derived_fixture(source, pseudonymization_key="test-key")

    assert manifest["qualification"]["passed"] is True
    assert manifest["product_count"] == 7
    assert manifest["fact_count"] == 15
    assert manifest["fact_type_counts"] == {"dimensions": 1, "gross_weight": 7, "material": 7}
    assert all(placeholder not in fact["content"] for product in fixture["products"] for fact in product["facts"])
