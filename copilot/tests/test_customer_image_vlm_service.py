import base64
import time

from app.services.customer_image_vlm_service import analyze_customer_images
from app.agent.nodes.build_response import build_response
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


def test_customer_image_vlm_uses_hard_budget_without_retries(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request_timeout"] = kwargs["timeout"]
            raise TimeoutError("request timed out")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("app.config.COPILOT_VLM_ENABLED", True)
    monkeypatch.setattr("app.config.COPILOT_VLM_API_BASE", "https://example.invalid/v1")
    monkeypatch.setattr("app.config.COPILOT_VLM_API_KEY", "test-key")
    monkeypatch.setattr("app.config.COPILOT_VLM_MODEL", "test-vlm")
    monkeypatch.setattr("app.config.COPILOT_VLM_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr("app.services.customer_image_vlm_service.OpenAI", FakeOpenAI)

    result = analyze_customer_images([{"base64": "ZmFrZQ==", "kind": "installation_photo"}])

    assert captured["timeout"] == 8
    assert captured["request_timeout"] == 8
    assert captured["max_retries"] == 0
    assert result[0]["fallback_to_text"] is True
    assert result[0]["warnings"] == ["vlm_timeout_fallback"]
    assert "图片细节还需人工确认" in result[0]["reason_for_review"]


def test_build_response_adds_safe_notice_when_image_analysis_degrades():
    result = build_response({
        "suggested_reply": "亲，我先按您说的少配件问题核实。",
        "risk_level": "medium",
        "copilot_context": {
            "image_analysis": [{
                "success": False,
                "fallback_to_text": True,
                "warnings": ["vlm_timeout_fallback"],
            }],
        },
        "trace_steps": [],
    })

    assert "图片细节" in result["suggested_reply"]
    assert "未识别清楚的图片" in result["suggested_reply"]
    assert "人工确认" not in result["suggested_reply"]


def test_customer_image_hard_deadline_does_not_wait_for_stalled_provider(monkeypatch):
    monkeypatch.setattr("app.config.COPILOT_VLM_ENABLED", True)
    monkeypatch.setattr("app.config.COPILOT_VLM_API_BASE", "https://example.invalid/v1")
    monkeypatch.setattr("app.config.COPILOT_VLM_API_KEY", "test-key")
    monkeypatch.setattr("app.config.COPILOT_VLM_MODEL", "test-vlm")
    monkeypatch.setattr("app.services.customer_image_vlm_service.CUSTOMER_IMAGE_REQUEST_BUDGET_SECONDS", 0.02)

    def stalled_call(_image_url, _attachment):
        time.sleep(0.2)
        return {"success": True}

    monkeypatch.setattr(
        "app.services.customer_image_vlm_service._call_customer_image_vlm",
        stalled_call,
    )
    started = time.perf_counter()
    result = analyze_customer_images([{"base64": "ZmFrZQ==", "kind": "damage_photo"}])
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1
    assert result[0]["fallback_to_text"] is True
    assert result[0]["warnings"] == ["vlm_timeout_fallback"]


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
