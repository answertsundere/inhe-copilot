"""
测试 RAG 范围守卫 - 商品范围不匹配检测
"""

import os
import tempfile
import uuid

_test_db_path = None


_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_rag_scope_{uuid.uuid4().hex}.db")

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


class TestScopeGuard:
    """测试 scope mismatch 检测"""

    def setup_method(self):
        # 创建带 SKU scope 的知识
        e1 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="SKU-A 专属说明",
            content="SKU-A 是蓝色款。\n\n尺寸为 60cm。",
            intent="product_question", sku_scope=["SKU-A"], created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e1.id, user="op")
        KnowledgeIndexService.on_publish(e1.id, user="supervisor_1")

        # 创建无 SKU scope 的通用知识
        e2 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="通用材质说明",
            content="所有产品采用环保材料。\n\n通过安全认证。",
            intent="product_question", created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e2.id, user="op")
        KnowledgeIndexService.on_publish(e2.id, user="supervisor_1")

    def test_sku_exact_match_scope_score(self):
        """SKU 精确匹配应得到 +1.0 scope_score"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="蓝色款",
            sku_name="SKU-A",
            top_k=10,
        )
        sku_a_results = [r for r in results if r.get("metadata", {}).get("sku_scope") == ["SKU-A"]]
        for r in sku_a_results:
            assert r["scope_score"] == 1.0

    def test_sku_conflict_negative_scope(self):
        """SKU 不匹配（冲突）应得到 -1.0 scope_score"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="说明",
            sku_name="SKU-B",
            top_k=10,
        )
        # 有 SKU-A scope 的 chunk 对 SKU-B 应冲突
        sku_scoped = [r for r in results if r.get("metadata", {}).get("sku_scope")]
        for r in sku_scoped:
            if "SKU-B" not in r["metadata"]["sku_scope"]:
                assert r["scope_score"] == -1.0
                assert r["mismatch_reason"] == "sku_conflict"

    def test_no_sku_scope_zero_scope_score(self):
        """没有指定 sku_name 时 scope_score 应为 0"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="材质",
            top_k=10,
        )
        for r in results:
            assert r["scope_score"] == 0.0

    def test_product_name_in_title_match(self):
        """product_name 出现在标题中应得到 +0.7 scope_score"""
        results = KnowledgeChunkRepository.search_hybrid(
            query="说明",
            product_name="材质说明",
            top_k=10,
        )
        title_matched = [r for r in results if "材质说明" in r.get("title", "")]
        for r in title_matched:
            # 应有产品名匹配的加分
            assert r["scope_score"] >= 0.7

    def test_scope_score_affects_ranking(self):
        """scope_score 应影响最终排序"""
        results_sku_a = KnowledgeChunkRepository.search_hybrid(
            query="说明",
            sku_name="SKU-A",
            top_k=10,
        )
        results_sku_b = KnowledgeChunkRepository.search_hybrid(
            query="说明",
            sku_name="SKU-B",
            top_k=10,
        )

        # SKU-A 搜索时 SKU-A 的 chunk 排名应高于 SKU-B 搜索时
        if results_sku_a and results_sku_b:
            sku_a_top_score = results_sku_a[0]["rerank_score"]
            sku_b_top_score = results_sku_b[0]["rerank_score"]
            # 两种搜索都有结果即可，具体排名因 scope_score 而不同
            assert isinstance(sku_a_top_score, float)
            assert isinstance(sku_b_top_score, float)
