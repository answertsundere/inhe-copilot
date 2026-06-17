"""
测试 RAG 检索只召回 published + index_status=ready 的知识
"""

import os
import tempfile
import uuid

_test_db_path = None


_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_ready_filter_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _orig_engine = db_module.engine
    _orig_session_local = db_module.SessionLocal

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    global _orig_engine, _orig_session_local
    import app.db as db_module
    if _orig_engine is not None:
        db_module.engine = _orig_engine
    if _orig_session_local is not None:
        db_module.SessionLocal = _orig_session_local
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass


from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever
from app.services.knowledge_index_service import KnowledgeIndexService
from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk


class TestRetrieverReadyFilter:
    """验证检索层强制 published + ready 过滤"""

    def setup_method(self):
        # 动态获取 SessionLocal（避免模块级 import 缓存旧引用）
        from app.db import SessionLocal
        self._SessionLocal = SessionLocal
        # 每个测试方法前清理数据库
        db = self._SessionLocal()
        try:
            db.query(KnowledgeChunk).delete()
            db.query(KnowledgeEntry).delete()
            db.commit()
        finally:
            db.close()

    def _create_and_publish(self, title, content, product_scope=None):
        """创建并发布知识，确保 index_status=ready"""
        e = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title=title,
            content=content,
            intent="product_question",
            product_scope=product_scope or ["测试商品"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        KnowledgeIndexService.on_publish(e.id, user="supervisor")
        return e

    def _set_index_status(self, entry_id, index_status):
        """手动修改 entry 的 index_status（用于模拟非 ready 状态）"""
        db = self._SessionLocal()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if entry:
                entry.index_status = index_status
                db.commit()
        finally:
            db.close()

    def test_published_ready_can_recall(self):
        """published + ready 可以召回"""
        e = self._create_and_publish("材质说明", "材质：实木。\n\n尺寸：60cm。")

        results = KnowledgeChunkRepository.search_chunks(query="材质", top_k=5)
        assert len(results) > 0
        assert results[0]["entry_status"] == "published"
        assert results[0]["index_status"] == "ready"

    def test_published_indexing_not_recall(self):
        """published + indexing 不能召回"""
        e = self._create_and_publish("尺寸说明", "尺寸：60cm。")
        self._set_index_status(e.id, "indexing")

        results = KnowledgeChunkRepository.search_chunks(query="尺寸", top_k=5)
        entry_ids = [r["entry_id"] for r in results]
        assert e.id not in entry_ids, "indexing 状态的条目不应被召回"

    def test_published_failed_not_recall(self):
        """published + failed 不能召回"""
        e = self._create_and_publish("承重说明", "承重：50kg。")
        self._set_index_status(e.id, "failed")

        results = KnowledgeChunkRepository.search_chunks(query="承重", top_k=5)
        entry_ids = [r["entry_id"] for r in results]
        assert e.id not in entry_ids, "failed 状态的条目不应被召回"

    def test_published_removed_not_recall(self):
        """published + removed 不能召回"""
        e = self._create_and_publish("清洗说明", "可水洗。")
        self._set_index_status(e.id, "removed")

        results = KnowledgeChunkRepository.search_chunks(query="水洗", top_k=5)
        entry_ids = [r["entry_id"] for r in results]
        assert e.id not in entry_ids, "removed 状态的条目不应被召回"

    def test_draft_ready_not_recall(self):
        """draft + ready 不能召回"""
        e = self._create_and_publish("安装说明", "安装简单。")
        db = self._SessionLocal()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == e.id).first()
            if entry:
                entry.status = "draft"
                db.commit()
        finally:
            db.close()

        results = KnowledgeChunkRepository.search_chunks(query="安装", top_k=5)
        entry_ids = [r["entry_id"] for r in results]
        assert e.id not in entry_ids, "draft 状态的条目不应被召回"

    def test_archived_ready_not_recall(self):
        """archived + ready 不能召回"""
        e = self._create_and_publish("售后政策", "7天无理由。")
        db = self._SessionLocal()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == e.id).first()
            if entry:
                entry.status = "archived"
                db.commit()
        finally:
            db.close()

        results = KnowledgeChunkRepository.search_chunks(query="售后", top_k=5)
        entry_ids = [r["entry_id"] for r in results]
        assert e.id not in entry_ids, "archived 状态的条目不应被召回"

    def test_top_k_excludes_invalid_before_sorting(self):
        """top_k 排序前排除无效 entry"""
        e_ready = self._create_and_publish("A商品", "A材质：实木。")
        e_failed = self._create_and_publish("B商品", "B材质：松木。")
        self._set_index_status(e_failed.id, "failed")

        results = KnowledgeChunkRepository.search_chunks(query="材质", top_k=5)
        for r in results:
            assert r["index_status"] == "ready", f"非 ready 条目不应出现在结果中: {r}"
            assert r["entry_status"] == "published", f"非 published 条目不应出现在结果中: {r}"

    def test_current_sqlite_retriever_enforces_ready(self):
        """CurrentSQLiteRetriever 二次验证 ready"""
        e = self._create_and_publish("填充物", "填充物：记忆棉。")

        retriever = CurrentSQLiteRetriever()
        results = retriever.retrieve(query="填充物")
        assert len(results) > 0
        for r in results:
            assert r["entry_status"] == "published"
            assert r["index_status"] == "ready"

    def test_hybrid_retriever_enforces_ready(self):
        """search_hybrid 同样强制 ready"""
        e = self._create_and_publish("高度", "高度：30cm。")

        results = KnowledgeChunkRepository.search_hybrid(query="高度", top_k=5)
        assert len(results) > 0
        for r in results:
            assert r["entry_status"] == "published"
            assert r["index_status"] == "ready"
