from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services import semantic_fact_type_service
from app.services.claim_resolution_service import build_claim_resolutions


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
