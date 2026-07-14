from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.analysis_pipeline_service import AnalysisPipelineRequest, AnalysisPipelineService


_DECISION_FIELDS = (
    "suggested_reply",
    "sendable_reply",
    "can_send",
    "requires_human_review",
    "reply_blocks",
    "reply_delivery",
    "recommended_assets",
)


def _graph_response() -> dict:
    return {
        "intent": "installation",
        "suggested_reply": "请参考安装说明。",
        "requires_human_review": False,
        "can_send": True,
        "sendable_reply": "请参考安装说明。",
        "context_used": {"product_context_pack": {}},
        "execution_debug": {},
        "evidence_debug": {"query_fact_type": "installation"},
        "trace_steps": [],
    }


@pytest.fixture()
def pipeline_harness(monkeypatch):
    import app.services.analysis_execution_service as execution
    import app.services.final_response_orchestrator as final_orchestrator
    import app.services.media_asset_service as media

    calls = {"final": 0}

    def fake_execute_analysis(**kwargs):
        return kwargs["response_post_processor"](deepcopy(_graph_response()))

    def fake_final(response, **kwargs):
        calls["final"] += 1
        result = deepcopy(response)
        result.update(
            {
                "draft_reply": result["suggested_reply"],
                "sendable_reply": result["suggested_reply"],
                "can_send": True,
                "requires_human_review": False,
                "reply_status": "sendable",
                "final_response_pipeline": {"version": "final-response-orchestrator-v1"},
            }
        )
        return result

    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)
    monkeypatch.setattr(final_orchestrator, "orchestrate_final_response", fake_final)
    monkeypatch.setattr(
        media,
        "recommend_for_analyze_response",
        lambda *args, **kwargs: {"recommended_assets": [], "priority_types": [], "has_unapproved": False},
    )
    monkeypatch.setattr(media, "select_delivery_assets", lambda assets, **kwargs: list(assets))
    monkeypatch.setattr(
        media,
        "build_reply_blocks",
        lambda reply, assets, **kwargs: {
            "reply_blocks": [{"type": "text", "content": reply, "send_mode": "auto_when_platform_connected"}],
            "reply_delivery": {"mode": "blocks", "auto_send_ready": False, "reason": "no_media_block"},
        },
    )
    return calls


def _request(source: str) -> AnalysisPipelineRequest:
    return AnalysisPipelineRequest(
        reply_service=object(),
        customer_message="如何安装",
        delivery_message="如何安装",
        conversation_id="pipeline-contract",
        product_name="示例商品",
        product_candidates=[{"type": "sku_code", "value": "SKU-CANONICAL"}],
        copilot_context={"sku_code": "SKU-CANONICAL"},
        source=source,
    )


def test_same_canonical_payload_keeps_core_decision_for_all_entrypoints(pipeline_harness):
    service = AnalysisPipelineService()
    decisions = [service.run(_request(source)) for source in ("api", "copilot", "agent_benchmark", "real_conversation_eval")]

    expected = {field: decisions[0].get(field) for field in _DECISION_FIELDS}
    for decision in decisions:
        assert {field: decision.get(field) for field in _DECISION_FIELDS} == expected
        assert decision["analysis_pipeline"]["final_orchestration_completed"] is True
        assert decision["analysis_pipeline"]["stages"]
        assert {
            stage["stage"] for stage in decision["analysis_pipeline"]["stages"]
        } >= {
            "canonical_input",
            "graph_execution",
            "media_delivery",
            "final_response_orchestration",
            "answer_memory_shadow",
            "grounded_reasoning_shadow",
        }
    assert pipeline_harness["final"] == 4


def test_final_orchestration_runs_once_for_one_pipeline_request(pipeline_harness):
    response = AnalysisPipelineService().run(_request("api"))

    assert response["analysis_pipeline"]["final_orchestration_completed"] is True
    assert pipeline_harness["final"] == 1


def test_media_exception_degrades_without_sendable_media(monkeypatch, pipeline_harness):
    import app.services.media_asset_service as media

    monkeypatch.setattr(media, "recommend_for_analyze_response", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("media unavailable")))

    response = AnalysisPipelineService().run(_request("api"))

    assert response["recommended_assets"] == []
    assert response["reply_delivery"]["auto_send_ready"] is False
    assert response["evidence_debug"]["analysis_pipeline_media_error"]["type"] == "RuntimeError"


def test_final_failure_disables_auto_media_delivery(monkeypatch, pipeline_harness):
    import app.services.final_response_orchestrator as final_orchestrator
    import app.services.media_asset_service as media

    monkeypatch.setattr(
        final_orchestrator,
        "orchestrate_final_response",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("final failed")),
    )
    monkeypatch.setattr(
        media,
        "recommend_for_analyze_response",
        lambda *args, **kwargs: {"recommended_assets": [{"asset_type": "install_video", "asset_url": "https://example.com/install.mp4"}]},
    )
    monkeypatch.setattr(media, "select_delivery_assets", lambda assets, **kwargs: list(assets))
    monkeypatch.setattr(
        media,
        "build_reply_blocks",
        lambda reply, assets, **kwargs: {
            "reply_blocks": [
                {"type": "text", "content": reply},
                {"type": "video", "url": "https://example.com/install.mp4", "send_mode": "auto_when_platform_connected"},
            ],
            "reply_delivery": {"mode": "blocks", "auto_send_ready": True},
        },
    )

    response = AnalysisPipelineService().run(_request("api"))

    assert response["analysis_pipeline"]["final_orchestration_completed"] is False
    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["sendable_reply"] == ""
    assert response["reply_status"] == "needs_human_review"
    assert response["reply_delivery"] == {
        "mode": "blocks",
        "auto_send_ready": False,
        "reason": "final_orchestration_failed",
    }
    assert response["reply_blocks"][1]["send_mode"] == "manual"


def test_pipeline_does_not_retry_after_post_processor_failure(monkeypatch):
    import app.services.analysis_execution_service as execution

    calls = {"complete": 0}
    service = AnalysisPipelineService()

    def fail_complete(response, request):
        calls["complete"] += 1
        raise RuntimeError("post processor failed")

    def fake_execute_analysis(**kwargs):
        try:
            kwargs["response_post_processor"](deepcopy(_graph_response()))
        except RuntimeError:
            return {
                **_graph_response(),
                "can_send": False,
                "requires_human_review": True,
                "sendable_reply": "",
                "reply_status": "needs_human_review",
                "trace_response_stage": "pre_final",
                "evidence_debug": {"analysis_pipeline_post_processor_error": {"type": "RuntimeError"}},
            }
        raise AssertionError("test double must execute response_post_processor")

    monkeypatch.setattr(service, "_complete_response", fail_complete)
    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)

    response = service.run(_request("api"))

    assert calls["complete"] == 1
    assert response["trace_response_stage"] == "pre_final"
    assert response["can_send"] is False
    assert response["sendable_reply"] == ""


def test_shadow_layers_do_not_change_formal_decision(monkeypatch, pipeline_harness):
    import app.services.answer_memory_adapter_service as answer_memory
    import app.services.grounded_reasoning_draft_service as grounded

    class FakeAnswerMemory:
        def attach_shadow_guidance(self, response, **kwargs):
            response = deepcopy(response)
            response["answer_memory_guidance"] = {"reference_only": True, "used_for_fact": False}
            return response

    class FakeGroundedReasoning:
        def attach_shadow_draft(self, response, **kwargs):
            response = deepcopy(response)
            response["grounded_reasoning_draft"] = {"used_for_final_reply": False, "can_change_can_send": False}
            return response

    monkeypatch.setenv("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED", "true")
    monkeypatch.setattr(answer_memory, "AnswerMemoryAdapterService", FakeAnswerMemory)
    monkeypatch.setattr(grounded, "GroundedReasoningDraftService", FakeGroundedReasoning)

    response = AnalysisPipelineService().run(_request("api"))

    assert response["answer_memory_guidance"]["used_for_fact"] is False
    assert response["grounded_reasoning_draft"]["used_for_final_reply"] is False
    assert response["grounded_reasoning_draft"]["can_change_can_send"] is False
    assert response["can_send"] is True


def test_shadow_contract_restores_malicious_formal_mutations(monkeypatch, pipeline_harness):
    import app.services.answer_memory_adapter_service as answer_memory
    import app.services.grounded_reasoning_draft_service as grounded

    class MutatingAnswerMemory:
        def attach_shadow_guidance(self, response, **kwargs):
            response["suggested_reply"] = "mutated"
            response["can_send"] = False
            response["reply_blocks"] = [{"type": "image", "url": "https://example.com/unsafe.png"}]
            response["answer_memory_guidance"] = {"reference_only": True}
            return response

    class MutatingGroundedReasoning:
        def attach_shadow_draft(self, response, **kwargs):
            response["sendable_reply"] = "mutated"
            response["reply_delivery"] = {"auto_send_ready": True}
            response["grounded_reasoning_draft"] = {"used_for_final_reply": False}
            return response

    monkeypatch.setenv("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED", "true")
    monkeypatch.setattr(answer_memory, "AnswerMemoryAdapterService", MutatingAnswerMemory)
    monkeypatch.setattr(grounded, "GroundedReasoningDraftService", MutatingGroundedReasoning)

    response = AnalysisPipelineService().run(_request("api"))

    assert response["suggested_reply"] == _graph_response()["suggested_reply"]
    assert response["can_send"] is True
    assert response["sendable_reply"] == _graph_response()["suggested_reply"]
    assert response["reply_blocks"][0]["type"] == "text"
    violations = response["evidence_debug"]["shadow_contract_violation"]
    assert {item["stage"] for item in violations} == {
        "answer_memory_shadow",
        "grounded_reasoning_shadow",
    }


def test_llm_decision_shadow_cannot_change_formal_decision(monkeypatch, pipeline_harness):
    import app.services.agent_decision_proposal_service as decision

    class MutatingDecisionProposal:
        def attach_shadow_decision(self, response, **kwargs):
            response["suggested_reply"] = "shadow changed reply"
            response["can_send"] = False
            response.setdefault("evidence_debug", {})["llm_decision_proposal"] = {
                "used_for_final_reply": False,
                "can_change_can_send": False,
            }
            return response

    monkeypatch.setenv("COPILOT_LLM_DECISION_SHADOW_ENABLED", "true")
    monkeypatch.setattr(decision, "AgentDecisionProposalService", MutatingDecisionProposal)

    response = AnalysisPipelineService().run(_request("api"))

    assert response["suggested_reply"] == _graph_response()["suggested_reply"]
    assert response["can_send"] is True
    assert response["evidence_debug"]["llm_decision_proposal"]["used_for_final_reply"] is False
    violations = response["evidence_debug"]["shadow_contract_violation"]
    assert any(item["stage"] == "llm_decision_shadow" for item in violations)


def test_benchmark_and_replay_delegate_to_pipeline(monkeypatch):
    from app.services.agent_benchmark_runner_service import AgentBenchmarkRunnerService
    from app.services.real_conversation_replay_service import RealConversationReplayService
    import app.services.analysis_pipeline_service as pipeline_module

    requests = []

    def fake_run(self, request):
        requests.append(request)
        return {"suggested_reply": "draft", "can_send": False, "requires_human_review": True}

    monkeypatch.setattr(pipeline_module.AnalysisPipelineService, "run", fake_run)
    monkeypatch.setattr("app.main.get_reply_service", lambda: object())

    AgentBenchmarkRunnerService()._call_agent({"message": "benchmark", "copilot_context": {}})
    RealConversationReplayService()._call_agent({"message": "replay", "copilot_context": {}})

    assert [request.source for request in requests] == ["agent_benchmark", "real_conversation_eval"]


def test_http_entrypoints_delegate_to_pipeline(monkeypatch):
    from app.main import create_app
    import app.services.analysis_pipeline_service as pipeline_module

    requests = []

    def fake_run(self, request):
        requests.append(request)
        return {
            "suggested_reply": "draft",
            "draft_reply": "draft",
            "sendable_reply": "",
            "can_send": False,
            "requires_human_review": True,
            "reply_status": "needs_human_review",
            "reply_blocks": [{"type": "text", "content": "draft"}],
            "reply_delivery": {"mode": "blocks", "auto_send_ready": False},
            "recommended_assets": [],
            "evidence_debug": {},
            "execution_debug": {},
            "trace_steps": [],
        }

    monkeypatch.setattr(pipeline_module.AnalysisPipelineService, "run", fake_run)
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    assert client.post("/api/analyze", json={"message": "test"}).status_code == 200
    assert client.post(
        "/api/copilot/context",
        json={"customer_message": "test", "source": "copilot_test"},
    ).status_code == 200

    assert [request.source for request in requests] == ["api", "copilot_test"]
