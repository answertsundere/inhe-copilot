from __future__ import annotations

from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder


def test_clarification_uses_known_sidecar_product_instead_of_asking_again():
    product = "ID 1046558780232 英禾喂养多功能收纳柜玩具柜"
    result = gold_csr_reply_builder({
        "response_strategy_plan": {"reply_goal": "clarify_product_identity"},
        "suggested_reply": "",
        "answer_mode": "no_evidence_clarification",
        "matched_product_name": product,
        "copilot_context": {
            "product_name": product,
            "order_candidates": [{"value": "5116887975001001001"}],
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "对上当前信息" in reply
    assert product in reply
    assert "发一下商品链接" not in reply
    assert "发一下" not in reply
    assert "继续按当前商品和订单信息核对" in reply


def test_clarification_uses_top_level_product_candidate_context():
    product = "英禾柜子固定器儿童家具免打孔防倾倒神器衣柜书架鞋柜连接器"
    result = gold_csr_reply_builder({
        "response_strategy_plan": {"reply_goal": "clarify_product_identity"},
        "suggested_reply": "",
        "answer_mode": "no_evidence_clarification",
        "matched_product_name": product,
        "product_candidates": [{"value": product, "type": "product_candidate", "verified": True}],
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": product,
            "i_id": "YH-TEST",
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "对上当前信息" in reply
    assert product in reply
    assert "发一下商品链接" not in reply
    assert "SKU 或订单信息" not in reply
