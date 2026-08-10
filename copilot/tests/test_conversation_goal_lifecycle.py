from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import semantic_fact_type_service as semantic_service


def _open_goal(
    *,
    alias: str = "open-goal-0123456789abcdef01234567",
    conversation_ref: str = "conversation-0123456789abcdef0123456789abcdef",
) -> dict:
    return {
        "goal_alias": alias,
        "goal_ref": "goal-0123456789abcdef",
        "conversation_ref": conversation_ref,
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "material",
        "policy_intent_kind": "",
        "source_turn_uid": "turn-0123456789abcdef0123",
        "source_span_sha256": "a" * 64,
    }


def _continued_raw_goal(
    source_text: str,
    *,
    alias: str = "open-goal-0123456789abcdef01234567",
) -> dict:
    return {
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": source_text,
        "continued_from": alias,
    }


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
        "policy_goal_family": "material",
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

    old_engine = repository._engine
    if old_engine is not None:
        old_engine.dispose()
    monkeypatch.setattr(repository, "TRACE_DB_PATH", str(tmp_path / "trace.db"))
    monkeypatch.setattr(repository, "_engine", None)
    monkeypatch.setattr(repository, "_SessionLocal", None)
    monkeypatch.setenv(
        repository.CONVERSATION_GOAL_LIFECYCLE_HMAC_ENV,
        "test-goal-lifecycle-secret",
    )
    repository.init_trace_tables()
    yield repository
    if repository._engine is not None:
        repository._engine.dispose()


def test_trace_lifecycle_uses_hmac_identity_and_supersedes_only_on_verified_continuation(
    lifecycle_trace_db,
):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    assert repository.record_conversation_goal_lifecycle(
        "customer-conversation-raw-id",
        [original],
    ) == {"status": "recorded", "write_count": 1}

    loaded, status = repository.load_conversation_goal_lifecycle_context(
        "customer-conversation-raw-id",
    )
    assert status == "loaded"
    assert loaded["conversation_ref"] != "customer-conversation-raw-id"
    assert loaded["open_goals"][0]["goal_ref"] == "goal-0123456789abcdef"
    assert "not persisted" not in str(loaded)

    successor = _canonical_goal(
        goal_ref="goal-fedcba9876543210",
        source_turn_uid="turn-fedcba9876543210fedc",
        source_span_sha256="b" * 64,
    )
    continuation = {
        "goal_ref": "goal-fedcba9876543210",
        "continued_from_goal_ref": "goal-0123456789abcdef",
        "continued_from_alias": loaded["open_goals"][0]["goal_alias"],
        "origin_source_turn_uid": "turn-0123456789abcdef0123",
        "origin_source_span_sha256": "a" * 64,
    }
    result = repository.record_conversation_goal_lifecycle(
        "customer-conversation-raw-id",
        [successor],
        [continuation],
    )
    assert result == {"status": "recorded", "write_count": 2}
    assert repository.record_conversation_goal_lifecycle(
        "customer-conversation-raw-id",
        [successor],
        [continuation],
    ) == {"status": "recorded", "write_count": 0}
    loaded, status = repository.load_conversation_goal_lifecycle_context(
        "customer-conversation-raw-id",
    )
    assert status == "loaded"
    assert [goal["goal_ref"] for goal in loaded["open_goals"]] == [
        "goal-fedcba9876543210"
    ]


def test_lifecycle_rejects_stale_or_cross_conversation_continuation(lifecycle_trace_db):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    repository.record_conversation_goal_lifecycle("conversation-a", [original])
    successor = _canonical_goal(
        goal_ref="goal-fedcba9876543210",
        source_turn_uid="turn-fedcba9876543210fedc",
        source_span_sha256="b" * 64,
    )
    continuation = {
        "goal_ref": "goal-fedcba9876543210",
        "continued_from_goal_ref": "goal-0123456789abcdef",
        "continued_from_alias": "opaque-alias",
        "origin_source_turn_uid": "turn-0123456789abcdef0123",
        "origin_source_span_sha256": "a" * 64,
    }
    assert repository.record_conversation_goal_lifecycle(
        "conversation-b",
        [successor],
        [continuation],
    ) == {"status": "invalid", "write_count": 0}


def test_completed_goal_is_removed_from_open_projection_and_cannot_reopen(
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
    loaded, status = repository.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )
    assert status == "loaded"
    alias = loaded["open_goals"][0]["goal_alias"]

    assert repository.complete_conversation_goal_lifecycle(
        "conversation-a", original["goal_ref"], alias
    ) == {"status": "recorded", "write_count": 1}
    assert repository.complete_conversation_goal_lifecycle(
        "conversation-a", original["goal_ref"], alias
    ) == {"status": "recorded", "write_count": 0}
    loaded, status = repository.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )
    assert status == "loaded"
    assert loaded["open_goals"] == []
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "invalid", "write_count": 0}


def test_completion_requires_current_conversation_alias(lifecycle_trace_db):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    repository.record_conversation_goal_lifecycle("conversation-a", [original])
    assert repository.complete_conversation_goal_lifecycle(
        "conversation-b",
        original["goal_ref"],
        "open-goal-0123456789abcdef01234567",
    ) == {"status": "invalid", "write_count": 0}


def test_copilot_feedback_cannot_complete_an_open_goal(lifecycle_trace_db, monkeypatch):
    """A client feedback record is not a trusted server-side delivery receipt."""
    from flask import Flask

    from app.api import copilot_routes

    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "recorded", "write_count": 1}

    class _FeedbackService:
        def save(self, **kwargs):
            return {"action": kwargs["action"]}

    monkeypatch.setattr(
        copilot_routes,
        "get_feedback_service",
        lambda: _FeedbackService(),
    )
    app = Flask(__name__)
    app.register_blueprint(copilot_routes.copilot_bp)
    response = app.test_client().post(
        "/api/copilot/feedback",
        json={
            "action": "edited",
            "customer_message": "customer message",
            "suggested_reply": "candidate reply",
            "final_reply": "human edited reply",
            "conversation_id": "conversation-a",
        },
    )

    assert response.status_code == 200
    lifecycle, status = repository.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )
    assert status == "loaded"
    assert [item["goal_ref"] for item in lifecycle["open_goals"]] == [
        original["goal_ref"]
    ]


def test_lifecycle_disabled_does_not_initialize_or_write_trace_storage(
    monkeypatch,
):
    from app.tracing import repository

    monkeypatch.delenv(repository.CONVERSATION_GOAL_LIFECYCLE_HMAC_ENV, raising=False)
    monkeypatch.setattr(
        repository,
        "init_trace_tables",
        lambda: pytest.fail("disabled lifecycle accessed trace storage"),
    )

    assert repository.load_conversation_goal_lifecycle_context("conversation-a") == (
        {},
        "disabled",
    )
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", []
    ) == {"status": "disabled", "write_count": 0}
    assert repository.complete_conversation_goal_lifecycle(
        "conversation-a",
        "goal-0123456789abcdef",
        "open-goal-0123456789abcdef01234567",
    ) == {"status": "disabled", "write_count": 0}


def test_lifecycle_keeps_distinct_customer_goals_in_stable_order(lifecycle_trace_db):
    repository = lifecycle_trace_db
    material = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    high_risk = _canonical_goal(
        goal_ref="goal-fedcba9876543210",
        source_turn_uid="turn-fedcba9876543210fedc",
        source_span_sha256="b" * 64,
        claim_type="stability",
    )
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a",
        [high_risk, material],
    ) == {"status": "recorded", "write_count": 2}
    loaded, status = repository.load_conversation_goal_lifecycle_context(
        "conversation-a",
    )
    assert status == "loaded"
    assert sorted(goal["claim_type"] for goal in loaded["open_goals"]) == [
        "material", "stability"
    ]


def test_lifecycle_rejects_premise_dependency_as_a_customer_goal(lifecycle_trace_db):
    repository = lifecycle_trace_db
    dependency = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    dependency["goal_kind"] = "evidence_dependency"
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a",
        [dependency],
    ) == {"status": "invalid", "write_count": 0}


def test_lifecycle_observation_never_changes_delivery_boundary(lifecycle_trace_db):
    from app.services.analysis_pipeline_service import AnalysisPipelineService

    response = {
        "can_send": False,
        "requires_human_review": True,
        "turn_understanding": {
            "goal_understanding_status": "valid",
            "customer_goals": [_canonical_goal(
                goal_ref="goal-0123456789abcdef",
                source_turn_uid="turn-0123456789abcdef0123",
                source_span_sha256="a" * 64,
            )],
        },
    }
    observation = AnalysisPipelineService._record_conversation_goal_lifecycle(
        response,
        type("Request", (), {"conversation_id": "conversation-a"})(),
        {"status": "valid"},
    )
    assert observation == {"status": "recorded", "write_count": 1}
    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["evidence_debug"]["conversation_goal_lifecycle"][
        "can_change_can_send"
    ] is False


def test_pipeline_lifecycle_persists_only_customer_targets(lifecycle_trace_db):
    from app.services.analysis_pipeline_service import AnalysisPipelineService

    target = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
        claim_type="load_capacity",
    )
    premise = deepcopy(target)
    premise["goal_ref"] = "goal-fedcba9876543210"
    premise["goal_kind"] = "evidence_dependency"
    premise["source_turn_uid"] = "turn-fedcba9876543210fedc"
    premise["source_span_sha256"] = "b" * 64
    premise["source_text_sha256"] = "b" * 64
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
        type("Request", (), {"conversation_id": "conversation-a"})(),
        {"status": "valid"},
    )
    loaded, status = lifecycle_trace_db.load_conversation_goal_lifecycle_context(
        "conversation-a"
    )

    assert observation == {"status": "recorded", "write_count": 1}
    assert status == "loaded"
    assert [item["goal_ref"] for item in loaded["open_goals"]] == [
        target["goal_ref"]
    ]
    assert response["can_send"] is False


def test_pipeline_removes_public_lifecycle_and_injects_only_server_projection(
    lifecycle_trace_db,
):
    from app.services.analysis_pipeline_service import (
        AnalysisPipelineRequest,
        AnalysisPipelineService,
    )

    repository = lifecycle_trace_db
    repository.record_conversation_goal_lifecycle(
        "conversation-a",
        [_canonical_goal(
            goal_ref="goal-0123456789abcdef",
            source_turn_uid="turn-0123456789abcdef0123",
            source_span_sha256="a" * 64,
        )],
    )
    prepared = AnalysisPipelineService()._prepare_request(AnalysisPipelineRequest(
        customer_message="What is the material?",
        reply_service=object(),
        conversation_id="conversation-a",
        copilot_context={
            "conversation_goal_lifecycle": {
                "schema_version": "forged",
                "open_goals": [{"goal_alias": "attacker"}],
            },
        },
    ))

    assert "conversation_goal_lifecycle" not in prepared.copilot_context
    owner_context = prepared.copilot_context[
        "_answer_eligibility_owner_context"
    ]
    lifecycle = owner_context["conversation_goal_lifecycle"]
    assert lifecycle["open_goals"][0]["goal_ref"] == "goal-0123456789abcdef"
    assert lifecycle["open_goals"][0]["goal_alias"] != "attacker"


def test_provider_projection_exposes_only_opaque_aliases(monkeypatch):
    captured: dict = {}
    current_message = "What is the material?"

    class _Message:
        content = (
            '{"goals":[{"goal_kind":"customer_goal",'
            '"claim_type_status":"canonical","claim_type":"material",'
            '"attribute_key":"","semantic_key":"",'
            '"policy_intent_ref":"","source_text":"What is the material?"}]}'
        )

    class _Choice:
        message = _Message()
        finish_reason = "stop"

    class _Response:
        choices = [_Choice()]

    class _Client:
        api_key = "test-key"
        model = "test-model"

        def create_chat_completion(self, **kwargs):
            captured.update(kwargs)
            return _Response()

    lifecycle = {
        "schema_version": "conversation-goal-lifecycle/v1",
        "owner": "analysis_pipeline",
        "conversation_ref": "conversation-0123456789abcdef0123456789abcdef",
        "open_goals": [_open_goal()],
    }
    owner_context = {
        "schema_version": "answer-eligibility-owner-context/v1",
        "source": "server_configuration",
        "owner": "analysis_pipeline",
        "provenance": {"boundary": "analysis_pipeline_internal"},
        "conversation_goal_lifecycle": lifecycle,
    }
    monkeypatch.setattr(semantic_service, "get_llm_client", lambda: _Client())

    result = semantic_service._classify_with_llm(
        {
            "customer_message": current_message,
            "intent": "product_question",
            "copilot_context": {
                "_answer_eligibility_owner_context": owner_context,
            },
        },
        current_message,
        "product_question",
    )

    assert result and result["goal_understanding_status"] == "valid"
    payload = __import__("json").loads(captured["messages"][1]["content"])
    assert payload["open_goal_candidates"] == [{
        key: _open_goal()[key]
        for key in (
            "goal_alias",
            "goal_kind",
            "claim_type_status",
            "claim_type",
            "attribute_key",
            "semantic_key",
            "policy_intent_ref",
            "policy_goal_family",
            "policy_intent_kind",
        )
    }]
    assert "goal_ref" not in str(payload["open_goal_candidates"])
    assert "conversation_ref" not in str(payload["open_goal_candidates"])


def test_open_goal_alias_can_continue_only_with_current_turn_provenance():
    current_message = "What is the material?"
    continuations: list[dict] = []

    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [_continued_raw_goal(current_message)],
        message=current_message,
        open_goal_candidates=[_open_goal()],
        lifecycle_continuations_sink=continuations,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 1
    assert goals[0]["claim_type"] == "material"
    assert goals[0]["source"] == "current_customer_message"
    assert goals[0]["source_turn_uid"] != "turn-0123456789abcdef0123"
    assert continuations == [{
        "goal_ref": goals[0]["goal_ref"],
        "continued_from_goal_ref": "goal-0123456789abcdef",
        "continued_from_alias": "open-goal-0123456789abcdef01234567",
        "origin_source_turn_uid": "turn-0123456789abcdef0123",
        "origin_source_span_sha256": "a" * 64,
    }]


def test_continued_and_new_customer_goals_coexist_in_source_order():
    message = "What material is it? What are the dimensions?"
    material = _continued_raw_goal("What material is it?")
    dimensions = {
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "dimensions",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": "What are the dimensions?",
    }

    forward, forward_status, forward_diagnostics = (
        semantic_service._sanitize_customer_goals(
            [material, dimensions],
            message=message,
            open_goal_candidates=[_open_goal()],
        )
    )
    reverse, reverse_status, reverse_diagnostics = (
        semantic_service._sanitize_customer_goals(
            [dimensions, material],
            message=message,
            open_goal_candidates=[_open_goal()],
        )
    )

    assert forward_status == reverse_status == "valid"
    assert forward_diagnostics == reverse_diagnostics == []
    assert [goal["claim_type"] for goal in forward] == [
        "material",
        "dimensions",
    ]
    assert [goal["claim_type"] for goal in reverse] == [
        "material",
        "dimensions",
    ]


@pytest.mark.parametrize("mutation", [
    {"continued_from": "unknown-goal"},
    {"claim_type": "dimensions"},
    {"goal_kind": "service_action"},
])
def test_forged_or_mutated_open_goal_reference_fails_closed(mutation):
    current_message = "What is the material?"
    raw = _continued_raw_goal(current_message)
    raw.update(mutation)

    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [raw],
        message=current_message,
        open_goal_candidates=[_open_goal()],
    )

    assert goals == []
    assert status == "invalid"
    assert diagnostics


def test_duplicate_continuation_alias_fails_closed():
    message = "first material request; second material request"
    first = _continued_raw_goal("first material request")
    second = _continued_raw_goal("second material request")
    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [first, second],
        message=message,
        open_goal_candidates=[_open_goal()],
    )

    assert goals == []
    assert status == "invalid"
    assert "conversation_goal_lifecycle_alias_duplicate" in diagnostics


def test_stale_continuation_cannot_reopen_a_superseded_goal(lifecycle_trace_db):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    repository.record_conversation_goal_lifecycle("conversation-a", [original])
    loaded, _ = repository.load_conversation_goal_lifecycle_context("conversation-a")
    successor = _canonical_goal(
        goal_ref="goal-fedcba9876543210",
        source_turn_uid="turn-fedcba9876543210fedc",
        source_span_sha256="b" * 64,
    )
    first_continuation = {
        "goal_ref": successor["goal_ref"],
        "continued_from_goal_ref": original["goal_ref"],
        "continued_from_alias": loaded["open_goals"][0]["goal_alias"],
        "origin_source_turn_uid": original["source_turn_uid"],
        "origin_source_span_sha256": original["source_span_sha256"],
    }
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [successor], [first_continuation]
    )["status"] == "recorded"
    reopened = _canonical_goal(
        goal_ref="goal-1111111111111111",
        source_turn_uid="turn-11111111111111111111",
        source_span_sha256="c" * 64,
    )
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a",
        [reopened],
        [{
            "goal_ref": reopened["goal_ref"],
            "continued_from_goal_ref": original["goal_ref"],
            "continued_from_alias": first_continuation["continued_from_alias"],
            "origin_source_turn_uid": original["source_turn_uid"],
            "origin_source_span_sha256": original["source_span_sha256"],
        }],
    ) == {"status": "invalid", "write_count": 0}


def test_existing_goal_ref_cannot_change_semantics_or_provenance(lifecycle_trace_db):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "recorded", "write_count": 1}

    changed = deepcopy(original)
    changed["claim_type"] = "dimensions"
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [changed]
    ) == {"status": "invalid", "write_count": 0}

    altered_provenance = deepcopy(original)
    altered_provenance["source_span_sha256"] = "b" * 64
    altered_provenance["source_text_sha256"] = "b" * 64
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [altered_provenance]
    ) == {"status": "invalid", "write_count": 0}


def test_superseded_goal_ref_cannot_be_reopened_without_valid_continuation(
    lifecycle_trace_db,
):
    repository = lifecycle_trace_db
    original = _canonical_goal(
        goal_ref="goal-0123456789abcdef",
        source_turn_uid="turn-0123456789abcdef0123",
        source_span_sha256="a" * 64,
    )
    repository.record_conversation_goal_lifecycle("conversation-a", [original])
    loaded, _ = repository.load_conversation_goal_lifecycle_context("conversation-a")
    successor = _canonical_goal(
        goal_ref="goal-fedcba9876543210",
        source_turn_uid="turn-fedcba9876543210fedc",
        source_span_sha256="b" * 64,
    )
    continuation = {
        "goal_ref": successor["goal_ref"],
        "continued_from_goal_ref": original["goal_ref"],
        "continued_from_alias": loaded["open_goals"][0]["goal_alias"],
        "origin_source_turn_uid": original["source_turn_uid"],
        "origin_source_span_sha256": original["source_span_sha256"],
    }
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [successor], [continuation]
    )["status"] == "recorded"
    assert repository.record_conversation_goal_lifecycle(
        "conversation-a", [original]
    ) == {"status": "invalid", "write_count": 0}


def test_open_goal_is_not_locally_reintroduced_when_provider_omits_it():
    current_message = "Please also tell me the dimensions."
    raw = {
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "dimensions",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": current_message,
    }

    goals, status, diagnostics = semantic_service._sanitize_customer_goals(
        [raw],
        message=current_message,
        open_goal_candidates=[_open_goal()],
    )

    assert status == "valid"
    assert diagnostics == []
    assert [goal["claim_type"] for goal in goals] == ["dimensions"]


def test_lifecycle_context_rejects_closed_cross_conversation_and_duplicate_aliases():
    from app.services.canonical_conversation_turn_service import (
        normalize_trusted_conversation_goal_lifecycle_context,
    )

    base = {
        "schema_version": "conversation-goal-lifecycle/v1",
        "owner": "analysis_pipeline",
        "conversation_ref": "conversation-0123456789abcdef0123456789abcdef",
        "open_goals": [_open_goal()],
    }
    assert normalize_trusted_conversation_goal_lifecycle_context(base) == base

    closed = deepcopy(base)
    closed["open_goals"][0]["status"] = "completed"
    assert normalize_trusted_conversation_goal_lifecycle_context(closed) == {}

    cross_conversation = deepcopy(base)
    cross_conversation["open_goals"][0]["conversation_ref"] = (
        "conversation-fedcba9876543210fedcba9876543210"
    )
    assert normalize_trusted_conversation_goal_lifecycle_context(cross_conversation) == {}

    duplicate = deepcopy(base)
    duplicate["open_goals"].append(deepcopy(duplicate["open_goals"][0]))
    assert normalize_trusted_conversation_goal_lifecycle_context(duplicate) == {}
