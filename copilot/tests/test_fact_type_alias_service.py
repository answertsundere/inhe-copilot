from __future__ import annotations


def test_low_risk_promotion_alias_is_direct_safe_for_product_fact():
    from app.services.fact_type_alias_service import (
        expand_fact_type_aliases,
        is_alias_safe_for_direct_answer,
    )

    aliases = expand_fact_type_aliases("promotion_policy")

    assert "price_negotiation" in aliases
    assert is_alias_safe_for_direct_answer(
        "promotion_policy",
        "price_negotiation",
        "product_fact_direct",
        "product_facts",
    ) is True


def test_high_risk_load_capacity_does_not_alias_to_weight():
    from app.services.fact_type_alias_service import (
        expand_fact_type_aliases,
        is_alias_safe_for_direct_answer,
        is_high_risk_fact_type,
    )

    assert is_high_risk_fact_type("load_capacity") is True
    assert expand_fact_type_aliases("load_capacity") == ["load_capacity"]
    assert is_alias_safe_for_direct_answer(
        "load_capacity",
        "gross_weight",
        "product_fact_direct",
        "product_facts",
    ) is False


def test_canonical_high_risk_registry_normalizes_aliases_without_promoting_material():
    from app.services.fact_type_alias_service import (
        high_risk_claim_types,
        is_alias_safe_for_direct_answer,
        is_high_risk_fact_type,
        normalize_high_risk_claim_type,
    )

    assert high_risk_claim_types() >= {
        "food_grade", "non_toxic_claim", "formaldehyde_claim",
        "material_safety", "child_safety", "child_suitability",
        "pinch_safety", "certification_report", "electrical_safety",
        "age_range", "load_capacity", "stability", "safety_claim",
        "safety_small_parts",
    }
    assert normalize_high_risk_claim_type("non_toxic") == "non_toxic_claim"
    assert normalize_high_risk_claim_type("formaldehyde") == "formaldehyde_claim"
    assert normalize_high_risk_claim_type("small_parts") == "safety_small_parts"
    assert is_high_risk_fact_type("material") is False
    assert is_alias_safe_for_direct_answer(
        "food_grade", "food_grade", "product_fact_direct", "product_facts"
    ) is True
    assert is_alias_safe_for_direct_answer(
        "food_grade", "material", "product_fact_direct", "product_facts"
    ) is False


def test_service_action_and_media_reference_are_not_direct_answer_aliases():
    from app.services.fact_type_alias_service import is_alias_safe_for_direct_answer

    assert is_alias_safe_for_direct_answer(
        "promotion_policy",
        "price_negotiation",
        "service_action",
        "generic_rule",
    ) is False
    assert is_alias_safe_for_direct_answer(
        "installation",
        "accessory_usage",
        "media_reference",
        "media_asset",
    ) is False


def test_medium_installation_alias_is_limited_to_safe_pair():
    from app.services.fact_type_alias_service import is_alias_safe_for_direct_answer

    assert is_alias_safe_for_direct_answer(
        "installation",
        "accessory_usage",
        "product_fact_direct",
        "product_facts",
    ) is True
    assert is_alias_safe_for_direct_answer(
        "installation",
        "accessory_availability",
        "product_fact_direct",
        "product_facts",
    ) is False

