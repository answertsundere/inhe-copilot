"""PgVector shadow retriever utilities.

This module is intentionally not wired into the production retriever factory.
It exists for shadow comparison only: initialize a pgvector table, sync existing
published chunk embeddings, and query it with the same product/fact metadata
contract used by the current RAG path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

VECTOR_DIMENSION = 1024
DEFAULT_COLLECTION = "kb_chunk_embeddings_pg"


class PgVectorConfigError(RuntimeError):
    """Raised when the local pgvector environment is not configured."""


def mask_dsn(dsn: str) -> str:
    """Mask DSN passwords before logging or returning diagnostics."""
    if not dsn:
        return ""
    try:
        parts = urlsplit(dsn)
        if not parts.password:
            return dsn
        username = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{username}:***@{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return re.sub(r"://([^:/@\s]+):([^@\s]+)@", r"://\1:***@", dsn)


def pgvector_config_from_env(env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    dsn = str(env.get("COPILOT_PGVECTOR_DSN") or "").strip()
    collection = str(env.get("COPILOT_PGVECTOR_COLLECTION") or DEFAULT_COLLECTION).strip() or DEFAULT_COLLECTION
    return {
        "enabled": str(env.get("COPILOT_PGVECTOR_ENABLED") or "false").strip().lower() in {"1", "true", "yes", "on"},
        "dsn_configured": bool(dsn),
        "dsn_masked": mask_dsn(dsn),
        "collection": collection,
        "retriever_backend": str(env.get("COPILOT_RETRIEVER_BACKEND") or "current_sqlite"),
        "shadow_backend": str(env.get("COPILOT_RETRIEVER_SHADOW_BACKEND") or "pgvector"),
    }


def _safe_identifier(name: str) -> str:
    name = str(name or "").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise ValueError(f"unsafe PostgreSQL identifier: {name!r}")
    return name


def _json_load(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        loaded = _json_load(value, None)
        if isinstance(loaded, list):
            value = loaded
        else:
            return [value.strip()] if value.strip() else []
    if isinstance(value, (set, tuple)):
        value = list(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _bool_with_default(value: Any, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def build_schema_sql(collection: str = DEFAULT_COLLECTION) -> list[str]:
    table = _safe_identifier(collection)
    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        f"""
CREATE TABLE IF NOT EXISTS {table} (
    id bigserial PRIMARY KEY,
    source_chunk_id text NOT NULL UNIQUE,
    entry_id integer,
    chunk_text text NOT NULL,
    embedding vector({VECTOR_DIMENSION}) NOT NULL,
    i_id text NOT NULL DEFAULT '',
    sku_code text NOT NULL DEFAULT '',
    product_title text NOT NULL DEFAULT '',
    query_fact_type text NOT NULL DEFAULT '',
    source_type text NOT NULL DEFAULT '',
    evidence_role text NOT NULL DEFAULT '',
    media_role text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'published',
    usable_for_agent boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    content_hash text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)""".strip(),
        f"CREATE INDEX IF NOT EXISTS idx_{table}_embedding_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_iid ON {table} (i_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_sku ON {table} (sku_code)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_fact ON {table} (query_fact_type)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_source ON {table} (source_type)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_role ON {table} (evidence_role)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_status ON {table} (status)",
        f"CREATE INDEX IF NOT EXISTS idx_{table}_metadata ON {table} USING gin (metadata)",
    ]


UPSERT_COLUMNS = (
    "source_chunk_id",
    "entry_id",
    "chunk_text",
    "embedding",
    "i_id",
    "sku_code",
    "product_title",
    "query_fact_type",
    "source_type",
    "evidence_role",
    "media_role",
    "status",
    "usable_for_agent",
    "metadata",
    "content_hash",
    "updated_at",
)


def build_upsert_sql(collection: str = DEFAULT_COLLECTION) -> str:
    table = _safe_identifier(collection)
    columns = ", ".join(UPSERT_COLUMNS)
    placeholders = ", ".join([f"%({name})s" if name != "embedding" else "%(embedding)s::vector" for name in UPSERT_COLUMNS])
    updates = ", ".join([f"{name} = EXCLUDED.{name}" for name in UPSERT_COLUMNS if name != "source_chunk_id"])
    return f"""
INSERT INTO {table} ({columns})
VALUES ({placeholders})
ON CONFLICT (source_chunk_id) DO UPDATE SET {updates}
""".strip()


def build_retrieve_sql(
    *,
    collection: str = DEFAULT_COLLECTION,
    i_id: str = "",
    sku_code: str = "",
    query_fact_type: str = "",
    allowed_source_types: list[str] | None = None,
    allowed_evidence_roles: list[str] | None = None,
    top_k: int = 5,
) -> tuple[str, dict[str, Any]]:
    table = _safe_identifier(collection)
    where = ["status = 'published'", "usable_for_agent = true"]
    params: dict[str, Any] = {
        "query_embedding": "",
        "top_k": max(1, min(int(top_k or 5), 50)),
    }
    if i_id:
        where.append("i_id = %(i_id)s")
        params["i_id"] = i_id
    if sku_code:
        where.append("sku_code = %(sku_code)s")
        params["sku_code"] = sku_code
    if query_fact_type:
        where.append("query_fact_type = %(query_fact_type)s")
        params["query_fact_type"] = query_fact_type
    if allowed_source_types:
        where.append("source_type = ANY(%(allowed_source_types)s)")
        params["allowed_source_types"] = allowed_source_types
    if allowed_evidence_roles:
        where.append("evidence_role = ANY(%(allowed_evidence_roles)s)")
        params["allowed_evidence_roles"] = allowed_evidence_roles
    sql = f"""
SELECT
    source_chunk_id,
    entry_id,
    chunk_text,
    i_id,
    sku_code,
    product_title,
    query_fact_type,
    source_type,
    evidence_role,
    media_role,
    status,
    usable_for_agent,
    metadata,
    content_hash,
    1 - (embedding <=> %(query_embedding)s::vector) AS vector_score
FROM {table}
WHERE {' AND '.join(where)}
ORDER BY embedding <=> %(query_embedding)s::vector
LIMIT %(top_k)s
""".strip()
    return sql, params


def build_fetch_by_source_ids_sql(collection: str = DEFAULT_COLLECTION) -> str:
    table = _safe_identifier(collection)
    return f"""
SELECT
    source_chunk_id,
    entry_id,
    chunk_text,
    i_id,
    sku_code,
    product_title,
    query_fact_type,
    source_type,
    evidence_role,
    media_role,
    status,
    usable_for_agent,
    metadata,
    content_hash
FROM {table}
WHERE source_chunk_id = ANY(%(source_chunk_ids)s)
""".strip()


def validate_embedding(value: Any, dimension: int = VECTOR_DIMENSION) -> list[float] | None:
    embedding = _json_load(value, value)
    if not isinstance(embedding, list) or len(embedding) != dimension:
        return None
    try:
        return [float(item) for item in embedding]
    except Exception:
        return None


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{float(item):.8g}" for item in embedding) + "]"


def chunk_to_pg_row(chunk: Any) -> tuple[dict[str, Any] | None, str]:
    embedding = validate_embedding(getattr(chunk, "embedding_json", None))
    if embedding is None:
        raw = _json_load(getattr(chunk, "embedding_json", None), None)
        if raw is None:
            return None, "no_embedding"
        return None, "bad_dimension"

    entry = getattr(chunk, "entry", None)
    metadata = chunk.get_metadata() if hasattr(chunk, "get_metadata") else _json_load(getattr(chunk, "metadata_json", None), {})
    entry_product_scope = entry.get_product_scope() if entry and hasattr(entry, "get_product_scope") else []
    entry_sku_scope = entry.get_sku_scope() if entry and hasattr(entry, "get_sku_scope") else []
    product_scope = _as_list(getattr(chunk, "product_scope_json", None)) or entry_product_scope
    sku_scope = _as_list(getattr(chunk, "sku_scope_json", None)) or entry_sku_scope
    source_type = _first_text(getattr(chunk, "source_type", ""), getattr(entry, "source_type", ""))
    query_fact_type = _first_text(
        metadata.get("query_fact_type"),
        metadata.get("fact_type"),
        getattr(entry, "fact_type", ""),
        getattr(chunk, "intent", ""),
    )
    evidence_role = _first_text(metadata.get("evidence_role"), metadata.get("role"), query_fact_type)
    media_role = _first_text(metadata.get("media_role"), metadata.get("asset_type"))
    source_chunk_id = str(getattr(chunk, "id", ""))
    chunk_text = str(getattr(chunk, "chunk_text", "") or "")
    content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
    status = _first_text(getattr(entry, "status", ""), "published")
    auto_reply_allowed = _bool_with_default(getattr(entry, "auto_reply_allowed", None), True)
    human_review_required = _bool_with_default(getattr(entry, "human_review_required", None), False)
    row = {
        "source_chunk_id": source_chunk_id,
        "entry_id": int(getattr(chunk, "entry_id", 0) or 0),
        "chunk_text": chunk_text,
        "embedding": vector_literal(embedding),
        "i_id": _first_text(metadata.get("i_id"), getattr(entry, "product_id", ""), product_scope[0] if product_scope else ""),
        "sku_code": _first_text(metadata.get("sku_code"), getattr(entry, "sku_id", ""), sku_scope[0] if sku_scope else ""),
        "product_title": _first_text(metadata.get("product_title"), getattr(entry, "title", ""), product_scope[0] if product_scope else ""),
        "query_fact_type": query_fact_type,
        "source_type": source_type,
        "evidence_role": evidence_role,
        "media_role": media_role,
        "status": status,
        "usable_for_agent": status == "published" and auto_reply_allowed and not human_review_required,
        "metadata": json.dumps(metadata, ensure_ascii=False),
        "content_hash": content_hash,
        "updated_at": datetime.now(timezone.utc),
    }
    return row, ""


def _connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:  # pragma: no cover - depends on local env
        raise PgVectorConfigError("psycopg_missing") from exc
    return psycopg.connect(dsn, row_factory=dict_row)


@dataclass
class PgVectorRetrieverService:
    dsn: str = ""
    collection: str = DEFAULT_COLLECTION
    connect_factory: Callable[[str], Any] | None = None

    def __post_init__(self) -> None:
        self.dsn = self.dsn or str(os.environ.get("COPILOT_PGVECTOR_DSN") or "")
        self.collection = self.collection or str(os.environ.get("COPILOT_PGVECTOR_COLLECTION") or DEFAULT_COLLECTION)
        self.connect_factory = self.connect_factory or _connect

    def check(self) -> dict[str, Any]:
        result = {
            "pgvector_available": False,
            "dsn_configured": bool(self.dsn),
            "dsn_masked": mask_dsn(self.dsn),
            "extension_available": False,
            "error": "",
        }
        if not self.dsn:
            result["error"] = "missing_dsn"
            return result
        try:
            with self.connect_factory(self.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                    result["extension_available"] = bool(cur.fetchone())
            result["pgvector_available"] = bool(result["extension_available"])
            return result
        except Exception as exc:
            result["error"] = type(exc).__name__
            return result

    def init_schema(self, *, apply: bool = False) -> dict[str, Any]:
        statements = build_schema_sql(self.collection)
        if not apply:
            return {"dry_run": True, "statement_count": len(statements), "statements": statements}
        if not self.dsn:
            return {"dry_run": False, "applied": False, "error": "missing_dsn"}
        with self.connect_factory(self.dsn) as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
            conn.commit()
        return {"dry_run": False, "applied": True, "statement_count": len(statements)}

    def retrieve(
        self,
        *,
        query_text: str,
        query_embedding: list[float],
        i_id: str = "",
        sku_code: str = "",
        query_fact_type: str = "",
        allowed_source_types: list[str] | None = None,
        allowed_evidence_roles: list[str] | None = None,
        top_k: int = 5,
        allow_broad_search: bool = False,
    ) -> list[dict[str, Any]]:
        embedding = validate_embedding(query_embedding)
        if embedding is None:
            return []
        if not allow_broad_search and not (i_id or sku_code or query_fact_type or allowed_source_types or allowed_evidence_roles):
            return []
        if not self.dsn:
            return []
        sql, params = build_retrieve_sql(
            collection=self.collection,
            i_id=i_id,
            sku_code=sku_code,
            query_fact_type=query_fact_type,
            allowed_source_types=allowed_source_types,
            allowed_evidence_roles=allowed_evidence_roles,
            top_k=top_k,
        )
        params["query_embedding"] = vector_literal(embedding)
        started = time.perf_counter()
        with self.connect_factory(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return [self._row_to_candidate(row, latency_ms=latency_ms, query_text=query_text) for row in rows]

    def fetch_rows_by_source_ids(self, source_chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = [str(item).strip() for item in source_chunk_ids if str(item).strip()]
        if not ids or not self.dsn:
            return {}
        sql = build_fetch_by_source_ids_sql(self.collection)
        with self.connect_factory(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"source_chunk_ids": ids})
                rows = cur.fetchall()
        return {str(row.get("source_chunk_id")): dict(row) for row in rows}

    @staticmethod
    def _row_to_candidate(row: dict[str, Any], *, latency_ms: float, query_text: str) -> dict[str, Any]:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = _json_load(metadata, {})
        score = float(row.get("vector_score") or 0.0)
        return {
            "score": round(score, 4),
            "vector_score": round(score, 4),
            "text_score": 0.0,
            "scope_score": 0.0,
            "rerank_score": round(score, 4),
            "chunk_id": f"pgvector:{row.get('source_chunk_id')}",
            "entry_id": row.get("entry_id"),
            "title": row.get("product_title") or "",
            "chunk_text": row.get("chunk_text") or "",
            "source_type": row.get("source_type") or "",
            "fact_type": row.get("query_fact_type") or "",
            "evidence_role": row.get("evidence_role") or "",
            "media_role": row.get("media_role") or "",
            "entry_status": row.get("status") or "",
            "metadata": metadata,
            "product_scope": [row.get("product_title")] if row.get("product_title") else [],
            "sku_scope": [row.get("sku_code")] if row.get("sku_code") else [],
            "retrieval_backend": "pgvector_shadow",
            "latency_ms": latency_ms,
            "query_text_preview": query_text[:80],
        }


def sync_chunks_to_pgvector(
    chunks: Iterable[Any],
    *,
    pg_service: PgVectorRetrieverService,
    apply: bool = False,
    batch_size: int = 500,
) -> dict[str, Any]:
    result = {
        "dry_run": not apply,
        "scanned_count": 0,
        "synced_count": 0,
        "skipped_no_embedding": 0,
        "skipped_bad_dimension": 0,
        "failed_count": 0,
    }
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        result["scanned_count"] += 1
        row, reason = chunk_to_pg_row(chunk)
        if reason == "no_embedding":
            result["skipped_no_embedding"] += 1
            continue
        if reason == "bad_dimension":
            result["skipped_bad_dimension"] += 1
            continue
        if row is None:
            result["failed_count"] += 1
            continue
        rows.append(row)

    if not apply:
        result["synced_count"] = len(rows)
        return result
    if not pg_service.dsn:
        result["failed_count"] += len(rows)
        result["error"] = "missing_dsn"
        return result
    sql = build_upsert_sql(pg_service.collection)
    batch_size = max(1, int(batch_size or 500))
    with pg_service.connect_factory(pg_service.dsn) as conn:
        with conn.cursor() as cur:
            for index, row in enumerate(rows, start=1):
                cur.execute("SAVEPOINT sync_row")
                try:
                    cur.execute(sql, row)
                    cur.execute("RELEASE SAVEPOINT sync_row")
                    result["synced_count"] += 1
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sync_row")
                    cur.execute("RELEASE SAVEPOINT sync_row")
                    result["failed_count"] += 1
                    continue
                if index % batch_size == 0:
                    conn.commit()
            conn.commit()
    return result


def sync_pg_rows_to_pgvector(
    rows: Iterable[dict[str, Any]],
    *,
    pg_service: PgVectorRetrieverService,
    batch_size: int = 500,
) -> dict[str, Any]:
    result = {
        "dry_run": False,
        "scanned_count": 0,
        "synced_count": 0,
        "failed_count": 0,
    }
    prepared = [row for row in rows if row]
    result["scanned_count"] = len(prepared)
    if not prepared:
        return result
    if not pg_service.dsn:
        result["failed_count"] = len(prepared)
        result["error"] = "missing_dsn"
        return result
    sql = build_upsert_sql(pg_service.collection)
    batch_size = max(1, int(batch_size or 500))
    with pg_service.connect_factory(pg_service.dsn) as conn:
        with conn.cursor() as cur:
            for index, row in enumerate(prepared, start=1):
                cur.execute("SAVEPOINT sync_row")
                try:
                    cur.execute(sql, row)
                    cur.execute("RELEASE SAVEPOINT sync_row")
                    result["synced_count"] += 1
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sync_row")
                    cur.execute("RELEASE SAVEPOINT sync_row")
                    result["failed_count"] += 1
                    continue
                if index % batch_size == 0:
                    conn.commit()
            conn.commit()
    return result
