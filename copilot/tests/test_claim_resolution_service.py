from __future__ import annotations

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
