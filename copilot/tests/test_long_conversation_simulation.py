from __future__ import annotations

import copy

import pytest

import app.services.long_conversation_simulation_service as service
import scripts.run_long_conversation_simulation as runner


def _turn(index: int, role: str = "BUYER", text: str | None = None, message_type: str = "text"):
    return {
        "turn_index": index,
        "turn_uid": f"turn_{index}",
        "speaker_role": role,
        "message_type": message_type,
        "text": text or f"第{index}条消息",
    }


def _gold_case(
    case_uid: str,
    target_index: int = 20,
    target_text: str = "这个问题接下来怎么处理",
    expected_evidence=None,
):
    turns = [
        _turn(index, "BUYER" if index % 2 else "AGENT")
        for index in range(1, 26)
    ]
    turns[target_index - 1].update({"speaker_role": "BUYER", "text": target_text})
    return {
        "case_uid": case_uid,
        "sidecar_present": True,
        "expected_evidence": list(expected_evidence or []),
        "conversation": {
            "turns": turns,
            "role_counts": {"BUYER": 13, "AGENT": 12, "SYSTEM": 0},
            "role_unresolved_count": 0,
            "privacy_review_required": False,
            "conversation_truncated": False,
        },
    }


def _review_item(case_uid: str, domain: str, target_index: int = 20, action: str = "verify_order_and_issue"):
    return {
        "case_uid": case_uid,
        "scenario_domain": domain,
        "risk_level": "medium",
        "query_fact_type": "售后",
        "sidecar_quality": "identity_present",
        "target_turn_uids": [f"turn_{target_index}"],
        "required_actions": [action],
        "atomic_claim": {
            "expected_status": "unresolved",
            "must_handoff": True,
            "required_action_points": [action],
        },
    }


def _source_dataset():
    cases = [
        _gold_case("case_a"),
        _gold_case("case_b", expected_evidence=["reviewed_media"]),
        _gold_case("case_c"),
    ]
    return {
        "dataset_id": "gold",
        "dataset_version": "1",
        "privacy": {"privacy_scan_status": "passed"},
        "manifest": {"content_sha256": "gold-hash"},
        "cases": cases,
    }, {
        "items": [
            _review_item("case_a", "aftersales_verification"),
            _review_item("case_b", "media_evidence", action="verify_media_role_and_delivery_block"),
            _review_item("case_c", "installation_accessory", action="locate_step_or_component"),
        ],
    }


def test_builder_selects_balanced_long_scenarios_without_enabling_accuracy(monkeypatch):
    gold, queue = _source_dataset()
    monkeypatch.setattr(service, "validate_gold_dataset", lambda _: [])
    dataset = service.build_long_conversation_dataset(gold, queue, limit=3, max_per_domain=1)
    assert dataset["selection"]["selected_count"] == 3
    assert dataset["selection"]["domain_count"] == 3
    assert dataset["accuracy_claim_allowed"] is False
    assert all(item["hidden_goal_contract"]["fact_correctness_scorable"] is False for item in dataset["scenarios"])
    assert all(len(item["seed_history"]) == 12 for item in dataset["scenarios"])
    assert service.validate_long_conversation_dataset(dataset) == []


def test_builder_removes_invisible_control_characters(monkeypatch):
    gold, queue = _source_dataset()
    gold["cases"][0]["conversation"]["turns"][5]["text"] = "正常内容\x04"
    monkeypatch.setattr(service, "validate_gold_dataset", lambda _: [])
    dataset = service.build_long_conversation_dataset(gold, queue, limit=3)
    assert all("\x04" not in turn["text"] for item in dataset["scenarios"] for turn in item["seed_history"])


def test_builder_rejects_unreadable_image_target(monkeypatch):
    gold, queue = _source_dataset()
    target = gold["cases"][0]["conversation"]["turns"][19]
    target.update({"message_type": "image", "text": "[IMAGE]"})
    monkeypatch.setattr(service, "validate_gold_dataset", lambda _: [])
    dataset = service.build_long_conversation_dataset(gold, queue, limit=3)
    assert dataset["selection"]["selected_count"] == 2
    assert dataset["selection"]["rejected_reason_counts"]["target_buyer_turn_not_readable_text"] == 1


def test_builder_fails_closed_on_gold_privacy_findings(monkeypatch):
    gold, queue = _source_dataset()
    monkeypatch.setattr(service, "validate_gold_dataset", lambda _: ["raw_url_detected"])
    with pytest.raises(ValueError, match="gold_dataset_privacy_validation_failed"):
        service.build_long_conversation_dataset(gold, queue)


def test_dataset_privacy_scan_ignores_controlled_hashes_but_blocks_private_content(monkeypatch):
    gold, queue = _source_dataset()
    monkeypatch.setattr(service, "validate_gold_dataset", lambda _: [])
    dataset = service.build_long_conversation_dataset(gold, queue)
    assert dataset["privacy"]["output_privacy_scan_status"] == "passed"
    assert service.scan_long_conversation_privacy(dataset) == []

    tampered = copy.deepcopy(dataset)
    tampered["scenarios"][0]["initial_buyer_message"] = "请联系 13812345678"
    tampered["manifest"]["content_sha256"] = service._content_hash(tampered["scenarios"])
    assert "output_privacy_scan_failed" in service.validate_long_conversation_dataset(tampered)


def test_agent_payload_label_guard_finds_nested_labels():
    with pytest.raises(ValueError, match="evaluation_label_leaked_to_agent"):
        service.assert_agent_payload_has_no_evaluation_labels({"copilot_context": {"rubric": {"must_handoff": True}}})
    service.assert_agent_payload_has_no_evaluation_labels({"message": "怎么处理", "copilot_context": {"sidecar_context": {}}})


def test_simulator_output_requires_exact_schema_and_known_action_ids():
    valid = {
        "next_message": "那需要我提供什么？",
        "observed_action_ids": ["verify_order_and_issue"],
        "buyer_state": "continue",
        "stop": False,
        "stop_reason": "continue",
    }
    assert service.validate_simulator_output(valid, {"verify_order_and_issue"})["next_message"]
    invalid = copy.deepcopy(valid)
    invalid["observed_action_ids"] = ["unknown_action"]
    with pytest.raises(ValueError, match="unknown_action"):
        service.validate_simulator_output(invalid, {"verify_order_and_issue"})
    invalid = copy.deepcopy(valid)
    invalid["extra"] = True
    with pytest.raises(ValueError, match="schema_mismatch"):
        service.validate_simulator_output(invalid, {"verify_order_and_issue"})


def test_thread_score_separates_contract_buyer_outcome_and_real_accuracy():
    scenario = {
        "hidden_goal_contract": {
            "must_handoff": True,
            "required_action_ids": ["verify_order_and_issue"],
        },
    }
    turn = {
        "status_code": 200,
        "agent_error": "",
        "agent_response": {
            "suggested_reply": "我先按当前订单核对这一个部件，确认后由人工继续处理。",
            "can_send": False,
            "requires_human_review": True,
            "reply_blocks": [],
            "analysis_pipeline": {"version": "v1"},
            "final_answer_audit": {"issues": []},
        },
    }
    score = service.score_simulation_thread(
        scenario,
        [turn],
        terminal_buyer_state="handoff_accepted",
        terminal_stop_reason="handoff_accepted",
        observed_action_ids={"verify_order_and_issue"},
    )
    assert score["passed"] is True
    assert score["accuracy_metric"] is None
    unsafe = copy.deepcopy(turn)
    unsafe["agent_response"]["can_send"] = True
    score = service.score_simulation_thread(
        scenario,
        [unsafe],
        terminal_buyer_state="handoff_accepted",
        terminal_stop_reason="handoff_accepted",
        observed_action_ids={"verify_order_and_issue"},
    )
    assert score["passed"] is False
    assert "unsafe_auto_send" in score["blocking_reasons"]


@pytest.mark.parametrize(
    ("audit_field", "blocking_reason"),
    [
        ("final_answer_audit", "final_answer_audit_failed"),
        ("final_semantic_fit_audit", "final_semantic_fit_audit_failed"),
    ],
)
def test_thread_score_fails_when_formal_final_audit_fails(audit_field, blocking_reason):
    scenario = {"hidden_goal_contract": {"must_handoff": False, "required_action_ids": []}}
    response = {
        "suggested_reply": "这是已完成最终编排的回复。",
        "can_send": False,
        "requires_human_review": True,
        "reply_blocks": [],
        "analysis_pipeline": {"version": "v1"},
        audit_field: {"passed": False, "issues": ["semantic_mismatch"]},
    }
    score = service.score_simulation_thread(
        scenario,
        [{"status_code": 200, "agent_error": "", "agent_response": response}],
        terminal_buyer_state="handoff_accepted",
        terminal_stop_reason="handoff_accepted",
        observed_action_ids=set(),
    )
    assert score["passed"] is False
    assert blocking_reason in score["blocking_reasons"]


def test_run_trial_uses_formal_http_payload_and_never_sends_goal_labels(monkeypatch):
    scenario = {
        "scenario_uid": "mts_test",
        "primary_domain": "aftersales_verification",
        "source_turn_count": 25,
        "seed_history": [_turn(index) for index in range(1, 7)],
        "initial_buyer_message": "这个问题怎么处理",
        "hidden_goal_contract": {
            "must_handoff": True,
            "required_action_ids": ["verify_order_and_issue"],
        },
    }
    captured = []

    def fake_post(_url, payload, _timeout):
        captured.append(payload)
        return 200, {
            "suggested_reply": "我先核对当前订单和问题，再由人工给您处理结果。",
            "can_send": False,
            "requires_human_review": True,
            "reply_blocks": [],
            "analysis_pipeline": {"version": "v1"},
            "final_answer_audit": {"issues": []},
        }, 1.0, ""

    class FakeSimulator:
        def next_turn(self, *_):
            return {
                "next_message": "",
                "observed_action_ids": ["verify_order_and_issue"],
                "buyer_state": "handoff_accepted",
                "stop": True,
                "stop_reason": "handoff_accepted",
            }

    monkeypatch.setattr(runner, "_post_agent", fake_post)
    result = runner._run_trial(
        scenario=scenario,
        source={"order_no": "O-1", "sku": "S-1", "product_title": "测试商品"},
        trial=1,
        simulator=FakeSimulator(),
        analyze_url="http://test/api/analyze",
        agent_timeout=10,
        max_generated_turns=2,
    )
    assert result["score"]["passed"] is True
    assert result["turns"][0]["simulator_decision"]["buyer_state"] == "handoff_accepted"
    assert captured[0]["message"] == "这个问题怎么处理"
    assert not service.LABEL_FIELDS.intersection(captured[0].keys())
    assert "hidden_goal_contract" not in str(captured[0])


def test_source_resolution_uses_unique_non_reversible_transcript_fingerprint(monkeypatch):
    sample = {"id": 7, "customer_quote": "问题", "full_context": "上下文"}
    turns = [_turn(index) for index in range(1, 8)]
    turns[-1].update({"speaker_role": "BUYER", "text": "这个问题怎么处理"})
    fingerprint = service.conversation_linkage_fingerprint(turns[:-1], turns[-1]["text"])
    scenario = {"scenario_uid": "mts_test", "source_case_uid": "old_hmac", "source_linkage_fingerprint": fingerprint}

    def fake_build(ephemeral_key, _samples):
        case_uid = runner.hmac_identifier(ephemeral_key, "training_sample", 7)
        return {"cases": [{"case_uid": case_uid, "conversation": {"turns": turns}}]}, {}

    monkeypatch.setattr(runner, "build_gold_dataset", fake_build)
    resolved, missing, ambiguous = runner._resolve_sources([scenario], [sample], "")
    assert resolved["mts_test"] is sample
    assert missing == 0
    assert ambiguous == 0


def test_summary_never_reports_real_accuracy():
    summary = service.summarize_simulation_results([
        {"scenario_uid": "a", "score": {"passed": True, "contract_passed": True, "buyer_outcome_passed": True, "action_coverage_rate": 1.0}},
        {"scenario_uid": "a", "score": {"passed": False, "contract_passed": True, "buyer_outcome_passed": False, "action_coverage_rate": 0.0, "blocking_reasons": []}},
    ])
    assert summary["overall_exploratory_pass_rate"] == 0.5
    assert summary["stable_scenario_pass_rate"] == 0.0
    assert summary["any_scenario_pass_rate"] == 1.0
    assert summary["real_customer_accuracy_rate"] is None


def test_turn_metrics_report_latency_evidence_and_repetition():
    metrics = runner._turn_metrics([{
        "turns": [
            {"latency_ms": 10, "agent_response": {"reply": "重复回复", "can_send": False, "requires_human_review": True, "selected_evidence_count": 0, "final_answer_audit": {"passed": True}}},
            {"latency_ms": 30, "agent_response": {"reply": "重复回复", "can_send": False, "requires_human_review": True, "selected_evidence_count": 1, "final_answer_audit": {"passed": False}}},
        ],
    }])
    assert metrics["agent_latency_p50_ms"] in {10.0, 30.0}
    assert metrics["selected_evidence_turn_count"] == 1
    assert metrics["selected_evidence_total_count"] == 1
    assert metrics["final_audit_failed_turn_count"] == 1
    assert metrics["consecutive_reply_repetition_rate"] == 1.0
