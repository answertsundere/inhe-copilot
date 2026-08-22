from __future__ import annotations

import os
import sys
import re

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestCopilotPanelPage:
    def test_copilot_panel_opens_shared_desktop_page(self, client):
        resp = client.get("/copilot-panel")

        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "INHE" in html
        assert 'id="analyzeBtn"' in html
        assert 'id="reloadBtn"' in html
        assert "pollLatest" in html
        assert "/api/sidecar/latest" in html
        assert "capture_qianniu_once" in html
        assert "get_sidecar_latest" in html
        assert "最近会话上下文" in html
        assert 'id="histList"' in html
        assert "latestConversationHistory" in html

    def test_compact_mode_still_supported(self, client):
        resp = client.get("/copilot-panel?mode=compact")

        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        assert "mode" in html
        assert "compact" in html

    def test_panel_explicitly_does_not_auto_send(self, client):
        resp = client.get("/copilot-panel")

        html = resp.data.decode("utf-8")
        assert "不会自动发送到千牛" in html
        assert "复制回复" in html
        assert "采纳" in html
        assert "拒绝" in html

    def test_panel_script_is_parseable(self, client):
        resp = client.get("/copilot-panel")
        html = resp.data.decode("utf-8")
        match = re.search(r"<script>([\s\S]*?)</script>", html)
        assert match is not None
        script = match.group(1)
        assert "conversation_history:latestConversationHistory" in script
        assert "setConversationHistory(data.latest_messages" in script

    def test_panel_uses_sendable_contract_for_final_reply(self, client):
        resp = client.get("/copilot-panel")
        html = resp.data.decode("utf-8")

        assert 'finalReply").value = data.suggested_reply' not in html
        assert "sendable_reply" in html
        assert "can_send" in html
        assert "block_reasons" in html
        assert 'data.can_send ? (data.sendable_reply || "") : ""' in html
        assert 'var text = $("finalReply").value;' in html

    def test_real_test_panel_is_owned_by_vue_supervisor_workbench(self, client):
        resp = client.get("/real-test")
        html = resp.data.decode("utf-8")

        assert resp.status_code == 200
        assert '<div id="app"></div>' in html
        assert "sendableTextFromLastResponse" not in html
        assert "premium_manual_cases" not in html

    def test_real_test_panel_distinguishes_completed_live_lookup_from_formal_evidence(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        api_source = open(
            os.path.join(project_root, "frontend", "src", "api", "supervisorAssist.ts"),
            encoding="utf-8",
        ).read()
        page_source = open(
            os.path.join(
                project_root,
                "frontend",
                "src",
                "views",
                "SupervisorAssistWorkbenchPage.vue",
            ),
            encoding="utf-8",
        ).read()

        assert "serviceActions: ServiceActionSummary[]" in api_source
        assert "inform_lookup_completed_no_record" in api_source
        assert "订单查询已完成：暂无可见出库或物流记录" in api_source
        assert "shopPlatform" in api_source
        assert "shop_platform" in api_source
        assert "inform_sales_outbound_record_not_visible" in api_source
        assert "当前数据源仅能读取销售出库记录" in api_source
        assert "platform: String(item?.platform || item?.shop_platform" in page_source
        assert "turn.observation.serviceActions" in page_source
        assert "实时查询状态" in page_source
        assert "本轮未选中正式证据" in page_source


class TestCopilotContextAPI:
    def test_missing_message_returns_400(self, client):
        resp = client.post("/api/copilot/context", json={"source": "manual"})

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "missing_customer_message"

    def test_analyze_with_message_returns_required_fields(self, client):
        resp = client.post(
            "/api/copilot/context",
            json={"source": "copilot_panel_manual", "customer_message": "你好"},
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "suggested_reply" in data
        assert "intent" in data
        assert "risk_level" in data
        assert "evidence_debug" in data
        assert "trace_steps" in data
        assert data["context_echo"]["customer_message"] == "你好"

    def test_context_accepts_conversation_history(self, client):
        resp = client.post(
            "/api/copilot/context",
            json={
                "source": "sidecar_mixed",
                "customer_message": "我没找到，怎么让他自动感应",
                "conversation_history": [
                    {"role": "customer", "text": "这个感应灯"},
                    {"role": "customer", "text": "为什么只能手动摁呢"},
                    {"role": "customer", "text": "我没找到，怎么让他自动感应"},
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        history = data["context_echo"]["conversation_history"]
        assert len(history) == 2
        assert data["evidence_debug"]["copilot_context"]["conversation_history"][0]["content"] == "这个感应灯"


class TestCopilotFeedbackAPI:
    def test_feedback_accepts_accepted(self, client):
        resp = client.post(
            "/api/copilot/feedback",
            json={
                "action": "accepted",
                "customer_message": "你好",
                "suggested_reply": "您好",
                "sendable_reply": "您好",
                "can_send": True,
                "final_reply": "您好",
                "source": "copilot_panel",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["record"]["action"] == "accepted"

    def test_feedback_rejects_accepted_when_not_sendable(self, client):
        resp = client.post(
            "/api/copilot/feedback",
            json={
                "action": "accepted",
                "customer_message": "你好",
                "suggested_reply": "您好",
                "sendable_reply": "",
                "can_send": False,
                "final_reply": "",
                "source": "copilot_panel",
            },
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "sendable_reply" in data["error"]

    def test_feedback_accepts_edited(self, client):
        resp = client.post(
            "/api/copilot/feedback",
            json={
                "action": "edited",
                "customer_message": "你好",
                "suggested_reply": "您好",
                "final_reply": "您好，请问有什么可以帮您？",
                "source": "copilot_panel",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["record"]["action"] == "edited"
        assert data["record"]["final_reply"] == "您好，请问有什么可以帮您？"

    def test_rejected_requires_reason(self, client):
        resp = client.post(
            "/api/copilot/feedback",
            json={
                "action": "rejected",
                "customer_message": "你好",
                "suggested_reply": "您好",
            },
        )

        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "reject_reason is required when action=rejected"

    def test_feedback_accepts_rejected_with_reason(self, client):
        resp = client.post(
            "/api/copilot/feedback",
            json={
                "action": "rejected",
                "customer_message": "你好",
                "suggested_reply": "您好",
                "reject_reason": "事实错误",
                "source": "copilot_panel",
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["record"]["action"] == "rejected"
        assert data["record"]["reject_reason"] == "事实错误"

    def test_feedback_accepts_escalated(self, client):
        resp = client.post(
            "/api/copilot/feedback",
            json={
                "action": "escalated",
                "customer_message": "我要投诉",
                "suggested_reply": "我帮您转人工处理",
                "final_reply": "我帮您转人工处理",
                "source": "copilot_panel",
                "need_human_review": True,
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["record"]["action"] == "escalated"
