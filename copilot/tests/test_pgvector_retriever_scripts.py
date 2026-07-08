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


def test_shadow_embedding_generation_batches_api_requests(monkeypatch):
    import scripts.sync_pgvector_kb_chunks as script
    from app.models.kb_tables import KBGenericServiceRule

    calls = []

    def fake_get_embeddings(texts):
        calls.append(len(texts))
        return [[0.01] * 1024 for _ in texts]

    monkeypatch.setattr(script.EmbeddingService, "get_embeddings", fake_get_embeddings)
    rules = [
        KBGenericServiceRule(
            id=index,
            rule_key=f"rule-{index}",
            title=f"title {index}",
            content="content",
            fact_type="promotion_policy",
            auto_reply_allowed=False,
        )
        for index in range(25)
    ]

    rows, failed = script._build_rows_with_embeddings(rules, source_type="generic_rule")

    assert calls == [10, 10, 5]
    assert len(rows) == 25
    assert failed == 0


class _FakeMetadataPgService:
    def __init__(self):
        self.updates = []

    def fetch_rows_for_metadata_normalization(self, *, limit=0):
        return [{
            "source_chunk_id": "1",
            "query_fact_type": "accessories",
            "evidence_role": "accessories",
            "source_type": "product_facts",
            "chunk_text": "配件可以单独购买",
            "metadata": {},
        }]

    def apply_metadata_normalization_updates(self, updates, *, batch_size=500):
        self.updates.extend(updates)
        return {"updated_count": len(updates), "failed_count": 0}


def test_normalize_metadata_dry_run_does_not_update_pgvector():
    import scripts.sync_pgvector_kb_chunks as script

    service = _FakeMetadataPgService()

    result = script.normalize_pgvector_metadata(apply=False, pg_service=service)

    assert result["dry_run"] is True
    assert result["would_update_count"] == 1
    assert result["updated_count"] == 0
    assert service.updates == []


def test_normalize_metadata_apply_updates_pgvector_metadata_only():
    import scripts.sync_pgvector_kb_chunks as script

    service = _FakeMetadataPgService()

    result = script.normalize_pgvector_metadata(apply=True, pg_service=service)

    assert result["dry_run"] is False
    assert result["would_update_count"] == 1
    assert result["updated_count"] == 1
    assert service.updates[0]["query_fact_type"] == "accessory_availability"
    assert "embedding" not in service.updates[0]
    metadata = json.loads(service.updates[0]["metadata"])
    assert metadata["original_query_fact_type"] == "accessories"
    assert metadata["normalized_query_fact_type"] == "accessory_availability"
