"""Summarize the read-only formal-evidence funnel captured in a Tier D report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ALLOWED_BREAKPOINTS = frozenset({
    "context_missing",
    "product_identity_missing",
    "source_coverage_gap",
    "evidence_role_ineligible",
    "review_status_ineligible",
    "identity_mismatch",
    "fact_type_mismatch",
    "placeholder_value",
    "conflicting_evidence",
    "convergence_disabled",
    "graph_selection_gap",
    "selected_successfully",
})


def _normalize_breakpoint(funnel: dict[str, Any]) -> str:
    raw = str(funnel.get("earliest_breakpoint") or "")
    if raw in ALLOWED_BREAKPOINTS:
        return raw
    counts = funnel.get("counts") if isinstance(funnel.get("counts"), dict) else {}
    aliases = {
        "review_or_direct_evidence_missing": "review_status_ineligible",
        "identity_missing_or_mismatch": "identity_mismatch",
        "fact_type_missing_or_mismatch": "fact_type_mismatch",
        "selected_evidence_dropped": "graph_selection_gap",
    }
    if raw in aliases:
        return aliases[raw]
    if raw == "no_product_context":
        return (
            "source_coverage_gap"
            if int(counts.get("candidate_count") or 0) == 0
            else "evidence_role_ineligible"
        )
    if raw == "formal_admission_rejected":
        reasons = funnel.get("rejected_by_reason") if isinstance(funnel.get("rejected_by_reason"), dict) else {}
        if int(reasons.get("placeholder_fact") or 0):
            return "placeholder_value"
        if int(reasons.get("conflicting_evidence") or 0):
            return "conflicting_evidence"
        return "evidence_role_ineligible"
    if raw in {"none", ""} and int(counts.get("formal_selected_count") or 0) > 0:
        return "selected_successfully"
    raise ValueError(f"evidence_funnel_breakpoint_invalid:{raw or 'missing'}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("tier_d_report_not_object")
    return value


def analyze_report(report: dict[str, Any]) -> dict[str, Any]:
    gap_counts: Counter[str] = Counter()
    breakpoint_counts: Counter[str] = Counter()
    funnel_turn_count = 0
    turn_count = 0
    selected_evidence_turn_count = 0
    turn_diagnostics: list[dict[str, Any]] = []
    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        for turn_index, turn in enumerate(result.get("turns") or [], start=1):
            if not isinstance(turn, dict):
                continue
            turn_count += 1
            observation = turn.get("observation") if isinstance(turn.get("observation"), dict) else {}
            if int(observation.get("selected_evidence_count") or 0) > 0:
                selected_evidence_turn_count += 1
            shadow = observation.get("evidence_action_shadow") if isinstance(observation.get("evidence_action_shadow"), dict) else {}
            funnel = shadow.get("evidence_funnel") if isinstance(shadow.get("evidence_funnel"), dict) else {}
            if not funnel:
                continue
            breakpoint = _normalize_breakpoint(funnel)
            gap = breakpoint
            counts = funnel.get("counts") if isinstance(funnel.get("counts"), dict) else {}
            funnel_turn_count += 1
            gap_counts[gap] += 1
            breakpoint_counts[breakpoint] += 1
            turn_diagnostics.append({
                "scenario_uid": str(result.get("scenario_uid") or ""),
                "trial": int(result.get("trial") or 0),
                "turn_number": int(turn.get("turn_number") or turn_index),
                "earliest_breakpoint": breakpoint,
                "counts": {
                    key: int(counts.get(key) or 0)
                    for key in (
                        "product_context_candidate_count",
                        "direct_fact_candidate_count",
                        "direct_reviewed_count",
                        "identity_matched_count",
                        "fact_type_compatible_count",
                        "non_placeholder_count",
                        "non_conflicting_count",
                        "formally_admissible_count",
                        "formal_selected_count",
                    )
                },
            })

    diagnostics_available = funnel_turn_count > 0
    return {
        "schema_version": "tier-d-formal-evidence-funnel-analysis-v2",
        "source_report_schema_version": str(report.get("schema_version") or ""),
        "turn_count": turn_count,
        "selected_evidence_turn_count": selected_evidence_turn_count,
        "evidence_funnel_turn_count": funnel_turn_count,
        "missing_funnel_turn_count": turn_count - funnel_turn_count,
        "evidence_funnel_status": "available" if diagnostics_available else "not_captured_in_source_report",
        "gap_classification_counts": dict(sorted(gap_counts.items())),
        "earliest_breakpoint_counts": dict(sorted(breakpoint_counts.items())),
        "turn_diagnostics": turn_diagnostics,
        "interpretation": (
            "turn_level_funnel_available"
            if diagnostics_available
            else "selected_evidence_zero_cannot_distinguish_source_gap_from_disabled_or_dropped_convergence"
        ),
        "scoring_contract_changed": False,
        "formal_agent_changed": False,
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.json_output)
    try:
        raw = input_path.read_bytes()
        report = json.loads(raw.decode("utf-8"))
        if not isinstance(report, dict):
            raise ValueError("tier_d_report_not_object")
        result = analyze_report(report)
        result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
