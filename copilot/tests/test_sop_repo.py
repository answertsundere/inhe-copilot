"""
SOP 仓库测试
"""

import sys
import os
import yaml
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.repositories.sop_repository import SOPRepository


@pytest.fixture
def repo_with_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        data = {
            "scenarios": [
                {
                    "id": "sop_shipping_001",
                    "intent": "shipping",
                    "scenario": "客户催发货",
                    "risk_level": "medium",
                    "steps": ["安抚客户", "查询订单", "说明时效"],
                    "forbidden_claims": ["今天一定发"],
                    "escalation_triggers": ["投诉"],
                    "suggested_reply_style": "温和安抚",
                },
                {
                    "id": "sop_refund_001",
                    "intent": "refund",
                    "scenario": "客户要求退货",
                    "risk_level": "high",
                    "steps": ["确认商品状态", "引导申请退货", "说明流程"],
                    "forbidden_claims": ["一定退"],
                    "escalation_triggers": ["威胁差评"],
                    "suggested_reply_style": "诚恳处理",
                },
            ],
            "meta": {"count": 2}
        }
        with open(os.path.join(tmpdir, "sop_scenarios.yaml"), "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

        repo = SOPRepository(knowledge_dir=tmpdir)
        repo.load()
        yield repo


@pytest.fixture
def empty_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = SOPRepository(knowledge_dir=tmpdir)
        repo.load()
        yield repo


class TestSOPRepoEmpty:
    def test_count_zero(self, empty_repo):
        assert empty_repo.count() == 0

    def test_search_empty(self, empty_repo):
        assert empty_repo.search("发货") == []


class TestSOPRepoWithData:
    def test_count(self, repo_with_data):
        assert repo_with_data.count() == 2

    def test_get_by_id(self, repo_with_data):
        s = repo_with_data.get_by_id("sop_shipping_001")
        assert s is not None
        assert s["intent"] == "shipping"

    def test_get_by_intent(self, repo_with_data):
        ss = repo_with_data.get_by_intent("refund")
        assert len(ss) == 1
        assert ss[0]["id"] == "sop_refund_001"

    def test_search_by_keyword(self, repo_with_data):
        results = repo_with_data.search("催发货")
        assert len(results) >= 1
        assert any(r["id"] == "sop_shipping_001" for r in results)

    def test_search_with_intent_filter(self, repo_with_data):
        results = repo_with_data.search("退货", intent="refund")
        assert len(results) >= 1
        assert results[0]["intent"] == "refund"

    def test_search_no_match(self, repo_with_data):
        results = repo_with_data.search("不存在的xyz")
        assert results == []
