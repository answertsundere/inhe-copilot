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
    if isinstance(payload, dict):
        return [item for item in _as_list(payload.get("scenarios")) if isinstance(item, dict)]
    return [item for item in _as_list(payload) if isinstance(item, dict)]


def _contains_forbidden_claim(draft_text: str, claims: list[Any]) -> bool:
    return any(contains_asserted_claim(draft_text, str(claim)) for claim in claims if str(claim).strip())


def evaluate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Score a scenario without ever passing expectation fields to the draft builder."""
    draft = build_grounded_reasoning_draft(
        customer_message=str(scenario.get("customer_message") or ""),
        query_fact_type=str(scenario.get("query_fact_type") or ""),
        product_identity=_as_dict(scenario.get("product_identity")),
        selected_evidence=[item for item in _as_list(scenario.get("selected_evidence")) if isinstance(item, dict)],
        product_context_pack=_as_dict(scenario.get("product_context_pack")),
        answer_memory_guidance=_as_dict(scenario.get("answer_memory_guidance")),
        reply_blocks=[],
    )
    used_facts = _as_list(draft.get("used_facts"))
    rejected = _as_list(draft.get("rejected_evidence"))
    expected_keys = {str(value) for value in _as_list(scenario.get("expected_fact_keys")) if str(value)}
    used_keys = {str(_as_dict(item).get("attribute_key") or "") for item in used_facts}
    expected_rejections = {str(value) for value in _as_list(scenario.get("expected_rejection_reasons")) if str(value)}
    actual_rejections = {str(_as_dict(item).get("reason") or "") for item in rejected}
    expected_terms = [str(value) for value in _as_list(scenario.get("expected_draft_terms")) if str(value)]
    draft_text = str(draft.get("grounded_draft") or "")
    forbidden_claims = _as_list(scenario.get("forbidden_claims"))
    expected_fact_pass = expected_keys.issubset(used_keys)
    expected_rejection_pass = expected_rejections.issubset(actual_rejections)
    answer_relevance_pass = all(term in draft_text for term in expected_terms)
    must_handoff = bool(scenario.get("must_handoff"))
    handoff_pass = not must_handoff or bool(draft.get("requires_human_review"))
    forbidden_claim_violation = _contains_forbidden_claim(draft_text, forbidden_claims) or has_forbidden_claim_violation(draft)
    identity_leakage = any(
        "identity" in str(_as_dict(item).get("source") or "").lower()
        for item in used_facts
    ) and bool(expected_rejections.intersection({"product_identity_mismatch", "product_identity_namespace_missing", "product_identity_missing"}))
    answer_memory_leakage = used_answer_memory_as_fact(draft)
    checks = []
    if expected_keys:
        checks.append(expected_fact_pass)
    if expected_rejections:
        checks.append(expected_rejection_pass)
    if expected_terms:
        checks.append(answer_relevance_pass)
    if must_handoff:
        checks.append(handoff_pass)
    checks.extend([
        not forbidden_claim_violation,
        not identity_leakage,
        not answer_memory_leakage,
        draft.get("can_change_can_send") is False,
        draft.get("used_for_final_reply") is False,
    ])
    return {
        "scenario_uid": scenario.get("scenario_uid"),
        "source": scenario.get("source", ""),
        "reasoning_tier": scenario.get("reasoning_tier", ""),
        "query_fact_type": scenario.get("query_fact_type", ""),
        "passed": all(checks),
        "expected_fact_keys": sorted(expected_keys),
        "used_fact_keys": sorted(key for key in used_keys if key),
        "expected_fact_pass": expected_fact_pass,
        "expected_rejection_reasons": sorted(expected_rejections),
        "actual_rejection_reasons": sorted(actual_rejections),
        "expected_rejection_pass": expected_rejection_pass,
        "expected_draft_terms": expected_terms,
        "answer_relevance_pass": answer_relevance_pass,
        "must_handoff": must_handoff,
        "handoff_pass": handoff_pass,
        "forbidden_claim_violation": forbidden_claim_violation,
        "identity_leakage": identity_leakage,
        "answer_memory_fact_leakage": answer_memory_leakage,
        "can_change_can_send": draft.get("can_change_can_send"),
        "used_for_final_reply": draft.get("used_for_final_reply"),
        "used_facts": used_facts,
        "rejected_evidence": rejected,
        "admission_warnings": _as_list(draft.get("admission_warnings")),
        "grounded_draft": draft_text,
        "failure_reasons": [
            reason
            for reason, failed in (
                ("expected_fact_missing", bool(expected_keys) and not expected_fact_pass),
                ("expected_rejection_missing", bool(expected_rejections) and not expected_rejection_pass),
                ("answer_not_relevant", bool(expected_terms) and not answer_relevance_pass),
                ("high_risk_handoff_missing", must_handoff and not handoff_pass),
                ("forbidden_claim_violation", forbidden_claim_violation),
                ("identity_leakage", identity_leakage),
                ("answer_memory_fact_leakage", answer_memory_leakage),
                ("shadow_contract_violation", draft.get("can_change_can_send") is not False or draft.get("used_for_final_reply") is not False),
            )
            if failed
        ],
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def run_eval(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [evaluate_scenario(scenario) for scenario in scenarios]
    expected_fact_rows = [row for row in rows if row["expected_fact_keys"]]
    rejected_rows = [row for row in rows if row["expected_rejection_reasons"]]
    l3_rows = [row for row in rows if row["reasoning_tier"] == "L3" and row["must_handoff"]]
    conflict_rows = [row for row in rows if "conflicting_evidence" in row["expected_rejection_reasons"]]
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
        "schema_version": "grounded-reasoning-positive-eval-result-v1",
        "total": len(rows),
        "evaluated": len(rows),
        "skipped": 0,
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "valid_fact_admission_rate": _rate(sum(row["expected_fact_pass"] for row in expected_fact_rows), len(expected_fact_rows)),
        "invalid_fact_rejection_rate": _rate(sum(row["expected_rejection_pass"] for row in rejected_rows), len(rejected_rows)),
        "expected_fact_coverage_rate": _rate(sum(row["expected_fact_pass"] for row in expected_fact_rows), len(expected_fact_rows)),
        "answer_relevance_rate": _rate(sum(row["answer_relevance_pass"] for row in rows if row["expected_draft_terms"]), sum(bool(row["expected_draft_terms"]) for row in rows)),
        "unsupported_inference_rate": _rate(sum(row["forbidden_claim_violation"] for row in rows), len(rows)),
        "identity_leakage_count": sum(row["identity_leakage"] for row in rows),
        "answer_memory_fact_leakage_count": sum(row["answer_memory_fact_leakage"] for row in rows),
        "conflict_block_rate": _rate(sum(row["expected_rejection_pass"] for row in conflict_rows), len(conflict_rows)),
        "high_risk_handoff_rate": _rate(sum(row["handoff_pass"] for row in l3_rows), len(l3_rows)),
        "forbidden_claim_violation_count": sum(row["forbidden_claim_violation"] for row in rows),
        "can_change_can_send_count": sum(row["can_change_can_send"] is not False for row in rows),
        "by_reasoning_tier": {key: dict(value, pass_rate=_rate(value["passed"], value["total"])) for key, value in sorted(by_tier.items())},
        "by_query_fact_type": {key: dict(value, pass_rate=_rate(value["passed"], value["total"])) for key, value in sorted(by_fact_type.items())},
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
    # ASCII JSON keeps Windows PowerShell 5's default Get-Content decoding safe.
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
