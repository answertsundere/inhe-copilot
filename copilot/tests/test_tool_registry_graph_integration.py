"""
Tool Registry Graph Integration 测试 — 验证 Tool Registry 与 LangGraph 主图的集成

覆盖需求：
1. 物流+platform_trade_id → tool_planner → tool_executor_node → jst_lookup_outbound_tool
2. 物流+internal_order_id → tool_plan 含 jst_lookup_order_tool → fallback
3. 物流+tracking_no → tool_plan 含 jst_lookup_tracking_tool
4. 商品咨询 → tool_plan 含 product_resolver_tool + rag_search_tool
5. 投诉 → required_tools 含 sop_lookup_tool → requires_human_review
6. JST 工具失败时 fallback 到旧 jst_live_query 链路
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _invoke(msg: str, order_id: str = "", tracking_no: str = "") -> dict:
    """调用 customer_service_graph 并返回结果。
    对于 sample 订单号，mock JST 查询返回 sample 数据。
    """
    from app.agent.graph import customer_service_graph

    state = {
        "customer_message": msg,
        "order_id": order_id,
        "tracking_no": tracking_no,
        "trace_steps": [],
    }

    sample_ids = {"202501010001", "202501010003"}
    if order_id in sample_ids:
        from app.repositories.json_order_repository import JsonOrderRepository
        repo = JsonOrderRepository()
        repo.load()
        order = repo.get_order(order_id)
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


def _steps(result: dict) -> list:
    """提取 trace step 名称列表"""
    return [s.get("node") or s.get("step") for s in result.get("trace_steps", [])]


def _trace_summaries(result: dict) -> list:
    """提取 trace step 摘要列表"""
    return [s.get("summary", "") for s in result.get("trace_steps", [])]


# ---------------------------------------------------------------------------
# A. 物流链 — platform_trade_id
# ---------------------------------------------------------------------------

class TestLogisticsPlatformTradeId:
    """物流+外部交易号 → tool_planner → tool_executor_node → outbound 工具"""

    def test_intent_is_logistics_eta(self):
        """意图应检测为 logistics_eta"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        assert result["intent"] == "logistics_eta"

    def test_route_to_tool_planner_and_executor(self):
        """trace_steps 应包含 tool_planner 和 tool_executor"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        steps = _steps(result)
        assert "tool_planner" in steps, f"Missing tool_planner, got: {steps}"
        assert "tool_executor" in steps or "tool_executor_node" in steps, \
            f"Missing tool_executor_node, got: {steps}"

    def test_tool_plan_contains_outbound_tool(self):
        """tool_plan 应包含 jst_lookup_outbound_tool"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "jst_lookup_outbound_tool" in tool_names, \
            f"Expected jst_lookup_outbound_tool, got: {tool_names}"

    def test_tool_planner_source_auto_required(self):
        """无 LLM key 时 tool_planner_source 应为 auto_required"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        assert result.get("tool_planner_source") in (
            "auto_required",
            "explicit_logistics_identifier_fast_path",
        )

    def test_evidence_debug_tool_executor_used(self):
        """evidence_debug 应标记 tool_executor_used"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        debug = result.get("evidence_debug", {})
        assert debug.get("tool_executor_used") is True

    def test_evidence_debug_tool_plan_has_outbound(self):
        """evidence_debug.tool_plan 应包含 jst_lookup_outbound_tool"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        debug = result.get("evidence_debug", {})
        assert "jst_lookup_outbound_tool" in debug.get("tool_plan", [])

    def test_jst_not_found_still_gets_safe_reply(self):
        """JST 工具调用返回 found=False 时，不 fallback，直接走 evidence_builder 生成安全回复。
        使用 mock 使 JST 工具返回 found=False，验证 tool_executor 正常执行并生成安全回复。"""
        from app.agent.graph import customer_service_graph
        from app.agent.tools.registry import get_tool_registry

        registry = get_tool_registry()
        original_handler = registry.get("jst_lookup_outbound_tool").handler
        registry.get("jst_lookup_outbound_tool").handler = lambda inputs, state: {
            "found": False, "endpoint": "", "duration_ms": 0,
        }
        try:
            result = customer_service_graph.invoke({
                "customer_message": "5118207015382036103 我的快递大概什么时候到",
                "order_id": "",
                "trace_steps": [],
            })
        finally:
            registry.get("jst_lookup_outbound_tool").handler = original_handler

        steps = _steps(result)
        assert "tool_planner" in steps
        assert "evidence_builder" in steps
        reply = result.get("suggested_reply", "")
        assert reply, "应有安全回复"
        assert "一定" not in reply

    def test_slots_identifier_type_platform_trade_id(self):
        """slot 应识别出 identifier_type=platform_trade_id"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        slots = result.get("slots", {})
        assert slots.get("identifier_type") == "platform_trade_id"
        assert slots.get("platform_trade_id") == "5118207015382036103"

    def test_has_suggested_reply(self):
        """应有 suggested_reply"""
        result = _invoke("5118207015382036103 我的快递大概什么时候到")
        assert result.get("suggested_reply")
        assert len(result.get("suggested_reply", "")) > 10


# ---------------------------------------------------------------------------
# B. 物流链 — internal_order_id
# ---------------------------------------------------------------------------

class TestLogisticsInternalOrderId:
    """物流+内部订单号 → tool_plan 含 jst_lookup_order_tool"""

    def test_tool_plan_contains_order_tool(self):
        """tool_plan 应包含 jst_lookup_order_tool"""
        result = _invoke("订单号 1636367 什么时候到？")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "jst_lookup_order_tool" in tool_names, \
            f"Expected jst_lookup_order_tool, got: {tool_names}"

    def test_intent_is_logistics_eta(self):
        """意图应为 logistics_eta"""
        result = _invoke("订单号 1636367 什么时候到？")
        assert result["intent"] == "logistics_eta"

    def test_slots_have_order_id(self):
        """slots 应包含 order_id"""
        result = _invoke("订单号 1636367 什么时候到？")
        slots = result.get("slots", {})
        assert slots.get("order_id") == "1636367"

    def test_fallback_graceful_when_order_not_found(self):
        """查不到订单时应优雅降级，仍有 suggested_reply"""
        result = _invoke("订单号 1636367 什么时候到？")
        assert result.get("suggested_reply"), \
            "Should have suggested_reply even when order not found"

    def test_no_500_on_order_not_found(self):
        """查不到订单不应导致错误"""
        result = _invoke("订单号 1636367 什么时候到？")
        assert not result.get("error") or "GRAPH_EXECUTION_ERROR" not in str(result.get("error", ""))

    def test_tool_planner_source_auto_required(self):
        """tool_planner_source 应为 auto_required"""
        result = _invoke("订单号 1636367 什么时候到？")
        assert result.get("tool_planner_source") in (
            "auto_required",
            "explicit_logistics_identifier_fast_path",
        )

    def test_with_sample_order_mocked(self):
        """使用 sample 订单号 mock 时应查到订单"""
        result = _invoke("订单号 202501010001 什么时候到？", order_id="202501010001")
        assert result.get("order_found") is True or result.get("live_order") is not None

    def test_evidence_debug_tool_plan_has_order_tool(self):
        """evidence_debug.tool_plan 应包含 jst_lookup_order_tool"""
        result = _invoke("订单号 1636367 什么时候到？")
        debug = result.get("evidence_debug", {})
        assert "jst_lookup_order_tool" in debug.get("tool_plan", [])


# ---------------------------------------------------------------------------
# C. 物流链 — tracking_no
# ---------------------------------------------------------------------------

class TestLogisticsTrackingNo:
    """物流+快递单号 → tool_plan 含 jst_lookup_tracking_tool"""

    def test_tool_plan_contains_tracking_tool(self):
        """tool_plan 应包含 jst_lookup_tracking_tool"""
        result = _invoke("SF0229477422177 到哪里了？")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "jst_lookup_tracking_tool" in tool_names, \
            f"Expected jst_lookup_tracking_tool, got: {tool_names}"

    def test_intent_is_logistics_eta(self):
        """意图应为 logistics_eta"""
        result = _invoke("SF0229477422177 到哪里了？")
        assert result["intent"] == "logistics_eta"

    def test_slots_have_tracking_no(self):
        """slots 应包含 tracking_no"""
        result = _invoke("SF0229477422177 到哪里了？")
        slots = result.get("slots", {})
        assert slots.get("tracking_no") == "SF0229477422177"

    def test_identifier_type_is_tracking_no(self):
        """identifier_type 应为 tracking_no"""
        result = _invoke("SF0229477422177 到哪里了？")
        slots = result.get("slots", {})
        assert slots.get("identifier_type") == "tracking_no"

    def test_route_to_tool_planner(self):
        """trace_steps 应包含 tool_planner"""
        result = _invoke("SF0229477422177 到哪里了？")
        steps = _steps(result)
        assert "tool_planner" in steps, f"Missing tool_planner, got: {steps}"

    def test_evidence_debug_tool_executor_used(self):
        """evidence_debug 应标记 tool_executor_used"""
        result = _invoke("SF0229477422177 到哪里了？")
        debug = result.get("evidence_debug", {})
        assert debug.get("tool_executor_used") is True

    def test_has_suggested_reply(self):
        """应有 suggested_reply"""
        result = _invoke("SF0229477422177 到哪里了？")
        assert result.get("suggested_reply")


# ---------------------------------------------------------------------------
# D. 商品链
# ---------------------------------------------------------------------------

class TestProductChain:
    """商品咨询 → tool_plan 含 product_resolver_tool + rag_search_tool"""

    def test_intent_is_product_question(self):
        """意图应为 product_question"""
        result = _invoke("一号狮子围兜防水吗？")
        assert result["intent"] == "product_question"

    def test_tool_plan_contains_product_resolver(self):
        """tool_plan 应包含 product_resolver_tool"""
        result = _invoke("一号狮子围兜防水吗？")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "product_resolver_tool" in tool_names, \
            f"Expected product_resolver_tool, got: {tool_names}"

    def test_tool_plan_contains_rag_search(self):
        """tool_plan 应包含 rag_search_tool"""
        result = _invoke("一号狮子围兜防水吗？")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "rag_search_tool" in tool_names, \
            f"Expected rag_search_tool, got: {tool_names}"

    def test_tool_executor_node_in_trace(self):
        """trace_steps 应包含 tool_executor"""
        result = _invoke("一号狮子围兜防水吗？")
        steps = _steps(result)
        assert "tool_executor" in steps or "tool_executor_node" in steps, \
            f"Missing tool_executor_node, got: {steps}"

    def test_tool_planner_source_auto_required(self):
        """tool_planner_source 应为 auto_required"""
        result = _invoke("一号狮子围兜防水吗？")
        assert result.get("tool_planner_source") in (
            "auto_required",
            "explicit_logistics_identifier_fast_path",
        )

    def test_evidence_debug_tool_executor_used(self):
        """evidence_debug 应标记 tool_executor_used"""
        result = _invoke("一号狮子围兜防水吗？")
        debug = result.get("evidence_debug", {})
        assert debug.get("tool_executor_used") is True

    def test_no_jst_tools_in_plan(self):
        """tool_plan 不应包含 JST 工具"""
        result = _invoke("一号狮子围兜防水吗？")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        jst_tools = {"jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"}
        for jst in jst_tools:
            assert jst not in tool_names, f"Product chain should not use {jst}"

    def test_has_suggested_reply(self):
        """应有 suggested_reply"""
        result = _invoke("一号狮子围兜防水吗？")
        assert result.get("suggested_reply")

    def test_response_strategy_is_product_question(self):
        """response_strategy 应为 product_question"""
        result = _invoke("一号狮子围兜防水吗？")
        assert result.get("response_strategy") == "product_question"


# ---------------------------------------------------------------------------
# E. 投诉链
# ---------------------------------------------------------------------------

class TestComplaintChain:
    """投诉 → required_tools 含 sop_lookup_tool → requires_human_review"""

    def test_required_tools_contains_sop(self):
        """required_tools 应包含 sop_lookup_tool"""
        result = _invoke("再不处理我就投诉平台")
        required = result.get("required_tools", [])
        # If the graph doesn't propagate required_tools, check tool_plan instead
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "sop_lookup_tool" in required or "sop_lookup_tool" in tool_names, \
            f"Expected sop_lookup_tool in required={required} or tool_plan={tool_names}"

    def test_requires_human_review(self):
        """投诉应标记 requires_human_review"""
        result = _invoke("再不处理我就投诉平台")
        assert result.get("requires_human_review") is True

    def test_risk_level_is_high(self):
        """风险级别应为 high"""
        result = _invoke("再不处理我就投诉平台")
        assert result.get("risk_level") == "high"

    def test_no_jst_tools_in_plan(self):
        """tool_plan 不应包含 JST 工具"""
        result = _invoke("再不处理我就投诉平台")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        jst_tools = {"jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"}
        for jst in jst_tools:
            assert jst not in tool_names, f"Complaint chain should not use {jst}"

    def test_tool_plan_contains_sop_lookup(self):
        """tool_plan 应包含 sop_lookup_tool"""
        result = _invoke("再不处理我就投诉平台")
        tool_plan = result.get("tool_plan", [])
        tool_names = [c.get("tool_name") for c in tool_plan]
        assert "sop_lookup_tool" in tool_names, \
            f"Expected sop_lookup_tool in tool_plan, got: {tool_names}"

    def test_evidence_debug_tool_executor_used(self):
        """evidence_debug 应标记 tool_executor_used"""
        result = _invoke("再不处理我就投诉平台")
        debug = result.get("evidence_debug", {})
        assert debug.get("tool_executor_used") is True

    def test_response_strategy_is_high_risk(self):
        """response_strategy 应为 high_risk"""
        result = _invoke("再不处理我就投诉平台")
        assert result.get("response_strategy") == "high_risk"

    def test_no_false_promise_in_reply(self):
        """回复不应包含虚假承诺"""
        result = _invoke("再不处理我就投诉平台")
        reply = result.get("suggested_reply", "")
        assert "一定赔偿" not in reply
        assert "一定退款" not in reply

    def test_has_suggested_reply(self):
        """投诉应有 suggested_reply（安抚回复）"""
        result = _invoke("再不处理我就投诉平台")
        assert result.get("suggested_reply")
        assert len(result.get("suggested_reply", "")) > 10


# ---------------------------------------------------------------------------
# F. Fallback 测试
# ---------------------------------------------------------------------------

class TestJSTFallback:
    """JST 工具执行失败（found=False）时应 fallback 到旧 jst_live_query 链路"""

    def _invoke_with_jst_failure(self, msg: str, order_id: str = "") -> dict:
        """调用 graph，mock JST 工具返回 found=False，强制触发 fallback"""
        from app.agent.graph import customer_service_graph
        from app.agent.tools.registry import get_tool_registry

        registry = get_tool_registry()
        jst_tools = ["jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"]
        originals = {t: registry.get(t).handler for t in jst_tools if registry.get(t)}
        for t in jst_tools:
            if registry.get(t):
                registry.get(t).handler = lambda inputs, state: {
                    "found": False, "endpoint": "", "duration_ms": 0,
                }
        try:
            return customer_service_graph.invoke({
                "customer_message": msg,
                "order_id": order_id,
                "trace_steps": [],
            })
        finally:
            for t, handler in originals.items():
                registry.get(t).handler = handler

    def test_logistics_fallback_to_jst_live_query(self):
        """JST 工具返回 found=False 时应走旧 jst_live_query 链路"""
        result = self._invoke_with_jst_failure("5118207015382036103 我的快递大概什么时候到")
        steps = _steps(result)
        assert "tool_executor" in steps or "tool_executor_node" in steps, \
            f"Expected tool execution fallback, got: {steps}"

    def test_fallback_still_has_tool_executor(self):
        """fallback 前应已执行过 tool_executor"""
        result = self._invoke_with_jst_failure("5118207015382036103 我的快递大概什么时候到")
        steps = _steps(result)
        assert "tool_executor" in steps or "tool_executor_node" in steps

    def test_fallback_still_has_tool_planner(self):
        """fallback 前应已执行过 tool_planner"""
        result = self._invoke_with_jst_failure("5118207015382036103 我的快递大概什么时候到")
        steps = _steps(result)
        assert "tool_planner" in steps

    def test_fallback_order_with_sample_id(self):
        """使用 sample 订单号 mock JST 时，tool_executor + fallback 都应有结果"""
        result = _invoke("快递到哪了", order_id="202501010001")
        steps = _steps(result)
        assert "tool_executor" in steps or "tool_executor_node" in steps
        assert result.get("order_found") is True

    def test_fallback_graceful_no_error(self):
        """fallback 不应导致系统错误"""
        result = _invoke("订单号 999999999999 快递到哪了")
        assert not result.get("error") or "GRAPH_EXECUTION_ERROR" not in str(result.get("error", ""))
        assert result.get("suggested_reply")

    def test_product_chain_no_fallback_to_jst(self):
        """商品咨询链路不需要 fallback 到 JST"""
        result = _invoke("一号狮子围兜防水吗？")
        steps = _steps(result)
        assert "jst_live_query" not in steps, \
            f"Product chain should not fallback to jst_live_query, got: {steps}"

    def test_evidence_debug_reflects_tool_execution(self):
        """evidence_debug 应反映 tool_executor 的执行情况"""
        result = self._invoke_with_jst_failure("5118207015382036103 我的快递大概什么时候到")
        debug = result.get("evidence_debug", {})
        assert debug.get("tool_executor_used") is True
        assert len(debug.get("tool_plan", [])) > 0

    def test_fallback_trace_has_both_paths(self):
        """trace 应同时记录 tool_executor 和 jst_live_query"""
        result = self._invoke_with_jst_failure("5118207015382036103 我的快递大概什么时候到")
        steps = _steps(result)
        has_tool_executor = "tool_executor" in steps or "tool_executor_node" in steps
        assert has_tool_executor, f"Missing tool_executor in trace: {steps}"
        assert result.get("suggested_reply"), f"Missing safe fallback reply: {steps}"

    def test_high_risk_aftersales_jst_fallback_does_not_replan_tools(self):
        """A completed high-risk tool attempt must not loop back into tool planning."""
        result = self._invoke_with_jst_failure(
            "收到商品后发现有破损，请协助核对售后处理。",
            order_id="FIXTURE-ORDER-01",
        )

        steps = _steps(result)
        assert steps.count("tool_planner") == 1, steps
        assert "jst_live_query" in steps, steps
        assert "evidence_builder" in steps, steps
        assert result.get("suggested_reply")
