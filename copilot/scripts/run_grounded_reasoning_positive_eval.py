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
    return {"numerator": numerator, "denominator": denominator, "rate": round(numerator / denominator, 4) if denominator else None}


def _build_shadow_draft(scenario: dict[str, Any], selected_evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return build_grounded_reasoning_draft(
        customer_message=str(scenario.get("customer_message") or ""),
        query_fact_type=str(scenario.get("query_fact_type") or ""),
        product_identity=_as_dict(scenario.get("product_identity")),
        selected_evidence=selected_evidence if selected_evidence is not None else [item for item in _as_list(scenario.get("selected_evidence")) if isinstance(item, dict)],
        product_context_pack=_as_dict(scenario.get("product_context_pack")),
        answer_memory_guidance=_as_dict(scenario.get("answer_memory_guidance")),
        reply_blocks=[],
    )


def _matches_required_terms(draft_text: str, requirement: dict[str, Any]) -> bool:
    terms = [str(term) for term in _as_list(requirement.get("required_terms")) if str(term).strip()]
    if not terms:
        return False
    return any(term in draft_text for term in terms) if requirement.get("matcher") == "any_term" else all(term in draft_text for term in terms)


def _rejection_checks(expected: list[dict[str, Any]], used_facts: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool, bool]:
    used_by_uid = {str(item.get("evidence_uid") or ""): item for item in used_facts}
    reasons_by_uid: dict[str, set[str]] = defaultdict(set)
    for item in rejected:
        reasons_by_uid[str(item.get("evidence_uid") or "")].add(str(item.get("reason") or ""))
    checks = []
    identity_leakage = False
    for item in expected:
        evidence_uid = str(item.get("evidence_uid") or "")
        expected_reason = str(item.get("expected_reason") or "")
        used_item = used_by_uid.get(evidence_uid, {})
        is_used = bool(used_item)
        if expected_reason.startswith("product_identity_") and is_used:
            identity_leakage = True
        checks.append(
            {
                "evidence_uid": evidence_uid,
                "expected_reason": expected_reason,
                "expected_identity_scope": _as_list(item.get("identity_scope")),
                "used_identity_scope": _as_list(used_item.get("identity_scopes")),
                "rejected_with_expected_reason": expected_reason in reasons_by_uid.get(evidence_uid, set()),
                "leaked_into_used_facts": is_used,
                "passed": expected_reason in reasons_by_uid.get(evidence_uid, set()) and not is_used,
            }
        )
    return checks, all(item["passed"] for item in checks), identity_leakage


def _plan_checks(expected_admitted: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    selected = {str(value) for value in _as_list(plan.get("selected_evidence_uids"))}
    return [
        {
            "evidence_uid": str(item.get("evidence_uid") or ""),
            "fact_key": str(item.get("fact_key") or ""),
            "passed": bool(item.get("evidence_uid")) and str(item.get("evidence_uid")) in selected,
        }
        for item in expected_admitted
    ]


def _render_checks(requirements: list[dict[str, Any]], expected_admitted: list[dict[str, Any]], plan: dict[str, Any], draft_text: str) -> tuple[list[dict[str, Any]], int]:
    expected_by_key = {str(item.get("fact_key") or ""): str(item.get("evidence_uid") or "") for item in expected_admitted}
    selected = {str(value) for value in _as_list(plan.get("selected_evidence_uids"))}
    rendered = {str(value) for value in _as_list(plan.get("rendered_evidence_uids"))}
    checks = []
    unattributed_count = 0
    for requirement in requirements:
        fact_key = str(requirement.get("fact_key") or "")
        evidence_uid = expected_by_key.get(fact_key, "")
        terms_match = _matches_required_terms(draft_text, requirement)
        rendered_with_evidence = bool(evidence_uid and evidence_uid in selected and evidence_uid in rendered)
        if terms_match and not rendered_with_evidence:
            unattributed_count += 1
        checks.append(
            {
                "fact_key": fact_key,
                "evidence_uid": evidence_uid,
                "required_terms": _as_list(requirement.get("required_terms")),
                "terms_match": terms_match,
                "planned": evidence_uid in selected,
                "rendered_with_evidence": rendered_with_evidence,
                "passed": terms_match and rendered_with_evidence,
            }
        )
    return checks, unattributed_count


def _composition_signature(draft: dict[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    plan = _as_dict(draft.get("fact_coverage_plan"))
    return (
        frozenset(str(value) for value in _as_list(plan.get("selected_evidence_uids"))),
        frozenset(str(value) for value in _as_list(plan.get("rendered_evidence_uids"))),
    )


def evaluate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Score a scenario after the draft call; expectations never enter the builder."""
    draft = _build_shadow_draft(scenario)
    used_facts = [_as_dict(item) for item in _as_list(draft.get("used_facts"))]
    rejected_evidence = [_as_dict(item) for item in _as_list(draft.get("rejected_evidence"))]
    plan = _as_dict(draft.get("fact_coverage_plan"))
    expected_admitted = [_as_dict(item) for item in _as_list(scenario.get("expected_admitted_evidence"))]
    admission_uids = {str(item.get("evidence_uid") or "") for item in used_facts}
    admission_checks = [{"evidence_uid": str(item.get("evidence_uid") or ""), "fact_key": str(item.get("fact_key") or ""), "passed": str(item.get("evidence_uid") or "") in admission_uids} for item in expected_admitted]
    plan_checks = _plan_checks(expected_admitted, plan)
    requirements = [_as_dict(item) for item in _as_list(scenario.get("required_draft_facts"))]
    draft_text = str(draft.get("grounded_draft") or "")
    render_checks, unattributed_clause_count = _render_checks(requirements, expected_admitted, plan, draft_text)
    rejection_checks, rejection_pass, identity_leakage = _rejection_checks([_as_dict(item) for item in _as_list(scenario.get("expected_rejected_evidence"))], used_facts, rejected_evidence)
    expected_uids = {str(item.get("evidence_uid") or "") for item in expected_admitted}
    irrelevant_fact_inclusion_count = len({str(value) for value in _as_list(plan.get("selected_evidence_uids"))} - expected_uids) if expected_uids else 0
    reversed_draft = _build_shadow_draft(scenario, list(reversed([item for item in _as_list(scenario.get("selected_evidence")) if isinstance(item, dict)])))
    composition_order_instability = _composition_signature(draft) != _composition_signature(reversed_draft)
    declared_forbidden = _as_list(scenario.get("declared_forbidden_inferences"))
    declared_unsupported_claim = any(contains_asserted_claim(draft_text, str(claim)) for claim in declared_forbidden if str(claim).strip())
    formal_forbidden_claim = has_forbidden_claim_violation(draft)
    must_handoff = bool(scenario.get("must_handoff"))
    handoff_pass = not must_handoff or bool(draft.get("requires_human_review"))
    answer_memory_leakage = used_answer_memory_as_fact(draft)
    checks = [
        *(item["passed"] for item in admission_checks),
        *(item["passed"] for item in plan_checks),
        *(item["passed"] for item in render_checks),
        *(item["passed"] for item in rejection_checks),
        handoff_pass,
        not declared_unsupported_claim,
        not formal_forbidden_claim,
        not identity_leakage,
        not answer_memory_leakage,
        unattributed_clause_count == 0,
        irrelevant_fact_inclusion_count == 0,
        not composition_order_instability,
        draft.get("can_change_can_send") is False,
        draft.get("used_for_final_reply") is False,
    ]
    failure_reasons = []
    for reason, failed in (
        ("expected_fact_missing", any(not item["passed"] for item in admission_checks)),
        ("admitted_fact_not_planned", any(not item["passed"] for item in plan_checks)),
        ("planned_fact_not_rendered", any(not item["passed"] for item in render_checks)),
        ("invalid_evidence_rejection_failed", any(not item["passed"] for item in rejection_checks)),
        ("high_risk_handoff_missing", must_handoff and not handoff_pass),
        ("declared_unsupported_claim", declared_unsupported_claim),
        ("forbidden_claim_violation", formal_forbidden_claim),
        ("identity_leakage", identity_leakage),
        ("answer_memory_fact_leakage", answer_memory_leakage),
        ("unattributed_clause", unattributed_clause_count > 0),
        ("irrelevant_fact_inclusion", irrelevant_fact_inclusion_count > 0),
        ("composition_order_instability", composition_order_instability),
        ("shadow_contract_violation", draft.get("can_change_can_send") is not False or draft.get("used_for_final_reply") is not False),
    ):
        if failed:
            failure_reasons.append(reason)
    return {
        "scenario_uid": scenario.get("scenario_uid"),
        "source": scenario.get("source", ""),
        "reasoning_tier": scenario.get("reasoning_tier", ""),
        "query_fact_type": scenario.get("query_fact_type", ""),
        "passed": all(checks),
        "fact_admission_checks": admission_checks,
        "plan_fact_coverage_checks": plan_checks,
        "rendered_fact_coverage_checks": render_checks,
        "answer_relevance_pass": all(item["passed"] for item in render_checks) if render_checks else None,
        "fact_coverage_plan": plan,
        "rejection_checks": rejection_checks,
        "invalid_fact_rejection_pass": rejection_pass,
        "allowed_inferences": _as_list(scenario.get("allowed_inferences")),
        "allowed_inferences_scoring": "not_scored",
        "declared_forbidden_inferences": declared_forbidden,
        "declared_unsupported_claim": declared_unsupported_claim,
        "must_handoff": must_handoff,
        "handoff_pass": handoff_pass,
        "forbidden_claim_violation": formal_forbidden_claim,
        "identity_leakage": identity_leakage,
        "answer_memory_fact_leakage": answer_memory_leakage,
        "unattributed_clause_count": unattributed_clause_count,
        "irrelevant_fact_inclusion_count": irrelevant_fact_inclusion_count,
        "composition_order_instability": composition_order_instability,
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
    admission = [check for row in rows for check in row["fact_admission_checks"]]
    plan = [check for row in rows for check in row["plan_fact_coverage_checks"]]
    rendered = [check for row in rows for check in row["rendered_fact_coverage_checks"]]
    rejected = [check for row in rows for check in row["rejection_checks"]]
    conflict = [check for check in rejected if check["expected_reason"] == "conflicting_evidence"]
    l3 = [row for row in rows if row["reasoning_tier"] == "L3" and row["must_handoff"]]
    declared = [row for row in rows if row["declared_forbidden_inferences"]]
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
        "schema_version": "grounded-reasoning-positive-eval-result-v3",
        "total": len(rows), "evaluated": len(rows), "skipped": 0,
        "passed": sum(row["passed"] for row in rows), "failed": sum(not row["passed"] for row in rows),
        "fact_admission_rate": _metric(sum(check["passed"] for check in admission), len(admission)),
        "invalid_fact_rejection_rate": _metric(sum(check["passed"] for check in rejected), len(rejected)),
        "plan_fact_coverage_rate": _metric(sum(check["passed"] for check in plan), len(plan)),
        "rendered_fact_coverage_rate": _metric(sum(check["passed"] for check in rendered), len(rendered)),
        "answer_relevance_rate": _metric(sum(row["answer_relevance_pass"] is True for row in rows if row["answer_relevance_pass"] is not None), sum(row["answer_relevance_pass"] is not None for row in rows)),
        "declared_unsupported_claim_rate": _metric(sum(row["declared_unsupported_claim"] for row in declared), len(declared)),
        "forbidden_claim_violation_rate": _metric(sum(row["forbidden_claim_violation"] for row in rows), len(rows)),
        "allowed_inferences_scoring": "not_scored",
        "identity_leakage_count": sum(row["identity_leakage"] for row in rows),
        "answer_memory_fact_leakage_count": sum(row["answer_memory_fact_leakage"] for row in rows),
        "unattributed_clause_count": sum(row["unattributed_clause_count"] for row in rows),
        "irrelevant_fact_inclusion_count": sum(row["irrelevant_fact_inclusion_count"] for row in rows),
        "composition_order_instability_count": sum(row["composition_order_instability"] for row in rows),
        "conflict_block_rate": _metric(sum(check["passed"] for check in conflict), len(conflict)),
        "high_risk_handoff_rate": _metric(sum(row["handoff_pass"] for row in l3), len(l3)),
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
