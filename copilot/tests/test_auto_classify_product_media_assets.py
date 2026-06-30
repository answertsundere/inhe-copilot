from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def media_db(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBMediaAsset, KBProduct

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine, tables=[KBProduct.__table__, KBMediaAsset.__table__])
    return session_factory


def _add_product(db):
    from app.models.kb_tables import KBProduct

    product = KBProduct(i_id="YH30K01", product_name="media product", status="published")
    product.set_sku_list([{"sku_code": "YH30K01B01S01"}])
    db.add(product)
    db.commit()
    return product


def _write_rows(path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_media_classifier_dry_run_does_not_write(media_db, tmp_path):
    from app.models.kb_tables import KBMediaAsset
    from scripts.auto_classify_product_media_assets import run_classify

    db = media_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "media.json"
    _write_rows(source, [{"i_id": "YH30K01", "asset_url": "https://cdn.example.com/install.mp4?token=secret", "asset_title": "安装视频", "source": "dingtalk"}])

    result = run_classify(str(source), apply=False, db_factory=media_db)

    assert result["media_created_count"] == 1
    db = media_db()
    try:
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


def test_media_classifier_classifies_install_video_as_pending_review(media_db, tmp_path):
    from app.models.kb_tables import KBMediaAsset
    from scripts.auto_classify_product_media_assets import run_classify

    db = media_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "media.json"
    _write_rows(source, [{"i_id": "YH30K01", "asset_url": "https://cdn.example.com/install.mp4?token=secret", "asset_title": "安装教程视频", "source": "dingtalk"}])

    result = run_classify(str(source), apply=True, db_factory=media_db)

    assert result["classified_by_type"]["install_video"] == 1
    db = media_db()
    try:
        asset = db.query(KBMediaAsset).one()
        assert asset.asset_type == "install_video"
        assert asset.status == "pending_review"
        assert asset.usable_for_agent == 0
        assert "token=secret" not in asset.asset_url
    finally:
        db.close()


def test_media_classifier_classifies_install_image_and_size_image(media_db, tmp_path):
    from scripts.auto_classify_product_media_assets import run_classify

    db = media_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "media.json"
    _write_rows(source, [
        {"i_id": "YH30K01", "asset_url": "https://cdn.example.com/manual.jpg", "asset_title": "安装说明书步骤图", "source": "trusted_product_sheet"},
        {"i_id": "YH30K01", "asset_url": "https://cdn.example.com/size.jpg", "asset_title": "尺寸规格长宽高", "source": "trusted_product_sheet"},
    ])

    result = run_classify(str(source), apply=False, db_factory=media_db)

    assert result["classified_by_type"]["install_image"] == 1
    assert result["classified_by_type"]["size_image"] == 1


def test_media_classifier_plain_product_image_does_not_become_install_image(media_db, tmp_path):
    from scripts.auto_classify_product_media_assets import run_classify

    db = media_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "media.json"
    _write_rows(source, [{"i_id": "YH30K01", "asset_url": "https://cdn.example.com/main.jpg", "asset_title": "商品主图外观", "source": "dingtalk"}])

    result = run_classify(str(source), apply=False, db_factory=media_db)

    assert result["classified_by_type"]["sku_image"] == 1
    assert "install_image" not in result["classified_by_type"]


def test_media_classifier_skips_history_chat_images(media_db, tmp_path):
    from app.models.kb_tables import KBMediaAsset
    from scripts.auto_classify_product_media_assets import run_classify

    db = media_db()
    try:
        _add_product(db)
    finally:
        db.close()
    source = tmp_path / "media.json"
    _write_rows(source, [{"i_id": "YH30K01", "asset_url": "https://cdn.example.com/install.jpg", "asset_title": "安装图", "source": "history_chat"}])

    result = run_classify(str(source), apply=True, db_factory=media_db)

    assert result["skipped_reasons"][0]["reason"] == "untrusted_source"
    db = media_db()
    try:
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()
