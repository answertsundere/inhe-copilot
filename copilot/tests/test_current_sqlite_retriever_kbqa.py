from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_kbqa_fallback_matches_sku_family_and_ranks_material_first(monkeypatch, tmp_path):
    import app.db as db_module
    from app.models.kb_tables import KBProduct, KBQA
    from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
    from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever

    engine = create_engine(f"sqlite:///{tmp_path / 'kbqa.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(KnowledgeChunkRepository, "search_hybrid", lambda **kwargs: [])

    db_module.Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        product = KBProduct(
            i_id="YH06K53",
            product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": "YH06K53"}]),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add_all([
            KBQA(
                question="\u8fd9\u6b3e\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc\u6bcf\u5c42\u627f\u91cd\u591a\u5c11\uff1f",
                answer="\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg\u3002",
                product_id=product.id,
                sku_codes_json=json.dumps(["YH06K53"]),
                status="published",
                auto_reply=True,
            ),
            KBQA(
                question="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc\u6750\u8d28\u662f\u4ec0\u4e48\uff1f\u9632\u6f6e\u5417\uff1f",
                answer="\u4e3b\u8981\u91c7\u7528\u51b7\u8f67\u94a2\u7ba1/\u73af\u4fddPP/\u65e0\u7eba\u5e03\u7b49\u6750\u8d28\u3002",
                product_id=product.id,
                sku_codes_json=json.dumps(["YH06K53"]),
                status="published",
                auto_reply=True,
            ),
        ])
        db.commit()
    finally:
        db.close()

    results = CurrentSQLiteRetriever().retrieve(
        query="\u6750\u8d28\u5b89\u5168\u5417\uff1f",
        sku_scope=["YH06K53B05S13"],
        source_types=["faq"],
        top_k=5,
    )

    assert results
    assert results[0]["entry_id"].startswith("kbqa:")
    assert "\u6750\u8d28" in results[0]["title"]


def test_kbqa_fallback_preserves_source_scope_and_rejects_explicit_sku_conflict(
    monkeypatch,
    tmp_path,
):
    import app.db as db_module
    from app.models.kb_tables import KBProduct, KBQA
    from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
    from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever

    engine = create_engine(f"sqlite:///{tmp_path / 'kbqa-scope.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(KnowledgeChunkRepository, "search_hybrid", lambda **kwargs: [])

    db_module.Base.metadata.create_all(bind=engine)
    db = session_factory()
    try:
        target = KBProduct(
            i_id="YH06K07",
            product_name="\u751c\u70b9\u5c4b\u94c1\u6746\u6536\u7eb3\u67b6",
            sku_list_json=json.dumps([{"sku_code": "YH06K07"}]),
            status="published",
        )
        other = KBProduct(
            i_id="YH06K40",
            product_name="A\u751c\u70b9\u5c4b\u94c1\u6746\u6536\u7eb3\u67b6",
            sku_list_json=json.dumps([{"sku_code": "YH06K40"}]),
            status="published",
        )
        db.add_all([target, other])
        db.flush()
        db.add_all([
            KBQA(
                question="\u751c\u70b9\u5c4b\u94c1\u6746\u6536\u7eb3\u67b6\u600e\u4e48\u5b89\u88c5\uff1f",
                answer="\u5305\u88c5\u5185\u6709\u5b89\u88c5\u8bf4\u660e\u3002",
                product_id=target.id,
                sku_codes_json=json.dumps(["YH06K07"]),
                status="published",
                auto_reply=True,
            ),
            KBQA(
                question="A\u751c\u70b9\u5c4b\u94c1\u6746\u6536\u7eb3\u67b6\u600e\u4e48\u5b89\u88c5\uff1f",
                answer="\u53e6\u4e00\u6b3e\u5546\u54c1\u7684\u5b89\u88c5\u8bf4\u660e\u3002",
                product_id=other.id,
                sku_codes_json=json.dumps(["YH06K40"]),
                status="published",
                auto_reply=True,
            ),
        ])
        db.commit()
    finally:
        db.close()

    results = CurrentSQLiteRetriever().retrieve(
        query="\u8fd9\u6b3e\u5177\u4f53\u600e\u4e48\u5b89\u88c5\uff1f",
        product_scope=["\u751c\u70b9\u5c4b\u94c1\u6746\u6536\u7eb3\u67b6"],
        sku_scope=["YH06K07B01S04"],
        source_types=["faq"],
        fact_type="installation",
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["sku_scope"] == ["YH06K07"]
    assert results[0]["product_scope"] == [
        "\u751c\u70b9\u5c4b\u94c1\u6746\u6536\u7eb3\u67b6",
        "YH06K07",
    ]
