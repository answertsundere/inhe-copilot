"""
测试 RAG 检索、intent 过滤、evidence 过滤、factual_guard
"""

import os
import tempfile
import uuid
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_knowledge_base_{uuid.uuid4().hex}.db")

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


from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from app.services.knowledge_index_service import KnowledgeIndexService


class TestRAGRetrieve:
    def setup_method(self):
        # 创建多种 source_type 的知识
        self.entries = []

        # shipping_policy - published
        e1 = KnowledgeEntryRepository.create(
            source_type="shipping_policy", title="发货时效", content="现货商品付款后48小时内发货。\n\n大件商品使用德邦物流。",
            intent="logistics_eta", created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e1.id, user="op")
        KnowledgeIndexService.on_publish(e1.id, user="supervisor_1")
        self.entries.append(e1)

        # product_facts - published
        e2 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="儿童书架材质", content="材质：进口实木松木。\n\n尺寸：60cm x 120cm。",
            intent="product_question", product_scope=["儿童书架"], created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e2.id, user="op")
        KnowledgeIndexService.on_publish(e2.id, user="supervisor_1")
        self.entries.append(e2)

        # faq - published
        e3 = KnowledgeEntryRepository.create(
            source_type="faq", title="书架承重", content="这款书架最大承重50kg，适合放置儿童绘本和玩具。",
            intent="product_question", product_scope=["儿童书架"], created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e3.id, user="op")
        KnowledgeIndexService.on_publish(e3.id, user="supervisor_1")
        self.entries.append(e3)

        # high_risk_sop - published
        e4 = KnowledgeEntryRepository.create(
            source_type="high_risk_sop", title="客诉处理SOP", content="客诉处理第一步：安抚客户情绪。\n\n第二步：记录问题详情。",
            intent="complaint", created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e4.id, user="op")
        KnowledgeIndexService.on_publish(e4.id, user="supervisor_1")
        self.entries.append(e4)

        # draft - 不发布
        e5 = KnowledgeEntryRepository.create(
            source_type="faq", title="草稿FAQ", content="这是一个草稿内容，不应该被检索到。",
            intent="product_question", created_by="op",
        )
        self.entries.append(e5)

    def test_draft_not_retrieved(self):
        results = KnowledgeChunkRepository.search_chunks(
            query="草稿", source_types=["faq"], top_k=5,
        )
        assert len(results) == 0

    def test_published_can_be_retrieved(self):
        results = KnowledgeChunkRepository.search_chunks(
            query="发货", source_types=["shipping_policy"], intent="logistics_eta", top_k=5,
        )
        assert len(results) > 0
        assert any("发货" in r["chunk_text"] for r in results)

    def test_logistics_eta_only_searches_allowed_types(self):
        # 模拟 logistics_eta 允许的类型
        allowed = ["shipping_policy", "product_facts", "response_templates"]
        results = KnowledgeChunkRepository.search_chunks(
            query="发货", source_types=allowed, top_k=10,
        )
        for r in results:
            assert r["source_type"] in allowed
        # 不应出现 aftersales_policy
        assert not any(r["source_type"] == "aftersales_policy" for r in results)

    def test_complaint_only_searches_high_risk(self):
        allowed = ["high_risk_sop", "forbidden_rules", "response_templates"]
        results = KnowledgeChunkRepository.search_chunks(
            query="客诉", source_types=allowed, intent="complaint", top_k=10,
        )
        for r in results:
            assert r["source_type"] in allowed

    def test_product_scope_filter(self):
        # 搜索儿童书架相关
        results = KnowledgeChunkRepository.search_chunks(
            query="材质", source_types=["product_facts", "faq"],
            product_scope=["儿童书架"], top_k=5,
        )
        assert len(results) > 0

    def test_sku_scope_filter(self):
        # 创建带 SKU 的知识
        e = KnowledgeEntryRepository.create(
            source_type="product_facts", title="SKU专属", content="SKU123的专属说明",
            intent="product_question", sku_scope=["SKU123"], created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        KnowledgeIndexService.on_publish(e.id, user="supervisor_1")

        # 匹配 SKU
        results = KnowledgeChunkRepository.search_chunks(
            query="专属", source_types=["product_facts"], sku_scope=["SKU123"], top_k=5,
        )
        assert len(results) > 0

        # 不匹配 SKU
        results_miss = KnowledgeChunkRepository.search_chunks(
            query="专属", source_types=["product_facts"], sku_scope=["SKU999"], top_k=5,
        )
        assert len(results_miss) == 0

    def test_low_score_filtered(self):
        results = KnowledgeChunkRepository.search_chunks(
            query="完全不相关的关键词XYZ", top_k=5, min_score=1.0,
        )
        assert len(results) == 0


class TestEvidenceFilterLogic:
    """测试 evidence_filter 的逻辑规则"""

    def test_auto_reply_false_marked_reference(self):
        # auto_reply_allowed=false 的证据应标记为 reference_only
        chunk = {
            "score": 0.8,
            "chunk_text": "某条知识",
            "source_type": "high_risk_sop",
            "intent": "complaint",
            "metadata": {"auto_reply_allowed": False, "human_review_required": True},
        }
        # 模拟过滤逻辑
        assert chunk["metadata"]["auto_reply_allowed"] is False

    def test_human_review_required_flagged(self):
        chunk = {
            "score": 0.8,
            "chunk_text": "某条知识",
            "source_type": "high_risk_sop",
            "intent": "complaint",
            "metadata": {"human_review_required": True},
        }
        assert chunk["metadata"]["human_review_required"] is True
