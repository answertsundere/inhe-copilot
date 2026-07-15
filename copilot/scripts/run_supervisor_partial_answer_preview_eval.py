"""Evaluate the supervisor-only partial-answer contract from raw fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.admitted_answer_context_service import build_minimal_decision_context
from app.services.agent_decision_proposal_service import (
    _preview_safety_validation,
    build_supervisor_partial_answer_preview,
)
from app.services.claim_resolution_service import build_claim_resolutions
from app.services.eval_sanitizer_service import sanitize_text


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def _claim_key(item: dict[str, Any]) -> tuple[str, str]:
    return sanitize_text(item.get("claim_type")).lower(), sanitize_text(item.get("attribute_key")).lower()


def _direct_fact(item: dict[str, Any]) -> dict[str, Any]:
    fact = dict(item or {})
    text = sanitize_text(fact.get("text") or fact.get("content"))
    fact["text"] = text
    fact["content"] = text
    if not isinstance(fact.get("claim_types_supported"), list):
        fact["claim_types_supported"] = [sanitize_text(fact.get("fact_type"))] if sanitize_text(fact.get("fact_type")) else []
    return fact


def _build_preview_context(raw: dict[str, Any]) -> dict[str, Any]:
    """Build the preview input without reading fixture expectations or resolutions."""
    requested_claims = [dict(item) for item in raw.get("requested_claims") or [] if isinstance(item, dict)]
    direct_product = [_direct_fact(item) for item in raw.get("admitted_direct_facts") or [] if isinstance(item, dict)]
    direct_policy = [_direct_fact(item) for item in raw.get("admitted_policy_facts") or [] if isinstance(item, dict)]
    conflicts = [_direct_fact(item) for item in raw.get("conflicts") or [] if isinstance(item, dict)]
    resolutions = build_claim_resolutions(
        requested_claims,
        direct_product_facts=direct_product,
        direct_policy_facts=direct_policy,
        conflicts=conflicts,
    )
    unresolved = [
        {
            "claim_uid": item.get("claim_uid"),
            "claim_type": item.get("claim_type"),
            "attribute_key": item.get("attribute_key"),
            "status": item.get("status"),
            "reason": item.get("reason"),
            "evidence_uids": item.get("evidence_uids") or [],
            "conflicting_evidence_uids": item.get("conflicting_evidence_uids") or [],
        }
        for item in resolutions
        if item.get("status") != "supported"
    ]
    admitted = {
        "direct_product_facts": direct_product,
        "direct_policy_facts": direct_policy,
        "requested_claims": requested_claims,
        "claim_resolutions": resolutions,
        "unresolved_claims": unresolved,
        "conflicting_claims": [item for item in unresolved if item.get("status") == "conflicting"],
        "handoff_action_guidance": list(raw.get("service_actions") or []),
        "media_candidates": list(raw.get("media_candidates") or []),
        "product_identity": dict(raw.get("product_identity") or {}),
    }
    return build_minimal_decision_context(
        admitted,
        customer_message=sanitize_text(raw.get("customer_message")),
        conversation_summary=raw.get("conversation_summary") if isinstance(raw.get("conversation_summary"), dict) else {},
    )


def _preview_projection(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_resolutions": preview.get("claim_resolutions") or [],
        "confirmed_clauses": preview.get("confirmed_clauses") or [],
        "pending_clauses": preview.get("pending_clauses") or [],
        "conflicting_clauses": preview.get("conflicting_clauses") or [],
        "candidate_text": preview.get("candidate_text"),
        "evidence_uids": preview.get("evidence_uids") or [],
        "can_send": preview.get("can_send"),
        "requires_human_review": preview.get("requires_human_review"),
        "used_for_final_reply": preview.get("used_for_final_reply"),
    }


def _reordered(raw: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(raw)
    for key in ("requested_claims", "admitted_direct_facts", "admitted_policy_facts", "conflicts"):
        if isinstance(result.get(key), list):
            result[key] = list(reversed(result[key]))
    return result


def _identity_leaks(text: str, identity: dict[str, Any]) -> bool:
    values = {
        sanitize_text(identity.get(key))
        for key in ("sku_code", "i_id", "product_id", "order_id", "order_id_hash", "content_hash")
        if sanitize_text(identity.get(key))
    }
    return any(value in text for value in values)


def _score_scenario(
    scenario: dict[str, Any],
    *,
    preview_mutator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = scenario.get("raw_context") if isinstance(scenario.get("raw_context"), dict) else {}
    minimal_context = _build_preview_context(raw)
    preview = build_supervisor_partial_answer_preview(minimal_context, provider_status="not_qualified")
    if preview_mutator:
        preview = preview_mutator(deepcopy(preview))
        preview["safety_validation"] = _preview_safety_validation(preview, minimal_context=minimal_context)
    expected = scenario.get("expected") if isinstance(scenario.get("expected"), dict) else {}
    expected_claims = [item for item in expected.get("claims") or [] if isinstance(item, dict)]
    actual = {_claim_key(item): item for item in preview.get("claim_resolutions") or [] if isinstance(item, dict)}
    expected_by_key = {_claim_key(item): item for item in expected_claims}
    resolution_ok = set(actual) == set(expected_by_key) and all(
        sanitize_text(actual[key].get("status")) == sanitize_text(requirement.get("status"))
        for key, requirement in expected_by_key.items()
    )
    confirmed = {sanitize_text(item.get("claim_uid")): item for item in preview.get("confirmed_clauses") or [] if isinstance(item, dict)}
    pending = {sanitize_text(item.get("claim_uid")): item for item in preview.get("pending_clauses") or [] if isinstance(item, dict)}
    conflicting = {sanitize_text(item.get("claim_uid")): item for item in preview.get("conflicting_clauses") or [] if isinstance(item, dict)}
    known_facts = {sanitize_text(item.get("evidence_uid")): item for item in minimal_context.get("admitted_evidence") or []}

    support_total = support_passed = unresolved_total = unresolved_passed = conflict_total = conflict_passed = 0
    citation_total = citation_passed = unsupported_claim_count = 0
    for key, requirement in expected_by_key.items():
        status = sanitize_text(requirement.get("status"))
        resolution = actual.get(key) or {}
        uid = sanitize_text(resolution.get("claim_uid"))
        expected_uids = set(requirement.get("evidence_uids") or [])
        if status == "supported":
            support_total += 1
            clause = confirmed.get(uid) or {}
            clause_uids = set(clause.get("evidence_uids") or [])
            support_passed += int(bool(clause) and clause_uids == expected_uids)
            citation_total += 1
            citation_passed += int(clause_uids == expected_uids and clause_uids.issubset(known_facts))
        elif status in {"unresolved", "prohibited"}:
            unresolved_total += 1
            unresolved_passed += int(uid in pending)
        elif status == "conflicting":
            conflict_total += 1
            conflict_passed += int(uid in conflicting)

    for uid, clause in confirmed.items():
        resolution = next((item for item in actual.values() if sanitize_text(item.get("claim_uid")) == uid), {})
        allowed = set(resolution.get("evidence_uids") or []) if resolution.get("status") == "supported" else set()
        clause_uids = set(clause.get("evidence_uids") or [])
        expected_clause = "；".join(
            sanitize_text(known_facts[evidence_uid].get("content"))
            for evidence_uid in clause.get("evidence_uids") or []
            if evidence_uid in known_facts
        )
        if not allowed or not clause_uids or not clause_uids.issubset(allowed) or sanitize_text(clause.get("customer_facing_clause")) != expected_clause:
            unsupported_claim_count += 1

    text = sanitize_text(preview.get("candidate_text"))
    rendered_clauses = [
        *(sanitize_text(item.get("customer_facing_clause")) for item in preview.get("confirmed_clauses") or []),
        *(sanitize_text(item.get("customer_facing_clause")) for item in preview.get("pending_clauses") or []),
        *(sanitize_text(item.get("customer_facing_clause")) for item in preview.get("conflicting_clauses") or []),
    ]
    if rendered_clauses and text != "亲，" + " ".join(rendered_clauses):
        unsupported_claim_count += 1

    safety = preview.get("safety_validation") or {}
    safety_issues = set(safety.get("issues") or [])
    identity_leakage = int(_identity_leaks(text, raw.get("product_identity") or {}))
    order_stable = _preview_projection(preview) == _preview_projection(
        build_supervisor_partial_answer_preview(_build_preview_context(_reordered(raw)), provider_status="not_qualified")
    )
    violations = {
        "unsupported_claim_count": unsupported_claim_count,
        "identity_leakage_count": identity_leakage,
        "internal_jargon_count": int("internal_jargon" in safety_issues),
        "mojibake_count": int("mojibake" in safety_issues),
        "media_promise_violation_count": int("unsupported_media_promise" in safety_issues),
        "formal_reply_mutation_count": int(preview.get("used_for_final_reply") is not False),
        "can_send_change_count": int(preview.get("can_send") is not False),
    }
    fail_reasons = [
        reason for reason, failed in {
            "claim_resolution_mismatch": not resolution_ok,
            "supported_clause_missing": support_passed != support_total,
            "unresolved_clause_missing": unresolved_passed != unresolved_total,
            "conflicting_clause_missing": conflict_passed != conflict_total,
            "evidence_citation_invalid": citation_passed != citation_total,
            "preview_safety_failed": not bool(safety.get("passed")),
            "unsupported_claim": unsupported_claim_count > 0,
            "identity_leakage": identity_leakage > 0,
            "order_instability": not order_stable,
            "formal_contract_mutation": violations["formal_reply_mutation_count"] > 0 or violations["can_send_change_count"] > 0,
        }.items() if failed
    ]
    return {
        "scenario_uid": scenario.get("scenario_uid"),
        "pass": not fail_reasons,
        "fail_reasons": fail_reasons,
        "minimal_context": minimal_context,
        "preview": preview,
        "counts": {
            "supported": [support_passed, support_total],
            "unresolved": [unresolved_passed, unresolved_total],
            "conflicting": [conflict_passed, conflict_total],
            "citations": [citation_passed, citation_total],
            "resolution": [int(resolution_ok), 1],
            "order_stability": [int(order_stable), 1],
        },
        "violations": violations,
    }


def evaluate(
    dataset: dict[str, Any],
    *,
    preview_mutator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [_score_scenario(scenario, preview_mutator=preview_mutator) for scenario in dataset.get("scenarios") or []]
    totals = {name: [0, 0] for name in ("claim_resolution_accuracy", "supported_claim_coverage", "unresolved_claim_retention", "conflicting_claim_retention", "evidence_citation_rate", "deterministic_order_stability")}
    violations = {name: 0 for name in ("unsupported_claim_count", "identity_leakage_count", "internal_jargon_count", "mojibake_count", "media_promise_violation_count", "formal_reply_mutation_count", "can_send_change_count")}
    for row in rows:
        counts = row["counts"]
        for metric, source in (
            ("claim_resolution_accuracy", "resolution"),
            ("supported_claim_coverage", "supported"),
            ("unresolved_claim_retention", "unresolved"),
            ("conflicting_claim_retention", "conflicting"),
            ("evidence_citation_rate", "citations"),
            ("deterministic_order_stability", "order_stability"),
        ):
            totals[metric][0] += counts[source][0]
            totals[metric][1] += counts[source][1]
        for name, value in row["violations"].items():
            violations[name] += value
    metrics = {name: _rate(*values) for name, values in totals.items()}
    metrics.update(violations)
    metrics["unsupported_claim_rate"] = _rate(violations["unsupported_claim_count"], sum(row["counts"]["supported"][1] for row in rows))
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "total": len(rows),
        "passed": sum(item["pass"] for item in rows),
        "failed": sum(not item["pass"] for item in rows),
        "metrics": metrics,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("tests/fixtures/supervisor_partial_answer_preview/v1.json"))
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads(args.input.read_text(encoding="utf-8"))
    report = evaluate(dataset)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
