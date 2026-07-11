import json

from scripts.build_grounded_reasoning_positive_eval_set import build_eval_payload, build_synthetic_eval_set
from scripts.run_grounded_reasoning_positive_eval import evaluate_scenario, run_eval


def _scenario(uid: str):
    return next(item for item in build_synthetic_eval_set() if item["scenario_uid"] == uid)


def _plan(*uids, rendered=None, attributes=None):
    attributes = attributes or {}
    return {
        "composition_mode": "fact_bound_multi_clause" if len(uids) > 1 else "single_fact",
        "selected_evidence_uids": list(uids),
        "rendered_evidence_uids": list(uids if rendered is None else rendered),
        "factual_clauses": [
            {"evidence_uid": uid, "attribute_key": attributes.get(uid, "width"), "text": "fixture fact"}
            for uid in uids
        ],
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def _fake_draft(*, text="", used_facts=None, rejected_evidence=None, plan=None, segments=None):
    return {
        "grounded_draft": text,
        "draft_segments": segments if segments is not None else [],
        "used_facts": used_facts or [],
        "rejected_evidence": rejected_evidence or [],
        "fact_coverage_plan": plan or _plan(),
        "admission_warnings": [],
        "requires_human_review": True,
        "can_change_can_send": False,
        "used_for_final_reply": False,
        "forbidden_claims": [],
    }


def test_synthetic_eval_set_has_required_reasoning_tier_coverage_and_stable_evidence_uids():
    payload = build_eval_payload()
    evidence = [fact for scenario in payload["scenarios"] for fact in scenario["selected_evidence"]]

    assert payload["reasoning_tier_counts"] == {"L0": 12, "L1": 8, "L2": 5, "L3": 12}
    assert all(fact["evidence_uid"].startswith("ev-") for fact in evidence)
    assert all(len(fact["evidence_uid"]) == 17 for fact in evidence)


def test_multifact_plan_renders_every_admitted_required_fact():
    row = evaluate_scenario(_scenario("synthetic-l1-01"))

    assert row["passed"] is True
    assert len(row["fact_coverage_plan"]["factual_clauses"]) == 2
    assert {item["attribute_key"] for item in row["fact_coverage_plan"]["factual_clauses"]} == {"width", "height"}
    assert all(check["passed"] for check in row["plan_fact_coverage_checks"])
    assert all(check["passed"] for check in row["rendered_fact_coverage_checks"])


def test_multifact_draft_covering_only_one_fact_fails(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l1-01")
    expected = scenario["expected_admitted_evidence"]
    uids = [item["evidence_uid"] for item in expected]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="高度为120cm",
            used_facts=[{"evidence_uid": uid} for uid in uids],
            plan=_plan(*uids, rendered=[uids[1]]),
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["passed"] is False
    assert "planned_fact_not_rendered" in row["failure_reasons"]


def test_composition_is_order_independent_for_fact_sets():
    row = evaluate_scenario(_scenario("synthetic-l1-03"))

    assert row["composition_order_instability"] is False
    assert len(row["fact_coverage_plan"]["selected_evidence_uids"]) == 2


def test_irrelevant_used_fact_is_not_included_in_plan(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    expected_uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm",
            used_facts=[{"evidence_uid": expected_uid}],
            plan=_plan(expected_uid, "ev-9999-9999-9999", attributes={expected_uid: "width", "ev-9999-9999-9999": "depth"}),
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["irrelevant_fact_inclusion_count"] == 1
    assert "irrelevant_fact_inclusion" in row["failure_reasons"]


def test_rejected_conflicting_and_non_fact_roles_never_enter_plan():
    for uid in ("synthetic-l3-reject-05", "synthetic-l3-reject-06", "synthetic-l3-reject-07"):
        row = evaluate_scenario(_scenario(uid))
        assert row["fact_coverage_plan"]["selected_evidence_uids"] == []
        assert row["invalid_fact_rejection_pass"] is True


def test_identity_mismatch_leakage_fails_even_when_rejection_reason_is_present(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l3-reject-01")
    evidence_uid = scenario["expected_rejected_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            used_facts=[{"evidence_uid": evidence_uid, "identity_scopes": [{"namespace": "i_id", "value": "OTHER"}]}],
            rejected_evidence=[{"evidence_uid": evidence_uid, "reason": "product_identity_mismatch"}],
            plan=_plan(evidence_uid),
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["identity_leakage"] is True
    assert "identity_leakage" in row["failure_reasons"]


def test_rendered_claim_without_evidence_uid_fails(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    evidence_uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(text="宽度为80cm", used_facts=[{"evidence_uid": evidence_uid}], plan=_plan()),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["required_fact_attribution_failure_count"] == 1
    assert "required_fact_attribution_failure" in row["failure_reasons"]


def test_answer_memory_cannot_enter_factual_plan(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    evidence_uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(text="宽度为80cm", used_facts=[{"evidence_uid": evidence_uid, "source": "answer_memory"}], plan=_plan(evidence_uid)),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["answer_memory_fact_leakage"] is True


def test_expectations_are_never_forwarded_to_the_draft_builder(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    evidence_uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return _fake_draft(text="宽度为80cm", used_facts=[{"evidence_uid": evidence_uid}], plan=_plan(evidence_uid))

    monkeypatch.setattr(runner, "build_grounded_reasoning_draft", fake_build)
    runner.evaluate_scenario(scenario)

    assert not {"expected_admitted_evidence", "required_draft_facts", "allowed_inferences", "declared_forbidden_inferences"}.intersection(captured)


def test_draft_outside_segments_fails_render_integrity(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm 还可以长期泡水使用",
            used_facts=[{"evidence_uid": uid}],
            plan=_plan(uid),
            segments=[{"type": "factual_clause", "text": "宽度为80cm", "evidence_uid": uid}],
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["draft_render_integrity_pass"] is False
    assert "draft_integrity_violation" in row["failure_reasons"]


def test_factual_segment_requires_selected_evidence_uid(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm",
            used_facts=[{"evidence_uid": uid}],
            plan=_plan(uid),
            segments=[{"type": "factual_clause", "text": "宽度为80cm"}],
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["factual_clause_without_evidence_count"] == 1
    assert row["unrendered_planned_fact_count"] == 1


def test_factual_segment_cannot_reference_unplanned_or_non_fact_sources(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    uid = scenario["expected_admitted_evidence"][0]["evidence_uid"]
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm 安装资料可参考",
            used_facts=[{"evidence_uid": uid}],
            plan=_plan(uid),
            segments=[
                {"type": "factual_clause", "text": "宽度为80cm", "evidence_uid": uid},
                {"type": "factual_clause", "text": "安装资料可参考", "evidence_uid": "memory-or-media"},
            ],
        ),
    )

    row = runner.evaluate_scenario(scenario)

    assert row["factual_clause_not_in_plan_count"] == 1


def test_explicit_selection_empty_plan_does_not_pass(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l1-01")
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="请核对尺寸资料。",
            used_facts=[
                {"evidence_uid": item["evidence_uid"], "attribute_key": item["fact_key"]}
                for item in scenario["expected_admitted_evidence"]
            ],
            segments=[{"type": "customer_copy", "text": "请核对尺寸资料。"}],
        ),
    )

    row = runner.evaluate_scenario(scenario)
    check = row["requested_attribute_selection_checks"][0]

    assert check["passed"] is False
    assert check["available_requested_attribute_count"] == 2
    assert check["selected_requested_attribute_count"] == 0
    assert check["missing_requested_attribute_count"] == 2


def test_explicit_selection_detects_missing_and_unexpected_attributes(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l1-01")
    by_key = {item["fact_key"]: item["evidence_uid"] for item in scenario["expected_admitted_evidence"]}
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm 深度为35cm",
            used_facts=[
                {"evidence_uid": uid, "attribute_key": key}
                for key, uid in by_key.items()
            ],
            plan=_plan(by_key["width"], "ev-unexpected-depth", attributes={by_key["width"]: "width", "ev-unexpected-depth": "depth"}),
            segments=[
                {"type": "factual_clause", "text": "宽度为80cm", "evidence_uid": by_key["width"]},
                {"type": "factual_clause", "text": "深度为35cm", "evidence_uid": "ev-unexpected-depth"},
            ],
        ),
    )

    row = runner.evaluate_scenario(scenario)
    check = row["requested_attribute_selection_checks"][0]

    assert check["missing_requested_attribute_keys"] == ["height"]
    assert check["unexpected_selected_attribute_keys"] == ["depth"]
    assert check["passed"] is False


def test_explicit_selection_without_available_fact_is_no_evidence_not_success(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l0-02")
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="请核对尺寸资料。",
            segments=[{"type": "customer_copy", "text": "请核对尺寸资料。"}],
        ),
    )

    row = runner.evaluate_scenario(scenario)
    check = row["requested_attribute_selection_checks"][0]

    assert check["denominator"] == 0
    assert check["rate"] is None
    assert check["no_evidence_requested_attribute_count"] == 1
    assert check["passed"] is False


def test_mixed_evidence_coverage_does_not_equal_explicit_request_completeness(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l1-01")
    width_uid = next(item["evidence_uid"] for item in scenario["expected_admitted_evidence"] if item["fact_key"] == "width")
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm",
            used_facts=[{"evidence_uid": width_uid, "attribute_key": "width"}],
            plan=_plan(width_uid, attributes={width_uid: "width"}),
            segments=[{"type": "factual_clause", "text": "宽度为80cm", "evidence_uid": width_uid}],
        ),
    )

    row = runner.evaluate_scenario(scenario)
    check = row["requested_attribute_selection_checks"][0]

    assert check["coverage_rate"] == 1.0
    assert check["explicit_request_complete"] is False
    assert check["no_evidence_requested_attribute_keys"] == ["height"]
    assert row["passed"] is False
    assert "requested_attribute_no_evidence" in row["failure_reasons"]


def test_missing_available_requested_attribute_has_coverage_gap_reason(monkeypatch):
    import scripts.run_grounded_reasoning_positive_eval as runner

    scenario = _scenario("synthetic-l1-01")
    uids = {item["fact_key"]: item["evidence_uid"] for item in scenario["expected_admitted_evidence"]}
    monkeypatch.setattr(
        runner,
        "build_grounded_reasoning_draft",
        lambda **_: _fake_draft(
            text="宽度为80cm",
            used_facts=[
                {"evidence_uid": uids["width"], "attribute_key": "width"},
                {"evidence_uid": uids["height"], "attribute_key": "height"},
            ],
            plan=_plan(uids["width"], attributes={uids["width"]: "width"}),
            segments=[{"type": "factual_clause", "text": "宽度为80cm", "evidence_uid": uids["width"]}],
        ),
    )

    row = runner.evaluate_scenario(scenario)
    check = row["requested_attribute_selection_checks"][0]

    assert check["coverage_rate"] == 0.5
    assert check["explicit_request_complete"] is False
    assert "requested_attribute_not_selected" in row["failure_reasons"]


def test_non_explicit_request_does_not_enter_completeness_denominator():
    scenario = dict(_scenario("synthetic-l0-02"), request_scope="broad")
    result = run_eval([scenario])

    assert result["explicit_request_count"] == 0
    assert result["explicit_request_completeness_rate"] == {"numerator": 0, "denominator": 0, "rate": None}


def test_rates_and_shadow_contract_are_explicit():
    result = run_eval(build_synthetic_eval_set())

    for name in (
        "fact_admission_rate", "invalid_fact_rejection_rate", "plan_fact_coverage_rate",
        "rendered_fact_coverage_rate", "answer_relevance_rate", "declared_unsupported_claim_rate",
        "forbidden_claim_violation_rate", "conflict_block_rate", "high_risk_handoff_rate",
    ):
        assert set(result[name]) == {"numerator", "denominator", "rate"}
    assert result["required_fact_attribution_failure_count"] == 0
    assert result["draft_integrity_violation_count"] == 0
    assert result["irrelevant_fact_inclusion_count"] == 0
    assert result["composition_order_instability_count"] == 0
    assert result["can_change_can_send_count"] == 0


def test_report_serialization_is_ascii_json_for_windows_powershell_compatibility():
    encoded = json.dumps(run_eval(build_synthetic_eval_set()), ensure_ascii=True, indent=2)
    assert encoded.isascii()
    assert json.loads(encoded)["total"] >= 30
