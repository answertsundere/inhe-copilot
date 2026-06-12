"""
质检 API 测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask

from app.api.quality_routes import quality_bp
from app.services.quality_check_service import QualityCheckService
from app.repositories.file_policy_repository import FilePolicyRepository


@pytest.fixture
def app():
    app = Flask(__name__)
    policy_repo = FilePolicyRepository()
    policy_repo.load()
    svc = QualityCheckService(policy_repo=policy_repo)
    app.config["quality_check_service"] = svc
    app.register_blueprint(quality_bp)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


class TestQualityAPI:
    def test_check_reply_valid(self, client):
        resp = client.post("/api/quality/check-reply", json={
            "customer_message": "什么时候发货",
            "reply": "您好，我帮您查询一下物流情况",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] >= 90
        assert data["risk_level"] == "low"

    def test_check_reply_forbidden(self, client):
        resp = client.post("/api/quality/check-reply", json={
            "customer_message": "什么时候发货",
            "reply": "放心，今天一定发给您",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["score"] < 100
        assert data["requires_human_review"] is True

    def test_check_reply_missing_reply(self, client):
        resp = client.post("/api/quality/check-reply", json={
            "customer_message": "hello",
        })
        assert resp.status_code == 400
