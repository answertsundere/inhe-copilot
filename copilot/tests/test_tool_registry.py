"""
Tool Registry 测试 — 验证工具注册、策略路由、执行器行为

覆盖需求：
1. allowed_tools 不包含非法工具
2. required_tools 缺失时自动补齐
3. LLM 选择 forbidden_tool 会被拒绝
4. 无 LLM key 时直接执行 required_tools
5. product_question 不会调用 JST
6. logistics_with_order 必须调用 JST 工具
7. complaint 必须调用 SOP 工具并 need_human_review=true
8. tool timeout 不导致 500
9. tool_results 能进入 evidence_builder
10. trace_steps 记录工具调用
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import unittest.mock as mock


# ---------------------------------------------------------------------------
# A. ToolRegistry 基本注册
# ---------------------------------------------------------------------------

class TestToolRegistry:
    """验证工具注册中心基本能力"""

    def test_default_tools_registered(self):
        """默认注册 7 个工具"""
        from app.agent.tools.registry import get_tool_registry
        registry = get_tool_registry()
        names = registry.tool_names
        assert "jst_lookup_order_tool" in names
        assert "jst_lookup_outbound_tool" in names
        assert "jst_lookup_tracking_tool" in names
        assert "rag_search_tool" in names
        assert "product_resolver_tool" in names
        assert "sop_lookup_tool" in names
        assert "template_select_tool" in names
        assert len(names) == 7

    def test_tool_spec_has_handler(self):
        """每个工具都有 handler"""
        from app.agent.tools.registry import get_tool_registry
        registry = get_tool_registry()
        for name in registry.tool_names:
            spec = registry.get(name)
            assert spec is not None, f"{name} 未注册"
            assert spec.handler is not None, f"{name} 无 handler"

    def test_tool_spec_has_schemas(self):
        """每个工具都有 input/output schema"""
        from app.agent.tools.registry import get_tool_registry
        registry = get_tool_registry()
        for name in registry.tool_names:
            spec = registry.get(name)
            assert spec.input_schema, f"{name} 无 input_schema"
            assert spec.output_schema, f"{name} 无 output_schema"

    def test_get_tool_metas(self):
        """get_tool_metas 返回工具元数据"""
        from app.agent.tools.registry import get_tool_registry
        registry = get_tool_registry()
        metas = registry.get_tool_metas(["jst_lookup_order_tool"])
        assert len(metas) == 1
        assert metas[0]["name"] == "jst_lookup_order_tool"
        assert "description" in metas[0]


# ---------------------------------------------------------------------------
# B. response_strategy_router: allowed/required/forbidden
# ---------------------------------------------------------------------------

class TestStrategyToolLists:
    """验证 response_strategy_router 输出正确的工具权限列表"""

    def _route(self, intent, risk_level="low", identifier_type="", platform_trade_id="", order_id="", tracking_no=""):
        from app.agent.nodes.response_strategy_router import response_strategy_router
        state = {
            "intent": intent,
            "risk_level": risk_level,
            "slots": {
                "identifier_type": identifier_type,
                "platform_trade_id": platform_trade_id,
                "order_id": order_id,
                "tracking_no": tracking_no,
                "possible_numeric_id": "",
                "product_name": "",
            },
            "is_logistics_time_commitment": False,
            "trace_steps": [],
        }
        return response_strategy_router(state)

    def test_logistics_with_platform_trade_id(self):
        """物流+外部交易号 → required=[jst_lookup_outbound_tool]"""
        result = self._route("logistics_eta", identifier_type="platform_trade_id",
                             platform_trade_id="5118207015382036103")
        assert "jst_lookup_outbound_tool" in result["required_tools"]
        assert "jst_lookup_outbound_tool" in result["allowed_tools"]
        # 不允许使用错误的 JST 工具
        assert "jst_lookup_order_tool" in result["forbidden_tools"]
        assert "jst_lookup_tracking_tool" in result["forbidden_tools"]

    def test_logistics_trace_with_platform_trade_id(self):
        result = self._route("logistics_trace", identifier_type="platform_trade_id",
                             platform_trade_id="6926666820903533935")
        assert result["response_strategy"] == "logistics_with_order"
        assert "jst_lookup_outbound_tool" in result["required_tools"]
        assert result["answer_mode"] == "verified"

    def test_logistics_with_internal_order_id(self):
        """物流+内部订单号 → required=[jst_lookup_order_tool]"""
        result = self._route("logistics_eta", identifier_type="internal_order_id", order_id="1636367")
        assert "jst_lookup_order_tool" in result["required_tools"]
        assert "jst_lookup_outbound_tool" in result["forbidden_tools"]

    def test_logistics_with_tracking_no(self):
        """物流+快递单号 → required=[jst_lookup_tracking_tool]"""
        result = self._route("logistics_eta", identifier_type="tracking_no", tracking_no="SF0229477422177")
        assert "jst_lookup_tracking_tool" in result["required_tools"]
        assert "jst_lookup_order_tool" in result["forbidden_tools"]

    def test_product_question_forbidden_jst(self):
        """商品咨询 → required=[product_resolver_tool, rag_search_tool], 禁止所有 JST 工具"""
        result = self._route("product_question")
        assert "product_resolver_tool" in result["required_tools"]
        assert "rag_search_tool" in result["required_tools"]
        assert "jst_lookup_order_tool" in result["forbidden_tools"]
        assert "jst_lookup_outbound_tool" in result["forbidden_tools"]
        assert "jst_lookup_tracking_tool" in result["forbidden_tools"]

    def test_complaint_requires_sop(self):
        """投诉 → required=[sop_lookup_tool]"""
        result = self._route("complaint", risk_level="high")
        assert "sop_lookup_tool" in result["required_tools"]
        assert "jst_lookup_order_tool" in result["forbidden_tools"]

    def test_clarification_no_jst(self):
        """通用 → 禁止 JST 工具，无 required"""
        result = self._route("general")
        assert result["required_tools"] == []
        assert "jst_lookup_order_tool" in result["forbidden_tools"]

    def test_allowed_tools_always_include_common(self):
        """所有策略都包含 rag_search_tool 和 template_select_tool"""
        for intent in ("logistics_eta", "product_question", "complaint", "general"):
            result = self._route(intent, risk_level="low" if intent != "complaint" else "high",
                                 identifier_type="internal_order_id" if "logistics" in intent else "")
            assert "rag_search_tool" in result["allowed_tools"], f"{intent}: rag_search_tool missing"
            assert "template_select_tool" in result["allowed_tools"], f"{intent}: template_select_tool missing"


# ---------------------------------------------------------------------------
# C. ToolExecutor: 执行和超时
# ---------------------------------------------------------------------------

class TestToolExecutor:
    """验证工具执行器行为"""

    def test_execute_single_success(self):
        """单工具执行成功"""
        from app.agent.tools.executor import ToolExecutor
        from app.agent.tools.base import ToolSpec

        def mock_handler(inputs, state):
            return {"found": True, "o_id": "123"}

        executor = ToolExecutor()
        executor._registry._tools["test_tool"] = ToolSpec(
            name="test_tool", description="test", handler=mock_handler,
        )

        plan = [{"tool_name": "test_tool", "inputs": {"id": "123"}}]
        result = executor.execute_plan(plan, {}, total_timeout_ms=5000)

        assert result["tool_results"]["test_tool"]["found"] is True
        assert result["tool_traces"][0]["status"] == "success"
        assert result["timed_out"] is False

    def test_execute_timeout_no_500(self):
        """工具超时不会导致 500，而是记录错误"""
        from app.agent.tools.executor import ToolExecutor
        from app.agent.tools.base import ToolSpec
        import time

        def slow_handler(inputs, state):
            time.sleep(0.1)
            return {"found": False}

        executor = ToolExecutor()
        executor._registry._tools["slow_tool"] = ToolSpec(
            name="slow_tool", description="slow", handler=slow_handler, timeout_ms=50,
        )

        plan = [{"tool_name": "slow_tool", "inputs": {}}]
        result = executor.execute_plan(plan, {}, total_timeout_ms=200)

        # 不抛异常，正常返回
        assert "tool_results" in result
        assert result["tool_results"]["slow_tool"]["found"] is False

    def test_execute_exception_caught(self):
        """工具抛异常不会传播，而是记录到 trace"""
        from app.agent.tools.executor import ToolExecutor
        from app.agent.tools.base import ToolSpec

        def bad_handler(inputs, state):
            raise ValueError("boom")

        executor = ToolExecutor()
        executor._registry._tools["bad_tool"] = ToolSpec(
            name="bad_tool", description="bad", handler=bad_handler,
        )

        plan = [{"tool_name": "bad_tool", "inputs": {}}]
        result = executor.execute_plan(plan, {}, total_timeout_ms=5000)

        assert "error" in result["tool_results"]["bad_tool"]
        assert result["tool_traces"][0]["status"] == "error"
        assert result["tool_traces"][0]["error_code"] == "ValueError"

    def test_not_found_tool_skipped(self):
        """未注册的工具被跳过"""
        from app.agent.tools.executor import ToolExecutor

        executor = ToolExecutor()
        plan = [{"tool_name": "nonexistent_tool", "inputs": {}}]
        result = executor.execute_plan(plan, {}, total_timeout_ms=5000)

        assert "nonexistent_tool" not in result["tool_results"]
        assert any(t.get("error_code") == "tool_not_found" for t in result["tool_traces"])


# ---------------------------------------------------------------------------
# D. plan_tools: required_tools 自动补齐
# ---------------------------------------------------------------------------

class TestPlanTools:
    """验证 tool_planner 行为"""

    def test_auto_required_when_no_llm(self):
        """无 LLM key 时直接执行 required_tools"""
        from app.agent.tools.executor import plan_tools

        state = {
            "normalized_message": "5118207015382036103 快递到哪了",
            "intent": "logistics_eta",
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5118207015382036103",
                "order_id": "",
                "tracking_no": "",
            },
            "allowed_tools": ["jst_lookup_outbound_tool", "rag_search_tool", "template_select_tool"],
            "required_tools": ["jst_lookup_outbound_tool"],
            "forbidden_tools": ["jst_lookup_order_tool", "jst_lookup_tracking_tool"],
            "allowed_source_types": ["shipping_policy"],
            "trace_steps": [],
        }

        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=None):
            result = plan_tools(state)

        plan = result["tool_plan"]
        tool_names = [c["tool_name"] for c in plan]
        assert "jst_lookup_outbound_tool" in tool_names
        assert result["tool_planner_source"] in (
            "auto_required",
            "explicit_logistics_identifier_fast_path",
        )

    def test_forbidden_tool_removed_from_plan(self):
        """forbidden_tool 从计划中移除"""
        from app.agent.tools.executor import plan_tools

        state = {
            "normalized_message": "test",
            "intent": "logistics_eta",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": ""},
            "allowed_tools": ["rag_search_tool", "template_select_tool"],
            "required_tools": ["rag_search_tool"],
            "forbidden_tools": ["jst_lookup_order_tool"],
            "allowed_source_types": ["faq"],
            "trace_steps": [],
        }

        # Simulate LLM returning a forbidden tool
        llm_plan = [
            {"tool_name": "rag_search_tool", "inputs": {"query": "test"}},
            {"tool_name": "jst_lookup_order_tool", "inputs": {"identifier": "123"}},
        ]
        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=llm_plan):
            result = plan_tools(state)

        tool_names = [c["tool_name"] for c in result["tool_plan"]]
        assert "jst_lookup_order_tool" not in tool_names
        assert "rag_search_tool" in tool_names

    def test_required_tool_auto_added(self):
        """LLM 遗漏 required_tool 时自动补上"""
        from app.agent.tools.executor import plan_tools

        state = {
            "normalized_message": "test",
            "intent": "complaint",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": ""},
            "allowed_tools": ["sop_lookup_tool", "rag_search_tool", "template_select_tool"],
            "required_tools": ["sop_lookup_tool"],
            "forbidden_tools": [],
            "allowed_source_types": ["high_risk_sop"],
            "trace_steps": [],
        }

        # LLM only selects rag_search_tool, missing sop_lookup_tool
        llm_plan = [{"tool_name": "rag_search_tool", "inputs": {"query": "test"}}]
        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=llm_plan):
            result = plan_tools(state)

        tool_names = [c["tool_name"] for c in result["tool_plan"]]
        assert "sop_lookup_tool" in tool_names, "required_tool should be auto-added"
        assert "rag_search_tool" in tool_names

    def test_rag_scope_inputs_use_system_defaults_over_llm_guess(self):
        """LLM 不应覆盖策略路由给出的 RAG source_types 和商品范围"""
        from app.agent.tools.executor import plan_tools

        state = {
            "normalized_message": "一号狮子围兜防水吗？",
            "intent": "product_question",
            "matched_product_name": "一号狮子围兜",
            "slots": {
                "identifier_type": "none",
                "product_name": "一号狮子围兜",
                "sku_name": "",
                "sku_code": "",
            },
            "allowed_tools": ["product_resolver_tool", "rag_search_tool", "template_select_tool"],
            "required_tools": ["product_resolver_tool", "rag_search_tool"],
            "forbidden_tools": ["jst_lookup_order_tool"],
            "allowed_source_types": ["product_facts", "product_mapping", "faq"],
            "trace_steps": [],
        }
        llm_plan = [
            {"tool_name": "rag_search_tool", "inputs": {
                "query": "一号狮子围兜防水吗？",
                "source_types": ["product_info"],
                "product_name": "商品",
            }},
        ]

        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=llm_plan):
            result = plan_tools(state)

        rag_call = next(c for c in result["tool_plan"] if c["tool_name"] == "rag_search_tool")
        assert rag_call["inputs"]["source_types"] == ["product_facts", "product_mapping", "faq"]
        assert rag_call["inputs"]["product_name"] == "一号狮子围兜"
        assert rag_call["inputs"]["product_scope"] == ["一号狮子围兜"]


# ---------------------------------------------------------------------------
# E. tool_results 进入 evidence_builder
# ---------------------------------------------------------------------------

class TestToolResultsInEvidence:
    """验证 tool_results 能被 evidence_builder 消费"""

    def test_outbound_tool_result_generates_order_facts(self):
        """jst_lookup_outbound_tool 结果生成 order_facts"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [],
            "intent": "logistics_eta",
            "trace_steps": [],
            "tool_results": {
                "jst_lookup_outbound_tool": {
                    "found": True,
                    "o_id": "1636367",
                    "status": "Confirmed",
                    "logistics_company": "顺丰速运",
                    "l_id": "SF0229477422177",
                    "send_date": "2026-06-01 13:22:39",
                    "endpoint": "orders/out/simple/query",
                },
            },
        }
        result = evidence_builder(state)
        order_facts = result["evidence"]["order_facts"]
        assert len(order_facts) >= 1
        assert any(f.get("source_type") == "jst_sales_out" for f in order_facts)

    def test_sop_tool_result_generates_sop_evidence(self):
        """sop_lookup_tool 结果生成 sop_evidence"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [],
            "intent": "complaint",
            "trace_steps": [],
            "tool_results": {
                "sop_lookup_tool": {
                    "sops": [{"scenario": "投诉处理", "steps": ["安抚"]}],
                    "forbidden_claims": ["保证"],
                },
            },
        }
        result = evidence_builder(state)
        sop = result["evidence"]["sop_evidence"]
        assert len(sop) >= 1
        assert sop[0]["source_type"] == "high_risk_sop"


# ---------------------------------------------------------------------------
# F. trace_steps 记录工具调用
# ---------------------------------------------------------------------------

class TestToolTraceSteps:
    """验证 trace_steps 正确记录工具调用"""

def test_tool_executor_node_produces_traces():
        """tool_executor_node 输出 trace_steps"""
        from app.agent.tools.executor import tool_executor_node
        from app.agent.tools.base import ToolSpec
        from app.agent.tools.registry import get_tool_registry

        registry = get_tool_registry()
        # Use a real registered tool with mocked handler
        original_handler = registry.get("rag_search_tool").handler
        registry.get("rag_search_tool").handler = lambda inputs, state: {"chunks": [], "count": 0}

        try:
            state = {
                "tool_plan": [
                    {"tool_name": "rag_search_tool", "inputs": {"query": "test"}},
                ],
                "trace_steps": [],
            }
            result = tool_executor_node(state)

            assert len(result["trace_steps"]) >= 2  # at least main trace + tool trace
            tool_trace = [t for t in result["trace_steps"] if t.get("tool_name") == "rag_search_tool"]
            assert len(tool_trace) >= 1
            assert tool_trace[0]["status"] == "success"
            assert "duration_ms" in tool_trace[0]
        finally:
            registry.get("rag_search_tool").handler = original_handler


# ---------------------------------------------------------------------------
# G. ToolSpec 安全检查
# ---------------------------------------------------------------------------

class TestToolSpecSafety:
    """验证 ToolSpec.is_allowed 安全检查"""

    def test_allowed_intent_passes(self):
        from app.agent.tools.base import ToolSpec
        spec = ToolSpec(name="t", description="d", allowed_intents=["logistics_eta"])
        assert spec.is_allowed("logistics_eta", "low") is True

    def test_disallowed_intent_blocked(self):
        from app.agent.tools.base import ToolSpec
        spec = ToolSpec(name="t", description="d", allowed_intents=["logistics_eta"])
        assert spec.is_allowed("product_question", "low") is False

    def test_forbidden_intent_blocked(self):
        from app.agent.tools.base import ToolSpec
        spec = ToolSpec(name="t", description="d", forbidden_intents=["complaint"])
        assert spec.is_allowed("complaint", "low") is False

    def test_empty_allowed_means_all(self):
        from app.agent.tools.base import ToolSpec
        spec = ToolSpec(name="t", description="d", allowed_intents=[])
        assert spec.is_allowed("anything", "low") is True

    def test_sop_tool_is_readonly(self):
        from app.agent.tools.registry import get_tool_registry
        spec = get_tool_registry().get("sop_lookup_tool")
        assert spec.read_only is True
        assert spec.requires_human_review is True
