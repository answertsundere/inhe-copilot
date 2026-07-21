from __future__ import annotations

import copy
import json

import pytest

import app.services.long_conversation_simulation_service as service
import scripts.run_long_conversation_simulation as runner


class _QualifiedGrader:
    def __init__(self, completed_action_ids=()):
        self.completed_action_ids = set(completed_action_ids)

    def grade(self, required_action_ids, _turns):
        required = sorted(required_action_ids)
        covered = sorted(set(required).intersection(self.completed_action_ids))
        return {
            "status": "completed",
            "reason": "",
            "covered_action_ids": covered,
            "action_coverage_rate": len(covered) / len(required) if required else None,
        }


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


def test_agent_payload_uses_canonical_turns_and_marks_evaluation_context_strict():
    source, _ = _source_dataset()
    scenario = {"scenario_uid": "scenario_contract", "seed_history": source["cases"][0]["conversation"]["turns"][:12]}
    payload = runner._agent_payload(
        {"product_title": "测试商品"},
        scenario,
        1,
        "当前买家问题",
        scenario["seed_history"],
    )

    assert payload["copilot_context"]["evaluation_context_contract"] == "strict"
    assert isinstance(payload["conversation_history"], list)
    assert payload["conversation_history"]
    assert all({"role", "content", "turn_uid"}.issubset(turn) for turn in payload["conversation_history"])


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
    invalid = copy.deepcopy(valid)
    invalid["observed_action_ids"] = ["verify_order_and_issue", "verify_order_and_issue"]
    with pytest.raises(ValueError, match="duplicate_action"):
        service.validate_simulator_output(invalid, {"verify_order_and_issue"})


def test_customer_simulator_retries_one_local_semantic_validation_failure():
    invalid = {
        "next_message": "",
        "observed_action_ids": [],
        "buyer_state": "continue",
        "stop": False,
        "stop_reason": "continue",
    }
    valid = {
        "next_message": "请继续核对。",
        "observed_action_ids": [],
        "buyer_state": "continue",
        "stop": False,
        "stop_reason": "continue",
    }

    class _Provider:
        def __init__(self):
            self.responses = iter([invalid, valid])
            self.call_count = 0

        def request(self, **_kwargs):
            self.call_count += 1
            return next(self.responses)

        def metadata(self):
            return {}

        def ready_for_shadow(self):
            return True

    provider = _Provider()
    simulator = runner.CustomerSimulator(
        api_key="",
        api_base="",
        model="",
        timeout=10,
        provider=provider,
        allow_unqualified=True,
    )
    decision = simulator.next_turn({"hidden_goal_contract": {}}, [], set())

    assert provider.call_count == 2
    assert decision["next_message"] == "请继续核对。"
    assert decision["validation_retry_count"] == 1


def test_customer_simulator_stops_after_two_local_semantic_validation_failures():
    invalid = {
        "next_message": "",
        "observed_action_ids": [],
        "buyer_state": "continue",
        "stop": False,
        "stop_reason": "continue",
    }

    class _Provider:
        def __init__(self):
            self.call_count = 0

        def request(self, **_kwargs):
            self.call_count += 1
            return invalid

        def metadata(self):
            return {}

        def ready_for_shadow(self):
            return True

    provider = _Provider()
    simulator = runner.CustomerSimulator(
        api_key="",
        api_base="",
        model="",
        timeout=10,
        provider=provider,
        allow_unqualified=True,
    )

    with pytest.raises(ValueError, match="simulator_next_message_invalid"):
        simulator.next_turn({"hidden_goal_contract": {}}, [], set())
    assert provider.call_count == 2


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
        grader=_QualifiedGrader({"verify_order_and_issue"}),
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
        grader=_QualifiedGrader({"verify_order_and_issue"}),
    )
    assert score["passed"] is False
    assert "unsafe_auto_send" in score["blocking_reasons"]


def test_simulator_observation_cannot_credit_action_coverage_without_agent_reply():
    scenario = {
        "hidden_goal_contract": {
            "must_handoff": True,
            "required_action_ids": ["verify_order_and_issue"],
        },
    }
    score = service.score_simulation_thread(
        scenario,
        [{
            "status_code": 200,
            "agent_error": "",
            "agent_response": {
                "suggested_reply": "请您稍等。",
                "can_send": False,
                "requires_human_review": True,
                "reply_blocks": [],
                "analysis_pipeline": {"version": "v1"},
                "final_answer_audit": {"issues": []},
            },
        }],
        terminal_buyer_state="handoff_accepted",
        terminal_stop_reason="handoff_accepted",
        observed_action_ids={"verify_order_and_issue"},
        grader=_QualifiedGrader(),
    )

    assert score["passed"] is False
    assert score["action_coverage_rate"] == 0.0
    assert score["simulator_observed_action_ids"] == ["verify_order_and_issue"]
    assert score["transcript_action_grade"]["covered_action_ids"] == []


def test_runtime_metadata_preserves_version_when_readiness_returns_503(monkeypatch):
    def fake_get_json(url, _timeout):
        if url.endswith("/version"):
            return 200, {
                "runtime_commit": "abc",
                "formal_model": "model-x",
                "formal_provider_identity": _provider_identity("formal", "runtime"),
                "action_policy_provider_identity": _provider_identity("action", "runtime"),
                "feature_flags": {"x": False},
            }
        return 503, {"ready": False, "reasons": ["admin_auth_configuration_missing"]}

    monkeypatch.setattr(runner, "_get_json", fake_get_json)

    metadata = runner._runtime_metadata("http://127.0.0.1:5012/api/analyze", 2)

    assert metadata["status"] == "not_ready"
    assert metadata["runtime_commit"] == "abc"
    assert metadata["formal_provider_identity"] == _provider_identity("formal", "runtime")
    assert metadata["action_policy_provider_identity"] == _provider_identity("action", "runtime")
    assert "https://" not in str(metadata["formal_provider_identity"])
    assert metadata["version_http_status"] == 200
    assert metadata["readiness_http_status"] == 503
    assert metadata["readiness"]["reasons"] == ["admin_auth_configuration_missing"]


def test_tier_d_runner_rejects_dirty_runtime_without_matching_source_identity(monkeypatch, tmp_path):
    runtime = {
        "status": "available",
        "runtime_commit": "candidate-commit",
        "formal_model": "model-x",
        "worktree_dirty": True,
        "source_tree_sha256": "candidate-hash",
        "boot_source_tree_sha256": "candidate-hash",
        "source_tree_drift": False,
        "feature_flags": {"answer_memory_shadow": False},
    }
    monkeypatch.setattr(runner, "_runtime_metadata", lambda *_args: runtime)

    result = runner.main([
        "--dataset", str(tmp_path / "dataset.json"),
        "--source-db", str(tmp_path / "source.sqlite"),
        "--json-output", str(tmp_path / "report.json"),
    ])

    assert result == 2


def test_tier_d_runner_rejects_source_hash_model_and_feature_flag_mismatches(monkeypatch, tmp_path):
    runtime = {
        "status": "available",
        "runtime_commit": "candidate-commit",
        "formal_model": "model-x",
        "worktree_dirty": True,
        "source_tree_sha256": "candidate-hash",
        "boot_source_tree_sha256": "candidate-hash",
        "source_tree_drift": False,
        "feature_flags": {"answer_memory_shadow": False},
    }
    monkeypatch.setattr(runner, "_runtime_metadata", lambda *_args: runtime)
    common = [
        "--dataset", str(tmp_path / "dataset.json"),
        "--source-db", str(tmp_path / "source.sqlite"),
        "--json-output", str(tmp_path / "report.json"),
        "--expected-source-tree-sha256", "other-hash",
    ]

    assert runner.main(common) == 2
    assert runner.main([
        *common[:-2], "--expected-source-tree-sha256", "candidate-hash",
        "--expected-formal-model", "other-model",
    ]) == 2
    assert runner.main([
        *common[:-2], "--expected-source-tree-sha256", "candidate-hash",
        "--expected-feature-flags-json", '{"answer_memory_shadow": true}',
    ]) == 2


def test_tier_d_runner_rejects_source_tree_drift(monkeypatch, tmp_path):
    runtime = {
        "status": "available",
        "runtime_commit": "candidate-commit",
        "formal_model": "model-x",
        "worktree_dirty": False,
        "source_tree_sha256": "boot-hash",
        "boot_source_tree_sha256": "boot-hash",
        "current_source_tree_sha256": "changed-hash",
        "source_tree_drift": True,
        "feature_flags": {},
    }
    monkeypatch.setattr(runner, "_runtime_metadata", lambda *_args: runtime)

    assert runner.main([
        "--dataset", str(tmp_path / "dataset.json"),
        "--source-db", str(tmp_path / "source.sqlite"),
        "--json-output", str(tmp_path / "report.json"),
    ]) == 2


def _provider_identity(name: str, suffix: str) -> dict:
    return {
        "provider_name": name,
        "host_fingerprint": f"host-{suffix}",
        "model_name": f"model-{suffix}",
        "configured": True,
        "identity": f"host-{suffix}:model-{suffix}",
    }


@pytest.mark.parametrize(
    ("identities", "passed", "conflict_count"),
    [
        ({"formal_agent": _provider_identity("formal", "a"), "customer_simulator": _provider_identity("simulator", "a"), "transcript_grader": _provider_identity("grader", "b")}, False, 1),
        ({"formal_agent": _provider_identity("formal", "a"), "customer_simulator": _provider_identity("simulator", "b"), "transcript_grader": _provider_identity("grader", "a")}, False, 1),
        ({"formal_agent": _provider_identity("formal", "a"), "customer_simulator": _provider_identity("simulator", "b"), "transcript_grader": _provider_identity("grader", "b")}, False, 1),
        ({"formal_agent": _provider_identity("formal", "a"), "customer_simulator": _provider_identity("simulator", "a"), "transcript_grader": _provider_identity("grader", "a")}, False, 3),
        ({"formal_agent": _provider_identity("formal", "a"), "customer_simulator": _provider_identity("simulator", "b"), "transcript_grader": _provider_identity("grader", "c")}, True, 0),
    ],
)
def test_provider_independence_rejects_shared_identities_before_trials(identities, passed, conflict_count):
    result = runner._provider_independence(identities)

    assert result["passed"] is passed
    assert len(result["conflicts"]) == conflict_count
    assert "https://" not in str(result)


def test_provider_independence_rejects_unknown_identity_and_records_same_model_different_host_risk():
    identities = {
        "formal_agent": {"provider_name": "formal", "host_fingerprint": "", "model_name": "model-a", "configured": False, "identity": ""},
        "customer_simulator": {"provider_name": "simulator", "host_fingerprint": "host-b", "model_name": "model-a", "configured": True, "identity": "host-b:model-a"},
        "transcript_grader": {"provider_name": "grader", "host_fingerprint": "host-c", "model_name": "model-a", "configured": True, "identity": "host-c:model-a"},
    }
    result = runner._provider_independence(identities)

    assert result["passed"] is False
    assert result["unknown_roles"] == ["formal_agent"]

    independent = {
        "formal_agent": _provider_identity("formal", "a"),
        "customer_simulator": {**_provider_identity("simulator", "b"), "model_name": "shared-model", "identity": "host-b:shared-model"},
        "transcript_grader": {**_provider_identity("grader", "c"), "model_name": "shared-model", "identity": "host-c:shared-model"},
    }
    independent_result = runner._provider_independence(independent)
    assert independent_result["passed"] is True
    assert independent_result["same_model_different_host_risks"] == [{
        "roles": ["customer_simulator", "transcript_grader"],
        "model_name": "shared-model",
    }]


def test_tier_d_runner_fails_before_dataset_read_when_provider_identities_conflict(monkeypatch, tmp_path, capsys):
    formal_identity = runner.safe_provider_identity(
        provider_name="formal",
        api_base="https://formal.example.invalid/v1",
        model="model-a",
    )
    runtime = {
        "status": "available",
        "runtime_commit": "candidate-commit",
        "formal_model": "model-a",
        "formal_provider_identity": formal_identity,
        "worktree_dirty": False,
        "source_tree_drift": False,
        "feature_flags": {},
    }

    class _ReadyGrader:
        def ready(self):
            return True

        def metadata(self):
            return {
                **_provider_identity("grader", "b"),
                "capability": "strict_json_schema",
                "qualified": True,
            }

    monkeypatch.setattr(runner, "_runtime_metadata", lambda *_args: runtime)
    monkeypatch.setattr(runner, "_git_text", lambda *_args: "")
    monkeypatch.setattr(runner, "TierDTranscriptGrader", _ReadyGrader)
    monkeypatch.setenv("COPILOT_CUSTOMER_SIMULATOR_API_KEY", "test-key")
    monkeypatch.setenv("COPILOT_CUSTOMER_SIMULATOR_API_BASE", "https://formal.example.invalid/openai/v1?ignored=true")
    monkeypatch.setenv("COPILOT_CUSTOMER_SIMULATOR_MODEL", "model-a")
    monkeypatch.setenv("COPILOT_CUSTOMER_SIMULATOR_CAPABILITY", "strict_json_schema")
    monkeypatch.setenv("COPILOT_CUSTOMER_SIMULATOR_QUALIFIED", "true")

    result = runner.main([
        "--dataset", str(tmp_path / "missing.json"),
        "--source-db", str(tmp_path / "missing.sqlite"),
        "--json-output", str(tmp_path / "report.json"),
    ])

    assert result == 2
    emitted = capsys.readouterr().out
    assert "provider_independence_failed" in emitted
    assert "formal.example.invalid" not in emitted


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
    assert score["passed"] is None
    assert score["semantic_pass"] is None
    assert score["overall_pass"] is None
    assert score["evaluation_status"] == "semantic_grader_unavailable"
    assert score["contract_passed"] is False
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

    grader = _QualifiedGrader({"verify_order_and_issue"})

    monkeypatch.setattr(runner, "_post_agent", fake_post)
    result = runner._run_trial(
        scenario=scenario,
        source={"order_no": "O-1", "sku": "S-1", "product_title": "测试商品"},
        trial=1,
        simulator=FakeSimulator(),
        analyze_url="http://test/api/analyze",
        agent_timeout=10,
        max_generated_turns=2,
        grader=grader,
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


def test_source_resolution_uses_conversation_digest_to_disambiguate_shared_tail(monkeypatch):
    first_sample = {"id": 7, "customer_quote": "同一个问题", "full_context": "第一段上下文"}
    second_sample = {"id": 8, "customer_quote": "同一个问题", "full_context": "第二段上下文"}
    shared_prefix = [_turn(index) for index in range(1, 6)]
    target = _turn(6, text="同一个问题")
    target.update({"speaker_role": "BUYER"})
    first_turns = [*shared_prefix, target, _turn(7, text="第一段后续")]
    second_turns = [*shared_prefix, target, _turn(7, text="第二段后续")]
    fingerprint = service.conversation_linkage_fingerprint(shared_prefix, target["text"])
    scenario = {
        "scenario_uid": "mts_digest",
        "source_case_uid": "old_hmac",
        "source_linkage_fingerprint": fingerprint,
        "source_conversation_digest": service.conversation_content_digest(second_turns),
    }

    def fake_build(ephemeral_key, _samples):
        return {
            "cases": [
                {
                    "case_uid": runner.hmac_identifier(ephemeral_key, "training_sample", 7),
                    "conversation": {"turns": first_turns},
                },
                {
                    "case_uid": runner.hmac_identifier(ephemeral_key, "training_sample", 8),
                    "conversation": {"turns": second_turns},
                },
            ],
        }, {}

    monkeypatch.setattr(runner, "build_gold_dataset", fake_build)
    resolved, missing, ambiguous = runner._resolve_sources(
        [scenario],
        [first_sample, second_sample],
        "",
    )

    assert resolved["mts_digest"] is second_sample
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
            {"latency_ms": 10, "observation": {"reply": "重复回复", "can_send": False, "requires_human_review": True, "selected_evidence_count": 0, "final_answer_audit": {"passed": True}}},
            {"latency_ms": 30, "observation": {"reply": "重复回复", "can_send": False, "requires_human_review": True, "selected_evidence_count": 1, "final_answer_audit": {"passed": False}}},
        ],
    }])
    assert metrics["agent_latency_p50_ms"] in {10.0, 30.0}
    assert metrics["selected_evidence_turn_count"] == 1
    assert metrics["selected_evidence_total_count"] == 1
    assert metrics["final_audit_failed_turn_count"] == 1
    assert metrics["consecutive_reply_repetition_rate"] == 1.0


def test_turn_observation_drives_scoring_and_report_recomputation_for_media_promise():
    observation = service.build_tier_d_turn_observation({
        "suggested_reply": "我现在给您发安装视频。",
        "can_send": False,
        "requires_human_review": True,
        "reply_status": "needs_human_review",
        "reply_blocks": [{"type": "text", "text": "我现在给您发安装视频。"}],
        "selected_evidence": [],
        "analysis_pipeline": {"version": "v1"},
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"passed": True, "issues": []},
    })
    result = {
        "scenario_uid": "mts_media",
        "trial": 1,
        "evaluation_contract": {"must_handoff": False, "required_action_ids": []},
        "turns": [{"status_code": 200, "agent_error": "", "observation": observation}],
        "score": {
            "blocking_reasons": ["unsupported_media_promise"],
            "contract_passed": False,
            "buyer_outcome_passed": True,
            "passed": False,
            "terminal_buyer_state": "handoff_accepted",
            "terminal_stop_reason": "handoff_accepted",
            "transcript_action_grade": {
                "status": "completed",
                "reason": "",
                "covered_action_ids": [],
                "action_coverage_rate": None,
            },
        },
    }

    assert observation["attached_media_block_count"] == 0
    assert runner._score_consistency_findings({"results": [result]}) == []
    result["score"]["blocking_reasons"] = []
    assert runner._score_consistency_findings({"results": [result]})[0]["fields"] == ["blocking_reasons"]


def test_conversation_content_digest_disambiguates_same_tail_with_different_history():
    shared_tail = [_turn(index) for index in range(10, 16)]
    first = [_turn(1, text="第一段上下文"), *shared_tail]
    second = [_turn(1, text="第二段上下文"), *shared_tail]

    assert service.conversation_content_digest(first) != service.conversation_content_digest(second)


def test_qualification_loaders_reject_tampered_qualified_status(tmp_path):
    identity = "host:model"
    perfect_rate = {"numerator": 1, "denominator": 1, "rate": 1.0}
    load_phase = {
        "status": "qualified",
        "timeout_attempt_count": 0,
        "truncated_attempt_count": 0,
        "schema_error_attempt_count": 0,
        "free_text_fallback_attempt_count": 0,
        "semantic_pass_rate": perfect_rate,
        "citation_valid_rate": perfect_rate,
        "repeat_stability_rate": perfect_rate,
        "latency_ms": {"p95": 10.0},
        "p95_limit_ms": 100.0,
    }
    grader_report = {
        "schema_version": "tier-d-transcript-grader-qualification/v4",
        "qualification_status": "qualified",
        "configured_candidate": True,
        "local_contract_checks": {"negative_semantics": True},
        "secret_exposure_count": 0,
        "provider": {"identity": identity},
        "timeout_attempt_count": 0,
        "truncated_attempt_count": 0,
        "schema_error_attempt_count": 0,
        "free_text_fallback_attempt_count": 0,
        "provider_schema_success_rate": perfect_rate,
        "positive_semantic_pass_rate": perfect_rate,
        "negative_semantic_block_rate": perfect_rate,
        "citation_valid_rate": perfect_rate,
        "repeat_stability_rate": perfect_rate,
        "counterfactual_qualification": {
            "status": "qualified",
            "timeout_attempt_count": 0,
            "truncated_attempt_count": 0,
            "schema_error_attempt_count": 0,
            "free_text_fallback_attempt_count": 0,
            "semantic_pass_rate": perfect_rate,
            "repeat_stability_rate": perfect_rate,
            "latency_ms": {"p95": 10.0},
            "p95_limit_ms": 100.0,
        },
        "long_load_qualification": {"serial": load_phase, "concurrent": load_phase},
    }
    grader_path = tmp_path / "grader.json"
    grader_path.write_text(json.dumps(grader_report), encoding="utf-8")
    loaded = runner._load_grader_qualification(
        grader_path,
        {"identity": identity},
        workers=1,
    )
    assert loaded["selected_execution_profile"] == "serial"

    grader_report["long_load_qualification"]["concurrent"] = {
        **load_phase,
        "schema_error_attempt_count": 1,
    }
    grader_path.write_text(json.dumps(grader_report), encoding="utf-8")
    # A concurrent failure does not invalidate a runner pinned to one worker.
    runner._load_grader_qualification(grader_path, {"identity": identity}, workers=1)
    with pytest.raises(ValueError, match="grader_long_load_concurrent_error_present"):
        runner._load_grader_qualification(grader_path, {"identity": identity}, workers=2)

    grader_report["local_contract_checks"]["negative_semantics"] = False
    grader_path.write_text(json.dumps(grader_report), encoding="utf-8")
    with pytest.raises(ValueError, match="grader_qualification_local_contract_failed"):
        runner._load_grader_qualification(grader_path, {"identity": identity}, workers=1)

    grader_report["local_contract_checks"]["negative_semantics"] = True
    grader_report["counterfactual_qualification"] = {"status": "paused_not_qualified"}
    grader_path.write_text(json.dumps(grader_report), encoding="utf-8")
    runner._load_grader_qualification(grader_path, {"identity": identity}, workers=1)

    simulator_phase = {
        "status": "qualified",
        "error_attempt_count": 0,
        "semantic_pass_rate": perfect_rate,
        "repeat_stability_rate": perfect_rate,
        "latency_ms": {"p95": 10.0},
        "p95_limit_ms": 100.0,
    }
    simulator_report = {
        "schema_version": "tier-d-customer-simulator-qualification/v1",
        "qualification_status": "qualified",
        "provider": {"identity": identity},
        "short": simulator_phase,
        "serial": simulator_phase,
        "concurrent": {**simulator_phase, "semantic_pass_rate": {**perfect_rate, "rate": 0.5}},
        "gold_label_leakage_count": 0,
    }
    simulator_path = tmp_path / "simulator.json"
    simulator_path.write_text(json.dumps(simulator_report), encoding="utf-8")
    with pytest.raises(ValueError, match="simulator_long_load_metric_incomplete"):
        runner._load_simulator_qualification(simulator_path, {"identity": identity})


def test_runner_identity_does_not_depend_on_paused_action_policy_report(tmp_path):
    grader = tmp_path / "grader.json"
    simulator = tmp_path / "simulator.json"
    grader.write_text("{}", encoding="utf-8")
    simulator.write_text("{}", encoding="utf-8")

    identity = runner._runner_identity(
        grader_qualification_report=grader,
        simulator_qualification_report=simulator,
        dataset_manifest={"content_sha256": "a" * 64},
    )

    assert "action_policy_qualification_report_sha256" not in identity


def test_customer_simulator_honors_bounded_long_run_timeout():
    simulator = runner.CustomerSimulator(
        api_key="local-test",
        api_base="http://127.0.0.1:11436/v1",
        model="simulator-test",
        timeout=300,
        allow_unqualified=True,
    )

    assert simulator.provider.config.timeout_seconds == 300

    bounded = runner.CustomerSimulator(
        api_key="local-test",
        api_base="http://127.0.0.1:11436/v1",
        model="simulator-test",
        timeout=900,
        allow_unqualified=True,
    )
    assert bounded.provider.config.timeout_seconds == 300


def test_trial_execution_failure_is_structured_and_fail_closed():
    scenario = {
        "scenario_uid": "scenario-safe-id",
        "hidden_goal_contract": {"required_action_ids": ["verify_live_state"]},
    }

    result = runner._trial_execution_failure(scenario, 2, RuntimeError("private detail"))

    assert result["trial_execution_error"] == "RuntimeError"
    assert result["score"]["blocking_reasons"] == ["trial_execution_error"]
    assert result["score"]["action_coverage_rate"] is None
    assert "private detail" not in json.dumps(result)


def test_resume_checkpoint_is_identity_bound_and_rejects_duplicate_results(tmp_path):
    identity = {"boot_source_tree_sha256": "a" * 64}
    result = {"scenario_uid": "scenario-safe-id", "trial": 1}
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(json.dumps({
        "schema_version": "tier-d-checkpoint-v2",
        "checkpoint_identity": identity,
        "completed_trial_count": 1,
        "results": [result],
    }), encoding="utf-8")

    assert runner._load_resume_results(
        checkpoint,
        checkpoint_identity=identity,
        allowed_keys={("scenario-safe-id", 1)},
    ) == [result]

    with pytest.raises(ValueError, match="checkpoint_identity_mismatch"):
        runner._load_resume_results(
            checkpoint,
            checkpoint_identity={"boot_source_tree_sha256": "b" * 64},
            allowed_keys={("scenario-safe-id", 1)},
        )

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["results"].append(result)
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint_results_invalid"):
        runner._load_resume_results(
            checkpoint,
            checkpoint_identity=identity,
            allowed_keys={("scenario-safe-id", 1)},
        )


def test_formal_provider_probe_is_identity_bound_and_fail_closed(monkeypatch):
    identity = runner.safe_provider_identity(
        provider_name="formal_agent",
        api_base="https://formal.example.invalid/v1",
        model="formal-model",
    )
    monkeypatch.setenv("COPILOT_LLM_API_BASE", "https://formal.example.invalid/openai/v1")
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COPILOT_LLM_MODEL", "formal-model")

    class _Completion:
        choices = [type("Choice", (), {
            "message": type("Message", (), {"content": "TIER_D_PROVIDER_READY"})(),
            "finish_reason": "stop",
        })()]

    class _Client:
        def __init__(self, **_kwargs):
            self.chat = type("Chat", (), {})()
            self.chat.completions = type("Completions", (), {
                "create": staticmethod(lambda **_kwargs: _Completion()),
            })()

    monkeypatch.setattr(runner, "OpenAI", _Client)
    result = runner._formal_provider_probe({"formal_provider_identity": identity}, 10)

    assert result["status"] == "available"
    assert result["provider_identity"]["identity"] == identity["identity"]
    assert "formal.example.invalid" not in str(result)
    assert "test-key" not in str(result)

    class _QuotaError(Exception):
        status_code = 402

    class _QuotaClient(_Client):
        def __init__(self, **_kwargs):
            self.chat = type("Chat", (), {})()
            self.chat.completions = type("Completions", (), {
                "create": staticmethod(lambda **_kwargs: (_ for _ in ()).throw(_QuotaError())),
            })()

    monkeypatch.setattr(runner, "OpenAI", _QuotaClient)
    blocked = runner._formal_provider_probe({"formal_provider_identity": identity}, 10)
    assert blocked["status"] == "not_available"
    assert blocked["error_category"] == "formal_provider_quota_unavailable"


def test_formal_provider_probe_reuses_minimax_formal_transport(monkeypatch):
    identity = runner.safe_provider_identity(
        provider_name="formal_agent",
        api_base="https://api.minimaxi.com/v1",
        model="MiniMax-M3",
    )
    monkeypatch.setenv("COPILOT_LLM_API_BASE", "https://api.minimaxi.com/v1")
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("COPILOT_LLM_MODEL", "MiniMax-M3")
    calls = []

    class _Completion:
        choices = [type("Choice", (), {
            "message": type("Message", (), {"content": "TIER_D_PROVIDER_READY"})(),
            "finish_reason": "stop",
        })()]

    class _Client:
        def __init__(self, **_kwargs):
            self.chat = type("Chat", (), {})()
            self.chat.completions = type("Completions", (), {
                "create": staticmethod(lambda **kwargs: calls.append(kwargs) or _Completion()),
            })()

    monkeypatch.setattr(runner, "OpenAI", _Client)
    result = runner._formal_provider_probe({"formal_provider_identity": identity}, 10)

    assert result["status"] == "available"
    assert calls[0]["max_tokens"] == 800
    assert calls[0]["extra_body"] == {
        "reasoning_split": True,
        "thinking": {"type": "disabled"},
    }


def test_atomic_json_write_never_leaves_a_partial_target(tmp_path):
    target = tmp_path / "checkpoint.json"
    runner._write_json_atomic(target, {"completed_trial_count": 1, "label": "中文"})
    raw = target.read_text(encoding="utf-8")
    assert json.loads(raw) == {"completed_trial_count": 1, "label": "中文"}
    assert "\\u4e2d\\u6587" in raw
    assert not (tmp_path / ".checkpoint.json.tmp").exists()


def test_report_runtime_preserves_only_typed_sha256_fields():
    digest = "a" * 64
    runtime = {
        "status": "available",
        "source_tree_sha256": digest,
        "boot_source_tree_sha256": digest,
        "current_source_tree_sha256": digest,
        "readiness": {"ready": True, "status": "ready", "reasons": []},
    }
    projected = runner._report_runtime(runtime)
    assert projected["source_tree_sha256"] == digest
    assert projected["boot_source_tree_sha256"] == digest
    assert projected["current_source_tree_sha256"] == digest

    with pytest.raises(ValueError, match="runtime_source_tree_sha256_invalid"):
        runner._report_runtime({**runtime, "source_tree_sha256": "12345678901234567890"})


def test_failure_classification_uses_observation_and_grader_contracts():
    result = {
        "scenario_uid": "mts_failure",
        "trial": 1,
        "simulator_error": "",
        "turns": [
            {
                "observation": {
                    "reply": "同一条回复",
                    "can_send": True,
                    "selected_evidence_summary": [{"evidence_uid": "evidence_a", "is_placeholder": True}],
                    "final_answer_audit": {"issues": []},
                    "final_semantic_fit_audit": {"passed": True, "issues": []},
                },
            },
            {
                "observation": {
                    "reply": "同一条回复",
                    "can_send": False,
                    "selected_evidence_summary": [],
                    "final_answer_audit": {"issues": ["unsupported_product_claim"]},
                    "final_semantic_fit_audit": {"passed": False, "issues": ["semantic_mismatch"]},
                },
            },
        ],
        "score": {
            "blocking_reasons": ["unsupported_media_promise", "required_handoff_missing"],
            "terminal_buyer_state": "blocked",
            "terminal_stop_reason": "cannot_continue",
            "transcript_action_grade": {"uncovered_action_ids": ["verify_order_and_issue"]},
        },
    }

    rows = runner._failure_classification(result)
    reasons = {row["reason"] for row in rows}

    assert reasons == {
        "action_not_completed",
        "context_followup_failure",
        "evidence_free_product_claim",
        "placeholder_fact_auto_send",
        "query_reply_mismatch",
        "repeated_generic_reply",
        "required_handoff_missing",
        "unsupported_media_promise",
    }
    summary = runner._failure_classification_summary([result])
    assert summary["counts"]["unsupported_media_promise"] == 1
    assert summary["representatives"]["placeholder_fact_auto_send"]["evidence_summary"][0]["evidence_uid"] == "evidence_a"
