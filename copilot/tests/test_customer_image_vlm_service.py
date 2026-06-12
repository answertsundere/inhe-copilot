import base64

from app.services.customer_image_vlm_service import analyze_customer_images
from app.agent.nodes.generate_reply import generate_reply


def test_customer_image_vlm_disabled_returns_metadata_result(monkeypatch):
    monkeypatch.setattr("app.config.COPILOT_VLM_ENABLED", False)
    png_b64 = base64.b64encode(b"fake").decode("ascii")

    result = analyze_customer_images([{
        "base64": png_b64,
        "kind": "damage_photo",
        "description": "桌面边角开裂",
    }])

    assert result[0]["success"] is False
    assert "vlm_not_configured" in result[0]["warnings"]
    assert result[0]["requires_human_review"] is True
    assert result[0]["summary"] == "桌面边角开裂"


def test_image_reply_uses_vlm_damage_issue_type():
    result = generate_reply({
        "normalized_message": "图片发你了",
        "customer_message": "图片发你了",
        "intent": "image_attachment",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "copilot_context": {
            "image_analysis": [{
                "success": True,
                "image_type": "damage_photo",
                "issue_type": "damage",
                "summary": "图片显示桌面边角疑似开裂",
                "confidence": 0.86,
            }],
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "破损位置" in reply
    assert "外包装" in reply
    assert result["requires_human_review"] is True


def test_image_reply_uses_vlm_promotion_issue_type():
    result = generate_reply({
        "normalized_message": "截图发你了",
        "customer_message": "截图发你了",
        "intent": "image_attachment",
        "answer_mode": "aftersales_policy",
        "risk_level": "low",
        "copilot_context": {
            "image_analysis": [{
                "success": True,
                "image_type": "promotion_screenshot",
                "issue_type": "promotion",
                "summary": "图片显示活动页面优惠券",
                "confidence": 0.9,
            }],
        },
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "页面规则" in reply
    assert "订单结算" in reply
