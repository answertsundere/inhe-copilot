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


def _claim_types(fact: dict[str, Any]) -> set[str]:
    values = fact.get("claim_types_supported") or []
    if not isinstance(values, list):
        values = [values]
    return {sanitize_text(value).lower() for value in values if sanitize_text(value)}


def _facts_for_claim(claim_type: str, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [fact for fact in facts if claim_type in _claim_types(fact)],
        key=lambda fact: sanitize_text(fact.get("evidence_uid")),
    )


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
        matching_facts = _facts_for_claim(claim_type, direct_facts)
        matching_conflicts = _facts_for_claim(claim_type, conflicts)
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
            "attribute_key": sanitize_text(requested.get("attribute_key")).lower(),
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
