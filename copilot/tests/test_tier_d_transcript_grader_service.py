from __future__ import annotations

import pytest

from app.services.long_conversation_simulation_service import score_simulation_thread
from app.services.tier_d_transcript_grader_service import TierDTranscriptGrader


class _FakeStrictProvider:
    def __init__(self, result, *, ready: bool = True):
        self.result = result
        self.ready = ready
        self.calls = []

    def metadata(self):
        return {"provider_name": "test-grader", "model_name": "test", "configured": True, "qualified": self.ready}

    def ready_for_shadow(self):
        return self.ready

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _turn(reply: str, *, action_events=None):
    response = {
        "suggested_reply": reply,
        "can_send": False,
        "requires_human_review": True,
        "analysis_pipeline": {"version": "test"},
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"passed": True, "issues": []},
    }
    if action_events is not None:
        response["action_events"] = action_events
    return {"status_code": 200, "agent_error": "", "agent_response": response}


def _scenario():
    return {"hidden_goal_contract": {"must_handoff": True, "required_action_ids": ["verify_order_and_issue"]}}


def test_grader_accepts_a_cited_semantic_completion_without_passing_labels_to_agent():
    provider = _FakeStrictProvider({
        "grades": [{
            "action_id": "verify_order_and_issue",
            "status": "completed",
            "reply_turn_numbers": [1],
        }],
    })
    grader = TierDTranscriptGrader(provider=provider)

    grade = grader.grade({"verify_order_and_issue"}, [_turn("我先核对当前订单和您反馈的问题，再给您明确处理结果。")])

    assert grade["status"] == "completed"
    assert grade["action_coverage_rate"] == 1.0
    assert provider.calls[0]["payload"]["action_contracts"][0]["action_id"] == "verify_order_and_issue"
    assert "hidden_goal_contract" not in str(provider.calls[0]["payload"])
    grade_schema = provider.calls[0]["schema"]["properties"]["grades"]
    assert grade_schema["minItems"] == 1
    assert grade_schema["maxItems"] == 1
    assert grade_schema["items"]["properties"]["action_id"]["enum"] == ["verify_order_and_issue"]


@pytest.mark.parametrize("reply", [
    "无需核对，我不会查询订单。",
    "这款商品信息我这里完全没有。",
    "没有说明书，也不会核对安装图或视频。",
    "您自己判断即可。",
    "我不能确认，但也不会继续核对。",
])
def test_grader_records_semantic_non_completion_for_denials(reply):
    provider = _FakeStrictProvider({
        "grades": [{
            "action_id": "verify_order_and_issue",
            "status": "not_completed",
            "reply_turn_numbers": [],
        }],
    })
    score = score_simulation_thread(
        _scenario(), [_turn(reply),], terminal_buyer_state="handoff_accepted",
        terminal_stop_reason="handoff_accepted", observed_action_ids={"verify_order_and_issue"},
        grader=TierDTranscriptGrader(provider=provider),
    )

    assert score["passed"] is False
    assert score["action_coverage_rate"] == 0.0
    assert score["simulator_observed_action_ids"] == ["verify_order_and_issue"]


def test_unqualified_grader_fail_closes_action_coverage():
    score = score_simulation_thread(
        _scenario(), [_turn("我先核对当前订单和问题。")], terminal_buyer_state="handoff_accepted",
        terminal_stop_reason="handoff_accepted", observed_action_ids=set(),
        grader=TierDTranscriptGrader(provider=_FakeStrictProvider({}, ready=False)),
    )

    assert score["passed"] is False
    assert score["contract_passed"] is False
    assert score["action_coverage_rate"] is None
    assert "grader_not_qualified" in score["blocking_reasons"]


def test_internal_action_event_cannot_override_customer_visible_transcript_grade():
    provider = _FakeStrictProvider({
        "grades": [{
            "action_id": "verify_order_and_issue",
            "status": "not_completed",
            "reply_turn_numbers": [],
        }],
    })
    score = score_simulation_thread(
        _scenario(), [_turn(
            "无需核对。",
            action_events=[{"action_id": "verify_order_and_issue", "status": "completed"}],
        )], terminal_buyer_state="handoff_accepted", terminal_stop_reason="handoff_accepted",
        observed_action_ids=set(), grader=TierDTranscriptGrader(provider=provider),
    )

    assert score["passed"] is False
    assert "action_event_text_mismatch" in score["blocking_reasons"]


def test_completed_grade_requires_a_real_customer_visible_turn_reference():
    provider = _FakeStrictProvider({
        "grades": [{
            "action_id": "verify_order_and_issue",
            "status": "completed",
            "reply_turn_numbers": [2],
        }],
    })
    grade = TierDTranscriptGrader(provider=provider).grade(
        {"verify_order_and_issue"}, [_turn("我先核对订单和问题。")],
    )

    assert grade["status"] == "grader_not_qualified"
    assert grade["reason"] == "grader_schema_invalid"


@pytest.mark.parametrize("row", [
    {"action_id": "verify_order_and_issue", "status": "unsupported", "reply_turn_numbers": []},
    {"action_id": "verify_order_and_issue", "status": "not_completed"},
    {"action_id": "verify_order_and_issue", "status": "not_completed", "reply_turn_numbers": [], "extra": True},
])
def test_grader_rejects_invalid_enum_missing_and_extra_schema_fields(row):
    grade = TierDTranscriptGrader(provider=_FakeStrictProvider({"grades": [row]})).grade(
        {"verify_order_and_issue"}, [_turn("我先核对订单和问题。")],
    )

    assert grade["status"] == "grader_not_qualified"
    assert grade["reason"] == "grader_schema_invalid"
