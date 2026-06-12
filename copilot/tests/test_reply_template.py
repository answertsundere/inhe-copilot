"""
话术模板仓库测试
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.repositories.reply_template_repository import ReplyTemplateRepository


@pytest.fixture
def repo_with_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        data = {
            "templates": [
                {
                    "id": "tpl_001",
                    "intent": "shipping",
                    "scenario": "催发货",
                    "risk_level": "medium",
                    "template": "亲，我们会尽快帮您安排发货哦",
                    "tags": ["售前"],
                },
                {
                    "id": "tpl_002",
                    "intent": "refund",
                    "scenario": "退货退款",
                    "risk_level": "high",
                    "template": "非常抱歉，我们会为您处理退货",
                    "tags": ["售后"],
                },
                {
                    "id": "tpl_003",
                    "intent": "product_consult",
                    "scenario": "材质咨询",
                    "risk_level": "low",
                    "template": "这款是实木材质哦",
                    "tags": ["售前"],
                },
            ],
            "meta": {"count": 3}
        }
        with open(os.path.join(tmpdir, "reply_templates.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        repo = ReplyTemplateRepository(knowledge_dir=tmpdir)
        repo.load()
        yield repo


@pytest.fixture
def empty_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = ReplyTemplateRepository(knowledge_dir=tmpdir)
        repo.load()
        yield repo


class TestReplyTemplateRepoEmpty:
    def test_count_zero(self, empty_repo):
        assert empty_repo.count() == 0

    def test_search_empty(self, empty_repo):
        assert empty_repo.search("发货") == []


class TestReplyTemplateRepoWithData:
    def test_count(self, repo_with_data):
        assert repo_with_data.count() == 3

    def test_get_by_id(self, repo_with_data):
        t = repo_with_data.get_by_id("tpl_001")
        assert t is not None
        assert t["intent"] == "shipping"

    def test_get_by_intent(self, repo_with_data):
        ts = repo_with_data.get_by_intent("refund")
        assert len(ts) == 1
        assert ts[0]["id"] == "tpl_002"

    def test_search_by_keyword(self, repo_with_data):
        results = repo_with_data.search("发货")
        assert len(results) >= 1
        assert any(r["id"] == "tpl_001" for r in results)

    def test_search_with_intent_filter(self, repo_with_data):
        results = repo_with_data.search("材质", intent="product_consult")
        assert len(results) >= 1
        assert results[0]["intent"] == "product_consult"

    def test_search_with_risk_filter(self, repo_with_data):
        results = repo_with_data.search("", risk_level="high")
        assert len(results) == 1
        assert results[0]["risk_level"] == "high"

    def test_search_no_match(self, repo_with_data):
        results = repo_with_data.search("不存在的xyz")
        assert results == []
