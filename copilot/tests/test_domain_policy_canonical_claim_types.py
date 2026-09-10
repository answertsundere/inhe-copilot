from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services import semantic_fact_type_service
from app.services.claim_resolution_service import build_claim_resolutions
from app.services.admitted_answer_context_service import AdmittedAnswerContextService
from app.agent.nodes.query_fact_type_classifier import _turn_understanding_from_result


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
