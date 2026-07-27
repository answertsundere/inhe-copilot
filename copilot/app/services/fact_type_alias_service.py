"""Safe fact-type alias helpers for shadow retrieval diagnostics.

The aliases in this module are intentionally conservative. They are used to
expand retrieval candidates in shadow diagnostics only; they do not change the
original query fact type or final answer gates.
"""

from __future__ import annotations

import unicodedata
from typing import Any


LOW_RISK_ALIAS_GROUPS: tuple[set[str], ...] = (
    {"promotion", "promotion_policy", "price_negotiation", "gift_policy"},
    {"stock_shipping", "delivery", "shipping", "logistics"},
    {"aftersales", "aftersales_policy", "return_pickup", "refund_policy", "replacement_policy"},
    {"dimensions", "space_fit", "size"},
    {"invoice", "receipt", "billing", "invoice_policy"},
    {"order_assistance", "purchase_link", "sku_selection"},
)

MEDIUM_RISK_ALIAS_GROUPS: tuple[set[str], ...] = (
    {"installation", "accessory_usage"},
    {"accessory_availability"},
    {"structure_function"},
    {"cleaning", "cleaning_care", "maintenance"},
    {"material"},
    {"material_safety"},
)

# The only canonical registry for claim types that require high-risk evidence.
# Keep aliases here so admission, the final gate, and QA cannot drift apart.
HIGH_RISK_FACT_TYPES = frozenset({
    "age_range",
    "certification_report",
    "child_safety",
    "child_suitability",
    "bite_or_toxicity",
    "electrical_safety",
    "food_grade",
    "formaldehyde_claim",
    "load_capacity",
    "material_safety",
    "non_toxic_claim",
    "pinch_safety",
    "safety_claim",
    "safety_small_parts",
    "stability",
})

_HIGH_RISK_CLAIM_ALIASES = {
    "non_toxic": "non_toxic_claim",
    "non_toxic_claim": "non_toxic_claim",
    "formaldehyde": "formaldehyde_claim",
    "formaldehyde_claim": "formaldehyde_claim",
    "material_safety": "material_safety",
    "food_grade": "food_grade",
    "certification_report": "certification_report",
    "child_safety": "child_safety",
    "child_suitability": "child_suitability",
    "pinch_safety": "pinch_safety",
    "safety": "safety_claim",
    "safety_small_parts": "safety_small_parts",
    "small_parts": "safety_small_parts",
    "small_parts_safety": "safety_small_parts",
    "electrical_safety": "electrical_safety",
    "age_range": "age_range",
    "load_capacity": "load_capacity",
    "stability": "stability",
    "safety_claim": "safety_claim",
    "bite_or_toxicity": "bite_or_toxicity",
}

DIRECT_SOURCE_TYPES = {
    "product_fact",
    "product_facts",
    "dingtalk_product_detail",
    "product_activity_rule",
    "manual",
    "faq",
    "kbqa",
}

NON_DIRECT_EVIDENCE_ROLES = {
    "service_action",
    "fallback_only",
    "media_reference",
    "reference_only",
}

NON_DIRECT_SOURCE_TYPES = {
    "generic_rule",
    "generic_rules",
    "response_templates",
    "media_asset",
}

SAFE_MEDIUM_CROSS_ALIASES = {
    ("installation", "accessory_usage"),
    ("accessory_usage", "installation"),
    ("cleaning", "cleaning_care"),
    ("cleaning_care", "cleaning"),
    ("cleaning_care", "maintenance"),
    ("maintenance", "cleaning_care"),
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_high_risk_claim_type(value: Any) -> str:
    """Return the canonical high-risk claim, or an empty value when unknown."""
    return _HIGH_RISK_CLAIM_ALIASES.get(_clean(value).lower(), "")


_BASE_MATERIAL_COMPOSITION_ALIASES = frozenset({
    "material",
    "material_composition",
})

_CANONICAL_ATTRIBUTE_FAMILIES = (
    {
        "canonical_family": "material_composition",
        "fact_type_aliases": _BASE_MATERIAL_COMPOSITION_ALIASES,
        "canonical_default_attribute_slot": "material_composition",
        "accepted_self_attribute_aliases": frozenset({
            "",
            "material",
            "material_composition",
            "材质",
            "材料",
            "材质组成",
            "材料组成",
            "材质成分",
        }),
        "preserve_specific_attributes": frozenset({
            "material_safety",
            "non_toxic",
            "food_grade",
            "certification",
            "moisture_resistance",
            "waterproof",
            "durability",
            "drop_resistance",
            "load_capacity",
            "child_safety",
            "component_material",
            "frame_material",
            "coating_material",
            "surface_material",
        }),
    },
)


def _normalize_contract_token(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def canonical_material_composition_claim_type(value: Any) -> str:
    """Canonicalize only the legacy base-material claim aliases."""
    claim_type = _normalize_contract_token(value)
    if claim_type in _BASE_MATERIAL_COMPOSITION_ALIASES:
        return "material_composition"
    return claim_type


def canonical_attribute_slot(
    value: Any,
    *,
    fact_type: Any = "",
    supported_claim_types: Any = (),
) -> str:
    """Return a canonical attribute slot without widening fact eligibility."""
    attribute = _normalize_contract_token(value)
    primary_fact_type = _normalize_contract_token(fact_type)
    declared = (
        supported_claim_types
        if isinstance(supported_claim_types, (list, tuple, set, frozenset))
        else (supported_claim_types,)
    )
    declared_types = {
        token
        for item in declared
        if (token := _normalize_contract_token(item))
    }

    for family in _CANONICAL_ATTRIBUTE_FAMILIES:
        aliases = family["fact_type_aliases"]
        if attribute in family["preserve_specific_attributes"]:
            return attribute
        if primary_fact_type:
            belongs_to_family = primary_fact_type in aliases
        else:
            belongs_to_family = bool(declared_types) and declared_types <= aliases
        if (
            belongs_to_family
            and attribute in family["accepted_self_attribute_aliases"]
        ):
            return str(family["canonical_default_attribute_slot"])
    return attribute


def canonical_material_composition_slot(
    value: Any,
    *,
    fact_type: Any = "",
    supported_claim_types: Any = (),
) -> str:
    """Compatibility wrapper for the shared canonical attribute owner."""
    return canonical_attribute_slot(
        value,
        fact_type=fact_type,
        supported_claim_types=supported_claim_types,
    )


def high_risk_claim_types() -> frozenset[str]:
    """Expose the immutable canonical registry to formal safety consumers."""
    return HIGH_RISK_FACT_TYPES


def _group_for(fact_type: str) -> set[str]:
    fact_type = _clean(fact_type)
    for group in (*LOW_RISK_ALIAS_GROUPS, *MEDIUM_RISK_ALIAS_GROUPS):
        if fact_type in group:
            return set(group)
    return {fact_type} if fact_type else set()


def is_high_risk_fact_type(fact_type: str) -> bool:
    return bool(normalize_high_risk_claim_type(fact_type))


def risk_level_for_fact_type(fact_type: str) -> str:
    value = _clean(fact_type)
    if not value:
        return "unknown"
    if is_high_risk_fact_type(value):
        return "high"
    if any(value in group for group in MEDIUM_RISK_ALIAS_GROUPS):
        return "medium"
    if any(value in group for group in LOW_RISK_ALIAS_GROUPS):
        return "low"
    return "medium"


def build_risk_policy_status(
    requested_claims: list[dict[str, Any]],
    *,
    domain_policy_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    """Combine data policy with deterministic safety overrides."""
    pack = domain_policy_pack if isinstance(domain_policy_pack, dict) else {}
    domain_id = _clean(pack.get("domain_id"))
    version = _clean(pack.get("version"))
    policies = pack.get("claim_policies")
    base = {
        "policy_refs": [],
        "source_stage": "deterministic_claim_safety_policy",
        "reason_codes": [],
    }
    if pack.get("status") != "loaded" or not isinstance(policies, dict):
        return {
            **base,
            "status": "unknown",
            "reason_codes": ["domain_policy_not_loaded"],
        }

    levels: list[str] = []
    refs: list[str] = []
    for requested in requested_claims:
        if not isinstance(requested, dict):
            continue
        if requested.get("supporting_only") is True:
            continue
        claim_type = _clean(requested.get("claim_type")).lower()
        if not claim_type:
            return {
                **base,
                "status": "unknown",
                "reason_codes": ["requested_claim_type_missing"],
            }
        policy = policies.get(claim_type)
        if not isinstance(policy, dict):
            return {
                **base,
                "status": "unknown",
                "reason_codes": ["claim_policy_missing"],
            }
        refs.append(f"domain-policy:{domain_id}@{version}:{claim_type}")
        if (
            requested.get("direct_handling_prohibited") is True
            or requested.get("prohibited") is True
            or policy.get("risk_level") == "prohibited"
        ):
            levels.append("prohibited")
            continue
        declared_risk = _clean(requested.get("risk_level")).lower()
        if is_high_risk_fact_type(claim_type) or declared_risk in {
            "high",
            "critical",
        }:
            levels.append("high")
        else:
            levels.append(_clean(policy.get("risk_level")).lower())

    base["policy_refs"] = sorted(set(refs))
    if not levels:
        return {
            **base,
            "status": "unknown",
            "reason_codes": ["requested_claims_missing"],
        }
    if "prohibited" in levels:
        return {**base, "status": "prohibited"}
    if "high" in levels:
        return {**base, "status": "high_risk"}
    if "medium" in levels:
        return {**base, "status": "medium_or_review_required"}
    if all(level == "low" for level in levels):
        return {**base, "status": "low_risk_verified"}
    return {
        **base,
        "status": "unknown",
        "reason_codes": ["domain_policy_risk_invalid"],
    }


def expand_fact_type_aliases(fact_type: str, context: str = "retrieval") -> list[str]:
    """Return safe candidate fact types for shadow retrieval expansion.

    High-risk fields deliberately return only themselves. Material-safety claims
    also stay strict to avoid turning safety questions into ordinary material
    answers.
    """
    value = _clean(fact_type)
    if not value:
        return []
    canonical_high_risk = normalize_high_risk_claim_type(value)
    if canonical_high_risk:
        return [canonical_high_risk]
    aliases = list(dict.fromkeys([value, *sorted(_group_for(value) - {value})]))
    return aliases


def is_alias_candidate(requested: str, candidate: str) -> bool:
    requested = _clean(requested)
    candidate = _clean(candidate)
    return bool(requested and candidate and requested != candidate and candidate in expand_fact_type_aliases(requested))


def _is_direct_evidence(evidence_role: str, source_type: str) -> bool:
    role = _clean(evidence_role)
    source = _clean(source_type)
    if role in NON_DIRECT_EVIDENCE_ROLES or source in NON_DIRECT_SOURCE_TYPES:
        return False
    return source in DIRECT_SOURCE_TYPES or role in {"product_fact_direct", "faq_direct"}


def is_alias_safe_for_direct_answer(
    requested: str,
    candidate: str,
    evidence_role: str = "",
    source_type: str = "",
) -> bool:
    """Return whether a candidate may be counted as direct-answerable.

    This is stricter than retrieval expansion. service_action/media_reference
    rows are useful diagnostics, but they never become direct answer evidence.
    """
    requested = _clean(requested)
    candidate = _clean(candidate)
    if not requested or not candidate:
        return False
    if not _is_direct_evidence(evidence_role, source_type):
        return False
    requested_high_risk = normalize_high_risk_claim_type(requested)
    candidate_high_risk = normalize_high_risk_claim_type(candidate)
    if requested_high_risk or candidate_high_risk:
        return bool(requested_high_risk and requested_high_risk == candidate_high_risk)
    if requested == candidate:
        return True
    requested_group = _group_for(requested)
    candidate_group = _group_for(candidate)
    if requested_group != candidate_group:
        return False
    if risk_level_for_fact_type(requested) == "medium":
        return (requested, candidate) in SAFE_MEDIUM_CROSS_ALIASES
    return True

