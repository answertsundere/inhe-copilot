from __future__ import annotations

from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder


def test_product_fact_no_evidence_does_not_fall_back_to_social_reply():
    result = gold_csr_reply_builder({
        "response_strategy_plan": {"reply_goal": "social_reply"},
        "suggested_reply": "我在。您可以直接说要查物流、问商品、处理售后。",
        "answer_mode": "no_evidence_clarification",
        "customer_message": "基础款和升级版差什么",
        "query_fact_type": "variant_compare",
        "intent": "product_question",
        "matched_product_name": "一号喂养柜",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "一号喂养柜",
            "sku_id": "YH88K01B01S26",
            "i_id": "YH88K01",
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]

    assert "一号喂养柜" in reply
    assert "基础款和升级款的区别" in reply
    assert "没有可直接引用的已审核说明" in reply
    assert "查物流" not in reply
    assert result["gold_csr_applied"] is True
