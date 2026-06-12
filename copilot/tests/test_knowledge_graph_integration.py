"""
测试 LangGraph 单场景接入：product_question
验证：
1. 能按 intent 检索正确 source_type
2. draft 知识不被检索
3. published 知识可被检索
4. auto_reply_allowed=false 不自动回复
5. human_review_required=true 进人工
6. factual_guard 不允许编造商品事实
"""

import os
import tempfile
import uuid
import pytest

_test_db_path = None


_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_knowledge_graph_{uuid.uuid4().hex}.db")

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
from app.services.knowledge_index_service import KnowledgeIndexService


class TestProductQuestionRAG:
    """product_question 场景的 RAG 接入测试"""

    def setup_method(self):
        # 创建 published product_facts
        e1 = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="儿童书架材质",
            content="材质：进口实木松木。表面环保水性漆。",
            intent="product_question",
            product_scope=["儿童书架"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e1.id, user="op")
        KnowledgeIndexService.on_publish(e1.id, user="supervisor_1")
        self.published_fact_id = e1.id

        # 创建 published faq
        e2 = KnowledgeEntryRepository.create(
            source_type="faq",
            title="书架安装难吗",
            content="安装很简单，配有详细说明书和安装工具。",
            intent="product_question",
            product_scope=["儿童书架"],
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e2.id, user="op")
        KnowledgeIndexService.on_publish(e2.id, user="supervisor_1")

        # 创建 draft（不应被检索）
        e3 = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="草稿材质",
            content="这是草稿内容",
            intent="product_question",
            created_by="op",
        )
        self.draft_id = e3.id

        # 创建 auto_reply_allowed=false
        e4 = KnowledgeEntryRepository.create(
            source_type="faq",
            title="退货政策",
            content="退货需保持商品原状。",
            intent="product_question",
            auto_reply_allowed=False,
            human_review_required=True,
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e4.id, user="op")
        KnowledgeIndexService.on_publish(e4.id, user="supervisor_1")

    def test_product_question_routes_to_rag(self):
        """product_question 意图应走 RAG 或 Tool Registry 链"""
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "这个儿童书架是什么材质？",
            "trace_steps": [],
        })
        steps = [s.get("node", "") for s in result.get("trace_steps", [])]
        # 新链路走 tool_planner → tool_executor_node，旧链路走 knowledge_scope_router → rag_retrieve
        uses_tool_registry = "tool_planner" in steps and "tool_executor" in steps
        uses_old_chain = "knowledge_scope_router" in steps and "rag_retrieve" in steps
        assert uses_tool_registry or uses_old_chain, f"Neither tool_registry nor old RAG chain found in steps: {steps}"
        assert "evidence_builder" in steps

    def test_published_knowledge_retrieved(self):
        """published 知识可被检索到"""
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        results = KnowledgeChunkRepository.search_chunks(
            query="材质", source_types=["product_facts"], intent="product_question", top_k=5
        )
        assert len(results) > 0
        assert any("实木" in r["chunk_text"] for r in results)

    def test_draft_not_retrieved(self):
        """draft 知识不应被检索"""
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        results = KnowledgeChunkRepository.search_chunks(
            query="草稿", source_types=["product_facts"], intent="product_question", top_k=5
        )
        assert len(results) == 0

    def test_intent_filters_source_type(self):
        """product_question 只允许 product_facts/product_mapping/faq"""
        from app.agent.nodes.knowledge_scope_router import INTENT_SOURCE_MAP
        allowed = INTENT_SOURCE_MAP.get("product_question", [])
        assert "product_facts" in allowed
        assert "faq" in allowed
        assert "shipping_policy" not in allowed
        assert "aftersales_policy" not in allowed

    def test_auto_reply_false_marked_reference(self):
        """auto_reply_allowed=false 的证据标记为 reference_only"""
        from app.agent.nodes.evidence_filter_node import evidence_filter_node
        state = {
            "retrieved_chunks": [
                {"chunk_text": "退货政策", "source_type": "faq", "intent": "product_question",
                 "score": 0.8, "metadata": {"auto_reply_allowed": False, "human_review_required": True}},
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts", "faq"],
            "trace_steps": [],
        }
        result = evidence_filter_node(state)
        assert len(result["filtered_evidence"]) == 1
        assert result["filtered_evidence"][0]["reference_only"] is True

    def test_factual_guard_blocks_fabrication(self):
        """无 product_facts 时不得编造商品参数"""
        from app.agent.nodes.factual_guard import factual_guard
        state = {
            "suggested_reply": "这款书架采用碳纤维材质，尺寸是 200x300cm。",
            "intent": "product_question",
            "evidence": {
                "verified_facts": [],
                "estimated_facts": [],
                "unknowns": [],
                "conflicts": [],
            },
            "guard_warnings": [],
        }
        result = factual_guard(state)
        warnings = result["guard_warnings"]
        assert any("product_facts" in w or "编造" in w for w in warnings)

    def test_product_question_trace_has_evidence(self):
        """完整链路 trace 中应包含知识库证据"""
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "这个儿童书架是什么材质？",
            "trace_steps": [],
        })
        evidence = result.get("evidence", {})
        # evidence_builder 应把 product_facts 放入 verified_facts
        verified = evidence.get("verified_facts", [])
        assert any("实木" in f.get("fact", "") for f in verified)
