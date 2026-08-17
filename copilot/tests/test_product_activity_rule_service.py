from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def activity_db(monkeypatch, tmp_path):
    import app.db as db_module
    from app.models.kb_tables import KBMediaAsset, KBProduct, KBProductActivityRule, KBQA  # noqa: F401
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'activity.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


def test_activity_normalization_keeps_customer_benefit_and_hides_internal_price():
    from app.services.product_activity_rule_service import normalize_activity_record

    item = normalize_activity_record(
        {
            "\u4ea7\u54c1\u540d\u79f0": "\u4e00\u53f7\u5582\u517b\u67dc",
            "\u4f18\u60e0\u4e00": "\u7acb\u5373\u4e0b\u5355\uff0c\u8054\u7cfb\u5ba2\u670d\u9886\u53d620\u5143\u4f18\u60e0\u5238",
            "\u4f18\u60e0\u4e8c": "\u6536\u5230\u8d27\u540e\uff0c\u6652\u56fe\u7ed9\u5230\u56db\u7ea7\u63a7\u4ef7\u3010\u4e8c\u9009\u4e00\u3011\u4f18\u60e0\uff1a\u6652\u56fe\u597d\u8bc4\uff0c\u9886\u53d620\u5143\u7ea2\u5305",
            "\u5927\u4fc3\u4ef7_\u96364": "399",
        },
        source_record_id="rec-1",
        source_sheet_id="sheet-1",
    )

    assert item["status"] == "active"
    assert item["auto_reply_allowed"] is True
    assert "\u9886\u53d620\u5143\u4f18\u60e0\u5238" in item["customer_reply"]
    assert "\u9886\u53d620\u5143\u7ea2\u5305" in item["customer_reply"]
    assert "\u56db\u7ea7\u63a7\u4ef7" not in item["customer_reply"]
    assert "\u5927\u4fc3\u4ef7" not in item["customer_reply"]
    assert item["internal_price_field"] == "\u5927\u4fc3\u4ef7_\u96364"


def test_internal_only_activity_stays_pending_review():
    from app.services.product_activity_rule_service import normalize_activity_record

    item = normalize_activity_record(
        {
            "\u4ea7\u54c1\u540d\u79f0": "\u4e00\u53f7\u5582\u517b\u67dc",
            "\u5927\u4fc3\u4ef7_\u96364": "399",
        },
        source_record_id="rec-2",
        source_sheet_id="sheet-1",
    )

    assert item["status"] == "pending_review"
    assert item["auto_reply_allowed"] is False
    assert item["customer_reply"] == ""


def test_upsert_activity_rule_customer_context_excludes_internal_fields(activity_db):
    from app.models.kb_tables import KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule

    db = activity_db()
    try:
        normalized = normalize_activity_record(
            {
                "\u4ea7\u54c1\u540d\u79f0": "\u4e00\u53f7\u5582\u517b\u67dc",
                "\u4f18\u60e0": "\u8054\u7cfb\u5ba2\u670d\u9886\u53d620\u5143\u4f18\u60e0\u5238",
                "\u5927\u4fc3\u4ef7_\u96364": "399",
            },
            source_record_id="rec-3",
            source_sheet_id="sheet-1",
        )
        row, action = upsert_activity_rule(db, KBProductActivityRule, normalized)
        db.commit()

        context = row.customer_context()
    finally:
        db.close()

    assert action == "created"
    assert "internal_price_value" not in context
    assert "raw_fields" not in context
    assert "\u63a7\u4ef7" not in json.dumps(context, ensure_ascii=False)


def test_product_context_pack_returns_activity_rule_for_promotion_query(activity_db):
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule
    from app.services.product_context_pack_service import build_product_context_pack

    db = activity_db()
    try:
        product = KBProduct(
            i_id="YH88K01",
            product_name="\u4e00\u53f7\u5582\u517b\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH88K01B09S26"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        normalized = normalize_activity_record(
            {
                "\u5546\u54c1\u7f16\u7801": "YH88K01",
                "\u4ea7\u54c1\u540d\u79f0": "\u4e00\u53f7\u5582\u517b\u67dc",
                "\u4f18\u60e0": "\u7acb\u5373\u4e0b\u5355\uff0c\u8054\u7cfb\u5ba2\u670d\u9886\u53d620\u5143\u4f18\u60e0\u5238",
            },
            source_record_id="rec-4",
            source_sheet_id="sheet-1",
        )
        normalized["product_id"] = product.id
        upsert_activity_rule(db, KBProductActivityRule, normalized)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "YH88K01B09S26"},
            "matched_product_name": "\u4e00\u53f7\u5582\u517b\u67dc",
        },
        query="\u8fd9\u4e2a\u6709\u4ec0\u4e48\u4f18\u60e0",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="promotion_policy",
    )

    assert pack["activity_rules"]
    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "promotion_policy"
    assert "\u4f18\u60e0\u5238" in pack["facts"][0]["chunk_text"]
    assert "\u63a7\u4ef7" not in pack["facts"][0]["chunk_text"]


def test_activity_rule_requires_exact_sku_when_rule_is_variant_scoped(activity_db):
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule
    from app.services.product_context_pack_service import build_product_context_pack

    db = activity_db()
    try:
        product = KBProduct(
            i_id="ACTIVITY_SCOPE_001",
            product_name="activity scoped product",
            sku_list_json=json.dumps([
                {"sku_code": "ACTIVITY-SKU-A"},
                {"sku_code": "ACTIVITY-SKU-B"},
            ]),
            status="published",
        )
        db.add(product)
        db.flush()
        normalized = normalize_activity_record(
            {
                "i_id": "ACTIVITY_SCOPE_001",
                "SKU": "ACTIVITY-SKU-B",
                "\u4f18\u60e0": "\u9886\u53d630\u5143\u4f18\u60e0\u5238",
            },
            source_record_id="variant-b-rule",
            source_sheet_id="activity-scope-sheet",
        )
        normalized["product_id"] = product.id
        upsert_activity_rule(db, KBProductActivityRule, normalized)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"i_id": "ACTIVITY_SCOPE_001", "slots": {"sku_code": "ACTIVITY-SKU-A"}},
        query="\u73b0\u5728\u6709\u4ec0\u4e48\u4f18\u60e0",
        allowed_source_types=["product_facts"],
        query_fact_type="promotion_policy",
    )

    assert pack["activity_rules"] == []
    assert pack["facts"] == []


def test_activity_rule_does_not_match_product_name_when_exact_identity_exists(activity_db):
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule
    from app.services.product_context_pack_service import build_product_context_pack

    db = activity_db()
    try:
        product = KBProduct(
            i_id="ACTIVITY_IDENTITY_001",
            product_name="shared display title",
            status="published",
        )
        db.add(product)
        db.flush()
        normalized = normalize_activity_record(
            {
                "i_id": "ACTIVITY_IDENTITY_OTHER",
                "\u4ea7\u54c1\u540d\u79f0": "shared display title",
                "\u4f18\u60e0": "\u9886\u53d640\u5143\u4f18\u60e0\u5238",
            },
            source_record_id="other-product-rule",
            source_sheet_id="activity-identity-sheet",
        )
        upsert_activity_rule(db, KBProductActivityRule, normalized)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"i_id": "ACTIVITY_IDENTITY_001"},
        query="\u73b0\u5728\u6709\u4ec0\u4e48\u4f18\u60e0",
        allowed_source_types=["product_facts"],
        query_fact_type="promotion_policy",
    )

    assert pack["activity_rules"] == []
    assert pack["facts"] == []


def test_activity_rule_reread_changes_value_sensitive_evidence_identity(activity_db):
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule
    from app.services.product_context_pack_service import build_product_context_pack

    db = activity_db()
    try:
        product = KBProduct(
            i_id="ACTIVITY_DYNAMIC_001",
            product_name="dynamic activity product",
            status="published",
        )
        db.add(product)
        db.flush()
        normalized = normalize_activity_record(
            {
                "i_id": "ACTIVITY_DYNAMIC_001",
                "\u4f18\u60e0": "\u9886\u53d610\u5143\u4f18\u60e0\u5238",
            },
            source_record_id="dynamic-rule",
            source_sheet_id="dynamic-sheet",
        )
        normalized["product_id"] = product.id
        upsert_activity_rule(db, KBProductActivityRule, normalized)
        db.commit()
    finally:
        db.close()

    state = {"i_id": "ACTIVITY_DYNAMIC_001"}
    first = build_product_context_pack(
        state,
        query="\u73b0\u5728\u6709\u4ec0\u4e48\u4f18\u60e0",
        allowed_source_types=["product_facts"],
        query_fact_type="promotion_policy",
    )

    db = activity_db()
    try:
        normalized = normalize_activity_record(
            {
                "i_id": "ACTIVITY_DYNAMIC_001",
                "\u4f18\u60e0": "\u9886\u53d625\u5143\u4f18\u60e0\u5238",
            },
            source_record_id="dynamic-rule",
            source_sheet_id="dynamic-sheet",
        )
        normalized["product_id"] = db.query(KBProduct).filter_by(i_id="ACTIVITY_DYNAMIC_001").one().id
        row, action = upsert_activity_rule(db, KBProductActivityRule, normalized)
        row.updated_at = datetime(2026, 8, 17, 10, 0, 0)
        db.commit()
        assert action == "updated"
    finally:
        db.close()

    second = build_product_context_pack(
        state,
        query="\u73b0\u5728\u6709\u4ec0\u4e48\u4f18\u60e0",
        allowed_source_types=["product_facts"],
        query_fact_type="promotion_policy",
    )

    first_fact = first["facts"][0]
    second_fact = second["facts"][0]
    assert "10\u5143\u4f18\u60e0\u5238" in first_fact["chunk_text"]
    assert "25\u5143\u4f18\u60e0\u5238" in second_fact["chunk_text"]
    assert first_fact["evidence_id"] != second_fact["evidence_id"]
    assert first_fact["value_sha256"] != second_fact["value_sha256"]
    assert second_fact["source_updated_at"] == "2026-08-17T10:00:00"


def test_product_context_pack_excludes_expired_activity_rule(activity_db):
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule
    from app.services.product_context_pack_service import build_product_context_pack

    db = activity_db()
    try:
        product = KBProduct(
            i_id="ACTIVITY_EXPIRED_001",
            product_name="expired activity product",
            status="published",
        )
        db.add(product)
        db.flush()
        normalized = normalize_activity_record(
            {
                "i_id": "ACTIVITY_EXPIRED_001",
                "\u4f18\u60e0": "\u9886\u53d650\u5143\u4f18\u60e0\u5238",
            },
            source_record_id="expired-rule",
            source_sheet_id="expired-sheet",
        )
        normalized["product_id"] = product.id
        normalized["end_at"] = datetime.utcnow() - timedelta(seconds=1)
        upsert_activity_rule(db, KBProductActivityRule, normalized)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"i_id": "ACTIVITY_EXPIRED_001"},
        query="\u73b0\u5728\u6709\u4ec0\u4e48\u4f18\u60e0",
        allowed_source_types=["product_facts"],
        query_fact_type="promotion_policy",
    )

    assert pack["activity_rules"] == []
    assert pack["facts"] == []


def test_media_ranking_prefers_size_image_for_dimension_fact_type(activity_db):
    from app.models.kb_tables import KBMediaAsset
    from app.services.product_context_pack_service import _rank_media_assets_for_query

    db = activity_db()
    try:
        sku = KBMediaAsset(
            i_id="YH00K01",
            sku_code="YH00K01",
            product_name="demo",
            asset_type="sku_image",
            asset_title="demo sku image",
            asset_url="https://example.com/sku.png",
            status="approved",
            usable_for_agent=1,
            match_confidence=0.9,
        )
        sku.set_source_raw({"answer_scenarios": ["ask_photo", "appearance", "dimensions"]})
        size = KBMediaAsset(
            i_id="YH00K01",
            sku_code="YH00K01",
            product_name="demo",
            asset_type="size_image",
            asset_title="demo size image",
            asset_url="https://example.com/size.png",
            status="approved",
            usable_for_agent=1,
            match_confidence=0.8,
        )
        size.set_source_raw({"answer_scenarios": ["dimensions"]})
        db.add_all([sku, size])
        db.commit()
        ranked = _rank_media_assets_for_query(
            [sku, size],
            query="\u6709\u5c3a\u5bf8\u56fe\u5417",
            query_fact_type="dimensions",
            limit=2,
            signals={"customer_message": "\u6709\u5c3a\u5bf8\u56fe\u5417", "i_id": "YH00K01"},
        )
    finally:
        db.close()

    assert ranked[0].asset_type == "size_image"


def test_media_priority_treats_photo_as_sku_image():
    from app.services.product_context_pack_service import _media_priority

    assert _media_priority("\u6709\u7167\u7247\u5417", "")[:1] == ["sku_image"]


def test_product_detail_asset_rows_include_semantic_labels():
    from scripts.sync_dingtalk_product_detail_assets import build_asset_rows

    class Product:
        id = 1
        i_id = "YH64K01"
        product_name = "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f"

    rows = build_asset_rows(
        {
            "\u89c4\u683c": {"name": "\u7ec4\u54083"},
            "\u989c\u8272": {"name": "\u8309\u8389\u767d"},
            "SKU\u56fe": [{"url": "https://example.com/sku.png", "filename": "sku.png"}],
            "\u7ec6\u8282\u5c3a\u5bf8": [{"url": "https://example.com/size.png", "filename": "size.png"}],
            "\u5b89\u88c5\u89c6\u9891(\u6296\u97f3)": {"link": "https://example.com/install", "text": "install"},
        },
        Product(),
        "rec-1",
    )

    by_type = {row["asset_type"]: row for row in rows}
    assert by_type["sku_image"]["source_raw"]["answer_scenarios"] == ["ask_photo", "appearance", "dimensions"]
    assert by_type["size_image"]["source_raw"]["answer_scenarios"] == ["dimensions", "detachable"]
    assert by_type["install_video"]["source_raw"]["answer_scenarios"] == ["installation", "drilling"]
    assert by_type["size_image"]["source_raw"]["applicable_style"]["scope_values"] == ["\u7ec4\u54083", "\u8309\u8389\u767d"]
