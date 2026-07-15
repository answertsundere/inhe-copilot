from __future__ import annotations

import sqlite3

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
