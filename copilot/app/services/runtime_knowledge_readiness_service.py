"""Read-only readiness checks for the configured formal knowledge database."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any


REQUIRED_KNOWLEDGE_TABLES = ("knowledge_entries", "knowledge_chunks", "kb_qa")
_BENCHMARK_FIXTURE_TABLE = "benchmark_fixture_metadata"


class RuntimeKnowledgeReadinessService:
    """Inspect the configured SQLite database without creating or mutating it."""

    def inspect(self, path_value: str | None = None) -> dict[str, Any]:
        if path_value is None:
            from app.config import KNOWLEDGE_DB_PATH

            path_value = KNOWLEDGE_DB_PATH
        path = Path(path_value or "").expanduser()
        report: dict[str, Any] = {
            "ready": False,
            "status": "not_ready",
            "reasons": [],
            "knowledge": {"entries": 0, "chunks": 0, "kb_qa": 0},
            "database": {"basename": path.name or "unconfigured"},
        }
        if not path.is_file():
            report["reasons"].append("knowledge_db_missing")
            return report

        report["database"]["size_bytes"] = path.stat().st_size
        try:
            connection = sqlite3.connect(
                f"file:{path.resolve().as_posix()}?mode=ro",
                uri=True,
            )
        except sqlite3.Error:
            report["reasons"].append("knowledge_db_unreadable")
            return report

        try:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if self._is_explicit_benchmark_fixture(connection, table_names):
                report.update({
                    "ready": True,
                    "status": "ready_fixture",
                    "database": {
                        "basename": path.name,
                        "size_bytes": path.stat().st_size,
                        "evaluation_fixture": True,
                        "fingerprint": hashlib.sha256(
                            "\n".join(sorted(table_names)).encode("utf-8")
                        ).hexdigest(),
                    },
                })
                return report
            missing = [name for name in REQUIRED_KNOWLEDGE_TABLES if name not in table_names]
            if missing:
                report["reasons"].extend(
                    f"required_table_missing:{name}" for name in missing
                )
                return report
            counts = {
                "entries": connection.execute("SELECT COUNT(*) FROM knowledge_entries").fetchone()[0],
                "chunks": connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0],
                "kb_qa": connection.execute("SELECT COUNT(*) FROM kb_qa").fetchone()[0],
            }
            report["knowledge"] = counts
            for key, reason in (
                ("entries", "knowledge_entries_empty"),
                ("chunks", "knowledge_chunks_empty"),
                ("kb_qa", "kb_qa_empty"),
            ):
                if counts[key] <= 0:
                    report["reasons"].append(reason)
            report["database"].update({
                "schema_version": connection.execute("PRAGMA schema_version").fetchone()[0],
                "fingerprint": hashlib.sha256(
                    "\n".join(sorted(table_names)).encode("utf-8")
                ).hexdigest(),
            })
        except sqlite3.Error:
            report["reasons"].append("knowledge_db_query_failed")
        finally:
            connection.close()

        if not report["reasons"]:
            report["ready"] = True
            report["status"] = "ready"
        return report

    @staticmethod
    def _is_explicit_benchmark_fixture(
        connection: sqlite3.Connection,
        table_names: set[str],
    ) -> bool:
        if os.getenv("COPILOT_BENCHMARK_FIXTURE_MODE", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return False
        if _BENCHMARK_FIXTURE_TABLE not in table_names:
            return False
        try:
            row = connection.execute(
                f"SELECT value FROM {_BENCHMARK_FIXTURE_TABLE} WHERE key = 'database_source'"
            ).fetchone()
        except sqlite3.Error:
            return False
        return bool(row and row[0] == "versioned_fixture")

    @staticmethod
    def health_status(readiness: dict[str, Any]) -> str:
        if readiness.get("ready"):
            return "ok"
        reasons = set(readiness.get("reasons") or [])
        if "knowledge_db_missing" in reasons:
            return "missing"
        if reasons & {"knowledge_entries_empty", "knowledge_chunks_empty", "kb_qa_empty"}:
            return "empty"
        return "error"
