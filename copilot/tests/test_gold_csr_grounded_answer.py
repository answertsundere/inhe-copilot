from __future__ import annotations

from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder


def test_gold_csr_does_not_overwrite_grounded_faq_answer():
    result = gold_csr_reply_builder({
        "response_strategy_plan": {"reply_goal": "clarify_product_identity"},
        "suggested_reply": "grounded material answer",
        "answer_mode": "exact_faq_answer",
        "used_knowledge_entry_ids": ["kbqa:344"],
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "product",
            "sku_id": "YH06K53B05S13",
        },
        "trace_steps": [],
    })

    assert result["suggested_reply"] == "grounded material answer"
    assert result["answer_mode"] == "exact_faq_answer"
    assert result["gold_csr_applied"] is False
