import hashlib
import hmac
import json


def _write_orders(tmp_path, orders, *, include_manifest=True, manifest_overrides=None):
    orders_path = tmp_path / "orders.json"
    orders_path.write_text(
        json.dumps(orders, ensure_ascii=False),
        encoding="utf-8",
    )
    if include_manifest:
        manifest = {
            "dataset_id": "jst_snapshot_order_projection",
            "schema_version": "jst_snapshot_order_projection/v1",
            "source_basename": "fixture.jsonl",
            "source_sha256": "a" * 64,
            "projection_sha256": hashlib.sha256(orders_path.read_bytes()).hexdigest(),
            "order_count": len(orders),
            "generated_at": "2026-01-01T00:00:00+00:00",
            "privacy_projection": {"identity_only": True},
        }
        manifest.update(manifest_overrides or {})
        (tmp_path / "snapshot_order_projection.manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )


def _write_hmac_order_projection(tmp_path, *, order_reference: str, lookup_secret: str):
    orders_path = tmp_path / "orders.json"
    order_reference_hmac = hmac.new(
        lookup_secret.encode("utf-8"),
        order_reference.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    orders = [
        {
            "snapshot_record_uid": "a" * 32,
            "snapshot_identity_only": True,
            "order_reference_hmac": order_reference_hmac,
            "items": [
                {
                    "outer_oi_id": "platform-item-1",
                    "sku_id": "SKU-EXACT-1",
                    "i_id": "INTERNAL-1",
                }
            ],
        }
    ]
    orders_path.write_text(json.dumps(orders, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "dataset_id": "jst_snapshot_order_projection",
        "schema_version": "jst_snapshot_order_projection/v2",
        "source_basename": "fixture.jsonl",
        "source_sha256": "a" * 64,
        "projection_sha256": hashlib.sha256(orders_path.read_bytes()).hexdigest(),
        "order_count": len(orders),
        "generated_at": "2026-01-01T00:00:00+00:00",
        "order_reference_hmac_algorithm": "hmac-sha256",
        "privacy_projection": {"identity_only": True},
    }
    (tmp_path / "snapshot_order_projection.manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_snapshot_order_repository_resolves_hmac_sidebar_order_reference(tmp_path, monkeypatch):
    from app.repositories import json_order_repository as module

    lookup_secret = "fixture-lookup-secret"
    side_bar_order_reference = "sidebar-order-reference-private"
    _write_hmac_order_projection(
        tmp_path,
        order_reference=side_bar_order_reference,
        lookup_secret=lookup_secret,
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_SECRET", lookup_secret)

    repository = module.JsonOrderRepository()
    repository.load()

    order = repository.get_order_by_snapshot_order_reference(side_bar_order_reference)

    assert order["snapshot_identity_only"] is True
    assert order["identity_source"] == "jst_snapshot_order_reference"
    assert order["matched_item_reason"] == "exact_jst_snapshot_order_reference"
    assert order["matched_item"]["sku_id"] == "SKU-EXACT-1"
    assert side_bar_order_reference not in json.dumps(order, ensure_ascii=False)


def test_snapshot_order_repository_rejects_hmac_reference_when_lookup_secret_differs(tmp_path, monkeypatch):
    from app.repositories import json_order_repository as module

    _write_hmac_order_projection(
        tmp_path,
        order_reference="sidebar-order-reference-private",
        lookup_secret="projection-secret",
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_SECRET", "wrong-secret")

    repository = module.JsonOrderRepository()
    repository.load()

    assert repository.get_order_by_snapshot_order_reference("sidebar-order-reference-private") is None


def test_snapshot_order_repository_resolves_one_exact_external_item_reference(
    tmp_path,
    monkeypatch,
):
    from app.repositories import json_order_repository as module

    _write_orders(
        tmp_path,
        [
            {
                "snapshot_record_uid": "a" * 32,
                "snapshot_identity_only": True,
                "items": [
                    {
                        "outer_oi_id": "platform-item-1",
                        "sku_id": "SKU-EXACT-1",
                        "i_id": "INTERNAL-1",
                    }
                ],
            }
        ],
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")

    repository = module.JsonOrderRepository()
    repository.load()

    order = repository.get_order_by_external_item_id("platform-item-1")

    assert order["snapshot_identity_only"] is True
    assert order["identity_source"] == "jst_snapshot_order_items"
    assert order["matched_item_reason"] == "exact_jst_snapshot_order_item"
    assert order["matched_item"] == order["items"][0]
    assert order["matched_item"]["sku_id"] == "SKU-EXACT-1"


def test_snapshot_order_repository_rejects_duplicate_external_item_references(
    tmp_path,
    monkeypatch,
):
    from app.repositories import json_order_repository as module

    _write_orders(
        tmp_path,
        [
            {
                "snapshot_record_uid": "a" * 32,
                "snapshot_identity_only": True,
                "items": [{"outer_oi_id": "duplicate-item", "sku_id": "SKU-1", "i_id": "PRODUCT-1"}],
            },
            {
                "snapshot_record_uid": "b" * 32,
                "snapshot_identity_only": True,
                "items": [{"outer_oi_id": "duplicate-item", "sku_id": "SKU-2", "i_id": "PRODUCT-2"}],
            },
        ],
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")

    repository = module.JsonOrderRepository()
    repository.load()

    assert repository.get_order_by_external_item_id("duplicate-item") is None


def test_snapshot_order_repository_rebuilds_exact_index_on_reload(
    tmp_path,
    monkeypatch,
):
    from app.repositories import json_order_repository as module

    _write_orders(
        tmp_path,
        [
            {
                "snapshot_record_uid": "a" * 32,
                "snapshot_identity_only": True,
                "items": [{"outer_oi_id": "platform-item-1", "sku_id": "SKU-1", "i_id": "PRODUCT-1"}],
            }
        ],
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")

    repository = module.JsonOrderRepository()
    repository.load()
    repository.load()

    assert repository.get_order_by_external_item_id("platform-item-1")["snapshot_record_uid"] == "a" * 32


def test_snapshot_order_repository_does_not_load_sample_live_state(tmp_path, monkeypatch):
    from app.repositories import json_order_repository as module

    projection_dir = tmp_path / "projection"
    sample_dir = tmp_path / "samples"
    projection_dir.mkdir()
    sample_dir.mkdir()
    _write_orders(
        projection_dir,
        [
            {
                "snapshot_record_uid": "a" * 32,
                "snapshot_identity_only": True,
                "items": [{"outer_oi_id": "platform-item-1", "sku_id": "SKU-1", "i_id": "PRODUCT-1"}],
            }
        ],
    )
    (sample_dir / "sample_logistics.json").write_text(
        json.dumps([{"o_id": "sample-order", "tracking_no": "sample-tracking"}]),
        encoding="utf-8",
    )
    (sample_dir / "sample_refunds.json").write_text(
        json.dumps([{"o_id": "sample-order", "status": "sample-refund"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(projection_dir))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(sample_dir))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")

    repository = module.JsonOrderRepository()
    repository.load()

    assert repository.count_logistics() == 0
    assert repository.count_refunds() == 0
    assert repository.count_aftersale() == 0


def test_snapshot_order_repository_rejects_snapshot_orders_without_manifest(
    tmp_path,
    monkeypatch,
):
    from app.repositories import json_order_repository as module

    _write_orders(
        tmp_path,
        [
            {
                "snapshot_record_uid": "a" * 32,
                "snapshot_identity_only": True,
                "items": [{"outer_oi_id": "platform-item-1", "sku_id": "SKU-1", "i_id": "PRODUCT-1"}],
            }
        ],
        include_manifest=False,
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")

    repository = module.JsonOrderRepository()
    repository.load()

    assert repository.get_order_by_external_item_id("platform-item-1") is None


def test_snapshot_order_repository_rejects_tampered_projection_manifest(
    tmp_path,
    monkeypatch,
):
    from app.repositories import json_order_repository as module

    _write_orders(
        tmp_path,
        [
            {
                "snapshot_record_uid": "a" * 32,
                "snapshot_identity_only": True,
                "items": [{"outer_oi_id": "platform-item-1", "sku_id": "SKU-1", "i_id": "PRODUCT-1"}],
            }
        ],
        manifest_overrides={"projection_sha256": "0" * 64},
    )
    monkeypatch.setattr(module, "EXTERNAL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "SAMPLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "true")

    repository = module.JsonOrderRepository()
    repository.load()

    assert repository.get_order_by_external_item_id("platform-item-1") is None
