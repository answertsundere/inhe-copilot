import json
import os
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.agent_benchmark_fixture_service import (
    BenchmarkFixtureError,
    build_manifest,
    build_semantic_projection_fixture,
    fixture_database_metadata,
    fixture_session_factory,
    initialize_fixture_database,
    load_fixture,
    scan_sensitive_content,
    fixture_sha256,
    validate_fixture,
)
from app.services.agent_benchmark_runner_service import AgentBenchmarkRunnerService
from scripts.run_agent_benchmark import (
    _configure_fixture_database_from_argv,
    main as run_agent_benchmark_main,
    run_benchmark_report,
)


def _source_scenario(uid: str = "raw-scenario-1") -> dict:
    return {
        "scenario_uid": uid,
        "source_type": "real_conversation",
        "source_uid": "real-source-identifier",
        "status": "active",
        "title": "Raw customer transcript title",
        "scenario_type": "installation",
        "sidecar_context": {
            "product_title": "Customer item title",
            "sku_code": "LIVE-SKU-9",
            "i_id": "LIVE-IID-9",
            "order_id": "LIVE-ORDER-9",
        },
        "conversation_turns": [
            {"turn_uid": "raw-turn-1", "speaker": "buyer", "text": "Raw customer question"},
        ],
        "expected_reply": {
            "expected_reply": "Please verify the installation guide before sending it.",
            "key_points": ["installation guide", "human review"],
            "forbidden_claims": ["send a video immediately"],
            "must_handoff": True,
            "auto_send_allowed": False,
        },
        "rubric": {"fact_correctness": True},
        "metadata": {"query_fact_type": "installation", "source_turn_uid": "raw-turn-1"},
    }


def _write_fixture(tmp_path: Path, scenarios: list[dict] | None = None) -> tuple[Path, Path, dict]:
    payload = build_semantic_projection_fixture(
        scenarios or [_source_scenario()],
        dataset_id="fixture-test-v1",
        dataset_version="1.0.0",
        reviewed_at="2026-07-15",
    )
    fixture_path = tmp_path / "active.json"
    manifest_path = tmp_path / "active.manifest.json"
    fixture_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(build_manifest(payload), ensure_ascii=False), encoding="utf-8")
    return fixture_path, manifest_path, payload


def test_semantic_projection_removes_raw_conversation_and_identity(tmp_path):
    fixture_path, manifest_path, payload = _write_fixture(tmp_path)

    scenario = payload["scenarios"][0]
    serialized = fixture_path.read_text(encoding="utf-8")
    assert payload["source"]["raw_transcript_included"] is False
    assert scenario["source_type"] == "benchmark_fixture"
    assert scenario["sidecar_context"]["sku_code"].startswith("FIXTURE-SKU-")
    assert scenario["conversation_turns"][0]["text"] != "Raw customer question"
    assert "Raw customer question" not in serialized
    assert "LIVE-SKU-9" not in serialized
    assert "LIVE-ORDER-9" not in serialized
    assert load_fixture(fixture_path, manifest_path)[1]["scenario_count"] == 1


def test_fixture_validation_rejects_empty_duplicate_invalid_and_sensitive_payloads(tmp_path):
    _, _, payload = _write_fixture(tmp_path)

    empty = deepcopy(payload)
    empty["scenarios"] = []
    with pytest.raises(BenchmarkFixtureError, match="missing scenarios"):
        validate_fixture(empty)

    duplicate = deepcopy(payload)
    duplicate["scenarios"].append(deepcopy(duplicate["scenarios"][0]))
    with pytest.raises(BenchmarkFixtureError, match="duplicate"):
        validate_fixture(duplicate)

    invalid_status = deepcopy(payload)
    invalid_status["scenarios"][0]["status"] = "candidate"
    with pytest.raises(BenchmarkFixtureError, match="unsupported scenario status"):
        validate_fixture(invalid_status)

    no_rubric = deepcopy(payload)
    no_rubric["scenarios"][0]["rubric"] = None
    with pytest.raises(BenchmarkFixtureError, match="missing rubric"):
        validate_fixture(no_rubric)

    unsupported_schema = deepcopy(payload)
    unsupported_schema["schema_version"] = "agent-benchmark-fixture/v0"
    with pytest.raises(BenchmarkFixtureError, match="schema version"):
        validate_fixture(unsupported_schema)

    sensitive = {"phone": "13812345678", "address": "北京市海淀区中关村路10号", "token": "sk-test"}
    scan = scan_sensitive_content(sensitive)
    assert scan["passed"] is False
    assert {item["category"] for item in scan["findings"]} >= {"phone", "address", "credential"}


def test_fixture_projection_is_order_independent_and_hash_stable():
    scenarios = [_source_scenario("raw-b"), _source_scenario("raw-a")]
    first = build_semantic_projection_fixture(
        scenarios,
        dataset_id="fixture-test-v1",
        dataset_version="1.0.0",
        reviewed_at="2026-07-15",
    )
    second = build_semantic_projection_fixture(
        list(reversed(scenarios)),
        dataset_id="fixture-test-v1",
        dataset_version="1.0.0",
        reviewed_at="2026-07-15",
    )

    assert first == second
    assert fixture_sha256(first) == fixture_sha256(second)


def test_fixture_manifest_mismatch_is_rejected(tmp_path):
    fixture_path, manifest_path, _payload = _write_fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixture_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BenchmarkFixtureError, match="manifest mismatch"):
        load_fixture(fixture_path, manifest_path)


def test_fixture_initialization_is_repeatable_and_contains_only_benchmark_tables(tmp_path):
    fixture_path, manifest_path, payload = _write_fixture(tmp_path, [_source_scenario("raw-1"), _source_scenario("raw-2")])
    first = tmp_path / "first.sqlite"
    second = tmp_path / "second.sqlite"

    first_report = initialize_fixture_database(fixture_path, first, manifest_path=manifest_path)
    second_report = initialize_fixture_database(fixture_path, second, manifest_path=manifest_path)

    assert first_report["fixture_sha256"] == second_report["fixture_sha256"]
    assert fixture_database_metadata(first)["scenario_count"] == "2"
    with sqlite3.connect(first) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = connection.execute(
            "SELECT scenario_uid, source_type, status, sidecar_context_json, conversation_turns_json "
            "FROM agent_benchmark_scenarios ORDER BY scenario_uid"
        ).fetchall()
    with sqlite3.connect(second) as connection:
        second_rows = connection.execute(
            "SELECT scenario_uid, source_type, status, sidecar_context_json, conversation_turns_json "
            "FROM agent_benchmark_scenarios ORDER BY scenario_uid"
        ).fetchall()

    assert tables == {"agent_benchmark_scenarios", "benchmark_fixture_metadata"}
    assert rows == second_rows
    assert len(rows) == len(payload["scenarios"])


def test_fixture_database_refuses_existing_or_production_named_path(tmp_path):
    fixture_path, manifest_path, _payload = _write_fixture(tmp_path)
    existing = tmp_path / "exists.sqlite"
    existing.write_text("", encoding="utf-8")
    with pytest.raises(BenchmarkFixtureError, match="already exists"):
        initialize_fixture_database(fixture_path, existing, manifest_path=manifest_path)
    with pytest.raises(BenchmarkFixtureError, match="knowledge_base"):
        initialize_fixture_database(fixture_path, tmp_path / "knowledge_base.db", manifest_path=manifest_path)


def test_fixture_bootstrap_keeps_scenario_database_separate_from_knowledge_snapshot(
    monkeypatch,
    tmp_path,
):
    scenario_database = tmp_path / "benchmark_scenarios.sqlite"
    knowledge_snapshot = tmp_path / "knowledge_snapshot.sqlite"
    monkeypatch.delenv("COPILOT_BENCHMARK_FIXTURE_MODE", raising=False)
    monkeypatch.delenv("COPILOT_KNOWLEDGE_DB_PATH", raising=False)
    monkeypatch.delenv("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", raising=False)

    _configure_fixture_database_from_argv([
        "--fixture", "active.json",
        "--benchmark-db", str(scenario_database),
        "--knowledge-db", str(knowledge_snapshot),
    ])

    assert os.environ.get("COPILOT_BENCHMARK_FIXTURE_MODE") == "true"
    assert os.environ.get("COPILOT_KNOWLEDGE_DB_PATH") == str(knowledge_snapshot)
    assert os.environ.get("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY") == "true"
    os.environ.pop("COPILOT_BENCHMARK_FIXTURE_MODE", None)
    os.environ.pop("COPILOT_KNOWLEDGE_DB_PATH", None)
    os.environ.pop("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", None)


def test_fixture_bootstrap_does_not_use_scenario_database_as_knowledge_database(
    monkeypatch,
    tmp_path,
):
    scenario_database = tmp_path / "benchmark_scenarios.sqlite"
    monkeypatch.delenv("COPILOT_BENCHMARK_FIXTURE_MODE", raising=False)
    monkeypatch.setenv("COPILOT_KNOWLEDGE_DB_PATH", "stale-parent-database.sqlite")
    monkeypatch.setenv("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", "false")

    _configure_fixture_database_from_argv([
        "--fixture", "active.json",
        "--benchmark-db", str(scenario_database),
    ])

    assert os.environ.get("COPILOT_BENCHMARK_FIXTURE_MODE") == "true"
    assert "COPILOT_KNOWLEDGE_DB_PATH" not in os.environ
    assert "COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY" not in os.environ
    os.environ.pop("COPILOT_BENCHMARK_FIXTURE_MODE", None)


def test_fixture_cli_requires_an_explicit_isolated_knowledge_snapshot(
    capsys,
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("COPILOT_KNOWLEDGE_DB_PATH", raising=False)
    monkeypatch.delenv("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        run_agent_benchmark_main([
            "--fixture", str(tmp_path / "active.json"),
            "--benchmark-db", str(tmp_path / "benchmark_scenarios.sqlite"),
        ])

    assert exc_info.value.code == 2
    assert "--knowledge-db" in capsys.readouterr().err


def test_runner_marks_no_scenarios_invalid_and_reports_dataset_metadata(tmp_path):
    fixture_path, manifest_path, _payload = _write_fixture(tmp_path)
    db_path = tmp_path / "fixture.sqlite"
    initialize_fixture_database(fixture_path, db_path, manifest_path=manifest_path)
    factory = fixture_session_factory(db_path)

    empty = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {}).run_scenarios(
        scenario_type="missing-category",
        db_factory=factory,
        dataset_metadata={"dataset_id": "fixture-test-v1", "database_source": "versioned_fixture"},
    )
    assert empty["invalid_run"] is True
    assert empty["invalid_reason"] == "no_scenarios"
    assert empty["pass_rate"] == 0
    assert empty["dataset"]["database_source"] == "versioned_fixture"

    result, exit_code = run_benchmark_report(
        scenario_type="missing-category",
        db_factory=factory,
        agent_callable=lambda _payload: {},
        dataset_metadata={"dataset_id": "fixture-test-v1", "database_source": "versioned_fixture"},
    )
    assert exit_code == 2
    assert result["invalid_run"] is True
