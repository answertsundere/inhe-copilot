from __future__ import annotations

import builtins
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from app.services.analysis_pipeline_service import (
    PIPELINE_COMPOSER_ENTRY_DIAGNOSTICS_SCHEMA,
    AnalysisPipelineRequest,
    AnalysisPipelineService,
)


MUTATION_COVERAGE = {
    "composer_flag_disabled": "test_feature_gates_report_exact_reason",
    "formal_convergence_disabled": "test_feature_gates_report_exact_reason",
    "invalid_or_degraded_understanding": "test_understanding_boundary_skips_composer",
    "authoritative_goal_cardinality": "test_entry_observation_counts_and_domain_status",
    "requested_claim_presence": "test_entry_observation_counts_and_domain_status",
    "resolution_presence": "test_entry_observation_counts_and_domain_status",
    "minimal_context_presence": "test_composer_invocation_and_early_return_capture",
    "domain_pack_status": "test_entry_observation_counts_and_domain_status",
    "composer_service_unavailable": "test_composer_service_unavailable_is_observable",
    "media_or_service_only": "test_media_or_service_only_goal_is_not_counted_as_authoritative",
    "graph_failure": "test_graph_failure_and_finally_diagnostics",
    "response_shape_invalid": "test_invalid_graph_response_shape_is_observable",
    "composer_invocation": "test_composer_invocation_and_early_return_capture",
    "composer_early_return": "test_composer_invocation_and_early_return_capture",
    "privacy_invalid": "test_privacy_and_provenance_reasons_are_forwarded",
    "goal_provenance_invalid": "test_privacy_and_provenance_reasons_are_forwarded",
    "provider_boundary_reached": "test_privacy_and_provenance_reasons_are_forwarded",
    "sink_failure": "test_sink_failure_cannot_change_pipeline_behavior",
    "request_concurrency": "test_request_scoped_sinks_do_not_cross_contaminate",
    "finally_restore": "test_graph_failure_and_finally_diagnostics",
    "unknown_branch": "test_graph_completion_not_observed_is_fail_closed_diagnostic",
    "model_tool_call_equivalence": "test_diagnostics_off_on_are_behaviorally_equivalent",
    "can_send_equivalence": "test_diagnostics_off_on_are_behaviorally_equivalent",
    "final_reply_equivalence": "test_diagnostics_off_on_are_behaviorally_equivalent",
}


@pytest.fixture(autouse=True)
def diagnostic_hmac_key(monkeypatch):
    monkeypatch.setenv(
        "COPILOT_FORMAL_KB_AUDIT_HMAC_KEY",
        "diagnostics-test-key",
    )


def _graph_response(
    *,
    understanding_status: str = "valid",
    goal_count: int = 1,
    requested_count: int | None = None,
    resolution_count: int | None = None,
    selected_count: int = 1,
    admitted_count: int = 1,
    minimal_present: bool = True,
    domain_status: str = "selected",
    goal_kind: str = "customer_goal",
) -> dict:
    requested_count = goal_count if requested_count is None else requested_count
    resolution_count = (
        requested_count if resolution_count is None else resolution_count
    )
    goals = [
        {
            "goal_ref": f"goal-{index}",
            "goal_kind": goal_kind,
            "claim_type": "dimensions",
        }
        for index in range(goal_count)
    ]
    requested = [
        {
            "claim_uid": f"claim-{index}",
            "goal_ref": f"goal-{index}",
            "goal_kind": goal_kind,
            "claim_type": "dimensions",
        }
        for index in range(requested_count)
    ]
    resolutions = [
        {
            "claim_uid": f"claim-{index}",
            "goal_ref": f"goal-{index}",
            "status": "supported",
        }
        for index in range(resolution_count)
    ]
    response = {
        "suggested_reply": "candidate",
        "draft_reply": "candidate",
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
        "reply_status": "needs_human_review",
        "reply_blocks": [],
        "reply_delivery": {
            "mode": "blocked",
            "auto_send_ready": False,
        },
        "recommended_assets": [],
        "turn_understanding": {
            "goal_understanding_status": understanding_status,
            "goal_understanding_diagnostics": (
                []
                if understanding_status == "valid"
                else ["diagnostic_understanding_invalid"]
            ),
            "customer_goals": goals,
            "requested_claims": requested,
        },
        "selected_evidence": [
            {"evidence_uid": f"evidence-{index}"}
            for index in range(selected_count)
        ],
        "evidence_debug": {},
        "trace_steps": [],
    }
    if minimal_present:
        response["minimal_decision_context"] = {
            "requested_claims": requested,
            "claim_resolutions": resolutions,
            "admitted_evidence": [
                {"evidence_uid": f"evidence-{index}"}
                for index in range(admitted_count)
            ],
            "trusted_domain_policy_context": {
                "status": domain_status,
            },
        }
    return response


def _request(
    *,
    sink=None,
    privacy_sink=None,
    request_alias: str = "request_A",
    case_alias: str = "case_A",
) -> AnalysisPipelineRequest:
    if sink is not None:
        sink["request_alias"] = request_alias
        sink["case_alias"] = case_alias
    return AnalysisPipelineRequest(
        customer_message="diagnostic request",
        reply_service=object(),
        source="api",
        composer_entry_diagnostics_sink=sink,
        composer_privacy_diagnostics_sink=privacy_sink,
    )


@pytest.fixture()
def pipeline_environment(monkeypatch):
    import app.services.analysis_execution_service as execution
    import app.services.final_response_orchestrator as final_orchestrator

    calls = {
        "graph": 0,
        "composer": 0,
        "model": 0,
        "tool": 0,
        "final": 0,
    }

    def final(response, **_kwargs):
        calls["final"] += 1
        return deepcopy(response)

    monkeypatch.setattr(
        final_orchestrator,
        "orchestrate_final_response",
        final,
    )
    monkeypatch.setattr(
        AnalysisPipelineService,
        "_apply_media_delivery",
        lambda self, response, _request, _identity: (
            deepcopy(response),
            {"stage": "media_delivery", "status": "disabled"},
        ),
    )
    monkeypatch.setattr(
        AnalysisPipelineService,
        "_attach_shadow_layers",
        lambda self, response, _request, _identity: (
            deepcopy(response),
            [],
        ),
    )
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service."
        "RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {
            "ready": True,
            "status": "ready",
            "reasons": [],
        },
    )

    def install_graph(response: dict):
        def execute_analysis(**kwargs):
            calls["graph"] += 1
            return kwargs["response_post_processor"](
                deepcopy(response)
            )

        monkeypatch.setattr(execution, "execute_analysis", execute_analysis)

    def install_composer(
        *,
        reason: str = "",
        privacy_updates: dict | None = None,
        status: str = "accepted",
        renderable_count: int = 1,
    ):
        def compose(self, response, **kwargs):
            calls["composer"] += 1
            sink = kwargs.get("privacy_diagnostics_sink")
            if isinstance(sink, dict):
                sink.update({
                    "schema_version": (
                        "composer-decision-input-privacy-diagnostics/v1"
                    ),
                    "owner": "model_first_answer_composer",
                    "decision_input_build_attempted": True,
                    "decision_input_build_completed": not bool(reason),
                    "d1_generated": True,
                    "d2_generated": True,
                    "transport_attempted": False,
                    "transport_forwarded": False,
                    **(privacy_updates or {}),
                })
            result = {
                "status": status,
                "rejection_reason": reason,
                "used_for_final_reply": status == "accepted",
                "can_change_can_send": False,
                "input_eligibility": {
                    "renderable_customer_goal_count": renderable_count,
                },
                "provider_diagnostics": {
                    "model_call_count": 0,
                },
            }
            return deepcopy(response), result

        monkeypatch.setattr(
            "app.services.model_first_answer_composer_service."
            "ModelFirstAnswerComposerService.compose",
            compose,
        )

    return calls, install_graph, install_composer


def _enable_composer(monkeypatch) -> None:
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "true",
    )
    monkeypatch.setenv(
        "COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED",
        "true",
    )


def test_mutation_contract_has_all_required_cases():
    assert len(MUTATION_COVERAGE) == 24


@pytest.mark.parametrize(
    ("composer", "convergence", "reason"),
    [
        (False, True, "composer_feature_disabled"),
        (True, False, "formal_evidence_convergence_disabled"),
    ],
)
def test_feature_gates_report_exact_reason(
    pipeline_environment,
    monkeypatch,
    composer,
    convergence,
    reason,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        str(composer).lower(),
    )
    monkeypatch.setenv(
        "COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED",
        str(convergence).lower(),
    )
    sink = {}

    AnalysisPipelineService().run(_request(sink=sink))

    assert sink["exact_reason_code"] == reason
    assert sink["composer_entry_eligible"] is False
    assert sink["composer_invocation_attempted"] is False


@pytest.mark.parametrize("status", ["invalid", "degraded"])
def test_understanding_boundary_skips_composer(
    pipeline_environment,
    monkeypatch,
    status,
):
    calls, install_graph, install_composer = pipeline_environment
    install_graph(_graph_response(understanding_status=status))
    install_composer()
    _enable_composer(monkeypatch)
    sink = {}

    response = AnalysisPipelineService().run(_request(sink=sink))

    assert calls["composer"] == 0
    assert sink["understanding_status"] == status
    assert sink["exact_reason_code"] == (
        "turn_understanding_not_authoritative"
    )
    assert response["can_send"] is False


@pytest.mark.parametrize(
    (
        "goal_count",
        "requested_count",
        "resolution_count",
        "minimal_present",
        "domain_status",
    ),
    [
        (0, 0, 0, False, "missing"),
        (1, 1, 1, True, "selected"),
        (3, 2, 1, True, "invalid"),
    ],
)
def test_entry_observation_counts_and_domain_status(
    pipeline_environment,
    monkeypatch,
    goal_count,
    requested_count,
    resolution_count,
    minimal_present,
    domain_status,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response(
        goal_count=goal_count,
        requested_count=requested_count,
        resolution_count=resolution_count,
        minimal_present=minimal_present,
        domain_status=domain_status,
    ))
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )
    sink = {}

    AnalysisPipelineService().run(_request(sink=sink))

    assert sink["authoritative_customer_goal_count"] == goal_count
    assert sink["requested_claim_count"] == requested_count
    assert sink["claim_resolution_count"] == (
        resolution_count if minimal_present else 0
    )
    assert sink["minimal_context_completed"] is minimal_present
    expected_status = domain_status if minimal_present else "missing"
    assert sink["trusted_domain_pack_status"] == expected_status


@pytest.mark.parametrize("goal_kind", ["service_action", "media_request"])
def test_media_or_service_only_goal_is_not_counted_as_authoritative(
    pipeline_environment,
    monkeypatch,
    goal_kind,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response(goal_kind=goal_kind))
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )
    sink = {}

    AnalysisPipelineService().run(_request(sink=sink))

    assert sink["authoritative_customer_goal_count"] == 0


@pytest.mark.parametrize(
    ("minimal_present", "reason", "renderable_count"),
    [
        (True, "", 2),
        (False, "minimal_decision_context_missing", 0),
    ],
)
def test_composer_invocation_and_early_return_capture(
    pipeline_environment,
    monkeypatch,
    minimal_present,
    reason,
    renderable_count,
):
    calls, install_graph, install_composer = pipeline_environment
    install_graph(_graph_response(
        goal_count=2,
        minimal_present=minimal_present,
    ))
    install_composer(
        reason=reason,
        status="provider_blocked" if reason else "accepted",
        renderable_count=renderable_count,
    )
    _enable_composer(monkeypatch)
    sink = {}
    privacy_sink = {}

    AnalysisPipelineService().run(_request(
        sink=sink,
        privacy_sink=privacy_sink,
    ))

    assert calls["composer"] == 1
    assert sink["composer_service_available"] is True
    assert sink["composer_entry_eligible"] is True
    assert sink["composer_invocation_attempted"] is True
    assert sink["composer_invocation_completed"] is True
    assert sink["minimal_context_attempted"] is True
    assert sink["minimal_context_completed"] is minimal_present
    assert sink["renderable_customer_goal_count"] == renderable_count
    assert sink["exact_reason_code"] == (
        reason or "composer_invocation_completed"
    )
    assert privacy_sink["d1_generated"] is True


@pytest.mark.parametrize(
    ("reason", "privacy_updates"),
    [
        (
            "composer_decision_input_privacy_invalid",
            {
                "privacy_projection_equal": False,
                "diff_total_count": 1,
                "first_diff_path": "$.requested_claims[0].content",
            },
        ),
        (
            "composer_goal_provenance_invalid",
            {"early_return_reason": "composer_goal_provenance_invalid"},
        ),
        (
            "formal_llm_error:ComposerTransportIntercepted",
            {
                "transport_attempted": True,
                "transport_forwarded": False,
            },
        ),
    ],
)
def test_privacy_and_provenance_reasons_are_forwarded(
    pipeline_environment,
    monkeypatch,
    reason,
    privacy_updates,
):
    _calls, install_graph, install_composer = pipeline_environment
    install_graph(_graph_response())
    install_composer(
        reason=reason,
        status="provider_blocked",
        privacy_updates=privacy_updates,
    )
    _enable_composer(monkeypatch)
    sink = {}
    privacy_sink = {}

    AnalysisPipelineService().run(_request(
        sink=sink,
        privacy_sink=privacy_sink,
    ))

    assert sink["exact_reason_code"] == reason
    for key, value in privacy_updates.items():
        assert privacy_sink[key] == value


def test_composer_service_unavailable_is_observable(
    pipeline_environment,
    monkeypatch,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    _enable_composer(monkeypatch)
    sink = {}
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "app.services.model_first_answer_composer_service":
            raise ImportError("diagnostic mutation")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    AnalysisPipelineService().run(_request(sink=sink))

    assert sink["composer_service_available"] is False
    assert sink["composer_service_check_status"] == "unavailable"
    assert sink["exact_reason_code"] == "composer_service_unavailable"


def test_invalid_graph_response_shape_is_observable(
    pipeline_environment,
    monkeypatch,
):
    import app.services.analysis_execution_service as execution

    monkeypatch.setattr(
        execution,
        "execute_analysis",
        lambda **kwargs: kwargs["response_post_processor"]([]),
    )
    sink = {}

    AnalysisPipelineService().run(_request(sink=sink))

    assert sink["graph_completed"] is True
    assert sink["response_shape_valid"] is False
    assert sink["exact_reason_code"] == "graph_response_shape_invalid"


def test_graph_completion_not_observed_is_fail_closed_diagnostic(
    pipeline_environment,
    monkeypatch,
):
    import app.services.analysis_execution_service as execution

    monkeypatch.setattr(
        execution,
        "execute_analysis",
        lambda **_kwargs: deepcopy(_graph_response()),
    )
    sink = {}

    AnalysisPipelineService().run(_request(sink=sink))

    assert sink["graph_completed"] is False
    assert sink["exact_reason_code"] == "graph_completion_not_observed"


def test_graph_failure_and_finally_diagnostics(
    pipeline_environment,
    monkeypatch,
):
    import app.services.analysis_execution_service as execution

    monkeypatch.setattr(
        execution,
        "execute_analysis",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("failure")),
    )
    sink = {}

    with pytest.raises(RuntimeError):
        AnalysisPipelineService().run(_request(sink=sink))

    assert sink["pipeline_entered"] is True
    assert sink["pipeline_completed"] is False
    assert sink["exact_reason_code"] == "graph_execution_failed"
    assert sink["pipeline_elapsed_ms"] >= 0


class _FailingUpdateSink(dict):
    def __init__(self):
        super().__init__()
        self.update_count = 0

    def update(self, *args, **kwargs):
        self.update_count += 1
        if self.update_count > 1:
            raise RuntimeError("sink unavailable")
        return super().update(*args, **kwargs)


def test_sink_failure_cannot_change_pipeline_behavior(
    pipeline_environment,
    monkeypatch,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )

    expected = AnalysisPipelineService().run(_request())
    failing_sink = _FailingUpdateSink()
    actual = AnalysisPipelineService().run(_request(sink=failing_sink))

    assert actual == expected
    assert failing_sink["diagnostics_error_code"] == (
        "diagnostics_sink_update_failed"
    )


def test_request_scoped_sinks_do_not_cross_contaminate(
    pipeline_environment,
    monkeypatch,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )
    sinks = [{}, {}]

    def run(index: int):
        return AnalysisPipelineService().run(_request(
            sink=sinks[index],
            request_alias=f"request_{index}",
            case_alias=f"case_{index}",
        ))

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(run, range(2)))

    assert responses[0] == responses[1]
    request_aliases = [sink["request_alias"] for sink in sinks]
    case_aliases = [sink["case_alias"] for sink in sinks]
    assert len(set(request_aliases)) == 2
    assert len(set(case_aliases)) == 2
    assert all(value.startswith("request_") for value in request_aliases)
    assert all(value.startswith("case_") for value in case_aliases)
    serialized = str(sinks)
    assert "request_0" not in serialized
    assert "request_1" not in serialized
    assert "case_0" not in serialized
    assert "case_1" not in serialized


def test_request_aliases_fail_closed_without_trusted_hmac_key(
    pipeline_environment,
    monkeypatch,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )
    monkeypatch.delenv(
        "COPILOT_FORMAL_KB_AUDIT_HMAC_KEY",
        raising=False,
    )
    monkeypatch.delenv("COPILOT_GOLD_SET_HMAC_KEY", raising=False)
    sink: dict = {}

    response = AnalysisPipelineService().run(_request(
        sink=sink,
        request_alias="1380013",
        case_alias="ORD-7281",
    ))
    serialized = json.dumps(sink, ensure_ascii=False)

    assert response["can_send"] is False
    assert sink["request_alias"] == ""
    assert sink["case_alias"] == ""
    assert sink["diagnostics_error_code"] == (
        "diagnostic_alias_unavailable"
    )
    assert "1380013" not in serialized
    assert "ORD-7281" not in serialized


def test_diagnostics_off_on_are_behaviorally_equivalent(
    pipeline_environment,
    monkeypatch,
):
    calls, install_graph, install_composer = pipeline_environment
    install_graph(_graph_response(goal_count=2))
    install_composer(renderable_count=2)
    _enable_composer(monkeypatch)

    without = AnalysisPipelineService().run(_request())
    calls_without = deepcopy(calls)
    sink = {}
    privacy_sink = {}
    with_diagnostics = AnalysisPipelineService().run(_request(
        sink=sink,
        privacy_sink=privacy_sink,
    ))
    calls_with_delta = {
        key: calls[key] - calls_without[key]
        for key in calls
    }

    assert with_diagnostics == without
    assert calls_with_delta == calls_without
    assert sink["schema_version"] == (
        PIPELINE_COMPOSER_ENTRY_DIAGNOSTICS_SCHEMA
    )
    assert sink["used_for_final_reply"] is False
    assert sink["used_as_evidence"] is False
    assert sink["can_change_can_send"] is False
    assert sink["can_change_model_call_count"] is False
    assert with_diagnostics["can_send"] is False


def test_diagnostics_sink_is_absent_by_default(
    pipeline_environment,
    monkeypatch,
):
    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )

    response = AnalysisPipelineService().run(_request())

    assert "composer_entry_diagnostics" not in response


def test_sink_none_performs_zero_diagnostic_work(
    pipeline_environment,
    monkeypatch,
):
    import app.services.analysis_pipeline_service as pipeline_module

    _calls, install_graph, _install_composer = pipeline_environment
    install_graph(_graph_response())
    monkeypatch.setenv(
        "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
        "false",
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("diagnostics_must_not_run_without_sink")

    for name in (
        "_composer_entry_diagnostic_base",
        "_initialize_composer_entry_diagnostics",
        "_update_composer_entry_diagnostics",
        "_composer_entry_diagnostic_reason",
        "_composer_entry_diagnostic_flag",
        "_diagnostic_alias",
        "_diagnostic_rows",
    ):
        monkeypatch.setattr(pipeline_module, name, unexpected)
    monkeypatch.setattr(
        AnalysisPipelineService,
        "_composer_entry_observation",
        unexpected,
    )
    monkeypatch.setattr(
        pipeline_module.time,
        "perf_counter",
        unexpected,
    )

    response = AnalysisPipelineService().run(_request())

    assert response["can_send"] is False
    assert response["requires_human_review"] is True


def test_full_entry_off_on_call_oracle_is_exactly_equivalent(
    monkeypatch,
):
    import app.services.analysis_execution_service as execution
    import app.services.final_response_orchestrator as final_orchestrator

    counter_names = (
        "turn_understanding_llm",
        "intent_router_llm",
        "customer_state_llm",
        "tool_selection_llm",
        "composer_llm",
        "unified_audit_llm",
        "embedding",
        "rag_retrieval",
        "service_tool",
        "media_tool",
        "formal_knowledge_read",
        "dml_attempt",
        "fallback",
    )
    calls = {name: 0 for name in counter_names}
    payload_hashes: list[str] = []

    def canonical_hash(value):
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def execute_analysis(**kwargs):
        for name in (
            "turn_understanding_llm",
            "intent_router_llm",
            "customer_state_llm",
            "tool_selection_llm",
            "embedding",
            "rag_retrieval",
            "formal_knowledge_read",
        ):
            calls[name] += 1
        payload_hashes.append(canonical_hash({
            "customer_message": kwargs["customer_message"],
            "source": kwargs["source"],
            "scenario": kwargs["scenario"],
            "copilot_context": kwargs["copilot_context"],
        }))
        return kwargs["response_post_processor"](
            deepcopy(_graph_response(goal_count=2))
        )

    def compose(_self, response, **kwargs):
        calls["composer_llm"] += 1
        payload_hashes.append(canonical_hash({
            "customer_message": kwargs["customer_message"],
            "response": response,
        }))
        sink = kwargs.get("privacy_diagnostics_sink")
        if isinstance(sink, dict):
            sink.update({
                "schema_version": (
                    "composer-decision-input-privacy-diagnostics/v1"
                ),
                "can_change_can_send": False,
                "can_change_model_call_count": False,
            })
        return deepcopy(response), {
            "status": "accepted",
            "rejection_reason": "",
            "used_for_final_reply": True,
            "can_change_can_send": False,
            "input_eligibility": {
                "renderable_customer_goal_count": 2,
            },
        }

    def final(response, **_kwargs):
        calls["unified_audit_llm"] += 1
        updated = deepcopy(response)
        updated["final_answer_audit"] = {"passed": True}
        updated["final_semantic_fit_audit"] = {"passed": True}
        return updated

    def media(_self, response, _request, _identity):
        calls["service_tool"] += 1
        calls["media_tool"] += 1
        return deepcopy(response), {
            "stage": "media_delivery",
            "status": "disabled",
        }

    monkeypatch.setattr(execution, "execute_analysis", execute_analysis)
    monkeypatch.setattr(
        "app.services.model_first_answer_composer_service."
        "ModelFirstAnswerComposerService.compose",
        compose,
    )
    monkeypatch.setattr(
        final_orchestrator,
        "orchestrate_final_response",
        final,
    )
    monkeypatch.setattr(
        AnalysisPipelineService,
        "_apply_media_delivery",
        media,
    )
    monkeypatch.setattr(
        AnalysisPipelineService,
        "_attach_shadow_layers",
        lambda _self, response, _request, _identity: (
            deepcopy(response),
            [],
        ),
    )
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service."
        "RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {
            "ready": True,
            "status": "ready",
            "reasons": [],
        },
    )
    _enable_composer(monkeypatch)

    without = AnalysisPipelineService().run(_request())
    calls_without = deepcopy(calls)
    payloads_without = list(payload_hashes)
    sink: dict = {}
    privacy_sink: dict = {}
    with_diagnostics = AnalysisPipelineService().run(_request(
        sink=sink,
        privacy_sink=privacy_sink,
    ))
    calls_with = {
        key: calls[key] - calls_without[key]
        for key in calls
    }
    payloads_with = payload_hashes[len(payloads_without):]

    expected_calls = {
        "turn_understanding_llm": 1,
        "intent_router_llm": 1,
        "customer_state_llm": 1,
        "tool_selection_llm": 1,
        "composer_llm": 1,
        "unified_audit_llm": 1,
        "embedding": 1,
        "rag_retrieval": 1,
        "service_tool": 1,
        "media_tool": 1,
        "formal_knowledge_read": 1,
        "dml_attempt": 0,
        "fallback": 0,
    }
    assert calls_without == expected_calls
    assert calls_with == expected_calls
    assert payloads_with == payloads_without
    assert with_diagnostics == without
    assert with_diagnostics["can_send"] is False
    assert with_diagnostics["requires_human_review"] is True
