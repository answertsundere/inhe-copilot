"""Read-only readiness checks for the configured formal knowledge database."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


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
        source_mode = os.getenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "local").strip()
        if source_mode not in {"local", "product_hub_review_only"}:
            report["reasons"].append("knowledge_source_mode_invalid")
            return report
        hub_mode = source_mode == "product_hub_review_only"
        if hub_mode:
            report["source_mode"] = source_mode
            if os.getenv("COPILOT_RUNTIME_ENV", "production").strip().lower() not in {"development", "test"}:
                report["reasons"].append("product_hub_candidate_environment_required")
                return report
            required_flags = (
                "COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY",
                "COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED",
                "COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED",
                "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
            )
            if not all(self._enabled(flag) for flag in required_flags):
                report["reasons"].append("product_hub_review_only_configuration_required")
                return report
            if self._enabled("COPILOT_BENCHMARK_FIXTURE_MODE"):
                report["reasons"].append("product_hub_fixture_mode_forbidden")
                return report
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

            if hub_mode and _BENCHMARK_FIXTURE_TABLE in table_names:
                report["reasons"].append("product_hub_fixture_database_forbidden")
                return report
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
            if hub_mode:
                # A Hub-only candidate must not silently mix in historical/local facts.
                nonempty = 0
                for table in table_names:
                    if table.startswith("sqlite_"):
                        continue
                    quoted = '"' + table.replace('"', '""') + '"'
                    nonempty += connection.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone() is not None
                if nonempty:
                    report["reasons"].append("product_hub_local_store_not_empty")
            else:
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

        if hub_mode and not report["reasons"]:
            return self._inspect_product_hub(report)
        if not report["reasons"]:
            report["ready"] = True
            report["status"] = "ready"
        return report

    @staticmethod
    def _enabled(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _inspect_product_hub(report: dict[str, Any]) -> dict[str, Any]:
        """Check one configured source probe, never publish its identity or facts."""
        try:
            base = urlsplit(os.getenv("COPILOT_PRODUCT_HUB_BASE_URL", ""))
            if (
                base.scheme not in {"http", "https"}
                or base.hostname not in {"127.0.0.1", "localhost", "::1"}
                or base.username or base.password or base.query or base.fragment
                or base.path not in {"", "/"}
            ):
                raise ValueError("not_loopback")
            _ = base.port
        except ValueError:
            report["reasons"].append("product_hub_loopback_configuration_required")
            return report
        sku = os.getenv("COPILOT_PRODUCT_HUB_READINESS_SKU", "").strip()
        if not sku or len(sku) > 128 or not sku.isprintable():
            report["reasons"].append("product_hub_readiness_probe_required")
            return report
        try:
            from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
            from app.services.product_context_pack_service import _product_hub_facts_for_query

            result = ProductHubReviewedFactsClient().fetch_confirmed_facts_for_sku(sku)
            if (
                not isinstance(result, dict) or result.get("state") != "ready"
                or result.get("resolved_sku_code") != sku
                or not result.get("product_code")
                or result.get("identity_source") != "product_hub_exact_sku"
                or not isinstance(result.get("facts"), list)
                or any(not isinstance(fact, dict) or fact.get("product_code") != result["product_code"]
                       for fact in result.get("facts", []))
            ):
                report["reasons"].append("product_hub_probe_unavailable")
                return report
            identity = {
                "sku": sku,
                "i_id": result["product_code"],
                "product_identity_resolution": {"status": "resolved"},
            }
            candidates = _product_hub_facts_for_query(
                result, identity=identity, query_fact_type="product_overview",
            )
            if not candidates:
                report["reasons"].append("product_hub_probe_no_eligible_facts")
                return report
        except Exception:
            # Diagnostics must not expose URL, source content or credentials from exceptions.
            report["reasons"].append("product_hub_probe_failed")
            return report
        report.update({
            "ready": True,
            "status": "ready_product_hub_review_only",
            "product_hub": {"probe_candidate_count": len(candidates)},
            "limitations": [
                "product_facts_only", "per_request_identity_and_evidence_required",
                "legacy_knowledge_unavailable", "human_review_required", "no_auto_send",
            ],
        })
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
