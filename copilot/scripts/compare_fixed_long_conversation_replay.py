"""Compare paired OFF/ON fixed replay reports without claiming accuracy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.long_conversation_simulation_service import summarize_fixed_replay_results  # noqa: E402
from scripts.run_long_conversation_simulation import _write_json_atomic  # noqa: E402


def _turn_map(report: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    return {
        (str(result.get("scenario_uid") or ""), int(turn.get("turn_index") or 0)): turn.get("observation") or {}
        for result in report.get("results") or []
        for turn in result.get("turns") or []
    }


def compare_reports(off: dict[str, Any], on: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if off.get("run_mode") != "OFF" or on.get("run_mode") != "ON":
        findings.append("run_mode_invalid")
    for field in ("content_sha256", "scenario_count", "fixed_buyer_turn_count"):
        if (off.get("dataset") or {}).get(field) != (on.get("dataset") or {}).get(field):
            findings.append(f"dataset_{field}_mismatch")
    for field in ("runtime_commit", "source_tree_sha256", "formal_model"):
        if (off.get("runtime") or {}).get(field) != (on.get("runtime") or {}).get(field):
            findings.append(f"runtime_{field}_mismatch")
    for field in ("formal_content_sha256", "formal_tables"):
        if (off.get("formal_knowledge_database_before") or {}).get(field) != (on.get("formal_knowledge_database_before") or {}).get(field):
            findings.append(f"knowledge_database_{field}_mismatch")
    off_turns = _turn_map(off)
    on_turns = _turn_map(on)
    if set(off_turns) != set(on_turns):
        findings.append("paired_turn_set_mismatch")
    off_summary = summarize_fixed_replay_results(off.get("results") or [])
    on_summary = summarize_fixed_replay_results(on.get("results") or [])
    metric_fields = (
        "selected_evidence_total_count",
        "unsafe_auto_send_count",
        "unsupported_media_promise_count",
        "media_role_mismatch_count",
        "requires_human_review_count",
        "final_audit_failure_count",
        "semantic_fit_failure_count",
    )
    differences = {
        field: {
            "off": off_summary.get(field),
            "on": on_summary.get(field),
            "delta": int(on_summary.get(field) or 0) - int(off_summary.get(field) or 0),
        }
        for field in metric_fields
    }
    if differences["unsafe_auto_send_count"]["delta"] > 0:
        findings.append("on_unsafe_auto_send_regression")
    if int(on_summary.get("media_role_mismatch_count") or 0):
        findings.append("on_media_role_mismatch")
    paired = []
    for key in sorted(set(off_turns) & set(on_turns)):
        before = off_turns[key]
        after = on_turns[key]
        paired.append({
            "scenario_uid": key[0],
            "turn_index": key[1],
            "off_selected_evidence_count": int(before.get("selected_evidence_count") or 0),
            "on_selected_evidence_count": int(after.get("selected_evidence_count") or 0),
            "off_breakpoint": str(before.get("earliest_breakpoint") or ""),
            "on_breakpoint": str(after.get("earliest_breakpoint") or ""),
            "off_reply_sha256": str(before.get("normalized_reply_sha256") or ""),
            "on_reply_sha256": str(after.get("normalized_reply_sha256") or ""),
        })
    return {
        "schema_version": "fixed-long-conversation-replay-comparison/v1",
        "evaluation_tier": "tier_d_fixed_real_turn_replay",
        "accuracy_claim_allowed": False,
        "paired_turn_count": len(paired),
        "contract_findings": sorted(set(findings)),
        "comparison_valid": not findings,
        "metric_differences": differences,
        "offline_recomputed_summaries": {"off": off_summary, "on": on_summary},
        "paired_turns": paired,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--off-report", required=True)
    parser.add_argument("--on-report", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    off = json.loads(Path(args.off_report).read_text(encoding="utf-8"))
    on = json.loads(Path(args.on_report).read_text(encoding="utf-8"))
    comparison = compare_reports(off, on)
    _write_json_atomic(Path(args.json_output), comparison)
    print(json.dumps({
        "paired_turn_count": comparison["paired_turn_count"],
        "comparison_valid": comparison["comparison_valid"],
        "contract_findings": comparison["contract_findings"],
    }, ensure_ascii=False))
    return 0 if comparison["comparison_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
