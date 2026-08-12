"""Build a review-only candidate database from a historical knowledge snapshot.

The historical snapshot remains query-only. This tool never changes the formal
schema database: it uses that database solely as a schema seed for a separate,
new candidate file. Candidate rows deliberately lose published/auto-reply
status and cannot be used as formal evidence until current review governance
accepts them through an explicit later workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.formal_knowledge_database_guard_service import backup_sqlite_database  # noqa: E402


_RECOVERY_CANDIDATE_ROOT = PROJECT_ROOT / "data" / "imports"
_COPIED_TABLES = ("kb_product", "knowledge_entries")
_EXCLUDED_TABLES = (
    "kb_qa",
    "knowledge_chunks",
    "kb_media_asset",
    "agent_answer_memory",
    "kb_change_log",
)
_REQUIRED_SOURCE_COLUMNS = {
    "kb_product": ("i_id", "status"),
    "knowledge_entries": ("product_id", "status", "fact_review_status", "fact_scope"),
}
_REQUIRED_CANDIDATE_COLUMNS = {
    "kb_product": ("i_id", "status", "import_batch_id"),
    "knowledge_entries": (
        "product_id",
        "status",
        "fact_review_status",
        "auto_reply_allowed",
        "human_review_required",
        "index_status",
        "content_hash",
        "import_batch_id",
    ),
}


def _resolve_existing_database(path: Path | str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise ValueError("database_file_not_found")
    return candidate


def _resolve_candidate_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if int(connection.execute("PRAGMA query_only").fetchone()[0] or 0) != 1:
        connection.close()
        raise RuntimeError("sqlite_query_only_not_enforced")
    return connection


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if not exists:
        raise ValueError(f"required_table_missing:{table}")
    return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({_quote(table)})"))


def _require_columns(
    connection: sqlite3.Connection,
    required: dict[str, Iterable[str]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for table, names in required.items():
        columns = _table_columns(connection, table)
        missing = sorted(set(names) - set(columns))
        if missing:
            raise ValueError(f"required_column_missing:{table}:{','.join(missing)}")
        result[table] = columns
    return result


def _validate_candidate_path(
    snapshot_path: Path,
    schema_path: Path,
    candidate_path: Path,
    *,
    apply: bool,
) -> None:
    reserved_paths = {
        *{path for path in (snapshot_path, schema_path)},
        *{
            Path(f"{path}{suffix}")
            for path in (snapshot_path, schema_path)
            for suffix in ("-wal", "-shm", "-journal")
        },
    }
    candidate_root = _RECOVERY_CANDIDATE_ROOT.resolve()
    try:
        candidate_path.relative_to(candidate_root)
    except ValueError:
        raise ValueError("candidate_path_not_isolated") from None
    if (
        candidate_path in reserved_paths
        or candidate_path.name.lower() == "knowledge_base.db"
        or candidate_path.name.lower().endswith(("-wal", "-shm", "-journal"))
    ):
        raise ValueError("candidate_path_not_isolated")
    if apply and candidate_path.exists():
        raise ValueError("candidate_path_not_isolated")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _recovery_content_hash(entry: sqlite3.Row) -> str:
    """Reuse the formal repository's title-and-content duplicate fingerprint."""
    payload = f"{str(entry['title'] or '').strip()}|{str(entry['content'] or '').strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _select_eligible_rows(
    source: sqlite3.Connection,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    products = list(
        source.execute(
            """
            SELECT product.*
            FROM kb_product AS product
            WHERE product.status='published'
              AND EXISTS (
                  SELECT 1
                  FROM knowledge_entries AS entry
                  WHERE typeof(entry.product_id)='text'
                    AND typeof(product.i_id)='text'
                    AND entry.product_id=product.i_id
                    AND entry.status='published'
                    AND entry.fact_review_status='published'
                    AND entry.fact_scope='product'
              )
            ORDER BY product.i_id, product.id
            """
        )
    )
    entries = list(
        source.execute(
            """
            SELECT entry.*
            FROM knowledge_entries AS entry
            JOIN kb_product AS product
              ON typeof(entry.product_id)='text'
             AND typeof(product.i_id)='text'
             AND entry.product_id=product.i_id
            WHERE product.status='published'
              AND entry.status='published'
              AND entry.fact_review_status='published'
              AND entry.fact_scope='product'
            ORDER BY entry.product_id, entry.id
            """
        )
    )
    return products, entries


def _candidate_overrides(table: str, *, batch_id: str, row: sqlite3.Row) -> dict[str, Any]:
    if table == "kb_product":
        return {
            "status": "pending_review",
            "version": 1,
            "created_by": "snapshot_recovery",
            "updated_by": "snapshot_recovery",
            "import_batch_id": batch_id,
            "domain_policy_id": "",
        }
    return {
        "status": "pending_review",
        "version": 1,
        "created_by": "snapshot_recovery",
        "updated_by": "snapshot_recovery",
        "reviewed_by": "",
        "published_at": None,
        "import_batch_id": batch_id,
        "content_hash": _recovery_content_hash(row),
        "parent_entry_id": None,
        "auto_reply_allowed": 0,
        "human_review_required": 1,
        "fact_review_status": "needs_human_review",
        "index_status": "pending",
    }


def _insert_row(
    connection: sqlite3.Connection,
    table: str,
    row: sqlite3.Row,
    source_columns: tuple[str, ...],
    candidate_columns: tuple[str, ...],
    *,
    batch_id: str,
) -> None:
    overrides = _candidate_overrides(table, batch_id=batch_id, row=row)
    values = dict(row)
    insert_columns = [
        name
        for name in candidate_columns
        if name != "id" and (name in source_columns or name in overrides)
    ]
    payload = [overrides.get(name, values.get(name)) for name in insert_columns]
    placeholders = ", ".join("?" for _ in insert_columns)
    connection.execute(
        f"INSERT INTO {_quote(table)} ({', '.join(_quote(name) for name in insert_columns)}) "
        f"VALUES ({placeholders})",
        payload,
    )


def _clear_candidate_database(connection: sqlite3.Connection) -> None:
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name DESC"
        )
    ]
    connection.execute("PRAGMA foreign_keys=OFF")
    for table in tables:
        connection.execute(f"DELETE FROM {_quote(table)}")
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone():
        connection.execute("DELETE FROM sqlite_sequence")


def _candidate_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])
        for table in (*_COPIED_TABLES, *_EXCLUDED_TABLES)
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    }


def build_snapshot_recovery_candidate(
    snapshot_path: Path | str,
    schema_path: Path | str,
    candidate_path: Path | str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Create a current-schema, review-only candidate DB or return a dry-run manifest."""
    snapshot = _resolve_existing_database(snapshot_path)
    schema = _resolve_existing_database(schema_path)
    candidate = _resolve_candidate_path(candidate_path)
    if snapshot == schema:
        raise ValueError("snapshot_and_schema_must_differ")
    _validate_candidate_path(snapshot, schema, candidate, apply=apply)

    source_sha256 = _file_sha256(snapshot)
    schema_sha256_before = _file_sha256(schema)
    batch_id = f"snapshot-recovery-{source_sha256[:16]}"
    source = _read_only_connection(snapshot)
    schema_connection = _read_only_connection(schema)
    candidate_created = False
    candidate_sha256 = ""
    candidate_counts: dict[str, int] = {table: 0 for table in (*_COPIED_TABLES, *_EXCLUDED_TABLES)}
    try:
        source_columns = _require_columns(source, _REQUIRED_SOURCE_COLUMNS)
        candidate_columns = _require_columns(schema_connection, _REQUIRED_CANDIDATE_COLUMNS)
        product_rows, entry_rows = _select_eligible_rows(source)
    finally:
        schema_connection.close()
        source.close()

    if apply:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".snapshot-recovery-", dir=candidate.parent) as temporary_dir:
            temporary_candidate = Path(temporary_dir) / candidate.name
            backup_sqlite_database(schema, temporary_candidate)
            candidate_connection = sqlite3.connect(temporary_candidate)
            candidate_connection.row_factory = sqlite3.Row
            try:
                candidate_connection.execute("BEGIN IMMEDIATE")
                _clear_candidate_database(candidate_connection)
                for row in product_rows:
                    _insert_row(
                        candidate_connection,
                        "kb_product",
                        row,
                        source_columns["kb_product"],
                        candidate_columns["kb_product"],
                        batch_id=batch_id,
                    )
                for row in entry_rows:
                    _insert_row(
                        candidate_connection,
                        "knowledge_entries",
                        row,
                        source_columns["knowledge_entries"],
                        candidate_columns["knowledge_entries"],
                        batch_id=batch_id,
                    )
                candidate_counts = _candidate_table_counts(candidate_connection)
                candidate_connection.commit()
            finally:
                candidate_connection.close()
            if candidate.exists():
                raise ValueError("candidate_path_not_isolated")
            try:
                os.link(temporary_candidate, candidate)
            except FileExistsError as exc:
                raise ValueError("candidate_path_not_isolated") from exc
            candidate_created = True
            candidate_sha256 = _file_sha256(candidate)

    schema_sha256_after = _file_sha256(schema)
    if schema_sha256_before != schema_sha256_after:
        raise RuntimeError("formal_schema_database_changed")

    return {
        "report_schema_version": "knowledge-snapshot-recovery-candidate/v1",
        "source": {
            "database_basename": snapshot.name,
            "database_sha256": source_sha256,
            "query_only_verified": True,
        },
        "schema_seed": {
            "database_basename": schema.name,
            "database_sha256": schema_sha256_before,
            "query_only_verified": True,
        },
        "candidate": {
            "database_basename": candidate.name,
            "candidate_created": candidate_created,
            "database_sha256": candidate_sha256,
            "import_batch_id": batch_id,
        },
        "selection": {
            "identity_contract": "knowledge_entries.product_id_exactly_equals_kb_product.i_id",
            "source_review_contract": "product_and_fact_status_published_fact_scope_product",
            "eligible_product_count": len(product_rows),
            "eligible_fact_count": len(entry_rows),
        },
        "candidate_review_contract": {
            "product_status": "pending_review",
            "fact_status": "pending_review",
            "fact_review_status": "needs_human_review",
            "auto_reply_allowed": False,
            "human_review_required": True,
            "index_status": "pending",
            "formal_evidence_admission_allowed": False,
        },
        "copy_counts": candidate_counts,
        "candidate_created": candidate_created,
        "direct_database_copy_allowed": False,
        "formal_evidence_admission_allowed": False,
        "formal_schema_sha256_before": schema_sha256_before,
        "formal_schema_sha256_after": schema_sha256_after,
        "formal_knowledge_write_attempt_count": 0,
        "can_change_can_send_count": 0,
        "recommended_next_step": "current_governance_review_of_isolated_candidate",
    }


def write_json_report(path: Path | str, report: dict[str, Any]) -> None:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a review-only candidate DB from historical knowledge snapshots."
    )
    parser.add_argument("--snapshot-db", required=True)
    parser.add_argument("--schema-db", required=True)
    parser.add_argument("--candidate-db", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-output", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_snapshot_recovery_candidate(
        args.snapshot_db,
        args.schema_db,
        args.candidate_db,
        apply=bool(args.apply),
    )
    if args.json_output:
        write_json_report(args.json_output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
