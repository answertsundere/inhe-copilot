"""Resolve requested claims against already admitted evidence.

This service is read-only.  It does not retrieve, generate customer wording, or
change any formal response field.  It gives shadow planners a deterministic
claim-by-claim boundary after evidence admission has completed.
"""

from __future__ import annotations

from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


def _claim_types(fact: dict[str, Any]) -> set[str]:
    values = fact.get("claim_types_supported") or []
    if not isinstance(values, list):
        values = [values]
    return {sanitize_text(value).lower() for value in values if sanitize_text(value)}


def _facts_for_claim(claim_type: str, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [fact for fact in facts if claim_type in _claim_types(fact)]


def build_claim_resolutions(
    requested_claims: list[dict[str, Any]],
    *,
    direct_product_facts: list[dict[str, Any]],
    direct_policy_facts: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one supported, unresolved, or conflicting decision per claim.

    A claim is supported only by direct evidence already admitted by the caller.
    A conflicting candidate blocks that claim even if another candidate exists.
    """
    direct_facts = [*direct_product_facts, *direct_policy_facts]
    results: list[dict[str, Any]] = []
    for requested in requested_claims:
        claim_type = sanitize_text(requested.get("claim_type")).lower()
        if not claim_type:
            continue
        matching_facts = _facts_for_claim(claim_type, direct_facts)
        matching_conflicts = _facts_for_claim(claim_type, conflicts)
        if matching_conflicts:
            status = "conflicting"
            reason = sanitize_text(matching_conflicts[0].get("reason")) or "conflicting_evidence"
            facts: list[dict[str, Any]] = []
        elif matching_facts:
            status = "supported"
            reason = "admitted_direct_evidence"
            facts = matching_facts
        else:
            status = "unresolved"
            reason = "no_admitted_direct_evidence"
            facts = []
        results.append({
            "claim_type": claim_type,
            "status": status,
            "evidence_uids": [
                sanitize_text(fact.get("evidence_uid")) for fact in facts if sanitize_text(fact.get("evidence_uid"))
            ],
            "admitted_fact_texts": [
                sanitize_text(fact.get("text")) for fact in facts if sanitize_text(fact.get("text"))
            ],
            "requires_human_review": status != "supported",
            "reason": reason,
        })
    return sanitize_obj(results)
