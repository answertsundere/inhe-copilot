from app.agent.nodes.build_response import build_response


def test_build_response_exposes_selected_rejected_assets_and_quality_result():
    result = build_response({
        "intent": "product_question",
        "answer_mode": "product_fact_answer",
        "query_fact_type": "visual_asset",
        "suggested_reply": "\u4eb2\uff5e\u8fd9\u6b3e\u5546\u54c1\u56fe\u7247\u6211\u4e00\u8d77\u53d1\u60a8\u53c2\u8003\u3002",
        "knowledge_evidence": [{
            "chunk_id": "kbmedia:1:visual_asset",
            "entry_id": "kbmedia:1:visual_asset",
            "source_type": "product_facts",
            "fact_type": "visual_asset",
            "evidence_fact_type": "visual_asset",
            "title": "\u5546\u54c1\u5c55\u793a\u56fe",
            "chunk_text": "\u8fd9\u6b3e\u5546\u54c1\u53ef\u4ee5\u53c2\u8003\u4e0b\u9762\u53d1\u9001\u7684\u5546\u54c1\u56fe\u7247\u3002",
            "gate_status": "allowed",
            "direct_answer_allowed": True,
        }],
        "rejected_evidence": [{
            "chunk_id": "load-1",
            "entry_id": "load-1",
            "source_type": "product_facts",
            "fact_type": "load_capacity",
            "evidence_fact_type": "load_capacity",
            "chunk_text": "\u5355\u5c42\u627f\u91cd15kg\u3002",
            "rejection_reasons": ["strict_mismatch"],
        }],
        "product_context_pack": {
            "recommended_assets": [{
                "asset_id": 1,
                "asset_type": "sku_image",
                "asset_title": "\u5546\u54c1\u5c55\u793a\u56fe",
                "asset_url": "https://example.com/sku.jpg",
                "send_mode": "manual",
            }],
            "evidence_pack": {
                "answerability": "direct_answer",
                "query_fact_type": "visual_asset",
                "matched_fields": ["visual_asset"],
            },
        },
        "trace_steps": [],
    })

    debug = result["evidence_debug"]
    assert debug["selected_evidence"][0]["evidence_fact_type"] == "visual_asset"
    assert debug["rejected_evidence"][0]["evidence_fact_type"] == "load_capacity"
    assert debug["selected_assets"][0]["asset_type"] == "sku_image"
    assert debug["quality_result"]["passed"] is True
