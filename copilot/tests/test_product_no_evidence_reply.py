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
    assert "麻烦您稍等一下" in reply
    assert "已审核" not in reply
    assert "知识库" not in reply
    assert "系统里" not in reply
    assert "查物流" not in reply
    assert result["gold_csr_applied"] is True
    assert result["requires_human_review"] is True
    assert result["review_reason"] == "商品具体字段需要人工核实"


def test_product_load_capacity_no_evidence_uses_fact_label():
    result = gold_csr_reply_builder({
        "response_strategy_plan": {"reply_goal": "answer_product_fact"},
        "suggested_reply": "亲，我先帮您核对。",
        "answer_mode": "no_evidence_clarification",
        "customer_message": "可以放很多绘本和玩具吗？会不会压弯？",
        "query_fact_type": "load_capacity",
        "intent": "product_question",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "九号防夹滑门收纳柜",
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "九号防夹滑门收纳柜" in reply
    assert "承重" in reply
    assert "的您问的这个点" not in reply
