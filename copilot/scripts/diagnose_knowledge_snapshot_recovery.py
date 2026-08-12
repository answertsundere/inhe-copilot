"""Assess a historical knowledge snapshot without importing or exposing its contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


_SENSITIVE_PATTERNS = {
    "phone_like": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "email_like": re.compile(r"(?<![\w.-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    "url_with_query": re.compile(r"https?://[^\s\"\\]+\?[^\s\"\\]+", re.IGNORECASE),
    "long_numeric_identifier_like": re.compile(r"(?<!\d)\d{12,}(?!\d)"),
}

_SENSITIVE_SCAN_COLUMNS = {
    "kb_product": ("product_name", "brand", "specs_json", "logistics_json", "warranty_json"),
    "kb_qa": ("question", "answer", "keywords_json"),
    "knowledge_entries": ("title", "content", "condition_text", "forbidden_usage", "search_keywords"),
    "knowledge_chunks": ("chunk_text", "search_keywords"),
    "kb_media_asset": ("asset_title", "asset_url", "source_doc_id", "source_raw_json"),
    "agent_answer_memory": ("customer_question_pattern", "approved_answer", "reference_reply", "metadata_json"),
    "kb_change_log": ("snapshot_json", "change_reason", "changed_fields_json"),
}

_SCHEMA_TABLES = (
    "kb_product",
    "kb_qa",
    "knowledge_entries",
    "knowledge_chunks",
    "kb_media_asset",
    "agent_answer_memory",
    "kb_change_log",
)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _resolve_database(path: Path | str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise ValueError("database_file_not_found")
    return candidate


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    if int(connection.execute("PRAGMA query_only").fetchone()[0] or 0) != 1:
        connection.close()
        raise RuntimeError("sqlite_query_only_not_enforced")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    return {
        str(row[1]): {
            "type": str(row[2] or ""),
            "notnull": bool(row[3]),
            "default": row[4],
            "pk": bool(row[5]),
        }
        for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
    }


def _has_columns(connection: sqlite3.Connection, table: str, columns: Iterable[str]) -> bool:
    if table not in _table_names(connection):
        return False
    available = _columns(connection, table)
    return all(column in available for column in columns)


def _count(connection: sqlite3.Connection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0] or 0)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_compatibility(
    snapshot: sqlite3.Connection,
    target: sqlite3.Connection,
) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    snapshot_tables = _table_names(snapshot)
    target_tables = _table_names(target)
    for table in _SCHEMA_TABLES:
        if table not in snapshot_tables and table not in target_tables:
            continue
        snapshot_columns = _columns(snapshot, table) if table in snapshot_tables else {}
        target_columns = _columns(target, table) if table in target_tables else {}
        common = set(snapshot_columns) & set(target_columns)
        result[table] = {
            "target_only_columns": sorted(set(target_columns) - set(snapshot_columns)),
            "snapshot_only_columns": sorted(set(snapshot_columns) - set(target_columns)),
            "same_named_definition_differences": sorted(
                name
                for name in common
                if snapshot_columns[name] != target_columns[name]
            ),
        }
    return result


def _candidate_counts(connection: sqlite3.Connection) -> dict[str, int]:
    result = {
        "published_products": 0,
        "published_products_with_sku_identity": 0,
        "reviewed_product_facts": 0,
        "reviewed_product_facts_identity_matched": 0,
        "unreviewed_or_ineligible_product_facts": 0,
        "reviewed_product_facts_missing_content_hash": 0,
        "media_strict_identity_matched": 0,
        "media_identity_mismatch_or_missing": 0,
        "published_low_or_medium_risk_qa": 0,
        "published_high_risk_qa": 0,
    }
    if _has_columns(connection, "kb_product", ("status",)):
        result["published_products"] = _count(
            connection, "SELECT COUNT(*) FROM kb_product WHERE status='published'"
        )
    if _has_columns(connection, "kb_product", ("status", "sku_list_json")):
        result["published_products_with_sku_identity"] = _count(
            connection,
            "SELECT COUNT(*) FROM kb_product "
            "WHERE status='published' "
            "AND sku_list_json IS NOT NULL "
            "AND TRIM(sku_list_json) NOT IN ('', '[]', '{}')",
        )

    entry_columns = (
        "status", "fact_review_status", "fact_scope", "product_id",
    )
    if _has_columns(connection, "knowledge_entries", entry_columns):
        result["reviewed_product_facts"] = _count(
            connection,
            "SELECT COUNT(*) FROM knowledge_entries "
            "WHERE status='published' "
            "AND fact_review_status='published' "
            "AND fact_scope='product'",
        )
        result["unreviewed_or_ineligible_product_facts"] = _count(
            connection,
            "SELECT COUNT(*) FROM knowledge_entries "
            "WHERE fact_scope='product' "
            "AND NOT (status='published' AND fact_review_status='published')",
        )
        if _has_columns(connection, "kb_product", ("i_id", "status")):
            result["reviewed_product_facts_identity_matched"] = _count(
                connection,
                "SELECT COUNT(*) FROM knowledge_entries entry "
                "JOIN kb_product product ON CAST(entry.product_id AS TEXT)=CAST(product.i_id AS TEXT) "
                "WHERE entry.status='published' "
                "AND entry.fact_review_status='published' "
                "AND entry.fact_scope='product' "
                "AND product.status='published'",
            )
        if _has_columns(connection, "knowledge_entries", ("content_hash",)):
            result["reviewed_product_facts_missing_content_hash"] = _count(
                connection,
                "SELECT COUNT(*) FROM knowledge_entries "
                "WHERE status='published' "
                "AND fact_review_status='published' "
                "AND fact_scope='product' "
                "AND (content_hash IS NULL OR LENGTH(TRIM(content_hash)) <> 64)",
            )

    media_columns = (
        "product_id", "i_id", "status", "audit_status", "usable_for_agent", "refresh_status",
    )
    if _has_columns(connection, "kb_media_asset", media_columns) and _has_columns(
        connection, "kb_product", ("id", "i_id", "status")
    ):
        result["media_strict_identity_matched"] = _count(
            connection,
            "SELECT COUNT(*) FROM kb_media_asset media "
            "JOIN kb_product product "
            "ON media.product_id=product.id AND media.i_id=product.i_id "
            "WHERE media.status='approved' "
            "AND media.audit_status='reviewed' "
            "AND media.usable_for_agent=1 "
            "AND media.refresh_status='ok' "
            "AND product.status='published'",
        )
        result["media_identity_mismatch_or_missing"] = _count(
            connection,
            "SELECT COUNT(*) FROM kb_media_asset media "
            "LEFT JOIN kb_product product "
            "ON media.product_id=product.id AND media.i_id=product.i_id "
            "WHERE media.status='approved' AND product.id IS NULL",
        )

    if _has_columns(connection, "kb_qa", ("status", "risk_level")):
        result["published_low_or_medium_risk_qa"] = _count(
            connection,
            "SELECT COUNT(*) FROM kb_qa "
            "WHERE status='published' AND risk_level IN ('low', 'medium')",
        )
        result["published_high_risk_qa"] = _count(
            connection,
            "SELECT COUNT(*) FROM kb_qa "
            "WHERE status='published' AND risk_level='high'",
        )
    return result


def _safe_distribution(
    connection: sqlite3.Connection,
    table: str,
    columns: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    if table not in _table_names(connection):
        return {}
    available = _columns(connection, table)
    result: dict[str, list[dict[str, Any]]] = {}
    for column in columns:
        if column not in available:
            continue
        rows = connection.execute(
            "SELECT COALESCE(NULLIF(TRIM(CAST(" + _quote(column) + " AS TEXT)), ''), '<empty>'), COUNT(*) "
            "FROM " + _quote(table) + " GROUP BY 1 ORDER BY 2 DESC, 1"
        ).fetchall()
        result[column] = [
            {"value": str(value), "count": int(count)}
            for value, count in rows
        ]
    return result


def _candidate_distributions(connection: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if _has_columns(
        connection,
        "knowledge_entries",
        ("status", "fact_review_status", "fact_scope", "fact_type", "risk_level"),
    ):
        rows = connection.execute(
            "SELECT fact_type, risk_level, human_review_required, auto_reply_allowed, COUNT(*) "
            "FROM knowledge_entries "
            "WHERE status='published' AND fact_review_status='published' AND fact_scope='product' "
            "GROUP BY fact_type, risk_level, human_review_required, auto_reply_allowed "
            "ORDER BY fact_type, risk_level, human_review_required, auto_reply_allowed"
        ).fetchall()
        result["reviewed_product_fact_policy_distribution"] = [
            {
                "fact_type": str(fact_type or "<empty>"),
                "risk_level": str(risk_level or "<empty>"),
                "human_review_required": bool(human_review_required),
                "auto_reply_allowed": bool(auto_reply_allowed),
                "count": int(count),
            }
            for fact_type, risk_level, human_review_required, auto_reply_allowed, count in rows
        ]
    return result


def _sensitive_pattern_counts(connection: sqlite3.Connection) -> dict[str, dict[str, dict[str, int]]]:
    result: dict[str, dict[str, dict[str, int]]] = {}
    tables = _table_names(connection)
    for table, requested_columns in _SENSITIVE_SCAN_COLUMNS.items():
        if table not in tables:
            continue
        available = _columns(connection, table)
        per_table: dict[str, dict[str, int]] = {}
        for column in requested_columns:
            if column not in available:
                continue
            counts = {name: 0 for name in _SENSITIVE_PATTERNS}
            for (raw_value,) in connection.execute(
                "SELECT " + _quote(column) + " FROM " + _quote(table) + " "
                "WHERE " + _quote(column) + " IS NOT NULL AND " + _quote(column) + " <> ''"
            ):
                value = str(raw_value)
                for name, pattern in _SENSITIVE_PATTERNS.items():
                    counts[name] += len(pattern.findall(value))
            if any(counts.values()):
                per_table[column] = counts
        if per_table:
            result[table] = per_table
    return result


def build_snapshot_recovery_report(
    snapshot_path: Path | str,
    target_path: Path | str,
) -> dict[str, Any]:
    """Return a structural recovery assessment without copying source rows."""
    snapshot = _resolve_database(snapshot_path)
    target = _resolve_database(target_path)
    if snapshot == target:
        raise ValueError("snapshot_and_target_must_differ")

    source_connection = _read_only_connection(snapshot)
    target_connection = _read_only_connection(target)
    try:
        candidates = _candidate_counts(source_connection)
        sensitive = _sensitive_pattern_counts(source_connection)
        decision_reasons = [
            "historical_snapshot_requires_separate_candidate_database",
            "historical_review_status_requires_current_governance_confirmation",
        ]
        if candidates["reviewed_product_facts_missing_content_hash"]:
            decision_reasons.append("reviewed_product_fact_content_hash_missing")
        if candidates["media_identity_mismatch_or_missing"]:
            decision_reasons.append("approved_media_identity_mismatch_or_missing")
        if sensitive:
            decision_reasons.append("potential_sensitive_content_requires_manual_review")
        return {
            "report_schema_version": "knowledge-snapshot-recovery-audit/v1",
            "source": {
                "database_basename": snapshot.name,
                "database_sha256": _file_sha256(snapshot),
                "integrity_check": str(source_connection.execute("PRAGMA integrity_check").fetchone()[0]),
                "query_only_verified": True,
                "table_count": len(_table_names(source_connection)),
            },
            "target": {
                "database_basename": target.name,
                "integrity_check": str(target_connection.execute("PRAGMA integrity_check").fetchone()[0]),
                "query_only_verified": True,
                "table_count": len(_table_names(target_connection)),
            },
            "schema_compatibility": _schema_compatibility(source_connection, target_connection),
            "candidate_counts": candidates,
            "candidate_distributions": _candidate_distributions(source_connection),
            "source_status_distributions": {
                "knowledge_entries": _safe_distribution(
                    source_connection,
                    "knowledge_entries",
                    ("status", "fact_review_status", "fact_scope", "index_status"),
                ),
                "kb_media_asset": _safe_distribution(
                    source_connection,
                    "kb_media_asset",
                    ("status", "audit_status", "usable_for_agent", "refresh_status"),
                ),
            },
            "potential_sensitive_pattern_counts": sensitive,
            "recovery_decision": {
                "direct_database_copy_allowed": False,
                "formal_evidence_admission_allowed": False,
                "recommended_next_step": "staged_candidate_import_with_current_review_governance",
                "reason_codes": decision_reasons,
            },
        }
    finally:
        target_connection.close()
        source_connection.close()


def write_json_report(path: Path | str, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only recovery audit for a historical knowledge SQLite snapshot."
    )
    parser.add_argument("--snapshot-db", required=True)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--json-output", default="")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_snapshot_recovery_report(args.snapshot_db, args.target_db)
    if args.json_output:
        write_json_report(args.json_output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
