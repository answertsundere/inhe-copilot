from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import create_engine, text

from app.services.formal_knowledge_database_guard_service import (
    DmlDiagnosticRecorder,
    backup_sqlite_database,
    compare_formal_knowledge_fingerprints,
    configure_knowledge_engine_guards,
    fingerprint_formal_knowledge_tables,
)


def _create_database(path):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE kb_product ("
        "id INTEGER PRIMARY KEY, specs_json TEXT, amount NUMERIC, updated_at DATETIME, note TEXT)"
    )
    connection.execute(
        "INSERT INTO kb_product VALUES (1, ?, ?, ?, ?)",
        ('{"height":120,"width":80}', 1, "2026-07-22T10:00:00+08:00", None),
    )
    connection.commit()
    connection.close()


def test_row_fingerprint_is_stable_for_json_numeric_and_timezone_format(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)
    before = fingerprint_formal_knowledge_tables(database, hmac_key="test-key", tables=("kb_product",))

    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE kb_product SET specs_json=?, amount=?, updated_at=? WHERE id=1",
        ('{ "width": 80, "height": 120 }', 1.0, "2026-07-22T02:00:00Z"),
    )
    connection.commit()
    connection.close()

    after = fingerprint_formal_knowledge_tables(database, hmac_key="test-key", tables=("kb_product",))
    assert before == after
    assert compare_formal_knowledge_fingerprints(before, after) == {
        "changed": False,
        "changed_row_count": 0,
        "changed_table_count": 0,
        "table_diffs": [],
    }


def test_row_fingerprint_reports_hashed_identity_and_changed_columns_only(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    _create_database(database)
    before = fingerprint_formal_knowledge_tables(database, hmac_key="test-key", tables=("kb_product",))
    connection = sqlite3.connect(database)
    connection.execute("UPDATE kb_product SET specs_json=?, note=? WHERE id=1", ('{"width":81}', "secret-value"))
    connection.commit()
    connection.close()
    after = fingerprint_formal_knowledge_tables(database, hmac_key="test-key", tables=("kb_product",))

    diff = compare_formal_knowledge_fingerprints(before, after)
    assert diff["changed_row_count"] == 1
    row = diff["table_diffs"][0]["changed_rows"][0]
    assert row["changed_column_names"] == ["note", "specs_json"]
    assert len(row["row_identity_hmac"]) == 64
    assert len(row["before_value_sha256"]) == 64
    assert len(row["after_value_sha256"]) == 64
    assert "secret-value" not in json.dumps(diff)
    assert "width" not in json.dumps(diff)


def test_sqlite_backup_is_consistent_and_refuses_overwrite(tmp_path):
    source = tmp_path / "source.sqlite"
    target = tmp_path / "target.sqlite"
    _create_database(source)
    backup_sqlite_database(source, target)
    source_fingerprint = fingerprint_formal_knowledge_tables(source, hmac_key="k", tables=("kb_product",))
    target_fingerprint = fingerprint_formal_knowledge_tables(target, hmac_key="k", tables=("kb_product",))
    source_fingerprint.pop("database_basename")
    target_fingerprint.pop("database_basename")
    assert source_fingerprint == target_fingerprint
    with pytest.raises(FileExistsError):
        backup_sqlite_database(source, target)


def test_query_only_applies_to_every_pooled_connection_and_dml_is_diagnosed(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    diagnostics = tmp_path / "dml.jsonl"
    _create_database(database)
    engine = create_engine(f"sqlite:///{database}")
    recorder = configure_knowledge_engine_guards(
        engine,
        query_only=True,
        dml_diagnostic_path=str(diagnostics),
        hmac_key="test-key",
    )
    assert isinstance(recorder, DmlDiagnosticRecorder)

    for _ in range(2):
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar() == 1
            with pytest.raises(Exception, match="readonly database"):
                connection.execute(text("UPDATE kb_product SET note='forbidden' WHERE id=1"))

    rows = [json.loads(line) for line in diagnostics.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert all(row["operation"] == "UPDATE" for row in rows)
    assert all(row["table"] == "kb_product" for row in rows)
    assert all("forbidden" not in json.dumps(row) for row in rows)
    assert all("parameters" not in row for row in rows)
    assert all(any("test_formal_knowledge_database_guard_service.py" in item for item in row["stack_summary"]) for row in rows)
