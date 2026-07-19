from __future__ import annotations

import pytest

from app.services.strict_decision_provider_service import StrictDecisionProviderError
from app.services.tier_d_transcript_grader_service import TierDTranscriptGrader
from scripts.qualify_tier_d_transcript_grader import qualify


class _Provider:
    def __init__(self, *, configured=True, ready=True, latencies=()):
        self.configured = configured
        self.ready = ready
        self.calls = []
        self._latencies = list(latencies)
        self.last_latency_ms = None

    def metadata(self):
        return {
            "provider_name": "grader",
            "model_name": "grader-model",
            "capability": "strict_json_schema",
            "configured": self.configured,
            "qualified": self.ready,
        }

    def ready_for_shadow(self):
        return self.ready

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self._latencies:
            self.last_latency_ms = self._latencies[(len(self.calls) - 1) % len(self._latencies)]
        reply = kwargs["payload"]["customer_visible_agent_replies"][0]["reply"]
        action_id = kwargs["payload"]["action_contracts"][0]["action_id"]
        completed = reply in {
            "我先核对当前订单和您反馈的问题，再给您明确处理结果。",
            "我按当前商品资料核对对应安装步骤，确认后回复您。",
            "请把卡住的安装位置拍一张，我按这个位置继续核对。",
        }
        return {
            "grades": [{
                "action_id": action_id,
                "status": "completed" if completed else "not_completed",
                "reply_turn_numbers": [1] if completed else [],
            }],
        }


def test_transcript_grader_qualification_uses_unqualified_configured_candidate_for_semantic_matrix():
    provider = _Provider(ready=False)
    grader = TierDTranscriptGrader(provider=provider)

    report = qualify(repeats=2, grader=grader)

    assert report["qualification_status"] == "qualified"
    assert report["configured_candidate"] is True
    assert report["qualified_for_evaluation"] is False
    assert report["credentials_reported"] is False
    assert all(report["local_contract_checks"].values())
    assert report["provider_schema_success_rate"]["rate"] == 1.0
    assert report["positive_semantic_pass_rate"]["rate"] == 1.0
    assert report["negative_semantic_block_rate"]["rate"] == 1.0
    assert provider.calls
    assert all(call["allow_unqualified"] is True for call in provider.calls)


def test_unconfigured_transcript_grader_reports_not_qualified_without_network_call():
    provider = _Provider(configured=False, ready=False)
    report = qualify(repeats=2, grader=TierDTranscriptGrader(provider=provider))

    assert report["qualification_status"] == "not_qualified"
    assert report["provider_schema_success_rate"] == {"numerator": 0, "denominator": 0, "rate": None}
    assert provider.calls == []


def test_qualification_records_each_successful_call_latency_without_reusing_last_value():
    provider = _Provider(ready=False, latencies=(10, 20, 30))

    report = qualify(repeats=3, grader=TierDTranscriptGrader(provider=provider))

    assert [row["latency_ms"] for row in report["attempts"][:3]] == [10.0, 20.0, 30.0]
    assert report["latency_ms"] == {
        "successful_attempt_count": 30,
        "p50": 20.0,
        "p95": 30.0,
    }


class _TimeoutProvider(_Provider):
    def request(self, **kwargs):
        self.calls.append(kwargs)
        self.last_latency_ms = 30
        raise StrictDecisionProviderError("timeout")


def test_qualification_does_not_assign_latency_to_timeout_attempts():
    provider = _TimeoutProvider(ready=False)

    report = qualify(repeats=3, grader=TierDTranscriptGrader(provider=provider))

    assert report["total_attempt_count"] == 30
    assert report["timeout_attempt_count"] == 30
    assert report["timeout_count"] == 30
    assert report["latency_ms"] == {
        "successful_attempt_count": 0,
        "p50": None,
        "p95": None,
    }
    assert all(row["latency_ms"] is None for row in report["attempts"])


class _OneTimeoutProvider(_Provider):
    def request(self, **kwargs):
        if not self.calls:
            self.calls.append(kwargs)
            self.last_latency_ms = 99
            raise StrictDecisionProviderError("timeout")
        return super().request(**kwargs)


def test_qualification_counts_a_single_timeout_and_never_reuses_its_latency():
    provider = _OneTimeoutProvider(ready=False, latencies=(10, 20))

    report = qualify(repeats=1, grader=TierDTranscriptGrader(provider=provider))

    assert report["total_attempt_count"] == 10
    assert report["timeout_attempt_count"] == 1
    assert report["successful_attempt_count"] == 9
    assert report["attempts"][0]["latency_ms"] is None
    assert all(row["latency_ms"] is not None for row in report["attempts"][1:])


class _InvalidSchemaProvider(_Provider):
    def request(self, **kwargs):
        self.calls.append(kwargs)
        self.last_latency_ms = 25
        action_id = kwargs["payload"]["action_contracts"][0]["action_id"]
        return {"grades": [{"action_id": action_id, "status": "invalid", "reply_turn_numbers": []}]}


@pytest.mark.parametrize("provider", [_InvalidSchemaProvider(ready=False), _TimeoutProvider(ready=False)])
def test_qualification_fails_closed_for_schema_or_transport_errors(provider):
    report = qualify(repeats=1, grader=TierDTranscriptGrader(provider=provider))

    assert report["qualification_status"] == "not_qualified"
    assert report["successful_attempt_count"] == 0
    assert all(row["latency_ms"] is None for row in report["attempts"])


def test_qualification_counts_schema_errors_from_attempts():
    report = qualify(repeats=1, grader=TierDTranscriptGrader(provider=_InvalidSchemaProvider(ready=False)))

    assert report["schema_error_attempt_count"] == 10
    assert report["free_text_fallback_attempt_count"] == 0


class _StructuredFailureProvider(_Provider):
    def __init__(self, reason, **kwargs):
        super().__init__(**kwargs)
        self.reason = reason

    def request(self, **kwargs):
        self.calls.append(kwargs)
        self.last_latency_ms = 25
        raise StrictDecisionProviderError(self.reason)


@pytest.mark.parametrize(
    ("reason", "counter_name"),
    [
        ("structured_output_truncated", "truncated_attempt_count"),
        ("structured_output_not_json", "free_text_fallback_attempt_count"),
        ("empty_structured_output", "schema_error_attempt_count"),
    ],
)
def test_qualification_counts_structured_failures_per_attempt(reason, counter_name):
    provider = _StructuredFailureProvider(reason, ready=False)

    report = qualify(repeats=1, grader=TierDTranscriptGrader(provider=provider))

    assert report["qualification_status"] == "not_qualified"
    assert report[counter_name] == 10
    assert report["successful_attempt_count"] == 0
    assert all(row["latency_ms"] is None for row in report["attempts"])
