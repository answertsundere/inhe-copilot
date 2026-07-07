"""Sync existing published chunk embeddings to pgvector shadow storage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBQA  # noqa: E402
from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.pgvector_retriever_service import PgVectorRetrieverService, sync_chunks_to_pgvector  # noqa: E402


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def load_published_chunks(db, *, limit: int = 0) -> list[KnowledgeChunk]:
    query = (
        db.query(KnowledgeChunk)
        .join(KnowledgeEntry)
        .filter(KnowledgeEntry.status == "published")
        .filter(KnowledgeChunk.embedding_json.isnot(None))
        .order_by(KnowledgeChunk.id.asc())
    )
    if limit:
        query = query.limit(max(1, int(limit)))
    return query.all()


def _source_type_plan(
    *,
    source_type: str,
    include_kbqa: bool,
    include_generic_rules: bool,
    include_media_assets: bool,
) -> list[str]:
    source_type = str(source_type or "knowledge_chunk").strip()
    if source_type == "all":
        return ["knowledge_chunk", "kbqa", "generic_rule", "media_asset"]
    selected = [source_type]
    if include_kbqa:
        selected.append("kbqa")
    if include_generic_rules:
        selected.append("generic_rule")
    if include_media_assets:
        selected.append("media_asset")
    return list(dict.fromkeys(selected))


def _limited_count(query, limit: int) -> int:
    if limit:
        return len(query.limit(max(1, int(limit))).all())
    return int(query.count() or 0)


def _count_kbqa_without_embeddings(db, *, limit: int = 0) -> int:
    query = db.query(KBQA).filter(KBQA.status == "published", KBQA.auto_reply == True)  # noqa: E712
    return _limited_count(query, limit)


def _count_generic_rules_without_embeddings(db, *, limit: int = 0) -> int:
    query = db.query(KBGenericServiceRule).filter(KBGenericServiceRule.status == "active")
    return _limited_count(query, limit)


def _count_media_assets_without_embeddings(db, *, limit: int = 0) -> int:
    query = db.query(KBMediaAsset).filter(KBMediaAsset.status == "approved", KBMediaAsset.usable_for_agent == 1)
    return _limited_count(query, limit)


def run(
    *,
    apply: bool = False,
    limit: int = 0,
    batch_size: int = 500,
    source_type: str = "knowledge_chunk",
    include_kbqa: bool = False,
    include_generic_rules: bool = False,
    include_media_assets: bool = False,
    json_output: str = "",
    db_factory=SessionLocal,
) -> dict:
    db = db_factory()
    try:
        selected_sources = _source_type_plan(
            source_type=source_type,
            include_kbqa=include_kbqa,
            include_generic_rules=include_generic_rules,
            include_media_assets=include_media_assets,
        )
        result = {
            "dry_run": not apply,
            "scanned_count": 0,
            "synced_count": 0,
            "skipped_no_embedding": 0,
            "skipped_bad_dimension": 0,
            "failed_count": 0,
            "source_types": selected_sources,
            "scanned_count_by_source_type": {},
            "synced_count_by_source_type": {},
            "skipped_no_embedding_by_source_type": {},
            "metadata_only_source_types": [],
        }
        if "knowledge_chunk" in selected_sources:
            chunks = load_published_chunks(db, limit=limit)
            chunk_result = sync_chunks_to_pgvector(
                chunks,
                pg_service=PgVectorRetrieverService(),
                apply=apply,
                batch_size=batch_size,
            )
            for key in ("scanned_count", "synced_count", "skipped_no_embedding", "skipped_bad_dimension", "failed_count"):
                result[key] += int(chunk_result.get(key) or 0)
            result["scanned_count_by_source_type"]["knowledge_chunk"] = int(chunk_result.get("scanned_count") or 0)
            result["synced_count_by_source_type"]["knowledge_chunk"] = int(chunk_result.get("synced_count") or 0)
            if chunk_result.get("skipped_no_embedding"):
                result["skipped_no_embedding_by_source_type"]["knowledge_chunk"] = int(chunk_result.get("skipped_no_embedding") or 0)
            if chunk_result.get("error"):
                result["error"] = chunk_result.get("error")
        no_embedding_sources = {
            "kbqa": _count_kbqa_without_embeddings,
            "generic_rule": _count_generic_rules_without_embeddings,
            "media_asset": _count_media_assets_without_embeddings,
        }
        for name, counter in no_embedding_sources.items():
            if name not in selected_sources:
                continue
            count = int(counter(db, limit=limit) or 0)
            result["scanned_count"] += count
            result["skipped_no_embedding"] += count
            result["scanned_count_by_source_type"][name] = count
            result["skipped_no_embedding_by_source_type"][name] = count
            result["metadata_only_source_types"].append(name)
        result["apply"] = bool(apply)
        result["limit"] = int(limit or 0)
        result["batch_size"] = int(batch_size or 500)
    finally:
        db.close()
    _write_json(json_output, result)
    return sanitize_obj(result)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sync published knowledge chunk embeddings to pgvector shadow table.")
    parser.add_argument("--apply", action="store_true", help="Write to pgvector. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--source-type",
        default="knowledge_chunk",
        choices=["all", "knowledge_chunk", "kbqa", "generic_rule", "media_asset"],
    )
    parser.add_argument("--include-kbqa", action="store_true")
    parser.add_argument("--include-generic-rules", action="store_true")
    parser.add_argument("--include-media-assets", action="store_true")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(
        apply=args.apply,
        limit=args.limit,
        batch_size=args.batch_size,
        source_type=args.source_type,
        include_kbqa=args.include_kbqa,
        include_generic_rules=args.include_generic_rules,
        include_media_assets=args.include_media_assets,
        json_output=args.json_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
