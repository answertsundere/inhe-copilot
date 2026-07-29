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
    canonical_material_composition_claim_type,
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


def _select_for_attribute(
    requested_attribute: str,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Select evidence by declared attribute without inferring from free text."""
    if requested_attribute:
        matching = [fact for fact in candidates if _attribute_key(fact) == requested_attribute]
        if matching:
            return matching, ""
        if any(not _attribute_key(fact) for fact in candidates):
            return [], "attribute_evidence_missing"
        return [], "no_admitted_direct_evidence"

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


def _policy_values(policy: dict[str, Any], key: str) -> list[str]:
    values = policy.get(key)
    if not isinstance(values, list):
        return []
    return sorted({
        sanitize_text(value).lower()
        for value in values
        if sanitize_text(value)
    })


def _bounded_inference_resolution(
    requested: dict[str, Any],
    *,
    direct_product_facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    bounded_inference_policies: list[dict[str, Any]],
    context_capabilities: dict[str, Any],
    policy_ref_prefix: str,
) -> dict[str, Any] | None:
    policy_intent_ref = sanitize_text(
        requested.get("policy_intent_ref")
    ).lower()
    if not policy_intent_ref:
        return None

    matching_policies = sorted(
        (
            policy
            for policy in bounded_inference_policies
            if isinstance(policy, dict)
            and policy.get("review_only") is True
            and sanitize_text(policy.get("policy_intent_ref")).lower()
            == policy_intent_ref
        ),
        key=lambda item: sanitize_text(item.get("policy_intent_ref")),
    )
    if not matching_policies:
        return {"reason": "bounded_inference_policy_intent_unknown"}
    if len(matching_policies) != 1:
        return {"reason": "bounded_inference_policy_ambiguous"}

    policy = matching_policies[0]
    if (
        sanitize_text(requested.get("goal_kind")).lower()
        != "customer_goal"
        or requested.get("supporting_only") is True
    ):
        return {"reason": "bounded_inference_goal_kind_prohibited"}
    policy_goal_family = sanitize_text(
        requested.get("policy_goal_family")
    ).lower()
    if (
        not policy_goal_family
        or policy_goal_family
        != sanitize_text(policy.get("goal_family")).lower()
    ):
        return {"reason": "bounded_inference_goal_family_mismatch"}
    policy_intent_kind = sanitize_text(
        requested.get("policy_intent_kind")
    ).lower()
    if (
        not policy_intent_kind
        or policy_intent_kind
        != sanitize_text(policy.get("intent_kind")).lower()
    ):
        return {"reason": "bounded_inference_intent_kind_mismatch"}

    claim_families = _structured_claim_families(requested)
    if (
        any(normalize_high_risk_claim_type(value) for value in claim_families)
        or sanitize_text(requested.get("risk_level")).lower()
        in {"high", "critical", "prohibited"}
    ):
        return {"reason": "bounded_inference_high_risk_prohibited"}

    if claim_families.intersection(
        _policy_values(policy, "prohibited_claim_families")
    ):
        return {"reason": "bounded_inference_prohibited_extension"}
    if policy_intent_kind == "absolute_guarantee":
        return {"reason": "bounded_inference_absolute_guarantee_prohibited"}
    if policy_intent_kind == "test_standard_request":
        return {
            "reason": "bounded_inference_direct_test_evidence_required"
        }
    if policy_intent_kind == "warranty_or_liability_request":
        return {
            "reason": (
                "bounded_inference_policy_or_service_evidence_required"
            )
        }
    if policy_intent_kind != "practical_guidance":
        return {"reason": "bounded_inference_intent_kind_unsupported"}

    requested_risk = (
        sanitize_text(requested.get("risk_level")).lower()
        or "medium"
    )
    maximum_risk = sanitize_text(
        policy.get("maximum_risk_level")
    ).lower()
    if (
        requested_risk not in _BOUNDED_INFERENCE_RISK_RANK
        or maximum_risk not in _BOUNDED_INFERENCE_RISK_RANK
    ):
        return {"reason": "bounded_inference_risk_contract_invalid"}
    if (
        _BOUNDED_INFERENCE_RISK_RANK[requested_risk]
        > _BOUNDED_INFERENCE_RISK_RANK[maximum_risk]
    ):
        return {"reason": "bounded_inference_risk_limit_exceeded"}

    required_capabilities = _policy_values(
        policy,
        "required_context_capabilities",
    )
    if any(
        not isinstance(context_capabilities.get(capability), dict)
        or context_capabilities[capability].get("available") is not True
        for capability in required_capabilities
    ):
        return {"reason": "bounded_inference_context_capability_missing"}

    premise_families = _policy_values(policy, "premise_fact_families")
    premise_facts: list[dict[str, Any]] = []
    for family in premise_families:
        if _facts_for_claim(family, conflicts):
            return {"reason": "bounded_inference_premise_conflicting"}
        family_facts = _facts_for_claim(family, direct_product_facts)
        if not family_facts:
            return {"reason": "bounded_inference_premise_missing"}
        premise_facts.extend(family_facts)
    premise_by_uid = {
        sanitize_text(item.get("evidence_uid")): item
        for item in premise_facts
        if sanitize_text(item.get("evidence_uid"))
    }
    if not premise_by_uid:
        return {"reason": "bounded_inference_premise_missing"}

    if not policy_ref_prefix:
        return {"reason": "bounded_inference_policy_reference_missing"}
    premise_uids = sorted(premise_by_uid)
    return {
        "reason": "policy_bounded_inference",
        "facts": [premise_by_uid[uid] for uid in premise_uids],
        "premise_evidence_uids": premise_uids,
        "inference_policy_refs": [
            f"{policy_ref_prefix}:intent:{policy_intent_ref}"
        ],
        "scope_qualifier": sanitize_text(policy.get("allowed_scope")).lower(),
        "inference_risk_level": requested_risk,
        "maximum_risk_level": maximum_risk,
        "inference_review_only": True,
        "required_qualifiers": _policy_values(
            policy,
            "required_qualifiers",
        ),
        "prohibited_extensions": _policy_values(
            policy,
            "prohibited_claim_families",
        ),
    }


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
        matching_facts, fact_selection_reason = (
            ([], "")
            if unmapped_customer_goal
            else _select_for_attribute(
                requested_attribute,
                _facts_for_claim(claim_type, direct_facts),
            )
        )
        conflict_candidates = (
            []
            if unmapped_customer_goal
            else _facts_for_claim(claim_type, conflicts)
        )
        matching_conflicts, _conflict_selection_reason = (
            _select_for_attribute(requested_attribute, conflict_candidates)
            if conflict_candidates
            else ([], "")
        )
        conflict_uids = [
            sanitize_text(fact.get("evidence_uid"))
            for fact in matching_conflicts
            if sanitize_text(fact.get("evidence_uid"))
        ]
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
        bounded: dict[str, Any] | None = None
        policy_nominated = bool(
            sanitize_text(requested.get("policy_intent_ref"))
        )
        if (
            policy_nominated
            and status in {"supported", "unresolved"}
            and (
                status == "supported"
                or reason in {
                    "no_admitted_direct_evidence",
                    "unmapped_claim_type",
                }
            )
        ):
            bounded = _bounded_inference_resolution(
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
            if bounded:
                if bounded.get("facts"):
                    status = "supported"
                    reason = sanitize_text(bounded.get("reason"))
                    facts = list(bounded["facts"])
                    policy_refs = list(
                        bounded.get("inference_policy_refs") or []
                    )
                elif status == "unresolved":
                    reason = sanitize_text(bounded.get("reason"))
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
            "original_claim_type": original_claim_type,
            "original_attribute_key": original_attribute_key,
            "canonical_claim_family": _canonical_claim_type(claim_type),
            "canonical_attribute_key": requested_attribute,
            "status": status,
            "evidence_uids": [
                sanitize_text(fact.get("evidence_uid")) for fact in facts if sanitize_text(fact.get("evidence_uid"))
            ],
            "admitted_fact_texts": [
                sanitize_text(fact.get("text")) for fact in facts if sanitize_text(fact.get("text"))
            ],
            "conflicting_evidence_uids": conflict_uids if status == "conflicting" else [],
            "support_basis": (
                "bounded_inference"
                if status == "supported" and bounded and bounded.get("facts")
                else "direct_evidence"
                if status == "supported"
                else "prohibited"
                if status == "prohibited"
                else "none"
            ),
            "inference_policy_refs": policy_refs,
            "premise_evidence_uids": (
                list(bounded.get("premise_evidence_uids") or [])
                if bounded and bounded.get("facts")
                else []
            ),
            "scope_qualifier": (
                sanitize_text(bounded.get("scope_qualifier"))
                if bounded and bounded.get("facts")
                else ""
            ),
            "inference_risk_level": (
                sanitize_text(bounded.get("inference_risk_level"))
                if bounded and bounded.get("facts")
                else ""
            ),
            "maximum_risk_level": (
                sanitize_text(bounded.get("maximum_risk_level"))
                if bounded and bounded.get("facts")
                else ""
            ),
            "inference_review_only": bool(
                bounded
                and bounded.get("facts")
                and bounded.get("inference_review_only") is True
            ),
            "bounded_inference_rejection_reason": (
                sanitize_text(bounded.get("reason"))
                if (
                    bounded
                    and not bounded.get("facts")
                    and status == "supported"
                )
                else ""
            ),
            "required_qualifiers": (
                list(bounded.get("required_qualifiers") or [])
                if bounded and bounded.get("facts")
                else []
            ),
            "prohibited_extensions": (
                list(bounded.get("prohibited_extensions") or [])
                if bounded and bounded.get("facts")
                else []
            ),
            "bounded_inference_policy": sanitize_text(
                "review_required"
                if bounded and bounded.get("facts")
                else policy.get("bounded_inference_policy")
            ),
            "requires_human_review": (
                bool(bounded and bounded.get("facts"))
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
        for ref in item.get("inference_policy_refs") or []
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
    if (
        any(item.get("support_basis") == "bounded_inference" for item in resolutions)
        and all(item.get("status") == "supported" for item in resolutions)
    ):
        return {**base, "status": "bounded_inference_completed"}
    if any(
        item.get("status") in {"unresolved", "conflicting"}
        and item.get("bounded_inference_policy") in {"allowed", "review_required"}
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
