"""
知识质量 API 测试
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask

from app.api.knowledge_routes import knowledge_bp
from app.services.data_quality_service import DataQualityService


@pytest.fixture
def app():
    app = Flask(__name__)
    with tempfile.TemporaryDirectory() as tmpdir:
        cards = [
            {"i_id": "K001", "product_name": "测试桌", "completeness_score": 80,
             "agent_usable_level": "L3", "review_status": "高可用待确认",
             "missing_fields": [], "data_quality_warnings": [],
             "sku_summary": {"sku_count": 1}},
        ]
        with open(os.path.join(tmpdir, "product_cards.json"), "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False)

        svc = DataQualityService(data_dir=tmpdir)
        svc.load()
        app.config["data_quality_service"] = svc
        app.register_blueprint(knowledge_bp)
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


class TestKnowledgeAPI:
    def test_quality_summary(self, client):
        resp = client.get("/api/knowledge/quality")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["product_count"] == 1
        assert data["sku_count"] == 1

    def test_missing_info_empty(self, client):
        resp = client.get("/api/knowledge/missing-info")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["records"] == []
        assert data["count"] == 0

    def test_product_quality_found(self, client):
        resp = client.get("/api/knowledge/products/K001/quality")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["product_name"] == "测试桌"
        assert data["agent_usable_level"] == "L3"

    def test_product_quality_not_found(self, client):
        resp = client.get("/api/knowledge/products/NOEXIST/quality")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["review_status"] == "未找到"
