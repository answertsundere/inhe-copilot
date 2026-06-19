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


def test_certification_report_does_not_reuse_material_evidence_as_direct_answer():
    pack = {"product_card_evidence": [_product_card_item("material", "\u6750\u8d28: \u73af\u4fddPP")]}

    result = _compose_from_pack(
        pack,
        query_fact_type="certification_report",
        secondary_fact_types=["material"],
    )

    trace = result["composition_trace"]
    assert "material" in trace["evidence_answered_fact_types"]
    assert "certification_report" not in trace["evidence_answered_fact_types"]
    assert "certification_report" in trace["needs_followup_fact_types"]


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


def test_primary_visual_secondary_dimensions_builds_card_dimensions_evidence(phase5_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = phase5_db()
    try:
        db.add(KBProduct(
            i_id="PHASE5_MULTI_CARD",
            product_name="\u591a\u610f\u56fe\u5361\u7247\u6d4b\u8bd5",
            sku_list_json=json.dumps([{"sku_code": "PHASE5_MULTI_CARDB01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"size": "88*42*106cm"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "PHASE5_MULTI_CARDB01S01"},
            "matched_product_name": "\u591a\u610f\u56fe\u5361\u7247\u6d4b\u8bd5",
            "query_understanding": {
                "query_fact_type": "visual_asset",
                "secondary_fact_types": ["dimensions"],
            },
        },
        query="\u5c3a\u5bf8\u591a\u5927\uff0c\u6709\u6ca1\u6709\u56fe",
        allowed_source_types=["product_facts"],
        query_fact_type="visual_asset",
    )

    dimensions = [
        item for item in pack["product_card_evidence"]
        if item["evidence_fact_type"] == "dimensions"
    ]
    assert dimensions
    assert "88*42*106cm" in dimensions[0]["chunk_text"]
    assert "dimensions" in pack["stats"]["required_fact_types"]

    result = _compose_from_pack(
        pack,
        query_fact_type="visual_asset",
        secondary_fact_types=["dimensions"],
    )
    trace = result["composition_trace"]
    assert "dimensions" in trace["evidence_answered_fact_types"]
    assert trace["evidence_origin_by_fact_type"]["dimensions"] == ["product_card"]
    assert "dimensions" not in trace["missing_fact_types"]


def test_primary_visual_secondary_dimensions_builds_size_image_media_evidence(phase5_db):
    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = phase5_db()
    try:
        product = KBProduct(
            i_id="PHASE5_MULTI_MEDIA",
            product_name="\u591a\u610f\u56fe\u7d20\u6750\u6d4b\u8bd5",
            sku_list_json=json.dumps([{"sku_code": "PHASE5_MULTI_MEDIAB01S01"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        asset = KBMediaAsset(
            product_id=product.id,
            i_id="PHASE5_MULTI_MEDIA",
            sku_code="PHASE5_MULTI_MEDIAB01S01",
            product_name="\u591a\u610f\u56fe\u7d20\u6750\u6d4b\u8bd5",
            asset_type="size_image",
            asset_title="\u5c3a\u5bf8\u56fe",
            asset_url="https://example.com/size.jpg",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.95,
        )
        asset.set_source_raw({"auto_send_level": "auto", "answer_scenarios": ["dimensions", "ask_photo"]})
        db.add(asset)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "PHASE5_MULTI_MEDIAB01S01"},
            "matched_product_name": "\u591a\u610f\u56fe\u7d20\u6750\u6d4b\u8bd5",
            "query_understanding": {
                "query_fact_type": "visual_asset",
                "secondary_fact_types": ["dimensions"],
            },
        },
        query="\u5c3a\u5bf8\u591a\u5927\uff0c\u6709\u6ca1\u6709\u56fe",
        allowed_source_types=["product_facts"],
        query_fact_type="visual_asset",
    )

    fact_types = {item["evidence_fact_type"] for item in pack["media_evidence"]}
    assert {"dimensions", "visual_asset"} <= fact_types

    result = _compose_from_pack(
        pack,
        query_fact_type="visual_asset",
        secondary_fact_types=["dimensions"],
    )
    trace = result["composition_trace"]
    assert "visual_asset" in trace["evidence_answered_fact_types"]
    assert trace["media_evidence_used"]["dimensions"]
    assert trace["asset_evidence_used"]["visual_asset"][0]["asset_type"] == "size_image"


def test_installation_with_visual_asset_builds_install_video_evidence(phase5_db):
    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = phase5_db()
    try:
        product = KBProduct(
            i_id="PHASE5_INSTALL_MEDIA",
            product_name="\u5b89\u88c5\u7d20\u6750\u6d4b\u8bd5",
            sku_list_json=json.dumps([{"sku_code": "PHASE5_INSTALL_MEDIAB01S01"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        asset = KBMediaAsset(
            product_id=product.id,
            i_id="PHASE5_INSTALL_MEDIA",
            sku_code="PHASE5_INSTALL_MEDIAB01S01",
            product_name="\u5b89\u88c5\u7d20\u6750\u6d4b\u8bd5",
            asset_type="install_video",
            asset_title="\u5b89\u88c5\u89c6\u9891",
            asset_url="https://example.com/install.mp4",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.95,
        )
        asset.set_source_raw({"auto_send_level": "auto", "answer_scenarios": ["installation", "ask_photo"]})
        db.add(asset)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "PHASE5_INSTALL_MEDIAB01S01"},
            "matched_product_name": "\u5b89\u88c5\u7d20\u6750\u6d4b\u8bd5",
            "secondary_fact_types": ["visual_asset"],
        },
        query="\u600e\u4e48\u5b89\u88c5\uff0c\u6709\u89c6\u9891\u5417",
        allowed_source_types=["product_facts"],
        query_fact_type="installation",
    )

    result = _compose_from_pack(
        pack,
        query_fact_type="installation",
        secondary_fact_types=["visual_asset"],
    )
    trace = result["composition_trace"]
    assert "installation" in trace["evidence_answered_fact_types"]
    assert "visual_asset" in trace["evidence_answered_fact_types"]
    asset_trace = trace["asset_evidence_used"]["visual_asset"][0]
    assert asset_trace["asset_type"] == "install_video"
    assert asset_trace["asset_id"]
    assert asset_trace["asset_url"] == "https://example.com/install.mp4"
    assert "\u89c6\u9891" in result["composed_reply"]


def test_visual_asset_without_sendable_asset_is_not_answered_and_has_no_fake_send_claim():
    pack = {"media_evidence": []}

    result = _compose_from_pack(pack, query_fact_type="visual_asset")

    reply = result["composed_reply"]
    trace = result["composition_trace"]
    assert "visual_asset" not in trace["answered_fact_types"]
    assert "visual_asset" in trace["needs_followup_fact_types"]
    assert "下面发" not in reply
    assert "视频发您参考" not in reply
    assert "看下方图片" not in reply
    assert "一起发您" not in reply


def test_required_fact_types_include_secondary_fact_types():
    pack = {
        "product_card_evidence": [_product_card_item("dimensions", "size: 60*30*90cm")],
        "media_evidence": [_media_item("visual_asset", "sku_image", "\u5546\u54c1\u56fe", "\u5f53\u524d\u5546\u54c1\u6709\u56fe\u7247\u300a\u5546\u54c1\u56fe\u300b\uff0c\u53ef\u4e00\u8d77\u53d1\u60a8\u53c2\u8003\u3002")],
    }

    result = _compose_from_pack(
        pack,
        query_fact_type="visual_asset",
        secondary_fact_types=["dimensions"],
    )

    assert result["composition_trace"]["mode"] == "multi_intent"
    assert set(result["composition_trace"]["covered_fact_types"]) == {"visual_asset", "dimensions"}


def test_composed_reply_does_not_leak_internal_terms():
    pack = {"product_card_evidence": [_product_card_item("dimensions", "size: 60*30*90cm")]}

    result = _compose_from_pack(pack, query_fact_type="dimensions")

    for term in ("RAG", "fact_type", "query_fact_type", "\u77e5\u8bc6\u5e93", "\u8d44\u6599\u5e93", "\u7cfb\u7edf"):
        assert term not in result["composed_reply"]


def test_installation_media_fallback_without_asset_does_not_mix_dimensions():
    from app.services.customer_reply_polisher import polish_customer_reply

    response = {
        "suggested_reply": (
            "亲～这款商品这个细节可以直接参考我下面发您的图片或视频。\n"
            "如果是看尺寸，重点对照家里预留位置的宽度、进深和高度；\n"
            "如果是看安装或配件，按图里标注的位置和步骤核对会更直观。"
        ),
        "query_fact_type": "installation",
        "evidence_debug": {
            "query_fact_type": "installation",
            "evidence_grouping": {"coverage": {"required_fact_types": ["installation"]}},
            "answer_composition_trace": {"needs_followup_fact_types": ["installation"]},
        },
    }

    result = polish_customer_reply(response, customer_message="怎么安装，有视频吗？")
    reply = result["suggested_reply"]

    assert "安装" in reply
    assert "没有可直接发送" in reply
    for term in ("尺寸", "宽度", "进深", "高度", "预留位置", "按图", "图里", "下面发"):
        assert term not in reply


def test_final_answer_auditor_blocks_installation_fallback_with_dimension_drift():
    from app.services.final_answer_auditor import audit_final_answer

    response = {
        "suggested_reply": (
            "亲～这款商品这个细节可以直接参考我下面发您的图片或视频。\n"
            "如果是看尺寸，重点对照家里预留位置的宽度、进深和高度。"
        ),
        "query_fact_type": "installation",
        "evidence_debug": {
            "query_fact_type": "installation",
            "evidence_grouping": {"coverage": {"required_fact_types": ["installation"]}},
            "answer_composition_trace": {"needs_followup_fact_types": ["installation"]},
        },
    }

    audited = audit_final_answer(response, customer_message="怎么安装，有视频吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert "unsupported_media_reference_without_asset" in audited["final_answer_audit"]["issues"]
    assert "off_topic:installation_media_fallback_mentions_dimensions" in audited["final_answer_audit"]["issues"]
    assert audited["generation_mode"] == "final_answer_audit_fallback"


def test_final_semantic_gate_blocks_unsupported_media_reference_without_asset():
    from app.services.final_semantic_quality_service import audit_customer_reply_semantic_fit

    response = {
        "suggested_reply": "亲～安装步骤可以参考我下面发您的视频，按图里标注的位置操作就可以。",
        "query_fact_type": "installation",
        "evidence_debug": {
            "query_fact_type": "installation",
            "answer_composition_trace": {"needs_followup_fact_types": ["installation"]},
        },
    }

    result = audit_customer_reply_semantic_fit(response, customer_message="怎么安装，有视频吗？")

    assert result["passed"] is False
    assert "unsupported_media_reference_without_asset" in result["issues"]


def test_dimensions_media_fallback_without_asset_does_not_mix_installation():
    from app.services.customer_reply_polisher import polish_customer_reply

    response = {
        "suggested_reply": (
            "亲～这款商品目前没有可直接发送的图片/视频素材，我先帮您核对。\n"
            "如果是看安装或配件，按图里标注的位置和步骤核对会更直观。"
        ),
        "query_fact_type": "dimensions",
        "evidence_debug": {
            "query_fact_type": "dimensions",
            "evidence_grouping": {"coverage": {"required_fact_types": ["dimensions"]}},
        },
    }

    result = polish_customer_reply(response, customer_message="尺寸多大，有没有图？")
    reply = result["suggested_reply"]

    assert "尺寸" in reply
    assert "没有可直接发送" in reply
    for term in ("安装", "配件", "按图", "图里", "步骤"):
        assert term not in reply
