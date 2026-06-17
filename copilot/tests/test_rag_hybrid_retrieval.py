"""
测试 RAG 混合检索打分逻辑
"""

import os
import tempfile
import uuid

_test_db_path = None


_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_rag_hybrid_{uuid.uuid4().hex}.db")

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
from app.services.knowledge_index_service import KnowledgeIndexService


class TestHybridSearchScoring:
    """测试 search_hybrid 返回打分字段"""

    def setup_method(self):
        # 创建测试知识
        e1 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="儿童书架材质说明",
            content="材质：进口实木松木。\n\n尺寸：60cm x 120cm。",
            intent="product_question", product_scope=["儿童书架"], sku_scope=["SKU-001"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e1.id, user="op")
        KnowledgeIndexService.on_publish(e1.id, user="supervisor_1")
        self.entry1 = e1

        e2 = KnowledgeEntryRepository.create(
            source_type="shipping_policy", title="发货时效",
            content="现货商品付款后48小时内发货。\n\n大件商品使用德邦物流。",
            intent="logistics_eta", created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e2.id, user="op")
        KnowledgeIndexService.on_publish(e2.id, user="supervisor_1")
        self.entry2 = e2

    def test_hybrid_returns_scoring_fields(self):
        """search_hybrid 应返回 text_score, vector_score, scope_score, rerank_score"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="书架材质",
            source_types=["product_facts"],
            top_k=5,
        )
        assert len(results) > 0
        r = results[0]
        assert "text_score" in r
        assert "vector_score" in r
        assert "scope_score" in r
        assert "rerank_score" in r
        assert "mismatch_reason" in r

    def test_text_score_non_negative(self):
        """text_score 应该 >= 0"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="材质",
            top_k=5,
        )
        for r in results:
            assert r["text_score"] >= 0

    def test_vector_score_zero_without_embedding(self):
        """未启用 embedding 时 vector_score 应为 0"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="材质",
            top_k=5,
        )
        for r in results:
            assert r["vector_score"] == 0.0

    def test_rerank_score_ordering(self):
        """结果应按 rerank_score 降序排列"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="发货",
            top_k=10,
        )
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i]["rerank_score"] >= results[i + 1]["rerank_score"]

    def test_sku_scope_match_in_hybrid(self):
        """带 sku_name 的 hybrid 搜索应正确计算 scope_score"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="材质",
            sku_name="SKU-001",
            top_k=5,
        )
        # SKU-001 匹配的 chunk 应有正的 scope_score
        matched = [r for r in results if r.get("scope_score", 0) > 0]
        # 至少有一条匹配结果
        assert len(matched) > 0

    def test_sku_scope_conflict_in_hybrid(self):
        """SKU 冲突时应得到负的 scope_score"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="材质",
            sku_name="SKU-999",
            top_k=5,
        )
        # 有 sku_scope 的 chunk 但 SKU 不匹配应被标记为冲突
        conflicts = [r for r in results if r.get("mismatch_reason") == "sku_conflict"]
        # 可能没有冲突结果（如果没有匹配到有 sku_scope 的 chunks）
        # 但如果有带 sku_scope 的结果且不匹配 SKU-999，应该有冲突标记
        sku_scoped = [r for r in results if r.get("metadata", {}).get("sku_scope")]
        for r in sku_scoped:
            if "SKU-999" not in r["metadata"]["sku_scope"]:
                assert r["scope_score"] == -1.0

    def test_hybrid_graceful_degradation(self):
        """embedding 未启用时应优雅降级为纯文本搜索"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="发货时效",
            top_k=5,
        )
        assert isinstance(results, list)
        assert len(results) > 0
        # 全部 vector_score 应为 0
        for r in results:
            assert r["vector_score"] == 0.0
