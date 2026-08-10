"""RAG scope and lifecycle contracts using only isolated fixture knowledge."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def isolated_rag_db(tmp_path, monkeypatch):
    """Seed a disposable formal knowledge database without recovered products."""
    import app.config as config_module
    import app.db as db_module
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    db_path = tmp_path / "rag_contract.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(config_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    def add_entry(
        db,
        *,
        title: str,
        content: str,
        product_scope: list[str],
        fact_type: str,
        status: str = "published",
        index_status: str = "ready",
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            source_type="product_facts",
            title=title,
            content=content,
            intent="product_question",
            product_scope_json=json.dumps(product_scope),
            fact_type=fact_type,
            fact_scope="product",
            status=status,
            index_status=index_status,
            source_confidence=1.0,
            fact_review_status="reviewed",
            content_hash=f"fixture-{title}",
        )
        db.add(entry)
        db.flush()
        db.add(KnowledgeChunk(
            entry_id=entry.id,
            chunk_text=content,
            chunk_index=0,
            source_type="product_facts",
            intent="product_question",
            product_scope_json=json.dumps(product_scope),
            sku_scope_json="[]",
            platform_scope_json="[]",
            search_keywords=title,
            embedding_status="done",
            fact_source_type="product_facts",
            fact_review_status="reviewed",
            source_confidence=1.0,
        ))
        return entry

    db = session_factory()
    try:
        add_entry(
            db,
            title="fixture alpha material",
            content="fixture alpha material information",
            product_scope=["fixture-alpha"],
            fact_type="material",
        )
        add_entry(
            db,
            title="fixture beta material",
            content="fixture beta material information",
            product_scope=["fixture-beta"],
            fact_type="material",
        )
        add_entry(
            db,
            title="fixture gamma draft",
            content="fixture gamma draft information",
            product_scope=["fixture-gamma"],
            fact_type="material",
            status="draft",
        )
        add_entry(
            db,
            title="fixture alpha appearance",
            content="fixture alpha appearance information",
            product_scope=["fixture-alpha"],
            fact_type="appearance",
        )
        add_entry(
            db,
            title="fixture alpha certificate",
            content="fixture alpha certificate information",
            product_scope=["fixture-alpha"],
            fact_type="certification_report",
        )
        db.commit()
    finally:
        db.close()
    yield session_factory
    engine.dispose()


def _search(**kwargs):
    from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository

    return KnowledgeChunkRepository().search_chunks(**kwargs)


def test_published_ready_knowledge_is_retrievable_for_matching_scope(isolated_rag_db):
    results = _search(
        query="fixture alpha material",
        product_scope=["fixture-alpha"],
        fact_type="material",
        top_k=5,
    )

    assert results
    result = results[0]
    assert result["title"] == "fixture alpha material"
    assert result["entry_status"] == "published"
    assert result["index_status"] == "ready"
    assert result["product_scope"] == ["fixture-alpha"]


def test_product_scope_prevents_cross_product_retrieval(isolated_rag_db):
    results = _search(
        query="fixture material",
        product_scope=["fixture-alpha"],
        fact_type="material",
        top_k=5,
    )

    assert results
    assert results[0]["title"] == "fixture alpha material"
    assert all(result["product_scope"] == ["fixture-alpha"] for result in results)


def test_strict_fact_type_excludes_other_reviewed_product_facts(isolated_rag_db):
    results = _search(
        query="fixture alpha certificate",
        product_scope=["fixture-alpha"],
        fact_type="certification_report",
        top_k=5,
    )

    assert {result["fact_type"] for result in results} == {"certification_report"}
    assert [result["title"] for result in results] == ["fixture alpha certificate"]


def test_formal_retrieval_excludes_draft_even_with_legacy_include_draft_flag(isolated_rag_db):
    results = _search(
        query="fixture gamma draft",
        product_scope=["fixture-gamma"],
        include_draft=True,
        top_k=5,
    )

    assert results == []


def test_retrieval_result_preserves_review_provenance(isolated_rag_db):
    results = _search(
        query="fixture alpha material",
        product_scope=["fixture-alpha"],
        fact_type="material",
        top_k=1,
    )

    assert len(results) == 1
    result = results[0]
    assert result["source_type"] == "product_facts"
    assert result["fact_source_type"] == "product_facts"
    assert result["fact_review_status"] == "reviewed"
    assert result["source_confidence"] == 1.0


def test_retrieval_order_is_stable_for_same_fixture_input(isolated_rag_db):
    query = {
        "query": "fixture alpha material",
        "product_scope": ["fixture-alpha"],
        "top_k": 5,
    }

    first = _search(**query)
    second = _search(**query)

    assert [result["chunk_id"] for result in first] == [result["chunk_id"] for result in second]
