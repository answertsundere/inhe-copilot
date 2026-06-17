from app.agent.nodes.evidence_builder import evidence_builder


def test_evidence_builder_allows_material_faq_with_no_odor_for_odor_query():
    state = {
        "intent": "product_question",
        "query_fact_type": "odor",
        "knowledge_evidence": [
            {
                "entry_id": "kbqa:1403",
                "title": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f\u7684\u6750\u8d28\u5b89\u5168\u73af\u4fdd\u5417\uff1f",
                "source_type": "faq",
                "chunk_text": "\u91c7\u7528\u98df\u54c1\u7ea7HDPE/PP\u73af\u4fdd\u6750\u6599\uff0c\u65e0\u6bd2\u65e0\u5473\u3002",
                "evidence_fact_type": "material",
                "query_fact_type": "odor",
                "evidence_allowed_for_direct_answer": False,
                "evidence_allowed_for_exact_answer": False,
                "entry_status": "published",
                "reference_only": False,
            }
        ],
    }

    result = evidence_builder(state)
    faq = result["evidence"]["faq_evidence"][0]

    assert faq["evidence_fact_type"] == "odor"
    assert faq["evidence_allowed_for_direct_answer"] is True
    assert faq["evidence_allowed_for_exact_answer"] is True
    assert faq.get("mismatch_reason", "") == ""


def test_evidence_builder_allows_tool_rag_material_faq_with_no_odor_for_odor_query():
    state = {
        "intent": "product_question",
        "query_fact_type": "odor",
        "tool_results": {
            "rag_search_tool": {
                "chunks": [
                    {
                        "entry_id": "kbqa:1403",
                        "chunk_id": "kbqa:1403",
                        "title": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f\u7684\u6750\u8d28\u5b89\u5168\u73af\u4fdd\u5417\uff1f",
                        "source_type": "faq",
                        "chunk_text": "\u91c7\u7528\u98df\u54c1\u7ea7HDPE/PP\u73af\u4fdd\u6750\u6599\uff0c\u65e0\u6bd2\u65e0\u5473\u3002",
                        "evidence_fact_type": "material",
                        "query_fact_type": "odor",
                        "evidence_allowed_for_direct_answer": False,
                        "evidence_allowed_for_exact_answer": False,
                        "entry_status": "published",
                        "metadata": {"auto_reply_allowed": True},
                        "score": 2.0,
                        "rerank_score": 2.0,
                    }
                ]
            }
        },
    }

    result = evidence_builder(state)
    faq = result["evidence"]["faq_evidence"][0]

    assert faq["evidence_fact_type"] == "odor"
    assert faq["evidence_allowed_for_direct_answer"] is True
    assert faq["evidence_allowed_for_exact_answer"] is True
    assert faq.get("mismatch_reason", "") == ""


def test_profile_fact_text_does_not_treat_size_as_detachable_answer():
    from app.agent.nodes.evidence_builder import _profile_fact_text

    fact_text, missing = _profile_fact_text(
        {"specs": {"size": "80*40*90cm"}},
        "detachable",
        "\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417",
    )

    assert fact_text == ""
    assert "\u62c6\u5378/\u62c6\u88c5" in missing


def test_profile_fact_text_does_not_treat_plain_material_as_odor_answer():
    from app.agent.nodes.evidence_builder import _profile_fact_text

    fact_text, missing = _profile_fact_text(
        {"specs": {"material": "\u73af\u4fddPP"}},
        "odor",
        "\u4ea7\u54c1\u6709\u5473\u9053\u5417",
    )

    assert fact_text == ""
    assert "\u6c14\u5473\u8bf4\u660e" in missing


def test_profile_fact_text_allows_material_with_explicit_no_odor_signal():
    from app.agent.nodes.evidence_builder import _profile_fact_text

    fact_text, missing = _profile_fact_text(
        {"specs": {"material": "\u98df\u54c1\u7ea7HDPE/PP\uff0c\u65e0\u6bd2\u65e0\u5473"}},
        "odor",
        "\u4ea7\u54c1\u6709\u5473\u9053\u5417",
    )

    assert "\u65e0\u6bd2\u65e0\u5473" in fact_text
    assert "\u6c14\u5473\u8bf4\u660e" in missing
