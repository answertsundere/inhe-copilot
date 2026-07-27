from __future__ import annotations

import pytest

from app.services.claim_resolution_service import build_claim_resolutions, expand_claim_dependencies


def _claim(attribute_key: str = "", claim_type: str = "dimensions") -> dict[str, str]:
    return {"claim_type": claim_type, "attribute_key": attribute_key, "question": "", "risk_level": "medium"}


def _fact(uid: str, attribute_key: str, *, claim_type: str = "dimensions", reason: str = "") -> dict[str, str | list[str]]:
    return {
        "evidence_uid": uid,
        "attribute_key": attribute_key,
        "claim_types_supported": [claim_type],
        "text": f"{attribute_key} fact",
        "reason": reason,
    }


def _by_attribute(results: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["attribute_key"]): item for item in results}


def _bounded_policy(**overrides) -> dict:
    value = {
        "policy_intent_ref": "product_durability_practical_guidance",
        "goal_family": "product_durability",
        "intent_kind": "practical_guidance",
        "premise_fact_families": ["material_composition"],
        "required_context_capabilities": ["product_category"],
        "allowed_scope": "ordinary_minor_accidental_impact",
        "required_qualifiers": ["no_absolute_guarantee"],
        "prohibited_claim_families": [
            "certification_report",
            "child_safety",
            "warranty",
        ],
        "review_only": True,
    }
    value.update(overrides)
    return value


def _bounded_goal(**overrides) -> dict:
    value = {
        "goal_ref": "goal-durability",
        "goal_kind": "customer_goal",
        "claim_type": "unmapped_customer_goal",
        "attribute_key": "drop_durability",
        "semantic_key": "product_drop_durability",
        "policy_intent_ref": "product_durability_practical_guidance",
        "policy_goal_family": "product_durability",
        "policy_intent_kind": "practical_guidance",
        "goal_summary": "了解日常意外跌落的耐用边界",
        "risk_level": "medium",
    }
    value.update(overrides)
    return value


def test_explicit_dimension_claims_select_only_their_matching_attribute():
    results = _by_attribute(build_claim_resolutions(
        [_claim("width"), _claim("height")],
        direct_product_facts=[_fact("width", "width"), _fact("height", "height")],
        direct_policy_facts=[],
        conflicts=[],
    ))

    assert results["width"]["evidence_uids"] == ["width"]
    assert results["height"]["evidence_uids"] == ["height"]


def test_width_conflict_does_not_pollute_height_claim():
    results = _by_attribute(build_claim_resolutions(
        [_claim("width"), _claim("height")],
        direct_product_facts=[_fact("height", "height")],
        direct_policy_facts=[],
        conflicts=[_fact("width-a", "width", reason="conflicting_evidence"), _fact("width-b", "width", reason="conflicting_evidence")],
    ))

    assert results["width"]["status"] == "conflicting"
    assert results["height"]["status"] == "supported"
    assert results["height"]["evidence_uids"] == ["height"]


def test_weight_and_load_capacity_never_share_evidence():
    results = _by_attribute(build_claim_resolutions(
        [_claim("gross_weight", "gross_weight"), _claim("load_capacity", "load_capacity")],
        direct_product_facts=[
            _fact("weight", "gross_weight", claim_type="gross_weight"),
            _fact("load", "load_capacity", claim_type="load_capacity"),
        ],
        direct_policy_facts=[],
        conflicts=[],
    ))

    assert results["gross_weight"]["evidence_uids"] == ["weight"]
    assert results["load_capacity"]["evidence_uids"] == ["load"]


def test_explicit_attribute_requires_attributed_evidence():
    result = build_claim_resolutions(
        [_claim("width")],
        direct_product_facts=[_fact("unattributed", "")],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "attribute_evidence_missing"


def test_ambiguous_unattributed_claim_does_not_absorb_multiple_attributes():
    result = build_claim_resolutions(
        [_claim()],
        direct_product_facts=[_fact("width", "width"), _fact("height", "height")],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "selection_ambiguous"


def test_unmapped_customer_goal_stays_unresolved_with_semantic_provenance():
    result = build_claim_resolutions(
        [{
            "goal_ref": "goal-unmapped",
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "semantic_key": "",
            "goal_summary": "确认未注册的商品属性",
            "source": "current_customer_message",
            "source_span_start": 3,
            "source_span_end": 11,
            "source_span_sha256": "a" * 64,
        }],
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "unmapped_claim_type"
    assert result["evidence_uids"] == []
    assert result["support_basis"] == "none"
    assert result["inference_policy_refs"] == []
    assert result["semantic_key"] == ""
    assert result["goal_summary"] == "确认未注册的商品属性"
    assert result["source"] == "current_customer_message"
    assert result["source_span_start"] == 3
    assert result["source_span_end"] == 11
    assert result["source_span_sha256"] == "a" * 64


def test_unmapped_goal_without_semantic_metadata_cannot_match_evidence_or_policy():
    result = build_claim_resolutions(
        [{
            "goal_ref": "goal-unmapped",
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "durability",
            "semantic_key": "",
            "policy_intent_ref": "",
            "goal_summary": "确认耐用边界",
        }],
        direct_product_facts=[
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            ),
            _fact(
                "durability",
                "durability",
                claim_type="unmapped_customer_goal",
            ),
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy()],
        context_capabilities={
            "product_category": {"available": True},
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "unmapped_claim_type"
    assert result["evidence_uids"] == []
    assert result["support_basis"] == "none"
    assert result["inference_policy_refs"] == []


def test_claim_resolution_is_stable_across_input_order():
    claims = [_claim("width"), _claim("height")]
    facts = [_fact("width", "width"), _fact("height", "height")]
    first = build_claim_resolutions(claims, direct_product_facts=facts, direct_policy_facts=[], conflicts=[])
    second = build_claim_resolutions(list(reversed(claims)), direct_product_facts=list(reversed(facts)), direct_policy_facts=[], conflicts=[])

    assert first == second


def test_material_composition_dependency_is_supported_without_resolving_safety_claim():
    requested = expand_claim_dependencies([_claim("", "material_safety")])
    results = {
        str(item["claim_type"]): item
        for item in build_claim_resolutions(
            requested,
            direct_product_facts=[_fact("material", "", claim_type="material_composition")],
            direct_policy_facts=[],
            conflicts=[],
        )
    }

    assert results["material_composition"]["status"] == "supported"
    assert results["material_safety"]["status"] == "unresolved"


def test_legacy_material_evidence_is_a_composition_alias_not_a_safety_alias():
    results = {
        str(item["claim_type"]): item
        for item in build_claim_resolutions(
            expand_claim_dependencies([_claim("", "material_safety")]),
            direct_product_facts=[_fact("material", "material", claim_type="material")],
            direct_policy_facts=[],
            conflicts=[],
        )
    }

    assert results["material_composition"]["status"] == "supported"
    assert results["material_safety"]["status"] == "unresolved"


def test_equivalent_structured_material_facts_share_the_canonical_material_slot():
    result = build_claim_resolutions(
        [_claim("", "material")],
        direct_product_facts=[
            _fact("legacy", "", claim_type="material"),
            _fact("profile", "material", claim_type="material"),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["legacy", "profile"]


@pytest.mark.parametrize(
    ("claim_type", "claim_attribute", "evidence_type", "evidence_attribute"),
    [
        ("material", "材质", "material", ""),
        ("material", "", "material", "材质"),
        ("material_composition", "", "material", "材质"),
        ("material", "material_composition", "material", ""),
        (" ＭＡＴＥＲＩＡＬ ", " 材质 ", "material_composition", ""),
    ],
)
def test_base_material_display_attributes_align_to_one_canonical_slot(
    claim_type,
    claim_attribute,
    evidence_type,
    evidence_attribute,
):
    result = build_claim_resolutions(
        [_claim(claim_attribute, claim_type)],
        direct_product_facts=[
            _fact(
                "material-fact",
                evidence_attribute,
                claim_type=evidence_type,
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["material-fact"]
    assert result["original_claim_type"] == claim_type.strip()
    assert result["original_attribute_key"] == claim_attribute.strip().lower()
    assert result["canonical_claim_family"] == "material_composition"
    assert result["canonical_attribute_key"] == "material_composition"


@pytest.mark.parametrize(
    ("goal_type", "evidence_type"),
    [
        ("material", "material"),
        ("material_composition", "material"),
        ("material", "material_composition"),
        ("material_composition", "material_composition"),
    ],
)
def test_base_material_aliases_share_one_canonical_slot(
    goal_type,
    evidence_type,
):
    result = build_claim_resolutions(
        [_claim(goal_type, goal_type)],
        direct_product_facts=[
            _fact("material-fact", evidence_type, claim_type=evidence_type)
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["material-fact"]
    assert result["attribute_key"] == "material_composition"


@pytest.mark.parametrize(
    "claim_type",
    [
        "material_safety",
        "durability",
        "moisture_resistance",
        "non_toxic",
        "food_grade",
        "certification",
        "waterproof",
        "drop_resistance",
        "load_capacity",
        "child_safety",
        "component_material",
        "frame_material",
        "coating_material",
        "surface_material",
    ],
)
def test_base_material_evidence_does_not_support_other_claim_families(
    claim_type,
):
    result = build_claim_resolutions(
        [_claim("", claim_type)],
        direct_product_facts=[
            _fact("material-fact", "material", claim_type="material")
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["evidence_uids"] == []


def test_material_safety_evidence_does_not_support_base_material_claim():
    result = build_claim_resolutions(
        [_claim("material", "material")],
        direct_product_facts=[
            _fact(
                "safety-fact",
                "material_safety",
                claim_type="material_safety",
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["evidence_uids"] == []


def test_material_alias_conflicts_remain_conflicting_and_order_stable():
    claims = [_claim("material_composition", "material")]
    conflicts = [
        _fact(
            "material-pp",
            "material",
            claim_type="material",
            reason="material_conflicting_evidence",
        ),
        _fact(
            "material-abs",
            "material_composition",
            claim_type="material_composition",
            reason="material_conflicting_evidence",
        ),
    ]

    first = build_claim_resolutions(
        claims,
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=conflicts,
    )
    second = build_claim_resolutions(
        claims,
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=list(reversed(conflicts)),
    )

    assert first == second
    assert first[0]["status"] == "conflicting"
    assert first[0]["conflicting_evidence_uids"] == [
        "material-abs",
        "material-pp",
    ]


def test_policy_bounded_inference_uses_only_admitted_premises_and_is_order_stable():
    claims = [_claim("material", "material_composition"), _bounded_goal()]
    facts = [
        _fact(
            "material-b",
            "material",
            claim_type="material_composition",
        ),
        _fact(
            "material-a",
            "material",
            claim_type="material_composition",
        ),
    ]
    kwargs = {
        "direct_policy_facts": [],
        "conflicts": [],
        "bounded_inference_policies": [_bounded_policy()],
        "context_capabilities": {"product_category": {"available": True}},
        "policy_ref_prefix": "domain-policy:fixture@1.0.0",
    }

    first = build_claim_resolutions(
        claims,
        direct_product_facts=facts,
        **kwargs,
    )
    second = build_claim_resolutions(
        list(reversed(claims)),
        direct_product_facts=list(reversed(facts)),
        **kwargs,
    )

    assert first == second
    bounded = next(
        item for item in first if item["goal_ref"] == "goal-durability"
    )
    assert bounded["status"] == "supported"
    assert bounded["support_basis"] == "bounded_inference"
    assert bounded["premise_evidence_uids"] == ["material-a", "material-b"]
    assert bounded["evidence_uids"] == ["material-a", "material-b"]
    assert bounded["inference_policy_refs"] == [
        "domain-policy:fixture@1.0.0:"
        "intent:product_durability_practical_guidance"
    ]
    assert bounded["scope_qualifier"] == "ordinary_minor_accidental_impact"
    assert bounded["required_qualifiers"] == ["no_absolute_guarantee"]
    assert bounded["prohibited_extensions"] == [
        "certification_report",
        "child_safety",
        "warranty",
    ]
    assert bounded["requires_human_review"] is True


@pytest.mark.parametrize(
    ("facts", "policies", "capabilities", "conflicts", "expected_reason"),
    [
        ([], [_bounded_policy()], {"product_category": {"available": True}}, [], "bounded_inference_premise_missing"),
        (
            [_fact("material", "material", claim_type="material_composition")],
            [_bounded_policy()],
            {},
            [],
            "bounded_inference_context_capability_missing",
        ),
        (
            [_fact("material", "material", claim_type="material_composition")],
            [],
            {"product_category": {"available": True}},
            [],
            "bounded_inference_policy_intent_unknown",
        ),
        (
            [_fact("material", "material", claim_type="material_composition")],
            [_bounded_policy()],
            {"product_category": {"available": True}},
            [_fact("material-conflict", "material", claim_type="material_composition")],
            "bounded_inference_premise_conflicting",
        ),
        (
            [_fact("material", "material", claim_type="material_composition")],
            [_bounded_policy(), _bounded_policy()],
            {"product_category": {"available": True}},
            [],
            "bounded_inference_policy_ambiguous",
        ),
    ],
)
def test_policy_bounded_inference_fails_closed_when_contract_is_incomplete(
    facts,
    policies,
    capabilities,
    conflicts,
    expected_reason,
):
    result = build_claim_resolutions(
        [_bounded_goal()],
        direct_product_facts=facts,
        direct_policy_facts=[],
        conflicts=conflicts,
        bounded_inference_policies=policies,
        context_capabilities=capabilities,
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["support_basis"] == "none"
    assert result["evidence_uids"] == []
    assert result["reason"] == expected_reason


def test_policy_bounded_inference_never_resolves_high_risk_goal():
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type="child_safety",
            attribute_key="child_safety",
            semantic_key="child_safety",
        )],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy()],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "bounded_inference_high_risk_prohibited"


@pytest.mark.parametrize(
    ("goal_overrides", "expected_reason"),
    [
        (
            {"policy_intent_ref": "unknown_policy_intent"},
            "bounded_inference_policy_intent_unknown",
        ),
        (
            {"policy_goal_family": "different_goal_family"},
            "bounded_inference_goal_family_mismatch",
        ),
        (
            {"policy_intent_kind": "test_standard_request"},
            "bounded_inference_intent_kind_mismatch",
        ),
    ],
)
def test_policy_binding_requires_exact_trusted_intent_contract(
    goal_overrides,
    expected_reason,
):
    result = build_claim_resolutions(
        [_bounded_goal(**goal_overrides)],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy()],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["support_basis"] == "none"
    assert result["reason"] == expected_reason


def test_policy_binding_without_nomination_stays_unresolved():
    result = build_claim_resolutions(
        [_bounded_goal(
            policy_intent_ref="",
            policy_goal_family="",
            policy_intent_kind="",
        )],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy()],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "no_admitted_direct_evidence"


@pytest.mark.parametrize(
    ("policy_intent_ref", "intent_kind", "expected_reason"),
    [
        (
            "product_durability_absolute_guarantee",
            "absolute_guarantee",
            "bounded_inference_absolute_guarantee_prohibited",
        ),
        (
            "product_durability_test_standard",
            "test_standard_request",
            "bounded_inference_direct_test_evidence_required",
        ),
        (
            "product_durability_warranty_liability",
            "warranty_or_liability_request",
            "bounded_inference_policy_or_service_evidence_required",
        ),
    ],
)
def test_non_practical_policy_intents_remain_unresolved(
    policy_intent_ref,
    intent_kind,
    expected_reason,
):
    result = build_claim_resolutions(
        [_bounded_goal(
            policy_intent_ref=policy_intent_ref,
            policy_intent_kind=intent_kind,
        )],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy(
            policy_intent_ref=policy_intent_ref,
            intent_kind=intent_kind,
        )],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["support_basis"] == "none"
    assert result["reason"] == expected_reason


def test_semantic_key_variation_cannot_change_policy_binding():
    kwargs = {
        "direct_product_facts": [
            _fact("material", "material", claim_type="material_composition")
        ],
        "direct_policy_facts": [],
        "conflicts": [],
        "bounded_inference_policies": [_bounded_policy()],
        "context_capabilities": {"product_category": {"available": True}},
        "policy_ref_prefix": "domain-policy:fixture@1.0.0",
    }

    first = build_claim_resolutions(
        [_bounded_goal(semantic_key="first_free_summary")],
        **kwargs,
    )[0]
    second = build_claim_resolutions(
        [_bounded_goal(semantic_key="unrelated_free_summary")],
        **kwargs,
    )[0]

    for field in (
        "status",
        "support_basis",
        "evidence_uids",
        "premise_evidence_uids",
        "inference_policy_refs",
        "scope_qualifier",
        "reason",
    ):
        assert first[field] == second[field]
