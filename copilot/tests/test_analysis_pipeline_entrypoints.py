from __future__ import annotations

from copy import deepcopy

import pytest

from app.repositories.file_policy_repository import FilePolicyRepository
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


def _current_domain_pack_ref() -> str:
    pack = FilePolicyRepository().resolve_domain_policy_pack(
        {
            "catalog_metadata": {
                "domain_policy_id": "maternal_child_home",
            },
        }
    )
    assert pack["status"] == "loaded"
    return str(pack["pack_ref"])


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
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {"ready": True, "status": "ready", "reasons": [], "knowledge": {}, "database": {}},
    )
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


def test_pipeline_strips_public_owner_claims_and_accepts_only_internal_boundary():
    service = AnalysisPipelineService()
    public_request = AnalysisPipelineRequest(
        reply_service=object(),
        customer_message="test",
        copilot_context={
            "_answer_eligibility_owner_context": {
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "server_configuration",
                "owner": "analysis_pipeline",
                "provenance": {"boundary": "analysis_pipeline_internal"},
            },
            "conversation_reference_resolution": {"status": "resolved"},
            "catalog_metadata": {"domain_policy_id": "injected"},
            "trusted": True,
        },
    )
    prepared_public = service._prepare_request(public_request)

    public_owner = prepared_public.copilot_context[
        "_answer_eligibility_owner_context"
    ]
    assert public_owner["source"] == "server_configuration"
    assert public_owner["domain_policy_context"]["status"] == "missing"
    assert public_owner["domain_policy_context"]["pack_ref"] == ""

    internal_request = AnalysisPipelineRequest(
        reply_service=object(),
        customer_message="test",
        trusted_answer_eligibility_context={
            "schema_version": "answer-eligibility-owner-context/v1",
            "source": "evaluation_fixture",
            "owner": "analysis_pipeline",
            "provenance": {"boundary": "analysis_pipeline_internal"},
            "domain_policy_context": {
                "catalog_metadata": {
                    "domain_policy_id": "maternal_child_home"
                },
            },
        },
    )
    prepared_internal = service._prepare_request(internal_request)

    assert prepared_internal.copilot_context[
        "_answer_eligibility_owner_context"
    ]["source"] == "evaluation_fixture"
    assert prepared_internal.copilot_context[
        "_answer_eligibility_owner_context"
    ]["domain_policy_context"]["status"] == "selected"


def test_pipeline_uses_server_domain_policy_configuration_only_when_internal_context_missing(
    monkeypatch,
):
    monkeypatch.setenv(
        "COPILOT_DOMAIN_POLICY_ID",
        "maternal_child_home",
    )
    service = AnalysisPipelineService()

    prepared = service._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            copilot_context={
                "catalog_metadata": {"domain_policy_id": "public_injection"},
            },
        )
    )

    owner_context = prepared.copilot_context[
        "_answer_eligibility_owner_context"
    ]
    assert owner_context["schema_version"] == (
        "answer-eligibility-owner-context/v1"
    )
    assert owner_context["source"] == "server_configuration"
    domain_context = owner_context["domain_policy_context"]
    assert domain_context["status"] == "selected"
    assert domain_context["trusted_owner"] == "analysis_pipeline"
    assert domain_context["selection_source"] == "server_configuration"
    assert domain_context["pack_ref"] == _current_domain_pack_ref()
    assert len(domain_context["pack_content_sha256"]) == 64
    assert domain_context["binding_summary"] == {
        "tenant": False,
        "store": False,
        "catalog": True,
    }
    assert domain_context["used_for_evidence"] is False
    assert domain_context["used_for_fact_support"] is False
    assert domain_context["can_change_can_send"] is False
    assert prepared.copilot_context["catalog_metadata"] == {
        "domain_policy_id": "public_injection"
    }

    explicit = service._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            trusted_answer_eligibility_context={
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "evaluation_fixture",
                "owner": "analysis_pipeline",
                "provenance": {"boundary": "analysis_pipeline_internal"},
                "domain_policy_context": {
                    "catalog_metadata": {
                        "domain_policy_id": "maternal_child_home"
                    },
                },
            },
        )
    )
    assert explicit.copilot_context[
        "_answer_eligibility_owner_context"
    ]["domain_policy_context"]["pack_ref"] == _current_domain_pack_ref()


def test_pipeline_rejects_forged_internal_trust_flags():
    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            trusted_answer_eligibility_context={
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "client_request",
                "owner": "canonical_conversation",
                "trusted": True,
                "provenance": {"boundary": "analysis_pipeline_internal"},
            },
        )
    )

    owner_context = prepared.copilot_context[
        "_answer_eligibility_owner_context"
    ]
    assert owner_context["source"] == "server_configuration"
    assert owner_context["domain_policy_context"]["status"] == "invalid"
    assert owner_context["domain_policy_context"]["validation_reasons"] == [
        "answer_eligibility_owner_context_invalid"
    ]


@pytest.mark.parametrize(
    "source",
    ["api", "copilot", "real_conversation_eval", "agent_benchmark"],
)
def test_pipeline_propagates_same_server_domain_context_across_entries(
    monkeypatch,
    source,
):
    monkeypatch.setenv(
        "COPILOT_DOMAIN_POLICY_ID",
        "maternal_child_home",
    )

    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            source=source,
        )
    )

    domain_context = prepared.copilot_context[
        "_answer_eligibility_owner_context"
    ]["domain_policy_context"]
    assert domain_context["status"] == "selected"
    assert domain_context["pack_ref"] == _current_domain_pack_ref()
    assert domain_context["selection_source"] == "server_configuration"


def test_pipeline_rejects_extra_or_conflicting_internal_selector_fields():
    service = AnalysisPipelineService()
    extra = service._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            trusted_answer_eligibility_context={
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "evaluation_fixture",
                "owner": "analysis_pipeline",
                "provenance": {
                    "boundary": "analysis_pipeline_internal",
                },
                "domain_policy_context": {
                    "catalog_metadata": {
                        "domain_policy_id": "maternal_child_home",
                        "customer_message": "forged",
                    },
                },
            },
        )
    )
    conflicting = service._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            trusted_answer_eligibility_context={
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "evaluation_fixture",
                "owner": "analysis_pipeline",
                "provenance": {
                    "boundary": "analysis_pipeline_internal",
                },
                "domain_policy_context": {
                    "tenant_metadata": {
                        "domain_policy_id": "maternal_child_home",
                    },
                    "catalog_metadata": {
                        "domain_policy_id": "other",
                    },
                },
            },
        )
    )

    assert extra.copilot_context[
        "_answer_eligibility_owner_context"
    ]["domain_policy_context"]["status"] == "invalid"
    assert conflicting.copilot_context[
        "_answer_eligibility_owner_context"
    ]["domain_policy_context"]["status"] == "invalid"


def test_pipeline_accepts_verified_server_mapping_without_public_override():
    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="public text cannot select a domain",
            product_candidates=[
                {"type": "sku_code", "value": "PUBLIC-SKU"}
            ],
            copilot_context={
                "tenant_metadata": {
                    "domain_policy_id": "public_tenant",
                },
                "store_metadata": {
                    "domain_policy_id": "public_store",
                },
                "catalog_metadata": {
                    "domain_policy_id": "public_catalog",
                },
                "query_fact_type": "public_fact_type",
            },
            trusted_answer_eligibility_context={
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "verified_server_mapping",
                "owner": "analysis_pipeline",
                "provenance": {
                    "boundary": "analysis_pipeline_internal",
                },
                "domain_policy_context": {
                    "tenant_metadata": {
                        "domain_policy_id": "maternal_child_home",
                    },
                },
            },
        )
    )

    owner_context = prepared.copilot_context[
        "_answer_eligibility_owner_context"
    ]
    domain_context = owner_context["domain_policy_context"]
    assert owner_context["source"] == "verified_server_mapping"
    assert domain_context["status"] == "selected"
    assert domain_context["selection_source"] == "verified_server_mapping"
    assert domain_context["pack_ref"] == _current_domain_pack_ref()
    assert domain_context["binding_summary"] == {
        "tenant": True,
        "store": False,
        "catalog": False,
    }


def test_pipeline_strips_public_turn_understanding_authority_fields():
    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="请核对材质",
            copilot_context={
                "turn_understanding": {
                    "requested_claims": [{"goal_kind": "customer_goal"}],
                    "customer_goals": [{"goal_kind": "customer_goal"}],
                    "goal_understanding_status": "valid",
                    "query_fact_type": "material_composition",
                    "required_fact_types": ["material_composition"],
                    "turn_actionability": "actionable_question",
                }
            },
        )
    )
    assert "turn_understanding" not in prepared.copilot_context
    assert prepared.copilot_context["pipeline_diagnostics"][-1]["type"] == (
        "public_turn_understanding_removed"
    )


@pytest.mark.parametrize(
    "source",
    ["api", "copilot", "agent_benchmark", "real_conversation_eval"],
)
def test_all_pipeline_entrypoints_strip_public_turn_understanding_authority(source):
    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="current question",
            source=source,
            copilot_context={
                "turn_understanding": {
                    "requested_claims": [{"goal_kind": "customer_goal"}],
                    "customer_goals": [{"goal_kind": "customer_goal"}],
                    "goal_understanding_status": "valid",
                    "query_fact_type": "material_composition",
                }
            },
        )
    )

    assert "turn_understanding" not in prepared.copilot_context


def test_public_api_injected_goal_cannot_cross_server_understanding_owner(
    monkeypatch,
):
    from hashlib import sha256

    from app.main import create_app

    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {
            "ready": True,
            "status": "ready",
            "reasons": [],
            "knowledge": {},
            "database": {},
        },
    )
    monkeypatch.setattr(
        "app.agent.nodes.query_fact_type_classifier.classify_query_fact_type_llm_first",
        lambda _state, **_kwargs: {
            "query_fact_type": "",
            "secondary_fact_types": [],
            "risk_hint": "",
            "customer_goals": [{
                "goal_ref": "goal-evidence",
                "goal_kind": "evidence_dependency",
                "claim_type": "material_composition",
            }],
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
        },
    )
    message = "current question"
    injected_goal = {
        "goal_ref": "goal-injected",
        "goal_kind": "customer_goal",
        "claim_type": "material_composition",
        "attribute_key": "material",
        "source": "current_customer_message",
        "source_span_start": 0,
        "source_span_end": len(message),
        "source_span_sha256": sha256(message.encode("utf-8")).hexdigest(),
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "question": message,
        "risk_level": "low",
    }
    app = create_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/ask/api/analyze",
        json={
            "message": message,
            "copilot_context": {
                "turn_understanding": {
                    "requested_claims": [injected_goal],
                    "customer_goals": [injected_goal],
                    "goal_understanding_status": "valid",
                    "query_fact_type": "material_composition",
                }
            },
        },
    )

    assert response.status_code == 200
    decision = response.get_json()
    baseline = app.test_client().post(
        "/ask/api/analyze",
        json={"message": message},
    ).get_json()
    admitted = decision["evidence_debug"]["admitted_answer_context"]
    assert admitted["requested_claims"] == []
    assert (
        admitted["answer_eligibility_context"]["fast_path_preconditions_complete"]
        is False
    )
    assert decision["can_send"] is False
    assert {
        key: decision.get(key)
        for key in (
            "suggested_reply",
            "sendable_reply",
            "can_send",
            "requires_human_review",
            "reply_blocks",
        )
    } == {
        key: baseline.get(key)
        for key in (
            "suggested_reply",
            "sendable_reply",
            "can_send",
            "requires_human_review",
            "reply_blocks",
        )
    }


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


def test_model_first_composer_is_disabled_by_default(pipeline_harness, monkeypatch):
    monkeypatch.delenv("COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED", raising=False)

    response = AnalysisPipelineService().run(_request("api"))

    stage = next(
        item
        for item in response["analysis_pipeline"]["stages"]
        if item["stage"] == "model_first_answer_composer"
    )
    assert stage["status"] == "disabled"
    assert "model_first_answer_composer" not in response


def test_model_first_composer_fails_review_only_without_formal_convergence(
    pipeline_harness,
    monkeypatch,
):
    monkeypatch.setenv("COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED", "true")
    monkeypatch.delenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", raising=False)

    response = AnalysisPipelineService().run(_request("api"))

    diagnostics = response["model_first_answer_composer"]
    assert diagnostics["rejection_reason"] == "formal_evidence_convergence_disabled"
    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["sendable_reply"] == ""


def test_model_first_composer_applies_once_and_cannot_enable_send(
    pipeline_harness,
    monkeypatch,
):
    monkeypatch.setenv("COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED", "true")
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")

    calls = {"composer": 0}

    def fake_compose(self, response, **_kwargs):
        calls["composer"] += 1
        updated = deepcopy(response)
        updated["suggested_reply"] = "模型一次性候选回复"
        updated["can_send"] = True
        updated["requires_human_review"] = False
        diagnostics = {
            "version": "model-first-answer-composer-v1",
            "status": "accepted",
            "rejection_reason": "",
            "used_for_final_reply": True,
            "can_change_can_send": False,
        }
        return updated, diagnostics

    monkeypatch.setattr(
        "app.services.model_first_answer_composer_service.ModelFirstAnswerComposerService.compose",
        fake_compose,
    )

    response = AnalysisPipelineService().run(_request("api"))

    assert calls["composer"] == 1
    assert response["suggested_reply"] == "模型一次性候选回复"
    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["sendable_reply"] == ""


@pytest.mark.parametrize(
    "earliest_reason",
    [
        "source_text_not_found",
        "source_text_multiple_matches",
        "duplicate_resolved_provenance",
        "source_text_schema_invalid",
    ],
)
def test_invalid_understanding_skips_media_and_composer_even_with_evidence(
    pipeline_harness,
    monkeypatch,
    earliest_reason,
):
    import app.services.analysis_execution_service as execution
    import app.services.media_asset_service as media

    monkeypatch.setenv("COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED", "true")
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    calls = {"composer": 0, "media": 0}

    def fake_execute_analysis(**kwargs):
        graph_response = deepcopy(_graph_response())
        graph_response["evidence_debug"].update({
            "turn_understanding": {
                "goal_understanding_status": "invalid",
                "goal_understanding_diagnostics": [
                    earliest_reason,
                    "llm_goal_understanding_unavailable",
                ],
                "requested_claims": [{
                    "goal_ref": "stale-goal",
                    "claim_type": "installation",
                }],
            },
            "selected_evidence": [{"evidence_uid": "diagnostic-evidence"}],
            "admitted_answer_context": {
                "admitted_evidence": [{
                    "evidence_uid": "diagnostic-evidence",
                }],
            },
        })
        return kwargs["response_post_processor"](graph_response)

    def fail_compose(*_args, **_kwargs):
        calls["composer"] += 1
        raise AssertionError("composer must not be called")

    def fail_media(*_args, **_kwargs):
        calls["media"] += 1
        raise AssertionError("media selection must not be called")

    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)
    monkeypatch.setattr(
        "app.services.model_first_answer_composer_service."
        "ModelFirstAnswerComposerService.compose",
        fail_compose,
    )
    monkeypatch.setattr(media, "recommend_for_analyze_response", fail_media)

    response = AnalysisPipelineService().run(_request("api"))

    assert calls == {"composer": 0, "media": 0}
    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["sendable_reply"] == ""
    assert response["recommended_assets"] == []
    assert not {
        block.get("type")
        for block in response["reply_blocks"]
        if isinstance(block, dict)
    } & {"image", "video", "service_action"}
    assert response["reply_delivery"]["auto_send_ready"] is False
    boundary = response["turn_understanding_boundary"]
    assert boundary["earliest_reason_code"] == earliest_reason
    assert boundary["requested_claims"] == []
    assert boundary["used_for_final_reply"] is False
    assert response["evidence_debug"]["selected_evidence"] == [
        {"evidence_uid": "diagnostic-evidence"}
    ]
    stages = {
        stage["stage"]: stage
        for stage in response["analysis_pipeline"]["stages"]
    }
    assert stages["media_delivery"]["status"] == "blocked"
    assert stages["model_first_answer_composer"]["status"] == "blocked"


def test_degraded_understanding_preserves_existing_review_only_reply(
    pipeline_harness,
    monkeypatch,
):
    import app.services.analysis_execution_service as execution
    import app.services.media_asset_service as media

    calls = {"composer": 0, "media": 0}

    def fake_execute_analysis(**kwargs):
        graph_response = deepcopy(_graph_response())
        graph_response["evidence_debug"].update({
            "turn_understanding": {
                "goal_understanding_status": "degraded",
                "goal_understanding_diagnostics": [
                    "llm_goal_understanding_unavailable",
                ],
                "requested_claims": [],
            },
        })
        return kwargs["response_post_processor"](graph_response)

    def fail_compose(*_args, **_kwargs):
        calls["composer"] += 1
        raise AssertionError("composer must not be called")

    def fail_media(*_args, **_kwargs):
        calls["media"] += 1
        raise AssertionError("media selection must not be called")

    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)
    monkeypatch.setattr(
        "app.services.model_first_answer_composer_service."
        "ModelFirstAnswerComposerService.compose",
        fail_compose,
    )
    monkeypatch.setattr(media, "recommend_for_analyze_response", fail_media)

    response = AnalysisPipelineService().run(_request("api"))

    assert calls == {"composer": 0, "media": 0}
    assert response["suggested_reply"] == _graph_response()["suggested_reply"]
    assert response["draft_reply"] == ""
    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["sendable_reply"] == ""
    assert response["recommended_assets"] == []
    assert response["turn_understanding_boundary"]["status"] == "degraded"


@pytest.fixture()
def published_product_policy_db(monkeypatch):
    """An isolated formal-product catalog for canonical-input policy binding."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.db as db_module
    from app.models.kb_tables import KBProduct

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    def add_product(*, i_id: str, sku_code: str, status: str = "published", domain_policy_id: str = ""):
        db = session_factory()
        try:
            product = KBProduct(
                i_id=i_id,
                product_name="Catalog Product",
                status=status,
                domain_policy_id=domain_policy_id,
            )
            product.set_sku_list([{"sku_code": sku_code}])
            db.add(product)
            db.commit()
        finally:
            db.close()

    return add_product


def test_pipeline_uses_published_product_domain_policy_from_exact_sku(
    monkeypatch,
    published_product_policy_db,
):
    monkeypatch.delenv("COPILOT_DOMAIN_POLICY_ID", raising=False)
    published_product_policy_db(
        i_id="POLICY-PRODUCT-001",
        sku_code="POLICY-SKU-001",
        domain_policy_id="maternal_child_home",
    )

    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            product_candidates=[{"type": "sku_code", "value": "POLICY-SKU-001"}],
            copilot_context={
                "catalog_metadata": {"domain_policy_id": "public_injection"},
            },
        )
    )

    owner_context = prepared.copilot_context["_answer_eligibility_owner_context"]
    domain_context = owner_context["domain_policy_context"]
    assert owner_context["source"] == "verified_server_mapping"
    assert domain_context["status"] == "selected"
    assert domain_context["selection_source"] == "verified_server_mapping"
    assert domain_context["pack_ref"] == _current_domain_pack_ref()
    assert domain_context["binding_summary"] == {
        "tenant": False,
        "store": False,
        "catalog": True,
    }


def test_pipeline_rejects_title_only_or_unpublished_product_policy_binding(
    monkeypatch,
    published_product_policy_db,
):
    monkeypatch.delenv("COPILOT_DOMAIN_POLICY_ID", raising=False)
    published_product_policy_db(
        i_id="POLICY-PRODUCT-002",
        sku_code="POLICY-SKU-002",
        domain_policy_id="maternal_child_home",
    )
    published_product_policy_db(
        i_id="POLICY-PRODUCT-003",
        sku_code="POLICY-SKU-003",
        status="draft",
        domain_policy_id="maternal_child_home",
    )

    title_only = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            product_name="Catalog Product",
        )
    )
    unpublished = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            product_candidates=[{"type": "sku_code", "value": "POLICY-SKU-003"}],
        )
    )

    assert (
        title_only.copilot_context["_answer_eligibility_owner_context"]["source"]
        == "server_configuration"
    )
    assert (
        title_only.copilot_context["_answer_eligibility_owner_context"]
        ["domain_policy_context"]["status"]
        == "missing"
    )
    unpublished_owner = unpublished.copilot_context[
        "_answer_eligibility_owner_context"
    ]
    assert unpublished_owner["source"] == "verified_server_mapping"
    assert unpublished_owner["domain_policy_context"]["status"] == "missing"


def test_pipeline_rejects_conflicting_exact_product_identifiers(
    monkeypatch,
    published_product_policy_db,
):
    monkeypatch.delenv("COPILOT_DOMAIN_POLICY_ID", raising=False)
    published_product_policy_db(
        i_id="POLICY-PRODUCT-004",
        sku_code="POLICY-SKU-004",
        domain_policy_id="maternal_child_home",
    )
    published_product_policy_db(
        i_id="POLICY-PRODUCT-005",
        sku_code="POLICY-SKU-005",
        domain_policy_id="maternal_child_home",
    )

    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            copilot_context={"i_id": "POLICY-PRODUCT-004"},
            product_candidates=[{"type": "sku_code", "value": "POLICY-SKU-005"}],
        )
    )

    owner_context = prepared.copilot_context["_answer_eligibility_owner_context"]
    assert owner_context["source"] == "verified_server_mapping"
    assert owner_context["domain_policy_context"]["status"] == "missing"


def test_pipeline_keeps_legacy_query_only_catalog_usable_without_policy_column(
    monkeypatch,
    tmp_path,
):
    """A pre-migration catalog must fail closed for policy binding, not retrieval."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db as db_module
    from app.models.kb_tables import KBProduct

    database = tmp_path / "legacy-catalog.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE kb_product (
                id INTEGER PRIMARY KEY,
                i_id VARCHAR(64) NOT NULL,
                product_name VARCHAR(255) NOT NULL,
                brand VARCHAR(128) NOT NULL DEFAULT '',
                category_l1 VARCHAR(64) NOT NULL DEFAULT '',
                category_l2 VARCHAR(64) NOT NULL DEFAULT '',
                category_l3 VARCHAR(64) NOT NULL DEFAULT '',
                sku_list_json TEXT NOT NULL DEFAULT '[]',
                specs_json TEXT NOT NULL DEFAULT '{}',
                logistics_json TEXT NOT NULL DEFAULT '{}',
                warranty_json TEXT NOT NULL DEFAULT '{}',
                completeness_score FLOAT NOT NULL DEFAULT 0,
                missing_fields_json TEXT NOT NULL DEFAULT '[]',
                status VARCHAR(16) NOT NULL DEFAULT 'draft',
                version INTEGER NOT NULL DEFAULT 1,
                created_by VARCHAR(64) NOT NULL DEFAULT '',
                updated_by VARCHAR(64) NOT NULL DEFAULT '',
                created_at DATETIME,
                updated_at DATETIME,
                import_batch_id VARCHAR(64) NOT NULL DEFAULT ''
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO kb_product (
                id, i_id, product_name, sku_list_json, status
            ) VALUES (
                1, 'LEGACY-PRODUCT-001', 'Legacy catalog product',
                '[{"sku_code": "LEGACY-SKU-001"}]', 'published'
            )
            """
        )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.delenv("COPILOT_DOMAIN_POLICY_ID", raising=False)

    db = session_factory()
    try:
        legacy_product = db.query(KBProduct).filter(KBProduct.id == 1).one()
        assert legacy_product.to_dict()["i_id"] == "LEGACY-PRODUCT-001"
        assert legacy_product.to_dict(detail=True)["domain_policy_id"] == ""
    finally:
        db.close()

    prepared = AnalysisPipelineService()._prepare_request(
        AnalysisPipelineRequest(
            reply_service=object(),
            customer_message="test",
            product_candidates=[{"type": "sku_code", "value": "LEGACY-SKU-001"}],
        )
    )

    owner_context = prepared.copilot_context["_answer_eligibility_owner_context"]
    assert owner_context["source"] == "verified_server_mapping"
    assert owner_context["domain_policy_context"]["status"] == "missing"


def test_disabled_decision_shadow_reports_provider_block_without_a_candidate_reply(pipeline_harness, monkeypatch):
    monkeypatch.delenv("COPILOT_LLM_DECISION_SHADOW_ENABLED", raising=False)

    response = AnalysisPipelineService().run(_request("api"))

    status = response["evidence_debug"]["llm_decision_shadow_status"]
    assert status["status"] == "disabled"
    assert status["reason"] in {"provider_not_configured", "provider_not_qualified", "strict_capability_not_supported"}
    assert status["used_for_final_reply"] is False
    assert status["can_change_can_send"] is False
    assert "llm_decision_proposal" not in response["evidence_debug"]


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
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {"ready": True, "status": "ready", "reasons": [], "knowledge": {}, "database": {}},
    )
    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)

    response = service.run(_request("api"))

    assert calls["complete"] == 1
    assert response["trace_response_stage"] == "pre_final"
    assert response["can_send"] is False
    assert response["sendable_reply"] == ""


def test_product_scoped_request_fails_closed_when_runtime_is_not_ready(monkeypatch):
    import app.services.analysis_execution_service as execution

    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {
            "ready": False,
            "status": "not_ready",
            "reasons": ["knowledge_entries_empty"],
            "knowledge": {"entries": 0, "chunks": 0, "kb_qa": 0},
            "database": {"basename": "knowledge_base.db"},
        },
    )
    monkeypatch.setattr(execution, "execute_analysis", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not analyze")))

    response = AnalysisPipelineService().run(_request("api"))

    assert response["can_send"] is False
    assert response["requires_human_review"] is True
    assert response["sendable_reply"] == ""
    assert response["reply_status"] == "needs_human_review"
    assert response["evidence_debug"]["runtime_not_ready"] is True
    assert "knowledge_entries_empty" in response["evidence_debug"]["knowledge_db_unavailable"]


def test_product_context_does_not_block_explicit_aftersales_contract_when_runtime_is_not_ready(monkeypatch):
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not inspect product knowledge")),
    )
    request = _request("api")
    request = AnalysisPipelineRequest(
        **{
            **request.__dict__,
            "copilot_context": {
                **request.copilot_context,
                "turn_understanding": {"query_fact_type": "aftersales_policy"},
            },
        }
    )

    assert AnalysisPipelineService._knowledge_readiness_for_request(request) is None


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
