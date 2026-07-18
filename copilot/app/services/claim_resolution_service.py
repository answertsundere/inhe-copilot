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
    return "material_composition" if value in {"material", "material_composition"} else value


def _attribute_key(item: dict[str, Any]) -> str:
    value = sanitize_text(
        item.get("attribute_key")
        or item.get("field_name")
        or item.get("fact_key")
        or item.get("structured_field")
    ).lower()
    if value:
        return canonical_dimension_attribute(value)
    # `material` is the canonical slot for the legacy primary material fact
    # and the dependency-expanded material composition claim.  This prevents
    # otherwise equivalent, directly admitted structured material facts from
    # becoming an artificial multi-attribute ambiguity.
    claim_type = sanitize_text(item.get("claim_type") or item.get("fact_type")).lower()
    supported_claim_types = _claim_types(item)
    if claim_type in {"material", "material_composition"} or supported_claim_types & {"material", "material_composition"}:
        return "material"
    return ""


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
    canonical = {
        "claim_type": sanitize_text(requested.get("claim_type")).lower(),
        "attribute_key": sanitize_text(requested.get("attribute_key")).lower(),
        "question": sanitize_text(requested.get("question")).lower(),
        "risk_level": sanitize_text(requested.get("risk_level")).lower(),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"claim-{digest}"


def _claim_is_prohibited(requested: dict[str, Any]) -> bool:
    """Respect an upstream explicit prohibition without reclassifying risk locally."""
    return requested.get("direct_handling_prohibited") is True or requested.get("prohibited") is True


def build_claim_resolutions(
    requested_claims: list[dict[str, Any]],
    *,
    direct_product_facts: list[dict[str, Any]],
    direct_policy_facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
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
        claim_type = sanitize_text(requested.get("claim_type")).lower()
        if not claim_type:
            continue
        requested_attribute = _attribute_key(requested)
        matching_facts, fact_selection_reason = _select_for_attribute(
            requested_attribute,
            _facts_for_claim(claim_type, direct_facts),
        )
        conflict_candidates = _facts_for_claim(claim_type, conflicts)
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
        if _claim_is_prohibited(requested):
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
        results.append({
            "claim_uid": _claim_uid(requested),
            "claim_type": claim_type,
            "attribute_key": requested_attribute,
            "status": status,
            "evidence_uids": [
                sanitize_text(fact.get("evidence_uid")) for fact in facts if sanitize_text(fact.get("evidence_uid"))
            ],
            "admitted_fact_texts": [
                sanitize_text(fact.get("text")) for fact in facts if sanitize_text(fact.get("text"))
            ],
            "conflicting_evidence_uids": conflict_uids if status == "conflicting" else [],
            "requires_human_review": status != "supported" or sanitize_text(requested.get("risk_level")).lower() in {"high", "critical"},
            "reason": reason,
        })
    return sanitize_obj(results)
