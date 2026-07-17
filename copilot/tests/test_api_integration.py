"""
API 集成测试 - Flask test_client
"""

import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def client():
    """Flask test client，使用临时数据文件"""
    from app.main import create_app

    # 用临时文件隔离运行时数据
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tmpdir, "feedback.jsonl")
        os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tmpdir, "review_queue.jsonl")

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

        # 清理环境变量
        os.environ.pop("COPILOT_FEEDBACK_FILE", None)
        os.environ.pop("COPILOT_REVIEW_QUEUE_FILE", None)


class TestAnalyzeAPI:
    """分析接口测试"""

    def test_high_risk_requires_human_review(self, client):
        """高风险消息 requires_human_review=true 并返回 review_id"""
        resp = client.post("/api/analyze", json={
            "message": "我要投诉你们，不给解决就打12315",
            "order_id": "",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["requires_human_review"] is True
        assert data["risk_level"] == "high"
        assert "review_id" in data
        assert len(data.get("review_id", "")) > 0

    def test_context_used_no_privacy(self, client):
        """context_used 不包含隐私字段"""
        resp = client.post("/api/analyze", json={
            "message": "我的订单什么时候发货",
            "order_id": "O2024001",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        ctx = data.get("context_used", {})
        # 不应包含隐私字段
        assert "receiver_name" not in str(ctx)
        assert "receiver_address" not in str(ctx)
        assert "buyer_id" not in str(ctx)
        # 应包含摘要字段
        assert "has_order" in ctx or "product_knowledge_count" in ctx

    def test_no_llm_key_still_has_reply(self, client):
        """无 LLM Key 时使用规则引擎降级，仍返回非空 suggested_reply"""
        import app.config as cfg
        orig_key = cfg.LLM_API_KEY
        cfg.LLM_API_KEY = ""
        try:
            resp = client.post("/api/analyze", json={
                "message": "请问这款书桌的尺寸",
                "order_id": "",
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["suggested_reply"] and len(data["suggested_reply"]) > 10
            # 零配置降级模式下不再返回 error
            assert not data.get("error")
            # 应包含规则引擎生成的新字段
            assert "skill_route" in data
            assert data.get("intent") in ("product_consult", "product_question", "general")
        finally:
            cfg.LLM_API_KEY = orig_key

    def test_product_knowledge_in_response(self, client):
        """/api/analyze 返回 product_knowledge_count"""
        resp = client.post("/api/analyze", json={
            "message": "北欧风书架有货吗",
            "order_id": "",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        ctx = data.get("context_used", {})
        assert "product_knowledge_count" in ctx


class TestReviewAPI:
    """复核队列接口测试"""

    def test_list_reviews(self, client):
        """GET /api/reviews"""
        resp = client.get("/api/reviews?status=pending&limit=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "records" in data

    def test_review_decision_flow(self, client):
        """完整复核决策流程"""
        # 1. 产生一条高风险分析
        resp = client.post("/api/analyze", json={
            "message": "我要找媒体曝光你们",
            "order_id": "O999",
        })
        data = resp.get_json()
        review_id = data.get("review_id")
        assert review_id

        # 2. 查询 pending 列表
        resp = client.get("/api/reviews?status=pending")
        reviews = resp.get_json()
        assert any(r["id"] == review_id for r in reviews["records"])

        # 3. 查询单条
        resp = client.get(f"/api/reviews/{review_id}")
        detail = resp.get_json()
        assert detail["id"] == review_id

        # 4. 提交 approved 决策
        resp = client.post(f"/api/reviews/{review_id}/decision", json={
            "status": "approved",
            "reviewed_by": "客服A",
            "review_note": "已处理",
        })
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["ok"] is True
        assert result["record"]["status"] == "approved"

        # 5. edited 缺 final_reply 应 400
        resp2 = client.post("/api/reviews/{review_id}/decision", json={
            "status": "edited",
            "reviewed_by": "客服B",
        })
        # 这里的 review_id 已被 approved，但 edited 缺 final_reply 应返回 400
        # 注意：上一个测试已经 approved 了这条记录，所以这里用一个新的 review_id

    def test_edited_requires_final_reply(self, client):
        """edited 必须提供 final_reply"""
        # 产生新记录
        resp = client.post("/api/analyze", json={
            "message": "我要起诉你们",
            "order_id": "O888",
        })
        review_id = resp.get_json()["review_id"]

        resp = client.post(f"/api/reviews/{review_id}/decision", json={
            "status": "edited",
            "reviewed_by": "客服B",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert "final_reply" in data["error"]

    def test_decide_nonexistent(self, client):
        """id 不存在返回 404"""
        resp = client.post("/api/reviews/fake-id/decision", json={
            "status": "approved",
        })
        assert resp.status_code == 404

    def test_invalid_status(self, client):
        """非法 status 返回 400"""
        resp = client.post("/api/analyze", json={
            "message": "严重质量问题",
            "order_id": "O777",
        })
        review_id = resp.get_json()["review_id"]

        resp = client.post(f"/api/reviews/{review_id}/decision", json={
            "status": "bad_status",
        })
        assert resp.status_code == 400


class TestFeedbackAPI:
    def test_feedback_rejects_accepted_without_sendable_contract(self, client):
        resp = client.post("/api/feedback", json={
            "action": "accepted",
            "customer_message": "hello",
            "suggested_reply": "draft reply",
            "can_send": False,
            "sendable_reply": "",
            "final_reply": "",
        })

        assert resp.status_code == 400
        data = resp.get_json()
        assert "sendable_reply" in data["error"]

    def test_feedback_accepts_sendable_contract(self, client):
        resp = client.post("/api/feedback", json={
            "action": "accepted",
            "customer_message": "hello",
            "suggested_reply": "draft reply",
            "can_send": True,
            "sendable_reply": "sendable reply",
            "final_reply": "sendable reply",
        })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["record"]["action"] == "accepted"


class TestFeedbackStatsAPI:
    """反馈统计接口"""

    def test_feedback_stats(self, client):
        """GET /api/feedback/stats"""
        resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total" in data
        assert "acceptance_rate" in data
        assert "escalation_rate" in data
        assert "edit_rate" in data

    def test_feedback_stats_after_review(self, client):
        """复核决策后反馈统计正确"""
        resp = client.post("/api/analyze", json={
            "message": "我要曝光你们",
            "order_id": "O666",
        })
        review_id = resp.get_json()["review_id"]

        client.post(f"/api/reviews/{review_id}/decision", json={
            "status": "approved",
            "reviewed_by": "客服C",
        })

        resp = client.get("/api/feedback/stats")
        data = resp.get_json()
        assert data["total"] >= 1
        assert data["review_source_count"] >= 1


class TestHealthAPI:
    """健康检查接口"""

    def test_health_does_not_expose_review_queue_counters(self, client):
        """Public health intentionally avoids operational counters."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "data" not in data
