from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.eval_sanitizer_service import hash_sensitive


@pytest.fixture()
def product_context_db(monkeypatch):
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


def _add_chunked_entry(
    db,
    *,
    title,
    content,
    source_type,
    fact_type,
    product_scope,
    sku_scope,
    metadata=None,
):
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    entry = KnowledgeEntry(
        source_type=source_type,
        title=title,
        content=content,
        intent="product_question",
        product_scope_json=json.dumps(product_scope, ensure_ascii=False),
        sku_scope_json=json.dumps(sku_scope, ensure_ascii=False),
        status="published",
        index_status="ready",
        fact_type=fact_type,
        auto_reply_allowed=True,
    )
    db.add(entry)
    db.flush()
    chunk = KnowledgeChunk(
        entry_id=entry.id,
        chunk_text=content,
        chunk_index=0,
        source_type=source_type,
        intent="product_question",
        product_scope_json=json.dumps(product_scope, ensure_ascii=False),
        sku_scope_json=json.dumps(sku_scope, ensure_ascii=False),
        metadata_json=json.dumps(
            {"auto_reply_allowed": True, **(metadata or {})},
            ensure_ascii=False,
        ),
        category="",
        category_l3="",
        search_keywords="",
        source_confidence=0.8,
    )
    db.add(chunk)
    db.commit()
    return entry


def test_product_context_pack_collects_same_product_installation_by_sku_family(product_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc\u5b89\u88c5\u8bf4\u660e",
            content="\u91c7\u7528\u5361\u6263\u5f0f\u7ec4\u88c5\uff0c\u5148\u88c5\u4fa7\u677f\u518d\u56fa\u5b9a\u5c42\u677f\u3002",
            source_type="installation_guide",
            fact_type="installation",
            product_scope=["YH06K53", "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc"],
            sku_scope=["YH06K53"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "YH06K53B05S13"},
            "matched_product_name": "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
        },
        query="\u8fd9\u4e2a\u600e\u4e48\u5b89\u88c5",
        allowed_source_types=["installation_guide", "product_facts", "faq"],
        query_fact_type="installation",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "installation"
    assert pack["facts"][0]["product_context_pack"] is True


def test_product_context_pack_reads_sku_from_product_candidates(product_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc\u5b89\u88c5\u8bf4\u660e",
            content="\u8fd9\u6b3e\u91c7\u7528\u5361\u6263\u5f0f\u7ec4\u88c5\uff0c\u4e0d\u9700\u8981\u6253\u5b54\u3002",
            source_type="installation_guide",
            fact_type="installation",
            product_scope=["YH06K53"],
            sku_scope=["YH06K53"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "product_candidates": [
                {"type": "product_name", "value": "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc"},
                {"type": "sku_code", "value": "YH06K53B05S13"},
            ],
        },
        query="\u9700\u8981\u6253\u5b54\u5417",
        allowed_source_types=["installation_guide"],
        query_fact_type="installation",
    )

    assert pack["facts"]
    assert "\u4e0d\u9700\u8981\u6253\u5b54" in pack["facts"][0]["chunk_text"]


@pytest.mark.parametrize("query_fact_type", ["material", "material_composition"])
def test_product_context_pack_uses_resolved_platform_item_id_for_structured_facts(
    product_context_db,
    query_fact_type,
):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH91K01",
            product_name="Rocket shelf",
            status="published",
            sku_list_json=json.dumps([{
                "sku_code": "YH91K01B01S01",
                "platform_item_id": "987654321012",
                "platform_item_id_hash": hash_sensitive("987654321012"),
                "product_url": "https://item.taobao.com/item.htm?id=987654321012",
            }], ensure_ascii=False),
        )
        product.set_specs({"material": "PP plastic"})
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "copilot_context": {
                "real_context": {
                    "product": {
                        "item_id": "987654321012",
                        "item_id_hash": hash_sensitive("987654321012"),
                        "product_url": "https://item.taobao.com/item.htm?id=987654321012",
                    }
                }
            },
        },
        query="what material",
        allowed_source_types=["product_facts"],
        query_fact_type=query_fact_type,
    )

    product_first = pack["product_first_evidence_pack"]
    assert product_first["resolved_product_identity"]["i_id"] == "YH91K01"
    assert product_first["identity_confidence"] >= 0.95
    assert product_first["product_structured_facts"]
    assert product_first["product_structured_facts"][0]["fact_type"] == query_fact_type
    assert product_first["evidence_pack_trace"]["product_identity_resolution"]["match_reason"] == "exact_platform_item_id_hash_match"


def test_product_context_pack_does_not_use_structured_facts_for_ambiguous_title(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        first = KBProduct(i_id="YH91K02", product_name="Rocket shelf tall", status="published")
        first.set_specs({"material": "steel"})
        second = KBProduct(i_id="YH91K03", product_name="Rocket shelf short", status="published")
        second.set_specs({"material": "PP"})
        db.add(first)
        db.add(second)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"copilot_context": {"platform_product_title": "Rocket shelf"}},
        query="what material",
        allowed_source_types=["product_facts"],
        query_fact_type="material",
    )

    product_first = pack["product_first_evidence_pack"]
    assert product_first["product_structured_facts"] == []
    assert product_first["answerability"] == "no_product_identity"
    assert product_first["evidence_pack_trace"]["product_identity_resolution"]["status"] == "ambiguous"
    assert product_first["evidence_pack_trace"]["ambiguous_candidates"]


def test_product_context_pack_admits_exact_hub_facts_and_labeled_media_when_enabled(product_context_db, monkeypatch):
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "reason": "",
            "match_reason": "exact_product_and_sku_code",
            "product": {"hub_product_id": "hub-product-1", "product_code": "YH91K01", "product_name": "测试收纳柜"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "YH91K01B01S01"},
            "reference_only": False,
            "used_for_fact": True,
            "source": "product_data_hub",
            "facts": [{
                "fact_uid": "product_data_hub:fact-1",
                "fact_type": "dimensions",
                "attribute_key": "width",
                "value": "42",
                "unit": "cm",
                "scope": "商品整体",
                "applies": "",
                "source": "product_data_hub:ai-label",
                "source_detail": "尺寸参数图",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                "updated_at": "2026-08-22T10:00:00Z",
            }],
            "assets": [{
                "asset_id": "hub-asset-1",
                "asset_type": "size_image",
                "labels": ["尺寸参数图"],
                "label_note": "整体宽度尺寸",
                "spec_ref": "42cm",
                "asset_title": "尺寸图",
                "asset_url": "http://127.0.0.1:8795/api/v2/media/preview/hub-asset-1",
                "source": "product_data_hub",
                "product_code": "YH91K01",
                "sku_code": "YH91K01B01S01",
                "auto_send_level": "auto",
            }],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "YH91K01", "sku_code": "YH91K01B01S01"}},
        query="这个尺寸多大",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    assert pack["stats"]["catalog_reference_used_for_fact"] is True
    assert pack["facts"][0]["source_type"] == "product_facts"
    assert pack["facts"][0]["protocol_source_type"] == "product_data_hub"
    assert pack["facts"][0]["chunk_text"] == "42cm"
    assert pack["recommended_assets"][0]["asset_id"] == "hub-asset-1"
    assert pack["product_first_evidence_pack"]["answerability"] == "direct_answer"


def test_exact_product_hub_pair_wins_before_legacy_identity_resolution(
    product_context_db,
    monkeypatch,
):
    import app.config as config
    from app.services import product_context_pack_service
    from app.services.product_identity_resolver import ProductIdentityResolver

    hub_calls = []
    legacy_calls = []

    def lookup_bundle(*, i_id="", sku_id=""):
        hub_calls.append({"i_id": i_id, "sku_id": sku_id})
        if (i_id, sku_id) != ("HUB-PRODUCT", "SHARED-SKU"):
            return {
                "status": "not_found",
                "reason": "product_code_not_found",
                "facts": [],
                "assets": [],
            }
        return {
            "status": "resolved",
            "reason": "",
            "match_reason": "exact_product_and_sku_code",
            "product": {
                "hub_product_id": "hub-product-exact",
                "product_code": "HUB-PRODUCT",
                "product_name": "Exact Hub Product",
            },
            "sku": {
                "hub_sku_id": "hub-sku-exact",
                "sku_code": "SHARED-SKU",
            },
            "reference_only": False,
            "used_for_fact": True,
            "source": "product_data_hub",
            "facts": [{
                "fact_uid": "product_data_hub:exact-width",
                "fact_type": "size",
                "attribute_key": "width",
                "value": "42",
                "unit": "cm",
                "scope": "product",
                "applies": "",
                "source": "product_data_hub:confirmed_record",
                "source_detail": "",
                "review_status": "confirmed",
                "identity_scope": {
                    "hub_product_id": "hub-product-exact",
                    "hub_sku_id": "hub-sku-exact",
                },
                "updated_at": "2026-08-24T10:00:00Z",
            }],
            "assets": [],
        }

    def legacy_resolve(_self, **kwargs):
        legacy_calls.append(kwargs)
        return {
            "status": "resolved",
            "source": "sku_exact",
            "sku_code": "SHARED-SKU",
            "i_id": "LEGACY-PRODUCT",
            "canonical_product_name": "Legacy Product",
            "resolved_product_id": 41,
        }

    monkeypatch.setattr(config, "COPILOT_PRODUCT_DATA_HUB_ENABLED", True, raising=False)
    monkeypatch.setattr(
        config,
        "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lookup_bundle,
    )
    monkeypatch.setattr(ProductIdentityResolver, "resolve", legacy_resolve)

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "HUB-PRODUCT", "sku_code": "SHARED-SKU"}},
        query="What is the product width?",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    assert legacy_calls == []
    assert hub_calls == [{"i_id": "HUB-PRODUCT", "sku_id": "SHARED-SKU"}]
    assert pack["identity"]["i_id"] == "HUB-PRODUCT"
    assert pack["identity"]["sku"] == "SHARED-SKU"
    assert pack["facts"][0]["evidence_id"] == "product_data_hub:exact-width"
    assert pack["product_first_evidence_pack"]["answerability"] == "direct_answer"


@pytest.mark.parametrize(
    "reference",
    [
        {"status": "ambiguous", "product": {}, "sku": {}},
        {
            "status": "resolved",
            "product": {"product_code": "OTHER-PRODUCT"},
            "sku": {"sku_code": "SHARED-SKU"},
        },
        {
            "status": "resolved",
            "product": {"product_code": "HUB-PRODUCT"},
            "sku": {"sku_code": "OTHER-SKU"},
        },
    ],
)
def test_exact_product_hub_identity_does_not_trust_ambiguous_or_mismatched_pair(reference):
    from app.services.product_context_pack_service import _identity_from_exact_hub_reference

    assert _identity_from_exact_hub_reference(
        {"i_id": "HUB-PRODUCT", "sku": "SHARED-SKU", "product_name": ""},
        reference,
    ) is None


def test_product_context_pack_uses_product_only_i_id_from_slots_for_exact_hub_fact(
    product_context_db,
    monkeypatch,
):
    import app.config as config
    from app.services import product_context_pack_service

    observed_identity = {}

    def lookup_bundle(**kwargs):
        observed_identity.update(kwargs)
        return {
            "status": "resolved",
            "reason": "",
            "match_reason": "exact_product_code",
            "product": {
                "hub_product_id": "hub-product-only",
                "product_code": "P-HUB-ONLY",
                "product_name": "Product-only fact fixture",
            },
            "sku": {},
            "reference_only": False,
            "used_for_fact": True,
            "source": "product_data_hub",
            "facts": [{
                "fact_uid": "product_data_hub:product-size",
                "fact_type": "size",
                "attribute_key": "overall_dimensions",
                "value": "60x40x80",
                "unit": "cm",
                "scope": "product",
                "applies": "",
                "source": "product_data_hub:confirmed_record",
                "source_detail": "",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-only"},
                "updated_at": "2026-08-24T10:00:00Z",
            }],
            "assets": [],
        }

    monkeypatch.setattr(
        config,
        "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lookup_bundle,
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "P-HUB-ONLY"}},
        query="What are the overall product dimensions?",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    assert observed_identity == {"i_id": "P-HUB-ONLY", "sku_id": ""}
    assert pack["stats"]["catalog_reference_used_for_fact"] is True
    assert pack["facts"][0]["source_table"] == "product_data_hub"
    assert pack["product_first_evidence_pack"]["answerability"] == "direct_answer"


def test_exact_hub_parts_fact_answers_included_items_not_accessory_availability(product_context_db, monkeypatch):
    """A confirmed SKU packing list may answer contents, never purchase availability."""
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "P100"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "S100-COMBO"},
            "facts": [{
                "fact_uid": "product_data_hub:fact-included-items",
                "fact_type": "parts",
                "attribute_key": "configuration_contents",
                "value": "main item x1; ball x2",
                "unit": "",
                "scope": "included_item",
                "applies": "S100-COMBO",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
            }],
            "assets": [],
        },
    )

    contents_pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "P100", "sku_code": "S100-COMBO"}},
        query="what is included in this selected configuration",
        allowed_source_types=["product_facts"],
        query_fact_type="included_items",
    )
    availability_pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "P100", "sku_code": "S100-COMBO"}},
        query="can I purchase an accessory separately",
        allowed_source_types=["product_facts"],
        query_fact_type="accessory_availability",
    )

    assert [fact["fact_type"] for fact in contents_pack["facts"]] == ["included_items"]
    assert contents_pack["facts"][0]["chunk_text"] == "main item x1; ball x2"
    assert contents_pack["product_first_evidence_pack"]["answerability"] == "direct_answer"
    assert availability_pack["facts"] == []
    assert availability_pack["product_first_evidence_pack"]["answerability"] != "direct_answer"


def test_exact_hub_selected_sku_spec_answers_selected_configuration(product_context_db, monkeypatch):
    """A confirmed SKU specification may identify its selected configuration."""
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "P100"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "S100-COMBO"},
            "facts": [{
                "fact_uid": "product_data_hub:fact-selected-spec",
                "fact_type": "spec",
                "attribute_key": "selected_configuration",
                "value": "configuration-1",
                "unit": "",
                "scope": "product",
                "applies": "S100-COMBO",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
            }],
            "assets": [],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "P100", "sku_code": "S100-COMBO"}},
        query="which selected configuration does this SKU represent",
        allowed_source_types=["product_facts"],
        query_fact_type="included_items",
    )

    assert [fact["fact_type"] for fact in pack["facts"]] == ["included_items"]
    assert pack["facts"][0]["chunk_text"] == "configuration-1"
    assert pack["product_first_evidence_pack"]["answerability"] == "direct_answer"


def test_exact_hub_packaging_gross_weight_answers_gross_weight(product_context_db, monkeypatch):
    """A verified packaging gross-weight field answers a packing-weight goal."""
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "P100"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "S100-COMBO"},
            "facts": [{
                "fact_uid": "product_data_hub:fact-gross-weight",
                "fact_type": "weight",
                "attribute_key": "毛重",
                "value": "14.16",
                "unit": "kg",
                "scope": "packaging",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
            }],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "P100", "sku_code": "S100-COMBO"}},
        query="外箱大概多重",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )

    assert [fact["fact_type"] for fact in pack["facts"]] == ["gross_weight"]
    assert pack["facts"][0]["chunk_text"] == "14.16kg"
    assert pack["facts"][0]["fact_scope"] == "packaging"
    assert pack["product_first_evidence_pack"]["answerability"] == "direct_answer"


def test_exact_hub_net_product_weight_does_not_answer_gross_weight(product_context_db, monkeypatch):
    """A product net weight cannot be presented as a packaging gross weight."""
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "P100"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "S100-COMBO"},
            "facts": [{
                "fact_uid": "product_data_hub:fact-net-weight",
                "fact_type": "weight",
                "attribute_key": "净重",
                "value": "12.95",
                "unit": "kg",
                "scope": "product",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
            }],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "P100", "sku_code": "S100-COMBO"}},
        query="外箱大概多重",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )

    assert pack["facts"] == []


def test_hub_packaging_size_does_not_satisfy_product_dimensions(product_context_db, monkeypatch):
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "YH91K01"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "YH91K01B01S01"},
            "facts": [{
                "fact_uid": "product_data_hub:fact-pack-size",
                "fact_type": "pack_size",
                "attribute_key": "carton_size",
                "value": "71x43x16.5",
                "unit": "cm",
                "scope": "packaging",
                "applies": "carton",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
            }],
            "assets": [],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "YH91K01", "sku_code": "YH91K01B01S01"}},
        query="商品整体尺寸多大",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    assert not any(
        fact.get("source_table") == "product_data_hub"
        for fact in pack["facts"]
    )


def test_confirmed_exact_hub_material_carries_trusted_material_provenance(product_context_db, monkeypatch):
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "YH91K01"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "YH91K01B01S01"},
            "facts": [{
                "fact_uid": "product_data_hub:fact-material",
                "fact_type": "material",
                "attribute_key": "material",
                "value": "PP",
                "unit": "",
                "scope": "product",
                "applies": "body",
                "review_status": "confirmed",
                "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
            }],
            "assets": [],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "YH91K01", "sku_code": "YH91K01B01S01"}},
        query="这款是什么材质",
        allowed_source_types=["product_facts"],
        query_fact_type="material",
    )

    hub_fact = next(fact for fact in pack["facts"] if fact.get("source_table") == "product_data_hub")
    assert hub_fact["material_provenance"] == "product_data_hub_confirmed"
    assert hub_fact["metadata"]["material_provenance"] == "product_data_hub_confirmed"


def test_hub_dimension_facts_default_to_product_scope_for_product_dimension_question(product_context_db, monkeypatch):
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "YH91K01"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "YH91K01B01S01"},
            "facts": [
                {
                    "fact_uid": "product_data_hub:fact-product-size",
                    "fact_type": "size",
                    "attribute_key": "size",
                    "value": "45x42x70",
                    "unit": "cm",
                    "scope": "product",
                    "review_status": "confirmed",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
                {
                    "fact_uid": "product_data_hub:fact-package-size",
                    "fact_type": "pack_size",
                    "attribute_key": "carton_size",
                    "value": "71x43x16.5",
                    "unit": "cm",
                    "scope": "packaging",
                    "review_status": "confirmed",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
            ],
            "assets": [],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"slots": {"i_id": "YH91K01", "sku_code": "YH91K01B01S01"}},
        query="尺寸多大",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    scoped_facts = {
        fact["chunk_id"]: fact.get("subject_scope")
        for fact in pack["facts"]
        if fact.get("source_table") == "product_data_hub"
    }
    assert scoped_facts == {
        "product_data_hub:fact-product-size": "product",
    }

    packaging_pack = product_context_pack_service.build_product_context_pack(
        {
            "slots": {"i_id": "YH91K01", "sku_code": "YH91K01B01S01"},
            "semantic_query": {"subject_scope": "packaging"},
        },
        query="尺寸多大",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )
    packaging_scopes = {
        fact["chunk_id"]: fact.get("subject_scope")
        for fact in packaging_pack["facts"]
        if fact.get("source_table") == "product_data_hub"
    }
    assert packaging_scopes == {
        "product_data_hub:fact-package-size": "packaging",
    }


def test_hub_dimension_facts_include_every_authoritative_requested_subject_scope(
    product_context_db,
    monkeypatch,
):
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_DATA_HUB_ENABLED", True, raising=False)
    monkeypatch.setattr(
        config,
        "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "match_reason": "exact_product_and_sku_code",
            "product": {
                "hub_product_id": "hub-product-1",
                "product_code": "P100",
                "product_name": "Multi-scope product",
            },
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "S100-COMBO"},
            "facts": [
                {
                    "fact_uid": "product_data_hub:product-size",
                    "fact_type": "size",
                    "attribute_key": "size",
                    "value": "45x42x70",
                    "unit": "cm",
                    "scope": "product",
                    "review_status": "confirmed",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
                {
                    "fact_uid": "product_data_hub:pack-width",
                    "fact_type": "pack_size",
                    "attribute_key": "纸箱宽",
                    "value": "26",
                    "unit": "cm",
                    "scope": "packaging",
                    "review_status": "confirmed",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
                {
                    "fact_uid": "product_data_hub:pack-length",
                    "fact_type": "pack_size",
                    "attribute_key": "纸箱长",
                    "value": "81",
                    "unit": "cm",
                    "scope": "packaging",
                    "review_status": "confirmed",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
                {
                    "fact_uid": "product_data_hub:pack-height",
                    "fact_type": "pack_size",
                    "attribute_key": "纸箱高",
                    "value": "65.5",
                    "unit": "cm",
                    "scope": "packaging",
                    "review_status": "confirmed",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
            ],
            "assets": [],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {
            "slots": {"i_id": "P100", "sku_code": "S100-COMBO"},
            "semantic_query": {"subject_scope": "product"},
            "turn_understanding": {
                "schema_version": "turn-understanding/v2",
                "owner": "turn_understanding_owner",
                "source_stage": "query_fact_type_classifier",
                "goal_understanding_status": "valid",
                "requested_claims": [
                    {
                        "goal_kind": "customer_goal",
                        "claim_type": "dimensions",
                        "claim_type_status": "canonical",
                        "attribute_key": "overall_dimensions",
                        "subject_scope": "product",
                    },
                    {
                        "goal_kind": "customer_goal",
                        "claim_type": "dimensions",
                        "claim_type_status": "canonical",
                        "attribute_key": "overall_dimensions",
                        "subject_scope": "packaging",
                    },
                ],
            },
        },
        query="Compare the two requested dimension scopes",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    projected = {
        fact["chunk_id"]: fact.get("subject_scope")
        for fact in pack["facts"]
        if fact.get("source_table") == "product_data_hub"
    }
    assert projected == {
        "product_data_hub:product-size": "product",
        "product_data_hub:pack-width": "packaging",
        "product_data_hub:pack-length": "packaging",
        "product_data_hub:pack-height": "packaging",
    }


def test_hub_packaging_axis_labels_project_canonical_dimension_attributes(product_context_db, monkeypatch):
    import app.config as config
    from app.services import product_context_pack_service

    monkeypatch.setattr(config, "COPILOT_PRODUCT_HUB_MULTIMODAL_DELIVERY_ENABLED", True, raising=False)
    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_bundle",
        lambda **_kwargs: {
            "status": "resolved",
            "used_for_fact": True,
            "product": {"hub_product_id": "hub-product-1", "product_code": "P100"},
            "sku": {"hub_sku_id": "hub-sku-1", "sku_code": "S100-COMBO"},
            "facts": [
                {
                    "fact_uid": "product_data_hub:pack-width",
                    "fact_type": "pack_size",
                    "attribute_key": "纸箱宽",
                    "value": "26",
                    "unit": "cm",
                    "scope": "包装",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
                {
                    "fact_uid": "product_data_hub:pack-length",
                    "fact_type": "pack_size",
                    "attribute_key": "纸箱长",
                    "value": "81",
                    "unit": "cm",
                    "scope": "包装",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
                {
                    "fact_uid": "product_data_hub:pack-height",
                    "fact_type": "pack_size",
                    "attribute_key": "纸箱高",
                    "value": "65.5",
                    "unit": "cm",
                    "scope": "包装",
                    "identity_scope": {"hub_product_id": "hub-product-1", "hub_sku_id": "hub-sku-1"},
                },
            ],
            "assets": [],
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {
            "slots": {"i_id": "P100", "sku_code": "S100-COMBO"},
            "semantic_query": {"subject_scope": "packaging"},
        },
        query="尺寸多大",
        allowed_source_types=["product_facts"],
        query_fact_type="dimensions",
    )

    projected = {
        fact["chunk_id"]: fact.get("canonical_attribute_key")
        for fact in pack["facts"]
        if fact.get("source_table") == "product_data_hub"
    }
    assert projected == {
        "product_data_hub:pack-width": "width",
        "product_data_hub:pack-length": "length",
        "product_data_hub:pack-height": "height",
    }
    compacted = {
        fact["chunk_id"]: (
            fact.get("canonical_attribute_key"),
            fact.get("subject_scope"),
        )
        for fact in pack["evidence_pack"]["product_structured_facts"]
    }
    assert compacted == {
        "product_data_hub:pack-width": ("width", "packaging"),
        "product_data_hub:pack-length": ("length", "packaging"),
        "product_data_hub:pack-height": ("height", "packaging"),
    }


def test_product_context_pack_strict_fact_type_does_not_use_installation_for_detachable(product_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="\u4e00\u53f7\u5582\u517b\u67dc\u5b89\u88c5\u8bf4\u660e",
            content="\u5148\u62fc\u63a5\u5e95\u677f\uff0c\u518d\u5b89\u88c5\u4fa7\u677f\u3002",
            source_type="installation_guide",
            fact_type="installation",
            product_scope=["YH88K01", "\u4e00\u53f7\u5582\u517b\u67dc"],
            sku_scope=["YH88K01"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "YH88K01B09S26"},
            "matched_product_name": "\u4e00\u53f7\u5582\u517b\u67dc",
        },
        query="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417",
        allowed_source_types=["installation_guide", "product_facts", "faq"],
        query_fact_type="detachable",
    )

    assert pack["facts"] == []


def test_product_context_pack_can_return_product_scoped_kbqa(product_context_db):
    from app.models.kb_tables import KBProduct, KBQA
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH06K53",
            product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH06K53"}]),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add(KBQA(
            question="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc\u6750\u8d28\u662f\u4ec0\u4e48\uff1f",
            answer="\u4e3b\u8981\u91c7\u7528\u51b7\u8f67\u94a2\u7ba1\u548c\u73af\u4fddPP\u6750\u8d28\u3002",
            product_id=product.id,
            sku_codes_json=json.dumps(["YH06K53"], ensure_ascii=False),
            source_type="faq",
            status="published",
            auto_reply=True,
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "YH06K53B05S13"},
            "matched_product_name": "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
        },
        query="\u6750\u8d28\u5b89\u5168\u5417",
        allowed_source_types=["faq"],
        query_fact_type="material",
    )

    assert pack["facts"]
    assert pack["facts"][0]["entry_id"] == "kbqa:1"
    assert pack["facts"][0]["fact_type"] == "material"
    assert "Q:" not in pack["facts"][0]["chunk_text"]
    assert "A:" not in pack["facts"][0]["chunk_text"]
    assert "\u4e3b\u8981\u91c7\u7528" in pack["facts"][0]["chunk_text"]


def test_product_context_pack_uses_material_kbqa_with_no_odor_for_odor_query(product_context_db):
    from app.models.kb_tables import KBProduct, KBQA
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH64K01",
            product_name="\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
            sku_list_json=json.dumps([{"sku_code": "YH64K01"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add(KBQA(
            question="\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f\u7684\u6750\u8d28\u5b89\u5168\u73af\u4fdd\u5417\uff1f",
            answer="\u91c7\u7528\u98df\u54c1\u7ea7HDPE/PP\u73af\u4fdd\u6750\u6599\uff0c\u65e0\u6bd2\u65e0\u5473\uff0c\u4e0d\u542bBPA\u7b49\u6709\u5bb3\u7269\u8d28\u3002",
            product_id=product.id,
            sku_codes_json=json.dumps(["YH64K01"], ensure_ascii=False),
            source_type="faq",
            status="published",
            auto_reply=True,
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "YH64K01"},
            "matched_product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
        },
        query="\u4ea7\u54c1\u6709\u6c14\u5473\u5417",
        allowed_source_types=["faq"],
        query_fact_type="odor",
    )

    assert pack["facts"]
    assert pack["facts"][0]["entry_id"] == "kbqa:1"
    assert pack["facts"][0]["fact_type"] == "odor"
    assert "\u65e0\u6bd2\u65e0\u5473" in pack["facts"][0]["chunk_text"]


def test_product_context_pack_returns_structured_profile(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH88K01",
            product_name="\u4e00\u53f7\u5582\u517b\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH88K01B09S26", "sku_name": "\u767d\u8272"}], ensure_ascii=False),
            specs_json=json.dumps({
                "material": "\u73af\u4fddPP",
                "size": "80*40*90cm",
                "install_method": "\u5361\u6263\u5f0f\u7ec4\u88c5",
            }, ensure_ascii=False),
            logistics_json=json.dumps({"package_weight": "8kg"}, ensure_ascii=False),
            warranty_json=json.dumps({"warranty": "\u6309\u5e97\u94fa\u552e\u540e\u653f\u7b56"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH88K01B09S26"}, "matched_product_name": "\u4e00\u53f7\u5582\u517b\u67dc"},
        query="\u8fd9\u4e2a\u600e\u4e48\u5b89\u88c5",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="installation",
    )

    profile = pack["structured_profile"]
    assert profile["i_id"] == "YH88K01"
    assert profile["specs"]["install_method"] == "\u5361\u6263\u5f0f\u7ec4\u88c5"
    assert "installation" in profile["answerable_fields"]
    assert pack["stats"]["has_structured_profile"] is True
    assert "structured_profile" not in pack["evidence_pack"]
    assert pack["evidence_pack"]["answerability"] == "direct_answer"
    assert pack["evidence_pack"]["matched_fields"] == ["installation"]


def test_product_context_pack_answers_color_options_from_active_explicit_sku_fields(
    product_context_db,
):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="COLOR_PRODUCT_001",
            product_name="color fixture product",
            sku_list_json=json.dumps([
                {"sku_code": "COLOR-A", "color": "奶油白", "enabled": True},
                {"sku_code": "COLOR-B", "color": "薄荷绿", "enabled": "true"},
                {"sku_code": "COLOR-C", "color": "奶油白", "enabled": 1},
                {"sku_code": "COLOR-D", "color": "下架灰", "enabled": False},
            ], ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "i_id": "COLOR_PRODUCT_001",
            "slots": {"sku_code": "COLOR-A"},
        },
        query="这款还有其他颜色吗",
        allowed_source_types=["product_facts"],
        query_fact_type="color_options",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "color_options"
    assert "奶油白、薄荷绿" in pack["facts"][0]["chunk_text"]
    assert "下架灰" not in pack["facts"][0]["chunk_text"]
    assert pack["facts"][0]["sku_scope"] == ["COLOR-A", "COLOR-B", "COLOR-C"]
    assert "color_options" in pack["structured_profile"]["answerable_fields"]
    assert pack["evidence_pack"]["matched_fields"] == ["color_options"]


def test_product_context_pack_does_not_infer_color_from_sku_name(
    product_context_db,
):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="COLOR_PRODUCT_002",
            product_name="color inference guard product",
            sku_list_json=json.dumps([
                {"sku_code": "COLOR-NAME-A", "sku_name": "升级款奶油白"},
                {"sku_code": "COLOR-NAME-B", "name": "薄荷绿组合"},
            ], ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "i_id": "COLOR_PRODUCT_002",
            "slots": {"sku_code": "COLOR-NAME-A"},
        },
        query="有哪些颜色可选",
        allowed_source_types=["product_facts"],
        query_fact_type="color_options",
    )

    assert pack["facts"] == []
    assert "color_options" not in pack["structured_profile"]["answerable_fields"]
    assert pack["evidence_pack"]["missing_fields"] == ["color_options"]


def test_structured_profile_excludes_internal_backfill_provenance():
    from app.services.product_context_pack_service import _clean_mapping

    assert _clean_mapping({
        "material": "PP",
        "trusted_auto_backfill": {"source_file": "private/source.xlsx"},
        "_trusted_auto_backfill": {"source_sha256": "a" * 64},
    }) == {"material": "PP"}


def test_exact_identity_pending_product_is_not_used_as_structured_evidence(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import _find_kb_product

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="PENDING_PRODUCT",
            product_name="candidate product",
            specs_json=json.dumps({"material": "candidate material"}),
            status="pending_review",
        ))
        db.commit()

        product = _find_kb_product(
            db,
            KBProduct,
            {"sku": "", "i_id": "PENDING_PRODUCT", "sku_family": "", "product_name": ""},
        )
    finally:
        db.close()

    assert product is None


def test_product_context_pack_turns_exact_profile_field_into_fact(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH88K01",
            product_name="\u4e00\u53f7\u5582\u517b\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH88K01B09S26"}], ensure_ascii=False),
            specs_json=json.dumps({
                "install_method": "\u514d\u6253\u5b54\uff0c\u5361\u6263\u5f0f\u7ec4\u88c5",
                "material": "\u73af\u4fddPP",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH88K01B09S26"}, "matched_product_name": "\u4e00\u53f7\u5582\u517b\u67dc"},
        query="\u79df\u623f\u80fd\u7528\u5417\uff1f\u8981\u6253\u5b54\u5417\uff1f",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="installation",
    )

    assert pack["facts"]
    assert pack["facts"][0]["entry_id"] == "kbproduct:1"
    assert pack["facts"][0]["fact_type"] == "installation"
    assert "\u514d\u6253\u5b54" in pack["facts"][0]["chunk_text"]
    assert pack["evidence_pack"]["matched_facts"][0]["fact_type"] == "installation"


def test_product_context_pack_builds_low_risk_product_overview(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="OVERVIEW_PRODUCT_001",
            product_name="overview fixture product",
            sku_list_json=json.dumps([
                {"sku_code": "OVERVIEW_PRODUCT_001-A"},
            ]),
            specs_json=json.dumps({
                "material": "PP",
                "size": "60*40*90cm",
                "install_method": "卡扣式组装",
                "load_capacity": "100kg",
                "certification": "检测合格",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "i_id": "OVERVIEW_PRODUCT_001",
            "slots": {"sku_code": "OVERVIEW_PRODUCT_001-A"},
        },
        query="general product assessment",
        allowed_source_types=["product_facts"],
        query_fact_type="product_overview",
    )

    product_first = pack["product_first_evidence_pack"]
    assert product_first["answerability"] == "direct_answer"
    assert product_first["requested_fact_type"] == "product_overview"
    assert product_first["matched_fields"] == ["product_overview"]
    assert len(product_first["product_structured_facts"]) == 1
    fact = product_first["product_structured_facts"][0]
    assert fact["fact_type"] == "product_overview"
    assert "PP" in fact["customer_text"]
    assert "60*40*90cm" in fact["customer_text"]
    assert "卡扣式组装" in fact["customer_text"]
    assert "100kg" not in fact["customer_text"]
    assert "检测合格" not in fact["customer_text"]


def test_product_context_pack_answers_gross_weight_from_product_card(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_WEIGHT_001",
            product_name="\u6d4b\u8bd5\u7f6e\u7269\u67b6",
            sku_list_json=json.dumps([{"sku_code": "TEST_WEIGHT_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"size": "80*40*90cm", "load_capacity": "20kg"}, ensure_ascii=False),
            logistics_json=json.dumps({"package_weight": "7.5kg"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_WEIGHT_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u7f6e\u7269\u67b6"},
        query="\u8fd9\u4e2a\u591a\u91cd",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="gross_weight",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "gross_weight"
    assert "7.5kg" in pack["facts"][0]["chunk_text"]
    assert "package_weight:" not in pack["facts"][0]["chunk_text"]
    assert pack["facts"][0]["protocol_source_type"] == "product_spec"
    assert pack["facts"][0]["source_table"] == "kb_product"
    assert pack["facts"][0]["can_direct_answer"] is True
    assert pack["evidence_pack"]["answerability"] == "direct_answer"
    assert "gross_weight" in pack["evidence_pack"]["matched_fields"]
    assert "load_capacity" not in pack["evidence_pack"]["matched_fields"]
    matched = pack["evidence_pack"]["matched_facts"][0]
    assert matched["evidence_id"].startswith("kbproduct:")
    assert matched["source_table"] == "kb_product"
    assert matched["protocol_source_type"] == "product_spec"
    assert pack["product_first_evidence_pack"]["requested_fact_type"] == "gross_weight"
    assert pack["product_first_evidence_pack"]["product_structured_facts"][0]["fact_type"] == "gross_weight"
    assert pack["product_first_evidence_pack"]["missing_required_evidence"] == []


def test_product_context_pack_rereads_mutable_product_fact_with_versioned_evidence(
    product_context_db,
):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="DYNAMIC_WEIGHT_001",
            product_name="dynamic product",
            sku_list_json=json.dumps([{"sku_code": "DYNAMIC_WEIGHT_001-A"}]),
            logistics_json=json.dumps({"package_weight": "7.5kg"}),
            status="published",
            version=1,
            updated_at=datetime(2026, 8, 17, 8, 0, 0),
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    state = {
        "i_id": "DYNAMIC_WEIGHT_001",
        "slots": {"sku_code": "DYNAMIC_WEIGHT_001-A"},
    }
    first = build_product_context_pack(
        state,
        query="how much does it weigh",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )

    db = product_context_db()
    try:
        product = db.query(KBProduct).filter(KBProduct.i_id == "DYNAMIC_WEIGHT_001").one()
        product.set_logistics({"package_weight": "8.2kg"})
        product.version = 2
        product.updated_at = datetime(2026, 8, 17, 9, 0, 0)
        db.commit()
    finally:
        db.close()

    second = build_product_context_pack(
        state,
        query="how much does it weigh",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )

    first_fact = first["facts"][0]
    second_fact = second["facts"][0]
    assert "7.5kg" in first_fact["chunk_text"]
    assert "8.2kg" in second_fact["chunk_text"]
    assert first_fact["evidence_id"] != second_fact["evidence_id"]
    assert first_fact["value_sha256"] != second_fact["value_sha256"]
    assert second_fact["source_version"] == 2
    assert second_fact["source_updated_at"] == "2026-08-17T09:00:00"


def test_product_context_pack_drops_deleted_mutable_product_fact(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="DYNAMIC_DELETE_001",
            product_name="dynamic deletion product",
            logistics_json=json.dumps({"package_weight": "6.4kg"}),
            status="published",
            version=1,
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    state = {"i_id": "DYNAMIC_DELETE_001"}
    first = build_product_context_pack(
        state,
        query="how much does it weigh",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )
    assert "6.4kg" in first["facts"][0]["chunk_text"]

    db = product_context_db()
    try:
        product = db.query(KBProduct).filter(KBProduct.i_id == "DYNAMIC_DELETE_001").one()
        product.set_logistics({})
        product.version = 2
        db.commit()
    finally:
        db.close()

    second = build_product_context_pack(
        state,
        query="how much does it weigh",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )
    assert second["facts"] == []
    assert second["evidence_pack"]["answerability"] == "missing_product_fact"
    assert second["evidence_pack"]["missing_fields"] == ["gross_weight"]


def test_product_context_pack_answers_gross_weight_from_sku_variants(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_WEIGHT_SKU_001",
            product_name="\u6d4b\u8bd5\u591a\u89c4\u683c\u7f6e\u7269\u67b6",
            sku_list_json=json.dumps([
                {
                    "sku_code": "TEST_WEIGHT_SKU_001",
                    "sku_variant_key": "TEST_WEIGHT_SKU_001|\u7ec4\u54081|\u767d\u8272",
                    "spec": "\u7ec4\u54081",
                    "color": "\u767d\u8272",
                    "gross_weight_kg": "3.15",
                },
                {
                    "sku_code": "TEST_WEIGHT_SKU_001",
                    "sku_variant_key": "TEST_WEIGHT_SKU_001|\u7ec4\u54082|\u767d\u8272",
                    "spec": "\u7ec4\u54082",
                    "color": "\u767d\u8272",
                    "gross_weight_kg": "4.2",
                },
            ], ensure_ascii=False),
            specs_json=json.dumps({"load_capacity": "20kg"}, ensure_ascii=False),
            logistics_json=json.dumps({}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_WEIGHT_SKU_001"}, "matched_product_name": "\u6d4b\u8bd5\u591a\u89c4\u683c\u7f6e\u7269\u67b6"},
        query="\u6bdb\u91cd\u591a\u5c11",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="gross_weight",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "gross_weight"
    assert "\u7ec4\u54081 \u767d\u8272\uff1a3.15kg" in pack["facts"][0]["chunk_text"]
    assert "\u7ec4\u54082 \u767d\u8272\uff1a4.2kg" in pack["facts"][0]["chunk_text"]
    assert "load_capacity" not in pack["evidence_pack"]["matched_fields"]


def test_product_context_pack_limits_gross_weight_to_exact_sku(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="SKU_SCOPE_001",
            product_name="sku scoped product",
            sku_list_json=json.dumps([
                {"sku_code": "SKU-SCOPE-A", "gross_weight_kg": "3.1"},
                {"sku_code": "SKU-SCOPE-B", "gross_weight_kg": "4.2"},
            ]),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"i_id": "SKU_SCOPE_001", "slots": {"sku_code": "SKU-SCOPE-A"}},
        query="how much does this variant weigh",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )

    assert "3.1kg" in pack["facts"][0]["chunk_text"]
    assert "4.2kg" not in pack["facts"][0]["chunk_text"]
    assert pack["facts"][0]["sku_scope"] == ["SKU-SCOPE-A"]
    assert pack["evidence_pack"]["matched_facts"][0]["sku_scope"] == ["SKU-SCOPE-A"]


def test_product_context_pack_does_not_borrow_weight_for_unknown_sku(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="SKU_SCOPE_002",
            product_name="sku mismatch product",
            sku_list_json=json.dumps([
                {"sku_code": "SKU-SCOPE-A", "gross_weight_kg": "3.1"},
                {"sku_code": "SKU-SCOPE-B", "gross_weight_kg": "4.2"},
            ]),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"i_id": "SKU_SCOPE_002", "slots": {"sku_code": "SKU-SCOPE-UNKNOWN"}},
        query="how much does this variant weigh",
        allowed_source_types=["product_facts"],
        query_fact_type="gross_weight",
    )

    assert pack["facts"] == []
    assert pack["evidence_pack"]["answerability"] == "missing_product_fact"
    assert pack["evidence_pack"]["missing_fields"] == ["gross_weight"]


def test_product_context_pack_answers_accessory_availability_from_product_card(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_ACCESSORY_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_ACCESSORY_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({
                "install_method": "\u5361\u6263\u5f0f\u7ec4\u88c5",
                "accessory_availability": "\u914d\u4ef6\u9700\u6309\u5f53\u524dSKU\u4eba\u5de5\u6838\u5bf9\u662f\u5426\u53ef\u8865\u8d2d",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_ACCESSORY_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="accessory_availability",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "accessory_availability"
    assert "\u8865\u8d2d" in pack["facts"][0]["chunk_text"]
    assert pack["facts"][0]["source_table"] == "kb_product"
    assert pack["evidence_pack"]["answerability"] == "direct_answer"
    assert "accessory_availability" in pack["evidence_pack"]["matched_fields"]
    assert "installation" not in pack["evidence_pack"]["matched_fields"]


def test_product_context_pack_does_not_answer_accessory_availability_from_parts_list(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_ACCESSORY_LIST_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_ACCESSORY_LIST_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({
                "accessories": "\u87ba\u4e1d\u3001\u9632\u5012\u5668\u3001\u8d34\u7247",
                "install_method": "\u5361\u6263\u5f0f\u7ec4\u88c5",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_ACCESSORY_LIST_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="accessory_availability",
    )

    assert pack["facts"] == []
    assert pack["evidence_pack"]["answerability"] == "missing_product_fact"
    assert pack["evidence_pack"]["missing_fields"] == ["accessory_availability"]
    assert pack["product_first_evidence_pack"]["product_structured_facts"] == []
    assert {"evidence_type": "product_fact", "fact_type": "accessory_availability"} in pack["product_first_evidence_pack"]["missing_required_evidence"]


def test_product_context_pack_does_not_infer_pinch_safety_from_profile(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH06K53",
            product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH06K53B05S13"}], ensure_ascii=False),
            specs_json=json.dumps({
                "material": "\u51b7\u8f67\u94a2\u7ba1+PP",
                "install_method": "\u5361\u6263\u5f0f\u7ec4\u88c5",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH06K53B05S13"}, "matched_product_name": "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc"},
        query="\u5bb6\u91cc\u6709\u5b9d\u5b9d\uff0c\u4f1a\u4e0d\u4f1a\u5939\u624b\uff1f",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="pinch_safety",
    )

    assert pack["facts"] == []
    assert pack["evidence_pack"]["answerability"] == "missing_product_fact"
    assert pack["evidence_pack"]["missing_fields"] == ["pinch_safety"]


def test_product_context_pack_answers_material_from_product_card_without_raw_field_label(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_MATERIAL_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_MATERIAL_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "\u51b7\u8f67\u94a2\u7ba1+PP"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_MATERIAL_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u8fd9\u4e2a\u6750\u8d28\u662f\u4ec0\u4e48",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="material",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "material"
    assert "\u51b7\u8f67\u94a2\u7ba1+PP" in pack["facts"][0]["chunk_text"]
    assert "material:" not in pack["facts"][0]["chunk_text"]
    assert pack["facts"][0]["source_table"] == "kb_product"
    assert pack["evidence_pack"]["answerability"] == "direct_answer"


def test_product_context_pack_does_not_use_material_as_certification_report(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_CERT_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_CERT_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "PP/ABS"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_CERT_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u6709\u6ca1\u6709\u68c0\u6d4b\u62a5\u544a",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="certification_report",
    )

    assert pack["facts"] == []
    assert pack["evidence_pack"]["answerability"] == "missing_product_fact"
    assert pack["evidence_pack"]["missing_fields"] == ["certification_report"]


def test_product_context_pack_returns_ranked_media_assets(product_context_db):
    from datetime import datetime, timedelta

    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="YH06K53",
            product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH06K53B05S13"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add_all([
            KBMediaAsset(
                product_id=product.id,
                i_id="YH06K53",
                sku_code="YH06K53B05S13",
                product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
                asset_type="install_video",
                asset_title="\u5b89\u88c5\u89c6\u9891",
                asset_url="https://example.com/install.mp4",
                status="approved",
                usable_for_agent=1,
                refresh_status="ok",
                match_confidence=0.95,
                url_expires_at=datetime.utcnow() + timedelta(days=1),
            ),
            KBMediaAsset(
                product_id=product.id,
                i_id="YH06K53",
                sku_code="YH06K53B05S13",
                product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
                asset_type="sku_image",
                asset_title="\u5546\u54c1\u56fe",
                asset_url="https://example.com/sku.jpg",
                status="approved",
                usable_for_agent=1,
                refresh_status="ok",
                match_confidence=0.8,
            ),
        ])
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH06K53B05S13"}, "matched_product_name": "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc"},
        query="\u6709\u5b89\u88c5\u89c6\u9891\u5417",
        allowed_source_types=["installation_guide", "faq"],
        query_fact_type="installation",
    )

    assert len(pack["media_assets"]) == 2
    assert pack["recommended_assets"]
    assert pack["recommended_assets"][0]["asset_type"] == "install_video"
    assert pack["stats"]["recommended_media_count"] == 1
    assert pack["evidence_pack"]["matched_media"][0]["asset_type"] == "install_video"
    assert pack["product_first_evidence_pack"]["product_media_assets"][0]["evidence_media_type"] == "installation_video"
    assert pack["product_first_evidence_pack"]["product_media_assets"][0]["can_direct_answer"] is True


def test_product_context_pack_answers_detachable_from_product_card(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_CARD_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_CARD_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({
                "detachable": "\u5e95\u677f\u548c\u4fa7\u677f\u652f\u6301\u62c6\u88c5",
                "size": "80*40*90cm",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_CARD_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="detachable",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "detachable"
    assert "\u652f\u6301\u62c6\u88c5" in pack["facts"][0]["chunk_text"]
    assert pack["evidence_pack"]["answerability"] == "direct_answer"
    assert "detachable" in pack["evidence_pack"]["matched_fields"]


def test_product_context_pack_does_not_invent_detachable_when_product_card_missing_field(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_DETACHABLE_DEFAULT_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_DETACHABLE_DEFAULT_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"size": "80*40*90cm"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_DETACHABLE_DEFAULT_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="detachable",
    )

    assert pack["facts"] == []
    assert pack["evidence_pack"]["answerability"] == "missing_product_fact"
    assert pack["evidence_pack"]["missing_fields"] == ["detachable"]


def test_product_context_pack_answers_odor_from_product_card(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_ODOR_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_ODOR_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({
                "odor_note": "\u65b0\u54c1\u5bc6\u5c01\u5305\u88c5\u6253\u5f00\u540e\u53ef\u80fd\u6709\u8f7b\u5fae\u5305\u88c5\u6c14\u5473\uff0c\u901a\u98ce\u540e\u4f1a\u9010\u6b65\u6563\u53bb\u3002",
                "material": "\u73af\u4fddPP",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_ODOR_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u4ea7\u54c1\u6709\u5473\u9053\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="odor",
    )

    assert pack["facts"]
    assert pack["facts"][0]["fact_type"] == "odor"
    assert "odor_note" not in pack["facts"][0]["chunk_text"]
    assert "\u901a\u98ce" in pack["facts"][0]["chunk_text"]
    assert pack["evidence_pack"]["answerability"] == "direct_answer"
    assert pack["evidence_pack"]["matched_facts"][0]["fact_type"] == "odor"


def test_product_context_pack_does_not_invent_odor_when_product_card_missing_field(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_ODOR_DEFAULT_001",
            product_name="\u6d4b\u8bd5\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_ODOR_DEFAULT_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "\u73af\u4fddPP"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_ODOR_DEFAULT_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc"},
        query="\u4ea7\u54c1\u6709\u5473\u9053\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="odor",
    )

    assert pack["facts"] == []
    assert pack["generic_rules"]
    assert pack["generic_rules"][0]["fact_type"] == "odor"
    assert pack["evidence_pack"]["answerability"] == "generic_rule_fallback"
    assert pack["evidence_pack"]["missing_fields"] == ["odor"]


def test_product_context_pack_uses_tagged_media_for_detachable(product_context_db):
    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_MEDIA_CARD_001",
            product_name="\u6d4b\u8bd5\u5582\u517b\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_MEDIA_CARD_001B01S01"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        size_asset = KBMediaAsset(
            product_id=product.id,
            i_id="TEST_MEDIA_CARD_001",
            sku_code="TEST_MEDIA_CARD_001B01S01",
            product_name="\u6d4b\u8bd5\u5582\u517b\u67dc",
            asset_type="size_image",
            asset_title="\u5c3a\u5bf8\u548c\u62c6\u5378\u8bf4\u660e\u56fe",
            asset_url="https://example.com/size-detachable.png",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.85,
        )
        size_asset.set_scene_tags(["detachable", "dimensions"])
        sku_asset = KBMediaAsset(
            product_id=product.id,
            i_id="TEST_MEDIA_CARD_001",
            sku_code="TEST_MEDIA_CARD_001B01S01",
            product_name="\u6d4b\u8bd5\u5582\u517b\u67dc",
            asset_type="sku_image",
            asset_title="\u5546\u54c1\u56fe",
            asset_url="https://example.com/sku.png",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.99,
        )
        db.add_all([size_asset, sku_asset])
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_MEDIA_CARD_001B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u5582\u517b\u67dc"},
        query="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="detachable",
    )

    assert pack["recommended_assets"]
    assert pack["recommended_assets"][0]["asset_type"] == "size_image"
    assert pack["facts"]
    assert any(item["entry_id"].startswith("kbmedia:") for item in pack["facts"])
    media_fact = next(item for item in pack["facts"] if item["entry_id"].startswith("kbmedia:"))
    assert media_fact["fact_type"] == "detachable"
    assert media_fact["source_type"] == "media_reference"
    assert media_fact["evidence_role"] == "media_reference"
    assert media_fact["reference_only"] is True
    assert media_fact["can_direct_answer"] is False
    assert media_fact["evidence_allowed_for_direct_answer"] is False
    assert "\u62c6\u88c5" in media_fact["chunk_text"]
    assert "\u7ed3\u6784" in media_fact["chunk_text"]
    assert "\u5df2\u5339\u914d" not in media_fact["chunk_text"]


def test_product_context_pack_does_not_use_untagged_size_image_as_detachable_fact(product_context_db):
    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_MEDIA_CARD_002",
            product_name="\u6d4b\u8bd5\u7f6e\u7269\u67dc",
            sku_list_json=json.dumps([{"sku_code": "TEST_MEDIA_CARD_002B01S01"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add(KBMediaAsset(
            product_id=product.id,
            i_id="TEST_MEDIA_CARD_002",
            sku_code="TEST_MEDIA_CARD_002B01S01",
            product_name="\u6d4b\u8bd5\u7f6e\u7269\u67dc",
            asset_type="size_image",
            asset_title="\u5c3a\u5bf8\u56fe",
            asset_url="https://example.com/size.png",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.95,
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_MEDIA_CARD_002B01S01"}, "matched_product_name": "\u6d4b\u8bd5\u7f6e\u7269\u67dc"},
        query="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="detachable",
    )

    assert pack["recommended_assets"]
    assert not any(item["entry_id"].startswith("kbmedia:") for item in pack["facts"])


def test_rag_retrieve_merges_product_context_pack_when_primary_retriever_is_empty(product_context_db, monkeypatch):
    from app.agent.nodes.rag_retrieve import rag_retrieve
    import app.retrieval.retriever_factory as retriever_factory

    class EmptyRetriever:
        def retrieve(self, **kwargs):
            return []

    monkeypatch.setattr(retriever_factory, "get_retriever", lambda: EmptyRetriever())

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc\u5b89\u88c5\u8bf4\u660e",
            content="\u5b89\u88c5\u65f6\u5148\u5bf9\u9f50\u4fa7\u677f\uff0c\u518d\u88c5\u5c42\u677f\u3002",
            source_type="installation_guide",
            fact_type="installation",
            product_scope=["YH06K53", "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc"],
            sku_scope=["YH06K53"],
        )
    finally:
        db.close()

    result = rag_retrieve({
        "should_query_knowledge": True,
        "customer_message": "\u8fd9\u4e2a\u600e\u4e48\u5b89\u88c5",
        "normalized_message": "\u8fd9\u4e2a\u600e\u4e48\u5b89\u88c5",
        "allowed_source_types": ["installation_guide", "product_facts", "faq"],
        "query_fact_type": "installation",
        "slots": {"sku_code": "YH06K53B05S13"},
        "matched_product_name": "\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
        "trace_steps": [],
    })

    assert result["retrieved_chunks"]
    assert result["retrieved_chunks"][0]["product_context_pack"] is True
    assert result["product_context_pack_stats"]["returned_count"] == 1
    assert result["product_first_evidence_pack"]["requested_fact_type"] == "installation"
    assert result["trace_steps"][-1]["product_first_evidence_pack"]["product_scoped_chunks"]


def test_product_context_pack_does_not_recommend_wrong_variant_media(product_context_db):
    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_MEDIA_SCOPE_001",
            product_name="Test scoped product",
            sku_list_json=json.dumps([{"sku_code": "TEST_MEDIA_SCOPE_001B05S01"}], ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        wrong = KBMediaAsset(
            product_id=product.id,
            i_id="TEST_MEDIA_SCOPE_001",
            sku_code="TEST_MEDIA_SCOPE_001B07S01",
            product_name="Test scoped product",
            asset_type="sku_image",
            asset_title="Wrong combo image",
            asset_url="https://example.com/wrong.png",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.99,
        )
        wrong.set_source_raw({
            "answer_scenarios": ["dimensions"],
            "applicable_style": {
                "scope_type": "combo",
                "scope_values": ["combo7"],
                "scope_note": "combo7",
            },
            "auto_send_level": "auto",
        })
        db.add(wrong)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_MEDIA_SCOPE_001B05S01"}, "matched_product_name": "Test scoped product"},
        query="small bedroom, can it fit?",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="space_fit",
    )

    assert pack["recommended_assets"] == []


def test_product_context_pack_space_fit_prefers_dimensions_over_load_capacity(product_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="Demo product size",
            content="Overall size is 100cm wide, 40cm deep, and 90cm high.",
            source_type="product_facts",
            fact_type="dimensions",
            product_scope=["TEST_SPACE_001", "Demo storage rack"],
            sku_scope=["TEST_SPACE_001"],
        )
        _add_chunked_entry(
            db,
            title="Demo product load",
            content="Each shelf can hold about 20kg when weight is evenly distributed.",
            source_type="product_facts",
            fact_type="load_capacity",
            product_scope=["TEST_SPACE_001", "Demo storage rack"],
            sku_scope=["TEST_SPACE_001"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "TEST_SPACE_001B01S01"},
            "matched_product_name": "Demo storage rack",
            "semantic_query": {
                "primary_fact_type": "space_fit",
                "secondary_fact_types": ["load_capacity"],
            },
        },
        query="Can this fit in a small room?",
        allowed_source_types=["product_facts"],
        query_fact_type="space_fit",
    )

    assert pack["facts"]
    assert {item["fact_type"] for item in pack["facts"]} == {"dimensions"}
    assert pack["evidence_pack"]["matched_facts"][0]["semantic_alignment"]["alignment"] == "primary_match"


def test_product_context_pack_placement_scene_drops_material_evidence(product_context_db):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="Demo placement scenes",
            content="Suitable for bedroom, living room, study, and dry storage areas.",
            source_type="product_facts",
            fact_type="placement_scene",
            product_scope=["TEST_SCENE_001", "Demo storage rack"],
            sku_scope=["TEST_SCENE_001"],
        )
        _add_chunked_entry(
            db,
            title="Demo material",
            content="Made with coated steel pipe and PP material.",
            source_type="product_facts",
            fact_type="material",
            product_scope=["TEST_SCENE_001", "Demo storage rack"],
            sku_scope=["TEST_SCENE_001"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "TEST_SCENE_001B01S01"},
            "matched_product_name": "Demo storage rack",
            "semantic_query": {
                "primary_fact_type": "placement_scene",
                "secondary_fact_types": ["material"],
            },
        },
        query="Can it be used in the bedroom?",
        allowed_source_types=["product_facts"],
        query_fact_type="placement_scene",
    )

    assert pack["facts"]
    assert {item["fact_type"] for item in pack["facts"]} == {"placement_scene"}
    assert "bedroom" in pack["facts"][0]["chunk_text"]
    assert pack["evidence_pack"]["matched_facts"][0]["semantic_alignment"]["alignment"] == "primary_match"


def test_product_context_pack_keeps_direct_fact_for_each_authoritative_customer_goal(
    product_context_db,
):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="Demo material",
            content="The reviewed product material is PP.",
            source_type="product_facts",
            fact_type="material",
            product_scope=["TEST_MULTI_GOAL_001", "Demo household product"],
            sku_scope=["TEST_MULTI_GOAL_001"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "TEST_MULTI_GOAL_001B01S01"},
            "matched_product_name": "Demo household product",
            "turn_understanding": {
                "schema_version": "turn-understanding/v2",
                "owner": "turn_understanding_owner",
                "source_stage": "query_fact_type_classifier",
                "goal_understanding_status": "valid",
                "requested_claims": [
                    {
                        "goal_kind": "customer_goal",
                        "claim_type": "material_composition",
                    },
                    {
                        "goal_kind": "customer_goal",
                        "claim_type": "moisture_resistance",
                    },
                ],
            },
        },
        query="What is it made from, and how does it handle moisture?",
        allowed_source_types=["product_facts"],
        query_fact_type="moisture_resistance",
    )

    assert [item["fact_type"] for item in pack["facts"]] == ["material"]
    assert pack["facts"][0]["evidence_allowed_for_direct_answer"] is True
    assert pack["facts"][0]["semantic_alignment"]["query_fact_type"] == "material_composition"
    assert pack["evidence_pack"]["matched_facts"][0]["direct_answer_allowed"] is True


def test_product_context_pack_ignores_untrusted_requested_claim_injection(
    product_context_db,
):
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="Demo material",
            content="The reviewed product material is PP.",
            source_type="product_facts",
            fact_type="material",
            product_scope=["TEST_MULTI_GOAL_002", "Demo household product"],
            sku_scope=["TEST_MULTI_GOAL_002"],
        )
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "slots": {"sku_code": "TEST_MULTI_GOAL_002B01S01"},
            "matched_product_name": "Demo household product",
            "turn_understanding": {
                "schema_version": "turn-understanding/v2",
                "owner": "public_request",
                "source_stage": "query_fact_type_classifier",
                "goal_understanding_status": "valid",
                "requested_claims": [
                    {
                        "goal_kind": "customer_goal",
                        "claim_type": "material_composition",
                    }
                ],
            },
        },
        query="Can it handle moisture?",
        allowed_source_types=["product_facts"],
        query_fact_type="moisture_resistance",
    )

    assert [item["fact_type"] for item in pack["facts"]] == ["material"]
    assert pack["facts"][0]["evidence_allowed_for_direct_answer"] is False


def test_authoritative_requested_fact_types_does_not_promote_unmapped_goal():
    from app.services.product_context_pack_service import (
        authoritative_requested_fact_types,
    )

    requested = authoritative_requested_fact_types(
        {
            "turn_understanding": {
                "schema_version": "turn-understanding/v2",
                "owner": "turn_understanding_owner",
                "source_stage": "query_fact_type_classifier",
                "goal_understanding_status": "valid",
                "requested_claims": [
                    {
                        "goal_kind": "customer_goal",
                        "claim_type_status": "unmapped",
                        "claim_type": "material_composition",
                    }
                ],
            }
        },
        "moisture_resistance",
    )

    assert requested == ["moisture_resistance"]


def test_multi_goal_product_pack_converges_supported_and_unresolved_claims(
    product_context_db,
):
    from app.services.admitted_answer_context_service import (
        AdmittedAnswerContextService,
    )
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        _add_chunked_entry(
            db,
            title="Demo material",
            content="The reviewed product material is PP.",
            source_type="product_facts",
            fact_type="material",
            product_scope=["TEST_MULTI_GOAL_003", "Demo household product"],
            sku_scope=["TEST_MULTI_GOAL_003"],
            metadata={
                "attribute_key": "material",
                "can_direct_answer": True,
                "direct_answer_allowed": True,
                "evidence_role": "direct_product_fact",
                "evidence_uid": "test-evidence-material",
                "fact_review_status": "reviewed",
                "material_provenance": "structured_product_record",
                "product_evidence_protocol": True,
                "reference_only": False,
                "source_id": "test-evidence-material",
                "source_table": "knowledge_entries",
                "subject_scope": "product",
                "value": "PP",
                "verification_status": "reviewed",
            },
        )
    finally:
        db.close()

    requested_claims = [
        {
            "goal_ref": "goal-material",
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material_composition",
            "attribute_key": "material_composition",
        },
        {
            "goal_ref": "goal-safety",
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "safety_claim",
        },
        {
            "goal_ref": "goal-moisture",
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "moisture_resistance",
        },
    ]
    understanding = {
        "schema_version": "turn-understanding/v2",
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "goal_understanding_status": "valid",
        "requested_claims": requested_claims,
    }
    pack = build_product_context_pack(
        {
            "slots": {"i_id": "TEST_MULTI_GOAL_003"},
            "matched_product_name": "Demo household product",
            "turn_understanding": understanding,
        },
        query="What is it made from, and can safety be guaranteed?",
        allowed_source_types=["product_facts"],
        query_fact_type="safety_claim",
    )

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": pack},
        product_identity={
            "i_id": "TEST_MULTI_GOAL_003",
            "product_name": "Demo household product",
        },
        understanding=understanding,
    )

    assert [
        item["fact_type"] for item in admitted["direct_product_facts"]
    ] == ["material"], json.dumps(
        admitted["rejected_evidence"],
        ensure_ascii=False,
        sort_keys=True,
    )
    resolutions = {
        item["claim_type"]: item["status"]
        for item in admitted["claim_resolutions"]
    }
    assert resolutions == {
        "material_composition": "supported",
        "safety_claim": "unresolved",
        "moisture_resistance": "unresolved",
    }


def test_product_first_pack_does_not_promise_install_video_when_no_approved_media(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        product = KBProduct(
            i_id="TEST_NO_VIDEO_001",
            product_name="Test no video product",
            sku_list_json=json.dumps([{"sku_code": "TEST_NO_VIDEO_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {"slots": {"sku_code": "TEST_NO_VIDEO_001B01S01"}, "matched_product_name": "Test no video product"},
        query="installation video please",
        allowed_source_types=["installation_guide", "faq"],
        query_fact_type="installation",
    )

    product_first = pack["product_first_evidence_pack"]
    assert pack["recommended_assets"] == []
    assert product_first["matched_media"] == []
    assert {"evidence_type": "media_asset", "asset_type": "installation_video"} in product_first["missing_required_evidence"]


def test_product_first_pack_keeps_generic_rules_as_fallback_when_structured_fact_exists(product_context_db):
    from app.models.kb_tables import KBGenericServiceRule, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="TEST_GENERIC_BOUNDARY_001",
            product_name="Test generic boundary product",
            sku_list_json=json.dumps([{"sku_code": "TEST_GENERIC_BOUNDARY_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "steel and PP"}, ensure_ascii=False),
            status="published",
        ))
        rule = KBGenericServiceRule(
            rule_key="test_material_generic_boundary",
            title="Generic material boundary",
            intent="product_question",
            fact_type="material",
            scenario="material",
            content="Generic material wording only.",
            reply_template="Generic material wording only.",
            status="active",
            auto_reply_allowed=True,
            source_confidence=0.75,
        )
        rule.set_query_keywords(["material"])
        db.add(rule)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "intent": "product_question",
            "slots": {"sku_code": "TEST_GENERIC_BOUNDARY_001B01S01"},
            "matched_product_name": "Test generic boundary product",
        },
        query="what material is it",
        allowed_source_types=["faq"],
        query_fact_type="material",
    )

    product_first = pack["product_first_evidence_pack"]
    assert pack["facts"]
    assert pack["facts"][0]["source_table"] == "kb_product"
    assert product_first["answerability"] == "direct_answer"
    assert product_first["product_structured_facts"][0]["fact_type"] == "material"
    assert product_first["generic_fallback_rules"]
    assert product_first["evidence_pack_trace"]["generic_rules_role"] == "fallback_only"


def test_product_first_pack_requires_clear_identity_before_using_similar_product_facts(product_context_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = product_context_db()
    try:
        db.add(KBProduct(
            i_id="TEST_SIMILAR_001",
            product_name="Similar product with facts",
            sku_list_json=json.dumps([{"sku_code": "TEST_SIMILAR_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "steel"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {},
        query="what material is this",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="material",
    )

    assert pack["facts"] == []
    assert pack["product_first_evidence_pack"]["answerability"] == "no_product_identity"
    assert pack["product_first_evidence_pack"]["product_structured_facts"] == []


def test_exact_sku_scope_mismatch_cannot_fall_back_to_similar_product_name():
    from app.services.product_context_pack_service import _scope_matches

    identity = {
        "sku": "YH06K07B01S04",
        "sku_family": "YH06K07",
        "i_id": "YH06K07",
        "product_name": "Sweet-house storage rack",
    }

    assert _scope_matches(
        identity,
        product_scope=["YH06K40", "A Sweet-house storage rack"],
        sku_scope=["YH06K40"],
        product_id="YH06K40",
        sku_id="",
        title="A Sweet-house storage rack installation",
    ) is False
    assert _scope_matches(
        identity,
        product_scope=["YH06K07", "Sweet-house storage rack"],
        sku_scope=["YH06K07"],
        product_id="YH06K07",
        sku_id="",
        title="Sweet-house storage rack installation",
    ) is True


def test_catalog_identity_is_reference_only_and_never_becomes_fact(product_context_db, monkeypatch):
    from app.services import product_context_pack_service

    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_reference",
        lambda **_kwargs: {
            "status": "resolved",
            "match_reason": "exact_product_and_sku_code",
            "product": {
                "hub_product_id": "hub-product-1",
                "product_code": "P100",
                "product_name": "内部商品甲",
                "brand": "英禾",
                "category_code": "HOME-1",
                "category_name": "家居用品",
                "status": "active",
                "updated_at": "2026-08-21T10:00:00Z",
            },
            "sku": {
                "hub_sku_id": "hub-sku-1",
                "sku_code": "S100-WHITE",
                "color": "白色",
                "size": "",
                "spec": "标准款",
                "status": "active",
            },
            "reference_only": True,
            "used_for_fact": False,
            "source": "product_data_hub",
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {
            "i_id": "P100",
            "slots": {"sku_code": "S100-WHITE"},
        },
        query="这个商品是什么",
        allowed_source_types=["product_facts"],
        query_fact_type="product_identity",
    )

    assert pack["catalog_reference"]["status"] == "resolved"
    assert pack["catalog_reference"]["product"]["product_name"] == "内部商品甲"
    assert pack["catalog_reference"]["reference_only"] is True
    assert pack["catalog_reference"]["used_for_fact"] is False
    assert pack["facts"] == []
    assert pack["evidence_pack"]["product_structured_facts"] == []
    assert pack["stats"]["catalog_reference_status"] == "resolved"
    assert pack["stats"]["catalog_reference_used_for_fact"] is False


def test_catalog_identity_conflict_does_not_replace_existing_identity(product_context_db, monkeypatch):
    from app.services import product_context_pack_service

    monkeypatch.setattr(
        product_context_pack_service,
        "lookup_product_data_hub_reference",
        lambda **_kwargs: {
            "status": "identity_conflict",
            "reason": "product_sku_parent_mismatch",
            "product": {},
            "sku": {},
            "reference_only": True,
            "used_for_fact": False,
            "source": "product_data_hub",
        },
    )

    pack = product_context_pack_service.build_product_context_pack(
        {"i_id": "P100", "slots": {"sku_code": "S200-GREEN"}},
        query="这个商品是什么",
        allowed_source_types=["product_facts"],
        query_fact_type="product_identity",
    )

    assert pack["identity"]["i_id"] == "P100"
    assert pack["identity"]["sku"] == "S200-GREEN"
    assert pack["catalog_reference"]["status"] == "identity_conflict"
    assert pack["facts"] == []
