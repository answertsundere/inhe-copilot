"""Read-only guards and privacy-safe diagnostics for the formal knowledge DB."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import event


FORMAL_KNOWLEDGE_TABLES = (
    "kb_product",
    "kb_qa",
    "knowledge_entries",
    "knowledge_chunks",
)
_DML_PATTERN = re.compile(
    r"^\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO|CREATE\s+(?:TABLE|INDEX)|ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX))\s+([^\s(;,]+)",
    re.IGNORECASE,
)
_DATETIME_NAME_PATTERN = re.compile(r"(?:^|_)(?:created|updated|published|reviewed|expires|timestamp|time|date)(?:_|$)")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalise_decimal(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    normalised = number.normalize()
    text = format(normalised, "f")
    return "0" if text in {"-0", "-0.0"} else text


def _normalise_datetime(value: str) -> str:
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    rendered = parsed.isoformat(timespec="microseconds")
    return rendered.replace("+00:00", "Z")


def _normalise_value(column_name: str, declared_type: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bytes):
        return {"type": "blob", "sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}

    type_name = str(declared_type or "").upper()
    if isinstance(value, (int, float)) or any(token in type_name for token in ("INT", "REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL")):
        return {"type": "number", "value": _normalise_decimal(value)}

    text = unicodedata.normalize("NFC", str(value))
    if column_name.lower().endswith("_json"):
        try:
            return {"type": "json", "value": json.loads(text)}
        except (TypeError, ValueError):
            pass
    if "DATE" in type_name or "TIME" in type_name or _DATETIME_NAME_PATTERN.search(column_name.lower()):
        return {"type": "datetime", "value": _normalise_datetime(text)}
    return {"type": "text", "value": text}


def backup_sqlite_database(source: Path | str, destination: Path | str) -> None:
    """Create one transaction-consistent copy through SQLite's backup API."""
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path == destination_path:
        raise ValueError("backup_source_equals_destination")
    if destination_path.exists():
        raise FileExistsError(str(destination_path))
    source_connection = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination_path)
    try:
        source_connection.execute("PRAGMA query_only=ON")
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def fingerprint_formal_knowledge_tables(
    database_path: Path | str,
    *,
    hmac_key: str,
    tables: Iterable[str] = FORMAL_KNOWLEDGE_TABLES,
) -> dict[str, Any]:
    """Return stable, row-level hashes without exposing formal knowledge values."""
    if not hmac_key:
        raise ValueError("formal_kb_audit_hmac_key_required")
    path = Path(database_path).resolve()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    result_tables: list[dict[str, Any]] = []
    composite_rows: list[dict[str, Any]] = []
    try:
        for table in tables:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                table_result = {
                    "table": table,
                    "exists": False,
                    "row_count": 0,
                    "schema_sha256": "",
                    "content_sha256": "",
                    "rows": [],
                }
                result_tables.append(table_result)
                composite_rows.append(table_result)
                continue

            columns = [dict(row) for row in connection.execute(f'PRAGMA table_info("{table}")')]
            schema_contract = [
                {
                    "cid": int(column["cid"]),
                    "name": str(column["name"]),
                    "type": str(column["type"] or ""),
                    "notnull": int(column["notnull"]),
                    "default_sha256": _hash(str(column["dflt_value"])) if column["dflt_value"] is not None else "",
                    "pk": int(column["pk"]),
                }
                for column in columns
            ]
            primary_keys = [
                str(column["name"])
                for column in sorted(columns, key=lambda item: int(item["pk"] or 0))
                if int(column["pk"] or 0) > 0
            ]
            if not primary_keys:
                raise ValueError(f"formal_table_primary_key_missing:{table}")
            names = [str(column["name"]) for column in columns]
            order_sql = ", ".join(f'"{name}"' for name in primary_keys)
            select_sql = ", ".join(f'"{name}"' for name in names)
            row_results: list[dict[str, Any]] = []
            for row in connection.execute(f'SELECT {select_sql} FROM "{table}" ORDER BY {order_sql}'):
                values = {
                    name: _normalise_value(name, str(columns[index]["type"] or ""), row[name])
                    for index, name in enumerate(names)
                }
                identity_contract = {name: values[name] for name in primary_keys}
                identity_hmac = hmac.new(
                    hmac_key.encode("utf-8"),
                    f"{table}\0{_canonical_json(identity_contract)}".encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                column_hashes = {name: _hash(values[name]) for name in names}
                row_results.append({
                    "row_identity_hmac": identity_hmac,
                    "row_sha256": _hash(column_hashes),
                    "column_sha256": column_hashes,
                })
            table_result = {
                "table": table,
                "exists": True,
                "row_count": len(row_results),
                "schema_sha256": _hash(schema_contract),
                "content_sha256": _hash([
                    [row["row_identity_hmac"], row["row_sha256"]] for row in row_results
                ]),
                "rows": row_results,
            }
            result_tables.append(table_result)
            composite_rows.append({key: table_result[key] for key in ("table", "exists", "row_count", "schema_sha256", "content_sha256")})
    finally:
        connection.close()
    return {
        "database_basename": path.name,
        "query_only": True,
        "formal_tables": result_tables,
        "formal_content_sha256": _hash(composite_rows),
    }


def compare_formal_knowledge_fingerprints(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Describe changed rows and columns using hashes only."""
    before_tables = {item["table"]: item for item in before.get("formal_tables") or []}
    after_tables = {item["table"]: item for item in after.get("formal_tables") or []}
    table_diffs: list[dict[str, Any]] = []
    changed_row_count = 0
    for table in sorted(set(before_tables) | set(after_tables)):
        old = before_tables.get(table, {})
        new = after_tables.get(table, {})
        old_rows = {row["row_identity_hmac"]: row for row in old.get("rows") or []}
        new_rows = {row["row_identity_hmac"]: row for row in new.get("rows") or []}
        changes: list[dict[str, Any]] = []
        for identity in sorted(set(old_rows) | set(new_rows)):
            old_row = old_rows.get(identity)
            new_row = new_rows.get(identity)
            if old_row and new_row and old_row.get("row_sha256") == new_row.get("row_sha256"):
                continue
            old_columns = (old_row or {}).get("column_sha256") or {}
            new_columns = (new_row or {}).get("column_sha256") or {}
            changed_columns = sorted(
                name for name in set(old_columns) | set(new_columns)
                if old_columns.get(name) != new_columns.get(name)
            )
            changes.append({
                "row_identity_hmac": identity,
                "change_type": "updated" if old_row and new_row else ("inserted" if new_row else "deleted"),
                "changed_column_names": changed_columns,
                "before_value_sha256": (old_row or {}).get("row_sha256", ""),
                "after_value_sha256": (new_row or {}).get("row_sha256", ""),
            })
        if changes or old.get("schema_sha256") != new.get("schema_sha256"):
            changed_row_count += len(changes)
            table_diffs.append({
                "table": table,
                "before_row_count": int(old.get("row_count") or 0),
                "after_row_count": int(new.get("row_count") or 0),
                "schema_changed": old.get("schema_sha256") != new.get("schema_sha256"),
                "changed_rows": changes,
            })
    return {
        "changed": bool(table_diffs),
        "changed_row_count": changed_row_count,
        "changed_table_count": len(table_diffs),
        "table_diffs": table_diffs,
    }


class DmlDiagnosticRecorder:
    """Record statement ownership without SQL parameters or business values."""

    def __init__(self, output_path: Path | str, *, logical_database: str, hmac_key: str):
        self.output_path = Path(output_path)
        self.logical_database = logical_database
        self.hmac_key = hmac_key
        self._lock = threading.Lock()

    def _correlation_uid(self) -> str:
        raw = "background"
        try:
            from flask import g, has_request_context, request

            if has_request_context():
                raw = str(getattr(g, "correlation_id", "") or request.headers.get("X-Correlation-ID") or "request")
        except Exception:
            pass
        return hmac.new(self.hmac_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _stack_summary() -> list[str]:
        summary: list[str] = []
        for frame in inspect.stack()[3:48]:
            path = Path(frame.filename)
            if "sqlalchemy" in {part.lower() for part in path.parts}:
                continue
            summary.append(f"{path.name}:{frame.function}")
            if len(summary) >= 6:
                break
        return summary

    def before_cursor_execute(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        match = _DML_PATTERN.match(str(statement or ""))
        if not match:
            return
        operation = match.group(1).split()[0].upper()
        table = match.group(2).strip('"`[]').split(".")[-1]
        stack = self._stack_summary()
        record = {
            "operation": operation,
            "logical_database": self.logical_database,
            "table": table,
            "correlation_uid": self._correlation_uid(),
            "thread": threading.current_thread().name,
            "task_kind": "request" if any("api" in item.lower() for item in stack) else "background_or_startup",
            "in_analyze_request": any("analyze" in item.lower() for item in stack),
            "stack_summary": stack,
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.output_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(record) + "\n")


def configure_knowledge_engine_guards(
    engine,
    *,
    query_only: bool,
    dml_diagnostic_path: str = "",
    hmac_key: str = "",
) -> DmlDiagnosticRecorder | None:
    """Apply connection-pool guards once to a SQLAlchemy engine."""
    if query_only and not getattr(engine, "_formal_kb_query_only_guard", False):
        @event.listens_for(engine, "connect")
        def _set_query_only(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA query_only=ON")
            finally:
                cursor.close()

        setattr(engine, "_formal_kb_query_only_guard", True)

    if not dml_diagnostic_path:
        return None
    if not hmac_key:
        raise ValueError("formal_kb_audit_hmac_key_required")
    existing = getattr(engine, "_formal_kb_dml_recorder", None)
    if existing is not None:
        return existing
    recorder = DmlDiagnosticRecorder(
        dml_diagnostic_path,
        logical_database="formal_knowledge",
        hmac_key=hmac_key,
    )
    event.listen(engine, "before_cursor_execute", recorder.before_cursor_execute)
    setattr(engine, "_formal_kb_dml_recorder", recorder)
    return recorder


def formal_kb_audit_hmac_key() -> str:
    return str(
        os.environ.get("COPILOT_FORMAL_KB_AUDIT_HMAC_KEY")
        or os.environ.get("COPILOT_GOLD_SET_HMAC_KEY")
        or ""
    )
