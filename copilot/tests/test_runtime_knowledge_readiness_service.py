from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Any

import pytest

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


_HUB_FLAGS = (
    "COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY",
    "COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED",
    "COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED",
    "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
)


def _hub_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "product_hub_review_only")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "test")
    monkeypatch.delenv("COPILOT_BENCHMARK_FIXTURE_MODE", raising=False)
    for flag in _HUB_FLAGS:
        monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_READINESS_SKU", "probe-variant-A")
    path = tmp_path / "hub-empty.db"
    _database(path, counts=(0, 0, 0))
    result = {
        "state": "ready", "product_code": "probe-product",
        "resolved_sku_code": "probe-variant-A", "identity_source": "product_hub_exact_sku",
        "facts": [{
            "id": "probe-fact", "product_code": "probe-product", "type": "material",
            "attr": "\u6750\u8d28", "scope": "\u5546\u54c1\u6574\u4f53",
            "unit": "", "value": "PP/TPE", "status": "confirmed",
            "conflict": False, "sku_code": "", "applies": "",
        }],
    }
    calls = []

    def fetch(_self, sku):
        calls.append(sku)
        return result

    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    monkeypatch.setattr(ProductHubReviewedFactsClient, "fetch_confirmed_facts_for_sku", fetch)
    return path, result, calls


def test_hub_candidate_is_explicit_limited_read_only_and_has_no_probe_evidence(tmp_path, monkeypatch):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    before = path.read_bytes()
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["ready"] is True, report
    assert report["status"] == "ready_product_hub_review_only"
    assert report["knowledge"] == {"entries": 0, "chunks": 0, "kb_qa": 0}
    assert report["product_hub"]["probe_candidate_count"] == 1
    assert "no_auto_send" in report["limitations"]
    serialized = json.dumps(report)
    for secret in ("probe-variant", "probe-product", "probe-fact", "PP/TPE", "http://", str(tmp_path)):
        assert secret not in serialized
    assert path.read_bytes() == before
    assert calls == ["probe-variant-A"]


@pytest.mark.parametrize("flag", _HUB_FLAGS)
def test_hub_requires_existing_review_and_read_only_flags(tmp_path, monkeypatch, flag):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    monkeypatch.setenv(flag, "false")
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert not report["ready"]
    assert report["reasons"] == ["product_hub_review_only_configuration_required"]
    assert calls == []


@pytest.mark.parametrize("mode", ["", "typo", "PRODUCT_HUB_REVIEW_ONLY", "benchmark"])
def test_unknown_knowledge_source_mode_fails_closed(tmp_path, monkeypatch, mode):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    monkeypatch.setenv("COPILOT_KNOWLEDGE_SOURCE_MODE", mode)
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["reasons"] == ["knowledge_source_mode_invalid"]
    assert not report["ready"] and not calls


def test_hub_flags_do_not_implicitly_change_local_mode(tmp_path, monkeypatch):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    monkeypatch.delenv("COPILOT_KNOWLEDGE_SOURCE_MODE")
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert not report["ready"] and len(report["reasons"]) == 3
    assert not calls


@pytest.mark.parametrize("table", ["knowledge_entries", "knowledge_chunks", "kb_qa", "unrelated_policy"])
def test_hub_rejects_any_local_application_rows(tmp_path, monkeypatch, table):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    with sqlite3.connect(path) as con:
        if table == "unrelated_policy":
            con.execute("CREATE TABLE unrelated_policy (id INTEGER)")
        con.execute(f"INSERT INTO {table} DEFAULT VALUES")
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["reasons"] == ["product_hub_local_store_not_empty"]
    assert not report["ready"] and not calls


@pytest.mark.parametrize("kind", ["mode", "table", "schema", "changed"])
def test_hub_cannot_bypass_fixture_schema_or_integrity_checks(tmp_path, monkeypatch, kind):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    if kind == "mode":
        monkeypatch.setenv("COPILOT_BENCHMARK_FIXTURE_MODE", "true")
    elif kind in {"table", "schema"}:
        with sqlite3.connect(path) as con:
            con.execute("CREATE TABLE benchmark_fixture_metadata (key TEXT, value TEXT)" if kind == "table" else "DROP TABLE kb_qa")
    else:
        original = RuntimeKnowledgeReadinessService.compute_content_fingerprint
        monkeypatch.setattr(RuntimeKnowledgeReadinessService, "compute_content_fingerprint", staticmethod(
            lambda value: {**original(value), "changed_during_fingerprint": True}
        ))
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert not report["ready"] and report["reasons"] and not calls


@pytest.mark.parametrize("base", ["https://example.com", "http://user:secret@127.0.0.1", "http://127.0.0.1/path", "http://127.0.0.1:bad", "http://127.0.0.1?token=secret"])
def test_hub_probe_rejects_non_loopback_or_credential_urls(tmp_path, monkeypatch, base):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", base)
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["reasons"] == ["product_hub_loopback_configuration_required"]
    assert not report["ready"] and not calls


@pytest.mark.parametrize("mutation", ["unavailable", "wrong_sku", "wrong_identity", "no_facts", "pending", "conflict", "wrong_scope", "wrong_product"])
def test_hub_probe_requires_current_eligible_exact_identity_facts(tmp_path, monkeypatch, mutation):
    path, result, _ = _hub_candidate(tmp_path, monkeypatch)
    if mutation == "unavailable":
        result["state"] = "unavailable"
    elif mutation == "wrong_sku":
        result["resolved_sku_code"] = "different-sku"
    elif mutation == "wrong_identity":
        result["identity_source"] = "title_guess"
    elif mutation == "no_facts":
        result["facts"] = []
    else:
        key, value = {
            "pending": ("status", "pending"), "conflict": ("conflict", True),
            "wrong_scope": ("scope", "component"), "wrong_product": ("product_code", "different-product"),
        }[mutation]
        result["facts"][0][key] = value
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert not report["ready"] and report["reasons"]


def test_hub_positive_probe_is_not_cached(tmp_path, monkeypatch):
    path, result, calls = _hub_candidate(tmp_path, monkeypatch)
    service = RuntimeKnowledgeReadinessService()
    assert service.inspect(str(path))["ready"]
    result["facts"][0]["status"] = "pending"
    assert not service.inspect(str(path))["ready"]
    assert len(calls) == 2


def test_hub_probe_failure_does_not_disclose_exception(tmp_path, monkeypatch):
    path, _, _ = _hub_candidate(tmp_path, monkeypatch)
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient

    def fail(*_args):
        raise RuntimeError("private-token-and-product")

    monkeypatch.setattr(ProductHubReviewedFactsClient, "fetch_confirmed_facts_for_sku", fail)
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["reasons"] == ["product_hub_probe_failed"]
    assert "private-token" not in json.dumps(report)


@pytest.mark.parametrize("sku", ["", " " , "x" * 129, "bad\nvalue"])
def test_hub_requires_valid_explicit_probe_sku(tmp_path, monkeypatch, sku):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_READINESS_SKU", sku)
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["reasons"] == ["product_hub_readiness_probe_required"]
    assert not report["ready"] and not calls


def test_hub_candidate_not_available_in_production_environment(tmp_path, monkeypatch):
    path, _, calls = _hub_candidate(tmp_path, monkeypatch)
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "production")
    report = RuntimeKnowledgeReadinessService().inspect(str(path))
    assert report["reasons"] == ["product_hub_candidate_environment_required"]
    assert not report["ready"] and not calls


@pytest.mark.parametrize("ready", [True, False])
def test_hub_public_readiness_is_limited_and_sanitized(ready):
    from app.api.runtime_routes import public_readiness_payload

    report = public_readiness_payload({
        "ready": ready, "source_mode": "product_hub_review_only",
        "reasons": [] if ready else ["product_hub_probe_unavailable", "private-exception"],
        "database": {"path": "private/path"}, "probe_sku": "private-sku",
        "facts": [{"value": "private-value"}],
    })
    assert report["status"] == ("ready_product_hub_review_only" if ready else "not_ready")
    assert report["scope"] == "product_facts_review_only"
    assert "private" not in json.dumps(report)
    if not ready:
        assert report["reasons"] == ["product_hub_probe_unavailable", "runtime_not_ready"]
