from __future__ import annotations


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
