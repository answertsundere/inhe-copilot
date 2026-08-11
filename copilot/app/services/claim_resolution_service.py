"""Resolve requested claims against already admitted evidence.

This service is read-only.  It does not retrieve, generate customer wording, or
change any formal response field.  It gives shadow planners a deterministic
claim-by-claim boundary after evidence admission has completed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.fact_type_alias_service import (
    canonical_attribute_slot,
    canonical_dimension_subject_scope,
    canonical_material_composition_claim_type,
    is_dimension_claim_type,
    normalize_high_risk_claim_type,
)
from app.services.product_media_annotation_schema_service import canonical_dimension_attribute


# A supporting claim makes an independently admitted fact available for a
# partial answer.  It never changes the status of the claim that requested the
# support.  In particular, material composition cannot establish safety,
# certification, care, odour, or toxicity.
CLAIM_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "material_safety": ("material_composition",),
    "non_toxic_claim": ("material_composition",),
    "bite_or_toxicity": ("material_composition",),
    "odor": ("material_composition",),
    "cleaning_care": ("material_composition",),
    "moisture_resistance": ("material_composition",),
    "certification_report": ("material_composition",),
    "food_grade": ("material_composition",),
}

_BOUNDED_INFERENCE_RISK_RANK = {
    "low": 0,
    "medium": 1,
}
_REQUEST_CLAIM_RISK_LEVELS = {
    "low",
    "medium",
    "high",
    "critical",
    "prohibited",
}

_DIMENSION_CLAIM_TYPES = frozenset({"dimensions", "size", "space_fit"})
_PRODUCT_OVERALL_DIMENSION_ATTRIBUTES = frozenset({
    "overall_width",
    "overall_height",
    "overall_depth",
    "overall_length",
    "overall_diameter",
    "overall_thickness",
    "overall_dimensions",
})
_PRODUCT_OVERALL_SUBJECT_SCOPES = frozenset({"product", "product_overall"})
_RESTRICTED_REQUEST_INTENT_REASONS = {
    "absolute_guarantee": "absolute_guarantee_prohibited",
    "test_standard_request": "direct_test_evidence_required",
    "warranty_or_liability_request": "policy_or_service_evidence_required",
}
_RESTRICTED_OPTION_REASONS = {
    "absolute_guarantee": "bounded_inference_absolute_guarantee_prohibited",
    "test_standard_request": (
        "bounded_inference_direct_test_evidence_required"
    ),
    "warranty_or_liability_request": (
        "bounded_inference_policy_or_service_evidence_required"
    ),
}


def _structured_sha256(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return (
        candidate
        if len(candidate) == 64
        and all(character in "0123456789abcdef" for character in candidate)
        else ""
    )


def expand_claim_dependencies(requested_claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add declared supporting claims without weakening their parent claims.

    The result is deterministic and contains one record per claim type and
    attribute slot.  The caller still resolves every parent claim against its
    own direct evidence; a supporting material fact is only a separately
    answerable clause.
    """
    prepared = [dict(item) for item in requested_claims if isinstance(item, dict)]
    existing = {
        (sanitize_text(item.get("claim_type")).lower(), _attribute_key(item))
        for item in prepared
        if sanitize_text(item.get("claim_type"))
    }
    additions: list[dict[str, Any]] = []
    for item in sorted(prepared, key=_claim_uid):
        claim_type = sanitize_text(item.get("claim_type")).lower()
        for supporting_type in CLAIM_DEPENDENCIES.get(claim_type, ()):
            supporting_attribute = _attribute_key({"claim_type": supporting_type})
            key = (supporting_type, supporting_attribute)
            if key in existing:
                continue
            existing.add(key)
            additions.append({
                "claim_type": supporting_type,
                "attribute_key": supporting_attribute,
                "question": sanitize_text(item.get("question")),
                "risk_level": "medium",
                "supporting_for_claim_type": claim_type,
                "supporting_only": True,
            })
    return sorted([*prepared, *additions], key=_claim_uid)


def _claim_types(fact: dict[str, Any]) -> set[str]:
    values = fact.get("claim_types_supported") or []
    if not isinstance(values, list):
        values = [values]
    return {sanitize_text(value).lower() for value in values if sanitize_text(value)}


def _canonical_claim_type(value: str) -> str:
    """Unify only the explicit legacy material/composition aliases."""
    return canonical_material_composition_claim_type(value)


def _original_attribute_key(item: dict[str, Any]) -> str:
    return sanitize_text(
        item.get("attribute_key")
        or item.get("field_name")
        or item.get("fact_key")
        or item.get("structured_field")
    )


def _attribute_key(item: dict[str, Any]) -> str:
    value = _original_attribute_key(item).lower()
    normalized_attribute = canonical_dimension_attribute(value) if value else ""
    claim_type = sanitize_text(item.get("claim_type") or item.get("fact_type")).lower()
    return canonical_attribute_slot(
        normalized_attribute,
        fact_type=claim_type,
        supported_claim_types=_claim_types(item),
    )


def _facts_for_claim(claim_type: str, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical_claim_type = _canonical_claim_type(claim_type)
    return sorted(
        [
            fact for fact in facts
            if canonical_claim_type in {_canonical_claim_type(value) for value in _claim_types(fact)}
        ],
        key=lambda fact: ( _attribute_key(fact), sanitize_text(fact.get("evidence_uid"))),
    )


def _requested_subject_scope(item: dict[str, Any]) -> str | None:
    """Return an explicit subject constraint encoded by a structured request."""
    claim_type = sanitize_text(item.get("claim_type")).lower()
    if not is_dimension_claim_type(claim_type):
        return None
    explicit_scope = canonical_dimension_subject_scope(
        item.get("subject_scope")
    )
    if explicit_scope:
        return explicit_scope
    original_attribute = canonical_dimension_attribute(
        _original_attribute_key(item).lower()
    )
    if (
        original_attribute in _PRODUCT_OVERALL_DIMENSION_ATTRIBUTES
    ):
        return "product"
    return ""


def _matches_subject_scope(
    fact: dict[str, Any],
    required_scope: str | None,
) -> bool:
    if required_scope is None:
        return True
    subject_scope = sanitize_text(fact.get("subject_scope")).lower()
    if not required_scope:
        return not subject_scope or subject_scope in _PRODUCT_OVERALL_SUBJECT_SCOPES
    if required_scope == "product":
        return subject_scope in _PRODUCT_OVERALL_SUBJECT_SCOPES
    return subject_scope == required_scope


def _select_for_attribute(
    requested_attribute: str,
    candidates: list[dict[str, Any]],
    *,
    required_subject_scope: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Select evidence by declared attribute without inferring from free text."""
    if requested_attribute:
        matching = [fact for fact in candidates if _attribute_key(fact) == requested_attribute]
        if matching:
            scoped = [
                fact for fact in matching
                if _matches_subject_scope(fact, required_subject_scope)
            ]
            if required_subject_scope is not None:
                if scoped:
                    return scoped, ""
                if not required_subject_scope:
                    return [], "subject_scope_missing"
                if any(
                    not sanitize_text(fact.get("subject_scope"))
                    for fact in matching
                ):
                    return [], "subject_scope_evidence_missing"
                return [], "subject_scope_mismatch"
            return matching, ""
        if any(not _attribute_key(fact) for fact in candidates):
            return [], "attribute_evidence_missing"
        return [], "no_admitted_direct_evidence"

    scoped_candidates = [
        fact
        for fact in candidates
        if _matches_subject_scope(fact, required_subject_scope)
    ]
    if required_subject_scope is not None and not scoped_candidates:
        if not required_subject_scope:
            return [], "subject_scope_missing"
        if any(not sanitize_text(fact.get("subject_scope")) for fact in candidates):
            return [], "subject_scope_evidence_missing"
        return [], "subject_scope_mismatch"
    candidates = scoped_candidates
    if len(candidates) <= 1:
        return candidates, ""
    attribute_groups = {_attribute_key(fact) or "__attribute_missing__" for fact in candidates}
    if len(attribute_groups) == 1:
        return candidates, ""
    return [], "selection_ambiguous"


def _claim_uid(requested: dict[str, Any]) -> str:
    """Create a stable claim identity from declared understanding, not input order."""
    goal_ref = sanitize_text(requested.get("goal_ref"))
    canonical = (
        {"goal_ref": goal_ref}
        if goal_ref
        else {
            "claim_type": sanitize_text(requested.get("claim_type")).lower(),
            "attribute_key": sanitize_text(requested.get("attribute_key")).lower(),
            "question": sanitize_text(requested.get("question")).lower(),
            "risk_level": sanitize_text(requested.get("risk_level")).lower(),
        }
    )
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"claim-{digest}"


def _claim_is_prohibited(requested: dict[str, Any]) -> bool:
    """Respect an upstream explicit prohibition without reclassifying risk locally."""
    return requested.get("direct_handling_prohibited") is True or requested.get("prohibited") is True


def _claim_policy(
    claim_type: str,
    claim_policies: dict[str, Any] | None,
) -> dict[str, Any]:
    policies = claim_policies if isinstance(claim_policies, dict) else {}
    value = policies.get(claim_type)
    if not isinstance(value, dict):
        value = policies.get(_canonical_claim_type(claim_type))
    return value if isinstance(value, dict) else {}


def _structured_claim_families(requested: dict[str, Any]) -> set[str]:
    return {
        value
        for value in (
            _canonical_claim_type(sanitize_text(requested.get("claim_type")).lower()),
            _attribute_key(requested),
        )
        if value
    }


def _requested_claim_risk(requested: dict[str, Any]) -> str:
    if any(
        normalize_high_risk_claim_type(value)
        for value in _structured_claim_families(requested)
    ):
        return "high"
    return (
        sanitize_text(requested.get("risk_level")).lower()
        or "medium"
    )


def _policy_values(policy: dict[str, Any], key: str) -> list[str]:
    values = policy.get(key)
    if not isinstance(values, list):
        return []
    return sorted({
        sanitize_text(value).lower()
        for value in values
        if sanitize_text(value)
    })


def _restricted_request_boundary(
    requested: dict[str, Any],
) -> dict[str, Any]:
    intent_kind = sanitize_text(
        requested.get("policy_intent_kind")
    ).lower()
    claim_families = _structured_claim_families(requested)
    high_risk_families = sorted({
        canonical
        for family in claim_families
        if (canonical := normalize_high_risk_claim_type(family))
    })
    requested_risk = _requested_claim_risk(requested)
    if _claim_is_prohibited(requested):
        reason = (
            sanitize_text(requested.get("prohibition_reason"))
            or "direct_handling_prohibited"
        )
        allows_alternative = False
    elif intent_kind in _RESTRICTED_REQUEST_INTENT_REASONS:
        reason = _RESTRICTED_REQUEST_INTENT_REASONS[intent_kind]
        allows_alternative = intent_kind == "absolute_guarantee"
    elif (
        high_risk_families
        and intent_kind == "practical_guidance"
        and sanitize_text(requested.get("policy_goal_family"))
    ):
        reason = "high_risk_factual_claim_prohibited"
        allows_alternative = True
    else:
        return {}
    return {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": reason,
        "requested_claim_risk": requested_risk,
        "policy_intent_ref": sanitize_text(
            requested.get("policy_intent_ref")
        ).lower(),
        "policy_goal_family": sanitize_text(
            requested.get("policy_goal_family")
        ).lower(),
        "policy_intent_kind": intent_kind,
        "high_risk_claim_families": high_risk_families,
        "must_remain_unresolved": True,
        "allows_bounded_alternative": allows_alternative,
    }


def valid_restricted_request_boundary(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "schema_version",
        "status",
        "reason_code",
        "requested_claim_risk",
        "policy_intent_ref",
        "policy_goal_family",
        "policy_intent_kind",
        "high_risk_claim_families",
        "must_remain_unresolved",
        "allows_bounded_alternative",
    }:
        return False
    high_risk_families = value.get("high_risk_claim_families")
    return bool(
        value.get("schema_version") == "restricted-request-boundary/v1"
        and value.get("status") == "prohibited"
        and sanitize_text(value.get("reason_code"))
        and value.get("requested_claim_risk")
        in _REQUEST_CLAIM_RISK_LEVELS
        and value.get("policy_intent_kind")
        in (
            set(_RESTRICTED_REQUEST_INTENT_REASONS)
            | {"", "practical_guidance"}
        )
        and isinstance(high_risk_families, list)
        and len(high_risk_families)
        == len(set(map(str, high_risk_families)))
        and all(
            normalize_high_risk_claim_type(item)
            for item in high_risk_families
        )
        and value.get("must_remain_unresolved") is True
        and isinstance(value.get("allows_bounded_alternative"), bool)
        and (
            value.get("allows_bounded_alternative") is False
            or (
                (
                    value.get("policy_intent_kind")
                    == "absolute_guarantee"
                    and sanitize_text(value.get("policy_intent_ref"))
                    and sanitize_text(value.get("policy_goal_family"))
                )
                or (
                    value.get("policy_intent_kind")
                    == "practical_guidance"
                    and bool(high_risk_families)
                    and sanitize_text(value.get("policy_goal_family"))
                )
            )
        )
    )


def _eligible_policy_options(
    requested: dict[str, Any],
    *,
    direct_product_facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    bounded_inference_policies: list[dict[str, Any]],
    context_capabilities: dict[str, Any],
    policy_ref_prefix: str,
) -> tuple[list[dict[str, Any]], str]:
    policy_intent_ref = sanitize_text(
        requested.get("policy_intent_ref")
    ).lower()
    restricted_boundary = _restricted_request_boundary(requested)
    if (
        sanitize_text(requested.get("goal_kind")).lower()
        != "customer_goal"
        or requested.get("supporting_only") is True
    ):
        return [], "bounded_inference_goal_kind_prohibited"

    claim_families = _structured_claim_families(requested)
    high_risk_families = {
        canonical
        for value in claim_families
        if (canonical := normalize_high_risk_claim_type(value))
    }
    requested_risk = _requested_claim_risk(requested)
    if requested_risk not in _REQUEST_CLAIM_RISK_LEVELS:
        return [], "bounded_inference_risk_contract_invalid"
    if (
        requested_risk in {"high", "critical", "prohibited"}
        and not restricted_boundary.get(
            "allows_bounded_alternative"
        )
    ):
        return [], "bounded_inference_high_risk_prohibited"
    if not policy_ref_prefix:
        return [], "bounded_inference_policy_reference_missing"

    policies = sorted(
        (
            policy
            for policy in bounded_inference_policies
            if isinstance(policy, dict)
            and policy.get("review_only") is True
            and sanitize_text(policy.get("policy_intent_ref"))
        ),
        key=lambda item: sanitize_text(item.get("policy_intent_ref")),
    )
    alternative_for_restricted_request = bool(
        restricted_boundary.get("allows_bounded_alternative")
    )
    if policy_intent_ref:
        matching = [
            policy
            for policy in policies
            if sanitize_text(policy.get("policy_intent_ref")).lower()
            == policy_intent_ref
        ]
        if not matching:
            return [], "bounded_inference_policy_intent_unknown"
        if len(matching) != 1:
            return [], "bounded_inference_policy_ambiguous"
        policy_goal_family = sanitize_text(
            requested.get("policy_goal_family")
        ).lower()
        if (
            not policy_goal_family
            or policy_goal_family
            != sanitize_text(matching[0].get("goal_family")).lower()
        ):
            return [], "bounded_inference_goal_family_mismatch"
        policy_intent_kind = sanitize_text(
            requested.get("policy_intent_kind")
        ).lower()
        if (
            not policy_intent_kind
            or policy_intent_kind
            != sanitize_text(matching[0].get("intent_kind")).lower()
        ):
            return [], "bounded_inference_intent_kind_mismatch"
        if alternative_for_restricted_request:
            policies = [
                policy
                for policy in policies
                if sanitize_text(policy.get("goal_family")).lower()
                == policy_goal_family
                and sanitize_text(policy.get("intent_kind")).lower()
                == "practical_guidance"
            ]
            if not policies:
                return [], "bounded_inference_absolute_guarantee_prohibited"
        else:
            policies = matching
        if restricted_boundary and not restricted_boundary.get(
            "allows_bounded_alternative"
        ):
            return [], _RESTRICTED_OPTION_REASONS.get(
                policy_intent_kind,
                "bounded_inference_high_risk_prohibited",
            )
    else:
        policy_goal_family = sanitize_text(
            requested.get("policy_goal_family")
        ).lower()
        policy_intent_kind = sanitize_text(
            requested.get("policy_intent_kind")
        ).lower()
        if not policy_goal_family:
            return [], "bounded_inference_policy_goal_family_missing"
        if policy_intent_kind != "practical_guidance":
            return [], "bounded_inference_intent_kind_mismatch"
        policies = [
            policy
            for policy in policies
            if sanitize_text(policy.get("goal_family")).lower()
            == policy_goal_family
            and sanitize_text(policy.get("intent_kind")).lower()
            == policy_intent_kind
        ]
        if not policies:
            return [], "bounded_inference_goal_family_mismatch"

    options: list[dict[str, Any]] = []
    rejection_reason = ""
    for policy in policies:
        intent_kind = sanitize_text(policy.get("intent_kind")).lower()
        allowed_conclusion_family = sanitize_text(
            policy.get("allowed_conclusion_family")
        ).lower()
        allowed_variability_factor_families = _policy_values(
            policy,
            "allowed_variability_factor_families",
        )
        raw_variability_factors = policy.get(
            "allowed_variability_factor_families"
        )
        advice_mode = sanitize_text(policy.get("advice_mode")).lower()
        prohibited_intersection = claim_families.intersection(
            _policy_values(policy, "prohibited_claim_families")
        )
        if (
            not allowed_conclusion_family
            or not isinstance(raw_variability_factors, list)
            or len(raw_variability_factors)
            != len(allowed_variability_factor_families)
            or any(
                not isinstance(value, str)
                or not sanitize_text(value).strip()
                for value in raw_variability_factors
            )
            or advice_mode not in {
                "none",
                "concise_care_only",
                "safety_handoff_required",
            }
        ):
            reason = "bounded_inference_semantic_budget_invalid"
        elif intent_kind == "absolute_guarantee":
            reason = "bounded_inference_absolute_guarantee_prohibited"
        elif intent_kind == "test_standard_request":
            reason = "bounded_inference_direct_test_evidence_required"
        elif intent_kind == "warranty_or_liability_request":
            reason = "bounded_inference_policy_or_service_evidence_required"
        elif intent_kind != "practical_guidance":
            reason = "bounded_inference_intent_kind_unsupported"
        elif high_risk_families and advice_mode != "safety_handoff_required":
            reason = "bounded_inference_high_risk_prohibited"
        elif prohibited_intersection and not (
            advice_mode == "safety_handoff_required"
            and prohibited_intersection.issubset(high_risk_families)
        ):
            reason = "bounded_inference_prohibited_extension"
        else:
            reason = ""
        if reason:
            rejection_reason = rejection_reason or reason
            continue

        maximum_risk = sanitize_text(
            policy.get("maximum_risk_level")
        ).lower()
        if maximum_risk not in _BOUNDED_INFERENCE_RISK_RANK:
            rejection_reason = (
                rejection_reason
                or "bounded_inference_risk_contract_invalid"
            )
            continue
        answer_strategy_risk = (
            requested_risk
            if requested_risk in _BOUNDED_INFERENCE_RISK_RANK
            else maximum_risk
        )
        if (
            answer_strategy_risk not in _BOUNDED_INFERENCE_RISK_RANK
            or _BOUNDED_INFERENCE_RISK_RANK[answer_strategy_risk]
            > _BOUNDED_INFERENCE_RISK_RANK[maximum_risk]
        ):
            rejection_reason = (
                rejection_reason
                or "bounded_inference_risk_limit_exceeded"
            )
            continue

        required_capabilities = _policy_values(
            policy,
            "required_context_capabilities",
        )
        if any(
            not isinstance(context_capabilities.get(capability), dict)
            or context_capabilities[capability].get("available") is not True
            for capability in required_capabilities
        ):
            rejection_reason = (
                rejection_reason
                or "bounded_inference_context_capability_missing"
            )
            continue

        premise_families = _policy_values(
            policy,
            "premise_fact_families",
        )
        premise_facts: list[dict[str, Any]] = []
        premise_reason = ""
        for family in premise_families:
            if _facts_for_claim(family, conflicts):
                premise_reason = "bounded_inference_premise_conflicting"
                break
            family_facts = _facts_for_claim(
                family,
                direct_product_facts,
            )
            if not family_facts:
                premise_reason = "bounded_inference_premise_missing"
                break
            premise_facts.extend(family_facts)
        premise_by_uid = {
            sanitize_text(item.get("evidence_uid")): item
            for item in premise_facts
            if sanitize_text(item.get("evidence_uid"))
        }
        policy_uses_authoritative_goal = (
            advice_mode == "safety_handoff_required"
            and not premise_families
        )
        if (
            premise_reason
            or (not premise_by_uid and not policy_uses_authoritative_goal)
        ):
            rejection_reason = (
                rejection_reason
                or premise_reason
                or "bounded_inference_premise_missing"
            )
            continue

        option_intent_ref = sanitize_text(
            policy.get("policy_intent_ref")
        ).lower()
        option_provenance = {
            "policy_owner": "domain_policy_pack",
            "filter_owner": "claim_resolution",
            "premise_owner": (
                "authoritative_customer_goal"
                if policy_uses_authoritative_goal
                else "admitted_answer_context"
            ),
            "intent_narrowed": (
                bool(policy_intent_ref)
                and not alternative_for_restricted_request
            ),
        }
        if alternative_for_restricted_request:
            option_provenance[
                "alternative_for_restricted_request"
            ] = True
        options.append({
            "policy_ref": (
                f"{policy_ref_prefix}:intent:{option_intent_ref}"
            ),
            "trusted_domain_pack_ref": policy_ref_prefix,
            "pack_content_sha256": _structured_sha256(
                policy.get("pack_content_sha256")
            ),
            "applicable_goal_ref": (
                sanitize_text(requested.get("goal_ref"))
                or _claim_uid(requested)
            ),
            "policy_intent_ref": option_intent_ref,
            "goal_family": sanitize_text(
                policy.get("goal_family")
            ).lower(),
            "intent_kind": intent_kind,
            "premise_evidence_refs": sorted(premise_by_uid),
            "premise_families": premise_families,
            "allowed_scope": sanitize_text(
                policy.get("allowed_scope")
            ).lower(),
            "allowed_conclusion_family": allowed_conclusion_family,
            "allowed_variability_factor_families": (
                allowed_variability_factor_families
            ),
            "advice_mode": advice_mode,
            "forbidden_claim_families": _policy_values(
                policy,
                "prohibited_claim_families",
            ),
            "maximum_risk": maximum_risk,
            "requested_risk": requested_risk,
            "requested_claim_risk": requested_risk,
            "answer_strategy_risk": answer_strategy_risk,
            "restricted_request_boundary": restricted_boundary,
            "required_qualifiers": _policy_values(
                policy,
                "required_qualifiers",
            ),
            "review_only": True,
            "used_for_evidence": False,
            "used_for_fact_support": False,
            "can_change_can_send": False,
            "option_provenance": option_provenance,
        })
    return (
        sorted(options, key=lambda item: item["policy_ref"]),
        "" if options else rejection_reason,
    )


def build_claim_resolutions(
    requested_claims: list[dict[str, Any]],
    *,
    direct_product_facts: list[dict[str, Any]],
    direct_policy_facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    claim_policies: dict[str, Any] | None = None,
    bounded_inference_policies: list[dict[str, Any]] | None = None,
    context_capabilities: dict[str, Any] | None = None,
    policy_ref_prefix: str = "",
) -> list[dict[str, Any]]:
    """Return one deterministic claim decision per declared claim.

    A claim is supported only by direct evidence already admitted by the caller.
    A conflicting candidate blocks that claim even if another candidate exists.
    """
    direct_facts = [*direct_product_facts, *direct_policy_facts]
    results: list[dict[str, Any]] = []
    ordered_requests = sorted(
        (item for item in requested_claims if isinstance(item, dict)),
        key=_claim_uid,
    )
    for requested in ordered_requests:
        original_claim_type = sanitize_text(requested.get("claim_type"))
        original_attribute_key = _original_attribute_key(requested)
        claim_type = original_claim_type.lower()
        claim_type_status = sanitize_text(
            requested.get("claim_type_status")
        ).lower()
        unmapped_customer_goal = (
            not claim_type
            and claim_type_status == "unmapped"
            and sanitize_text(requested.get("goal_kind")).lower()
            == "customer_goal"
        )
        if not claim_type and not unmapped_customer_goal:
            continue
        policy = (
            {}
            if unmapped_customer_goal
            else _claim_policy(claim_type, claim_policies)
        )
        policy_refs = (
            [f"{policy_ref_prefix}:{_canonical_claim_type(claim_type)}"]
            if policy and policy_ref_prefix
            else []
        )
        requested_attribute = _attribute_key(requested)
        requested_subject_scope = _requested_subject_scope(requested)
        matching_facts, fact_selection_reason = (
            ([], "")
            if unmapped_customer_goal
            else _select_for_attribute(
                requested_attribute,
                _facts_for_claim(claim_type, direct_facts),
                required_subject_scope=requested_subject_scope,
            )
        )
        conflict_candidates = (
            []
            if unmapped_customer_goal
            else _facts_for_claim(claim_type, conflicts)
        )
        matching_conflicts, _conflict_selection_reason = (
            _select_for_attribute(
                requested_attribute,
                conflict_candidates,
                required_subject_scope=requested_subject_scope,
            )
            if conflict_candidates
            else ([], "")
        )
        conflict_uids = [
            sanitize_text(fact.get("evidence_uid"))
            for fact in matching_conflicts
            if sanitize_text(fact.get("evidence_uid"))
        ]
        restricted_boundary = _restricted_request_boundary(requested)
        if unmapped_customer_goal:
            status = "unresolved"
            reason = "unmapped_claim_type"
            facts = []
        elif _claim_is_prohibited(requested):
            status = "prohibited"
            reason = sanitize_text(requested.get("prohibition_reason")) or "direct_handling_prohibited"
            facts = []
        elif matching_conflicts:
            status = "conflicting"
            reason = sanitize_text(matching_conflicts[0].get("reason")) or "conflicting_evidence"
            facts: list[dict[str, Any]] = []
        elif restricted_boundary:
            status = "unresolved"
            reason = restricted_boundary["reason_code"]
            facts = []
        elif fact_selection_reason:
            status = "unresolved"
            reason = fact_selection_reason
            facts = []
        elif matching_facts:
            status = "supported"
            reason = "admitted_direct_evidence"
            facts = matching_facts
        else:
            status = "unresolved"
            reason = "no_admitted_direct_evidence"
            facts = []
        eligible_policy_options: list[dict[str, Any]] = []
        option_rejection_reason = ""
        has_explicit_policy_nomination = bool(
            sanitize_text(requested.get("policy_intent_ref"))
        )
        if (
            status in {"supported", "unresolved"}
            and (
                (
                    status == "supported"
                    and (
                        has_explicit_policy_nomination
                        or not policy_ref_prefix
                    )
                )
                or reason in {
                    "no_admitted_direct_evidence",
                    "unmapped_claim_type",
                }
                or bool(restricted_boundary)
            )
        ):
            (
                eligible_policy_options,
                option_rejection_reason,
            ) = _eligible_policy_options(
                requested,
                direct_product_facts=direct_product_facts,
                conflicts=conflicts,
                bounded_inference_policies=[
                    item
                    for item in (bounded_inference_policies or [])
                    if isinstance(item, dict)
                ],
                context_capabilities=(
                    context_capabilities
                    if isinstance(context_capabilities, dict)
                    else {}
                ),
                policy_ref_prefix=policy_ref_prefix,
            )
        results.append({
            "claim_uid": _claim_uid(requested),
            "goal_ref": sanitize_text(requested.get("goal_ref")),
            "goal_kind": sanitize_text(requested.get("goal_kind")).lower(),
            "claim_type_status": claim_type_status,
            "semantic_key": sanitize_text(requested.get("semantic_key")).lower(),
            "policy_intent_ref": sanitize_text(
                requested.get("policy_intent_ref")
            ).lower(),
            "policy_goal_family": sanitize_text(
                requested.get("policy_goal_family")
            ).lower(),
            "policy_intent_kind": sanitize_text(
                requested.get("policy_intent_kind")
            ).lower(),
            "goal_summary": sanitize_text(requested.get("goal_summary")),
            "source": sanitize_text(requested.get("source")).lower(),
            "source_span_start": requested.get("source_span_start"),
            "source_span_end": requested.get("source_span_end"),
            "source_span_sha256": sanitize_text(
                requested.get("source_span_sha256")
            ).lower(),
            "supporting_only": requested.get("supporting_only") is True,
            "claim_type": claim_type,
            "attribute_key": requested_attribute,
            "subject_scope": requested_subject_scope or "",
            "original_claim_type": original_claim_type,
            "original_attribute_key": original_attribute_key,
            "canonical_claim_family": _canonical_claim_type(claim_type),
            "canonical_attribute_key": requested_attribute,
            "status": status,
            "requested_claim_risk": _requested_claim_risk(requested),
            "restricted_request_boundary": restricted_boundary,
            "evidence_uids": [
                sanitize_text(fact.get("evidence_uid")) for fact in facts if sanitize_text(fact.get("evidence_uid"))
            ],
            "admitted_fact_texts": [
                sanitize_text(fact.get("text")) for fact in facts if sanitize_text(fact.get("text"))
            ],
            "conflicting_evidence_uids": conflict_uids if status == "conflicting" else [],
            "support_basis": (
                "direct_evidence"
                if status == "supported"
                else "prohibited"
                if status == "prohibited"
                else "none"
            ),
            "inference_policy_refs": policy_refs,
            "eligible_policy_options": eligible_policy_options,
            "premise_evidence_uids": [],
            "scope_qualifier": "",
            "inference_risk_level": "",
            "maximum_risk_level": "",
            "inference_review_only": False,
            "bounded_inference_rejection_reason": (
                option_rejection_reason
            ),
            "required_qualifiers": [],
            "prohibited_extensions": [],
            "allowed_conclusion_family": "",
            "allowed_variability_factor_families": [],
            "advice_mode": "",
            "bounded_inference_policy": sanitize_text(
                "review_required"
                if eligible_policy_options
                else policy.get("bounded_inference_policy")
            ),
            "requires_human_review": (
                bool(eligible_policy_options)
                or status != "supported"
                or sanitize_text(requested.get("risk_level")).lower()
                in {"high", "critical"}
            ),
            "reason": reason,
        })
    return sanitize_obj(results)


def build_inference_requirement_status(
    claim_resolutions: list[dict[str, Any]],
    *,
    domain_policy_status: str,
) -> dict[str, Any]:
    """Summarize Claim Resolution support without executing inference."""
    resolutions = [
        item
        for item in claim_resolutions
        if isinstance(item, dict)
    ]
    refs = sorted({
        sanitize_text(ref)
        for item in resolutions
        for ref in [
            *(item.get("inference_policy_refs") or []),
            *(
                option.get("policy_ref")
                for option in item.get("eligible_policy_options") or []
                if isinstance(option, dict)
            ),
        ]
        if sanitize_text(ref)
    })
    base = {
        "policy_refs": refs,
        "source_stage": "claim_resolution",
        "reason_codes": [],
    }
    if not resolutions:
        return {**base, "status": "not_applicable"}
    if any(
        item.get("support_basis") == "prohibited"
        or item.get("bounded_inference_policy") == "prohibited"
        for item in resolutions
    ):
        return {
            **base,
            "status": "inference_prohibited",
            "reason_codes": ["claim_or_policy_prohibits_inference"],
        }
    if all(item.get("support_basis") == "direct_evidence" for item in resolutions):
        return {**base, "status": "direct_evidence_only"}
    if any(
        item.get("eligible_policy_options")
        or (
            item.get("status") in {"unresolved", "conflicting"}
            and item.get("bounded_inference_policy")
            in {"allowed", "review_required"}
        )
        for item in resolutions
    ):
        return {
            **base,
            "status": "bounded_inference_required",
            "reason_codes": ["direct_evidence_incomplete"],
        }
    if domain_policy_status != "loaded" or any(
        not item.get("bounded_inference_policy")
        for item in resolutions
        if item.get("support_basis") == "none"
    ):
        return {
            **base,
            "status": "unknown",
            "reason_codes": ["inference_policy_unknown"],
        }
    return {**base, "status": "not_applicable"}
