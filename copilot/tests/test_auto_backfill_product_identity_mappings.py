from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.eval_sanitizer_service import hash_sensitive


@pytest.fixture()
def identity_db(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBProduct, ProductIdentityMapping

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine, tables=[KBProduct.__table__, ProductIdentityMapping.__table__])
    return session_factory


def _add_product(db, *, i_id="YH10K01", sku_code="YH10K01B01S01"):
    from app.models.kb_tables import KBProduct

    product = KBProduct(i_id=i_id, product_name="trusted product", status="published")
    product.set_sku_list([{"sku_code": sku_code}])
    db.add(product)
    db.commit()
    return product


def _write_rows(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_identity_mapping_dry_run_does_not_write(identity_db, tmp_path):
    from app.models.kb_tables import ProductIdentityMapping
    from scripts.auto_backfill_product_identity_mappings import run_backfill

    db = identity_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "identity.json"
    _write_rows(source, [{"platform_item_id": "123456789", "i_id": "YH10K01", "confirmation_status": "已确认"}])

    result = run_backfill(str(source), apply=False, db_factory=identity_db)

    assert result["matched_count"] == 1
    assert result["written_mapping_count"] == 1
    db = identity_db()
    try:
        assert db.query(ProductIdentityMapping).count() == 0
    finally:
        db.close()


def test_identity_mapping_apply_writes_active_mapping(identity_db, tmp_path):
    from app.models.kb_tables import ProductIdentityMapping
    from scripts.auto_backfill_product_identity_mappings import run_backfill

    db = identity_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "identity.json"
    _write_rows(source, [{"platform_item_id": "123456789", "i_id": "YH10K01", "confirmation_status": "confirmed"}])

    result = run_backfill(str(source), apply=True, db_factory=identity_db)

    assert result["written_mapping_count"] == 1
    db = identity_db()
    try:
        mapping = db.query(ProductIdentityMapping).one()
        assert mapping.status == "active"
        assert mapping.platform_item_id == "123456789"
        assert mapping.platform_item_id_hash == hash_sensitive("123456789")
        assert mapping.i_id == "YH10K01"
        assert mapping.get_metadata()["writes_verified_knowledge"] is False
    finally:
        db.close()


def test_identity_mapping_skips_title_only_weak_match(identity_db, tmp_path):
    from scripts.auto_backfill_product_identity_mappings import run_backfill

    db = identity_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "identity.json"
    _write_rows(source, [{"platform_product_title": "trusted product", "confirmation_status": "已确认"}])

    result = run_backfill(str(source), apply=True, db_factory=identity_db)

    assert result["matched_count"] == 0
    assert result["skipped_reasons"][0]["reason"] == "missing_platform_identity"


def test_identity_mapping_skips_conflicting_existing_mapping(identity_db, tmp_path):
    from app.models.kb_tables import ProductIdentityMapping
    from scripts.auto_backfill_product_identity_mappings import run_backfill

    item_hash = hash_sensitive("123456789")
    db = identity_db()
    try:
        first = _add_product(db, i_id="YH10K01", sku_code="YH10K01B01S01")
        _add_product(db, i_id="YH10K02", sku_code="YH10K02B01S01")
        db.add(ProductIdentityMapping(
            mapping_uid="pim_existing",
            platform_item_id_hash=item_hash,
            kb_product_id=first.id,
            i_id=first.i_id,
            status="active",
        ))
        db.commit()
    finally:
        db.close()
    source = tmp_path / "identity.json"
    _write_rows(source, [{"platform_item_id": "123456789", "i_id": "YH10K02", "confirmation_status": "confirmed"}])

    result = run_backfill(str(source), apply=True, db_factory=identity_db)

    assert result["conflict_count"] == 1
    assert result["written_mapping_count"] == 0
