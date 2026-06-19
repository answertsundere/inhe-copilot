from __future__ import annotations

import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PHASE6_RAG_I_ID = "PHASE6_RAG_TRACE_PRODUCT"
PHASE6_RAG_SKU = "PHASE6_RAG_TRACE_SKU"
PHASE6_RAG_PRODUCT = "\u6d4b\u8bd5\u9632\u6f6e\u6536\u7eb3\u67dc"
PHASE6_RAG_MATERIAL = (
    "\u4e3b\u8981\u91c7\u7528\u51b7\u8f67\u94a2\u7ba1\u3001\u73af\u4fddPP\u548c\u65e0\u7eba\u5e03\u7b49\u6750\u8d28\uff1b"
    "\u91d1\u5c5e\u90e8\u5206\u7ecf\u8fc7\u9632\u9508\u55b7\u6d82\u5904\u7406\uff0c\u5177\u5907\u4e00\u5b9a\u9632\u6f6e\u80fd\u529b\u3002"
)


@pytest.fixture()
def phase6_rag_api(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA  # noqa: F401
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    saved_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    os.environ["COPILOT_LLM_API_KEY"] = ""
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "phase6_rag_feedback.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "phase6_rag_review.jsonl")

    _seed_phase6_rag_material(session_factory)

    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    try:
        yield app.test_client()
    finally:
        os.environ["COPILOT_LLM_API_KEY"] = saved_key


def _seed_phase6_rag_material(session_factory) -> None:
    from app.models.kb_tables import KBProduct
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    db = session_factory()
    try:
        product = KBProduct(
            i_id=PHASE6_RAG_I_ID,
            product_name=PHASE6_RAG_PRODUCT,
            sku_list_json=json.dumps([{"sku_code": PHASE6_RAG_SKU}], ensure_ascii=False),
            specs_json=json.dumps({
                "material": "\u73af\u4fddPP/\u51b7\u8f67\u94a2\u7ba1",
                "weight": "2.65",
                "load_capacity": "",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        entry = KnowledgeEntry(
            source_type="product_facts",
            title=f"{PHASE6_RAG_PRODUCT}\u6750\u8d28\u548c\u9632\u6f6e\u8bf4\u660e",
            content=PHASE6_RAG_MATERIAL,
            intent="product_question",
            category="\u6536\u7eb3\u67dc",
            category_l3=PHASE6_RAG_PRODUCT,
            search_keywords="\u6750\u8d28 \u5b89\u5168 \u9632\u6f6e \u53d7\u6f6e \u73af\u4fddPP \u51b7\u8f67\u94a2\u7ba1",
            product_scope_json=json.dumps([PHASE6_RAG_PRODUCT], ensure_ascii=False),
            sku_scope_json=json.dumps([PHASE6_RAG_SKU, PHASE6_RAG_I_ID], ensure_ascii=False),
            platform_scope_json="[]",
            risk_level="low",
            auto_reply_allowed=True,
            human_review_required=True,
            status="published",
            index_status="ready",
            source_confidence=0.95,
            fact_review_status="verified",
            fact_type="material",
            fact_scope="sku",
            business_key="phase6-rag-material",
            product_id=PHASE6_RAG_I_ID,
            sku_id=PHASE6_RAG_SKU,
            source_sheet="phase6_test",
            reviewed_by="phase6_test",
        )
        db.add(entry)
        db.flush()
        db.add(KnowledgeChunk(
            entry_id=entry.id,
            chunk_text=PHASE6_RAG_MATERIAL,
            chunk_index=0,
            source_type="product_facts",
            intent="product_question",
            product_scope_json=json.dumps([PHASE6_RAG_PRODUCT], ensure_ascii=False),
            sku_scope_json=json.dumps([PHASE6_RAG_SKU, PHASE6_RAG_I_ID], ensure_ascii=False),
            platform_scope_json="[]",
            metadata_json=json.dumps({
                "auto_reply_allowed": True,
                "human_review_required": True,
                "fact_type": "material",
                "fact_review_status": "verified",
            }, ensure_ascii=False),
            category="\u6536\u7eb3\u67dc",
            category_l3=PHASE6_RAG_PRODUCT,
            search_keywords="\u6750\u8d28 \u5b89\u5168 \u9632\u6f6e \u53d7\u6f6e \u73af\u4fddPP \u51b7\u8f67\u94a2\u7ba1",
            embedding_status="pending",
            source_confidence=0.95,
            fact_review_status="verified",
            fact_source_type="phase6_test",
        ))
        db.commit()
    finally:
        db.close()


def _phase6_trace(data: dict) -> dict:
    return data.get("answer_trace") or (data.get("evidence_debug") or {}).get("answer_trace") or {}


def test_answer_trace_normalizes_product_card_evidence_answer():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "亲～尺寸是 60*30*90cm。",
        "query_fact_type": "dimensions",
        "evidence_debug": {
            "query_fact_type": "dimensions",
            "answer_composition_trace": {
                "mode": "single_intent",
                "answered_fact_types": ["dimensions"],
                "evidence_answered_fact_types": ["dimensions"],
                "fallback_fact_types": [],
                "needs_followup_fact_types": [],
                "product_card_evidence_used": {
                    "dimensions": [{
                        "entry_id": "card:dimensions",
                        "chunk_id": "card:dimensions",
                        "source_type": "product_facts",
                    }]
                },
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["dimensions"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="尺寸多大？")
    trace = result["evidence_debug"]["answer_trace"]

    assert trace["query_fact_type"] == "dimensions"
    assert trace["required_fact_types"] == ["dimensions"]
    assert trace["evidence_answered_fact_types"] == ["dimensions"]
    assert trace["product_card_evidence_used"]["dimensions"]
    assert trace["final_audit"]["passed"] is True


def test_answer_trace_normalizes_media_answer_assets_and_blocks():
    from app.services.answer_trace_service import attach_answer_trace

    asset = {
        "asset_id": "asset-size",
        "asset_type": "size_image",
        "asset_title": "尺寸图",
        "asset_url": "https://example.com/size.jpg",
        "send_mode": "auto_when_platform_connected",
    }
    response = {
        "suggested_reply": "亲～尺寸图可以发您参考。",
        "recommended_assets": [asset],
        "selected_assets": [asset],
        "reply_blocks": [
            {"type": "text", "content": "亲～尺寸图可以发您参考。"},
            {"type": "image", "asset_id": "asset-size", "asset_type": "size_image", "url": "https://example.com/size.jpg"},
        ],
        "reply_delivery": {"mode": "blocks", "auto_send_ready": True, "reason": ""},
        "evidence_debug": {
            "query_fact_type": "visual_asset",
            "secondary_fact_types": ["dimensions"],
            "answer_composition_trace": {
                "answered_fact_types": ["visual_asset", "dimensions"],
                "evidence_answered_fact_types": ["visual_asset", "dimensions"],
                "fallback_fact_types": [],
                "needs_followup_fact_types": [],
                "media_evidence_used": {
                    "dimensions": [{"asset_id": "asset-size", "asset_type": "size_image"}],
                },
                "asset_evidence_used": {
                    "visual_asset": [{"asset_id": "asset-size", "asset_type": "size_image"}],
                },
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["visual_asset", "dimensions"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="尺寸多大，有没有图？")
    trace = result["evidence_debug"]["answer_trace"]

    assert trace["mode"] == "media_answer"
    assert trace["selected_assets"][0]["asset_type"] == "size_image"
    assert trace["media_evidence_used"]["dimensions"]
    assert trace["asset_evidence_used"]["visual_asset"]
    assert trace["reply_delivery"]["auto_send_ready"] is True
    assert any(block["asset_type"] == "size_image" for block in trace["reply_blocks"])


def test_answer_trace_exists_for_generic_rule_fallback():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "亲～这款商品目前没有可直接发送的尺寸图，我先帮您核对。",
        "generic_service_rule_used": {
            "rule_key": "media_supported_install_size_parts_v1",
            "title": "素材兜底",
            "fact_type": "media_reference",
            "score": 0.8,
        },
        "evidence_debug": {
            "query_fact_type": "dimensions",
            "evidence_grouping": {"coverage": {"required_fact_types": ["dimensions"]}},
            "answer_composition_trace": {
                "answered_fact_types": [],
                "evidence_answered_fact_types": [],
                "fallback_fact_types": ["dimensions"],
                "needs_followup_fact_types": ["dimensions"],
            },
        },
    }

    result = attach_answer_trace(response, customer_message="尺寸多大，有图吗？")
    trace = result["answer_trace"]

    assert trace["mode"] == "generic_rule_fallback"
    assert trace["generic_rule_used"]["rule_key"] == "media_supported_install_size_parts_v1"
    assert trace["fallback_fact_types"] == ["dimensions"]


def test_answer_trace_records_final_audit_rewrite():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "亲～我先帮您核对尺寸。",
        "generation_mode": "final_answer_audit_fallback",
        "final_answer_audit": {
            "passed": False,
            "issues": ["wrong_topic:dimensions->load_capacity"],
            "fallback_used": True,
            "original_reply": "亲～承重很好。",
        },
        "evidence_debug": {
            "query_fact_type": "dimensions",
            "evidence_grouping": {"coverage": {"required_fact_types": ["dimensions"]}},
            "answer_composition_trace": {
                "fallback_fact_types": ["dimensions"],
                "needs_followup_fact_types": ["dimensions"],
            },
        },
    }

    result = attach_answer_trace(response, customer_message="尺寸多大？")
    trace = result["evidence_debug"]["answer_trace"]

    assert trace["mode"] == "final_audit_rewrite"
    assert trace["final_audit"]["passed"] is False
    assert trace["final_audit"]["fallback_used"] is True
    assert trace["rewrite_applied"] is True


def test_answer_trace_records_selected_rag_evidence():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "材质是高密度板，日常使用注意保持干燥。",
        "query_fact_type": "material",
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{
                "entry_id": "fact-1",
                "chunk_id": "chunk-1",
                "fact_type": "material",
                "source_type": "product_facts",
                "title": "材质",
                "preview": "商品材质为高密度板。",
                "selected": True,
            }],
            "answer_composition_trace": {
                "answered_fact_types": [],
                "evidence_answered_fact_types": [],
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["material"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="这个材质安全吗？")
    trace = result["answer_trace"]

    assert trace["mode"] == "evidence_answer"
    assert trace["evidence_answered_fact_types"] == ["material"]
    assert trace["answered_fact_types"] == ["material"]
    assert trace["rag_evidence_used"]["material"][0]["source_type"] == "product_facts"
    assert trace["rag_evidence_used"]["material"][0]["entry_id"] == "fact-1"


def test_answer_trace_keeps_evidence_answer_when_human_review_required():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "材质信息可参考商品事实，检测报告我帮您再核对。",
        "query_fact_type": "material",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{
                "entry_id": "fact-2",
                "chunk_id": "chunk-2",
                "fact_type": "material",
                "source_type": "product_facts",
                "preview": "商品材质为实木颗粒板。",
                "selected": True,
            }],
            "answer_composition_trace": {
                "answered_fact_types": [],
                "evidence_answered_fact_types": [],
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["material"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="材质安全吗，有检测报告吗？")
    trace = result["answer_trace"]

    assert trace["mode"] == "mixed_with_human_review"
    assert trace["evidence_answered_fact_types"] == ["material"]
    assert trace["rag_evidence_used"]["material"][0]["chunk_id"] == "chunk-2"


def test_answer_trace_does_not_use_rejected_evidence():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "我先帮您核对准确材质。",
        "query_fact_type": "material",
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{
                "entry_id": "fact-rejected",
                "chunk_id": "chunk-rejected",
                "fact_type": "material",
                "source_type": "product_facts",
                "preview": "不匹配的材质信息。",
                "selected": False,
            }],
            "rejected_evidence": [{
                "entry_id": "fact-rejected",
                "chunk_id": "chunk-rejected",
                "fact_type": "material",
                "source_type": "product_facts",
                "reason": "wrong_product",
            }],
            "answer_composition_trace": {
                "answered_fact_types": [],
                "evidence_answered_fact_types": [],
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["material"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="这个是什么材质？")
    trace = result["answer_trace"]

    assert trace["rag_evidence_used"] == {}
    assert trace["evidence_answered_fact_types"] == []
    assert trace["mode"] == "mixed"


def test_answer_trace_records_product_context_matched_facts():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "尺寸是 60*30*90cm。",
        "query_fact_type": "dimensions",
        "evidence_debug": {
            "query_fact_type": "dimensions",
            "product_context_pack_summary": {
                "evidence_pack": {
                    "matched_facts": [{
                        "entry_id": "card-dimensions",
                        "chunk_id": "card-dimensions",
                        "fact_type": "dimensions",
                        "source_type": "product_facts",
                        "preview": "尺寸：60*30*90cm",
                    }]
                }
            },
            "answer_composition_trace": {
                "answered_fact_types": [],
                "evidence_answered_fact_types": [],
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["dimensions"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="尺寸多大？")
    trace = result["answer_trace"]

    assert trace["mode"] == "evidence_answer"
    assert trace["evidence_answered_fact_types"] == ["dimensions"]
    assert trace["rag_evidence_used"]["dimensions"][0]["entry_id"] == "card-dimensions"


def test_answer_trace_records_composition_knowledge_evidence_without_media_duplication():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "材质为环保 PP。",
        "query_fact_type": "material",
        "evidence_debug": {
            "query_fact_type": "material",
            "answer_composition_trace": {
                "answered_fact_types": ["material"],
                "evidence_answered_fact_types": ["material"],
                "evidence_used_by_fact_type": {
                    "material": [{
                        "entry_id": "knowledge-1",
                        "chunk_id": "knowledge-chunk-1",
                        "fact_type": "material",
                        "source_type": "product_facts",
                        "preview": "材质为环保 PP。",
                    }],
                    "visual_asset": [{
                        "entry_id": "media-1",
                        "chunk_id": "media-chunk-1",
                        "fact_type": "visual_asset",
                        "source_type": "product_media",
                        "evidence_origin": "product_media",
                        "asset_id": "asset-1",
                    }],
                },
            },
            "evidence_grouping": {"coverage": {"required_fact_types": ["material", "visual_asset"]}},
        },
    }

    result = attach_answer_trace(response, customer_message="材质是什么，有没有图？")
    trace = result["answer_trace"]

    assert trace["rag_evidence_used"]["material"][0]["entry_id"] == "knowledge-1"
    assert "visual_asset" not in trace["rag_evidence_used"]


def test_answer_trace_does_not_infer_query_fact_type_from_selected_evidence():
    from app.services.answer_trace_service import attach_answer_trace

    response = {
        "suggested_reply": "\u6750\u8d28\u4fe1\u606f\u9700\u8981\u7ed3\u5408\u5df2\u786e\u8ba4\u8bc1\u636e\u8bf4\u660e\u3002",
        "requires_human_review": True,
        "evidence_debug": {
            "selected_evidence": [{
                "entry_id": "selected-material",
                "chunk_id": "selected-material-1",
                "fact_type": "material",
                "source_type": "product_facts",
                "text": PHASE6_RAG_MATERIAL,
                "selected": True,
            }],
            "product_context_pack_summary": {
                "evidence_pack": {
                    "matched_facts": [{
                        "entry_id": "matched-material",
                        "chunk_id": "matched-material-1",
                        "fact_type": "material",
                        "source_type": "product_facts",
                        "preview": PHASE6_RAG_MATERIAL,
                    }],
                    "evidence_evaluation": [{
                        "evidence_id": "eval-material",
                        "fact_type": "material",
                        "source_type": "product_facts",
                        "text": PHASE6_RAG_MATERIAL,
                        "selected": True,
                    }],
                }
            },
        },
    }

    result = attach_answer_trace(
        response,
        customer_message="\u8fd9\u4e2a\u6750\u8d28\u5b89\u5168\u5417\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u53d7\u6f6e\uff1f",
    )
    trace = result["answer_trace"]

    assert result.get("query_fact_type", "") == ""
    assert trace["query_fact_type"] == ""
    assert trace["required_fact_types"] == []
    assert trace["rag_evidence_used"] == {}
    assert trace["evidence_answered_fact_types"] == []
    assert trace["trace_contract_broken"] is True
    assert trace["trace_contract_reason"] == "missing_query_fact_type"


def test_real_api_material_rag_trace_keeps_fact_contract_and_no_load_capacity(phase6_rag_api):
    response = phase6_rag_api.post("/ask/api/analyze", json={
        "message": "\u8fd9\u4e2a\u6750\u8d28\u5b89\u5168\u5417\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u53d7\u6f6e\uff1f",
        "sku_code": PHASE6_RAG_SKU,
        "conversation_id": "phase6_trace_material_api_test",
        "product_candidates": [
            {"type": "i_id", "value": PHASE6_RAG_I_ID, "i_id": PHASE6_RAG_I_ID, "product_name": PHASE6_RAG_PRODUCT},
            {"type": "sku_code", "value": PHASE6_RAG_SKU, "sku_code": PHASE6_RAG_SKU, "product_name": PHASE6_RAG_PRODUCT},
        ],
        "copilot_context": {
            "product_name": PHASE6_RAG_PRODUCT,
            "i_id": PHASE6_RAG_I_ID,
            "sku_code": PHASE6_RAG_SKU,
            "product_candidates": [
                {"type": "sku_code", "value": PHASE6_RAG_SKU, "sku_code": PHASE6_RAG_SKU, "product_name": PHASE6_RAG_PRODUCT},
            ],
        },
    })
    assert response.status_code == 200, response.data[:500]
    data = response.get_json()
    trace = _phase6_trace(data)
    debug = data.get("evidence_debug") or {}
    reply = data.get("suggested_reply") or ""

    assert data["query_fact_type"] == "material"
    assert trace["query_fact_type"] == "material"
    assert "material" in trace["required_fact_types"]
    assert trace["rag_evidence_used"]["material"]
    assert "material" in trace["evidence_answered_fact_types"]
    assert trace["mode"] == "mixed_with_human_review"
    assert len(debug.get("selected_evidence") or []) >= 1
    assert "\u627f\u91cd" not in reply
    assert "\u5bb9\u91cf" not in reply
    assert "2.65" not in reply
    for internal_term in ("系统", "知识库", "RAG", "fact_type", "query_fact_type", "evidence_debug"):
        assert internal_term not in reply
    for unsafe in ("\u7edd\u5bf9\u5b89\u5168", "0\u7532\u919b", "\u5b8c\u5168\u65e0\u5bb3", "\u5b9d\u5b9d\u53ef\u4ee5\u76f4\u63a5\u7528"):
        assert unsafe not in reply


@pytest.mark.parametrize(
    ("message", "expected_fact_type"),
    [
        ("\u5c3a\u5bf8\u591a\u5927\uff0c\u6709\u6ca1\u6709\u56fe\uff1f", "visual_asset"),
        ("\u600e\u4e48\u5b89\u88c5\uff0c\u6709\u89c6\u9891\u5417\uff1f", "installation"),
        ("\u6709\u6ca1\u6709\u68c0\u6d4b\u62a5\u544a\uff0c\u5b89\u5168\u5417\uff1f", "certification_report"),
    ],
)
def test_real_api_non_material_queries_are_not_overwritten_by_material_evidence(
    phase6_rag_api,
    message,
    expected_fact_type,
):
    data = _post_phase6_rag_api(
        phase6_rag_api,
        message,
        f"phase6_trace_{expected_fact_type}_api_test",
    )
    trace = _phase6_trace(data)
    reply = data.get("suggested_reply") or ""

    assert data["query_fact_type"] == expected_fact_type
    assert trace["query_fact_type"] == expected_fact_type
    assert expected_fact_type in trace["required_fact_types"]
    assert data["query_fact_type"] != "material"
    assert trace["query_fact_type"] != "material"
    assert trace["required_fact_types"] != ["material"]
    assert "\u6750\u8d28/\u9632\u6f6e" not in reply
    assert "2.65" not in reply


def _post_phase6_rag_api(client, message: str, conversation_id: str) -> dict:
    response = client.post("/ask/api/analyze", json={
        "message": message,
        "sku_code": PHASE6_RAG_SKU,
        "conversation_id": conversation_id,
        "product_candidates": [
            {"type": "i_id", "value": PHASE6_RAG_I_ID, "i_id": PHASE6_RAG_I_ID, "product_name": PHASE6_RAG_PRODUCT},
            {"type": "sku_code", "value": PHASE6_RAG_SKU, "sku_code": PHASE6_RAG_SKU, "product_name": PHASE6_RAG_PRODUCT},
        ],
        "copilot_context": {
            "product_name": PHASE6_RAG_PRODUCT,
            "i_id": PHASE6_RAG_I_ID,
            "sku_code": PHASE6_RAG_SKU,
            "product_candidates": [
                {"type": "sku_code", "value": PHASE6_RAG_SKU, "sku_code": PHASE6_RAG_SKU, "product_name": PHASE6_RAG_PRODUCT},
            ],
        },
    })
    assert response.status_code == 200, response.data[:500]
    return response.get_json()
