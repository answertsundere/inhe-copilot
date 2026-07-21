from __future__ import annotations

import json

from scripts.analyze_tier_d_evidence_action_shadow import analyze_report, main


def test_old_report_does_not_invent_source_gap():
    result = analyze_report({
        "schema_version": "long-conversation-simulation-report-v3",
        "results": [{"turns": [{"observation": {"selected_evidence_count": 0}}]}],
    })

    assert result["evidence_funnel_status"] == "not_captured_in_source_report"
    assert result["gap_classification_counts"] == {}
    assert result["interpretation"].startswith("selected_evidence_zero_cannot_distinguish")


def test_new_report_aggregates_observed_funnel_only():
    result = analyze_report({
        "schema_version": "long-conversation-simulation-report-v3",
        "results": [{"turns": [{"observation": {
            "selected_evidence_count": 1,
            "evidence_action_shadow": {
                "available": True,
                "evidence_funnel": {
                    "gap_classification": "selected_successfully",
                    "earliest_breakpoint": "selected_successfully",
                    "counts": {"formal_selected_count": 1},
                },
                "action_policy": {"status": "completed"},
                "supervisor_candidate_preview": {"candidate_text": "候选回复"},
            },
        }}]}],
    })

    assert result["selected_evidence_turn_count"] == 1
    assert result["gap_classification_counts"] == {"selected_successfully": 1}
    assert result["evidence_funnel_turn_count"] == 1
    assert "action_policy_status_counts" not in result
    assert "candidate_preview_turn_count" not in result


def test_cli_writes_parseable_json(tmp_path):
    source = tmp_path / "report.json"
    output = tmp_path / "analysis.json"
    source.write_text(json.dumps({"schema_version": "v3", "results": []}), encoding="utf-8")

    assert main(["--input", str(source), "--json-output", str(output)]) == 0
    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert len(parsed["source_report_sha256"]) == 64


def test_detailed_gap_classification_is_exclusive_and_redacted():
    report = {
        "schema_version": "long-conversation-simulation-report-v3",
        "results": [
            {
                "scenario_uid": "private-scenario-a",
                "trial": 1,
                "primary_domain": "product_fact_direct",
                "turns": [{"turn_number": 1, "observation": {"evidence_action_shadow": {"evidence_funnel": {
                    "earliest_breakpoint": "no_product_context",
                    "counts": {"candidate_count": 1},
                    "records": [{
                        "source_types": ["product_facts"],
                        "source_containers": ["product_context_pack.evidence_pack.product_structured_facts"],
                        "rejection_reason": "evidence_role_not_direct",
                    }],
                }}}}],
            },
            {
                "scenario_uid": "private-scenario-b",
                "trial": 1,
                "primary_domain": "aftersales_verification",
                "turns": [{"turn_number": 1, "observation": {"evidence_action_shadow": {"evidence_funnel": {
                    "earliest_breakpoint": "no_product_context",
                    "counts": {"candidate_count": 0},
                    "records": [],
                }}}}],
            },
        ],
    }

    result = analyze_report(report)

    assert result["detailed_gap_classification_counts"] == {
        "metadata_contract_missing": 1,
        "order_or_live_tool_required": 1,
    }
    assert all("scenario_uid" not in row for row in result["turn_diagnostics"])
    assert all(row["diagnostic_uid"].startswith("gap-") for row in result["turn_diagnostics"])
