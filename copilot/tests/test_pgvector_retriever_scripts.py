from __future__ import annotations

import json


class _FakePgService:
    dsn = "postgresql://user:pass@localhost/db"
    collection = "kb_chunk_embeddings_pg"

    def __init__(self):
        self.rows = []

    def connect_factory(self, dsn):  # pragma: no cover - apply path not used in this test
        raise AssertionError("dry-run must not connect")


def test_init_pgvector_dry_run_has_schema_without_secret(monkeypatch):
    from scripts.init_pgvector_retriever import run

    monkeypatch.setenv("COPILOT_PGVECTOR_DSN", "postgresql://copilot:secret@localhost:5432/copilot_vector")
    result = run(check=False, apply=False)

    assert result["config"]["dsn_masked"] == "postgresql://copilot:***@localhost:5432/copilot_vector"
    assert result["schema"]["dry_run"] is True
    assert "secret" not in json.dumps(result, ensure_ascii=False)


def test_sync_chunks_dry_run_counts_bad_dimensions():
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry
    from app.services.pgvector_retriever_service import PgVectorRetrieverService, sync_chunks_to_pgvector

    entry = KnowledgeEntry(
        id=1,
        source_type="faq",
        title="安装说明",
        content="安装说明",
        status="published",
        product_id="IID-1",
        sku_id="SKU-1",
        fact_type="installation",
    )
    good = KnowledgeChunk(
        id=1,
        entry_id=1,
        chunk_text="安装说明",
        source_type="faq",
        intent="installation",
        embedding_json=json.dumps([0.01] * 1024),
    )
    bad = KnowledgeChunk(
        id=2,
        entry_id=1,
        chunk_text="坏维度",
        source_type="faq",
        intent="installation",
        embedding_json=json.dumps([0.01] * 3),
    )
    missing = KnowledgeChunk(
        id=3,
        entry_id=1,
        chunk_text="无 embedding",
        source_type="faq",
        intent="installation",
        embedding_json=None,
    )
    for chunk in (good, bad, missing):
        chunk.entry = entry

    result = sync_chunks_to_pgvector(
        [good, bad, missing],
        pg_service=PgVectorRetrieverService(dsn=""),
        apply=False,
        batch_size=2,
    )

    assert result["dry_run"] is True
    assert result["scanned_count"] == 3
    assert result["synced_count"] == 1
    assert result["skipped_no_embedding"] == 1
    assert result["skipped_bad_dimension"] == 1


def test_sync_shadow_sources_reports_metadata_only_without_embedding(monkeypatch):
    import scripts.sync_pgvector_kb_chunks as script

    monkeypatch.setattr(script, "load_published_chunks", lambda db, limit=0: [])
    monkeypatch.setattr(script, "_count_kbqa_without_embeddings", lambda db, limit=0: 2)
    monkeypatch.setattr(script, "_count_generic_rules_without_embeddings", lambda db, limit=0: 1)
    monkeypatch.setattr(script, "_count_media_assets_without_embeddings", lambda db, limit=0: 3)

    class _Db:
        def close(self):
            pass

    result = script.run(
        apply=False,
        source_type="all",
        include_kbqa=True,
        include_generic_rules=True,
        include_media_assets=True,
        db_factory=lambda: _Db(),
    )

    assert result["source_types"] == ["knowledge_chunk", "kbqa", "generic_rule", "media_asset"]
    assert result["scanned_count"] == 6
    assert result["synced_count"] == 0
    assert result["skipped_no_embedding_by_source_type"] == {
        "kbqa": 2,
        "generic_rule": 1,
        "media_asset": 3,
    }
    assert result["metadata_only_source_types"] == ["kbqa", "generic_rule", "media_asset"]
