from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from app.agent.nodes.evidence_builder import (
    _formal_evidence_convergence,
    _formal_understanding,
)
from app.agent.tools.base import ToolSpec
from app.agent.tools.registry import (
    ToolRegistry,
    build_tool_requirement_status,
    get_tool_registry,
)
from app.repositories.file_policy_repository import FilePolicyRepository
from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_minimal_decision_context,
)
from app.services.canonical_conversation_turn_service import (
    canonical_conversation_reference_status,
)


def _write_pack(
    rules_dir: Path,
    *,
    domain_id: str,
    claim_type: str,
    risk_level: str,
    inference: str = "none",
) -> None:
    path = rules_dir / "domain_policy_packs" / f"{domain_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "domain-policy-pack/v1",
                "domain_id": domain_id,
                "version": "1.0.0",
                "claim_policies": {
                    claim_type: {
                        "risk_level": risk_level,
                        "direct_fact_fast_path_allowed": risk_level == "low",
                        "bounded_inference_policy": inference,
                        "freshness_requirement": "static",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _fact(*, claim_type: str = "material_composition") -> dict:
    return {
        "evidence_uid": "fact-1",
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "fact_type": claim_type,
        "attribute_key": "material" if claim_type == "material_composition" else "",
        "content": "reviewed direct fact",
        "sku_code": "SKU-A",
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
        "material_provenance": "structured_product_record",
    }


def _understanding(
    claim_type: str,
    *,
    status: str = "valid",
    risk_level: str = "low",
) -> dict:
    source_text = "current question"
    return {
        "goal_understanding_status": status,
        "goal_understanding_diagnostics": [] if status == "valid" else ["goal_contract_degraded"],
        "requested_claims": [
            {
                "goal_ref": f"goal-{claim_type}",
                "goal_kind": "customer_goal",
                "claim_type": claim_type,
                "attribute_key": "material" if claim_type == "material_composition" else "",
                "source": "current_customer_message",
                "source_span_start": 0,
                "source_span_end": len(source_text),
                "source_span_sha256": sha256(source_text.encode("utf-8")).hexdigest(),
                "question": source_text,
                "risk_level": risk_level,
            }
        ],
    }


def _owner_inputs(pack: dict, **overrides) -> dict:
    result = {
        "domain_policy_pack": pack,
        "conversation_reference_status": {
            "status": "resolved",
            "source_stage": "canonical_context_resolution",
            "reason_codes": [],
        },
        "tool_requirement_status": {
            "status": "not_required",
            "required_tool_refs": [],
            "completed_tool_refs": [],
            "source_stage": "tool_router_and_executor",
            "reason_codes": [],
        },
    }
    result.update(overrides)
    return result


def test_domain_pack_selection_requires_explicit_metadata_and_valid_schema(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="maternal_child_home",
        claim_type="material_composition",
        risk_level="low",
    )
    repository = FilePolicyRepository(rules_dir=str(tmp_path))

    assert repository.resolve_domain_policy_pack({})["status"] == "missing"
    assert repository.resolve_domain_policy_pack(
        {"domain_policy_id": "maternal_child_home"}
    )["status"] == "missing"
    assert repository.resolve_domain_policy_pack(
        {"customer_message": "maternal_child_home"}
    )["status"] == "missing"
    loaded = repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "maternal_child_home"}}
    )
    assert loaded["status"] == "loaded"
    assert loaded["domain_id"] == "maternal_child_home"
    assert loaded["claim_policies"]["material_composition"]["risk_level"] == "low"

    invalid_path = tmp_path / "domain_policy_packs" / "invalid.yaml"
    invalid_path.write_text("schema_version: wrong\n", encoding="utf-8")
    assert repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "invalid"}}
    )["status"] == "invalid"
    assert repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "../outside"}}
    )["status"] == "invalid"


def test_domain_pack_rejects_unknown_version_and_extra_product_or_reply_data(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="bad_version",
        claim_type="material_composition",
        risk_level="low",
    )
    bad_version = tmp_path / "domain_policy_packs" / "bad_version.yaml"
    payload = yaml.safe_load(bad_version.read_text(encoding="utf-8"))
    payload["version"] = "latest"
    bad_version.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )

    _write_pack(
        tmp_path,
        domain_id="extra_data",
        claim_type="material_composition",
        risk_level="low",
    )
    extra_data = tmp_path / "domain_policy_packs" / "extra_data.yaml"
    payload = yaml.safe_load(extra_data.read_text(encoding="utf-8"))
    payload["reply_template"] = "not allowed"
    extra_data.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    repository = FilePolicyRepository(rules_dir=str(tmp_path))

    assert repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "bad_version"}}
    )["status"] == "invalid"
    assert repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "extra_data"}}
    )["status"] == "invalid"


def test_second_domain_pack_changes_policy_without_core_branch(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="maternal_child_home",
        claim_type="material_composition",
        risk_level="low",
    )
    _write_pack(
        tmp_path,
        domain_id="sports_equipment_test",
        claim_type="material_composition",
        risk_level="high",
    )
    repository = FilePolicyRepository(rules_dir=str(tmp_path))

    first = repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "maternal_child_home"}}
    )
    second = repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "sports_equipment_test"}}
    )

    first_context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(first),
    )
    second_context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(second),
    )

    assert first_context["answer_eligibility_context"]["risk_policy_status"][
        "status"
    ] == "low_risk_verified"
    assert second_context["answer_eligibility_context"]["risk_policy_status"][
        "status"
    ] == "high_risk"


def test_all_registered_tools_declare_freshness_class():
    freshness = {
        name: get_tool_registry().get(name).freshness_class
        for name in get_tool_registry().tool_names
    }

    assert set(freshness.values()) <= {"static", "live", "action"}
    assert {"static", "live"} <= set(freshness.values())


def test_tool_requirement_status_distinguishes_availability_from_requirement():
    registry = ToolRegistry()
    registry.register(ToolSpec(name="static", description="", freshness_class="static"))
    registry.register(ToolSpec(name="live", description="", freshness_class="live"))
    registry.register(ToolSpec(name="action", description="", freshness_class="action"))

    assert build_tool_requirement_status([], {}, registry=registry)["status"] == "not_required"
    assert build_tool_requirement_status(
        ["live"], {}, registry=registry
    )["status"] == "live_tool_required"
    tool_results = {"live": {"found": False}}
    original_results = deepcopy(tool_results)
    assert build_tool_requirement_status(
        ["live"], tool_results, registry=registry
    )["status"] == "live_tool_completed"
    assert tool_results == original_results
    assert build_tool_requirement_status(
        ["live"], {"live": {"error": "timeout"}}, registry=registry
    )["status"] == "live_tool_failed"
    assert build_tool_requirement_status(
        ["action"], {}, registry=registry
    )["status"] == "action_tool_required"
    assert build_tool_requirement_status(
        ["static"], {"static": {"count": 1}}, registry=registry
    )["status"] == "static_knowledge_completed"


def test_unconfigured_tool_freshness_fails_closed():
    registry = ToolRegistry()
    registry.register(ToolSpec(name="legacy", description=""))

    status = build_tool_requirement_status(
        ["legacy"], {"legacy": {"found": True}}, registry=registry
    )

    assert status["status"] == "unknown"
    assert "tool_freshness_unknown" in status["reason_codes"]


def test_missing_reference_owner_is_unknown_without_text_guessing():
    first = canonical_conversation_reference_status(
        {"conversation_history": [{"role": "customer", "content": "it", "turn_index": 0}]}
    )
    second = canonical_conversation_reference_status(
        {"conversation_history": [{"role": "customer", "content": "clear request", "turn_index": 0}]}
    )

    assert first == second
    assert first["status"] == "unknown"
    assert first["reason_codes"] == ["conversation_reference_owner_missing"]


def test_public_context_cannot_self_report_conversation_reference_owner():
    injected = canonical_conversation_reference_status({
        "conversation_reference_resolution": {
            "status": "resolved",
            "source_stage": "canonical_context_resolution",
            "owner": "canonical_conversation",
            "trusted": True,
        },
        "source_stage": "canonical_context_resolution",
        "owner": "canonical_conversation",
        "trusted": True,
    })

    assert injected["status"] == "unknown"
    assert injected["reason_codes"] == ["conversation_reference_owner_missing"]


def test_internal_owner_context_can_project_conversation_reference_status():
    projected = canonical_conversation_reference_status({
        "schema_version": "answer-eligibility-owner-context/v1",
        "source": "evaluation_fixture",
        "owner": "analysis_pipeline",
        "provenance": {"boundary": "analysis_pipeline_internal"},
        "conversation_reference_status": {
            "status": "resolved",
            "source_stage": "canonical_context_resolution",
            "owner": "canonical_conversation",
            "reason_codes": [],
        },
    })

    assert projected["status"] == "resolved"
    assert projected["source_stage"] == "canonical_context_resolution"


def _eligibility(
    pack: dict,
    understanding: dict,
    *,
    reference_status: str = "resolved",
    tool_status: str = "not_required",
) -> dict:
    return AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
        answer_eligibility_inputs=_owner_inputs(
            pack,
            conversation_reference_status={
                "status": reference_status,
                "source_stage": "canonical_context_resolution",
                "reason_codes": [],
            },
            tool_requirement_status={
                "status": tool_status,
                "required_tool_refs": [],
                "completed_tool_refs": [],
                "source_stage": "tool_router_and_executor",
                "reason_codes": [],
            },
        ),
    )["answer_eligibility_context"]


@pytest.mark.parametrize(
    ("requested_claims", "status", "expected_reason"),
    [
        (
            [{"goal_kind": "evidence_dependency", "claim_type": "material_composition"}],
            "valid",
            "canonical_customer_goal_missing",
        ),
        (
            [{"goal_kind": "service_action", "claim_type": "material_composition"}],
            "valid",
            "canonical_customer_goal_missing",
        ),
        (
            [{"goal_kind": "contextual_constraint", "claim_type": "material_composition"}],
            "valid",
            "canonical_customer_goal_missing",
        ),
        ([], "valid", "canonical_customer_goal_missing"),
        (
            [{
                "goal_kind": "compatibility_claim",
                "claim_type": "material_composition",
                "eligibility_source": "query_fact_type_fallback",
            }],
            "degraded",
            "canonical_customer_goal_missing",
        ),
        (
            [{
                **_understanding("material_composition")["requested_claims"][0],
                "goal_ref": "",
            }],
            "valid",
            "canonical_customer_goal_goal_ref_missing",
        ),
        (
            [{
                key: value
                for key, value in _understanding("material_composition")[
                    "requested_claims"
                ][0].items()
                if not key.startswith("source_span_")
            }],
            "valid",
            "canonical_customer_goal_source_span_missing",
        ),
    ],
)
def test_noncanonical_requested_claims_never_qualify_for_fast_path(
    tmp_path,
    requested_claims,
    status,
    expected_reason,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    eligibility = _eligibility(
        pack,
        {
            "goal_understanding_status": status,
            "goal_understanding_diagnostics": (
                [] if status == "valid" else ["query_fact_type_compatibility_fallback"]
            ),
            "requested_claims": requested_claims,
        },
    )

    assert eligibility["fast_path_preconditions_complete"] is False
    assert expected_reason in eligibility["fast_path_block_reasons"]


@pytest.mark.parametrize("status", ["degraded", "invalid", "unknown"])
def test_nonvalid_understanding_blocks_even_with_canonical_customer_goal(
    tmp_path,
    status,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    understanding = _understanding("material_composition", status=status)

    eligibility = _eligibility(pack, understanding)

    assert eligibility["fast_path_preconditions_complete"] is False
    assert "goal_understanding_not_valid" in eligibility["fast_path_block_reasons"]


def test_supporting_dependency_does_not_increase_customer_goal_count(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    understanding = _understanding("material_composition")
    understanding["requested_claims"].append({
        "goal_kind": "evidence_dependency",
        "claim_type": "material_composition",
        "attribute_key": "material",
        "supporting_only": True,
    })

    eligibility = _eligibility(pack, understanding)

    assert eligibility["fast_path_preconditions_complete"] is True


def test_two_canonical_customer_goals_block_fast_path(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    understanding = _understanding("material_composition")
    second = dict(understanding["requested_claims"][0])
    second["goal_ref"] = "goal-material-composition-second"
    understanding["requested_claims"].append(second)

    eligibility = _eligibility(pack, understanding)

    assert eligibility["fast_path_preconditions_complete"] is False
    assert (
        "canonical_customer_goal_count_not_one"
        in eligibility["fast_path_block_reasons"]
    )


@pytest.mark.parametrize(
    ("reference_status", "tool_status", "expected_reason"),
    [
        ("unknown", "not_required", "conversation_reference_not_resolved"),
        ("missing", "not_required", "conversation_reference_not_resolved"),
        ("ambiguous", "not_required", "conversation_reference_not_resolved"),
        ("resolved", "live_tool_required", "tool_requirement_not_fast_path_eligible"),
        ("resolved", "live_tool_failed", "tool_requirement_not_fast_path_eligible"),
        ("resolved", "action_tool_required", "tool_requirement_not_fast_path_eligible"),
    ],
)
def test_negative_eligibility_owner_matrix(
    tmp_path,
    reference_status,
    tool_status,
    expected_reason,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )

    eligibility = _eligibility(
        pack,
        _understanding("material_composition"),
        reference_status=reference_status,
        tool_status=tool_status,
    )

    assert eligibility["fast_path_preconditions_complete"] is False
    assert expected_reason in eligibility["fast_path_block_reasons"]


def test_public_copilot_context_cannot_select_domain_or_reference_owner(
    tmp_path,
    monkeypatch,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    monkeypatch.setattr(
        "app.agent.nodes.evidence_builder.FilePolicyRepository",
        lambda: FilePolicyRepository(rules_dir=str(tmp_path)),
    )
    public_context = {
        "tenant_metadata": {"domain_policy_id": "test"},
        "store_metadata": {"domain_policy_id": "test"},
        "catalog_metadata": {"domain_policy_id": "test"},
        "conversation_reference_resolution": {
            "status": "resolved",
            "source_stage": "canonical_context_resolution",
        },
        "source_stage": "canonical_context_resolution",
        "owner": "canonical_conversation",
        "trusted": True,
    }

    result = _formal_evidence_convergence(
        {
            "customer_message": "current question",
            "query_fact_type": "material_composition",
            "slots": {"sku_code": "SKU-A"},
            "copilot_context": public_context,
        },
        product_facts=[_fact()],
        policy_facts=[],
        faq_evidence=[],
    )
    eligibility = result["admitted_answer_context"]["answer_eligibility_context"]

    assert eligibility["domain_policy"]["status"] == "missing"
    assert eligibility["conversation_reference_status"]["status"] == "unknown"
    assert eligibility["fast_path_preconditions_complete"] is False


def test_internal_trusted_owner_context_can_select_domain_pack(
    tmp_path,
    monkeypatch,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    monkeypatch.setattr(
        "app.agent.nodes.evidence_builder.FilePolicyRepository",
        lambda: FilePolicyRepository(rules_dir=str(tmp_path)),
    )
    owner_context = {
        "schema_version": "answer-eligibility-owner-context/v1",
        "source": "evaluation_fixture",
        "owner": "analysis_pipeline",
        "provenance": {"boundary": "analysis_pipeline_internal"},
        "domain_policy_context": {
            "catalog_metadata": {"domain_policy_id": "test"},
        },
        "conversation_reference_status": {
            "status": "resolved",
            "source_stage": "canonical_context_resolution",
            "owner": "canonical_conversation",
            "reason_codes": [],
        },
    }

    result = _formal_evidence_convergence(
        {
            "customer_message": "current question",
            "turn_understanding": _understanding("material_composition"),
            "slots": {"sku_code": "SKU-A"},
            "copilot_context": {
                "_answer_eligibility_owner_context": owner_context,
            },
        },
        product_facts=[_fact()],
        policy_facts=[],
        faq_evidence=[],
    )
    eligibility = result["admitted_answer_context"]["answer_eligibility_context"]

    assert eligibility["domain_policy"]["status"] == "loaded"
    assert eligibility["conversation_reference_status"]["status"] == "resolved"
    assert eligibility["fast_path_preconditions_complete"] is True


def test_query_fact_type_compatibility_claim_is_degraded_and_not_a_customer_goal():
    understanding = _formal_understanding({
        "customer_message": "current question",
        "query_fact_type": "material_composition",
    })

    assert understanding["goal_understanding_status"] == "degraded"
    assert (
        "query_fact_type_compatibility_fallback"
        in understanding["goal_understanding_diagnostics"]
    )
    assert understanding["requested_claims"] == [{
        "goal_kind": "compatibility_claim",
        "claim_type": "material_composition",
        "question": "current question",
        "eligibility_source": "query_fact_type_fallback",
        "customer_goal_eligible": False,
    }]


def test_conflicting_domain_policy_metadata_fails_closed(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    result = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {
            "tenant_metadata": {"domain_policy_id": "test"},
            "store_metadata": {"domain_policy_id": "other"},
        }
    )

    assert result["status"] == "invalid"
    assert result["reason_codes"] == ["domain_policy_id_conflict"]


@pytest.mark.parametrize("risk_level", ["medium", "high", "prohibited"])
def test_nonlow_domain_risk_blocks_fast_path(tmp_path, risk_level):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level=risk_level,
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )

    eligibility = _eligibility(pack, _understanding("material_composition"))

    assert eligibility["fast_path_preconditions_complete"] is False
    assert "low_risk_not_verified" in eligibility["fast_path_block_reasons"]


@pytest.mark.parametrize(
    ("inference_policy", "expected_status"),
    [
        ("allowed", "bounded_inference_required"),
        ("prohibited", "inference_prohibited"),
    ],
)
def test_non_direct_inference_requirements_block_fast_path(
    tmp_path,
    inference_policy,
    expected_status,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
        inference=inference_policy,
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]

    assert context["inference_requirement_status"]["status"] == expected_status
    assert context["fast_path_preconditions_complete"] is False
    assert (
        "direct_evidence_only_not_verified"
        in context["fast_path_block_reasons"]
    )


def test_prohibited_claim_has_specific_fast_path_reason(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    understanding = _understanding("material_composition")
    understanding["requested_claims"][0]["direct_handling_prohibited"] = True
    understanding["requested_claims"][0]["prohibition_reason"] = (
        "deterministic_policy_prohibited"
    )

    eligibility = _eligibility(pack, understanding)

    assert eligibility["fast_path_preconditions_complete"] is False
    assert "prohibited_claim_present" in eligibility["fast_path_block_reasons"]


def test_unresolved_claim_has_specific_fast_path_reason(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]

    assert context["fast_path_preconditions_complete"] is False
    assert "unresolved_claim_present" in context["fast_path_block_reasons"]


def test_conflicting_claim_has_specific_fast_path_reason(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="dimensions",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    first = {
        **_fact(claim_type="dimensions"),
        "evidence_uid": "width-80",
        "attribute_key": "width",
        "content": "80cm",
        "value": "80cm",
    }
    second = {
        **first,
        "evidence_uid": "width-120",
        "content": "120cm",
        "value": "120cm",
    }
    understanding = _understanding("dimensions")
    understanding["requested_claims"][0]["attribute_key"] = "width"
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [first, second]},
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]

    assert context["fast_path_preconditions_complete"] is False
    assert "conflicting_claim_present" in context["fast_path_block_reasons"]


def test_unsatisfied_supporting_dependency_blocks_fast_path(tmp_path):
    path = tmp_path / "domain_policy_packs" / "test.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "domain-policy-pack/v1",
                "domain_id": "test",
                "version": "1.0.0",
                "claim_policies": {
                    claim_type: {
                        "risk_level": "low",
                        "direct_fact_fast_path_allowed": True,
                        "bounded_inference_policy": "none",
                        "freshness_requirement": "static",
                    }
                    for claim_type in (
                        "material_safety",
                        "material_composition",
                    )
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    understanding = _understanding("material_safety")
    direct_safety = {
        **_fact(claim_type="material_safety"),
        "attribute_key": "",
    }
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [direct_safety]},
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]

    assert context["fast_path_preconditions_complete"] is False
    assert (
        "supporting_dependency_unsatisfied"
        in context["fast_path_block_reasons"]
    )


@pytest.mark.parametrize(
    ("extra_candidate", "expected_reason"),
    [
        (
            {
                "evidence_uid": "action-1",
                "source_type": "service_action",
                "evidence_role": "service_action",
                "content": "manual action",
            },
            "service_action_present",
        ),
        (
            {
                "evidence_uid": "media-1",
                "source_type": "media_reference",
                "evidence_role": "media_reference",
                "asset_type": "image",
                "asset_url": "internal-media-reference",
            },
            "media_candidate_present",
        ),
    ],
)
def test_nonfact_actions_and_media_block_fast_path(
    tmp_path,
    extra_candidate,
    expected_reason,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact(), extra_candidate]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]

    assert context["fast_path_preconditions_complete"] is False
    assert expected_reason in context["fast_path_block_reasons"]


def test_risk_hint_low_cannot_override_domain_or_deterministic_high_risk(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_safety",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_safety", risk_level="low"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )

    eligibility = context["answer_eligibility_context"]
    assert eligibility["risk_policy_status"]["status"] == "high_risk"
    assert eligibility["fast_path_preconditions_complete"] is False


def test_unknown_claim_and_missing_domain_pack_fail_closed(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    repository = FilePolicyRepository(rules_dir=str(tmp_path))
    pack = repository.resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )

    unknown_claim = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        understanding=_understanding("dimensions", risk_level="low"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]
    missing_pack = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        understanding=_understanding("material_composition", risk_level="low"),
        answer_eligibility_inputs=_owner_inputs(
            repository.resolve_domain_policy_pack({})
        ),
    )["answer_eligibility_context"]

    assert unknown_claim["risk_policy_status"]["status"] == "unknown"
    assert missing_pack["risk_policy_status"]["status"] == "unknown"


def test_direct_evidence_projects_complete_diagnostic_eligibility(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    admitted = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )
    minimal = build_minimal_decision_context(
        admitted,
        customer_message="current question",
    )

    resolution = admitted["claim_resolutions"][0]
    eligibility = minimal["answer_eligibility_context"]
    assert resolution["support_basis"] == "direct_evidence"
    assert eligibility["inference_requirement_status"]["status"] == "direct_evidence_only"
    assert eligibility["risk_policy_status"]["status"] == "low_risk_verified"
    assert eligibility["fast_path_preconditions_complete"] is True
    assert eligibility["used_for_final_reply"] is False
    assert eligibility["can_change_can_send"] is False


def test_eligibility_projection_is_side_effect_free_and_does_not_call_a_model(
    tmp_path,
    monkeypatch,
):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    response = {
        "selected_evidence": [_fact()],
        "suggested_reply": "formal reply",
        "draft_reply": "formal reply",
        "reply_blocks": [{"type": "text", "content": "formal reply"}],
        "can_send": False,
        "requires_human_review": True,
    }
    original = deepcopy(response)

    def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("eligibility projection must not call a model")

    monkeypatch.setattr(
        "app.llm.client.LLMClient.create_chat_completion",
        unexpected_model_call,
    )
    baseline_admitted = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )
    admitted = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )
    minimal = build_minimal_decision_context(
        admitted,
        customer_message="current question",
    )

    assert response == original
    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == [
        "fact-1"
    ]
    assert admitted["direct_product_facts"] == baseline_admitted[
        "direct_product_facts"
    ]
    assert admitted["direct_policy_facts"] == baseline_admitted[
        "direct_policy_facts"
    ]
    assert admitted["rejected_evidence"] == baseline_admitted[
        "rejected_evidence"
    ]
    assert minimal["answer_eligibility_context"] == admitted[
        "answer_eligibility_context"
    ]
    assert {
        key: response[key]
        for key in (
            "suggested_reply",
            "draft_reply",
            "reply_blocks",
            "can_send",
            "requires_human_review",
        )
    } == {
        key: original[key]
        for key in (
            "suggested_reply",
            "draft_reply",
            "reply_blocks",
            "can_send",
            "requires_human_review",
        )
    }


def test_eligibility_projection_excludes_customer_and_product_identity(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    eligibility = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "PRIVATE-SKU"},
        understanding={
            **_understanding("material_composition"),
            "customer_message": "private customer text",
        },
        answer_eligibility_inputs=_owner_inputs(pack),
    )["answer_eligibility_context"]
    serialized = str(eligibility)

    assert "PRIVATE-SKU" not in serialized
    assert "private customer text" not in serialized
    assert "product_identity" not in eligibility
    assert "customer_message" not in eligibility


def test_ambiguous_live_tool_inference_input_no_longer_matches_clear_direct(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="dimensions",
        risk_level="low",
        inference="allowed",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )
    direct = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact(claim_type="dimensions")]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )
    unsafe = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": []},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
        answer_eligibility_inputs=_owner_inputs(
            pack,
            conversation_reference_status={
                "status": "ambiguous",
                "source_stage": "canonical_context_resolution",
                "reason_codes": ["multiple_referents"],
            },
            tool_requirement_status={
                "status": "live_tool_required",
                "required_tool_refs": ["live"],
                "completed_tool_refs": [],
                "source_stage": "tool_router_and_executor",
                "reason_codes": ["required_live_tool_pending"],
            },
        ),
    )

    direct_minimal = build_minimal_decision_context(direct, customer_message="current")
    unsafe_minimal = build_minimal_decision_context(unsafe, customer_message="current")
    assert direct_minimal["answer_eligibility_context"] != unsafe_minimal["answer_eligibility_context"]
    assert unsafe_minimal["answer_eligibility_context"]["inference_requirement_status"]["status"] == "bounded_inference_required"
    assert unsafe_minimal["answer_eligibility_context"]["fast_path_preconditions_complete"] is False


def test_degraded_understanding_never_becomes_valid(tmp_path):
    _write_pack(
        tmp_path,
        domain_id="test",
        claim_type="material_composition",
        risk_level="low",
    )
    pack = FilePolicyRepository(rules_dir=str(tmp_path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition", status="degraded"),
        answer_eligibility_inputs=_owner_inputs(pack),
    )

    eligibility = context["answer_eligibility_context"]
    assert eligibility["goal_understanding_status"]["status"] == "degraded"
    assert eligibility["fast_path_preconditions_complete"] is False
