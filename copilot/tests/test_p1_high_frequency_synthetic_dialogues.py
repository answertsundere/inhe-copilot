from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.canonical_conversation_turn_service import normalize_conversation_turns
from scripts.build_p1_high_frequency_synthetic_dialogue_set import build_dataset
import scripts.run_p1_high_frequency_synthetic_preview as runner
from scripts.run_p1_high_frequency_synthetic_preview import (
    SyntheticDialogueError,
    _build_formal_observation,
    build_formal_report,
    build_report,
    main,
    validate_dataset,
)


def _stable_formal_response(item=None, **updates):
    history = (
        [
            {
                "role": "customer" if turn["speaker"] == "buyer" else "agent",
                "content": turn["text"],
            }
            for turn in item["conversation_turns"][:-1]
        ]
        if item
        else [
            {"role": "customer", "content": "第一轮"},
            {"role": "agent", "content": "第二轮"},
            {"role": "customer", "content": "第三轮"},
            {"role": "agent", "content": "第四轮"},
        ]
    )
    response = {
        "suggested_reply": "合成草稿",
        "requires_human_review": True,
        "can_send": False,
        "reply_status": "needs_human_review",
        "minimal_decision_context": {
            "recent_conversation_turns": history,
            "requested_claims": [{"goal_kind": "customer_goal"}],
            "claim_resolutions": [{"status": "unresolved"}],
            "admitted_evidence": [],
        },
        "model_first_answer_composer": {
            "status": "accepted",
            "rejection_reason": "",
            "composition_applicable": True,
            "used_for_final_reply": True,
            "clauses": [{"status": "unresolved"}],
        },
        "analysis_pipeline": {
            "stages": [
                {"stage": "model_first_answer_composer", "status": "completed"},
                {"stage": "final_response_orchestration", "status": "completed"},
            ],
        },
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"status": "passed", "passed": True},
    }
    response.update(updates)
    return response


def _stable_response_for_request(request, **updates):
    request_payload = json.loads(request.data.decode("utf-8"))
    response = _stable_formal_response(**updates)
    response["minimal_decision_context"]["recent_conversation_turns"] = [
        {
            "role": "customer" if turn["role"] == "user" else "agent",
            "content": turn["content"],
        }
        for turn in request_payload["conversation_history"]
    ]
    return response


def test_dataset_has_forty_multi_turn_synthetic_scenarios():
    payload = build_dataset()
    validation = validate_dataset(payload)

    assert validation["scenario_count"] == 40
    assert validation["privacy_scan"]["passed"] is True
    assert validation["topic_counts"]["installation_video"] == 3
    assert validation["topic_counts"]["dimensions_space_fit"] == 3
    assert validation["topic_counts"]["delivery_schedule_change"] == 2
    assert all(len(item["conversation_turns"]) == 5 for item in payload["scenarios"])
    assert all(item["source_class"] == "synthetic_anonymous" for item in payload["scenarios"])


def test_dataset_rejects_non_synthetic_identity_or_context_mismatch():
    payload = build_dataset()
    payload["scenarios"][0]["raw_context"]["product_identity"]["sku_code"] = "LIVE-SKU"
    with pytest.raises(SyntheticDialogueError, match="synthetic_identity"):
        validate_dataset(payload)

    payload = build_dataset()
    payload["scenarios"][0]["raw_context"]["customer_message"] = "不一致"
    with pytest.raises(SyntheticDialogueError, match="final_turn_and_context"):
        validate_dataset(payload)


def test_preview_report_remains_review_only_and_writes_outputs(tmp_path):
    payload = build_dataset()
    report = build_report(payload)

    assert report["summary"]["scenario_count"] == 40
    assert report["summary"]["requires_human_review_count"] == 40
    assert report["summary"]["can_send_true_count"] == 0
    assert report["summary"]["formal_reply_use_count"] == 0
    assert report["agent_call_is_formal_runtime_call"] is False

    input_path = tmp_path / "synthetic.json"
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert main(["--input", str(input_path), "--json-output", str(json_path), "--markdown-output", str(markdown_path)]) == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["can_send_true_count"] == 0
    assert "P1 高频问题合成对话预览" in markdown_path.read_text(encoding="utf-8")


def test_preview_cli_runs_from_project_root(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    input_path = tmp_path / "synthetic.json"
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    input_path.write_text(json.dumps(build_dataset(), ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_p1_high_frequency_synthetic_preview.py",
            "--input", str(input_path),
            "--json-output", str(json_path),
            "--markdown-output", str(markdown_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["scenario_count"] == 40


def test_formal_report_accepts_only_loopback_preserves_review_contract_and_resumes(monkeypatch, tmp_path):
    class _Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                self.body,
                ensure_ascii=False,
            ).encode("utf-8")

    calls = []
    monkeypatch.setattr(
        runner,
        "urlopen",
        lambda request, timeout: calls.append((request, timeout))
        or _Response(_stable_response_for_request(request)),
    )
    payload = build_dataset()
    checkpoint = tmp_path / "formal-checkpoint.json"
    report = build_formal_report(
        payload,
        analyze_url="http://127.0.0.1:5018/api/analyze",
        request_timeout=7,
        checkpoint_path=checkpoint,
    )

    assert len(calls) == 40
    assert report["agent_call_is_formal_runtime_call"] is True
    assert report["summary"]["response_count"] == 40
    assert report["summary"]["completed_count"] == 40
    assert report["summary"]["can_send_true_count"] == 0
    monkeypatch.setattr(runner, "urlopen", lambda *_args, **_kwargs: pytest.fail("completed row retried"))
    resumed = build_formal_report(
        payload,
        analyze_url="http://127.0.0.1:5018/api/analyze",
        checkpoint_path=checkpoint,
        resume=True,
    )
    assert resumed["summary"]["completed_count"] == 40
    with pytest.raises(SyntheticDialogueError, match="loopback"):
        build_formal_report(payload, analyze_url="https://example.com/api/analyze")


def test_formal_report_honors_batch_limit(monkeypatch, tmp_path):
    class _Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                self.body,
                ensure_ascii=False,
            ).encode("utf-8")

    calls = []
    monkeypatch.setattr(
        runner,
        "urlopen",
        lambda request, timeout: calls.append((request, timeout))
        or _Response(_stable_response_for_request(request)),
    )
    report = build_formal_report(
        build_dataset(),
        analyze_url="http://127.0.0.1:5018/api/analyze",
        checkpoint_path=tmp_path / "batch-checkpoint.json",
        max_new_cases=3,
    )

    assert len(calls) == 3
    assert report["summary"]["scenario_count"] == 40
    assert report["summary"]["completed_count"] == 3


def test_formal_report_rejects_pre_stability_checkpoint(monkeypatch, tmp_path):
    payload = build_dataset()
    checkpoint = tmp_path / "legacy-checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "report_schema_version": (
                    "p1-high-frequency-synthetic-formal-pipeline-report/v1"
                ),
                "dataset_id": payload["dataset_id"],
                "dataset_version": payload["dataset_version"],
                "dataset_sha256": runner._canonical_sha256(payload),
                "generation_path": "formal_analysis_pipeline",
                "rows": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("legacy checkpoint must fail first"),
    )

    with pytest.raises(
        SyntheticDialogueError,
        match="formal_checkpoint_schema_mismatch",
    ):
        build_formal_report(
            payload,
            analyze_url="http://127.0.0.1:5018/api/analyze",
            checkpoint_path=checkpoint,
            resume=True,
        )


def test_formal_report_stops_after_first_transport_failure(monkeypatch, tmp_path):
    calls = []

    def timeout_once(request, timeout):
        calls.append((request, timeout))
        raise TimeoutError("loopback model unavailable")

    monkeypatch.setattr(runner, "urlopen", timeout_once)
    report = build_formal_report(
        build_dataset(),
        analyze_url="http://127.0.0.1:5018/api/analyze",
        checkpoint_path=tmp_path / "formal-checkpoint.json",
    )

    assert len(calls) == 1
    assert report["summary"]["completed_count"] == 1
    assert report["summary"]["response_count"] == 0
    assert report["summary"]["error_count"] == 1


def test_formal_payload_supplies_canonical_history_roles_and_order():
    item = build_dataset()["scenarios"][0]

    payload = runner._formal_payload(item)

    turns, diagnostics = normalize_conversation_turns(
        payload["conversation_history"],
        strict=True,
    )

    assert [turn["role"] for turn in turns] == [
        "customer", "agent", "customer", "agent",
    ]
    assert [turn["turn_index"] for turn in turns] == [0, 1, 2, 3]
    assert diagnostics["status"] == "valid"
    assert payload["product_title"] == "合成评测商品"
    assert payload["sku_code"] == "SYN-SKU-001"
    assert payload["i_id"] == "SYN-IID-001"
    assert payload["order_id"] == "SYN-ORDER-001"
    assert "review_expectations" not in payload
    assert "requested_claims" not in payload


def test_formal_observation_qualifies_complete_history_and_composer_entry():
    item = build_dataset()["scenarios"][17]

    observation = _build_formal_observation(
        item,
        _stable_formal_response(item=item),
    )

    assert observation["expected_history_count"] == 4
    assert observation["projected_history_count"] == 4
    assert observation["history_projection_status"] == "complete"
    assert observation["turn_understanding_status"] == "authoritative"
    assert observation["composer_status"] == "accepted"
    assert observation["composer_used_for_final_reply"] is True
    assert observation["final_audit_passed"] is True
    assert observation["stability_status"] == "qualified"
    assert observation["stability_reason_code"] == ""


def test_formal_observation_keeps_contractual_composer_noop_scorable():
    item = build_dataset()["scenarios"][0]
    response = _stable_formal_response(item=item)
    response["minimal_decision_context"]["requested_claims"] = [{
        "goal_kind": "media_request",
    }]
    response["minimal_decision_context"]["claim_resolutions"] = [{
        "goal_kind": "media_request",
        "status": "unresolved",
    }]
    response["model_first_answer_composer"] = {
        "status": "accepted",
        "rejection_reason": "",
        "composition_applicable": False,
        "used_for_final_reply": False,
        "clauses": [],
    }

    observation = _build_formal_observation(item, response)

    assert observation["composer_contract_status"] == "not_applicable"
    assert observation["composer_composition_applicable"] is False
    assert observation["composer_used_for_final_reply"] is False
    assert observation["stability_status"] == "qualified"
    assert observation["stability_reason_code"] == ""


@pytest.mark.parametrize("composition_applicable", [True, None])
def test_formal_observation_rejects_unowned_or_undeclared_composer_path(
    composition_applicable,
):
    item = build_dataset()["scenarios"][0]
    response = _stable_formal_response(item=item)
    response["model_first_answer_composer"].update({
        "composition_applicable": composition_applicable,
        "used_for_final_reply": False,
        "clauses": [],
    })

    observation = _build_formal_observation(item, response)

    assert observation["composer_contract_status"] == "invalid"
    assert observation["stability_status"] == "not_qualified"
    assert observation["stability_reason_code"] == "composer_entry_blocked"


def test_formal_observation_rejects_same_length_history_with_wrong_order():
    item = build_dataset()["scenarios"][17]
    response = _stable_formal_response(item=item)
    response["minimal_decision_context"]["recent_conversation_turns"].reverse()

    observation = _build_formal_observation(item, response)

    assert observation["expected_history_count"] == 4
    assert observation["projected_history_count"] == 4
    assert observation["history_projection_status"] == "mismatch"
    assert observation["stability_reason_code"] == (
        "conversation_history_projection_mismatch"
    )


@pytest.mark.parametrize(
    ("response_updates", "expected_status", "expected_reason"),
    [
        (
            {
                "minimal_decision_context": {
                    "recent_conversation_turns": [],
                    "requested_claims": [],
                    "claim_resolutions": [],
                    "admitted_evidence": [],
                },
                "turn_understanding_boundary": {
                    "status": "degraded",
                    "earliest_reason_code": "llm_goal_understanding_unavailable",
                    "reason_codes": ["llm_goal_understanding_unavailable"],
                },
                "model_first_answer_composer": {
                    "status": "provider_blocked",
                    "rejection_reason": "turn_understanding_not_authoritative",
                    "used_for_final_reply": False,
                    "clauses": [],
                },
            },
            "not_qualified",
            "turn_understanding_not_authoritative",
        ),
        (
            {
                "minimal_decision_context": {
                    "recent_conversation_turns": [],
                    "requested_claims": [{"goal_kind": "customer_goal"}],
                    "claim_resolutions": [{"status": "unresolved"}],
                    "admitted_evidence": [],
                },
            },
            "not_qualified",
            "conversation_history_projection_mismatch",
        ),
        (
            {
                "model_first_answer_composer": {
                    "status": "provider_blocked",
                    "rejection_reason": "formal_llm_error:TimeoutError",
                    "used_for_final_reply": False,
                    "clauses": [],
                },
            },
            "not_qualified",
            "composer_entry_blocked",
        ),
        (
            {"final_answer_audit": {"passed": False, "issues": ["query_reply_mismatch"]}},
            "not_qualified",
            "final_audit_failed",
        ),
    ],
)
def test_formal_observation_classifies_the_earliest_stability_failure(
    response_updates,
    expected_status,
    expected_reason,
):
    item = build_dataset()["scenarios"][17]
    response = _stable_formal_response(item=item, **response_updates)

    observation = _build_formal_observation(item, response)

    assert observation["stability_status"] == expected_status
    assert observation["stability_reason_code"] == expected_reason


def test_formal_report_stops_after_first_composer_entry_failure(monkeypatch, tmp_path):
    class _Response:
        def __init__(self, request):
            self.request = request

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            body = _stable_response_for_request(
                self.request,
                model_first_answer_composer={
                    "status": "provider_blocked",
                    "rejection_reason": "formal_llm_error:TimeoutError",
                    "used_for_final_reply": False,
                    "clauses": [],
                },
            )
            return json.dumps(body, ensure_ascii=False).encode("utf-8")

    calls = []
    monkeypatch.setattr(
        runner,
        "urlopen",
        lambda request, timeout: calls.append((request, timeout))
        or _Response(request),
    )

    report = build_formal_report(
        build_dataset(),
        analyze_url="http://127.0.0.1:5018/api/analyze",
        checkpoint_path=tmp_path / "formal-checkpoint.json",
    )

    assert len(calls) == 1
    assert report["status"] == "stopped"
    assert report["stop_reason"] == "composer_entry_blocked"
    assert report["summary"]["stability_qualified_count"] == 0
    assert report["summary"]["stability_failure_counts"] == {
        "composer_entry_blocked": 1,
    }
