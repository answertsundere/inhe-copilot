from scripts.build_grounded_reasoning_positive_eval_set import build_eval_payload, build_synthetic_eval_set
from scripts.run_grounded_reasoning_positive_eval import evaluate_scenario, run_eval
import json


def test_synthetic_eval_set_has_required_reasoning_tier_coverage():
    payload = build_eval_payload()

    assert payload["scenario_count"] >= 30
    assert payload["reasoning_tier_counts"]["L0"] >= 12
    assert payload["reasoning_tier_counts"]["L1"] >= 8
    assert payload["reasoning_tier_counts"]["L2"] >= 5
    assert payload["reasoning_tier_counts"]["L3"] >= 5
    assert all(item["source"] == "synthetic_fixture" for item in payload["scenarios"])


def test_positive_direct_fact_is_admitted_and_used_in_fact_bound_draft():
    scenario = next(item for item in build_synthetic_eval_set() if item["scenario_uid"] == "synthetic-l0-02")

    row = evaluate_scenario(scenario)

    assert row["expected_fact_pass"] is True
    assert row["answer_relevance_pass"] is True
    assert row["can_change_can_send"] is False
    assert row["used_for_final_reply"] is False


def test_rejection_controls_remain_rejected_and_answer_memory_cannot_become_fact():
    scenario = next(item for item in build_synthetic_eval_set() if item["scenario_uid"] == "synthetic-l3-reject-04")

    row = evaluate_scenario(scenario)

    assert row["expected_rejection_pass"] is True
    assert row["answer_memory_fact_leakage"] is False
    assert row["used_facts"] == []


def test_eval_expectations_are_scored_after_the_draft_call(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {
            "grounded_draft": "宽度为80cm",
            "used_facts": [{"attribute_key": "width", "source": "selected_evidence"}],
            "rejected_evidence": [],
            "admission_warnings": [],
            "requires_human_review": False,
            "can_change_can_send": False,
            "used_for_final_reply": False,
            "forbidden_claims": [],
        }

    monkeypatch.setattr(runner, "build_grounded_reasoning_draft", fake_build)
    scenario = next(item for item in build_synthetic_eval_set() if item["scenario_uid"] == "synthetic-l0-02")
    row = runner.evaluate_scenario(scenario)

    assert row["passed"] is True
    assert "expected_fact_keys" not in captured
    assert "forbidden_claims" not in captured
    assert "allowed_inferences" not in captured


def test_eval_reports_shadow_invariants_and_grouped_metrics():
    result = run_eval(build_synthetic_eval_set())

    assert result["identity_leakage_count"] == 0
    assert result["answer_memory_fact_leakage_count"] == 0
    assert result["can_change_can_send_count"] == 0
    assert result["conflict_block_rate"] == 1.0
    assert result["high_risk_handoff_rate"] == 1.0
    assert {"L0", "L1", "L2", "L3"}.issubset(result["by_reasoning_tier"])


def test_report_serialization_is_ascii_json_for_windows_powershell_compatibility():
    encoded = json.dumps(run_eval(build_synthetic_eval_set()), ensure_ascii=True, indent=2)

    assert encoded.isascii()
    assert json.loads(encoded)["total"] >= 30


def test_generic_draft_composition_surfaces_an_admitted_low_risk_fact():
    scenario = next(item for item in build_synthetic_eval_set() if item["scenario_uid"] == "synthetic-l0-06")

    row = evaluate_scenario(scenario)

    assert row["expected_fact_pass"] is True
    assert row["answer_relevance_pass"] is True
    assert "承重" in row["grounded_draft"]
