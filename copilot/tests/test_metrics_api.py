"""
指标 API 测试 - GET /api/metrics 返回有效 JSON
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def client():
    """Flask test client，使用临时数据文件"""
    from app.main import create_app

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tmpdir, "feedback.jsonl")
        os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tmpdir, "review_queue.jsonl")

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

        os.environ.pop("COPILOT_FEEDBACK_FILE", None)
        os.environ.pop("COPILOT_REVIEW_QUEUE_FILE", None)


class TestMetricsAPI:
    """GET /api/metrics 接口测试"""

    def test_metrics_returns_json(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None

    def test_metrics_has_counters(self, client):
        resp = client.get("/api/metrics")
        data = resp.get_json()
        counters = data.get("counters", {})
        expected_keys = [
            "request_count",
            "jst_call_count",
            "jst_success_count",
            "jst_failure_count",
            "jst_timeout_count",
            "llm_call_count",
            "llm_success_count",
            "llm_failure_count",
            "llm_unconfigured_count",
            "rag_retrieval_count",
            "rag_no_evidence_count",
            "hallucination_guard_block_count",
            "factual_guard_rewrite_count",
            "human_review_count",
            "fallback_count",
        ]
        for key in expected_keys:
            assert key in counters, f"Missing counter: {key}"

    def test_metrics_has_latency(self, client):
        resp = client.get("/api/metrics")
        data = resp.get_json()
        latency = data.get("latency", {})
        assert "avg_ms" in latency
        assert "p50_ms" in latency
        assert "samples" in latency

    def test_metrics_has_uptime(self, client):
        resp = client.get("/api/metrics")
        data = resp.get_json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0
