"""
测试 Retriever 适配层
"""

import os
import uuid
import tempfile
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_retriever_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass


from app.db import SessionLocal
from app.models.knowledge_base import KnowledgeEntry
from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
from app.retrieval.retriever_factory import get_retriever, reset_retrievers
from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever
from app.retrieval.base import BaseKnowledgeRetriever


def _set_status(entry_id, status):
    from app.db import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("UPDATE knowledge_entries SET status=:status WHERE id=:id"),
                     {"status": status, "id": entry_id})
        conn.commit()


def _create_published_entry_with_chunks():
    _suffix = uuid.uuid4().hex[:6]
    entry = KnowledgeEntryRepository.create(
        source_type="product_facts",
        title=f"围兜颜色测试-{_suffix}",
        content=f"围兜有蓝色和粉色两种颜色可选，适合日常搭配使用。- {_suffix}",
        intent="product_question",
        product_scope=[f"围兜-{_suffix}"],
        sku_scope=[f"SKU-{_suffix}"],
        risk_level="low",
        created_by="tester",
        source_sheet="商品详情页",
    )
    _set_status(entry.id, "pending_review")
    result = KnowledgeLifecycleService.approve(entry.id, "supervisor")
    assert "error" not in result, f"approve failed: {result}"
    return result


class TestRetrieverAdapter:

    def setup_method(self):
        reset_retrievers()

    def test_default_backend_is_current_sqlite(self):
        os.environ["COPILOT_RETRIEVER_BACKEND"] = "current_sqlite"
        retriever = get_retriever()
        assert isinstance(retriever, CurrentSQLiteRetriever)

    def test_unknown_backend_falls_back(self):
        retriever = get_retriever("nonexistent")
        assert isinstance(retriever, CurrentSQLiteRetriever)

    def test_current_sqlite_retriever_returns_results(self):
        _create_published_entry_with_chunks()

        retriever = get_retriever("current_sqlite")
        results = retriever.retrieve(
            query="围兜颜色",
            source_types=["product_facts"],
            top_k=5,
        )

        assert isinstance(results, list)
        assert len(results) > 0

        r = results[0]
        assert "chunk_id" in r
        assert "entry_id" in r
        assert "title" in r
        assert "chunk_text" in r
        assert "source_type" in r
        assert "entry_status" in r

    def test_current_sqlite_retriever_only_published(self):
        _create_published_entry_with_chunks()

        KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="草稿条目",
            content="这是一条草稿内容",
            created_by="tester",
        )

        retriever = get_retriever("current_sqlite")
        results = retriever.retrieve(
            query="围兜",
            source_types=["product_facts"],
        )

        for r in results:
            assert r.get("entry_status") != "draft"

    def test_retriever_factory_is_singleton(self):
        r1 = get_retriever("current_sqlite")
        r2 = get_retriever("current_sqlite")
        assert r1 is r2

    def test_base_class_is_abstract(self):
        with pytest.raises(TypeError):
            BaseKnowledgeRetriever()

    def test_rag_search_tool_uses_get_retriever(self):
        """验证 _handle_rag_search 使用 get_retriever 函数。"""
        import inspect
        from app.agent.tools.registry import _handle_rag_search

        source = inspect.getsource(_handle_rag_search)
        assert "get_retriever" in source

    def test_no_llamaindex_dependency(self):
        """验证项目没有安装 LlamaIndex。"""
        import importlib
        try:
            importlib.import_module("llama_index")
            pytest.fail("LlamaIndex should not be installed")
        except ImportError:
            pass
