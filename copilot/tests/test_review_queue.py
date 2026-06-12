"""
人工复核队列服务测试
"""

import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.review_queue_service import ReviewQueueService
from app.services.feedback_service import FeedbackService


@pytest.fixture
def review_service():
    """带临时文件的复核队列服务"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        path = f.name
    service = ReviewQueueService(filepath=path)
    yield service
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def feedback_service():
    """带临时文件的反馈服务"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        path = f.name
    service = FeedbackService(filepath=path)
    yield service
    if os.path.exists(path):
        os.remove(path)


class TestReviewQueueEnqueue:
    """入队测试"""

    def test_enqueue_high_risk(self, review_service):
        """高风险结果可入队"""
        suggestion = {
            "suggested_reply": "测试回复",
            "risk_level": "high",
            "intent": "投诉",
            "customer_emotion": "愤怒",
            "policy_warnings": ["高风险"],
            "guard_warnings": [],
            "action_proposal": {"action_type": "转主管", "reason": "投诉"},
        }
        rec = review_service.enqueue(suggestion, "我要投诉你们", "O123")
        assert rec["status"] == "pending"
        assert rec["customer_message"] == "我要投诉你们"
        assert rec["order_id"] == "O123"
        assert rec["risk_level"] == "high"
        assert len(rec["id"]) > 0

    def test_no_duplicate_enqueue(self, review_service):
        """相同消息不重复入队"""
        suggestion = {"suggested_reply": "r", "risk_level": "high", "intent": "t"}
        rec1 = review_service.enqueue(suggestion, "相同消息", "O1")
        rec2 = review_service.enqueue(suggestion, "相同消息", "O1")
        assert rec1["id"] == rec2["id"]
        # 文件中应该只有一条
        all_recs = review_service.list_reviews()
        assert len(all_recs) == 1


class TestReviewQueueList:
    """列表查询测试"""

    def test_list_pending(self, review_service):
        suggestion = {"suggested_reply": "r", "risk_level": "high", "intent": "t"}
        review_service.enqueue(suggestion, "msg1")
        review_service.enqueue(suggestion, "msg2")

        pending = review_service.list_reviews(status="pending")
        assert len(pending) == 2

    def test_list_approved_empty(self, review_service):
        suggestion = {"suggested_reply": "r", "risk_level": "high", "intent": "t"}
        review_service.enqueue(suggestion, "msg1")
        approved = review_service.list_reviews(status="approved")
        assert len(approved) == 0


class TestReviewQueueGetById:
    """单条查询测试"""

    def test_get_by_id(self, review_service):
        suggestion = {"suggested_reply": "r", "risk_level": "high", "intent": "t"}
        rec = review_service.enqueue(suggestion, "msg1")
        found = review_service.get_by_id(rec["id"])
        assert found is not None
        assert found["customer_message"] == "msg1"

    def test_get_by_id_not_found(self, review_service):
        assert review_service.get_by_id("nonexistent") is None


class TestReviewQueueDecide:
    """决策测试"""

    def test_approved_decision(self, review_service):
        suggestion = {"suggested_reply": "建议", "risk_level": "high", "intent": "t"}
        rec = review_service.enqueue(suggestion, "msg")
        updated = review_service.decide(rec["id"], "approved", reviewed_by="客服A")
        assert updated["status"] == "approved"
        assert updated["final_reply"] == "建议"  # approved 默认用 suggested_reply
        assert updated["reviewed_by"] == "客服A"

    def test_edited_decision_requires_final_reply(self, review_service):
        suggestion = {"suggested_reply": "建议", "risk_level": "high", "intent": "t"}
        rec = review_service.enqueue(suggestion, "msg")
        with pytest.raises(ValueError) as exc_info:
            review_service.decide(rec["id"], "edited")
        assert "final_reply" in str(exc_info.value)

    def test_edited_decision_ok(self, review_service):
        suggestion = {"suggested_reply": "建议", "risk_level": "high", "intent": "t"}
        rec = review_service.enqueue(suggestion, "msg")
        updated = review_service.decide(rec["id"], "edited", final_reply="修改后的回复")
        assert updated["status"] == "edited"
        assert updated["final_reply"] == "修改后的回复"

    def test_invalid_status(self, review_service):
        suggestion = {"suggested_reply": "建议", "risk_level": "high", "intent": "t"}
        rec = review_service.enqueue(suggestion, "msg")
        with pytest.raises(ValueError) as exc_info:
            review_service.decide(rec["id"], "invalid_status")
        assert "非法 status" in str(exc_info.value)

    def test_decide_nonexistent(self, review_service):
        assert review_service.decide("nonexistent", "approved") is None

    def test_decide_sync_feedback(self, review_service, feedback_service):
        """decision 后同步写入 feedback"""
        suggestion = {
            "suggested_reply": "建议",
            "risk_level": "high",
            "intent": "投诉",
            "customer_emotion": "愤怒",
            "policy_warnings": [],
            "guard_warnings": [],
            "action_proposal": {},
        }
        rec = review_service.enqueue(suggestion, "msg", "O1")
        updated = review_service.decide(rec["id"], "approved", reviewed_by="客服A", review_note="已处理")

        # 手动同步（与路由中逻辑一致：approved -> accepted）
        feedback_service.save(
            customer_message=updated["customer_message"],
            suggested_reply=updated["suggested_reply"],
            action="accepted",
            order_id=updated["order_id"],
            final_reply=updated["final_reply"],
            risk_level=updated["risk_level"],
            source="review",
            review_id=rec["id"],
        )

        stats = feedback_service.get_stats()
        assert stats["total"] == 1
        assert stats["accepted"] == 1
        assert stats["review_source_count"] == 1


class TestReviewQueueCountPending:
    """待复核计数"""

    def test_count_pending(self, review_service):
        suggestion = {"suggested_reply": "r", "risk_level": "high", "intent": "t"}
        review_service.enqueue(suggestion, "msg1")
        review_service.enqueue(suggestion, "msg2")
        rec = review_service.enqueue(suggestion, "msg3")
        review_service.decide(rec["id"], "approved")
        assert review_service.count_pending() == 2
