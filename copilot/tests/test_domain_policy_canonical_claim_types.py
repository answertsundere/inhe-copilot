from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest
import yaml

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services import semantic_fact_type_service
from app.services.claim_resolution_service import build_claim_resolutions
from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_minimal_decision_context,
)
from app.agent.nodes.query_fact_type_classifier import _turn_understanding_from_result
from app.services.final_answer_auditor import audit_final_answer
from app.services.model_first_answer_composer_service import ModelFirstAnswerComposerService


def _loaded_pack() -> dict:
    return FilePolicyRepository().resolve_domain_policy_pack({
        "catalog_metadata": {
            "domain_policy_id": "maternal_child_home",
        },
    })


def _dimension_policy(pack: dict) -> dict:
    policy = next(
        item
        for item in pack["bounded_inference_policies"]
        if item["policy_intent_ref"]
        == "product_dimensions_practical_guidance"
    )
    return {
        **policy,
        "pack_content_sha256": pack["pack_content_sha256"],
    }


def _dimension_goal(policy: dict) -> dict:
    goals, status, diagnostics = (
        semantic_fact_type_service._sanitize_customer_goals(
            [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "height",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "height fit request",
            }],
            message="height fit request",
            policy_intent_candidates=[policy],
        )
    )
    assert status == "valid"
    assert diagnostics == []
    return goals[0]


def test_maternal_child_pack_declares_dimension_policy_claim_types():
    pack = _loaded_pack()

    assert pack["status"] == "loaded"
    policy = next(
        item
        for item in pack["bounded_inference_policies"]
        if item["policy_intent_ref"]
        == "product_dimensions_practical_guidance"
    )
    assert policy["canonical_claim_types"] == [
        "dimensions",
        "space_fit",
    ]


def test_dimension_policy_requires_admitted_dimension_premise():
    pack = _loaded_pack()
    policy = _dimension_policy(pack)
    goal = _dimension_goal(policy)
    common = {
        "direct_policy_facts": [],
        "conflicts": [],
        "bounded_inference_policies": [policy],
        "context_capabilities": {
            "product_category": {"available": True},
        },
        "policy_ref_prefix": pack["pack_ref"],
    }

    supported = build_claim_resolutions(
        [goal],
        direct_product_facts=[{
            "evidence_uid": "dimension-height-1",
            "attribute_key": "height",
            "claim_types_supported": ["dimensions"],
            "text": "confirmed product height",
            "subject_scope": "product_overall",
        }],
        **common,
    )[0]

    assert supported["status"] == "supported"
    assert supported["evidence_uids"] == ["dimension-height-1"]
    assert len(supported["eligible_policy_options"]) == 1
    option = supported["eligible_policy_options"][0]
    assert option["policy_intent_ref"] == (
        "product_dimensions_practical_guidance"
    )
    assert option["premise_evidence_refs"] == ["dimension-height-1"]
    assert option["review_only"] is True
    assert option["can_change_can_send"] is False
    assert option["pack_content_sha256"] == pack["pack_content_sha256"]

    missing = build_claim_resolutions(
        [goal],
        direct_product_facts=[],
        **common,
    )[0]

    assert missing["eligible_policy_options"] == []
    assert missing["bounded_inference_rejection_reason"] == (
        "bounded_inference_premise_missing"
    )


def test_dimension_policy_does_not_cross_to_undeclared_claim_type():
    pack = _loaded_pack()
    policy = _dimension_policy(pack)
    goals, status, diagnostics = (
        semantic_fact_type_service._sanitize_customer_goals(
            [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "material_safety",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "material safety request",
            }],
            message="material safety request",
            policy_intent_candidates=[policy],
        )
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == ""
    assert goals[0]["policy_intent_kind"] == ""


@pytest.mark.parametrize(
    "canonical_claim_types",
    [
        "dimensions",
        ["dimensions", "dimensions"],
        ["unknown_claim_type"],
    ],
)
def test_domain_pack_rejects_invalid_canonical_claim_type_declarations(
    tmp_path,
    canonical_claim_types,
):
    source = (
        Path(__file__).parents[1]
        / "rules"
        / "domain_policy_packs"
        / "maternal_child_home.yaml"
    )
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    mutated = deepcopy(raw)
    mutated["domain_id"] = "test"
    mutated["bounded_inference_policies"][0][
        "canonical_claim_types"
    ] = canonical_claim_types
    pack_dir = tmp_path / "domain_policy_packs"
    pack_dir.mkdir()
    (pack_dir / "test.yaml").write_text(
        yaml.safe_dump(mutated, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = FilePolicyRepository(
        rules_dir=str(tmp_path)
    ).resolve_domain_policy_pack({
        "catalog_metadata": {"domain_policy_id": "test"},
    })

    assert result["status"] == "invalid"
    assert result["reason_codes"] == [
        "domain_policy_canonical_claim_types_invalid"
    ]


def _daily_care_policy(pack):
    return next(
        policy for policy in pack["bounded_inference_policies"]
        if policy["policy_intent_ref"] == "material_daily_use_practical_guidance"
    )


def _material_care_goals(policy):
    goals, status, diagnostics = semantic_fact_type_service._sanitize_customer_goals(
        [
            {"goal_kind": "customer_goal", "claim_type_status": "canonical",
             "claim_type": "material_composition", "attribute_key": "",
             "semantic_key": "", "policy_intent_ref": "",
             "source_text": "composition request"},
            {"goal_kind": "customer_goal", "claim_type_status": "canonical",
             "claim_type": "cleaning_care", "attribute_key": "",
             "semantic_key": "", "policy_intent_ref": policy["policy_intent_ref"],
             "source_text": "ordinary care request"},
        ],
        message="composition request; ordinary care request",
        policy_intent_candidates=[policy],
    )
    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 2
    assert goals[0]["policy_intent_ref"] == ""
    return goals


def test_daily_handling_policy_declares_only_cleaning_care_compatibility():
    policy = _daily_care_policy(_loaded_pack())

    assert policy.get("canonical_claim_types") == ["cleaning_care"]
    assert policy["premise_fact_families"] == ["material_composition"]
    assert policy["allowed_scope"] == "ordinary_wiping_moving_and_storage"
    assert policy["maximum_risk_level"] == "medium"
    assert policy["review_only"] is True
    assert "no_temperature_or_chemical_prescription" in policy["required_qualifiers"]
    assert {"heat_resistance", "child_safety", "non_toxic_claim"}.issubset(
        policy["prohibited_claim_families"]
    )


def test_daily_handling_declaration_reaches_existing_understanding_projection():
    domain = FilePolicyRepository().build_trusted_domain_policy_context(
        {"catalog_metadata": {"domain_policy_id": "maternal_child_home"}},
        selection_source="evaluation_fixture",
    )
    candidates = semantic_fact_type_service._policy_intent_candidates({
        "copilot_context": {"_answer_eligibility_owner_context": {
            "schema_version": "answer-eligibility-owner-context/v1",
            "source": "evaluation_fixture", "owner": "analysis_pipeline",
            "provenance": {"boundary": "analysis_pipeline_internal"},
            "domain_policy_context": domain,
        }},
    })
    policy = next(item for item in candidates if item["policy_intent_ref"] ==
                  "material_daily_use_practical_guidance")
    assert policy["canonical_claim_types"] == ["cleaning_care"]
    goals = _material_care_goals(policy)
    assert goals[1]["claim_type"] == "cleaning_care"
    assert goals[1]["policy_goal_family"] == "material_daily_use"


@pytest.mark.parametrize("evidence_change", [
    None, "missing", "conflicting", "category_missing",
    {"fact_review_status": "draft"}, {"sku_code": "other-sku"},
    {"evidence_role": "reference_only"}, {"evidence_role": "media_reference"},
    {"evidence_role": "service_action"}, {"gate_status": "blocked"},
    {"content": "\u5f85\u786e\u8ba4", "value": ""},
])
def test_care_nomination_preserves_direct_fact_and_requires_admitted_premise(evidence_change):
    pack = _loaded_pack()
    policy = _daily_care_policy(pack)
    goals = _material_care_goals(policy)
    fact = {
        "evidence_uid": "material-direct", "source_type": "product_facts",
        "evidence_role": "product_fact_direct", "fact_type": "material_composition",
        "attribute_key": "material", "content": "PP", "value": "PP", "sku_code": "fixture-sku",
        "material_provenance": "structured_product_record",
        "fact_review_status": "verified", "gate_status": "allowed",
        "direct_answer_allowed": True,
    }
    if isinstance(evidence_change, dict):
        fact.update(evidence_change)
    facts = [] if evidence_change == "missing" else [fact]
    if evidence_change == "conflicting":
        facts.append({**fact, "evidence_uid": "material-other", "content": "PE", "value": "PE"})
    response = {
        "selected_evidence": facts,
        "product_context_pack": {"structured_profile": {
            "source": "kb_product", "category": {"l1": "fixture category"},
        }},
    }
    if evidence_change == "category_missing":
        response["product_context_pack"] = {}
    before = deepcopy(response)
    context = AdmittedAnswerContextService().build_for_response(
        response, product_identity={"sku_code": "fixture-sku"},
        understanding=_turn_understanding_from_result(
            {"customer_message": "composition request; ordinary care request"},
            {"customer_goals": goals, "goal_understanding_status": "valid"},
        ),
        answer_eligibility_inputs={"domain_policy_pack": pack},
    )
    assert response == before
    assert context["read_only"] is True
    assert context["can_change_can_send"] is False
    material, care = context["claim_resolutions"]
    assert care["status"] == "unresolved"
    assert care["evidence_uids"] == []
    if evidence_change is not None:
        assert care["eligible_policy_options"] == []
        return
    assert material["status"] == "supported"
    assert material["evidence_uids"] == ["material-direct"]
    assert material["eligible_policy_options"] == []
    assert len(care["eligible_policy_options"]) == 1
    option = care["eligible_policy_options"][0]
    assert option["premise_evidence_refs"] == ["material-direct"]
    assert option["policy_intent_ref"] == policy["policy_intent_ref"]
    assert option["pack_content_sha256"] == pack["pack_content_sha256"]
    assert option["allowed_scope"] == policy["allowed_scope"]
    assert option["required_qualifiers"] == sorted(policy["required_qualifiers"])
    assert option["review_only"] is True
    assert option["can_change_can_send"] is False


@pytest.mark.parametrize("claim_type", [
    "material_composition", "material_safety", "moisture_resistance",
    "certification_report", "load_capacity", "dimensions",
])
def test_daily_handling_does_not_nominate_for_other_canonical_claims(claim_type):
    policy = _daily_care_policy(_loaded_pack())
    goals, status, reasons = semantic_fact_type_service._sanitize_customer_goals(
        [{"goal_kind": "customer_goal", "claim_type_status": "canonical",
          "claim_type": claim_type, "attribute_key": "", "semantic_key": "",
          "policy_intent_ref": policy["policy_intent_ref"], "source_text": "synthetic request"}],
        message="synthetic request", policy_intent_candidates=[policy],
    )
    assert status == "degraded"
    assert "customer_goal_policy_intent_family_mismatch" in reasons
    assert goals[0]["policy_intent_ref"] == ""


def test_omitted_care_intent_does_not_choose_between_policy_families():
    pack = _loaded_pack()
    goals, status, reasons = semantic_fact_type_service._sanitize_customer_goals(
        [{"goal_kind": "customer_goal", "claim_type_status": "canonical",
          "claim_type": "cleaning_care", "attribute_key": "", "semantic_key": "",
          "policy_intent_ref": "", "source_text": "synthetic request"}],
        message="synthetic request",
        policy_intent_candidates=pack["bounded_inference_policies"],
    )
    assert status == "valid"
    assert reasons == []
    assert goals[0]["claim_type"] == "cleaning_care"
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == ""
    assert goals[0]["policy_intent_kind"] == ""


@pytest.fixture
def care_composer_response():
    pack = _loaded_pack()
    goals = _material_care_goals(_daily_care_policy(pack))
    question = "composition request; ordinary care request"
    trusted = FilePolicyRepository().build_trusted_domain_policy_context(
        {"catalog_metadata": {"domain_policy_id": "maternal_child_home"}},
        selection_source="evaluation_fixture",
    )
    response = {
        "selected_evidence": [{
            "evidence_uid": "material-direct", "source_type": "product_facts",
            "evidence_role": "product_fact_direct", "fact_type": "material_composition",
            "attribute_key": "material", "content": "PP", "value": "PP",
            "sku_code": "fixture-sku", "material_provenance": "structured_product_record",
            "fact_review_status": "verified", "gate_status": "allowed",
            "direct_answer_allowed": True,
        }],
        "product_context_pack": {"structured_profile": {
            "source": "kb_product", "category": {"l1": "fixture category"},
        }},
        "can_send": False, "requires_human_review": True,
    }
    admitted = AdmittedAnswerContextService().build_for_response(
        response, product_identity={"sku_code": "fixture-sku"},
        current_customer_message=question,
        understanding=_turn_understanding_from_result(
            {"customer_message": question},
            {"customer_goals": goals, "goal_understanding_status": "valid"},
        ),
        answer_eligibility_inputs={
            "domain_policy_pack": pack, "trusted_domain_policy_context": trusted,
        },
    )
    response["admitted_answer_context"] = admitted
    response["minimal_decision_context"] = build_minimal_decision_context(
        admitted, customer_message=question,
    )
    return response, question


@pytest.mark.parametrize("mutation", [
    "none", "unknown_option", "option_on_direct_fact", "duplicate_option",
    "omitted_option", "missing_trusted_context", "final_premise", "final_scope",
])
def test_care_option_reaches_composer_and_final_without_send_authority(
    care_composer_response, mutation, monkeypatch,
):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("network_forbidden_in_contract_test")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    response, question = care_composer_response
    before = deepcopy(response)
    service = ModelFirstAnswerComposerService()
    decision, error = service.build_composer_decision_input(
        response, customer_message=question,
    )
    assert not error
    material, error = service.build_provider_material_from_decision_input(decision)
    assert not error
    by_ref = {goal["goal_ref"]: goal for goal in material["customer_goals"]}
    texts = {
        "material_composition": "材质是 PP。",
        "cleaning_care": (
            "日常擦拭属于普通使用范围，但不能由材质保证耐摔，"
            "也不能推断高温或化学清洁是否适用。"
        ),
    }
    payload = {"clauses": [{
        "goal_ref": ref, "text": texts[by_ref[ref]["claim_type"]],
        "selected_option_refs": [
            option["option_ref"] for option in by_ref[ref]["eligible_policy_options"]
        ],
    } for ref in material["prompt_payload"]["presentation_order"]]}
    direct, care = payload["clauses"]
    assert by_ref[direct["goal_ref"]]["claim_type"] == "material_composition"
    assert len(care["selected_option_refs"]) == 1
    if mutation == "unknown_option":
        care["selected_option_refs"] = ["unknown-option"]
    elif mutation == "option_on_direct_fact":
        direct["selected_option_refs"] = list(care["selected_option_refs"])
    elif mutation == "duplicate_option":
        care["selected_option_refs"] *= 2
    elif mutation == "omitted_option":
        care["selected_option_refs"] = []
    elif mutation == "missing_trusted_context":
        response["minimal_decision_context"]["trusted_domain_policy_context"] = {}
        before = deepcopy(response)

    class FixtureClient:
        api_key = "fixture-only"
        model = "fixture-only"
        call_count = 0

        def create_chat_completion(self, **_kwargs):
            self.call_count += 1
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            )])

    client = FixtureClient()
    updated, result = service.compose(response, customer_message=question, client=client)
    assert response == before
    assert updated["can_send"] is False
    assert updated["requires_human_review"] is True
    assert client.call_count == (0 if mutation == "missing_trusted_context" else 1)
    expected_rejections = {
        "unknown_option": "composer_unknown_inference_policy_reference",
        "option_on_direct_fact": "composer_forbidden_option_selected",
        "duplicate_option": "composer_duplicate_inference_option_reference",
        "omitted_option": "composer_required_option_not_selected",
        "missing_trusted_context": "composer_domain_policy_context_invalid",
    }
    if mutation in expected_rejections:
        assert result["status"] != "accepted"
        assert result["rejection_reason"] == expected_rejections[mutation]
        assert result["used_for_final_reply"] is False
        return

    assert result["status"] == "accepted"
    assert updated["sendable_reply"] == ""
    claims = updated["admitted_answer_context"]["claim_resolutions"]
    assert [claim["status"] for claim in claims] == ["supported", "unresolved"]
    assert claims[1]["evidence_uids"] == []
    clauses = updated["model_first_answer_composer"]["clauses"]
    assert [clause["clause_kind"] for clause in clauses] == [
        "supported_fact", "allowed_inference",
    ]
    assert all(clause["evidence_uids"] == ["material-direct"] for clause in clauses)
    assert clauses[1]["inference_policy_refs"] == [
        claims[1]["eligible_policy_options"][0]["policy_ref"],
    ]
    if mutation == "final_premise":
        other_fact = deepcopy(updated["minimal_decision_context"]["admitted_evidence"][0])
        other_fact["evidence_uid"] = "other-admitted-direct"
        updated["minimal_decision_context"]["admitted_evidence"].append(other_fact)
        clauses[1]["evidence_uids"] = [other_fact["evidence_uid"]]
    elif mutation == "final_scope":
        clauses[1]["scope_qualifier"] = "different-scope"
    audited = audit_final_answer(updated, customer_message=question)
    audit = audited["final_answer_audit"]
    assert audit["passed"] is (mutation == "none")
    if mutation in {"final_premise", "final_scope"}:
        assert "model_first_candidate_bounded_inference_clause_invalid" in audit["issues"]
        assert "model_first_candidate_unknown_evidence" not in audit["issues"]
    assert audit["model_call_count"] == 0
    assert audited["can_send"] is False
    assert audited["requires_human_review"] is True
    assert audited["sendable_reply"] == ""
