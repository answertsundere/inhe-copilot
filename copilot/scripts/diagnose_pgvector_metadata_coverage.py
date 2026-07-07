"""Diagnose pgvector shadow metadata coverage.

This is a read-only diagnostic script. It checks whether the pgvector shadow
table has enough product identity, fact type, source, evidence role, and media
metadata to support meaningful shadow retrieval comparisons.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBQA  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.pgvector_retriever_service import PgVectorRetrieverService, pgvector_config_from_env  # noqa: E402


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_collection(name: str) -> str:
    if not name.replace("_", "").isalnum() or not name:
        raise ValueError("unsafe_collection")
    return name


def _distribution(cur, table: str, field: str, limit: int = 20) -> dict[str, int]:
    cur.execute(
        f"""
SELECT COALESCE(NULLIF({field}, ''), '__empty__') AS value, COUNT(*) AS count
FROM {table}
GROUP BY value
ORDER BY count DESC, value ASC
LIMIT %(limit)s
""",
        {"limit": limit},
    )
    return {str(row["value"]): int(row["count"] or 0) for row in cur.fetchall()}


def _embedding_dimension_distribution(cur, table: str) -> dict[str, int]:
    cur.execute(
        f"""
SELECT COALESCE((metadata->>'embedding_dimension'), '1024') AS value, COUNT(*) AS count
FROM {table}
GROUP BY value
ORDER BY count DESC, value ASC
"""
    )
    return {str(row["value"]): int(row["count"] or 0) for row in cur.fetchall()}


def _pgvector_coverage(service: PgVectorRetrieverService) -> dict[str, Any]:
    check = service.check()
    result: dict[str, Any] = {
        "available": bool(check.get("pgvector_available")),
        "extension_available": bool(check.get("extension_available")),
        "error": check.get("error") or "",
    }
    if not check.get("pgvector_available"):
        return result

    table = _safe_collection(service.collection)
    with service.connect_factory(service.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
SELECT
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE i_id <> '') AS i_id_non_null_count,
    COUNT(*) FILTER (WHERE sku_code <> '') AS sku_code_non_null_count,
    COUNT(*) FILTER (WHERE product_title <> '') AS product_title_non_null_count,
    COUNT(*) FILTER (WHERE query_fact_type <> '') AS query_fact_type_non_null_count,
    COUNT(*) FILTER (WHERE source_type <> '') AS source_type_non_null_count,
    COUNT(*) FILTER (WHERE evidence_role <> '') AS evidence_role_non_null_count,
    COUNT(*) FILTER (WHERE media_role <> '') AS media_role_non_null_count,
    COUNT(*) FILTER (WHERE usable_for_agent = true) AS usable_for_agent_true_count,
    COUNT(*) FILTER (WHERE i_id = '' AND sku_code = '' AND product_title = '') AS rows_missing_product_identity,
    COUNT(*) FILTER (WHERE query_fact_type = '') AS rows_missing_query_fact_type,
    COUNT(*) FILTER (WHERE evidence_role = '') AS rows_missing_evidence_role,
    COUNT(*) FILTER (WHERE source_type = '') AS rows_missing_source_type
FROM {table}
"""
            )
            row = dict(cur.fetchone() or {})
            result.update({key: int(value or 0) for key, value in row.items()})
            result["embedding_dimension_distribution"] = _embedding_dimension_distribution(cur, table)
            result["source_type_distribution"] = _distribution(cur, table, "source_type")
            result["evidence_role_distribution"] = _distribution(cur, table, "evidence_role")
            result["media_role_distribution"] = _distribution(cur, table, "media_role")
            result["status_distribution"] = _distribution(cur, table, "status")
    return result


def _sqlite_shadow_source_coverage(db) -> dict[str, Any]:
    generic_total = db.query(KBGenericServiceRule).filter(KBGenericServiceRule.status == "active").count()
    generic_auto = (
        db.query(KBGenericServiceRule)
        .filter(KBGenericServiceRule.status == "active", KBGenericServiceRule.auto_reply_allowed == True)  # noqa: E712
        .count()
    )
    media_total = db.query(KBMediaAsset).count()
    approved_media = (
        db.query(KBMediaAsset)
        .filter(KBMediaAsset.status == "approved", KBMediaAsset.usable_for_agent == 1)
        .count()
    )
    qa_total = db.query(KBQA).filter(KBQA.status == "published").count()
    qa_auto = db.query(KBQA).filter(KBQA.status == "published", KBQA.auto_reply == True).count()  # noqa: E712
    return {
        "sqlite_kbqa_published_count": int(qa_total or 0),
        "sqlite_kbqa_auto_reply_count": int(qa_auto or 0),
        "sqlite_generic_rule_active_count": int(generic_total or 0),
        "sqlite_generic_rule_auto_reply_count": int(generic_auto or 0),
        "sqlite_media_asset_count": int(media_total or 0),
        "sqlite_approved_usable_media_asset_count": int(approved_media or 0),
    }


def run(*, json_output: str = "", db_factory=SessionLocal, service: PgVectorRetrieverService | None = None) -> dict[str, Any]:
    service = service or PgVectorRetrieverService()
    db = db_factory()
    try:
        result = {
            "config": pgvector_config_from_env(),
            "pgvector": _pgvector_coverage(service),
            "sqlite_shadow_sources": _sqlite_shadow_source_coverage(db),
            "notes": [
                "pgvector shadow currently stores synced KnowledgeChunk rows only unless source_type_distribution shows otherwise.",
                "generic rules are service-action fallback evidence, not direct product facts.",
                "media assets must remain role-checked and reply-block attached before any sendable decision.",
            ],
        }
    finally:
        db.close()
    result = sanitize_obj(result)
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Diagnose pgvector shadow metadata coverage.")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("pgvector", {}).get("available") else 2


if __name__ == "__main__":
    raise SystemExit(main())
