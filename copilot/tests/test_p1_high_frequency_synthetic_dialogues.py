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
    build_formal_report,
    build_report,
    main,
    validate_dataset,
)


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
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"suggested_reply":"\xe5\x90\x88\xe6\x88\x90\xe8\x8d\x89\xe7\xa8\xbf","requires_human_review":true,"can_send":false,"reply_status":"needs_human_review"}'

    calls = []
    monkeypatch.setattr(runner, "urlopen", lambda request, timeout: calls.append((request, timeout)) or _Response())
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
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"suggested_reply":"draft","requires_human_review":true,"can_send":false}'

    calls = []
    monkeypatch.setattr(runner, "urlopen", lambda request, timeout: calls.append((request, timeout)) or _Response())
    report = build_formal_report(
        build_dataset(),
        analyze_url="http://127.0.0.1:5018/api/analyze",
        checkpoint_path=tmp_path / "batch-checkpoint.json",
        max_new_cases=3,
    )

    assert len(calls) == 3
    assert report["summary"]["scenario_count"] == 40
    assert report["summary"]["completed_count"] == 3


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

    turns, diagnostics = normalize_conversation_turns(
        runner._formal_payload(item)["conversation_history"],
        strict=True,
    )

    assert [turn["role"] for turn in turns] == [
        "customer", "agent", "customer", "agent",
    ]
    assert [turn["turn_index"] for turn in turns] == [0, 1, 2, 3]
    assert diagnostics["status"] == "valid"
