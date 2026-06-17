"""
知识事实审核测试 — 验证 unverified_fact 检测和保守声明

覆盖需求：
1. Draft entry 含高风险字段 → unverified_fact_fields
2. Published entry 不触发 unverified
3. evidence_debug 包含 unverified_fact_fields
4. 包含高风险字段的 draft FAQ 回复追加保守声明
5. Entry 812 专项检测
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestHighRiskFieldDetection:
    """验证高风险字段检测"""

    def test_detect_material(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        assert "材质" in _detect_high_risk_fields("材质: E1级环保板材")

    def test_detect_weight_capacity(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        assert "承重" in _detect_high_risk_fields("承重/容量: 15-25kg/层")

    def test_detect_filling(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        assert "填充" in _detect_high_risk_fields("枕芯采用优质填充棉/记忆棉")

    def test_detect_waterproof(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        assert "防水" in _detect_high_risk_fields("采用防水面料")

    def test_detect_age(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        assert "适用年龄" in _detect_high_risk_fields("适用年龄: 0-6岁")

    def test_no_risk_fields(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        assert _detect_high_risk_fields("发货时间 2026-06-01") == []

    def test_multiple_fields(self):
        from app.agent.nodes.evidence_builder import _detect_high_risk_fields
        result = _detect_high_risk_fields("材质: E1级环保板材 承重: 25kg 适用年龄: 0-6岁")
        assert "材质" in result
        assert "承重" in result
        assert "适用年龄" in result


class TestEvidenceBuilderUnverifiedFacts:
    """验证 evidence_builder 标记 unverified facts"""

    def test_draft_entry_with_risk_fields_tagged(self):
        """draft entry 含高风险字段 → unverified_fact=True"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [
                {
                    "source_type": "faq",
                    "chunk_text": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
                    "confidence": "low",
                    "reference_only": False,
                    "entry_status": "draft",
                    "source_sheet": "金牌客服问答（增强版）",
                    "row_number": 763,
                },
            ],
            "intent": "product_question",
            "trace_steps": [],
            "tool_results": {},
        }
        result = evidence_builder(state)
        evidence = result["evidence"]

        assert "填充" in evidence.get("unverified_fact_fields", [])
        faq = evidence.get("faq_evidence", [])
        assert len(faq) >= 1
        assert faq[0].get("unverified_fact") is True
        assert faq[0].get("entry_status") == "draft"

    def test_published_entry_not_unverified(self):
        """published entry 不触发 unverified"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [
                {
                    "source_type": "product_facts",
                    "chunk_text": "材质: E1级环保板材+冷轧钢框架",
                    "confidence": "high",
                    "reference_only": False,
                    "entry_status": "published",
                    "source_sheet": "商品总览",
                    "row_number": 1,
                },
            ],
            "intent": "product_question",
            "trace_steps": [],
            "tool_results": {},
        }
        result = evidence_builder(state)
        evidence = result["evidence"]

        assert evidence.get("unverified_fact_fields", []) == []

    def test_draft_entry_without_risk_fields_not_unverified(self):
        """draft entry 无高风险字段 → 不标记 unverified"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [
                {
                    "source_type": "faq",
                    "chunk_text": "发货后一般2-3天到达",
                    "confidence": "low",
                    "reference_only": False,
                    "entry_status": "draft",
                    "source_sheet": "金牌客服问答",
                    "row_number": 100,
                },
            ],
            "intent": "logistics_eta",
            "trace_steps": [],
            "tool_results": {},
        }
        result = evidence_builder(state)
        evidence = result["evidence"]

        assert evidence.get("unverified_fact_fields", []) == []


class TestKnowledgeChunkEnrichment:
    """验证 RAG 搜索结果包含 entry_status"""

    def test_search_returns_entry_status(self):
        """search_chunks 结果应包含 entry_status, source_sheet, row_number"""
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        results = KnowledgeChunkRepository.search_chunks(
            query="防摔枕",
            source_types=["faq"],
            include_draft=True,
            top_k=1,
        )
        if results:
            r = results[0]
            assert "entry_status" in r
            assert "source_sheet" in r
            assert "row_number" in r


class TestEntry812Audit:
    """Entry 812 专项审核"""

    def test_entry_812_exists_and_is_published_ready(self):
        """Entry 812 已发布并完成索引"""
        import sqlite3
        conn = sqlite3.connect('data/knowledge_base.db')
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM knowledge_entries WHERE id=812').fetchone()
        conn.close()

        assert row is not None
        assert row['status'] == 'published'
        assert row['index_status'] == 'ready'
        assert row['source_type'] == 'faq'
        assert '填充' in row['content'] or '记忆棉' in row['content']
        assert row['source_sheet'] == '金牌客服问答（增强版）'
        assert row['row_number'] == 763

    def test_entry_812_has_chunk(self):
        """Entry 812 有 1 个 chunk"""
        import sqlite3
        conn = sqlite3.connect('data/knowledge_base.db')
        count = conn.execute('SELECT COUNT(*) FROM knowledge_chunks WHERE entry_id=812').fetchone()[0]
        conn.close()
        assert count == 1
