"""Read-only readiness checks for the configured formal knowledge database."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable


REQUIRED_KNOWLEDGE_TABLES = ("knowledge_entries", "knowledge_chunks", "kb_qa")
_BENCHMARK_FIXTURE_TABLE = "benchmark_fixture_metadata"
_READ_CHUNK_SIZE = 8 * 1024 * 1024


class RuntimeKnowledgeReadinessService:
    """Inspect the configured SQLite database without creating or mutating it."""

    _CONTENT_CACHE: dict[str, tuple[str, str]] = {}

    @classmethod
    def compute_content_fingerprint(cls, path: Path) -> dict[str, Any]:
        """Return a SHA-256 of the actual file bytes with size/mtime caching.

        The cache key includes the resolved path, file size, and mtime in
        nanoseconds. If the file changes while it is being read, the result
        carries ``changed_during_fingerprint`` so the caller can fail closed.
        """
        resolved = str(path.resolve())
        stat_before = path.stat()
        cache_key = {
            "resolved_path": resolved,
            "size_bytes": stat_before.st_size,
            "mtime_ns": stat_before.st_mtime_ns,
        }
        cache_key_json = json.dumps(cache_key, sort_keys=True)
        cached = cls._CONTENT_CACHE.get(resolved)
        if cached is not None and cached[0] == cache_key_json:
            return {"content_sha256": cached[1], "cache_hit": True, "cache_key": cache_key}

        hasher = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_READ_CHUNK_SIZE), b""):
                hasher.update(chunk)
        content_sha256 = hasher.hexdigest()

        stat_after = path.stat()
        if (
            stat_after.st_size != stat_before.st_size
            or stat_after.st_mtime_ns != stat_before.st_mtime_ns
        ):
            return {
                "content_sha256": content_sha256,
                "changed_during_fingerprint": True,
                "cache_key": cache_key,
            }

        cls._CONTENT_CACHE[resolved] = (cache_key_json, content_sha256)
        return {"content_sha256": content_sha256, "cache_key": cache_key}

    @classmethod
    def _clear_content_cache(cls) -> None:
        """Test helper to force re-computation between isolated scenarios."""
        cls._CONTENT_CACHE.clear()

    @staticmethod
    def compute_schema_fingerprint(table_names: Iterable[str]) -> str:
        """SHA-256 of the sorted table names; distinct from content identity."""
        return hashlib.sha256("\n".join(sorted(table_names)).encode("utf-8")).hexdigest()

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
            schema_fingerprint = self.compute_schema_fingerprint(table_names)
            content_info = self.compute_content_fingerprint(path)
            content_sha256 = content_info.get("content_sha256")
            changed_during_fingerprint = bool(content_info.get("changed_during_fingerprint"))

            report["database"].update({
                "content_sha256": content_sha256,
                "schema_fingerprint": schema_fingerprint,
            })

            is_fixture = self._is_explicit_benchmark_fixture(connection, table_names)
            if is_fixture:
                report["database"].update({
                    "size_bytes": path.stat().st_size,
                    "evaluation_fixture": True,
                })
                if changed_during_fingerprint:
                    report["reasons"].append("knowledge_db_changed_during_fingerprint")
                else:
                    report["ready"] = True
                    report["status"] = "ready_fixture"
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
            report["database"]["schema_version"] = connection.execute(
                "PRAGMA schema_version"
            ).fetchone()[0]
            if changed_during_fingerprint:
                report["reasons"].append("knowledge_db_changed_during_fingerprint")
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
