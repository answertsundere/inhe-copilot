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


def run(
    *,
    apply: bool = False,
    limit: int = 0,
    batch_size: int = 500,
    json_output: str = "",
    db_factory=SessionLocal,
) -> dict:
    db = db_factory()
    try:
        chunks = load_published_chunks(db, limit=limit)
        result = sync_chunks_to_pgvector(
            chunks,
            pg_service=PgVectorRetrieverService(),
            apply=apply,
            batch_size=batch_size,
        )
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
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(apply=args.apply, limit=args.limit, batch_size=args.batch_size, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
