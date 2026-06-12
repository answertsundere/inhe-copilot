"""
图结构测试 - 校验 customer_service_graph 的编译、节点、边、路径和隐私
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestGraphCompile:
    """1. graph 可正常 compile"""

    def test_graph_compiles(self):
        from app.agent.graph import customer_service_graph
        assert customer_service_graph is not None
        graph = customer_service_graph.get_graph()
        assert graph is not None
        nodes = list(graph.nodes.keys())
        assert len(nodes) > 0
        edges = list(graph.edges)
        assert len(edges) > 0


class TestCoreNodesExist:
    """2. 核心节点都存在"""

    REQUIRED_NODES = {
        "normalize_input",
        "detect_intent",
        "risk_check",
        "build_base_context",
        "route_by_intent",
        "jst_live_query",
        "slot_extract",
        "identifier_router",
        "resolve_order_status",
        "resolve_product_identity",
        "match_shipping_policy",
        "generate_reply",
        "generate_logistics_reply",
        "quality_guard",
        "human_review_gate",
    }

    def test_all_core_nodes_present(self):
        from app.agent.graph import customer_service_graph
        graph = customer_service_graph.get_graph()
        node_ids = set(graph.nodes.keys())
        missing = self.REQUIRED_NODES - node_ids
        assert not missing, f"缺少核心节点: {missing}"

    def test_start_and_end_nodes(self):
        from app.agent.graph import customer_service_graph
        graph = customer_service_graph.get_graph()
        assert "__start__" in graph.nodes
        assert "__end__" in graph.nodes

    def test_post_generation_grounding_guard_after_factual_guard(self):
        """factual_guard 之后必经 post_generation_grounding_guard"""
        from app.agent.graph import customer_service_graph
        graph = customer_service_graph.get_graph()
        edges = list(graph.edges)
        factual_outgoing = [e.target for e in edges if e.source == "factual_guard"]
        assert "post_generation_grounding_guard" in factual_outgoing, (
            f"factual_guard 的出边缺少 post_generation_grounding_guard，"
            f"实际出边: {factual_outgoing}"
        )

    def test_post_generation_grounding_guard_before_build_response(self):
        """post_generation_grounding_guard 之后必经 build_response"""
        from app.agent.graph import customer_service_graph
        graph = customer_service_graph.get_graph()
        edges = list(graph.edges)
        grounding_outgoing = [e.target for e in edges if e.source == "post_generation_grounding_guard"]
        assert "build_response" in grounding_outgoing, (
            f"post_generation_grounding_guard 的出边缺少 build_response，"
            f"实际出边: {grounding_outgoing}"
        )

    def test_gold_csr_before_factual_guard(self):
        """gold_csr_reply_builder 之后必经 factual_guard"""
        from app.agent.graph import customer_service_graph
        graph = customer_service_graph.get_graph()
        edges = list(graph.edges)
        gold_csr_outgoing = [e.target for e in edges if e.source == "gold_csr_reply_builder"]
        assert "factual_guard" in gold_csr_outgoing, (
            f"gold_csr_reply_builder 的出边缺少 factual_guard，"
            f"实际出边: {gold_csr_outgoing}"
        )

    def test_no_duplicate_grounding_edges(self):
        """post_generation_grounding_guard 不在 factual_guard 之前出现"""
        from app.agent.graph import customer_service_graph
        graph = customer_service_graph.get_graph()
        edges = list(graph.edges)
        # 检查是否有从 generate_reply / generate_logistics_reply / gold_csr 直接到 grounding 的边
        bad_sources = {"generate_reply", "generate_logistics_reply", "hallucination_guard", "gold_csr_reply_builder"}
        for e in edges:
            if e.source in bad_sources and e.target == "post_generation_grounding_guard":
                pytest.fail(
                    f"发现 grounding_guard 在 factual_guard 之前的边: {e.source} -> {e.target}"
                )


class TestLogisticsTraceSteps:
    """3. 物流场景 trace_steps 包含关键节点"""

    def test_shipped_order_trace_has_key_nodes(self):
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "我快递大概几天会到？",
            "order_id": "202501010001",
            "trace_steps": [],
        })
        steps = [s.get("node") or s.get("step") for s in result.get("trace_steps", [])]
        assert "detect_intent" in steps or "intent_detected" in steps
        assert "risk_check" in steps
        assert any(s in steps for s in ("generate_reply", "reply_generated", "generate_logistics_reply"))
        assert "quality_guard" in steps
        # 物流场景应包含订单查询相关节点
        has_order_query = any(
            s in steps for s in (
                "jst_live_query",
                "order_lookup", "live_order_lookup",
            )
        )
        assert has_order_query, f"物流场景缺少订单查询节点，实际节点: {steps}"

    def test_no_order_trace_has_product_match(self):
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "这个书架什么时候发货？",
            "order_id": "",
            "trace_steps": [],
        })
        steps = [s.get("node") or s.get("step") for s in result.get("trace_steps", [])]
        # 无订单号时走 RAG 知识库检索，不再走 product_resolve
        assert any(s in steps for s in ("rag_retrieve", "knowledge_scope_router", "evidence_filter", "evidence_builder"))


class TestHighRiskPath:
    """4. 高风险投诉不进入普通物流查询路径"""

    def test_complaint_still_routes_correctly(self):
        """高风险消息仍会走完整 graph，但 generate_reply 会生成安抚回复"""
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "再不处理我就去12315投诉",
            "order_id": "",
            "trace_steps": [],
        })
        assert result["risk_level"] == "high"
        assert result["requires_human_review"] is True
        # 高风险没有订单号时，不应进入 JST 查询（因为没订单号）
        steps = [s.get("node") for s in result.get("trace_steps", [])]
        # 没有 order_id，所以 route_by_intent 会走 skip_order 分支
        assert "jst_live_query" not in steps

    def test_complaint_with_order_id(self):
        """高风险 + 有订单号：意图为 complaint，不走物流查询链路，但最终标记复核"""
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "我要投诉你们，订单 202501010001",
            "order_id": "202501010001",
            "trace_steps": [],
        })
        assert result["risk_level"] == "high"
        assert result["requires_human_review"] is True
        # complaint 意图走高风险短路，不走订单查询
        steps = [s.get("node") for s in result.get("trace_steps", [])]
        assert "jst_live_query" not in steps

    def test_logistics_with_order_id(self):
        """物流意图 + 有订单号：走完整订单查询链路"""
        from app.agent.graph import customer_service_graph
        result = customer_service_graph.invoke({
            "customer_message": "我快递大概几天会到？",
            "order_id": "202501010001",
            "trace_steps": [],
        })
        steps = [s.get("node") for s in result.get("trace_steps", [])]
        assert "jst_live_query" in steps


class TestPrivacy:
    """5. context_used 不泄露隐私"""

    def test_context_used_no_privacy_fields(self):
        from app.services.reply_service import ReplyService
        from app.repositories.json_order_repository import JsonOrderRepository
        from app.repositories.json_product_repository import JsonProductRepository
        from app.repositories.file_knowledge_repository import FileKnowledgeRepository
        from app.repositories.file_policy_repository import FilePolicyRepository
        from app.services.context_builder import ContextBuilder
        from app.services.risk_service import RiskService
        from app.services.output_guard import OutputGuard

        order_repo = JsonOrderRepository()
        order_repo.load()
        product_repo = JsonProductRepository()
        product_repo.load()
        knowledge_repo = FileKnowledgeRepository()
        knowledge_repo.load()
        policy_repo = FilePolicyRepository()
        policy_repo.load()

        service = ReplyService(
            risk_service=RiskService(policy_repo),
            context_builder=ContextBuilder(order_repo, product_repo, knowledge_repo),
            output_guard=OutputGuard(policy_repo),
        )

        suggestion = service.analyze("订单什么时候发货", order_id="202501010001")
        ctx = suggestion.context_used
        ctx_str = json.dumps(ctx, ensure_ascii=False)

        forbidden = ["receiver_name", "receiver_phone", "receiver_address", "buyer_id", "手机号", "地址", "张先生", "西湖区"]
        for f in forbidden:
            assert f not in ctx_str, f"context_used 泄露隐私字段: {f}"

    def test_order_items_safe(self):
        from app.services.reply_service import ReplyService
        from app.repositories.json_order_repository import JsonOrderRepository
        from app.repositories.json_product_repository import JsonProductRepository
        from app.repositories.file_knowledge_repository import FileKnowledgeRepository
        from app.repositories.file_policy_repository import FilePolicyRepository
        from app.services.context_builder import ContextBuilder
        from app.services.risk_service import RiskService
        from app.services.output_guard import OutputGuard

        order_repo = JsonOrderRepository()
        order_repo.load()
        product_repo = JsonProductRepository()
        product_repo.load()
        knowledge_repo = FileKnowledgeRepository()
        knowledge_repo.load()
        policy_repo = FilePolicyRepository()
        policy_repo.load()

        service = ReplyService(
            risk_service=RiskService(policy_repo),
            context_builder=ContextBuilder(order_repo, product_repo, knowledge_repo),
            output_guard=OutputGuard(policy_repo),
        )

        suggestion = service.analyze("订单什么时候发货", order_id="202501010001")
        items = suggestion.context_used.get("order_items", [])
        for item in items:
            assert "receiver_name" not in item
            assert "phone" not in item
            assert "address" not in item
            assert "buyer_id" not in item
