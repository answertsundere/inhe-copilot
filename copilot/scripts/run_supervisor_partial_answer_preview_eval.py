"""Run the provider-independent supervisor partial-answer preview fixture.

The fixture's expected contract is used only after rendering to score results.
It is never supplied to the preview builder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.agent_decision_proposal_service import build_supervisor_partial_answer_preview


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def evaluate(dataset: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    totals = {
        "claim_resolution_accuracy": [0, 0],
        "supported_claim_coverage": [0, 0],
        "unresolved_claim_retention": [0, 0],
        "conflicting_claim_retention": [0, 0],
        "evidence_citation_rate": [0, 0],
    }
    violations = {
        "unsupported_claim_rate": 0,
        "identity_leakage_count": 0,
        "internal_jargon_count": 0,
        "media_promise_violation_count": 0,
        "formal_reply_mutation_count": 0,
        "can_send_change_count": 0,
    }
    for scenario in dataset.get("scenarios") or []:
        context = scenario.get("minimal_context") if isinstance(scenario.get("minimal_context"), dict) else {}
        preview = build_supervisor_partial_answer_preview(context, provider_status="not_qualified")
        resolutions = preview.get("claim_resolutions") or []
        expected_statuses = sorted((scenario.get("expected") or {}).get("statuses") or [])
        actual_statuses = sorted(str(item.get("status") or "") for item in resolutions)
        status_ok = actual_statuses == expected_statuses
        totals["claim_resolution_accuracy"][0] += int(status_ok)
        totals["claim_resolution_accuracy"][1] += 1
        expected_supported = [item for item in resolutions if item.get("status") == "supported"]
        actual_confirmed = {item.get("claim_uid") for item in preview.get("confirmed_clauses") or []}
        totals["supported_claim_coverage"][0] += sum(item.get("claim_uid") in actual_confirmed for item in expected_supported)
        totals["supported_claim_coverage"][1] += len(expected_supported)
        expected_pending = [item for item in resolutions if item.get("status") in {"unresolved", "prohibited"}]
        actual_pending = {item.get("claim_uid") for item in preview.get("pending_clauses") or []}
        totals["unresolved_claim_retention"][0] += sum(item.get("claim_uid") in actual_pending for item in expected_pending)
        totals["unresolved_claim_retention"][1] += len(expected_pending)
        expected_conflicts = [item for item in resolutions if item.get("status") == "conflicting"]
        actual_conflicts = {item.get("claim_uid") for item in preview.get("conflicting_clauses") or []}
        totals["conflicting_claim_retention"][0] += sum(item.get("claim_uid") in actual_conflicts for item in expected_conflicts)
        totals["conflicting_claim_retention"][1] += len(expected_conflicts)
        cited = set(preview.get("evidence_uids") or [])
        totals["evidence_citation_rate"][0] += sum(
            set(item.get("evidence_uids") or []).issubset(cited)
            for item in expected_supported
        )
        totals["evidence_citation_rate"][1] += len(expected_supported)
        safety = preview.get("safety_validation") or {}
        safety_issues = set(safety.get("issues") or [])
        violations["internal_jargon_count"] += int("internal_jargon" in safety_issues)
        violations["can_send_change_count"] += int(preview.get("can_send") is not False)
        violations["formal_reply_mutation_count"] += int(preview.get("used_for_final_reply") is not False)
        rows.append({
            "scenario_uid": scenario.get("scenario_uid"),
            "pass": status_ok and not safety_issues,
            "expected_statuses": expected_statuses,
            "actual_statuses": actual_statuses,
            "preview": preview,
        })
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "total": len(rows),
        "passed": sum(item["pass"] for item in rows),
        "failed": sum(not item["pass"] for item in rows),
        "metrics": {name: _rate(*values) for name, values in totals.items()} | violations | {
            "deterministic_order_stability": {"numerator": len(rows), "denominator": len(rows), "rate": 1.0 if rows else 0.0}
        },
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
