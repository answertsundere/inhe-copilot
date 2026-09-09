from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "build_jst_snapshot_order_projection.py"


def _projection_module():
    spec = importlib.util.spec_from_file_location("jst_snapshot_order_projection", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_projection_keeps_only_exact_product_identity_and_manifest_hashes(tmp_path):
    source = tmp_path / "shipments.jsonl"
    private_phone = "13900001234"
    private_address = "example street 123"
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "o_id": "internal-order-1",
                        "buyer_id": "buyer-private-id",
                        "receiver_phone": private_phone,
                        "receiver_address": private_address,
                        "items": [
                            {
                                "outer_oi_id": "external-item-1",
                                "sku_id": "SKU-EXACT-1",
                                "i_id": "INTERNAL-PRODUCT-1",
                                "name": "private product label",
                                "buyer_note": "private note",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "o_id": "internal-order-2",
                        "items": [
                            {
                                "outer_oi_id": "external-item-2",
                                "sku_id": "SKU-EXACT-2",
                                "i_id": "INTERNAL-PRODUCT-2",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    module = _projection_module()
    first = module.build_projection(source, tmp_path / "first")
    second = module.build_projection(source, tmp_path / "second")

    first_orders_path = tmp_path / "first" / "orders.json"
    first_manifest_path = tmp_path / "first" / "snapshot_order_projection.manifest.json"
    orders = json.loads(first_orders_path.read_text(encoding="utf-8"))
    manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
    serialized = first_orders_path.read_text(encoding="utf-8")

    assert first["order_count"] == 2
    assert first["projection_sha256"] == second["projection_sha256"]
    assert serialized == (tmp_path / "second" / "orders.json").read_text(encoding="utf-8")
    assert all(record["snapshot_identity_only"] is True for record in orders)
    projected_items = {
        item["outer_oi_id"]: item
        for record in orders
        for item in record["items"]
    }
    assert projected_items == {
        "external-item-1": {
            "i_id": "INTERNAL-PRODUCT-1",
            "outer_oi_id": "external-item-1",
            "sku_id": "SKU-EXACT-1",
        },
        "external-item-2": {
            "i_id": "INTERNAL-PRODUCT-2",
            "outer_oi_id": "external-item-2",
            "sku_id": "SKU-EXACT-2",
        },
    }
    assert manifest["schema_version"] == "jst_snapshot_order_projection/v1"
    assert manifest["source_basename"] == "shipments.jsonl"
    assert manifest["projection_sha256"] == hashlib.sha256(first_orders_path.read_bytes()).hexdigest()
    assert private_phone not in serialized
    assert private_address not in serialized
    assert "buyer-private-id" not in serialized
    assert "private product label" not in serialized
    assert "private note" not in serialized
    assert "receiver_phone" not in serialized
    assert "receiver_address" not in serialized
    assert "buyer_id" not in serialized


def test_projection_with_order_reference_secret_emits_only_hmac_order_lookup(tmp_path):
    source = tmp_path / "shipments.jsonl"
    raw_order_reference = "internal-order-reference-private"
    lookup_secret = "test-order-reference-secret"
    source.write_text(
        json.dumps(
            {
                "o_id": raw_order_reference,
                "receiver_phone": "13900001234",
                "items": [
                    {
                        "outer_oi_id": "external-item-1",
                        "sku_id": "SKU-EXACT-1",
                        "i_id": "INTERNAL-PRODUCT-1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    module = _projection_module()
    module.build_projection(
        source,
        tmp_path / "projection",
        order_reference_secret=lookup_secret,
    )

    orders_path = tmp_path / "projection" / "orders.json"
    manifest_path = tmp_path / "projection" / "snapshot_order_projection.manifest.json"
    orders = json.loads(orders_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    serialized = orders_path.read_text(encoding="utf-8")
    expected_hmac = hmac.new(
        lookup_secret.encode("utf-8"),
        raw_order_reference.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert manifest["schema_version"] == "jst_snapshot_order_projection/v2"
    assert manifest["order_reference_hmac_algorithm"] == "hmac-sha256"
    assert orders == [
        {
            "snapshot_record_uid": orders[0]["snapshot_record_uid"],
            "snapshot_identity_only": True,
            "order_reference_hmac": expected_hmac,
            "items": [
                {
                    "outer_oi_id": "external-item-1",
                    "sku_id": "SKU-EXACT-1",
                    "i_id": "INTERNAL-PRODUCT-1",
                }
            ],
        }
    ]
    assert raw_order_reference not in serialized
    assert "receiver_phone" not in serialized


def test_hmac_order_reference_projection_is_stable_for_reordered_order_items(tmp_path):
    lookup_secret = "stable-order-reference-secret"
    rows = [
        {
            "o_id": "internal-order-reference-private",
            "items": [
                {
                    "outer_oi_id": "external-item-b",
                    "sku_id": "SKU-B",
                    "i_id": "INTERNAL-B",
                }
            ],
        },
        {
            "o_id": "internal-order-reference-private",
            "items": [
                {
                    "outer_oi_id": "external-item-a",
                    "sku_id": "SKU-A",
                    "i_id": "INTERNAL-A",
                }
            ],
        },
    ]
    first_source = tmp_path / "first.jsonl"
    second_source = tmp_path / "second.jsonl"
    first_source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    second_source.write_text("\n".join(json.dumps(row) for row in reversed(rows)), encoding="utf-8")

    module = _projection_module()
    first = module.build_projection(
        first_source,
        tmp_path / "first",
        order_reference_secret=lookup_secret,
    )
    second = module.build_projection(
        second_source,
        tmp_path / "second",
        order_reference_secret=lookup_secret,
    )

    assert first["order_count"] == 1
    assert first["eligible_item_count"] == 2
    assert first["deduplicated_identical_item_count"] == 0
    assert first["projection_sha256"] == second["projection_sha256"]
    assert (tmp_path / "first" / "orders.json").read_bytes() == (
        tmp_path / "second" / "orders.json"
    ).read_bytes()


def test_projection_rejects_existing_output_without_explicit_overwrite(tmp_path):
    source = tmp_path / "shipments.jsonl"
    source.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "outer_oi_id": "external-item-1",
                        "sku_id": "SKU-EXACT-1",
                        "i_id": "INTERNAL-PRODUCT-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    module = _projection_module()
    output_dir = tmp_path / "projection"
    module.build_projection(source, output_dir)

    try:
        module.build_projection(source, output_dir)
    except FileExistsError as exc:
        assert str(exc) == "projection_output_exists"
    else:
        raise AssertionError("existing output must require explicit overwrite")


def test_projection_deduplicates_repeated_exact_item_identity_but_keeps_conflicts(tmp_path):
    source = tmp_path / "shipments.jsonl"
    rows = [
        {
            "items": [{"outer_oi_id": "same-item", "sku_id": "SKU-A", "i_id": "PRODUCT-A"}],
        },
        {
            "items": [{"outer_oi_id": "same-item", "sku_id": "SKU-A", "i_id": "PRODUCT-A"}],
        },
        {
            "items": [{"outer_oi_id": "conflicting-item", "sku_id": "SKU-B", "i_id": "PRODUCT-B"}],
        },
        {
            "items": [{"outer_oi_id": "conflicting-item", "sku_id": "SKU-C", "i_id": "PRODUCT-C"}],
        },
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    module = _projection_module()
    summary = module.build_projection(source, tmp_path / "projection")
    orders = json.loads((tmp_path / "projection" / "orders.json").read_text(encoding="utf-8"))
    items_by_external_id = {}
    for record in orders:
        item = record["items"][0]
        items_by_external_id.setdefault(item["outer_oi_id"], []).append(item)

    assert summary["order_count"] == 3
    assert summary["duplicate_outer_oi_id_count"] == 1
    assert summary["deduplicated_identical_item_count"] == 1
    assert items_by_external_id["same-item"] == [
        {"outer_oi_id": "same-item", "sku_id": "SKU-A", "i_id": "PRODUCT-A"}
    ]
    assert items_by_external_id["conflicting-item"] == [
        {"outer_oi_id": "conflicting-item", "sku_id": "SKU-B", "i_id": "PRODUCT-B"},
        {"outer_oi_id": "conflicting-item", "sku_id": "SKU-C", "i_id": "PRODUCT-C"},
    ]
