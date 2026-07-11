"""Run the read-only Grounded Reasoning positive capability evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.claim_polarity_service import contains_asserted_claim
from app.services.grounded_reasoning_draft_service import (
    build_grounded_reasoning_draft,
    has_forbidden_claim_violation,
    used_answer_memory_as_fact,
)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_scenarios(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    source = payload.get("scenarios") if isinstance(payload, dict) else payload
    return [item for item in _as_list(source) if isinstance(item, dict)]


def _metric(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 4) if denominator else None,
    }


def _matches_required_terms(draft_text: str, requirement: dict[str, Any]) -> bool:
    terms = [str(term) for term in _as_list(requirement.get("required_terms")) if str(term).strip()]
    if not terms:
        return False
    matcher = str(requirement.get("matcher") or "all_terms")
    if matcher == "any_term":
        return any(term in draft_text for term in terms)
    return all(term in draft_text for term in terms)


def _rejection_checks(
    expected_rejected_evidence: list[dict[str, Any]],
    used_facts: list[dict[str, Any]],
    rejected_evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool, bool]:
    used_by_uid = {str(_as_dict(item).get("evidence_uid") or ""): _as_dict(item) for item in used_facts}
    rejected_by_uid: dict[str, set[str]] = defaultdict(set)
    for item in rejected_evidence:
        rejected_by_uid[str(_as_dict(item).get("evidence_uid") or "")].add(str(_as_dict(item).get("reason") or ""))
    checks = []
    identity_leakage = False
    for expected in expected_rejected_evidence:
        evidence_uid = str(expected.get("evidence_uid") or "")
        expected_reason = str(expected.get("expected_reason") or "")
        used_item = used_by_uid.get(evidence_uid, {})
        is_used = bool(used_item)
        reason_matches = bool(evidence_uid and expected_reason in rejected_by_uid.get(evidence_uid, set()))
        if expected_reason.startswith("product_identity_") and is_used:
            identity_leakage = True
        checks.append(
            {
                "evidence_uid": evidence_uid,
                "expected_reason": expected_reason,
                "expected_identity_scope": _as_list(expected.get("identity_scope")),
                "used_identity_scope": _as_list(used_item.get("identity_scopes")),
                "rejected_with_expected_reason": reason_matches,
                "leaked_into_used_facts": is_used,
                "passed": reason_matches and not is_used,
            }
        )
    return checks, all(check["passed"] for check in checks), identity_leakage


def evaluate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Score a scenario after building a shadow draft; expectations never enter it."""
    draft = build_grounded_reasoning_draft(
        customer_message=str(scenario.get("customer_message") or ""),
        query_fact_type=str(scenario.get("query_fact_type") or ""),
        product_identity=_as_dict(scenario.get("product_identity")),
        selected_evidence=[item for item in _as_list(scenario.get("selected_evidence")) if isinstance(item, dict)],
        product_context_pack=_as_dict(scenario.get("product_context_pack")),
        answer_memory_guidance=_as_dict(scenario.get("answer_memory_guidance")),
        reply_blocks=[],
    )
    used_facts = [_as_dict(item) for item in _as_list(draft.get("used_facts"))]
    rejected_evidence = [_as_dict(item) for item in _as_list(draft.get("rejected_evidence"))]
    used_uids = {str(item.get("evidence_uid") or "") for item in used_facts}
    expected_admitted = [_as_dict(item) for item in _as_list(scenario.get("expected_admitted_evidence"))]
    admission_checks = [
        {
            "evidence_uid": str(item.get("evidence_uid") or ""),
            "fact_key": str(item.get("fact_key") or ""),
            "passed": bool(item.get("evidence_uid")) and str(item.get("evidence_uid")) in used_uids,
        }
        for item in expected_admitted
    ]
    admission_pass = all(item["passed"] for item in admission_checks)

    requirements = [_as_dict(item) for item in _as_list(scenario.get("required_draft_facts"))]
    draft_text = str(draft.get("grounded_draft") or "")
    coverage_checks = [
        {
            "fact_key": str(item.get("fact_key") or ""),
            "required_terms": _as_list(item.get("required_terms")),
            "passed": _matches_required_terms(draft_text, item),
        }
        for item in requirements
    ]
    draft_coverage_pass = all(item["passed"] for item in coverage_checks) if coverage_checks else None

    expected_rejected = [_as_dict(item) for item in _as_list(scenario.get("expected_rejected_evidence"))]
    rejection_checks, rejection_pass, identity_leakage = _rejection_checks(expected_rejected, used_facts, rejected_evidence)
    declared_forbidden = _as_list(scenario.get("declared_forbidden_inferences"))
    declared_unsupported_claim = any(
        contains_asserted_claim(draft_text, str(claim))
        for claim in declared_forbidden
        if str(claim).strip()
    )
    formal_forbidden_claim = has_forbidden_claim_violation(draft)
    must_handoff = bool(scenario.get("must_handoff"))
    handoff_pass = not must_handoff or bool(draft.get("requires_human_review"))
    answer_memory_leakage = used_answer_memory_as_fact(draft)
    checks = [
        *(item["passed"] for item in admission_checks),
        *(item["passed"] for item in rejection_checks),
        *(item["passed"] for item in coverage_checks),
        handoff_pass,
        not declared_unsupported_claim,
        not formal_forbidden_claim,
        not identity_leakage,
        not answer_memory_leakage,
        draft.get("can_change_can_send") is False,
        draft.get("used_for_final_reply") is False,
    ]
    failure_reasons = []
    if any(not item["passed"] for item in admission_checks):
        failure_reasons.append("expected_fact_missing")
    if any(not item["passed"] for item in rejection_checks):
        failure_reasons.append("invalid_evidence_rejection_failed")
    if coverage_checks and not all(item["passed"] for item in coverage_checks):
        failure_reasons.append("draft_fact_coverage_missing")
    if must_handoff and not handoff_pass:
        failure_reasons.append("high_risk_handoff_missing")
    if declared_unsupported_claim:
        failure_reasons.append("declared_unsupported_claim")
    if formal_forbidden_claim:
        failure_reasons.append("forbidden_claim_violation")
    if identity_leakage:
        failure_reasons.append("identity_leakage")
    if answer_memory_leakage:
        failure_reasons.append("answer_memory_fact_leakage")
    if draft.get("can_change_can_send") is not False or draft.get("used_for_final_reply") is not False:
        failure_reasons.append("shadow_contract_violation")
    return {
        "scenario_uid": scenario.get("scenario_uid"),
        "source": scenario.get("source", ""),
        "reasoning_tier": scenario.get("reasoning_tier", ""),
        "query_fact_type": scenario.get("query_fact_type", ""),
        "passed": all(checks),
        "admission_checks": admission_checks,
        "fact_admission_pass": admission_pass,
        "rejection_checks": rejection_checks,
        "invalid_fact_rejection_pass": rejection_pass,
        "required_draft_facts": requirements,
        "draft_fact_coverage_checks": coverage_checks,
        "draft_fact_coverage_pass": draft_coverage_pass,
        "answer_relevance_pass": draft_coverage_pass,
        "allowed_inferences": _as_list(scenario.get("allowed_inferences")),
        "allowed_inferences_scoring": "not_scored",
        "declared_forbidden_inferences": declared_forbidden,
        "declared_unsupported_claim": declared_unsupported_claim,
        "must_handoff": must_handoff,
        "handoff_pass": handoff_pass,
        "forbidden_claim_violation": formal_forbidden_claim,
        "identity_leakage": identity_leakage,
        "answer_memory_fact_leakage": answer_memory_leakage,
        "can_change_can_send": draft.get("can_change_can_send"),
        "used_for_final_reply": draft.get("used_for_final_reply"),
        "used_facts": used_facts,
        "rejected_evidence": rejected_evidence,
        "admission_warnings": _as_list(draft.get("admission_warnings")),
        "grounded_draft": draft_text,
        "failure_reasons": failure_reasons,
    }


def run_eval(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [evaluate_scenario(scenario) for scenario in scenarios]
    admission_checks = [check for row in rows for check in row["admission_checks"]]
    rejection_checks = [check for row in rows for check in row["rejection_checks"]]
    coverage_checks = [check for row in rows for check in row["draft_fact_coverage_checks"]]
    l3_rows = [row for row in rows if row["reasoning_tier"] == "L3" and row["must_handoff"]]
    conflict_checks = [check for row in rows for check in row["rejection_checks"] if check["expected_reason"] == "conflicting_evidence"]
    declared_controls = [row for row in rows if row["declared_forbidden_inferences"]]
    by_tier: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    by_fact_type: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    failures: Counter[str] = Counter()
    for row in rows:
        by_tier[row["reasoning_tier"]]["total"] += 1
        by_tier[row["reasoning_tier"]]["passed"] += int(row["passed"])
        by_fact_type[row["query_fact_type"]]["total"] += 1
        by_fact_type[row["query_fact_type"]]["passed"] += int(row["passed"])
        failures.update(row["failure_reasons"])
    return {
        "schema_version": "grounded-reasoning-positive-eval-result-v2",
        "total": len(rows),
        "evaluated": len(rows),
        "skipped": 0,
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "fact_admission_rate": _metric(sum(check["passed"] for check in admission_checks), len(admission_checks)),
        "invalid_fact_rejection_rate": _metric(sum(check["passed"] for check in rejection_checks), len(rejection_checks)),
        "draft_fact_coverage_rate": _metric(sum(check["passed"] for check in coverage_checks), len(coverage_checks)),
        "answer_relevance_rate": _metric(sum(row["draft_fact_coverage_pass"] is True for row in rows if row["draft_fact_coverage_pass"] is not None), sum(row["draft_fact_coverage_pass"] is not None for row in rows)),
        "declared_unsupported_claim_rate": _metric(sum(row["declared_unsupported_claim"] for row in declared_controls), len(declared_controls)),
        "forbidden_claim_violation_rate": _metric(sum(row["forbidden_claim_violation"] for row in rows), len(rows)),
        "allowed_inferences_scoring": "not_scored",
        "identity_leakage_count": sum(row["identity_leakage"] for row in rows),
        "answer_memory_fact_leakage_count": sum(row["answer_memory_fact_leakage"] for row in rows),
        "conflict_block_rate": _metric(sum(check["passed"] for check in conflict_checks), len(conflict_checks)),
        "high_risk_handoff_rate": _metric(sum(row["handoff_pass"] for row in l3_rows), len(l3_rows)),
        "can_change_can_send_count": sum(row["can_change_can_send"] is not False for row in rows),
        "by_reasoning_tier": {key: {**value, "pass_rate": _metric(value["passed"], value["total"])["rate"]} for key, value in sorted(by_tier.items())},
        "by_query_fact_type": {key: {**value, "pass_rate": _metric(value["passed"], value["total"])["rate"]} for key, value in sorted(by_fact_type.items())},
        "failure_reasons": dict(sorted(failures.items())),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Grounded Reasoning positive capability evaluation.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    result = run_eval(_load_scenarios(args.input))
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
