from app.agent.nodes.build_response import build_response


def test_build_response_marks_missing_product_card_fact_as_insufficient():
    result = build_response({
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u4e2a\u62c6\u88c5\u7ec6\u8282\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u6e05\u695a\uff0c\u60a8\u7a0d\u7b49\u4e00\u4e0b\u3002",
        "intent": "product_question",
        "answer_mode": "product_fact_answer",
        "query_fact_type": "detachable",
        "product_context_pack": {
            "evidence_pack": {
                "answerability": "missing_product_fact",
                "query_fact_type": "detachable",
                "matched_fields": [],
                "missing_fields": ["detachable"],
                "matched_facts": [],
            }
        },
        "evidence": {"product_facts": []},
    })

    assert result["evidence_sufficient"] is False
    assert result["answer_relevance_passed"] is False
    assert result["direct_answer_supported"] is False
    assert result["missing_required_fact_fields"]


def test_build_response_accepts_direct_product_card_evidence():
    result = build_response({
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5e95\u677f\u548c\u4fa7\u677f\u652f\u6301\u62c6\u88c5\uff0c\u65e5\u5e38\u79fb\u52a8\u6216\u6536\u7eb3\u4f1a\u65b9\u4fbf\u4e00\u4e9b\u3002",
        "intent": "product_question",
        "answer_mode": "product_fact_answer",
        "query_fact_type": "detachable",
        "product_context_pack": {
            "evidence_pack": {
                "answerability": "direct_answer",
                "query_fact_type": "detachable",
                "matched_fields": ["detachable"],
                "missing_fields": [],
                "matched_facts": [
                    {
                        "entry_id": "kbproduct:1",
                        "fact_type": "detachable",
                        "direct_answer_allowed": True,
                        "preview": "\u5e95\u677f\u548c\u4fa7\u677f\u652f\u6301\u62c6\u88c5",
                    }
                ],
            }
        },
        "evidence": {"product_facts": []},
    })

    assert result["evidence_sufficient"] is True
    assert result["answer_relevance_passed"] is True
    assert result["direct_answer_supported"] is True
