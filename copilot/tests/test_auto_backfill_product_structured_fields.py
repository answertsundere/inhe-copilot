from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def structured_db(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBProduct

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


def _add_product(db, *, material="", dimensions=""):
    from app.models.kb_tables import KBProduct

    product = KBProduct(i_id="YH20K01", product_name="field product", status="published")
    product.set_sku_list([{"sku_code": "YH20K01B01S01"}])
    specs = {}
    if material:
        specs["material"] = material
    if dimensions:
        specs["dimensions"] = dimensions
    product.set_specs(specs)
    db.add(product)
    db.commit()
    return product


def _write_rows(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_structured_backfill_dry_run_does_not_write(structured_db, tmp_path):
    from scripts.auto_backfill_product_structured_fields import run_backfill

    db = structured_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "fields.json"
    _write_rows(source, [{"i_id": "YH20K01", "material": "PP", "gross_weight": "2.5kg"}])

    result = run_backfill(str(source), apply=False, db_factory=structured_db)

    assert result["field_updated_count"] == 2
    db = structured_db()
    try:
        product = db.query(__import__("app.models.kb_tables", fromlist=["KBProduct"]).KBProduct).one()
        assert product.get_specs() == {}
        assert product.get_logistics() == {}
    finally:
        db.close()


def test_structured_backfill_fills_empty_fields(structured_db, tmp_path):
    from app.models.kb_tables import KBProduct
    from scripts.auto_backfill_product_structured_fields import run_backfill

    db = structured_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "fields.json"
    _write_rows(source, [{"sku_code": "YH20K01B01S01", "material": "PP", "dimensions": "100x40x80cm", "gross_weight": "2.5kg"}])

    result = run_backfill(str(source), apply=True, db_factory=structured_db)

    assert result["product_updated_count"] == 1
    assert result["field_updated_count"] == 3
    db = structured_db()
    try:
        product = db.query(KBProduct).one()
        assert product.get_specs()["material"] == "PP"
        assert product.get_specs()["dimensions"] == "100x40x80cm"
        assert product.get_logistics()["gross_weight_kg"] == "2.5kg"
    finally:
        db.close()


def test_structured_backfill_returns_published_product_to_review(structured_db, tmp_path):
    from app.models.kb_tables import KBChangeLog, KBProduct
    from scripts.auto_backfill_product_structured_fields import run_backfill

    db = structured_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "fields.json"
    _write_rows(source, [{"i_id": "YH20K01", "material": "PP"}])

    result = run_backfill(str(source), apply=True, db_factory=structured_db)

    assert result["product_returned_to_review_count"] == 1
    assert result["writes_verified_knowledge"] is False
    db = structured_db()
    try:
        product = db.query(KBProduct).one()
        assert product.get_specs()["material"] == "PP"
        assert product.status == "pending_review"
        audit = db.query(KBChangeLog).one()
        assert audit.action == "structured_backfill_requires_review"
        assert audit.before_status == "published"
        assert audit.after_status == "pending_review"
        assert audit.get_changed_fields() == ["specs.material"]
        provenance = product.get_specs()["_trusted_auto_backfill"]
        assert len(provenance["source_sha256"]) == 64
        assert "source_file" not in provenance
    finally:
        db.close()


def test_structured_backfill_does_not_overwrite_existing_field(structured_db, tmp_path):
    from app.models.kb_tables import KBProduct
    from scripts.auto_backfill_product_structured_fields import run_backfill

    db = structured_db()
    try:
        _add_product(db, material="ABS")
    finally:
        db.close()
    source = tmp_path / "fields.json"
    _write_rows(source, [{"i_id": "YH20K01", "material": "PP"}])

    result = run_backfill(str(source), apply=True, db_factory=structured_db)

    assert result["conflict_count"] == 1
    assert result["field_updated_count"] == 0
    db = structured_db()
    try:
        assert db.query(KBProduct).one().get_specs()["material"] == "ABS"
    finally:
        db.close()


def test_structured_backfill_high_risk_fields_require_manual_review(structured_db, tmp_path):
    from scripts.auto_backfill_product_structured_fields import run_backfill

    db = structured_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "fields.json"
    _write_rows(source, [{"i_id": "YH20K01", "certification_report": "检测报告通过"}])

    result = run_backfill(str(source), apply=True, db_factory=structured_db)

    assert result["high_risk_pending_count"] == 1
    assert result["field_updated_count"] == 0
    assert result["conflicts"][0]["reason"] == "high_risk_field_requires_manual_review"
