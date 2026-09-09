"""
人工复核队列服务测试
"""

import sys
import os
import tempfile
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
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
        """同一完整执行身份的重复入队是幂等的。"""
        suggestion = {"suggested_reply": "r", "risk_level": "high", "intent": "t"}
        identity = dict(source="test", conversation_id="conversation-a",
                        message_id="message-a", request_id="request-a", shop_id="shop-a")
        rec1 = review_service.enqueue(suggestion, "相同消息", "O1", **identity)
        rec2 = review_service.enqueue(suggestion, "相同消息", "O1", **identity)
        assert rec1["id"] == rec2["id"]
        # 文件中应该只有一条
        all_recs = review_service.list_reviews()
        assert len(all_recs) == 1


def _identity(**changes):
    return dict(dict(source="test", conversation_id="conversation-a",
                     message_id="message-a", request_id="request-a", shop_id="shop-a"), **changes)


def test_unidentified_equal_text_and_order_never_merge(review_service):
    first = review_service.enqueue({"suggested_reply": "candidate"}, "same words", "order-a")
    second = review_service.enqueue({"suggested_reply": "candidate"}, "same words", "order-a")
    assert first["id"] != second["id"]
    assert review_service.count_pending() == 2


@pytest.mark.parametrize("field", ["conversation_id", "message_id", "request_id", "source", "shop_id"])
def test_different_identity_component_keeps_separate_review(review_service, field):
    first = review_service.enqueue({}, "same words", **_identity())
    second = review_service.enqueue({}, "same words", **_identity(**{field: "different"}))
    assert first["id"] != second["id"]


@pytest.mark.parametrize("changes", [
    {"source": ""}, {"conversation_id": ""}, {"conversation_id": "default"},
    {"conversation_id": "qianniu"}, {"message_id": "", "request_id": ""},
    {"conversation_id": None}, {"conversation_id": ["a"]}, {"shop_id": 123},
    {"message_id": " padded "}, {"request_id": "line\nbreak"}, {"source": "x" * 513},
])
def test_incomplete_or_invalid_identity_disables_dedup(review_service, changes):
    identity = _identity(**changes)
    first = review_service.enqueue({}, "same words", **identity)
    second = review_service.enqueue({}, "same words", **identity)
    assert first["id"] != second["id"]


@pytest.mark.parametrize("field", ["source", "shop_id", "conversation_id", "message_id", "request_id"])
def test_unencodable_identity_keeps_independent_review(review_service, field):
    identity = _identity(**{field: "\ud800"})
    first = review_service.enqueue({}, "same words", **identity)
    second = review_service.enqueue({}, "same words", **identity)
    assert first["id"] != second["id"]
    assert review_service.count_pending() == 2


@pytest.mark.parametrize("changes", [{"message_id": ""}, {"request_id": ""}, {"shop_id": ""}])
def test_one_execution_reference_or_unscoped_shop_still_has_exact_identity(review_service, changes):
    first = review_service.enqueue({}, "same words", **_identity(**changes))
    second = review_service.enqueue({}, "same words", **_identity(**changes))
    assert first["id"] == second["id"]


@pytest.mark.parametrize("change", [
    {"suggested_reply": "new candidate"}, {"risk_level": "high"},
    {"policy_warnings": ["review"]}, {"guard_warnings": ["blocked"]},
    {"action_proposal": {"action_type": "human_review"}},
])
def test_reused_identity_cannot_return_stale_review_content(review_service, change):
    first = review_service.enqueue({}, "same words", **_identity())
    second = review_service.enqueue(change, "same words", **_identity())
    assert first["id"] != second["id"]


@pytest.mark.parametrize("message,order", [("new words", "order-a"), ("same words", "order-b")])
def test_reused_identity_cannot_merge_different_input(review_service, message, order):
    first = review_service.enqueue({}, "same words", "order-a", **_identity())
    second = review_service.enqueue({}, message, order, **_identity())
    assert first["id"] != second["id"]


@pytest.mark.parametrize("status", ["approved", "edited", "rejected", "escalated"])
def test_completed_review_cannot_approve_a_new_enqueue(review_service, status):
    first = review_service.enqueue({}, "same words", **_identity())
    review_service.decide(first["id"], status, final_reply="reviewed candidate")
    second = review_service.enqueue({}, "same words", **_identity())
    assert second["id"] != first["id"]
    assert second["status"] == "pending"
    assert second["final_reply"] == ""


def test_legacy_record_is_not_reidentified_or_rewritten(review_service):
    old = {"id": "legacy", "status": "pending", "customer_message": "same words", "order_id": ""}
    original = json.dumps(old) + "\n"
    with open(review_service.filepath, "w", encoding="utf-8") as handle:
        handle.write(original)
    new = review_service.enqueue({}, "same words", **_identity())
    assert new["id"] != old["id"]
    with open(review_service.filepath, encoding="utf-8") as handle:
        assert handle.readline() == original
    assert review_service.get_by_id("legacy") == old


def test_identity_survives_reopen_and_more_than_200_new_records(review_service):
    first = review_service.enqueue({}, "same words", **_identity())
    for index in range(205):
        review_service.enqueue({}, str(index))
    reopened = ReviewQueueService(review_service.filepath)
    repeated = reopened.enqueue({}, "same words", **_identity())
    assert repeated["id"] == first["id"]
    assert reopened.count_pending() == 206


def test_identity_tuple_cannot_collide_on_delimiters(review_service):
    first = review_service.enqueue({}, "same words", **_identity(source="a|b", conversation_id="c"))
    second = review_service.enqueue({}, "same words", **_identity(source="a", conversation_id="b|c"))
    assert first["id"] != second["id"]


def test_raw_identity_fields_are_not_added_to_queue_storage(review_service):
    identity = _identity()
    record = review_service.enqueue({}, "same words", **identity)
    with open(review_service.filepath, encoding="utf-8") as handle:
        stored = handle.read()
    for value in identity.values():
        assert value not in stored
    assert record["enqueue_identity"]["schema_version"] == "review-event/v1"
    assert len(record["enqueue_identity"]["sha256"]) == 64


def test_concurrent_same_event_instances_share_one_pending_record(review_service):
    def enqueue(_):
        queue = ReviewQueueService(review_service.filepath)
        return queue.enqueue({}, "same words", **_identity())["id"]
    with ThreadPoolExecutor(max_workers=4) as workers:
        ids = list(workers.map(enqueue, range(12)))
    assert len(set(ids)) == 1
    assert review_service.count_pending() == 1


def test_decision_rewrite_cannot_erase_concurrent_enqueue(review_service, monkeypatch):
    first = review_service.enqueue({}, "first event", **_identity())
    writing, release, appending = Event(), Event(), Event()
    original_write = review_service._write_all

    def paused_write(records):
        writing.set()
        assert release.wait(3)
        original_write(records)

    def append():
        other = ReviewQueueService(review_service.filepath)
        appending.set()
        return other.enqueue({}, "second event", **_identity(message_id="message-b"))

    monkeypatch.setattr(review_service, "_write_all", paused_write)
    with ThreadPoolExecutor(max_workers=2) as workers:
        decision = workers.submit(review_service.decide, first["id"], "rejected")
        try:
            assert writing.wait(2)
            pending = workers.submit(append)
            assert appending.wait(2)
            with pytest.raises(TimeoutError):
                pending.result(timeout=0.1)
        finally:
            release.set()
        decision.result(timeout=2)
        second = pending.result(timeout=2)
    reopened = ReviewQueueService(review_service.filepath)
    assert len(reopened.list_reviews()) == 2
    assert reopened.get_by_id(first["id"])["status"] == "rejected"
    assert reopened.get_by_id(second["id"])["status"] == "pending"


def test_versioned_conversations_replay_without_cross_customer_merge(review_service):
    from app.services.high_quality_long_conversation_review_service import load_and_validate_review_dataset

    folder = Path(__file__).parent / "fixtures" / "p1_conversation_reconstructed"
    manifest = json.loads((folder / "v1.manifest.json").read_text(encoding="utf-8"))
    dataset, validation = load_and_validate_review_dataset(folder / "v1.json")
    # This is a queue-only fixture replay, not the native model benchmark.
    # Pin the existing semantic content contract, not native-run byte identity.
    assert validation["validation_status"] == "passed"
    assert validation["computed_content_sha256"] == manifest["content_sha256"]
    assert dataset["dataset_version"] == manifest["dataset_version"]
    assert len(dataset["scenarios"]) == manifest["scenario_count"]
    ids = []
    for scenario in dataset["scenarios"]:
        conversation = scenario["api_request_template"]["conversation_id"]
        messages = [turn["content"] for turn in scenario["conversation_history"]
                    if turn["role"] == "customer"] + [scenario["current_buyer_message"]]
        for index, message in enumerate(messages):
            identity = _identity(conversation_id=conversation, message_id=f"message-{index}",
                                 request_id=f"request-{index}")
            first = review_service.enqueue({}, message, **identity)
            retry = review_service.enqueue({}, message, **identity)
            other_customer = review_service.enqueue(
                {}, message, **dict(identity, conversation_id=f"other-{conversation}"))
            repeated_message = review_service.enqueue(
                {}, message, **dict(identity, message_id=f"repeat-{index}", request_id=f"repeat-{index}"))
            assert first["id"] == retry["id"]
            ids.extend([first["id"], other_customer["id"], repeated_message["id"]])
    assert len(set(ids)) == len(ids) == review_service.count_pending()


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
