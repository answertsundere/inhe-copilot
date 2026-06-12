"""
健康检查 API 测试 - GET /api/health 返回增强字段
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


class TestHealthAPI:
    """GET /api/health 增强字段测试"""

    def test_health_status_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"

    def test_health_has_version(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "version" in data
        assert data["version"] == "copilot-v2"

    def test_health_has_jst_configured(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "jst_configured" in data
        assert isinstance(data["jst_configured"], bool)

    def test_health_has_embedding_enabled(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "embedding_enabled" in data
        assert isinstance(data["embedding_enabled"], bool)

    def test_health_has_boot_time(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "boot_time" in data
        assert isinstance(data["boot_time"], float)

    def test_health_has_db_status(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "db_status" in data

    def test_health_has_knowledge_db_status(self, client):
        resp = client.get("/api/health")
        data = resp.get_json()
        assert "knowledge_db_status" in data

    def test_health_no_key_exposure(self, client):
        """健康检查不暴露密钥值"""
        resp = client.get("/api/health")
        text = resp.get_data(as_text=True)
        # 不应包含实际密钥值（敏感词模式检测）
        forbidden_patterns = [
            "APP_KEY",
            "APP_SECRET",
            "ACCESS_TOKEN",
            "API_KEY",
            "CLIENT_SECRET",
        ]
        for pattern in forbidden_patterns:
            # 允许字段名 "jst_configured"，但不应出现实际值
            # 检查 JSON 中没有包含这些字符串作为值（非布尔值）
            assert f'"{pattern}"' not in text or pattern in (
                "jst_configured",  # 布尔字段名，不是值
            )
        # 确保返回的 JSON 结构中不包含 secret/key 的实际值
        data = resp.get_json()
        text_lower = resp.get_data(as_text=True).lower()
        # 不应包含看起来像密钥的字符串
        assert "sk-" not in text_lower
        assert "Bearer " not in text_lower
