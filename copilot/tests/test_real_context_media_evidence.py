import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base


@pytest.fixture()
def media_context_db(monkeypatch):
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            KBProduct.__table__,
            KBQA.__table__,
            KBMediaAsset.__table__,
            KBProductActivityRule.__table__,
            KnowledgeEntry.__table__,
            KnowledgeChunk.__table__,
            KBGenericServiceRule.__table__,
        ],
    )
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    return session_factory


def _seed_product(db, *, with_asset: bool, auto_send_level: str = "auto"):
    from app.models.kb_tables import KBMediaAsset, KBProduct

    product = KBProduct(
        i_id="YH99K01",
        product_name="测试安装柜",
        sku_list_json=json.dumps([{"sku_code": "YH99K01B01S01"}], ensure_ascii=False),
        status="published",
    )
    db.add(product)
    db.flush()
    if with_asset:
        asset = KBMediaAsset(
            product_id=product.id,
            i_id="YH99K01",
            sku_code="YH99K01B01S01",
            product_name="测试安装柜",
            asset_type="install_video",
            asset_title="安装视频",
            asset_url="https://assets.example.com/install.mp4",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.95,
            url_expires_at=datetime.utcnow() + timedelta(days=1),
        )
        asset.set_source_raw({
            "auto_send_level": auto_send_level,
            "answer_scenarios": ["installation"],
            "applicable_style": {"scope_type": "all", "scope_values": []},
        })
        db.add(asset)
    db.commit()


def test_historical_media_url_is_only_conversation_reference(media_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = media_context_db()
    try:
        _seed_product(db, with_asset=False)
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "copilot_context": {
                "real_context": {
                    "product": {"product_title": "测试安装柜", "sku_code": "YH99K01B01S01"},
                    "media": {"video_urls": ["https://chat.example.com/old-install.mp4"], "image_urls": []},
                }
            }
        },
        query="请发安装视频",
        allowed_source_types=["product_facts"],
        query_fact_type="installation",
    )

    assert pack["recommended_assets"] == []
    assert pack["stats"]["media_context_count"] == 1
    assert pack["stats"]["matched_media_asset_count"] == 0
    assert pack["stats"]["sendable_media_asset_count"] == 0
    assert pack["conversation_media_reference"]["sendable"] is False
    assert pack["evidence_pack"]["conversation_media_reference"]["evidence_role"] == "conversation_media_reference"


def test_approved_usable_media_asset_becomes_sendable_evidence(media_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = media_context_db()
    try:
        _seed_product(db, with_asset=True, auto_send_level="auto")
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "copilot_context": {
                "real_context": {
                    "product": {"product_title": "测试安装柜", "sku_code": "YH99K01B01S01"},
                    "media": {"video_urls": ["https://chat.example.com/old-install.mp4"], "image_urls": []},
                }
            }
        },
        query="请发安装视频",
        allowed_source_types=["product_facts"],
        query_fact_type="installation",
    )

    assert pack["recommended_assets"]
    assert pack["recommended_assets"][0]["asset_type"] == "install_video"
    assert pack["recommended_assets"][0]["asset_url"] == "https://assets.example.com/install.mp4"
    assert pack["stats"]["media_context_count"] == 1
    assert pack["stats"]["matched_media_asset_count"] == 1
    assert pack["stats"]["sendable_media_asset_count"] == 1
    assert pack["evidence_pack"]["matched_media"][0]["asset_type"] == "install_video"


def test_review_only_media_asset_is_not_counted_as_sendable(media_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = media_context_db()
    try:
        _seed_product(db, with_asset=True, auto_send_level="review")
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "copilot_context": {
                "real_context": {
                    "product": {"product_title": "测试安装柜", "sku_code": "YH99K01B01S01"},
                    "media": {"video_urls": ["https://chat.example.com/old-install.mp4"], "image_urls": []},
                }
            }
        },
        query="请发安装视频",
        allowed_source_types=["product_facts"],
        query_fact_type="installation",
    )

    assert pack["recommended_assets"]
    assert pack["recommended_assets"][0]["auto_send_level"] == "review"
    assert pack["stats"]["matched_media_asset_count"] == 1
    assert pack["stats"]["sendable_media_asset_count"] == 0
    assert pack["stats"]["conversation_media_rejected_reason"] == "matched_media_asset_requires_manual_review"
