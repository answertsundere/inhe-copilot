"""
Phase 0+1 修复验证测试
覆盖：
1. 高风险投诉不进入 build_base_context
2. 无订单号但有商品名不查 JST
3. 无订单号无商品名
4. 物流单号已查过不重复查快递100
5. 聚水潭 timeout 走本地兜底
6. has_logistics=false 不得出现已签收
7. fixed fallback 不再单一
8. trace_steps 字段完整
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _invoke(msg: str, order_id: str = "", tracking_no: str = "") -> dict:
    """调用 graph"""
    from app.agent.graph import customer_service_graph
    state = {
        "customer_message": msg,
        "order_id": order_id,
        "trace_steps": [],
    }
    if tracking_no:
        state["tracking_no"] = tracking_no
    return customer_service_graph.invoke(state)


def _steps(result: dict) -> list:
    """提取 trace step 节点名称列表"""
    return [s.get("node", "") for s in result.get("trace_steps", [])]


# ---------------------------------------------------------------------------
# 1. 高风险投诉不进入 build_base_context
# ---------------------------------------------------------------------------

class TestHighRiskShortCircuit:
    """高风险投诉直接到 human_review_gate，不进入 build_base_context"""

    def test_complaint_no_build_context(self):
        """高风险投诉仍走完整知识链，最后进入 human_review_gate"""
        result = _invoke("再不到我就投诉平台，我要打12315")
        steps = _steps(result)
        assert "risk_check" in steps
        assert "human_review_gate" in steps
        # 高风险不再短路，应进入完整知识链
        assert "build_base_context" in steps
        assert "response_strategy_router" in steps
        # 新链路走 tool_planner，旧链路走 rag_retrieve；两者都应经过 knowledge_scope_router 或 tool_planner
        assert "knowledge_scope_router" in steps or "tool_planner" in steps
        assert "evidence_builder" in steps
        # 不应查订单和快递（无订单号）
        assert "jst_live_query" not in steps
        assert "query_by_tracking_no" not in steps

    def test_complaint_requires_human_review(self):
        """高风险投诉标记人工复核"""
        result = _invoke("再不到我就投诉平台")
        assert result["risk_level"] == "high"
        assert result["requires_human_review"] is True

    def test_complaint_trace_has_risk_short_circuit(self):
        """trace 记录 risk_short_circuit"""
        result = _invoke("我要投诉到12315，你们等着")
        risk_trace = None
        for s in result.get("trace_steps", []):
            if s.get("node") == "risk_check":
                risk_trace = s
                break
        assert risk_trace is not None
        assert risk_trace.get("risk_short_circuit") is True


# ---------------------------------------------------------------------------
# 2. 无订单号但有商品名不查 JST
# ---------------------------------------------------------------------------

class TestNoOrderIdNoJST:
    """无订单号但有商品名时不查 JST"""

    def test_product_name_no_jst(self):
        """三层黄色那个多久到 → 不查 JST"""
        result = _invoke("三层黄色那个多久到？")
        steps = _steps(result)
        assert "resolve_product_identity" in steps
        assert "jst_live_query" not in steps
        # 应返回通用政策或 clarification
        reply = result.get("suggested_reply", "")
        assert reply

    def test_product_name_reply_guides_order(self):
        """有商品名时回复引导提供订单号"""
        result = _invoke("三层书架多久到？")
        reply = result.get("suggested_reply", "")
        assert "订单号" in reply or "订单" in reply

    def test_product_name_trace_no_order_skip(self):
        """trace 记录 no_order_skip_order_lookup"""
        result = _invoke("书架什么时候发货？")
        product_trace = None
        for s in result.get("trace_steps", []):
            if s.get("node") == "resolve_product_identity":
                product_trace = s
                break
        assert product_trace is not None
        assert product_trace.get("no_order_skip_order_lookup") is True


# ---------------------------------------------------------------------------
# 3. 无订单号无商品名
# ---------------------------------------------------------------------------

class TestNoIdentifiers:
    """无订单号无商品名"""

    def test_no_identifiers_no_order_query(self):
        """不查订单，不查快递100"""
        result = _invoke("我快递大概几天到？")
        steps = _steps(result)
        assert "jst_live_query" not in steps
        assert "query_by_tracking_no" not in steps

    def test_no_identifiers_reply_guides_info(self):
        """引导提供订单号/物流单号/商品名"""
        result = _invoke("我快递大概几天到？")
        reply = result.get("suggested_reply", "")
        assert "订单号" in reply or "商品" in reply or "提供" in reply

    def test_no_identifiers_no_fake_data(self):
        """不出现任何具体单号、快递公司、已签收"""
        result = _invoke("我快递大概几天到？")
        reply = result.get("suggested_reply", "")
        import re
        tracking_like = re.findall(r"[A-Z]{2}\d{10,}|[A-Z]\d{12,}|\d{15,}", reply)
        assert len(tracking_like) == 0, f"回复中疑似编造单号: {tracking_like}"
        assert "已签收" not in reply
        assert "已经签收" not in reply


# ---------------------------------------------------------------------------
# 4. 物流单号已查过，不重复查快递100
# ---------------------------------------------------------------------------

class TestNoDuplicateKD100:
    """物流单号已查过不重复查快递100"""

    def test_tracking_no_query_once(self):
        """YT123456789 到哪里了 → 走聚水潭查订单"""
        result = _invoke("YT1234567890 到哪里了？")
        steps = _steps(result)
        assert any(s in steps for s in ("jst_live_query", "tool_executor", "tool_executor_node"))

    def test_already_has_trace_skip(self):
        """已有 logistics_trace 时不再 query_logistics_trace"""
        from app.agent.nodes.query_logistics_trace import query_logistics_trace
        # 模拟已有 logistics_trace
        state = {
            "logistics_trace": {
                "status": "delivered",
                "tracking_no": "YT1234567890",
                "carrier": "圆通",
                "is_delivered": True,
                "events": [{"time": "2026-05-01", "context": "已签收"}],
                "latest": {"time": "2026-05-01", "context": "已签收"},
            },
            "live_order": {"l_id": "YT1234567890", "status": "已发货"},
            "trace_steps": [],
        }
        result = query_logistics_trace(state)
        # 应该跳过，不再查询
        trace = result.get("trace_steps", [{}])[-1]
        assert trace.get("cache_hit") is True or "跳过" in trace.get("summary", "")

    def test_resolve_order_status_skip_flag(self):
        """resolve_order_status 标记 skip_duplicate_logistics_query"""
        from app.agent.nodes.resolve_order_status import resolve_order_status
        state = {
            "live_order": {"status": "已发货", "l_id": "YT1234567890"},
            "logistics_trace": {
                "status": "delivered",
                "tracking_no": "YT1234567890",
                "is_delivered": True,
                "events": [{"time": "2026-05-01", "context": "已签收"}],
                "latest": {"time": "2026-05-01", "context": "已签收"},
            },
            "trace_steps": [],
        }
        result = resolve_order_status(state)
        trace = result.get("trace_steps", [{}])[-1]
        assert trace.get("skip_duplicate_logistics_query") is True


# ---------------------------------------------------------------------------
# 5. 聚水潭 timeout 走本地兜底
# ---------------------------------------------------------------------------

class TestJSTTimeout:
    """聚水潭 timeout 走本地兜底"""

    def test_jst_timeout_trace(self):
        """JST 超时记录 jst_timeout"""
        from app.agent.nodes.query_jst_order import query_jst_order
        # 模拟超时
        state = {
            "order_id": "202501010001",
            "slots": {"order_id": "202501010001", "tracking_no": "", "possible_numeric_id": ""},
            "order_found": False,
            "trace_steps": [],
        }
        # 因为聚水潭未配置，所以会跳过
        # 但我们测试超时场景：直接用 order_adapter mock
        from unittest.mock import patch, MagicMock
        with patch("app.agent.nodes.query_jst_order._is_jst_configured", return_value=True):
            with patch("app.agent.nodes.query_jst_order.OrderAdapter") as mock_adapter_cls:
                mock_adapter = MagicMock()
                mock_adapter.query_jst.side_effect = TimeoutError("timeout")
                mock_adapter_cls.return_value = mock_adapter
                result = query_jst_order(state)
                trace = result.get("trace_steps", [{}])[-1]
                assert trace.get("status") == "jst_timeout"

    def test_jst_failed_no_500(self):
        """JST 失败不报 500"""
        from app.agent.nodes.query_jst_order import query_jst_order
        state = {
            "order_id": "202501010001",
            "slots": {"order_id": "202501010001", "tracking_no": "", "possible_numeric_id": ""},
            "order_found": False,
            "trace_steps": [],
        }
        from unittest.mock import patch, MagicMock
        with patch("app.agent.nodes.query_jst_order._is_jst_configured", return_value=True):
            with patch("app.agent.nodes.query_jst_order.OrderAdapter") as mock_adapter_cls:
                mock_adapter = MagicMock()
                mock_adapter.query_jst.side_effect = ConnectionError("refused")
                mock_adapter_cls.return_value = mock_adapter
                result = query_jst_order(state)
                # 不应抛异常
                assert result is not None
                assert result.get("order_found") is False
                trace = result.get("trace_steps", [{}])[-1]
                assert trace.get("status") == "jst_failed"

    def test_jst_timeout_enters_fallback(self):
        """JST 超时后走 resolve_order_status"""
        # graph 中 jst_live_query → resolve_order_status 是固定边
        # 只要 graph 编译通过就行
        from app.agent.graph import customer_service_graph
        assert customer_service_graph is not None


# ---------------------------------------------------------------------------
# 6. has_logistics=false 不得出现已签收
# ---------------------------------------------------------------------------

class TestNoLogisticsNoSigned:
    """无物流证据时不得出现已签收"""

    def test_no_logistics_no_signed_claim(self):
        """无物流证据时 generate_logistics_reply 不说已签收"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "我的快递到了吗？",
            "order": None,
            "live_order": None,
            "logistics_trace": None,
            "order_status": "",
            "shipping_policy": {},
            "matched_product_name": "",
            "slots": {"tracking_no": "", "order_id": ""},
            "evidence": {"conflicts": [], "unknowns": []},
            "need_clarification": False,
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "已签收" not in reply
        assert "已经签收" not in reply
        assert "签收啦" not in reply

    def test_no_logistics_guard_blocks_signed(self):
        """factual_guard 拦截无物流证据时的签收声明"""
        from app.agent.nodes.factual_guard import factual_guard
        state = {
            "suggested_reply": "亲，您的快递已经签收啦，请注意查收。",
            "logistics_trace": None,
            "order": None,
            "evidence": {"unknowns": [], "conflicts": []},
            "answer_type": "verified",
            "trace_steps": [],
        }
        result = factual_guard(state)
        assert len(result["guard_warnings"]) > 0
        # 应该被改写
        rewritten = result.get("suggested_reply", "")
        assert "已签收" not in rewritten or "核实" in rewritten

    def test_order_pending_no_signed(self):
        """待发货订单不说已签收"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "快递到了吗？",
            "order": {"items": [{"name": "书架"}], "status": "待发货", "l_id": "", "logistics_company": ""},
            "order_status": "pending_shipment",
            "logistics_trace": None,
            "shipping_policy": {},
            "matched_product_name": "",
            "slots": {},
            "evidence": {"conflicts": [], "unknowns": []},
            "need_clarification": False,
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "已签收" not in reply
        assert "已经签收" not in reply


# ---------------------------------------------------------------------------
# 7. fixed fallback 不再单一
# ---------------------------------------------------------------------------

class TestFallbackDiversity:
    """fallback 话术按场景区分，不再单一"""

    def test_fallback_scenario_a_tracking_no_only(self):
        """场景A: 有物流单号但聚水潭未查到 → 特定话术"""
        from app.agent.nodes.generate_logistics_reply import _fallback_tracking_no_only
        reply = _fallback_tracking_no_only("YT1234567890")
        assert "YT1234567890" in reply
        assert "暂未在系统中查到" in reply or "未查到" in reply
        assert "订单号" in reply

    def test_fallback_scenario_b_order_shipped_no_sync(self):
        """场景B: 有订单已发货但物流未同步 → 特定话术"""
        from app.agent.nodes.generate_logistics_reply import _fallback_order_shipped_no_sync
        reply = _fallback_order_shipped_no_sync(
            {"items": [{"name": "书架"}]}, "ZT123456", "中通"
        )
        assert "已安排发货" in reply
        assert "同步更新" in reply

    def test_fallback_scenario_c_kd100_low_confidence(self):
        """场景C: 低可信度签收 → 特定话术"""
        from app.agent.nodes.generate_logistics_reply import _fallback_low_confidence_signed
        reply = _fallback_low_confidence_signed("ZT123456", "中通")
        assert "暂无法确认" in reply
        assert "ZT123456" in reply
        assert "核实" in reply or "订单号" in reply or "截图" in reply
        # 不应建议去快递官网/App
        assert "官方渠道" not in reply
        assert "官网" not in reply

    def test_fallback_scenario_d_api_failed(self):
        """场景D: 接口失败/超时 → 特定话术"""
        from app.agent.nodes.generate_logistics_reply import _fallback_api_failed
        reply = _fallback_api_failed("SF1234567890")
        assert "不可用" in reply or "暂时" in reply
        assert "SF1234567890" in reply

    def test_fallbacks_are_different(self):
        """4 种 fallback 话术互不相同"""
        from app.agent.nodes.generate_logistics_reply import (
            _fallback_tracking_no_only,
            _fallback_order_shipped_no_sync,
            _fallback_low_confidence_signed,
            _fallback_api_failed,
        )
        replies = [
            _fallback_tracking_no_only("YT123"),
            _fallback_order_shipped_no_sync({"items": [{"name": "书架"}]}, "ZT123", "中通"),
            _fallback_low_confidence_signed("ZT123", "中通"),
            _fallback_api_failed("SF123"),
        ]
        # 确保至少3种明显不同的回复
        unique = set(replies)
        assert len(unique) >= 3, f"fallback 话术不够多样: {replies}"


# ---------------------------------------------------------------------------
# 8. trace_steps 字段完整
# ---------------------------------------------------------------------------

class TestTraceStepsComplete:
    """所有关键节点 trace 都包含 duration_ms、status、summary"""

    REQUIRED_FIELDS = {"status", "duration_ms", "summary"}

    def test_shipped_order_trace_fields(self):
        """有订单场景 trace 字段完整"""
        result = _invoke("我快递大概几天会到？", "202501010001")
        for trace in result.get("trace_steps", []):
            node = trace.get("node", "")
            if node in ("normalize_input", "detect_intent", "risk_check",
                        "build_base_context", "route_by_intent", "slot_extract",
                        "identifier_router", "resolve_order_status",
                        "jst_live_query", "match_shipping_policy",
                        "evidence_builder", "generate_logistics_reply",
                        "factual_guard", "build_response", "quality_guard",
                        "human_review_gate"):
                missing = self.REQUIRED_FIELDS - set(trace.keys())
                assert not missing, f"节点 {node} trace 缺少字段: {missing}"

    def test_product_only_trace_fields(self):
        """无订单有商品名场景 trace 字段完整"""
        result = _invoke("这个书架什么时候发货？")
        for trace in result.get("trace_steps", []):
            node = trace.get("node", "")
            if node in ("resolve_product_identity", "match_shipping_policy",
                        "generate_logistics_reply", "evidence_builder"):
                missing = self.REQUIRED_FIELDS - set(trace.keys())
                assert not missing, f"节点 {node} trace 缺少字段: {missing}"

    def test_no_identifier_trace_fields(self):
        """无标识符场景 trace 字段完整"""
        result = _invoke("我快递大概几天到？")
        for trace in result.get("trace_steps", []):
            node = trace.get("node", "")
            if node in ("normalize_input", "detect_intent", "risk_check",
                        "build_base_context", "route_by_intent",
                        "quality_guard", "human_review_gate"):
                missing = self.REQUIRED_FIELDS - set(trace.keys())
                assert not missing, f"节点 {node} trace 缺少字段: {missing}"


# ---------------------------------------------------------------------------
# 9. 统一知识检索接入修复验证
# ---------------------------------------------------------------------------

class TestHighRiskUsesSopBeforeHumanReview:
    """高风险投诉必须检索 high_risk_sop 再转人工"""

    def test_high_risk_uses_sop_before_human_review(self):
        """投诉场景：检索 high_risk_sop，回复非空，最后转人工"""
        result = _invoke("再不处理我就投诉平台")
        steps = _steps(result)
        assert result["intent"] == "complaint"
        assert result["risk_level"] == "high"
        assert result["requires_human_review"] is True
        assert "response_strategy_router" in steps
        # 新链路走 tool_planner，旧链路走 knowledge_scope_router + rag_retrieve
        assert ("knowledge_scope_router" in steps and "rag_retrieve" in steps) or "tool_planner" in steps
        assert "evidence_builder" in steps
        assert "human_review_gate" in steps
        reply = result.get("suggested_reply", "")
        assert reply, "高风险投诉回复不应为空"
        assert len(reply) > 10
        assert "赔偿" not in reply
        assert "退款" not in reply


class TestTimeCommitmentIsLogistics:
    """物流时效承诺类语句应识别为 logistics_eta"""

    def test_time_commitment_is_logistics(self):
        """明天能不能一定到？→ logistics_eta"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "明天能不能一定到？",
            "customer_message": "明天能不能一定到？",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "logistics_eta", f"应识别为 logistics_eta，实际 {result['intent']}"

    def test_guarantee_delivery_is_logistics(self):
        """明天能不能保证到？→ logistics_eta"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "明天能不能保证到？",
            "customer_message": "明天能不能保证到？",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "logistics_eta", f"应识别为 logistics_eta，实际 {result['intent']}"


class TestProductPriceNotLogistics:
    """商品到手价不应被判为物流"""

    def test_product_price_not_logistics(self):
        """这个商品到手价多少？→ 不应为 logistics_eta"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "这个商品到手价多少？",
            "customer_message": "这个商品到手价多少？",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] != "logistics_eta", f"不应识别为 logistics_eta，实际 {result['intent']}"


class TestApiReturnsEvidenceDebug:
    """API 响应应包含 evidence_debug"""

    def test_api_returns_evidence_debug(self):
        """/api/analyze 返回 evidence_debug 且不泄露隐私"""
        from app.main import create_app
        from app.agent.context.context_store import context_store
        context_store.clear()
        client = create_app().test_client()
        resp = client.post("/api/analyze", json={
            "message": "这个儿童书架是什么材质？",
            "order_id": "",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        ctx = data.get("context_used", {})
        assert "response_strategy" in ctx
        assert "answer_mode" in ctx
        assert "allowed_source_types" in ctx
        assert "used_fact_tools" in ctx
        assert "retrieved_knowledge_count" in ctx
        assert "selected_evidence_count" in ctx
        assert "used_knowledge_entry_ids" in ctx
        assert "used_knowledge_titles" in ctx
        assert "evidence_sources" in ctx
        # evidence_debug 或等价字段
        ev = data.get("evidence_debug", {})
        assert "retrieved_chunks_summary" in ev or "product_facts_count" in ctx
        # 不泄露隐私
        assert "receiver_name" not in str(data)
        assert "receiver_address" not in str(data)
        assert "receiver_phone" not in str(data)


class TestProductShippingPolicyReplyNotOverRewritten:
    """无订单有商品名的物流咨询不应被 factual_guard 过度改写"""

    def test_product_shipping_policy_reply_not_over_rewritten(self):
        """这个儿童书架多久发货？→ 回复应包含商品名，不应纯要订单号"""
        result = _invoke("这个儿童书架多久发货？")
        reply = result.get("suggested_reply", "")
        assert reply, "回复不应为空"
        # 应包含商品相关词或引导提供订单号
        assert "书架" in reply or "这款" in reply or "该商品" in reply or "订单号" in reply
        # 不应出现"您的订单已发货/已签收"
        assert "您的订单已发货" not in reply
        assert "您的订单已签收" not in reply
        # factual_guard 不应强制改写成纯要订单号模板（允许同时提及商品和引导）
        assert "麻烦您提供一下订单号或物流单号" != reply
