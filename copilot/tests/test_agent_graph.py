"""
LangGraph Agent 链路测试 - 覆盖物流/到货时间场景、隐私、降级、trace_steps
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _invoke_graph(msg: str, order_id: str = ""):
    """调用 graph 并返回结果 dict。
    对于使用 sample 订单号的测试，mock JST 查询以返回 sample 数据。"""
    from unittest.mock import patch
    from app.agent.graph import customer_service_graph

    state = {
        "customer_message": msg,
        "order_id": order_id,
        "trace_steps": [],
    }

    # 如果 order_id 是 sample 数据中的假订单号，mock JST 返回 sample 数据
    sample_ids = {"202501010001", "202501010003"}
    if order_id in sample_ids:
        from app.repositories.json_order_repository import JsonOrderRepository
        repo = JsonOrderRepository()
        repo.load()
        order = repo.get_order(order_id)
        logistics = repo.get_logistics(order_id) if order else []

        if order:
            mock_result = {
                "found": True,
                "data": order,
                "source": "jst_live_mock",
                "endpoint": "orders/single/query",
                "query_type": "order_id",
                "duration_ms": 1,
            }
            with patch("app.agent.nodes.jst_live_query.lookup_order_by_identifier", return_value=mock_result):
                return customer_service_graph.invoke(state)

    return customer_service_graph.invoke(state)


def _get_reply_service():
    """获取 ReplyService 实例（无 LLM key）"""
    from app.repositories.json_order_repository import JsonOrderRepository
    from app.repositories.json_product_repository import JsonProductRepository
    from app.repositories.file_knowledge_repository import FileKnowledgeRepository
    from app.repositories.file_policy_repository import FilePolicyRepository
    from app.services.context_builder import ContextBuilder
    from app.services.risk_service import RiskService
    from app.services.output_guard import OutputGuard
    from app.services.reply_service import ReplyService

    order_repo = JsonOrderRepository()
    order_repo.load()
    product_repo = JsonProductRepository()
    product_repo.load()
    knowledge_repo = FileKnowledgeRepository()
    knowledge_repo.load()
    policy_repo = FilePolicyRepository()
    policy_repo.load()

    risk_service = RiskService(policy_repo)
    context_builder = ContextBuilder(order_repo, product_repo, knowledge_repo)
    output_guard = OutputGuard(policy_repo)

    return ReplyService(
        risk_service=risk_service,
        context_builder=context_builder,
        output_guard=output_guard,
        forbidden_claims=[],
    )


# ---------------------------------------------------------------------------
# 1. 有订单号且已发货
# ---------------------------------------------------------------------------

class TestShippedOrder:
    """有订单号 + 已发货"""

    def test_shipped_order_has_logistics(self):
        result = _invoke_graph("我快递大概几天会到？", order_id="202501010001")
        assert result["order_found"] is True
        assert result["shipment_status"] == "shipped"

        # 快递公司、运单号应出现在订单中
        order = result.get("live_order") or result.get("order")
        assert order
        assert order.get("logistics_company")
        assert order.get("l_id")

    def test_shipped_reply_no_promise(self):
        service = _get_reply_service()
        suggestion = service.analyze("订单 202501010001 快递大概几天会到？", order_id="202501010001")
        assert suggestion.suggested_reply
        # 不能承诺“一定明天到”
        assert "一定明天到" not in suggestion.suggested_reply
        assert "保证" not in suggestion.suggested_reply

        ctx = suggestion.context_used
        assert ctx["has_order"] is True
        assert ctx["has_logistics"] is True

    def test_trace_has_order_lookup(self):
        service = _get_reply_service()
        suggestion = service.analyze("我快递大概几天会到？", order_id="202501010001")
        steps = [s for s in suggestion.trace_steps
                 if s.get("step") in ("order_lookup", "live_order_lookup")
                 or s.get("node") in ("jst_live_query", "tool_executor", "tool_executor_node")]
        assert len(steps) >= 1


# ---------------------------------------------------------------------------
# 2. 有订单号但未发货
# ---------------------------------------------------------------------------

class TestPendingOrder:
    """有订单号 + 未发货"""

    def test_pending_order_not_shipped(self):
        result = _invoke_graph("快递大概几天会到？", order_id="202501010003")
        assert result["order_found"] is True
        assert result["shipment_status"] == "pending"

    def test_pending_reply_says_not_shipped(self):
        service = _get_reply_service()
        suggestion = service.analyze("快递大概几天会到？", order_id="202501010003")
        assert suggestion.suggested_reply
        # 不得说已经发货
        assert "已发货" not in suggestion.suggested_reply
        # 不应承诺具体送达时间
        assert "一定" not in suggestion.suggested_reply

        ctx = suggestion.context_used
        assert ctx["order_status"] in ("待发货", "备货中", "待处理")

    def test_pending_has_product_fallback(self):
        result = _invoke_graph("什么时候发货", order_id="202501010003")
        # 应匹配订单商品
        assert result.get("products") or result.get("product_knowledge")


# ---------------------------------------------------------------------------
# 3. 无订单号但有商品名
# ---------------------------------------------------------------------------

class TestNoOrderWithProduct:
    """无订单号，识别商品名"""

    def test_product_match(self):
        result = _invoke_graph("这个书架什么时候发货？")
        assert result.get("matched_product_name") or result.get("product_knowledge")

    def test_product_reply_has_policy(self):
        service = _get_reply_service()
        suggestion = service.analyze("我的椅子发什么快递？")
        assert suggestion.suggested_reply
        # 应包含引导或说明
        assert len(suggestion.suggested_reply) > 10

    def test_no_fake_logistics(self):
        service = _get_reply_service()
        suggestion = service.analyze("书桌发什么快递？")
        # 不能编造具体快递单号
        assert "ZT" not in suggestion.suggested_reply
        assert "DB" not in suggestion.suggested_reply


# ---------------------------------------------------------------------------
# 4. 无订单号且无商品名
# ---------------------------------------------------------------------------

class TestNoOrderNoProduct:
    """无订单号无商品名"""

    def test_guide_user(self):
        service = _get_reply_service()
        suggestion = service.analyze("我快递大概几天会到？")
        assert suggestion.suggested_reply
        assert len(suggestion.suggested_reply) > 10

    def test_no_order_api_called(self):
        result = _invoke_graph("我快递大概几天会到？")
        assert result.get("order_found", False) is False
        assert result.get("order") is None


# ---------------------------------------------------------------------------
# 5. 高风险投诉进入人工复核
# ---------------------------------------------------------------------------

class TestHighRisk:
    """高风险投诉"""

    def test_complaint_needs_review(self):
        service = _get_reply_service()
        suggestion = service.analyze("再不处理我就去12315投诉")
        assert suggestion.requires_human_review is True
        assert suggestion.risk_level == "high"

    def test_bad_review_threat(self):
        service = _get_reply_service()
        suggestion = service.analyze("我要给差评，你们太烂了")
        assert suggestion.requires_human_review is True
        assert suggestion.risk_level == "high"

    def test_no_false_promises(self):
        service = _get_reply_service()
        suggestion = service.analyze("再不处理我就去12315投诉")
        assert "一定赔偿" not in suggestion.suggested_reply
        assert "一定退款" not in suggestion.suggested_reply


# ---------------------------------------------------------------------------
# 6. context_used 不泄露隐私
# ---------------------------------------------------------------------------

class TestPrivacy:
    """隐私保护"""

    def test_no_privacy_in_context(self):
        service = _get_reply_service()
        suggestion = service.analyze("订单什么时候发货", order_id="202501010001")
        ctx_str = json.dumps(suggestion.context_used, ensure_ascii=False)
        assert "receiver_name" not in ctx_str
        assert "receiver_phone" not in ctx_str
        assert "receiver_address" not in ctx_str
        assert "buyer_id" not in ctx_str
        assert "张先生" not in ctx_str
        assert "西湖区" not in ctx_str

    def test_order_items_safe(self):
        service = _get_reply_service()
        suggestion = service.analyze("订单什么时候发货", order_id="202501010001")
        items = suggestion.context_used.get("order_items", [])
        for item in items:
            assert "receiver_name" not in item
            assert "phone" not in item
            assert "address" not in item


# ---------------------------------------------------------------------------
# 7. LLM 未配置仍可用
# ---------------------------------------------------------------------------

class TestNoLLM:
    """LLM 降级"""

    def test_empty_key_has_reply(self):
        import app.config as cfg
        orig_key = cfg.LLM_API_KEY
        cfg.LLM_API_KEY = ""
        try:
            service = _get_reply_service()
            suggestion = service.analyze("请问这款书桌的尺寸")
            assert suggestion.suggested_reply and len(suggestion.suggested_reply) > 10
            assert not suggestion.error
        finally:
            cfg.LLM_API_KEY = orig_key

    def test_empty_key_no_500(self):
        import app.config as cfg
        orig_key = cfg.LLM_API_KEY
        cfg.LLM_API_KEY = ""
        try:
            service = _get_reply_service()
            suggestion = service.analyze("我快递大概几天会到？", order_id="202501010001")
            assert suggestion.suggested_reply
            assert suggestion.error == "" or "GRAPH_EXECUTION_ERROR" not in suggestion.error
        finally:
            cfg.LLM_API_KEY = orig_key

    def test_trace_records_llm_skip(self):
        import app.config as cfg
        orig_key = cfg.LLM_API_KEY
        cfg.LLM_API_KEY = ""
        try:
            service = _get_reply_service()
            suggestion = service.analyze("什么时候发货")
            step_names = [s.get("step") or s.get("node") for s in suggestion.trace_steps]
            assert any(n in step_names for n in ("reply_generated", "generate_reply", "generate_logistics_reply"))
        finally:
            cfg.LLM_API_KEY = orig_key


# ---------------------------------------------------------------------------
# 8. trace_steps 包含关键节点
# ---------------------------------------------------------------------------

class TestTraceSteps:
    """trace_steps 结构"""

    def test_has_key_nodes(self):
        service = _get_reply_service()
        suggestion = service.analyze("我快递大概几天会到？", order_id="202501010001")
        steps = [s.get("step") or s.get("node") for s in suggestion.trace_steps]
        assert "intent_detected" in steps or "detect_intent" in steps
        assert "risk_check" in steps
        assert "generate_reply" in steps or "reply_generated" in steps or "generate_logistics_reply" in steps
        assert "quality_guard" in steps

    def test_has_order_or_fallback_nodes(self):
        service = _get_reply_service()
        suggestion = service.analyze("我快递大概几天会到？", order_id="202501010001")
        steps = [s.get("step") or s.get("node") for s in suggestion.trace_steps]
        # 物流场景应包含订单查询
        has_order = any(
            s in steps for s in (
                "order_lookup",
                "live_order_lookup",
                "jst_live_query",
                "tool_executor",
                "tool_executor_node",
            )
        )
        assert has_order

    def test_trace_has_node_and_status(self):
        service = _get_reply_service()
        suggestion = service.analyze("什么时候发货")
        for step in suggestion.trace_steps:
            assert "node" in step or "step" in step
            # build_base_context 子步骤可能没有 status，但至少有一个可识别字段
            assert any(k in step for k in ("status", "summary", "matched", "found", "source", "mode"))

    def test_no_chain_of_thought(self):
        service = _get_reply_service()
        suggestion = service.analyze("什么时候发货")
        trace_str = json.dumps(suggestion.trace_steps, ensure_ascii=False)
        # 不应包含模型内部思维链标记
        assert "thought" not in trace_str.lower()
        assert "<思考>" not in trace_str
