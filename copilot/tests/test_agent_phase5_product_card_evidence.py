from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def phase5_db(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(
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
    return session_factory


def _compose_from_pack(pack: dict, *, query_fact_type: str, secondary_fact_types: list[str] | None = None) -> dict:
    from app.services.answer_composition_service import compose_customer_reply
    from app.services.evidence_grouping_service import group_evidence_by_fact_type

    query_understanding = {
        "query_fact_type": query_fact_type,
        "secondary_fact_types": secondary_fact_types or [],
    }
    evidence_payload = {"product_context_pack": pack}
    grouping = group_evidence_by_fact_type(evidence_payload, query_understanding)
    selected_evidence = [
        *(pack.get("product_card_evidence") or []),
        *(pack.get("media_evidence") or []),
    ]
    selected_assets = [
        item for item in pack.get("media_evidence", [])
        if item.get("evidence_fact_type") == "visual_asset"
    ]
    return compose_customer_reply(
        customer_message="\u5c3a\u5bf8\u591a\u5927\uff0c\u6709\u56fe\u5417",
        base_reply="",
        query_understanding=query_understanding,
        evidence_grouping=grouping,
        selected_evidence=selected_evidence,
        selected_assets=selected_assets,
        product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
        intent="product_question",
    )


def _product_card_item(fact_type: str, text: str) -> dict:
    return {
        "entry_id": f"card:{fact_type}",
        "chunk_id": f"card:{fact_type}",
        "title": "\u5546\u54c1\u5361\u7247",
        "chunk_text": text,
        "source_type": "product_facts",
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "evidence_origin": "product_card",
        "evidence_allowed_for_direct_answer": True,
    }


def _media_item(fact_type: str, asset_type: str, title: str, text: str) -> dict:
    return {
        "entry_id": f"media:{asset_type}:{fact_type}",
        "chunk_id": f"media:{asset_type}:{fact_type}",
        "asset_id": f"asset-{asset_type}",
        "asset_type": asset_type,
        "asset_title": title,
        "asset_url": f"https://example.com/{asset_type}.jpg",
        "url": f"https://example.com/{asset_type}.jpg",
        "title": title,
        "chunk_text": text,
        "source_type": "product_media",
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "evidence_origin": "product_media",
        "sendable": True,
        "evidence_allowed_for_direct_answer": True,
    }


def test_product_context_pack_builds_product_card_evidence_from_profile(phase5_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = phase5_db()
    try:
        db.add(KBProduct(
            i_id="PHASE5_CARD_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "PHASE5_CARD_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"size": "60*30*90cm", "material": "\u73af\u4fddPP"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "PHASE5_CARD_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u5c3a\u5bf8\u591a\u5927",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    assert pack["product_card_evidence"]
    assert pack["product_card_evidence"][0]["evidence_origin"] == "product_card"
    assert pack["product_card_evidence"][0]["evidence_fact_type"] == "dimensions"
    assert "60*30*90cm" in pack["product_card_evidence"][0]["chunk_text"]


def test_product_card_dimensions_enter_answer_composition_trace():
    pack = {"product_card_evidence": [_product_card_item("dimensions", "size: 60*30*90cm")]}

    result = _compose_from_pack(pack, query_fact_type="dimensions")

    assert "60*30*90cm" in result["composed_reply"]
    trace = result["composition_trace"]
    assert "dimensions" in trace["evidence_answered_fact_types"]
    assert trace["evidence_origin_by_fact_type"]["dimensions"] == ["product_card"]
    assert trace["product_card_evidence_used"]["dimensions"]


def test_size_image_enters_dimensions_and_visual_asset_trace():
    pack = {
        "media_evidence": [
            _media_item("dimensions", "size_image", "\u5c3a\u5bf8\u56fe", "\u5f53\u524d\u5546\u54c1\u6709\u5c3a\u5bf8\u56fe\u300a\u5c3a\u5bf8\u56fe\u300b\uff0c\u5c3a\u5bf8\u4ee5\u56fe\u4e2d\u6807\u6ce8\u4e3a\u51c6\u3002"),
            _media_item("visual_asset", "size_image", "\u5c3a\u5bf8\u56fe", "\u5f53\u524d\u5546\u54c1\u6709\u56fe\u7247\u300a\u5c3a\u5bf8\u56fe\u300b\uff0c\u53ef\u4e00\u8d77\u53d1\u60a8\u53c2\u8003\u3002"),
        ]
    }

    result = _compose_from_pack(pack, query_fact_type="dimensions", secondary_fact_types=["visual_asset"])

    trace = result["composition_trace"]
    assert "dimensions" in trace["covered_fact_types"]
    assert "visual_asset" in trace["covered_fact_types"]
    assert trace["media_evidence_used"]["dimensions"]
    assert trace["asset_evidence_used"]["visual_asset"]


def test_install_video_answers_installation_without_text_rag():
    pack = {
        "media_evidence": [
            _media_item("installation", "install_video", "\u5b89\u88c5\u89c6\u9891", "\u5f53\u524d\u5546\u54c1\u6709\u5b89\u88c5\u8bf4\u660e\u89c6\u9891\u300a\u5b89\u88c5\u89c6\u9891\u300b\uff0c\u53ef\u53d1\u60a8\u5bf9\u7167\u5b89\u88c5\u6b65\u9aa4\u53c2\u8003\u3002"),
            _media_item("visual_asset", "install_video", "\u5b89\u88c5\u89c6\u9891", "\u5f53\u524d\u5546\u54c1\u6709\u89c6\u9891\u300a\u5b89\u88c5\u89c6\u9891\u300b\uff0c\u53ef\u4e00\u8d77\u53d1\u60a8\u53c2\u8003\u3002"),
        ]
    }

    result = _compose_from_pack(pack, query_fact_type="installation", secondary_fact_types=["visual_asset"])

    trace = result["composition_trace"]
    assert "installation" in trace["evidence_answered_fact_types"]
    assert "visual_asset" in trace["evidence_answered_fact_types"]
    assert trace["asset_evidence_used"]["visual_asset"][0]["asset_type"] == "install_video"


def test_certificate_media_does_not_expand_to_absolute_safety_claim():
    pack = {
        "media_evidence": [
            _media_item("certification_report", "certificate_image", "\u8d28\u68c0\u62a5\u544a", "\u5f53\u524d\u5546\u54c1\u6709\u8bc1\u4e66/\u68c0\u6d4b\u7c7b\u56fe\u7247\u300a\u8d28\u68c0\u62a5\u544a\u300b\uff0c\u5177\u4f53\u7ed3\u8bba\u4ee5\u62a5\u544a\u6807\u6ce8\u4e3a\u51c6\u3002"),
        ]
    }

    result = _compose_from_pack(pack, query_fact_type="certification_report")

    assert "\u62a5\u544a" in result["composed_reply"]
    assert "0\u7532\u919b" not in result["composed_reply"]
    assert "\u7edd\u5bf9\u5b89\u5168" not in result["composed_reply"]
    assert result["composition_trace"]["media_evidence_used"]["certification_report"]


def test_invalid_product_card_placeholders_do_not_become_evidence(phase5_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = phase5_db()
    try:
        db.add(KBProduct(
            i_id="PHASE5_EMPTY_001",
            product_name="\u5360\u4f4d\u5b57\u6bb5\u6d4b\u8bd5",
            sku_list_json=json.dumps([{"sku_code": "PHASE5_EMPTY_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"size": "\u8be6\u89c1\u5546\u54c1\u8be6\u60c5\u9875", "material": "\u5f85\u8865\u5145"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "PHASE5_EMPTY_001B01S01"}, "matched_product_name": "\u5360\u4f4d\u5b57\u6bb5\u6d4b\u8bd5"},
        query="\u5c3a\u5bf8\u591a\u5927",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    assert pack["product_card_evidence"] == []


def test_product_card_evidence_takes_priority_over_generic_rag_text():
    pack = {
        "product_card_evidence": [_product_card_item("dimensions", "size: 60*30*90cm")],
    }
    generic_rag = {
        "entry_id": "faq:generic",
        "chunk_id": "faq:generic",
        "title": "\u901a\u7528\u5c3a\u5bf8\u8bf4\u660e",
        "chunk_text": "\u4e0d\u540c\u6b3e\u5f0f\u5c3a\u5bf8\u4e0d\u540c\uff0c\u8bf7\u4ee5\u9875\u9762\u4e3a\u51c6\u3002",
        "source_type": "faq",
        "fact_type": "dimensions",
        "evidence_fact_type": "dimensions",
    }

    from app.services.answer_composition_service import compose_customer_reply
    from app.services.evidence_grouping_service import group_evidence_by_fact_type

    query_understanding = {"query_fact_type": "dimensions", "secondary_fact_types": []}
    grouping = group_evidence_by_fact_type(
        {"product_context_pack": pack, "filtered_evidence": [generic_rag]},
        query_understanding,
    )
    result = compose_customer_reply(
        customer_message="\u5c3a\u5bf8\u591a\u5927",
        base_reply="",
        query_understanding=query_understanding,
        evidence_grouping=grouping,
        selected_evidence=[*pack["product_card_evidence"], generic_rag],
        selected_assets=[],
        product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
        intent="product_question",
    )

    assert "60*30*90cm" in result["composed_reply"]
    assert "\u4e0d\u540c\u6b3e\u5f0f\u5c3a\u5bf8\u4e0d\u540c" not in result["composed_reply"]
