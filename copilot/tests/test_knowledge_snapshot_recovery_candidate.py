from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_knowledge_snapshot_recovery_candidate.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "knowledge_snapshot_recovery_candidate",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_schema_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE kb_product (
            id INTEGER PRIMARY KEY,
            i_id TEXT NOT NULL UNIQUE,
            product_name TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            import_batch_id TEXT NOT NULL DEFAULT '',
            domain_policy_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE knowledge_entries (
            id INTEGER PRIMARY KEY,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            import_batch_id TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            business_key TEXT,
            product_id TEXT,
            fact_type TEXT,
            fact_scope TEXT,
            risk_level TEXT,
            auto_reply_allowed INTEGER NOT NULL DEFAULT 0,
            human_review_required INTEGER NOT NULL DEFAULT 1,
            source_confidence REAL,
            fact_review_status TEXT,
            index_status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE kb_qa (id INTEGER PRIMARY KEY, question TEXT NOT NULL DEFAULT '');
        CREATE TABLE knowledge_chunks (id INTEGER PRIMARY KEY, entry_id INTEGER, chunk_text TEXT NOT NULL DEFAULT '');
        CREATE TABLE kb_media_asset (id INTEGER PRIMARY KEY, asset_url TEXT NOT NULL DEFAULT '');
        CREATE TABLE agent_answer_memory (id INTEGER PRIMARY KEY, approved_answer TEXT NOT NULL DEFAULT '');
        CREATE TABLE kb_change_log (id INTEGER PRIMARY KEY, change_reason TEXT NOT NULL DEFAULT '');
        """
    )
    connection.executescript(
        """
        INSERT INTO kb_product (id, i_id, product_name, status) VALUES (99, 'SEED', 'seed product', 'published');
        INSERT INTO knowledge_entries (id, source_type, title, content, status) VALUES (99, 'seed', 'seed title', 'seed content', 'published');
        INSERT INTO kb_qa (id, question) VALUES (1, 'seed qa');
        INSERT INTO knowledge_chunks (id, entry_id, chunk_text) VALUES (1, 99, 'seed chunk');
        INSERT INTO kb_media_asset (id, asset_url) VALUES (1, 'https://seed.invalid/media');
        INSERT INTO agent_answer_memory (id, approved_answer) VALUES (1, 'seed answer');
        INSERT INTO kb_change_log (id, change_reason) VALUES (1, 'seed change');
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
            i_id TEXT NOT NULL UNIQUE,
            product_name TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            import_batch_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE knowledge_entries (
            id INTEGER PRIMARY KEY,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            import_batch_id TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            business_key TEXT,
            product_id TEXT,
            fact_type TEXT,
            fact_scope TEXT,
            risk_level TEXT,
            auto_reply_allowed INTEGER NOT NULL DEFAULT 0,
            human_review_required INTEGER NOT NULL DEFAULT 1,
            source_confidence REAL,
            fact_review_status TEXT,
            index_status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE kb_qa (id INTEGER PRIMARY KEY, question TEXT NOT NULL DEFAULT '');
        CREATE TABLE knowledge_chunks (id INTEGER PRIMARY KEY, entry_id INTEGER, chunk_text TEXT NOT NULL DEFAULT '');
        CREATE TABLE kb_media_asset (id INTEGER PRIMARY KEY, asset_url TEXT NOT NULL DEFAULT '');
        CREATE TABLE agent_answer_memory (id INTEGER PRIMARY KEY, approved_answer TEXT NOT NULL DEFAULT '');
        CREATE TABLE kb_change_log (id INTEGER PRIMARY KEY, change_reason TEXT NOT NULL DEFAULT '');
        """
    )
    connection.executemany(
        "INSERT INTO kb_product (id, i_id, product_name, status, version) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "IID-eligible", "eligible product", "published", 8),
            (2, "IID-archived", "archived product", "archived", 3),
            (3, "IID-component", "component product", "published", 2),
        ],
    )
    connection.execute(
        """
        INSERT INTO knowledge_entries (
            id, source_type, title, content, status, version, created_by, updated_by,
            reviewed_by, published_at, import_batch_id, content_hash, business_key,
            product_id, fact_type, fact_scope, risk_level, auto_reply_allowed,
            human_review_required, source_confidence, fact_review_status, index_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            16,
            "product_facts",
            "binary identity fact",
            "not selected",
            "published",
            1,
            "historical-user",
            "historical-user",
            "historical-reviewer",
            "2025-01-01T00:00:00",
            "old-batch",
            "",
            "product:IID-eligible:binary",
            sqlite3.Binary(b"IID-eligible"),
            "material",
            "product",
            "low",
            1,
            0,
            0.9,
            "published",
            "done",
        ),
    )
    connection.executemany(
        """
        INSERT INTO knowledge_entries (
            id, source_type, title, content, status, version, created_by, updated_by,
            reviewed_by, published_at, import_batch_id, content_hash, business_key,
            product_id, fact_type, fact_scope, risk_level, auto_reply_allowed,
            human_review_required, source_confidence, fact_review_status, index_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                11,
                "product_facts",
                "eligible title",
                "private source sentence",
                "published",
                4,
                "historical-user",
                "historical-user",
                "historical-reviewer",
                "2025-01-01T00:00:00",
                "old-batch",
                "",
                "product:IID-eligible:material",
                "IID-eligible",
                "material",
                "product",
                "low",
                1,
                0,
                0.9,
                "published",
                "done",
            ),
            (
                12,
                "product_facts",
                "unpublished fact",
                "not selected",
                "draft",
                1,
                "historical-user",
                "historical-user",
                "",
                None,
                "old-batch",
                "",
                "product:IID-eligible:draft",
                "IID-eligible",
                "material",
                "product",
                "low",
                0,
                1,
                0.5,
                "draft_unverified",
                "pending",
            ),
            (
                13,
                "product_facts",
                "archived product fact",
                "not selected",
                "published",
                1,
                "historical-user",
                "historical-user",
                "historical-reviewer",
                "2025-01-01T00:00:00",
                "old-batch",
                "",
                "product:IID-archived:material",
                "IID-archived",
                "material",
                "product",
                "low",
                1,
                0,
                0.9,
                "published",
                "done",
            ),
            (
                14,
                "product_facts",
                "component fact",
                "not selected",
                "published",
                1,
                "historical-user",
                "historical-user",
                "historical-reviewer",
                "2025-01-01T00:00:00",
                "old-batch",
                "",
                "product:IID-component:component",
                "IID-component",
                "width",
                "component",
                "low",
                1,
                0,
                0.9,
                "published",
                "done",
            ),
            (
                15,
                "product_facts",
                "mismatched fact",
                "not selected",
                "published",
                1,
                "historical-user",
                "historical-user",
                "historical-reviewer",
                "2025-01-01T00:00:00",
                "old-batch",
                "",
                "product:unknown:material",
                "IID-unknown",
                "material",
                "product",
                "low",
                1,
                0,
                0.9,
                "published",
                "done",
            ),
        ],
    )
    connection.executescript(
        """
        INSERT INTO kb_qa (id, question) VALUES (1, 'historical qa');
        INSERT INTO knowledge_chunks (id, entry_id, chunk_text) VALUES (1, 11, 'historical chunk');
        INSERT INTO kb_media_asset (id, asset_url) VALUES (1, 'https://historical.invalid/media?token=secret');
        INSERT INTO agent_answer_memory (id, approved_answer) VALUES (1, 'historical answer');
        INSERT INTO kb_change_log (id, change_reason) VALUES (1, 'historical change');
        """
    )
    connection.commit()
    connection.close()


@pytest.fixture()
def recovery_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_module()
    schema = tmp_path / "schema.db"
    snapshot = tmp_path / "snapshot.db"
    candidate_root = tmp_path / "ignored-candidates"
    candidate = candidate_root / "candidate.db"
    monkeypatch.setattr(
        module,
        "_RECOVERY_CANDIDATE_ROOT",
        candidate_root,
        raising=False,
    )
    _create_schema_database(schema)
    _create_snapshot_database(snapshot)
    return module, snapshot, schema, candidate


def _row_count(path: Path, table: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    finally:
        connection.close()


def test_dry_run_reports_only_eligible_counts_and_never_creates_candidate(
    recovery_context,
) -> None:
    module, snapshot, schema, candidate = recovery_context

    report = module.build_snapshot_recovery_candidate(
        snapshot,
        schema,
        candidate,
        apply=False,
    )

    assert report["candidate_created"] is False
    assert report["selection"]["eligible_product_count"] == 1
    assert report["selection"]["eligible_fact_count"] == 1
    assert report["source"]["query_only_verified"] is True
    assert not candidate.exists()


def test_apply_resets_review_state_and_excludes_other_knowledge_roles(
    recovery_context,
) -> None:
    module, snapshot, schema, candidate = recovery_context

    report = module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)

    assert report["candidate_created"] is True
    assert _row_count(candidate, "kb_product") == 1
    assert _row_count(candidate, "knowledge_entries") == 1
    for table in (
        "kb_qa",
        "knowledge_chunks",
        "kb_media_asset",
        "agent_answer_memory",
        "kb_change_log",
    ):
        assert _row_count(candidate, table) == 0

    connection = sqlite3.connect(candidate)
    try:
        product = connection.execute(
            "SELECT i_id, status, version, domain_policy_id, import_batch_id "
            "FROM kb_product"
        ).fetchone()
        fact = connection.execute(
            "SELECT product_id, status, fact_review_status, auto_reply_allowed, "
            "human_review_required, index_status, content_hash, import_batch_id, "
            "reviewed_by, published_at FROM knowledge_entries"
        ).fetchone()
    finally:
        connection.close()

    assert product[0] == "IID-eligible"
    assert product[1] == "pending_review"
    assert product[2] == 1
    assert product[3] == ""
    assert product[4] == fact[7]
    assert fact[0] == "IID-eligible"
    assert fact[1:6] == ("pending_review", "needs_human_review", 0, 1, "pending")
    assert fact[6] == hashlib.sha256(
        "eligible title|private source sentence".encode("utf-8")
    ).hexdigest()[:32]
    assert fact[8] == ""
    assert fact[9] is None


def test_builder_refuses_formal_target_or_existing_candidate(
    recovery_context,
) -> None:
    module, snapshot, schema, candidate = recovery_context

    with pytest.raises(ValueError, match="candidate_path_not_isolated"):
        module.build_snapshot_recovery_candidate(snapshot, schema, schema, apply=True)

    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"already exists")
    with pytest.raises(ValueError, match="candidate_path_not_isolated"):
        module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)


def test_builder_refuses_sqlite_sidecar_and_non_ignored_candidate_paths(
    recovery_context,
) -> None:
    module, snapshot, schema, candidate = recovery_context

    formal_sidecar = schema.with_name(f"{schema.name}-wal")
    with pytest.raises(ValueError, match="candidate_path_not_isolated"):
        module.build_snapshot_recovery_candidate(snapshot, schema, formal_sidecar, apply=True)

    outside_ignored_root = candidate.parent.parent / "not-ignored" / "candidate.db"
    with pytest.raises(ValueError, match="candidate_path_not_isolated"):
        module.build_snapshot_recovery_candidate(snapshot, schema, outside_ignored_root, apply=True)


def test_builder_never_deletes_external_file_created_after_validation(
    recovery_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, snapshot, schema, candidate = recovery_context

    def external_writer(_source: Path, _destination: Path) -> None:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"external")
        raise RuntimeError("injected_backup_failure")

    monkeypatch.setattr(module, "backup_sqlite_database", external_writer)

    with pytest.raises(RuntimeError, match="injected_backup_failure"):
        module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)

    assert candidate.read_bytes() == b"external"


def test_source_and_formal_schema_checksums_remain_unchanged(
    recovery_context,
) -> None:
    module, snapshot, schema, candidate = recovery_context
    before = (_sha256(snapshot), _sha256(schema))

    report = module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)

    assert (_sha256(snapshot), _sha256(schema)) == before
    assert report["formal_knowledge_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
    assert report["formal_schema_sha256_before"] == report["formal_schema_sha256_after"]


def test_manifest_contains_hashes_and_counts_but_not_source_content(
    recovery_context,
) -> None:
    module, snapshot, schema, candidate = recovery_context

    report = module.build_snapshot_recovery_candidate(snapshot, schema, candidate, apply=True)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)

    assert "private source sentence" not in rendered
    assert "historical.invalid" not in rendered
    assert report["formal_evidence_admission_allowed"] is False
    assert report["direct_database_copy_allowed"] is False
    assert report["copy_counts"] == {
        "kb_product": 1,
        "knowledge_entries": 1,
        "kb_qa": 0,
        "knowledge_chunks": 0,
        "kb_media_asset": 0,
        "agent_answer_memory": 0,
        "kb_change_log": 0,
    }


def test_cli_dry_run_works_when_invoked_as_a_script(
    tmp_path: Path,
) -> None:
    schema = tmp_path / "schema.db"
    snapshot = tmp_path / "snapshot.db"
    candidate = SCRIPT_PATH.parents[1] / "data" / "imports" / "candidate-dry-run.db"
    _create_schema_database(schema)
    _create_snapshot_database(snapshot)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--snapshot-db",
            str(snapshot),
            "--schema-db",
            str(schema),
            "--candidate-db",
            str(candidate),
        ],
        cwd=SCRIPT_PATH.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["candidate_created"] is False
