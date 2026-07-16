from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService


def _database(path, *, tables=("knowledge_entries", "knowledge_chunks", "kb_qa"), counts=(1, 1, 1)):
    connection = sqlite3.connect(path)
    try:
        for table, count in zip(tables, counts):
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.executemany(f"INSERT INTO {table} DEFAULT VALUES", [()] * count)
        connection.commit()
    finally:
        connection.close()


def test_ready_database_is_read_only_and_sanitized(tmp_path):
    path = tmp_path / "runtime.db"
    _database(path, counts=(2, 3, 4))

    report = RuntimeKnowledgeReadinessService().inspect(str(path))

    assert report["ready"] is True
    assert report["knowledge"] == {"entries": 2, "chunks": 3, "kb_qa": 4}
    assert report["database"]["basename"] == "runtime.db"
    assert "path" not in report["database"]
    assert RuntimeKnowledgeReadinessService.health_status(report) == "ok"


def test_missing_or_empty_database_is_not_ready_without_creation(tmp_path):
    missing = tmp_path / "missing.db"
    missing_report = RuntimeKnowledgeReadinessService().inspect(str(missing))
    assert missing_report["ready"] is False
    assert missing_report["reasons"] == ["knowledge_db_missing"]
    assert missing.exists() is False

    empty = tmp_path / "empty.db"
    _database(empty, counts=(0, 0, 0))
    empty_report = RuntimeKnowledgeReadinessService().inspect(str(empty))
    assert empty_report["ready"] is False
    assert set(empty_report["reasons"]) == {
        "knowledge_entries_empty", "knowledge_chunks_empty", "kb_qa_empty",
    }
    assert RuntimeKnowledgeReadinessService.health_status(empty_report) == "empty"


def test_missing_required_table_fails_closed(tmp_path):
    path = tmp_path / "partial.db"
    _database(path, tables=("knowledge_entries", "knowledge_chunks"), counts=(1, 1))

    report = RuntimeKnowledgeReadinessService().inspect(str(path))

    assert report["ready"] is False
    assert report["reasons"] == ["required_table_missing:kb_qa"]


def test_benchmark_fixture_requires_explicit_evaluation_mode(tmp_path, monkeypatch):
    path = tmp_path / "fixture.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE benchmark_fixture_metadata (key TEXT, value TEXT)")
    connection.execute("INSERT INTO benchmark_fixture_metadata VALUES ('database_source', 'versioned_fixture')")
    connection.commit()
    connection.close()

    service = RuntimeKnowledgeReadinessService()
    assert service.inspect(str(path))["ready"] is False
    monkeypatch.setenv("COPILOT_BENCHMARK_FIXTURE_MODE", "true")
    report = service.inspect(str(path))
    assert report["ready"] is True
    assert report["status"] == "ready_fixture"
    assert report["database"]["evaluation_fixture"] is True
    assert report["database"]["content_sha256"]
    assert report["database"]["schema_fingerprint"]
    assert "fingerprint" not in report["database"]


def test_content_sha256_differs_for_same_schema_different_data(tmp_path):
    path_a = tmp_path / "a.db"
    path_b = tmp_path / "b.db"
    _database(path_a, counts=(2, 3, 4))
    _database(path_b, counts=(5, 6, 7))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    report_a = RuntimeKnowledgeReadinessService().inspect(str(path_a))
    report_b = RuntimeKnowledgeReadinessService().inspect(str(path_b))

    assert report_a["database"]["content_sha256"] != report_b["database"]["content_sha256"]
    assert report_a["database"]["schema_fingerprint"] == report_b["database"]["schema_fingerprint"]


def test_content_sha256_same_for_identical_databases(tmp_path):
    path_a = tmp_path / "a.db"
    path_b = tmp_path / "b.db"
    _database(path_a, counts=(2, 3, 4))
    _database(path_b, counts=(2, 3, 4))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    report_a = RuntimeKnowledgeReadinessService().inspect(str(path_a))
    report_b = RuntimeKnowledgeReadinessService().inspect(str(path_b))

    assert report_a["database"]["content_sha256"] == report_b["database"]["content_sha256"]


def test_content_fingerprint_cache_avoids_re_read(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    _database(path, counts=(1, 1, 1))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    service = RuntimeKnowledgeReadinessService()
    report_first = service.inspect(str(path))
    assert report_first["database"]["content_sha256"]

    read_calls = []
    original_open = open

    def tracking_open(*args, **kwargs):
        if args and str(args[0]) == str(path):
            read_calls.append(args)
        return original_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)
    report_second = service.inspect(str(path))
    assert report_second["database"]["content_sha256"] == report_first["database"]["content_sha256"]
    assert read_calls == []


def test_content_fingerprint_cache_invalidated_when_size_or_mtime_changes(tmp_path):
    path = tmp_path / "runtime.db"
    _database(path, counts=(1, 1, 1))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    service = RuntimeKnowledgeReadinessService()
    first = service.inspect(str(path))["database"]["content_sha256"]

    connection = sqlite3.connect(path)
    connection.execute("INSERT INTO knowledge_entries DEFAULT VALUES")
    connection.commit()
    connection.close()

    second = service.inspect(str(path))["database"]["content_sha256"]
    assert second != first


def test_changed_during_fingerprint_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    _database(path, counts=(1, 1, 1))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    original_compute = RuntimeKnowledgeReadinessService.compute_content_fingerprint

    def changed_compute(path_arg: Path) -> dict[str, Any]:
        result = original_compute(path_arg)
        result["changed_during_fingerprint"] = True
        return result

    monkeypatch.setattr(RuntimeKnowledgeReadinessService, "compute_content_fingerprint", staticmethod(changed_compute))
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["ready"] is False
    assert "knowledge_db_changed_during_fingerprint" in report["reasons"]
    assert report["database"]["content_sha256"]


def test_readiness_does_not_leak_absolute_path(tmp_path):
    path = tmp_path / "runtime.db"
    _database(path, counts=(1, 1, 1))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    database = report["database"]

    assert database["basename"] == "runtime.db"
    assert "path" not in database
    assert "resolved_path" not in database
    assert str(tmp_path) not in str(database)
    assert str(path) not in str(database)


def test_empty_or_partial_database_still_reports_content_sha256(tmp_path):
    path = tmp_path / "empty.db"
    _database(path, counts=(0, 0, 0))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["ready"] is False
    assert report["database"]["content_sha256"]
    assert report["database"]["schema_fingerprint"]


def test_query_failure_still_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    _database(path, counts=(1, 1, 1))
    RuntimeKnowledgeReadinessService._clear_content_cache()

    real_connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)

    class FailingConnection:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.Error("forced query failure")

        def close(self):
            real_connection.close()

    monkeypatch.setattr(sqlite3, "connect", lambda *_args, **_kwargs: FailingConnection())
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["ready"] is False
    assert "knowledge_db_query_failed" in report["reasons"]
