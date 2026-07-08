"""Safe fact-type alias helpers for shadow retrieval diagnostics.

The aliases in this module are intentionally conservative. They are used to
expand retrieval candidates in shadow diagnostics only; they do not change the
original query fact type or final answer gates.
"""

from __future__ import annotations

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

HIGH_RISK_FACT_TYPES = {
    "certification_report",
    "safety_claim",
    "child_suitability",
    "age_range",
    "load_capacity",
    "electrical_safety",
    "food_grade",
    "non_toxic_claim",
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


def _group_for(fact_type: str) -> set[str]:
    fact_type = _clean(fact_type)
    for group in (*LOW_RISK_ALIAS_GROUPS, *MEDIUM_RISK_ALIAS_GROUPS):
        if fact_type in group:
            return set(group)
    return {fact_type} if fact_type else set()


def is_high_risk_fact_type(fact_type: str) -> bool:
    return _clean(fact_type) in HIGH_RISK_FACT_TYPES


def risk_level_for_fact_type(fact_type: str) -> str:
    value = _clean(fact_type)
    if not value:
        return "unknown"
    if value in HIGH_RISK_FACT_TYPES:
        return "high"
    if any(value in group for group in MEDIUM_RISK_ALIAS_GROUPS):
        return "medium"
    if any(value in group for group in LOW_RISK_ALIAS_GROUPS):
        return "low"
    return "medium"


def expand_fact_type_aliases(fact_type: str, context: str = "retrieval") -> list[str]:
    """Return safe candidate fact types for shadow retrieval expansion.

    High-risk fields deliberately return only themselves. Material-safety claims
    also stay strict to avoid turning safety questions into ordinary material
    answers.
    """
    value = _clean(fact_type)
    if not value:
        return []
    if is_high_risk_fact_type(value) or value == "material_safety":
        return [value]
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
    if requested == candidate:
        return True
    if is_high_risk_fact_type(requested) or is_high_risk_fact_type(candidate):
        return False
    if requested == "material_safety" or candidate == "material_safety":
        return False
    requested_group = _group_for(requested)
    candidate_group = _group_for(candidate)
    if requested_group != candidate_group:
        return False
    if risk_level_for_fact_type(requested) == "medium":
        return (requested, candidate) in SAFE_MEDIUM_CROSS_ALIASES
    return True

