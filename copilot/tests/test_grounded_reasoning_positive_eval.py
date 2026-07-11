import json

from scripts.build_grounded_reasoning_positive_eval_set import build_eval_payload, build_synthetic_eval_set
from scripts.run_grounded_reasoning_positive_eval import evaluate_scenario, run_eval


def _scenario(uid: str):
    return next(item for item in build_synthetic_eval_set() if item["scenario_uid"] == uid)


def _fake_draft(*, text="", used_facts=None, rejected_evidence=None):
    return {
        "grounded_draft": text,
        "used_facts": used_facts or [],
        "rejected_evidence": rejected_evidence or [],
        "admission_warnings": [],
        "requires_human_review": True,
        "can_change_can_send": False,
        "used_for_final_reply": False,
        "forbidden_claims": [],
    }


def test_synthetic_eval_set_has_required_reasoning_tier_coverage_and_stable_evidence_uids():
    payload = build_eval_payload()
    evidence = [fact for scenario in payload["scenarios"] for fact in scenario["selected_evidence"]]

    assert payload["scenario_count"] >= 30
    assert payload["reasoning_tier_counts"] == {"L0": 12, "L1": 8, "L2": 5, "L3": 12}
    assert all(fact["evidence_uid"].startswith("ev-") for fact in evidence)
    assert all(len(fact["evidence_uid"]) == 17 for fact in evidence)


def test_positive_direct_fact_is_admitted_with_stable_provenance():
    row = evaluate_scenario(_scenario("synthetic-l0-02"))

    assert row["fact_admission_pass"] is True
    assert row["draft_fact_coverage_pass"] is True
    assert row["used_facts"][0]["evidence_uid"].startswith("ev-")
    assert row["used_facts"][0]["identity_namespace"] == "sku_code"
    assert row["used_facts"][0]["identity_value"]


def test_identity_mismatch_leakage_fails_even_when_rejection_reason_is_present(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l3-reject-01")
    evidence_uid = scenario["expected_rejected_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            used_facts=[{"evidence_uid": evidence_uid, "source": "selected_evidence"}],
            rejected_evidence=[{"evidence_uid": evidence_uid, "reason": "product_identity_mismatch"}],
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["invalid_fact_rejection_pass"] is False
    assert row["identity_leakage"] is True
    assert row["rejection_checks"][0]["expected_identity_scope"]
    assert "identity_leakage" in row["failure_reasons"]


def test_l1_requires_draft_coverage_for_every_required_fact(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l1-01")
    used = [{"evidence_uid": item["evidence_uid"]} for item in scenario["expected_admitted_evidence"]]
    monkeypatch.setattr(runner, "build_grounded_reasoning_draft", lambda **_: _fake_draft(text="高度为120cm", used_facts=used))

    row = runner.evaluate_scenario(scenario)

    assert row["fact_admission_pass"] is True
    assert row["draft_fact_coverage_pass"] is False
    assert "draft_fact_coverage_missing" in row["failure_reasons"]


def test_declared_forbidden_inference_fails_after_valid_fact_admission(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l3-risk-05")
    monkeypatch.setattr(runner, "build_grounded_reasoning_draft", lambda **_: _fake_draft(text="可以保证承重", used_facts=[]))

    row = runner.evaluate_scenario(scenario)

    assert row["declared_unsupported_claim"] is True
    assert "declared_unsupported_claim" in row["failure_reasons"]


def test_rejection_reason_without_evidence_exclusion_fails(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l3-reject-04")
    evidence_uid = scenario["expected_rejected_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            used_facts=[{"evidence_uid": evidence_uid}],
            rejected_evidence=[{"evidence_uid": evidence_uid, "reason": "reference_only"}],
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["invalid_fact_rejection_pass"] is False
    assert "invalid_evidence_rejection_failed" in row["failure_reasons"]


def test_answer_memory_cannot_enter_used_facts(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(text="宽度为80cm", used_facts=[{"evidence_uid": scenario["expected_admitted_evidence"][0]["evidence_uid"], "source": "answer_memory"}]),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["answer_memory_fact_leakage"] is True
    assert "answer_memory_fact_leakage" in row["failure_reasons"]


def test_expectations_are_never_forwarded_to_the_draft_builder(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return _fake_draft(
            text="宽度为80cm",
            used_facts=[{"evidence_uid": _scenario("synthetic-l0-02")["expected_admitted_evidence"][0]["evidence_uid"]}],
        )

    monkeypatch.setattr(runner, "build_grounded_reasoning_draft", fake_build)
    runner.evaluate_scenario(_scenario("synthetic-l0-02"))

    assert not {"expected_fact_keys", "expected_admitted_evidence", "required_draft_facts", "allowed_inferences", "declared_forbidden_inferences"}.intersection(captured)


def test_empty_required_terms_are_not_automatically_relevant(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    scenario["required_draft_facts"] = [{"fact_key": "width", "required_terms": [], "matcher": "all_terms"}]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(used_facts=[{"evidence_uid": scenario["expected_admitted_evidence"][0]["evidence_uid"]}]),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["draft_fact_coverage_pass"] is False
    assert row["answer_relevance_pass"] is False


def test_rates_include_explicit_numerators_and_denominators():
    result = run_eval(build_synthetic_eval_set())

    for name in (
        "fact_admission_rate",
        "invalid_fact_rejection_rate",
        "draft_fact_coverage_rate",
        "answer_relevance_rate",
        "declared_unsupported_claim_rate",
        "forbidden_claim_violation_rate",
        "conflict_block_rate",
        "high_risk_handoff_rate",
    ):
        assert set(result[name]) == {"numerator", "denominator", "rate"}
    assert result["allowed_inferences_scoring"] == "not_scored"
    assert result["identity_leakage_count"] == 0
    assert result["answer_memory_fact_leakage_count"] == 0
    assert result["can_change_can_send_count"] == 0


def test_report_serialization_is_ascii_json_for_windows_powershell_compatibility():
    encoded = json.dumps(run_eval(build_synthetic_eval_set()), ensure_ascii=True, indent=2)

    assert encoded.isascii()
    assert json.loads(encoded)["total"] >= 30
