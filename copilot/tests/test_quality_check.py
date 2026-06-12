"""
QualityCheckService 测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.services.quality_check_service import QualityCheckService
from app.repositories.file_policy_repository import FilePolicyRepository


@pytest.fixture
def check_service():
    policy_repo = FilePolicyRepository()
    policy_repo.load()
    return QualityCheckService(policy_repo=policy_repo)


class TestQualityCheckForbidden:
    def test_detect_forbidden_claim(self, check_service):
        r = check_service.check(
            customer_message="什么时候发货",
            reply="放心，今天一定发给您",
        )
        assert r["score"] < 100
        assert any(v["type"] == "forbidden_claim" for v in r["violations"])
        assert r["requires_human_review"] is True

    def test_safe_reply(self, check_service):
        r = check_service.check(
            customer_message="什么时候发货",
            reply="您好，我们会尽快帮您安排发货，我帮您查询一下具体情况",
        )
        assert r["score"] >= 90
        assert r["risk_level"] == "low"
        assert r["requires_human_review"] is False


class TestQualityCheckRefundPromise:
    def test_refund_promise(self, check_service):
        r = check_service.check(
            customer_message="我要退货",
            reply="好的，一定全额退给您",
        )
        assert any(v["type"] == "refund_promise" for v in r["violations"])
        assert r["requires_human_review"] is True


class TestQualityCheckOfflineTrade:
    def test_offline_trade(self, check_service):
        r = check_service.check(
            customer_message="能便宜点吗",
            reply="您可以加微信私聊，给您更低价格",
        )
        assert any(v["type"] == "offline_trade" for v in r["violations"])
        assert r["requires_human_review"] is True


class TestQualityCheckRudeTone:
    def test_rude_tone(self, check_service):
        r = check_service.check(
            customer_message="质量太差了",
            reply="你脑子有问题吗？这哪里差了",
        )
        assert any(v["type"] == "rude_tone" for v in r["violations"])


class TestQualityCheckMissingEmpathy:
    def test_missing_empathy(self, check_service):
        r = check_service.check(
            customer_message="质量太差了，非常失望",
            reply="哦，那您申请退货吧",
        )
        assert any(v["type"] == "missing_empathy" for v in r["violations"])

    def test_has_empathy_no_violation(self, check_service):
        r = check_service.check(
            customer_message="质量太差了，非常失望",
            reply="非常抱歉给您带来不好的体验，我们会尽快为您处理",
        )
        assert not any(v["type"] == "missing_empathy" for v in r["violations"])


class TestQualityCheckMissingLookup:
    def test_missing_lookup(self, check_service):
        r = check_service.check(
            customer_message="我的订单怎么还没发货",
            reply="不知道呢",
        )
        assert any(v["type"] == "missing_lookup" for v in r["violations"])


class TestQualityCheckMissingEscalation:
    def test_missing_escalation(self, check_service):
        r = check_service.check(
            customer_message="我要打12315投诉你们",
            reply="好的，我们会处理",
        )
        assert any(v["type"] == "missing_escalation" for v in r["violations"])
