from __future__ import annotations

import pytest

from app.services.claim_resolution_service import build_claim_resolutions, expand_claim_dependencies


def _claim(attribute_key: str = "", claim_type: str = "dimensions") -> dict[str, str]:
    return {"claim_type": claim_type, "attribute_key": attribute_key, "question": "", "risk_level": "medium"}


def _fact(
    uid: str,
    attribute_key: str,
    *,
    claim_type: str = "dimensions",
    reason: str = "",
    subject_scope: str = "",
) -> dict[str, str | list[str]]:
    return {
        "evidence_uid": uid,
        "attribute_key": attribute_key,
        "claim_types_supported": [claim_type],
        "text": f"{attribute_key} fact",
        "reason": reason,
        "subject_scope": subject_scope,
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
        "allowed_conclusion_family": "ordinary_minor_impact_tolerance",
        "allowed_variability_factor_families": [
            "contact_surface",
            "impact_angle",
            "impact_height",
        ],
        "advice_mode": "none",
        "maximum_risk_level": "medium",
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


def _only_policy_option(result: dict) -> dict:
    options = result["eligible_policy_options"]
    assert len(options) == 1
    return options[0]


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


def test_overall_dimension_goal_selects_only_a_product_scoped_axis():
    result = build_claim_resolutions(
        [_claim("overall_width")],
        direct_product_facts=[
            _fact("component-width", "width", subject_scope="component"),
            _fact("packaging-width", "width", subject_scope="packaging"),
            _fact("product-width", "width", subject_scope="product"),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["attribute_key"] == "width"
    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["product-width"]


def test_overall_dimension_goal_requires_explicit_product_scope():
    result = build_claim_resolutions(
        [_claim("overall_height")],
        direct_product_facts=[_fact("unscoped-height", "height")],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "subject_scope_evidence_missing"


def test_aggregate_dimension_goal_accepts_complete_packaging_axis_set():
    result = build_claim_resolutions(
        [_claim("overall_dimensions") | {"subject_scope": "packaging"}],
        direct_product_facts=[
            _fact("packaging-width", "width", subject_scope="packaging"),
            _fact("packaging-length", "length", subject_scope="packaging"),
            _fact("packaging-height", "height", subject_scope="packaging"),
            _fact("product-width", "width", subject_scope="product"),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == [
        "packaging-height",
        "packaging-length",
        "packaging-width",
    ]


def test_aggregate_dimension_goal_rejects_incomplete_axis_set():
    result = build_claim_resolutions(
        [_claim("overall_dimensions") | {"subject_scope": "packaging"}],
        direct_product_facts=[
            _fact("packaging-width", "width", subject_scope="packaging"),
            _fact("packaging-height", "height", subject_scope="packaging"),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "overall_dimensions_incomplete"


def test_dimension_resolution_uses_canonical_attribute_key_over_source_label():
    result = build_claim_resolutions(
        [_claim("overall_dimensions") | {"subject_scope": "packaging"}],
        direct_product_facts=[
            _fact(
                "packaging-width",
                "source_width_label",
                subject_scope="packaging",
            ) | {"canonical_attribute_key": "width"},
            _fact(
                "packaging-length",
                "source_length_label",
                subject_scope="packaging",
            ) | {"canonical_attribute_key": "length"},
            _fact(
                "packaging-height",
                "source_height_label",
                subject_scope="packaging",
            ) | {"canonical_attribute_key": "height"},
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == [
        "packaging-height",
        "packaging-length",
        "packaging-width",
    ]


def test_unscoped_dimension_goal_never_selects_a_non_product_measurement():
    result = build_claim_resolutions(
        [_claim("width")],
        direct_product_facts=[
            _fact("product-width", "width", subject_scope="product"),
            _fact("packaging-width", "width", subject_scope="packaging"),
            _fact("component-width", "width", subject_scope="component"),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["product-width"]


def test_unscoped_dimension_goal_keeps_legacy_unscoped_evidence_compatibility():
    result = build_claim_resolutions(
        [_claim("width")],
        direct_product_facts=[_fact("legacy-width", "width")],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["legacy-width"]


def test_product_aggregate_dimension_label_satisfies_overall_dimensions():
    result = build_claim_resolutions(
        [_claim("overall_dimensions")],
        direct_product_facts=[
            _fact(
                "product-overall-dimensions",
                "尺寸",
                subject_scope="product",
            ),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["product-overall-dimensions"]


def test_ambiguous_unattributed_claim_does_not_absorb_multiple_attributes():
    result = build_claim_resolutions(
        [_claim()],
        direct_product_facts=[_fact("width", "width"), _fact("height", "height")],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "selection_ambiguous"


def test_unattributed_aggregate_claim_prefers_its_canonical_aggregate_fact():
    result = build_claim_resolutions(
        [_claim(claim_type="color_options")],
        direct_product_facts=[
            _fact(
                "product-color-options",
                "color_options",
                claim_type="color_options",
                subject_scope="product",
            ),
            _fact(
                "current-sku-color",
                "color",
                claim_type="color_options",
                subject_scope="product",
            ),
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["product-color-options"]


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
    assert bounded["status"] == "unresolved"
    assert bounded["support_basis"] == "none"
    assert bounded["premise_evidence_uids"] == []
    assert bounded["evidence_uids"] == []
    assert bounded["inference_policy_refs"] == []
    option = _only_policy_option(bounded)
    assert option["policy_ref"] == (
        "domain-policy:fixture@1.0.0:"
        "intent:product_durability_practical_guidance"
    )
    assert option["premise_evidence_refs"] == [
        "material-a",
        "material-b",
    ]
    assert option["premise_families"] == ["material_composition"]
    assert option["allowed_scope"] == "ordinary_minor_accidental_impact"
    assert option["allowed_conclusion_family"] == (
        "ordinary_minor_impact_tolerance"
    )
    assert option["allowed_variability_factor_families"] == [
        "contact_surface",
        "impact_angle",
        "impact_height",
    ]
    assert option["advice_mode"] == "none"
    assert option["requested_risk"] == "medium"
    assert option["maximum_risk"] == "medium"
    assert option["review_only"] is True
    assert option["required_qualifiers"] == ["no_absolute_guarantee"]
    assert option["forbidden_claim_families"] == [
        "certification_report",
        "child_safety",
        "warranty",
    ]
    assert option["applicable_goal_ref"] == "goal-durability"
    assert option["trusted_domain_pack_ref"] == (
        "domain-policy:fixture@1.0.0"
    )
    assert option["option_provenance"] == {
        "filter_owner": "claim_resolution",
        "intent_narrowed": True,
        "policy_owner": "domain_policy_pack",
        "premise_owner": "admitted_answer_context",
    }
    assert bounded["requires_human_review"] is True


def test_policy_bounded_inference_resolves_canonical_unmapped_customer_goal():
    result = build_claim_resolutions(
        [_bounded_goal(claim_type="", claim_type_status="unmapped")],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy()],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["claim_type"] == ""
    assert result["claim_type_status"] == "unmapped"
    assert result["status"] == "unresolved"
    assert result["support_basis"] == "none"
    assert result["premise_evidence_uids"] == []
    assert _only_policy_option(result)["premise_evidence_refs"] == [
        "material"
    ]


def test_policy_options_do_not_replace_direct_support_for_practical_goal():
    policy = _bounded_policy(
        policy_intent_ref="product_weight_practical_guidance",
        goal_family="product_weight_and_moving",
        premise_fact_families=["gross_weight"],
        allowed_scope="approximate_short_distance_moving_effort",
    )
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type="gross_weight",
            claim_type_status="mapped",
            attribute_key="gross_weight",
            policy_intent_ref="product_weight_practical_guidance",
            policy_goal_family="product_weight_and_moving",
        )],
        direct_product_facts=[
            _fact("gross-weight", "gross_weight", claim_type="gross_weight")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[policy],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "supported"
    assert result["support_basis"] == "direct_evidence"
    assert result["evidence_uids"] == ["gross-weight"]
    assert result["premise_evidence_uids"] == []
    option = _only_policy_option(result)
    assert option["premise_evidence_refs"] == ["gross-weight"]
    assert option["allowed_scope"] == (
        "approximate_short_distance_moving_effort"
    )


def test_supported_goal_without_policy_nomination_stays_direct_only():
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type="material_composition",
            claim_type_status="mapped",
            attribute_key="material",
            policy_intent_ref="",
            policy_goal_family="",
            policy_intent_kind="",
        )],
        direct_product_facts=[
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[
            _bounded_policy(),
            _bounded_policy(
                policy_intent_ref="cleaning_chemical_contact_practical_guidance",
                goal_family="cleaning_care",
                allowed_scope="unverified_chemical_cleaning_boundary",
            ),
        ],
        context_capabilities={
            "product_category": {"available": True},
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "supported"
    assert result["support_basis"] == "direct_evidence"
    assert result["evidence_uids"] == ["material"]
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == ""


def test_cleaning_goal_without_exact_intent_offers_method_specific_options():
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type="cleaning_care",
            attribute_key="cleaning_care",
            semantic_key="",
            policy_intent_ref="",
            policy_goal_family="cleaning_care",
            policy_intent_kind="practical_guidance",
            goal_summary="了解当前清洁方式的保守边界",
        )],
        direct_product_facts=[
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[
            _bounded_policy(
                policy_intent_ref=(
                    "cleaning_chemical_contact_practical_guidance"
                ),
                goal_family="cleaning_care",
                allowed_scope="unverified_chemical_cleaning_boundary",
            ),
            _bounded_policy(
                policy_intent_ref=(
                    "cleaning_high_temperature_practical_guidance"
                ),
                goal_family="cleaning_care",
                allowed_scope=(
                    "unverified_high_temperature_cleaning_boundary"
                ),
            ),
        ],
        context_capabilities={
            "product_category": {"available": True},
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert [
        option["policy_intent_ref"]
        for option in result["eligible_policy_options"]
    ] == [
        "cleaning_chemical_contact_practical_guidance",
        "cleaning_high_temperature_practical_guidance",
    ]


@pytest.mark.parametrize(
    (
        "claim_type",
        "attribute_key",
        "policy_intent_ref",
        "goal_family",
        "premise_fact_family",
    ),
    [
        (
            "space_fit",
            "space_fit",
            "product_dimensions_practical_guidance",
            "product_dimensions_and_space",
            "dimensions",
        ),
        (
            "gross_weight",
            "gross_weight",
            "product_weight_practical_guidance",
            "product_weight_and_moving",
            "gross_weight",
        ),
        (
            "variant_compare",
            "variant_compare",
            "variant_specification_practical_comparison",
            "variant_specification_comparison",
            "variant_compare",
        ),
        (
            "cleaning_care",
            "cleaning_care",
            "cleaning_chemical_contact_practical_guidance",
            "cleaning_care",
            "material_composition",
        ),
        (
            "cleaning_care",
            "cleaning_care",
            "cleaning_high_temperature_practical_guidance",
            "cleaning_care",
            "material_composition",
        ),
        (
            "moisture_resistance",
            "moisture_resistance",
            "moisture_exposure_practical_guidance",
            "moisture_resistance",
            "material_composition",
        ),
        (
            "detachable",
            "detachable",
            "detachable_storage_practical_guidance",
            "detachable_storage_convenience",
            "detachable",
        ),
    ],
)
def test_generic_policy_families_resolve_from_exact_admitted_premises(
    claim_type,
    attribute_key,
    policy_intent_ref,
    goal_family,
    premise_fact_family,
):
    policy = _bounded_policy(
        policy_intent_ref=policy_intent_ref,
        goal_family=goal_family,
        premise_fact_families=[premise_fact_family],
        allowed_scope=f"{goal_family}_scope",
    )
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type=claim_type,
            claim_type_status="mapped",
            attribute_key=attribute_key,
            policy_intent_ref=policy_intent_ref,
            policy_goal_family=goal_family,
        )],
        direct_product_facts=[
            _fact(
                f"premise-{premise_fact_family}",
                attribute_key,
                claim_type=premise_fact_family,
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[policy],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    option = _only_policy_option(result)
    assert result["support_basis"] in {"direct_evidence", "none"}
    assert option["premise_evidence_refs"] == [
        f"premise-{premise_fact_family}"
    ]
    assert option["review_only"] is True


@pytest.mark.parametrize(
    ("policy_maximum", "goal_risk", "expected_reason"),
    [
        ("low", "medium", "bounded_inference_risk_limit_exceeded"),
        ("unknown", "low", "bounded_inference_risk_contract_invalid"),
    ],
)
def test_policy_bounded_inference_enforces_risk_contract(
    policy_maximum,
    goal_risk,
    expected_reason,
):
    result = build_claim_resolutions(
        [_bounded_goal(risk_level=goal_risk)],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[
            _bounded_policy(maximum_risk_level=policy_maximum)
        ],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["support_basis"] == "none"
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == expected_reason


@pytest.mark.parametrize(
    "policy_mutation",
    [
        {"allowed_conclusion_family": ""},
        {"allowed_variability_factor_families": None},
        {
            "allowed_variability_factor_families": [
                "impact_height",
                "impact_height",
            ]
        },
        {"advice_mode": "free_form_advice"},
    ],
)
def test_policy_bounded_inference_requires_complete_semantic_budget(
    policy_mutation,
):
    result = build_claim_resolutions(
        [_bounded_goal()],
        direct_product_facts=[
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[
            _bounded_policy(**policy_mutation)
        ],
        context_capabilities={
            "product_category": {"available": True}
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == (
        "bounded_inference_semantic_budget_invalid"
    )


@pytest.mark.parametrize(
    "goal_overrides",
    [
        {"goal_kind": "service_action"},
        {"goal_kind": "media_request"},
        {"supporting_only": True},
    ],
)
def test_policy_bounded_inference_rejects_non_customer_fact_goals(
    goal_overrides,
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
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == (
        "bounded_inference_goal_kind_prohibited"
    )


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
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == expected_reason


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
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == (
        "bounded_inference_high_risk_prohibited"
    )


def test_oral_exposure_goal_offers_only_goal_owned_safety_handling():
    policy = _bounded_policy(
        policy_intent_ref="oral_exposure_safety_handling",
        goal_family="bite_or_toxicity",
        premise_fact_families=[],
        allowed_scope="interrupt_exposure_inspect_and_escalate_if_needed",
        allowed_conclusion_family="general_oral_exposure_risk_mitigation",
        allowed_variability_factor_families=[],
        advice_mode="safety_handoff_required",
        required_qualifiers=[
            "stop_further_oral_contact",
            "inspect_for_damage_or_missing_fragments",
            "seek_medical_help_if_ingested_or_symptomatic",
            "no_toxicity_or_ingestion_safety_conclusion",
        ],
        prohibited_claim_families=[
            "bite_or_toxicity",
            "child_safety",
            "material_safety",
            "non_toxic_claim",
        ],
    )
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type="bite_or_toxicity",
            claim_type_status="mapped",
            attribute_key="bite_or_toxicity",
            semantic_key="bite_or_toxicity",
            risk_level="low",
            policy_intent_ref="",
            policy_goal_family="bite_or_toxicity",
            policy_intent_kind="practical_guidance",
        )],
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[policy],
        context_capabilities={
            "product_category": {"available": True},
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["reason"] == "high_risk_factual_claim_prohibited"
    assert result["requested_claim_risk"] == "high"
    assert result["evidence_uids"] == []
    assert result["premise_evidence_uids"] == []
    assert result["restricted_request_boundary"] == {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "high_risk_factual_claim_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": "",
        "policy_goal_family": "bite_or_toxicity",
        "policy_intent_kind": "practical_guidance",
        "high_risk_claim_families": ["bite_or_toxicity"],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    option = _only_policy_option(result)
    assert option["premise_evidence_refs"] == []
    assert option["premise_families"] == []
    assert option["advice_mode"] == "safety_handoff_required"
    assert option["requested_claim_risk"] == "high"
    assert option["answer_strategy_risk"] == "medium"
    assert option["option_provenance"]["premise_owner"] == (
        "authoritative_customer_goal"
    )
    assert option["option_provenance"][
        "alternative_for_restricted_request"
    ] is True


def test_absolute_guarantee_keeps_restricted_boundary_and_offers_safe_strategy():
    absolute = _bounded_policy(
        policy_intent_ref="product_durability_absolute_guarantee",
        intent_kind="absolute_guarantee",
        allowed_scope="absolute_guarantee_disallowed",
    )
    goal = _bounded_goal(
        risk_level="high",
        policy_intent_ref="product_durability_absolute_guarantee",
        policy_intent_kind="absolute_guarantee",
    )
    kwargs = {
        "direct_product_facts": [
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            )
        ],
        "direct_policy_facts": [],
        "conflicts": [],
        "context_capabilities": {
            "product_category": {"available": True}
        },
        "policy_ref_prefix": "domain-policy:fixture@1.0.0",
    }

    first = build_claim_resolutions(
        [goal],
        bounded_inference_policies=[absolute, _bounded_policy()],
        **kwargs,
    )[0]
    second = build_claim_resolutions(
        [goal],
        bounded_inference_policies=[_bounded_policy(), absolute],
        **kwargs,
    )[0]

    assert first == second
    assert first["status"] == "unresolved"
    assert first["support_basis"] == "none"
    assert first["evidence_uids"] == []
    assert first["reason"] == "absolute_guarantee_prohibited"
    assert first["requested_claim_risk"] == "high"
    assert first["restricted_request_boundary"] == {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "absolute_guarantee_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": (
            "product_durability_absolute_guarantee"
        ),
        "policy_goal_family": "product_durability",
        "policy_intent_kind": "absolute_guarantee",
        "high_risk_claim_families": [],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    option = _only_policy_option(first)
    assert option["policy_intent_ref"] == (
        "product_durability_practical_guidance"
    )
    assert option["intent_kind"] == "practical_guidance"
    assert option["requested_risk"] == "high"
    assert option["requested_claim_risk"] == "high"
    assert option["answer_strategy_risk"] == "medium"
    assert option["maximum_risk"] == "medium"
    assert option["restricted_request_boundary"] == first[
        "restricted_request_boundary"
    ]
    assert option["option_provenance"][
        "alternative_for_restricted_request"
    ] is True
    assert option["option_provenance"]["intent_narrowed"] is False


def test_explicit_practical_sibling_owns_duplicate_restricted_alternative():
    absolute_policy = _bounded_policy(
        policy_intent_ref="product_durability_absolute_guarantee",
        intent_kind="absolute_guarantee",
        allowed_scope="absolute_guarantee_disallowed",
    )
    absolute_goal = _bounded_goal(
        goal_ref="goal-absolute",
        risk_level="high",
        policy_intent_ref="product_durability_absolute_guarantee",
        policy_intent_kind="absolute_guarantee",
    )
    practical_goal = _bounded_goal(goal_ref="goal-practical")
    kwargs = {
        "direct_product_facts": [
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            )
        ],
        "direct_policy_facts": [],
        "conflicts": [],
        "bounded_inference_policies": [
            absolute_policy,
            _bounded_policy(),
        ],
        "context_capabilities": {
            "product_category": {"available": True}
        },
        "policy_ref_prefix": "domain-policy:fixture@1.0.0",
    }

    first = build_claim_resolutions(
        [absolute_goal, practical_goal],
        **kwargs,
    )
    second = build_claim_resolutions(
        [practical_goal, absolute_goal],
        **kwargs,
    )

    assert first == second
    by_goal = {item["goal_ref"]: item for item in first}
    restricted = by_goal["goal-absolute"]
    practical = by_goal["goal-practical"]
    assert restricted["restricted_request_boundary"][
        "must_remain_unresolved"
    ] is True
    assert restricted["eligible_policy_options"] == []
    assert restricted["bounded_inference_rejection_reason"] == (
        "bounded_inference_alternative_owned_by_sibling_goal"
    )
    assert _only_policy_option(practical)["policy_intent_ref"] == (
        "product_durability_practical_guidance"
    )


def test_high_risk_practical_request_without_boundary_has_no_option():
    result = build_claim_resolutions(
        [_bounded_goal(
            risk_level="high",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
            policy_intent_kind="practical_guidance",
        )],
        direct_product_facts=[
            _fact(
                "material",
                "material",
                claim_type="material_composition",
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[_bounded_policy()],
        context_capabilities={
            "product_category": {"available": True}
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "unresolved"
    assert result["restricted_request_boundary"] == {}
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == (
        "bounded_inference_high_risk_prohibited"
    )


def test_high_risk_supported_fact_is_preserved_without_strategy_option():
    policy = _bounded_policy(
        policy_intent_ref="product_weight_practical_guidance",
        goal_family="product_weight_and_moving",
        premise_fact_families=["gross_weight"],
        allowed_scope="approximate_short_distance_moving_effort",
    )
    result = build_claim_resolutions(
        [_bounded_goal(
            claim_type="gross_weight",
            claim_type_status="mapped",
            attribute_key="gross_weight",
            risk_level="high",
            policy_intent_ref="product_weight_practical_guidance",
            policy_goal_family="product_weight_and_moving",
        )],
        direct_product_facts=[
            _fact(
                "gross-weight",
                "gross_weight",
                claim_type="gross_weight",
            )
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[policy],
        context_capabilities={
            "product_category": {"available": True}
        },
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["gross-weight"]
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == (
        "bounded_inference_high_risk_prohibited"
    )


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
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == expected_reason


def test_policy_binding_without_intent_ref_uses_owner_goal_family_only():
    result = build_claim_resolutions(
        [_bounded_goal(
            policy_intent_ref="",
            policy_goal_family="product_durability",
            policy_intent_kind="practical_guidance",
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
    option = _only_policy_option(result)
    assert option["policy_intent_ref"] == (
        "product_durability_practical_guidance"
    )
    assert option["option_provenance"]["intent_narrowed"] is False
    assert result["inference_policy_refs"] == []
    assert result["premise_evidence_uids"] == []


def test_policy_binding_without_intent_ref_excludes_other_goal_families():
    alternate = _bounded_policy(
        policy_intent_ref="material_daily_use_practical_guidance",
        goal_family="material_daily_use",
        allowed_scope="ordinary_daily_material_handling",
    )
    result = build_claim_resolutions(
        [_bounded_goal(
            policy_intent_ref="",
            policy_goal_family="product_durability",
            policy_intent_kind="practical_guidance",
        )],
        direct_product_facts=[
            _fact("material", "material", claim_type="material_composition")
        ],
        direct_policy_facts=[],
        conflicts=[],
        bounded_inference_policies=[alternate, _bounded_policy()],
        context_capabilities={"product_category": {"available": True}},
        policy_ref_prefix="domain-policy:fixture@1.0.0",
    )[0]

    assert [
        option["policy_intent_ref"]
        for option in result["eligible_policy_options"]
    ] == [
        "product_durability_practical_guidance",
    ]
    assert all(
        option["option_provenance"]["intent_narrowed"] is False
        for option in result["eligible_policy_options"]
    )


def test_policy_binding_without_owner_goal_family_offers_no_options():
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

    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == (
        "bounded_inference_policy_goal_family_missing"
    )


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
    assert result["eligible_policy_options"] == []
    assert result["bounded_inference_rejection_reason"] == expected_reason


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
        "eligible_policy_options",
        "scope_qualifier",
        "reason",
    ):
        assert first[field] == second[field]
