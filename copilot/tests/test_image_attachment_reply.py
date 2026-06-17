from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.router_validation import router_validation
from app.agent.nodes.response_strategy_router import response_strategy_router


def test_image_attachment_detected_from_attachment_metadata():
    result = detect_intent({
        "normalized_message": "图片发你了",
        "image_attachments": [{"kind": "customer_image", "description": "客户发来照片"}],
        "trace_steps": [],
    })

    assert result["intent"] == "image_attachment"
    assert result["skill"] == "image_attachment"


def test_image_attachment_with_text_product_question_uses_product_intent():
    result = detect_intent({
        "normalized_message": "[\u56fe\u72471]\n\u8fd9\u662f\u53ef\u62c6\u5378\u7684\u5417",
        "image_attachments": [{"kind": "product_photo", "description": "\u5ba2\u6237\u53d1\u6765\u5546\u54c1\u56fe"}],
        "trace_steps": [],
    })

    assert result["intent"] != "image_attachment"


def test_image_attachment_does_not_override_complaint():
    result = detect_intent({
        "normalized_message": "图片发你了，再不处理我就投诉平台",
        "image_attachments": [{"kind": "damage_photo"}],
        "trace_steps": [],
    })

    assert result["intent"] == "complaint"


def test_image_attachment_not_downgraded_by_validation_you_text():
    result = router_validation({
        "normalized_message": "收到的桌子裂了，图片发你了",
        "intent": "image_attachment",
        "router_decision": {"intent": "image_attachment", "need_tool": False, "tool_name": "none"},
        "router_source": "rule_fallback",
        "router_reason": "image attachment",
        "selected_tool": "none",
        "slots": {},
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["intent"] == "image_attachment"


def test_image_attachment_strategy_is_policy_only():
    result = response_strategy_router({
        "intent": "image_attachment",
        "risk_level": "low",
        "slots": {},
        "trace_steps": [],
    })

    assert result["response_strategy"] == "clarification"
    assert result["answer_mode"] == "no_evidence_clarification"
    assert result["should_query_facts"] is False
    assert result["should_query_knowledge"] is False


def test_damage_image_reply_requests_order_and_manual_review():
    result = generate_reply({
        "normalized_message": "收到的桌子裂了，图片发你了",
        "customer_message": "收到的桌子裂了，图片发你了",
        "intent": "image_attachment",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "image_attachments": [{"kind": "damage_photo", "description": "桌面边角开裂"}],
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "订单号" in reply
    assert "破损位置" in reply
    assert "人工" in reply
    assert result["requires_human_review"] is True


def test_promotion_screenshot_reply_checks_page_and_order():
    result = generate_reply({
        "normalized_message": "这个优惠怎么没有？截图发你了",
        "customer_message": "这个优惠怎么没有？截图发你了",
        "intent": "image_attachment",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "image_attachments": [{"kind": "promotion_screenshot", "description": "活动页截图显示优惠券"}],
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "页面规则" in reply
    assert "订单结算" in reply
    assert "截图" in reply


def test_missing_parts_image_reply_sounds_like_customer_service():
    result = generate_reply({
        "normalized_message": "我的滑滑梯 零件都掉了有没有补",
        "customer_message": "我的滑滑梯 零件都掉了有没有补",
        "intent": "image_attachment",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "image_attachments": [{"kind": "missing_parts", "description": "客户发来滑梯零件掉落照片"}],
        "copilot_context": {
            "image_analysis": [{
                "image_type": "missing_parts",
                "issue_type": "missing_parts",
                "summary": "滑梯配件掉落或缺失",
            }]
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "能不能补配件" in reply
    assert "图片我已经收到了" in reply
    assert "订单号" in reply
    assert "处理方案" in reply
    assert "核对材料" not in reply
    assert "仓库发货记录" not in reply
    assert "平铺" not in reply
