from __future__ import annotations

from copy import deepcopy

import pytest


class _Result:
    def __init__(self, payload: dict):
        self.payload = payload

    def to_dict(self) -> dict:
        return deepcopy(self.payload)


class _ReplyService:
    def __init__(self, payload: dict):
        self.payload = payload

    def analyze(self, *args, **kwargs):
        return _Result(self.payload)


@pytest.fixture()
def persistence_capture(monkeypatch):
    import app.services.analysis_snapshot as file_snapshot
    import app.tracing.recorder as recorder
    import app.tracing.repository as repository

    captured: dict[str, dict] = {}
    monkeypatch.setattr(repository, "init_trace_tables", lambda: None)
    monkeypatch.setattr(recorder, "start_trace", lambda **kwargs: "trace-final")
    monkeypatch.setattr(recorder, "start_span", lambda **kwargs: "span-final")
    monkeypatch.setattr(recorder, "end_span", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        recorder,
        "save_analysis_snapshot",
        lambda **kwargs: captured.__setitem__("sqlite", deepcopy(kwargs)),
    )
    monkeypatch.setattr(
        recorder,
        "end_trace",
        lambda trace_id, **kwargs: captured.__setitem__(
            "trace", {"trace_id": trace_id, **deepcopy(kwargs)}
        ),
    )
    monkeypatch.setattr(
        file_snapshot,
        "save_snapshot",
        lambda **kwargs: captured.__setitem__("file", deepcopy(kwargs)),
    )
    return captured


def _graph_payload() -> dict:
    return {
        "suggested_reply": "graph reply",
        "sendable_reply": "graph reply",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "graph reply"}],
        "reply_delivery": {"auto_send_ready": True},
        "recommended_assets": [],
        "intent": "product_question",
        "risk_level": "low",
        "execution_debug": {},
        "evidence_debug": {},
        "trace_steps": [],
        "context_used": {},
    }


def _final_payload(response: dict) -> dict:
    final = deepcopy(response)
    final.update(
        {
            "suggested_reply": "final reviewed reply",
            "draft_reply": "final reviewed reply",
            "sendable_reply": "",
            "can_send": False,
            "requires_human_review": True,
            "reply_status": "needs_human_review",
            "reply_blocks": [{"type": "text", "content": "final reviewed reply"}],
            "reply_delivery": {"auto_send_ready": False},
            "recommended_assets": [{"asset_uid": "asset-1", "asset_type": "manual"}],
            "final_answer_audit": {"passed": False, "issues": ["needs_review"]},
            "final_semantic_fit_audit": {"passed": True, "issues": []},
            "final_response_pipeline": {"version": "final-response-orchestrator-v1"},
        }
    )
    return final


def test_final_response_is_persisted_consistently(monkeypatch, persistence_capture):
    from app.services.analysis_execution_service import execute_analysis
    import app.services.final_response_orchestrator as orchestrator

    monkeypatch.setattr(
        orchestrator,
        "orchestrate_final_response",
        lambda response, **kwargs: _final_payload(response),
    )

    response = execute_analysis(
        reply_service=_ReplyService(_graph_payload()),
        customer_message="test message",
        conversation_id="trace-consistency",
    )

    expected = {
        key: response.get(key)
        for key in (
            "suggested_reply",
            "draft_reply",
            "sendable_reply",
            "can_send",
            "requires_human_review",
            "reply_status",
            "reply_blocks",
            "reply_delivery",
            "recommended_assets",
            "final_answer_audit",
            "final_semantic_fit_audit",
            "trace_response_stage",
            "final_response_pipeline_version",
        )
    }

    sqlite_contract = persistence_capture["sqlite"]["execution_debug"]["final_response_contract"]
    file_contract = persistence_capture["file"]["final_response_contract"]
    trace_contract = persistence_capture["trace"]["outcome"]["final_response_contract"]

    assert response["trace_response_stage"] == "final"
    assert response["final_response_pipeline_version"] == "final-response-orchestrator-v1"
    assert persistence_capture["sqlite"]["suggested_reply"] == response["suggested_reply"]
    assert persistence_capture["sqlite"]["need_human_review"] is True
    assert persistence_capture["file"]["suggested_reply"] == response["suggested_reply"]
    assert persistence_capture["file"]["need_human_review"] is True
    assert sqlite_contract == expected
    assert file_contract == expected
    assert trace_contract == expected


def test_final_orchestration_disabled_is_not_marked_final(persistence_capture):
    from app.services.analysis_execution_service import execute_analysis

    response = execute_analysis(
        reply_service=_ReplyService(_graph_payload()),
        customer_message="test message",
        final_orchestration=False,
    )

    assert response["trace_response_stage"] == "graph_result"
    assert response["final_response_pipeline_version"] == ""
    assert persistence_capture["sqlite"]["execution_debug"]["final_response_contract"][
        "trace_response_stage"
    ] == "graph_result"
    assert persistence_capture["file"]["final_response_contract"][
        "trace_response_stage"
    ] == "graph_result"
    assert persistence_capture["trace"]["outcome"]["final_response_contract"][
        "trace_response_stage"
    ] == "graph_result"


def test_final_orchestration_failure_is_not_marked_final(monkeypatch, persistence_capture):
    from app.services.analysis_execution_service import execute_analysis
    import app.services.final_response_orchestrator as orchestrator

    def fail_orchestration(*args, **kwargs):
        raise RuntimeError("orchestration failed")

    monkeypatch.setattr(orchestrator, "orchestrate_final_response", fail_orchestration)
    response = execute_analysis(
        reply_service=_ReplyService(_graph_payload()),
        customer_message="test message",
    )

    assert response["trace_response_stage"] == "pre_final"
    assert response["final_response_pipeline_version"] == ""
    assert persistence_capture["sqlite"]["execution_debug"]["final_response_contract"][
        "trace_response_stage"
    ] == "pre_final"
    assert persistence_capture["file"]["final_response_contract"][
        "trace_response_stage"
    ] == "pre_final"
    assert persistence_capture["trace"]["outcome"]["final_response_contract"][
        "trace_response_stage"
    ] == "pre_final"


def test_error_response_has_explicit_trace_stage(persistence_capture):
    from app.services.analysis_execution_service import execute_analysis

    class FailingService:
        def analyze(self, *args, **kwargs):
            raise RuntimeError("analysis failed")

    response = execute_analysis(
        reply_service=FailingService(),
        customer_message="test message",
    )

    assert response["trace_response_stage"] == "error"
    assert response["final_response_pipeline_version"] == ""
    assert persistence_capture["trace"]["outcome"]["trace_response_stage"] == "error"
