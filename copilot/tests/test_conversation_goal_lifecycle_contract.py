from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.services import semantic_fact_type_service as semantic_service


def _canonical_goal(
    *,
    goal_ref: str,
    source_turn_uid: str,
    source_span_sha256: str,
    claim_type: str = "material",
) -> dict:
    return {
        "schema_version": semantic_service.GOAL_IDENTITY_SCHEMA_VERSION,
        "goal_ref": goal_ref,
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": claim_type,
        "claim_type_exact_match": True,
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "goal_summary": "not persisted",
        "confidence": 1.0,
        "source": "current_customer_message",
        "source_span_start": 0,
        "source_span_end": 5,
        "source_span_sha256": source_span_sha256,
        "source_text_sha256": source_span_sha256,
        "source_turn_uid": source_turn_uid,
        "owner": "turn_understanding_owner",
        "source_stage": "semantic_fact_type_service",
        "claim_type_reason_code": "",
    }


@pytest.fixture
def lifecycle_trace_db(tmp_path, monkeypatch):
    from app.tracing import repository

    previous_engine = repository._engine
    if previous_engine is not None:
        previous_engine.dispose()
    monkeypatch.setattr(repository, "TRACE_DB_PATH", str(tmp_path / "trace.db"))
    monkeypatch.setattr(repository, "_engine", None)
    monkeypatch.setattr(repository, "_SessionLocal", None)
    monkeypatch.setenv(
        "COPILOT_CONVERSATION_GOAL_LIFECYCLE_HMAC_KEY",
        "test-only-conversation-goal-key",
    )
    yield repository
    if repository._engine is not None:
        repository._engine.dispose()


def test_open_goal_lifecycle_uses_hmac_identity_and_only_verified_successor(
    lifecycle_trace_db,
):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )

    assert repository.record_conversation_goal_lifecycle(
        "raw-conversation-identifier", [original]
    ) == {"status": "recorded", "write_count": 1}

    context, status = repository.load_conversation_goal_lifecycle_context(
        "raw-conversation-identifier"
    )
    assert status == "loaded"
    assert context["conversation_ref"] != "raw-conversation-identifier"
    assert context["open_goals"][0]["goal_ref"] == original["goal_ref"]
    assert "not persisted" not in str(context)

    successor = _canonical_goal(
        goal_ref="goal-fedcba9876543210",
        source_turn_uid="turn-fedcba9876543210fedc",
        source_span_sha256="b" * 64,
    )
    continuation = {
        "goal_ref": successor["goal_ref"],
        "continued_from_goal_ref": original["goal_ref"],
        "continued_from_alias": context["open_goals"][0]["goal_alias"],
        "origin_source_turn_uid": original["source_turn_uid"],
        "origin_source_span_sha256": original["source_span_sha256"],
    }

    assert repository.record_conversation_goal_lifecycle(
        "raw-conversation-identifier", [successor], [continuation]
    ) == {"status": "recorded", "write_count": 2}
    current, current_status = repository.load_conversation_goal_lifecycle_context(
        "raw-conversation-identifier"
    )
    assert current_status == "loaded"
    assert [item["goal_ref"] for item in current["open_goals"]] == [
        successor["goal_ref"]
    ]


def test_only_a_verified_lifecycle_completion_removes_an_open_goal(
    lifecycle_trace_db,
):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "recorded", "write_count": 1}
    context, status = repository.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )
    assert status == "loaded"

    assert repository.complete_conversation_goal_lifecycle(
        "conversation-a",
        original["goal_ref"],
        context["open_goals"][0]["goal_alias"],
    ) == {"status": "recorded", "write_count": 1}
    context, status = repository.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )
    assert status == "loaded"
    assert context["open_goals"] == []
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "invalid", "write_count": 0}


def test_lifecycle_is_disabled_without_a_runtime_hmac_key(monkeypatch):
    from app.tracing import repository

    monkeypatch.delenv("COPILOT_CONVERSATION_GOAL_LIFECYCLE_HMAC_KEY", raising=False)
    monkeypatch.setattr(
        repository,
        "init_trace_tables",
        lambda: pytest.fail("disabled lifecycle accessed trace storage"),
    )

    assert repository.load_conversation_goal_lifecycle_context("conversation-a") == (
        {}, "disabled"
    )
    assert repository.record_conversation_goal_lifecycle("conversation-a", []) == {
        "status": "disabled",
        "write_count": 0,
    }


def test_pipeline_removes_public_lifecycle_and_injects_only_server_projection(
    lifecycle_trace_db,
):
    from app.services.analysis_pipeline_service import (
        AnalysisPipelineRequest,
        AnalysisPipelineService,
    )

    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    assert lifecycle_trace_db.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "recorded", "write_count": 1}

    prepared = AnalysisPipelineService()._prepare_request(AnalysisPipelineRequest(
        customer_message="Please confirm the material.",
        reply_service=object(),
        conversation_id="conversation-a",
        copilot_context={
            "conversation_goal_lifecycle": {
                "schema_version": "forged",
                "open_goals": [{"goal_alias": "attacker-controlled"}],
            },
        },
    ))

    assert "conversation_goal_lifecycle" not in prepared.copilot_context
    lifecycle = prepared.copilot_context[
        "_answer_eligibility_owner_context"
    ]["conversation_goal_lifecycle"]
    assert lifecycle["open_goals"][0]["goal_ref"] == original["goal_ref"]
    assert lifecycle["open_goals"][0]["goal_alias"] != "attacker-controlled"


def test_pipeline_lifecycle_persists_only_customer_goals_and_never_changes_send(
    lifecycle_trace_db,
):
    from app.services.analysis_pipeline_service import (
        AnalysisPipelineRequest,
        AnalysisPipelineService,
    )

    target = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
        claim_type="load_capacity",
    )
    premise = deepcopy(target)
    premise.update({
        "goal_ref": "goal-fedcba9876543210",
        "goal_kind": "evidence_dependency",
        "source_turn_uid": "turn-fedcba9876543210fedc",
        "source_span_sha256": "b" * 64,
        "source_text_sha256": "b" * 64,
    })
    response = {
        "can_send": False,
        "requires_human_review": True,
        "turn_understanding": {
            "goal_understanding_status": "valid",
            "customer_goals": [target, premise],
        },
    }

    observation = AnalysisPipelineService._record_conversation_goal_lifecycle(
        response,
        AnalysisPipelineRequest(
            customer_message="Does this carry the requested load?",
            reply_service=object(),
            conversation_id="conversation-a",
        ),
        {"status": "valid"},
    )
    context, status = lifecycle_trace_db.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )

    assert observation == {"status": "recorded", "write_count": 1}
    assert status == "loaded"
    assert [item["goal_ref"] for item in context["open_goals"]] == [
        target["goal_ref"]
    ]
    assert response["can_send"] is False
    assert response["requires_human_review"] is True


def test_continuation_requires_current_turn_provenance_and_exact_goal_identity():
    current_message = "Please confirm the material we discussed."
    open_goal = {
        "goal_alias": "open-goal-0123456789abcdef01234567",
        "goal_ref": "goal-0123456789abcdef",
        "conversation_ref": "conversation-0123456789abcdef0123456789abcdef",
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "source_turn_uid": "turn-0123456789abcdef0123",
        "source_span_sha256": "a" * 64,
    }
    raw_goal = {
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": current_message,
        "continued_from": open_goal["goal_alias"],
    }
    continuations: list[dict] = []

    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [raw_goal],
        message=current_message,
        open_goal_candidates=[open_goal],
        lifecycle_continuations_sink=continuations,
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["claim_type"] == "material"
    assert goals[0]["source_turn_uid"] != open_goal["source_turn_uid"]
    assert continuations == [{
        "goal_ref": goals[0]["goal_ref"],
        "continued_from_goal_ref": open_goal["goal_ref"],
        "continued_from_alias": open_goal["goal_alias"],
        "origin_source_turn_uid": open_goal["source_turn_uid"],
        "origin_source_span_sha256": open_goal["source_span_sha256"],
    }]

    forged = deepcopy(raw_goal)
    forged["claim_type"] = "dimensions"
    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [forged],
        message=current_message,
        open_goal_candidates=[open_goal],
    )
    assert goals == []
    assert status == "invalid"
    assert "conversation_goal_lifecycle_identity_mismatch" in diagnostics


def test_comparison_keeps_target_as_customer_goal_and_premise_as_dependency():
    message = "It weighs 2.05 kg; does that mean it can carry 50 kg?"
    premise = "It weighs 2.05 kg"
    target = "does that mean it can carry 50 kg?"

    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [
            {
                "goal_kind": "evidence_dependency",
                "claim_type_status": "canonical",
                "claim_type": "gross_weight",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": premise,
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "load_capacity",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": target,
            },
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert [goal["goal_kind"] for goal in goals] == [
        "evidence_dependency", "customer_goal"
    ]
    assert [goal["claim_type"] for goal in goals] == [
        "gross_weight", "load_capacity"
    ]


def test_llm_receives_only_opaque_open_goal_metadata_and_returns_verified_continuation(
    monkeypatch,
):
    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        finish_reason = "stop"

        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _Client:
        api_key = object()
        model = "test-model"

        def __init__(self):
            self.request = None

        def create_chat_completion(self, **kwargs):
            self.request = kwargs
            return _Response(json.dumps({
                "goals": [{
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "material",
                    "attribute_key": "",
                    "semantic_key": "",
                    "policy_intent_ref": "",
                    "source_text": "Please confirm the material.",
                    "continued_from": "open-goal-bbbbbbbbbbbbbbbbbbbbbbbb",
                }],
            }))

    open_goal = {
        "goal_alias": "open-goal-bbbbbbbbbbbbbbbbbbbbbbbb",
        "goal_ref": "goal-0123456789abcdef",
        "conversation_ref": "conversation-0123456789abcdef0123456789abcdef",
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "source_turn_uid": "turn-0123456789abcdef0123",
        "source_span_sha256": "a" * 64,
    }
    client = _Client()
    monkeypatch.setattr(semantic_service, "get_llm_client", lambda: client)

    result = semantic_service._classify_with_llm(
        {
            "copilot_context": {
                "_answer_eligibility_owner_context": {
                    "schema_version": "answer-eligibility-owner-context/v1",
                    "source": "server_configuration",
                    "owner": "analysis_pipeline",
                    "provenance": {"boundary": "analysis_pipeline_internal"},
                    "domain_policy_context": {},
                    "conversation_goal_lifecycle": {
                        "schema_version": "conversation-goal-lifecycle/v1",
                        "owner": "analysis_pipeline",
                        "conversation_ref": open_goal["conversation_ref"],
                        "open_goals": [open_goal],
                    },
                },
            },
        },
        "Please confirm the material.",
        "product_question",
    )

    request_payload = json.loads(client.request["messages"][1]["content"])
    serialized_payload = json.dumps(request_payload, sort_keys=True)
    assert request_payload["open_goal_candidates"] == [{
        "goal_alias": open_goal["goal_alias"],
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
    }]
    assert open_goal["goal_ref"] not in serialized_payload
    assert open_goal["conversation_ref"] not in serialized_payload
    assert open_goal["source_turn_uid"] not in serialized_payload
    assert open_goal["source_span_sha256"] not in serialized_payload
    assert result["conversation_goal_lifecycle"]["continuations"][0][
        "continued_from_goal_ref"
    ] == open_goal["goal_ref"]
