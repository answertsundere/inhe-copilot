from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder


def test_social_frustration_reply_uses_customer_facing_language():
    result = gold_csr_reply_builder({
        "response_strategy_plan": {"reply_goal": "social_reply"},
        "customer_concern": "social_frustration",
        "suggested_reply": "",
        "trace_steps": [],
    })
    reply = result["suggested_reply"]

    assert "具体问题" in reply
    assert "核对清楚" in reply
    assert "按事实查" not in reply
    assert "不跟您绕" not in reply
