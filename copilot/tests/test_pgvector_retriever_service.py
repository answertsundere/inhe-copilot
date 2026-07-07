from __future__ import annotations

import json


def test_mask_dsn_hides_password():
    from app.services.pgvector_retriever_service import mask_dsn

    masked = mask_dsn("postgresql://copilot:secret-password@localhost:5432/copilot_vector")

    assert "secret-password" not in masked
    assert "copilot:***@" in masked


def test_schema_sql_uses_vector_dimension_and_no_password():
    from app.services.pgvector_retriever_service import VECTOR_DIMENSION, build_schema_sql

    statements = "\n".join(build_schema_sql("kb_chunk_embeddings_pg"))

    assert f"vector({VECTOR_DIMENSION})" in statements
    assert "USING hnsw" in statements
    assert "password" not in statements.lower()


def test_retrieve_sql_applies_metadata_filters():
    from app.services.pgvector_retriever_service import build_retrieve_sql

    sql, params = build_retrieve_sql(
        i_id="IID-1",
        sku_code="SKU-1",
        query_fact_type="installation",
        allowed_source_types=["faq", "manual"],
        allowed_evidence_roles=["installation_diagram"],
        top_k=7,
    )

    assert "i_id = %(i_id)s" in sql
    assert "sku_code = %(sku_code)s" in sql
    assert "query_fact_type = %(query_fact_type)s" in sql
    assert "source_type = ANY(%(allowed_source_types)s)" in sql
    assert "evidence_role = ANY(%(allowed_evidence_roles)s)" in sql
    assert params["top_k"] == 7


def test_retriever_blocks_broad_search_without_identity_or_filters():
    from app.services.pgvector_retriever_service import PgVectorRetrieverService

    service = PgVectorRetrieverService(dsn="postgresql://user:pass@localhost/db")
    result = service.retrieve(query_text="安装视频", query_embedding=[0.0] * 1024)

    assert result == []


def test_chunk_to_pg_row_validates_embedding_dimension():
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry
    from app.services.pgvector_retriever_service import chunk_to_pg_row

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
    bad = KnowledgeChunk(
        id=1,
        entry_id=1,
        chunk_text="安装说明",
        source_type="faq",
        intent="installation",
        embedding_json=json.dumps([0.1, 0.2]),
    )
    bad.entry = entry
    row, reason = chunk_to_pg_row(bad)
    assert row is None
    assert reason == "bad_dimension"

    good = KnowledgeChunk(
        id=2,
        entry_id=1,
        chunk_text="安装说明",
        source_type="faq",
        intent="installation",
        embedding_json=json.dumps([0.1] * 1024),
    )
    good.entry = entry
    row, reason = chunk_to_pg_row(good)
    assert reason == ""
    assert row["source_chunk_id"] == "2"
    assert row["query_fact_type"] == "installation"
    assert row["usable_for_agent"] is True
