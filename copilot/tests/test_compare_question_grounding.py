from app.agent.nodes.generate_reply import generate_reply


def test_compare_question_does_not_use_unrelated_faq_answer():
    product_name = "\u82f1\u79be\u513f\u7ae5\u4e66\u67b6\u843d\u5730\u7f6e\u7269\u67b6\u53ef\u79fb\u52a8\u4e66\u672c\u6536\u7eb3\u67b6"
    unrelated_content = "\u4e66\u67b6\u6bcf\u5c42\u627f\u91cd\u7ea615-25kg\uff0c\u7ed3\u6784\u7a33\u56fa\uff0c\u91c7\u7528\u52a0\u539a\u677f\u6750\u3002"
    chunk = {
        "chunk_id": "chunk-901",
        "entry_id": 901,
        "title": "\u4e66\u67b6\u6bcf\u5c42\u627f\u91cd\u591a\u5c11\uff1f",
        "source_type": "faq",
        "intent": "product_question",
        "score": 0.95,
        "chunk_text": unrelated_content,
        "confidence": "low",
        "reference_only": False,
        "needs_human_review": False,
        "evidence_allowed_for_exact_answer": False,
    }
    state = {
        "customer_message": "\u57fa\u7840\u6b3e\u548c\u5347\u7ea7\u7248\u5dee\u4ec0\u4e48",
        "normalized_message": "\u57fa\u7840\u6b3e\u548c\u5347\u7ea7\u7248\u5dee\u4ec0\u4e48",
        "intent": "product_question",
        "risk_level": "low",
        "matched_product_name": product_name,
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": product_name,
            "sku_code": "YH04K32B01S26",
            "source": "jst_product_name_query",
        },
        "filtered_evidence": [chunk],
        "knowledge_evidence": [chunk],
        "evidence": {
            "product_facts": [],
            "faq_evidence": [
                {
                    "fact": unrelated_content,
                    "source_type": "faq",
                    "confidence": "low",
                    "reference_only": False,
                }
            ],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "unknowns": [],
            "conflicts": [],
        },
        "trace_steps": [],
    }

    result = generate_reply(state)

    assert result["answer_mode"] == "no_evidence_clarification"
    assert "\u627f\u91cd" not in result["suggested_reply"]
    assert "\u7ed3\u6784\u7a33\u56fa" not in result["suggested_reply"]
    assert "\u52a0\u539a\u677f\u6750" not in result["suggested_reply"]
