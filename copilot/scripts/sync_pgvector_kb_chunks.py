"""Sync existing published chunk embeddings to pgvector shadow storage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBQA  # noqa: E402
from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.fact_type_service import infer_evidence_fact_type  # noqa: E402
from app.services.media_asset_service import get_auto_send_level  # noqa: E402
from app.services.pgvector_retriever_service import (  # noqa: E402
    PgVectorRetrieverService,
    sync_chunks_to_pgvector,
    sync_pg_rows_to_pgvector,
    validate_embedding,
    vector_literal,
)


EMBEDDING_REQUEST_BATCH_SIZE = 10


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


def _content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _row_base(
    *,
    source_chunk_id: str,
    entry_id: int,
    text: str,
    embedding: list[float],
    i_id: str = "",
    sku_code: str = "",
    product_title: str = "",
    query_fact_type: str = "",
    source_type: str,
    evidence_role: str,
    media_role: str = "",
    usable_for_agent: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    metadata["embedding_dimension"] = len(embedding)
    return {
        "source_chunk_id": source_chunk_id,
        "entry_id": int(entry_id or 0),
        "chunk_text": text,
        "embedding": vector_literal(embedding),
        "i_id": str(i_id or ""),
        "sku_code": str(sku_code or ""),
        "product_title": str(product_title or ""),
        "query_fact_type": str(query_fact_type or ""),
        "source_type": source_type,
        "evidence_role": evidence_role,
        "media_role": media_role,
        "status": "published",
        "usable_for_agent": bool(usable_for_agent),
        "metadata": json.dumps(metadata, ensure_ascii=False),
        "content_hash": _content_hash(text),
        "updated_at": datetime.now(timezone.utc),
    }


def _load_kbqa_rows(db, *, limit: int = 0) -> list[tuple[KBQA, KBProduct | None]]:
    query = (
        db.query(KBQA, KBProduct)
        .outerjoin(KBProduct, KBQA.product_id == KBProduct.id)
        .filter(KBQA.status == "published", KBQA.auto_reply == True)  # noqa: E712
        .order_by(KBQA.id.asc())
    )
    if limit:
        query = query.limit(max(1, int(limit)))
    return query.all()


def _load_generic_rules(db, *, limit: int = 0) -> list[KBGenericServiceRule]:
    query = (
        db.query(KBGenericServiceRule)
        .filter(KBGenericServiceRule.status == "active")
        .order_by(KBGenericServiceRule.id.asc())
    )
    if limit:
        query = query.limit(max(1, int(limit)))
    return query.all()


def _load_media_assets(db, *, limit: int = 0) -> list[KBMediaAsset]:
    query = (
        db.query(KBMediaAsset)
        .filter(KBMediaAsset.status == "approved", KBMediaAsset.usable_for_agent == 1)
        .filter(KBMediaAsset.asset_type.notin_(["", "other", "unknown", "image", "product_photo", "sku_image"]))
        .order_by(KBMediaAsset.id.asc())
    )
    if limit:
        query = query.limit(max(1, int(limit)))
    return query.all()


def _kbqa_text(qa: KBQA) -> str:
    return "\n".join(part for part in [qa.question or "", qa.answer or ""] if part)


def _generic_text(rule: KBGenericServiceRule) -> str:
    return "\n".join(part for part in [rule.title or "", rule.content or "", rule.reply_template or ""] if part)


def _media_text(asset: KBMediaAsset) -> str:
    raw = asset.get_source_raw() if hasattr(asset, "get_source_raw") else {}
    parts = [
        asset.asset_title,
        asset.asset_type,
        asset.product_name,
        asset.i_id,
        asset.sku_code,
        raw.get("media_purpose") if isinstance(raw, dict) else "",
        raw.get("asset_source_note") if isinstance(raw, dict) else "",
    ]
    return " ".join(str(part or "") for part in parts if str(part or "").strip())


def _sku_codes(qa: KBQA, product: KBProduct | None) -> list[str]:
    values = qa.get_sku_codes() if hasattr(qa, "get_sku_codes") else []
    if product and hasattr(product, "get_sku_list"):
        for item in product.get_sku_list():
            if isinstance(item, dict):
                values.append(item.get("sku_code") or item.get("sku_id") or item.get("value"))
            else:
                values.append(item)
    return [str(item).strip() for item in values if str(item or "").strip()]


def _build_rows_with_embeddings(items: list[Any], *, source_type: str) -> tuple[list[dict[str, Any]], int]:
    texts: list[str] = []
    payloads: list[Any] = []
    for item in items:
        if source_type == "kbqa":
            qa, _product = item
            text = _kbqa_text(qa)
        elif source_type == "generic_rule":
            text = _generic_text(item)
        else:
            text = _media_text(item)
        if text.strip():
            payloads.append(item)
            texts.append(text)
    if not texts:
        return [], 0
    embeddings: list[list[float] | None] = []
    for start in range(0, len(texts), EMBEDDING_REQUEST_BATCH_SIZE):
        batch_texts = texts[start:start + EMBEDDING_REQUEST_BATCH_SIZE]
        batch_embeddings = EmbeddingService.get_embeddings(batch_texts)
        if not batch_embeddings or len(batch_embeddings) != len(batch_texts):
            embeddings.extend([None] * len(batch_texts))
        else:
            embeddings.extend(batch_embeddings)
    rows: list[dict[str, Any]] = []
    failed = 0
    for item, text, embedding in zip(payloads, texts, embeddings):
        if embedding is None:
            failed += 1
            continue
        valid = validate_embedding(embedding)
        if valid is None:
            failed += 1
            continue
        if source_type == "kbqa":
            qa, product = item
            skus = _sku_codes(qa, product)
            fact_type = infer_evidence_fact_type({
                "title": qa.question,
                "chunk_text": qa.answer,
                "source_type": qa.source_type or "faq",
                "category": qa.category_l2 or qa.category_l1 or "",
                "category_l3": qa.category_l3 or "",
                "issue_type": qa.issue_type or "",
            })
            rows.append(_row_base(
                source_chunk_id=f"kbqa:{qa.id}",
                entry_id=qa.id,
                text=text,
                embedding=valid,
                i_id=product.i_id if product else "",
                sku_code=skus[0] if skus else "",
                product_title=product.product_name if product else "",
                query_fact_type=fact_type,
                source_type="kbqa",
                evidence_role="faq_direct" if fact_type and (product or skus) else "reference_only",
                usable_for_agent=bool(fact_type and (product or skus) and not qa.human_review),
                metadata={"qa_id": qa.id, "risk_level": qa.risk_level or "", "auto_reply": bool(qa.auto_reply)},
            ))
        elif source_type == "generic_rule":
            role = "service_action" if item.allowed_when_product_fact_missing else "fallback_only"
            rows.append(_row_base(
                source_chunk_id=f"generic_rule:{item.id}",
                entry_id=item.id,
                text=text,
                embedding=valid,
                query_fact_type=item.fact_type or "",
                source_type="generic_rule",
                evidence_role=role,
                usable_for_agent=bool(item.auto_reply_allowed),
                metadata={"rule_key": item.rule_key, "risk_level": item.risk_level or ""},
            ))
        else:
            auto_level = get_auto_send_level(item)
            rows.append(_row_base(
                source_chunk_id=f"media_asset:{item.id}",
                entry_id=item.id,
                text=text,
                embedding=valid,
                i_id=item.i_id,
                sku_code=item.sku_code,
                product_title=item.product_name,
                source_type="media_asset",
                evidence_role="media_reference",
                media_role=item.asset_type,
                usable_for_agent=bool(item.status == "approved" and item.usable_for_agent == 1),
                metadata={
                    "asset_id": item.id,
                    "asset_type": item.asset_type,
                    "auto_send_level": auto_level,
                    "approved": item.status == "approved",
                    "usable_for_agent": bool(item.usable_for_agent),
                },
            ))
    return rows, failed


def run(
    *,
    apply: bool = False,
    limit: int = 0,
    batch_size: int = 500,
    source_type: str = "knowledge_chunk",
    include_kbqa: bool = False,
    include_generic_rules: bool = False,
    include_media_assets: bool = False,
    generate_missing_embeddings: bool = False,
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
            "would_generate_embedding_count_by_source_type": {},
            "generated_embedding_count_by_source_type": {},
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
        source_loaders = {
            "kbqa": _load_kbqa_rows,
            "generic_rule": _load_generic_rules,
            "media_asset": _load_media_assets,
        }
        source_counters = {
            "kbqa": _count_kbqa_without_embeddings,
            "generic_rule": _count_generic_rules_without_embeddings,
            "media_asset": _count_media_assets_without_embeddings,
        }
        for name, counter in source_counters.items():
            if name not in selected_sources:
                continue
            count = int(counter(db, limit=limit) or 0)
            result["scanned_count"] += count
            result["scanned_count_by_source_type"][name] = count
            if not generate_missing_embeddings:
                result["skipped_no_embedding"] += count
                result["skipped_no_embedding_by_source_type"][name] = count
                result["metadata_only_source_types"].append(name)
                continue
            result["would_generate_embedding_count_by_source_type"][name] = count
            if not apply:
                continue
            rows, failed = _build_rows_with_embeddings(source_loaders[name](db, limit=limit), source_type=name)
            result["generated_embedding_count_by_source_type"][name] = len(rows)
            if failed:
                result["failed_count"] += failed
            sync_result = sync_pg_rows_to_pgvector(
                rows,
                pg_service=PgVectorRetrieverService(),
                batch_size=batch_size,
            )
            result["synced_count"] += int(sync_result.get("synced_count") or 0)
            result["failed_count"] += int(sync_result.get("failed_count") or 0)
            result["synced_count_by_source_type"][name] = int(sync_result.get("synced_count") or 0)
            if sync_result.get("error"):
                result["error"] = sync_result.get("error")
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
    parser.add_argument("--generate-missing-embeddings", action="store_true")
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
        generate_missing_embeddings=args.generate_missing_embeddings,
        json_output=args.json_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main())
