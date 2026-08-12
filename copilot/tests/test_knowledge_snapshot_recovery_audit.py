from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_knowledge_snapshot_recovery.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("knowledge_snapshot_recovery_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_current_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE kb_product (
            id INTEGER PRIMARY KEY,
            i_id TEXT NOT NULL,
            sku_list_json TEXT NOT NULL,
            product_name TEXT NOT NULL,
            status TEXT NOT NULL,
            domain_policy_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE knowledge_entries (
            id INTEGER PRIMARY KEY,
            product_id TEXT,
            status TEXT,
            fact_review_status TEXT,
            fact_scope TEXT,
            fact_type TEXT,
            risk_level TEXT,
            human_review_required INTEGER,
            auto_reply_allowed INTEGER,
            business_key TEXT,
            content_hash TEXT,
            content TEXT
        );
        CREATE TABLE kb_media_asset (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
            i_id TEXT,
            status TEXT,
            audit_status TEXT,
            usable_for_agent INTEGER,
            refresh_status TEXT,
            asset_url TEXT,
            source_raw_json TEXT
        );
        CREATE TABLE kb_qa (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
            status TEXT,
            risk_level TEXT,
            question TEXT,
            answer TEXT
        );
        """
    )
    connection.commit()
    connection.close()


def _create_snapshot_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE kb_product (
            id INTEGER PRIMARY KEY,
            i_id TEXT NOT NULL,
            sku_list_json TEXT NOT NULL,
            product_name TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE knowledge_entries (
            id INTEGER PRIMARY KEY,
            product_id TEXT,
            status TEXT,
            fact_review_status TEXT,
            fact_scope TEXT,
            fact_type TEXT,
            risk_level TEXT,
            human_review_required INTEGER,
            auto_reply_allowed INTEGER,
            business_key TEXT,
            content_hash TEXT,
            content TEXT
        );
        CREATE TABLE kb_media_asset (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
            i_id TEXT,
            status TEXT,
            audit_status TEXT,
            usable_for_agent INTEGER,
            refresh_status TEXT,
            asset_url TEXT,
            source_raw_json TEXT
        );
        CREATE TABLE kb_qa (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
            status TEXT,
            risk_level TEXT,
            question TEXT,
            answer TEXT
        );
        """
    )
    connection.executemany(
        "INSERT INTO kb_product VALUES (?, ?, ?, ?, ?)",
        [
            (1, "IID-1", '["SKU-1"]', "Product one", "published"),
            (2, "IID-2", '["SKU-2"]', "Product two", "archived"),
        ],
    )
    connection.executemany(
        "INSERT INTO knowledge_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "IID-1", "published", "published", "product", "material", "low", 0, 1, "fact-1", "", "contact 13800138000"),
            (2, "IID-1", "published", "draft_unverified", "product", "material", "low", 0, 1, "fact-2", "", "unverified"),
            (3, "IID-2", "published", "published", "product", "load_capacity", "high", 1, 0, "fact-3", "", "archived product"),
        ],
    )
    connection.executemany(
        "INSERT INTO kb_media_asset VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "IID-1", "approved", "reviewed", 1, "ok", "https://example.test/a?signature=x", "{}"),
            (2, 1, "IID-missing", "approved", "reviewed", 1, "ok", "https://example.test/b?signature=y", "{}"),
        ],
    )
    connection.executemany(
        "INSERT INTO kb_qa VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "published", "low", "question", "answer"),
            (2, 1, "published", "high", "question", "answer"),
        ],
    )
    connection.commit()
    connection.close()


def test_snapshot_recovery_report_is_read_only_and_quarantines_untrusted_rows(tmp_path):
    current = tmp_path / "current.sqlite"
    snapshot = tmp_path / "historical.sqlite"
    _create_current_database(current)
    _create_snapshot_database(snapshot)
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()

    module = _load_module()
    report = module.build_snapshot_recovery_report(snapshot, current)

    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == snapshot_hash
    assert report["source"]["query_only_verified"] is True
    assert report["candidate_counts"]["published_products"] == 1
    assert report["candidate_counts"]["reviewed_product_facts_identity_matched"] == 1
    assert report["candidate_counts"]["media_strict_identity_matched"] == 1
    assert report["candidate_counts"]["media_identity_mismatch_or_missing"] == 1
    assert report["candidate_counts"]["published_high_risk_qa"] == 1
    assert report["schema_compatibility"]["kb_product"]["target_only_columns"] == ["domain_policy_id"]
    assert report["recovery_decision"]["direct_database_copy_allowed"] is False
    assert report["recovery_decision"]["formal_evidence_admission_allowed"] is False
    assert "13800138000" not in json.dumps(report)
    assert report["potential_sensitive_pattern_counts"]["knowledge_entries"]["content"]["phone_like"] == 1


def test_snapshot_recovery_report_rejects_same_source_and_target(tmp_path):
    database = tmp_path / "same.sqlite"
    _create_current_database(database)

    module = _load_module()

    with pytest.raises(ValueError, match="snapshot_and_target_must_differ"):
        module.build_snapshot_recovery_report(database, database)


def test_snapshot_recovery_report_json_contains_only_structural_diagnostics(tmp_path):
    current = tmp_path / "current.sqlite"
    snapshot = tmp_path / "historical.sqlite"
    output = tmp_path / "audit.json"
    _create_current_database(current)
    _create_snapshot_database(snapshot)

    module = _load_module()
    report = module.build_snapshot_recovery_report(snapshot, current)
    module.write_json_report(output, report)
    loaded = json.loads(output.read_text(encoding="utf-8"))

    assert loaded == report
    rendered = json.dumps(loaded, ensure_ascii=False)
    assert "Product one" not in rendered
    assert "https://example.test" not in rendered
    assert "13800138000" not in rendered
