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
from types import SimpleNamespace


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
        assert set(metas[0]) == {"name", "description", "input_schema"}
        assert "freshness_class" not in metas[0]

    def test_llm_tool_planner_payload_excludes_internal_freshness(
        self,
        monkeypatch,
    ):
        from app.agent.tools.executor import _try_llm_tool_selection
        from app.agent.tools.registry import get_tool_registry

        captured = {}

        class FakeClient:
            api_key = "configured-for-test"
            model = "test-model"

            def create_chat_completion(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"tool_calls": []}'
                            )
                        )
                    ]
                )

        monkeypatch.setattr(
            "app.llm.client.get_llm_client",
            lambda: FakeClient(),
        )

        _try_llm_tool_selection(
            {
                "customer_message": "generic request",
                "intent": "product_question",
                "slots": {},
            },
            ["rag_search_tool"],
            [],
            get_tool_registry(),
        )

        assert "freshness_class" not in captured["messages"][0]["content"]

    def test_default_jst_inputs_use_structured_sidebar_identifiers(self):
        from app.agent.tools.executor import _build_default_inputs

        inputs = _build_default_inputs({
            "customer_message": "现在到哪里了",
            "slots": {},
            "copilot_context": {
                "platform_order_id": "platform-order-ref",
                "platform_trade_id": "platform-trade-ref",
                "tracking_no": "tracking-ref",
            },
        })

        assert inputs["jst_lookup_order_tool"] == {
            "identifier": "platform-order-ref",
            "identifier_type": "platform_order_id",
        }
        assert inputs["jst_lookup_outbound_tool"] == {
            "outer_so_id": "platform-trade-ref",
        }
        assert inputs["jst_lookup_tracking_tool"] == {
            "tracking_no": "tracking-ref",
        }


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
        result = executor.execute_plan(
            plan,
            {"copilot_context": {"eval_replay_options": {"external_tool_timeout_seconds": 0.05}}},
            total_timeout_ms=200,
        )

        # 不抛异常，正常返回
        assert "tool_results" in result
        assert result["tool_results"]["slow_tool"]["found"] is False
        assert result["tool_traces"][0]["status"] == "timeout"
        assert result["tool_traces"][0]["error_code"] == "timeout"
        assert result["requires_human_review"] is True
        assert result["timed_out"] is True

    def test_replay_disabled_external_tool_is_not_called(self):
        from app.agent.tools.executor import ToolExecutor
        from app.agent.tools.base import ToolSpec

        def should_not_call(_inputs, _state):
            raise AssertionError("external tool should be disabled in replay")

        executor = ToolExecutor()
        executor._registry._tools["jst_lookup_order_tool"] = ToolSpec(
            name="jst_lookup_order_tool",
            description="jst",
            handler=should_not_call,
        )

        result = executor.execute_plan(
            [{"tool_name": "jst_lookup_order_tool", "inputs": {"identifier": "LOCAL_ORDER"}}],
            {"copilot_context": {"eval_replay_options": {"disable_external_tools": True}}},
            total_timeout_ms=5000,
        )

        assert result["tool_results"]["jst_lookup_order_tool"]["safe_fallback_reason"] == "external_tools_disabled_for_replay"
        assert result["tool_traces"][0]["status"] == "skipped"
        assert result["tool_traces"][0]["error_code"] == "external_tools_disabled_for_replay"
        assert result["requires_human_review"] is True
        assert result["external_tool_control"]["disabled_tools"] == ["jst_lookup_order_tool"]

    def test_jst_live_query_honors_replay_external_tool_disable(self, monkeypatch):
        from app.agent.nodes.jst_live_query import jst_live_query

        def should_not_call(*_args, **_kwargs):
            raise AssertionError("legacy JST fallback should be disabled in replay")

        monkeypatch.setattr("app.agent.nodes.jst_live_query.lookup_order_by_identifier", should_not_call)

        result = jst_live_query({
            "slots": {"identifier_type": "internal_order_id", "order_id": "LOCAL_ORDER"},
            "copilot_context": {"eval_replay_options": {"disable_external_tools": True}},
        })

        assert result["order_found"] is False
        assert result["requires_human_review"] is True
        assert result["jst_fallback_reason"] == "external_tools_disabled_for_replay"
        assert result["trace_steps"][-1]["error_code"] == "external_tools_disabled_for_replay"

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

    def test_outbound_tool_result_hydrates_single_product_identity_context(self):
        """侧边栏订单查询结果应把商品身份留在内部上下文，不写入客户回复。"""
        from app.agent.tools.executor import _extract_legacy_fields

        fields = _extract_legacy_fields(
            {
                "jst_lookup_outbound_tool": {
                    "found": True,
                    "o_id": "internal-order-ref",
                    "status": "Confirmed",
                    "logistics_company": "测试快递",
                    "l_id": "TRACKING1234567890",
                    "items": [
                        {
                            "name": "内部商品名称",
                            "sku_id": "SKU-INTERNAL-001",
                            "i_id": "ITEM-INTERNAL-001",
                            "qty": 1,
                            "price": 99,
                        }
                    ],
                    "endpoint": "orders/out/simple/query",
                }
            },
            {
                "slots": {
                    "identifier_type": "platform_trade_id",
                    "platform_trade_id": "platform-order-ref",
                }
            },
        )

        identity = fields["order_product_identity"]
        assert identity["status"] == "resolved"
        assert identity["source"] == "jst_order_items"
        assert identity["matched_product_name"] == "内部商品名称"
        assert identity["internal_product_name"] == "内部商品名称"
        assert identity["sku_id"] == "SKU-INTERNAL-001"
        assert identity["i_id"] == "ITEM-INTERNAL-001"
        assert fields["matched_product_name"] == "内部商品名称"

    def test_outbound_tool_result_does_not_guess_product_for_multiple_primary_items(self):
        """多商品订单没有可靠上下文时不得随意选择第一项。"""
        from app.agent.tools.executor import _extract_legacy_fields

        fields = _extract_legacy_fields(
            {
                "jst_lookup_outbound_tool": {
                    "found": True,
                    "o_id": "internal-order-ref",
                    "status": "Confirmed",
                    "items": [
                        {"name": "商品甲", "sku_id": "SKU-A", "i_id": "ITEM-A", "price": 10},
                        {"name": "商品乙", "sku_id": "SKU-B", "i_id": "ITEM-B", "price": 20},
                    ],
                }
            },
            {
                "normalized_message": "我的快递到哪里了",
                "slots": {
                    "identifier_type": "platform_trade_id",
                    "platform_trade_id": "platform-order-ref",
                },
            },
        )

        identity = fields["order_product_identity"]
        assert identity["status"] == "ambiguous"
        assert identity["reason"] == "ambiguous_multi_item_order"
        assert "matched_product_name" not in fields

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


def test_tool_executor_rebuilds_product_context_with_same_turn_order_identity(
    monkeypatch,
):
    from app.agent.tools.executor import tool_executor_node
    from app.agent.tools.registry import get_tool_registry

    registry = get_tool_registry()
    outbound = registry.get("jst_lookup_outbound_tool")
    rag = registry.get("rag_search_tool")
    original_outbound_handler = outbound.handler
    original_rag_handler = rag.handler
    captured = {}

    outbound.handler = lambda _inputs, _state: {
        "found": True,
        "o_id": "internal-order-ref",
        "status": "Confirmed",
        "items": [{
            "name": "resolved fixture product",
            "sku_id": "SKU-FIXTURE-001",
            "i_id": "ITEM-FIXTURE-001",
            "qty": 1,
        }],
        "endpoint": "orders/out/simple/query",
    }
    rag.handler = lambda _inputs, _state: {
        "chunks": [],
        "retrieval_mode": "fixture",
    }

    def fake_build_product_context_pack(state, **_kwargs):
        captured.update(state)
        return {"facts": [], "stats": {}}

    monkeypatch.setattr(
        "app.services.product_context_pack_service.build_product_context_pack",
        fake_build_product_context_pack,
    )

    try:
        result = tool_executor_node({
            "tool_plan": [
                {
                    "tool_name": "jst_lookup_outbound_tool",
                    "inputs": {"platform_trade_id": "platform-order-ref"},
                },
                {
                    "tool_name": "rag_search_tool",
                    "inputs": {"query": "general product assessment"},
                },
            ],
            "customer_message": "general product assessment",
            "normalized_message": "general product assessment",
            "query_fact_type": "product_overview",
            "allowed_source_types": ["product_facts"],
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "platform-order-ref",
            },
            "trace_steps": [],
        })
    finally:
        outbound.handler = original_outbound_handler
        rag.handler = original_rag_handler

    assert result["order_product_identity"]["status"] == "resolved"
    assert captured["order_product_identity"] == result["order_product_identity"]
    assert captured["matched_product_name"] == "resolved fixture product"


def test_tool_executor_builds_product_context_for_exact_identity_without_rag_plan(
    monkeypatch,
):
    from app.agent.tools.executor import tool_executor_node
    from app.agent.tools.registry import get_tool_registry

    registry = get_tool_registry()
    sop = registry.get("sop_lookup_tool")
    original_sop_handler = sop.handler
    captured = {}

    sop.handler = lambda _inputs, _state: {"sops": []}

    def fake_build_product_context_pack(state, **_kwargs):
        captured.update(state)
        return {
            "facts": [{"evidence_id": "hub-material-fact"}],
            "stats": {"facts": 1},
        }

    monkeypatch.setattr(
        "app.services.product_context_pack_service.build_product_context_pack",
        fake_build_product_context_pack,
    )

    try:
        result = tool_executor_node({
            "tool_plan": [
                {
                    "tool_name": "sop_lookup_tool",
                    "inputs": {"scenario": "review-only product guidance"},
                },
            ],
            "customer_message": "Can you give bounded practical guidance?",
            "normalized_message": "Can you give bounded practical guidance?",
            "query_fact_type": "",
            "allowed_source_types": ["faq", "response_templates"],
            "order_product_identity": {
                "status": "resolved",
                "i_id": "PRODUCT-FIXTURE-001",
                "sku_id": "SKU-FIXTURE-001",
                "matched_product_name": "fixture product",
            },
            "slots": {
                "i_id": "PRODUCT-FIXTURE-001",
                "sku_code": "SKU-FIXTURE-001",
            },
            "copilot_context": {
                "i_id": "PRODUCT-FIXTURE-001",
                "sku_code": "SKU-FIXTURE-001",
            },
            "trace_steps": [],
        })
    finally:
        sop.handler = original_sop_handler

    assert captured["order_product_identity"]["status"] == "resolved"
    assert result["product_context_pack"]["facts"] == [
        {"evidence_id": "hub-material-fact"}
    ]
    assert result["product_context_pack_stats"] == {"facts": 1}


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


def test_outbound_tool_uses_provider_scoped_shop_identity(monkeypatch):
    from app.agent.tools.registry import _handle_jst_lookup_outbound

    captured = {}

    def fake_lookup(identifier, identifier_type, **kwargs):
        captured.update({
            "identifier": identifier,
            "identifier_type": identifier_type,
            **kwargs,
        })
        return {
            "found": False,
            "query_type": "platform_trade_id",
            "duration_ms": 10,
            "safe_fallback_reason": "not_found",
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = _handle_jst_lookup_outbound(
        {"outer_so_id": "platform-order-ref"},
        {"copilot_context": {"shop_id": "logical-store", "jst_shop_id": "provider-store"}},
    )

    assert captured == {
        "identifier": "platform-order-ref",
        "identifier_type": "platform_trade_id",
        "shop_id": "provider-store",
    }
    assert result["found"] is False
    assert result["lookup_complete"] is True


def test_outbound_tool_passes_structured_shop_platform(monkeypatch):
    from app.agent.tools.registry import _handle_jst_lookup_outbound

    captured = {}

    def fake_lookup(identifier, identifier_type, **kwargs):
        captured.update({"identifier": identifier, "identifier_type": identifier_type, **kwargs})
        return {
            "found": False,
            "query_type": "platform_trade_id",
            "duration_ms": 10,
            "safe_fallback_reason": "sales_outbound_record_not_visible",
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = _handle_jst_lookup_outbound(
        {"outer_so_id": "platform-order-ref"},
        {
            "copilot_context": {
                "shop_id": "logical-store",
                "jst_shop_id": "provider-store",
                "shop_platform": "tmall",
            }
        },
    )

    assert captured == {
        "identifier": "platform-order-ref",
        "identifier_type": "platform_trade_id",
        "shop_id": "provider-store",
        "shop_platform": "tmall",
    }
    assert result["found"] is False
    assert result["lookup_complete"] is True


def test_outbound_tool_does_not_mark_malformed_miss_complete(monkeypatch):
    from app.agent.tools.registry import _handle_jst_lookup_outbound

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        lambda *_args, **_kwargs: {"found": False},
    )

    result = _handle_jst_lookup_outbound(
        {"outer_so_id": "platform-order-ref"},
        {"copilot_context": {"jst_shop_id": "provider-store"}},
    )

    assert result["lookup_complete"] is False


def test_outbound_tool_ignores_legacy_qimen_metadata_and_uses_standard_jst(monkeypatch):
    from app.agent.tools.registry import _handle_jst_lookup_outbound

    captured = {}

    def fake_lookup(identifier, identifier_type, **kwargs):
        captured.update({"identifier": identifier, "identifier_type": identifier_type, **kwargs})
        return {
            "found": False,
            "endpoint": "orders/out/simple/query",
            "query_type": "platform_trade_id",
            "safe_fallback_reason": "not_found",
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = _handle_jst_lookup_outbound(
        {"outer_so_id": "platform-order-ref"},
        {
            "copilot_context": {
                "shop_id": "logical-store",
                "jst_shop_id": "provider-store",
                "order_lookup_provider": "qimen",
            }
        },
    )

    assert captured == {
        "identifier": "platform-order-ref",
        "identifier_type": "platform_trade_id",
        "shop_id": "provider-store",
    }
    assert result["found"] is False
    assert result["lookup_complete"] is True
    assert result["safe_fallback_reason"] == "not_found"
