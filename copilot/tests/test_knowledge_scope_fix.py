#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试知识库 scope 修复：
1. 导入时正确读取关联商品/关联SKU
2. search_chunks 按 product_scope / sku_scope 过滤
3. 数字前缀不混淆（十号 vs 十一号）
4. evidence_filter_node 从顶层字段读取 scope
"""

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_scope_fix_{uuid.uuid4().hex}.db")

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


class TestImportScopeBinding:
    """测试导入时 scope 绑定"""

    def test_preview_item_extracts_product_scope(self):
        from app.services.knowledge_import_service import _build_preview_item

        raw = {
            "关联商品": "一号狮子围兜",
            "关联SKU": "YH117K01B01S30",
            "客户问题": "一号狮子围兜防水吗？",
            "金牌回答": "采用防水面料。",
            "意图": "产品咨询",
            "风险等级": "低",
        }
        item, err = _build_preview_item(raw, 2, "金牌客服问答（增强版）", "faq", "batch_001")
        assert err is None
        assert item["product_scope"] == ["一号狮子围兜"]
        assert item["sku_scope"] == ["YH117K01B01S30"]

    def test_preview_item_extracts_multiple_skus(self):
        from app.services.knowledge_import_service import _build_preview_item

        raw = {
            "关联商品": "三层火箭书架",
            "关联SKU": "YH04K14B01S03, YH04K14B01S09",
            "客户问题": "这款书架结实吗？",
            "金牌回答": "很结实。",
        }
        item, err = _build_preview_item(raw, 3, "金牌客服问答（增强版）", "faq", "batch_001")
        assert err is None
        assert item["product_scope"] == ["三层火箭书架"]
        assert item["sku_scope"] == ["YH04K14B01S03", "YH04K14B01S09"]

    def test_import_creates_entry_with_scope(self):
        from app.services.knowledge_import_service import KnowledgeImportService

        preview = [{
            "source_sheet": "金牌客服问答（增强版）",
            "row_number": 2,
            "source_type": "faq",
            "title": "六号防摔枕适合多大宝宝？",
            "content": "适合1岁以上宝宝。",
            "intent": "产品咨询",
            "risk_level": "low",
            "auto_reply_allowed": True,
            "human_review_required": False,
            "product_scope": ["六号防摔枕"],
            "sku_scope": ["YH115K06B01S03"],
            "warnings": [],
            "errors": [],
            "duplicate_candidate": False,
            "possible_variant": False,
            "content_hash": "abc123",
            "content_generated": False,
            "import_batch_id": "batch_test",
            "raw": {},
        }]
        result = KnowledgeImportService.import_from_preview(preview, user="tester", batch_id="batch_test")
        assert result["success"] == 1

        entry_id = result["created_ids"][0]
        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        assert entry.get_product_scope() == ["六号防摔枕"]
        assert entry.get_sku_scope() == ["YH115K06B01S03"]


class TestSearchChunksScopeFiltering:
    """测试 search_chunks 按 scope 过滤"""

    def setup_method(self):
        # 十一号防摔枕
        e11 = KnowledgeEntryRepository.create(
            source_type="faq", title="这款十一号防摔枕适合多大宝宝？",
            content="亲，这款枕头适合1岁以上的宝宝使用。",
            intent="产品咨询", product_scope=["十一号防摔枕"], sku_scope=["YH115K11B01S03"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e11.id, user="op")
        KnowledgeIndexService.on_publish(e11.id, user="supervisor_1")
        self.e11 = e11

        # 十号防摔枕
        e10 = KnowledgeEntryRepository.create(
            source_type="faq", title="这款十号防摔枕适合多大宝宝？",
            content="亲，这款枕头适合1岁以上的宝宝使用。",
            intent="产品咨询", product_scope=["十号防摔枕"], sku_scope=["YH115K10B01S03"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e10.id, user="op")
        KnowledgeIndexService.on_publish(e10.id, user="supervisor_1")
        self.e10 = e10

        # 十二号防摔枕
        e12 = KnowledgeEntryRepository.create(
            source_type="faq", title="这款十二号防摔枕适合多大宝宝？",
            content="亲，这款枕头适合1岁以上的宝宝使用。",
            intent="产品咨询", product_scope=["十二号防摔枕"], sku_scope=["YH115K12B01S03"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e12.id, user="op")
        KnowledgeIndexService.on_publish(e12.id, user="supervisor_1")
        self.e12 = e12

        # 通用防摔枕（无 scope）
        e_generic = KnowledgeEntryRepository.create(
            source_type="faq", title="防摔枕一般适合多大宝宝？",
            content="一般建议1岁以上使用。",
            intent="产品咨询", created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e_generic.id, user="op")
        KnowledgeIndexService.on_publish(e_generic.id, user="supervisor_1")
        self.e_generic = e_generic

    def test_product_scope_filters_out_mismatch(self):
        """查询十一号时，十号和十二号应被过滤"""
        results = KnowledgeChunkRepository.search_chunks(
            query="十一号防摔枕适合多大宝宝？",
            product_scope=["十一号防摔枕"],
            top_k=10,
        )
        titles = [r["title"] for r in results]
        # 十号和十二号有明确 product_scope 且不匹配，应被过滤
        assert "这款十号防摔枕适合多大宝宝？" not in titles
        assert "这款十二号防摔枕适合多大宝宝？" not in titles
        # 十一号应命中
        assert any("十一号" in t for t in titles)

    def test_generic_without_scope_not_filtered(self):
        """无 scope 的通用知识不应被 product_scope 过滤掉"""
        results = KnowledgeChunkRepository.search_chunks(
            query="防摔枕",
            product_scope=["十一号防摔枕"],
            top_k=20,
            min_score=0.0,
        )
        titles = [r["title"] for r in results]
        # 通用知识无 scope，应保留（即使分数低）
        assert any("一般" in t for t in titles), f"通用知识应保留，实际结果: {titles}"

    def test_sku_scope_filters_exact(self):
        """sku_scope 精确过滤"""
        results = KnowledgeChunkRepository.search_chunks(
            query="防摔枕",
            sku_scope=["YH115K11B01S03"],
            top_k=10,
        )
        sku_scopes = [r.get("sku_scope", []) for r in results if r.get("sku_scope")]
        for ss in sku_scopes:
            assert "YH115K11B01S03" in ss


class TestSearchHybridScopeScore:
    """测试 search_hybrid scope_score"""

    def setup_method(self):
        e1 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="一号狮子围兜材质",
            content="材质：防水涤纶。",
            intent="product_question", product_scope=["一号狮子围兜"], sku_scope=["YH117K01B01S30"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e1.id, user="op")
        KnowledgeIndexService.on_publish(e1.id, user="supervisor_1")

    def test_scope_score_positive_when_product_matches(self):
        results = KnowledgeChunkRepository.search_hybrid(
            query="围兜材质",
            product_name="一号狮子围兜",
            top_k=5,
        )
        matched = [r for r in results if r.get("scope_score", 0) > 0]
        assert len(matched) > 0

    def test_scope_score_negative_when_product_mismatches(self):
        results = KnowledgeChunkRepository.search_hybrid(
            query="围兜材质",
            product_name="二号狮子围兜",
            top_k=5,
        )
        # With strong scope penalty (-2.0), mismatched entries are filtered out.
        # Verify that wrong-scope entries do NOT appear in results.
        wrong_scope = ["一号狮子围兜", "皇冠椅", "床护栏"]
        for r in results:
            scope = r.get("product_scope", [])
            for ws in wrong_scope:
                for s in scope:
                    assert ws not in s, (
                        f"Wrong-scope entry still in results: scope={scope}, "
                        f"chunk_id={r.get('chunk_id')}, scope_score={r.get('scope_score')}"
                    )


class TestNumberPrefixPenalty:
    """测试数字前缀不混淆"""

    def setup_method(self):
        e10 = KnowledgeEntryRepository.create(
            source_type="faq", title="十号防摔枕能洗吗？",
            content="外套可拆洗。", intent="产品咨询",
            product_scope=["十号防摔枕"], created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e10.id, user="op")
        KnowledgeIndexService.on_publish(e10.id, user="supervisor_1")

        e11 = KnowledgeEntryRepository.create(
            source_type="faq", title="十一号防摔枕能洗吗？",
            content="外套可拆洗。", intent="产品咨询",
            product_scope=["十一号防摔枕"], created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e11.id, user="op")
        KnowledgeIndexService.on_publish(e11.id, user="supervisor_1")

    def test_eleven_not_returned_as_ten(self):
        """查询十一号时，十号不应排在前面"""
        results = KnowledgeChunkRepository.search_chunks(
            query="十一号防摔枕能洗吗？",
            product_scope=["十一号防摔枕"],
            top_k=5,
        )
        # 十号有明确 product_scope 且不匹配，应被过滤
        titles = [r["title"] for r in results]
        assert "十号防摔枕能洗吗？" not in titles


class TestEvidenceFilterNodeScope:
    """测试 evidence_filter_node 从顶层字段读取 scope"""

    def test_rejects_sku_mismatch_from_top_level(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "围兜材质",
                    "source_type": "faq",
                    "intent": "product_question",
                    "chunk_text": "防水涤纶",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "sku_scope": ["YH117K01B01S30"],
                    "product_scope": ["一号狮子围兜"],
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["faq"],
            "slots": {"sku_code": "YH999"},
        }
        result = evidence_filter_node(state)
        # sku 不匹配应被拒绝
        assert len(result["filtered_evidence"]) == 0
        assert len(result["knowledge_evidence"]) == 0

    def test_accepts_sku_match_from_top_level(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "围兜材质",
                    "source_type": "faq",
                    "intent": "product_question",
                    "chunk_text": "防水涤纶",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "sku_scope": ["YH117K01B01S30"],
                    "product_scope": ["一号狮子围兜"],
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["faq"],
            "slots": {"sku_code": "YH117K01B01S30"},
        }
        result = evidence_filter_node(state)
        assert len(result["filtered_evidence"]) == 1
        assert result["knowledge_evidence"][0]["scope_match"] is True

    def test_rejects_product_scope_mismatch(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "喂养柜材质",
                    "source_type": "faq",
                    "intent": "product_question",
                    "chunk_text": "E1级板材",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "sku_scope": [],
                    "product_scope": ["一号喂养柜"],
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["faq"],
            "slots": {},
            "matched_product_name": "儿童书架",
        }
        result = evidence_filter_node(state)
        # 喂养柜与儿童书架不匹配，应被拒绝
        assert len(result["filtered_evidence"]) == 0
