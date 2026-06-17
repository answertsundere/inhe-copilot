from app.agent.nodes.reply_relevance_guard import reply_relevance_guard
from app.services.customer_reply_polisher import polish_customer_reply


def test_polisher_rewrites_quality_complaint_internal_handoff_language():
    msg = "这个质量太差了，再不处理我就投诉你们。"
    response = {
        "intent": "complaint",
        "risk_level": "high",
        "suggested_reply": (
            "亲～这个细节我先帮您按当前商品和页面信息一起核对。"
            "如果您方便，也可以把商品页面或实物位置截图发我，我这边会更快帮您判断。"
        ),
        "order_id": "6926666820903533935",
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }

    result = polish_customer_reply(response, customer_message=msg)
    reply = result["suggested_reply"]

    assert "非常抱歉" in reply
    assert "订单信息" in reply
    assert "优先" in reply
    assert "售后" in reply or "主管" in reply
    assert "商品页面" not in reply
    assert "页面信息" not in reply
    assert "当前商品" not in reply
    assert "避免" not in reply
    assert result["evidence_debug"]["answer_relevance_passed"] is True
    assert result["evidence_debug"]["complaint_output_contract"]["passed"] is True
    assert result["customer_reply_polish"]["applied"] is True


def test_polisher_marks_existing_safe_complaint_reply_as_relevant():
    msg = "这个质量太差了，再不处理我就投诉你们。"
    response = {
        "intent": "complaint",
        "risk_level": "high",
        "suggested_reply": (
            "亲～非常抱歉让您有这么不好的体验，您的反馈我已经收到，会优先帮您跟进。\n"
            "我这边已经收到您提供的订单信息，会直接按这笔订单优先跟进处理。\n"
            "如果方便，也麻烦您把问题位置拍照或录个小视频发我，我会一起提交给售后/主管核实处理。\n"
            "这边会尽快给您明确处理方向，不会让您一直等着没有结果。"
        ),
        "order_id": "6926666820903533935",
        "evidence_debug": {
            "query_fact_type": "aftersales_policy",
            "answer_relevance_passed": False,
        },
        "customer_reply_polish": {"applied": True},
    }

    result = polish_customer_reply(response, customer_message=msg)

    assert result["evidence_debug"]["answer_relevance_passed"] is True
    assert result["evidence_debug"]["complaint_output_contract"]["passed"] is True
    assert result["customer_reply_polish"]["applied"] is True


def test_relevance_guard_treats_quality_complaint_reply_as_answered():
    msg = "这个质量太差了，再不处理我就投诉你们。"
    reply = (
        "亲～非常抱歉让您有这么不好的体验，您的反馈我已经收到，会优先帮您跟进。\n"
        "我这边已经收到您提供的订单信息，会直接按这笔订单优先跟进处理。\n"
        "如果方便，也麻烦您把问题位置拍照或录个小视频发我，我会一起提交给售后/主管核实处理。\n"
        "这边会尽快给您明确处理方向，不会让您一直等着没有结果。"
    )

    result = reply_relevance_guard({
        "normalized_message": msg,
        "customer_message": msg,
        "suggested_reply": reply,
        "intent": "complaint",
        "risk_level": "high",
        "order_id": "6926666820903533935",
        "trace_steps": [],
    })

    assert result["reply_relevance_guard"]["passed"] is True
    assert result["suggested_reply"] == reply
