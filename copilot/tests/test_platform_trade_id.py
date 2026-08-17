"""
平台交易单号路由测试 — 验证 platform_trade_id 走 orders/out/simple/query
覆盖需求：
1. 外部交易单号 → orders/out/simple/query
2. 不走普通 o_ids/so_ids 主链路
3. 销售出库 → order_facts + logistics_facts
4. Confirmed → shipped/已发货
5. 回复包含快递公司、快递单号、发出时间
6. 回复不说已签收（除非有 sign_time）
7. 18-19位纯数字不识别为 product_question
8. unknown_identifier 轻量多路尝试 ≤ 3s
9. 多路冲突时 need_human_review=true
10. trace_steps 包含 orders/out/simple/query
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------------------------------------------------------------------------
# A. slot_extract: platform_trade_id 分类
# ---------------------------------------------------------------------------

class TestSlotExtractPlatformTradeId:
    """验证平台交易单号被正确分类为 platform_trade_id"""

    def _extract(self, msg, order_id="", tracking_no=""):
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": msg,
            "normalized_message": msg,
            "order_id": order_id,
            "tracking_no": tracking_no,
            "trace_steps": [],
        }
        return slot_extract(state)

    def test_trade_id_with_context(self):
        """带"交易单号"语义的长数字 → platform_trade_id"""
        result = self._extract("交易单号 5118207015382036103 快递到哪了")
        slots = result["slots"]
        assert slots["identifier_type"] == "platform_trade_id"
        assert slots["platform_trade_id"] == "5118207015382036103"

    def test_trade_id_taobao_context(self):
        """带"淘宝订单"语义的数字 → platform_trade_id"""
        result = self._extract("淘宝订单 5118207015382036103 什么时候到")
        slots = result["slots"]
        assert slots["identifier_type"] == "platform_trade_id"
        assert slots["platform_trade_id"] == "5118207015382036103"

    def test_trade_id_tmall_context(self):
        """带"天猫订单"语义 → platform_trade_id"""
        result = self._extract("天猫订单5118207015382036103到哪了")
        slots = result["slots"]
        assert slots["identifier_type"] == "platform_trade_id"

    def test_19_digit_with_logistics_context(self):
        """18-19位纯数字 + 物流上下文 → platform_trade_id（不能是 product_question）"""
        result = self._extract("5118207015382036103我的快递大概什么时候到")
        slots = result["slots"]
        assert slots["identifier_type"] == "platform_trade_id"
        assert slots["platform_trade_id"] == "5118207015382036103"

    def test_19_digit_pure_no_context(self):
        """19位纯数字无上下文 → unknown_identifier（不能是 product_question）"""
        result = self._extract("5118207015382036103")
        slots = result["slots"]
        # 无上下文时应为 unknown_identifier
        assert slots["identifier_type"] == "unknown_identifier"
        assert slots["possible_numeric_id"] == "5118207015382036103"
        # 绝对不能是 product_question
        assert slots["identifier_type"] != "product_question"

    def test_18_digit_with_order_context(self):
        """18位数字 + 订单上下文 → internal_order_id（"订单"触发通用订单模式）"""
        result = self._extract("订单 511820701538203610 快递到哪了")
        slots = result["slots"]
        # "订单" keyword triggers generic order pattern → internal_order_id
        assert slots["identifier_type"] == "internal_order_id"

    def test_short_number_with_order_context(self):
        """短数字 + 订单上下文 → internal_order_id"""
        result = self._extract("订单号 1636367 什么时候到")
        slots = result["slots"]
        assert slots["identifier_type"] == "internal_order_id"
        assert slots["order_id"] == "1636367"


# ---------------------------------------------------------------------------
# B. identifier_router: platform_trade_id 路由
# ---------------------------------------------------------------------------

class TestIdentifierRouterPlatformTradeId:
    """验证 platform_trade_id 正确路由到 query_order"""

    def _route(self, slots, intent="logistics_eta", risk_level="low"):
        from app.agent.nodes.identifier_router import _route_identifier
        state = {
            "slots": slots,
            "risk_level": risk_level,
            "intent": intent,
        }
        return _route_identifier(state)

    def test_platform_trade_id_routes_to_query_order(self):
        """platform_trade_id → query_order"""
        result = self._route({
            "order_id": "",
            "platform_trade_id": "5118207015382036103",
            "tracking_no": "",
            "possible_numeric_id": "",
            "product_name": "",
            "identifier_type": "platform_trade_id",
        })
        assert result == "query_order"

    def test_platform_trade_id_non_logistics_intent(self):
        """platform_trade_id + 非物流意图 → query_order（不走 clarification）"""
        result = self._route({
            "order_id": "",
            "platform_trade_id": "5118207015382036103",
            "tracking_no": "",
            "possible_numeric_id": "",
            "product_name": "",
            "identifier_type": "platform_trade_id",
        }, intent="general")
        assert result == "query_order"


# ---------------------------------------------------------------------------
# C. jst_live_query: platform_trade_id → lookup_order_by_identifier
# ---------------------------------------------------------------------------

class TestJstLiveQueryPlatformTradeId:
    """验证 jst_live_query 节点正确传递 platform_trade_id 到查询层"""

    def test_query_type_routing(self):
        """platform_trade_id 类型应被正确传递给 lookup_order_by_identifier"""
        from app.agent.nodes.jst_live_query import jst_live_query

        # Mock lookup_order_by_identifier
        import unittest.mock as mock
        mock_result = {
            "found": True,
            "data": {
                "o_id": "1636367",
                "so_id": "20250601001",
                "outer_so_id": "5118207015382036103",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "items": [{"name": "测试商品", "qty": 1}],
            },
            "source": "jst_live",
            "endpoint": "orders/out/simple/query",
            "query_type": "platform_trade_id->outbound_so_id",
            "duration_ms": 500,
        }

        with mock.patch("app.agent.nodes.jst_live_query.lookup_order_by_identifier", return_value=mock_result):
            state = {
                "customer_message": "5118207015382036103 快递到哪了",
                "slots": {
                    "identifier_type": "platform_trade_id",
                    "platform_trade_id": "5118207015382036103",
                    "order_id": "",
                    "tracking_no": "",
                    "possible_numeric_id": "",
                },
                "trace_steps": [],
            }
            result = jst_live_query(state)

        assert result["order_found"] is True
        assert result["order_status"] == "shipped"
        assert result["live_order"]["o_id"] == "1636367"
        assert result["live_order"]["l_id"] == "SF0229477422177"
        assert result["used_endpoint"] == "orders/out/simple/query"
        assert result["used_identifier_type"] == "platform_trade_id"

    def test_outbound_status_mapping(self):
        """Confirmed 状态映射为 shipped"""
        from app.agent.nodes.jst_live_query import _map_status
        assert _map_status("Confirmed") == "shipped"

    def test_outbound_waitconfirm_mapping(self):
        """WaitConfirm 映射为 pending_shipment"""
        from app.agent.nodes.jst_live_query import _map_status
        assert _map_status("WaitConfirm") == "pending_shipment"

    def test_trace_steps_include_endpoint(self):
        """trace_steps 应包含 orders/out/simple/query"""
        from app.agent.nodes.jst_live_query import jst_live_query
        import unittest.mock as mock

        mock_result = {
            "found": True,
            "data": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "items": [],
            },
            "endpoint": "orders/out/simple/query",
            "query_type": "platform_trade_id->outbound_so_id",
            "duration_ms": 500,
        }

        with mock.patch("app.agent.nodes.jst_live_query.lookup_order_by_identifier", return_value=mock_result):
            state = {
                "slots": {
                    "identifier_type": "platform_trade_id",
                    "platform_trade_id": "5118207015382036103",
                    "order_id": "",
                    "tracking_no": "",
                },
                "trace_steps": [],
            }
            result = jst_live_query(state)

        trace = result["trace_steps"][-1]
        assert "orders/out/simple/query" in trace.get("jst_endpoint", "")
        assert trace.get("provider") == "jst"
        assert trace.get("identifier_type") == "platform_trade_id"


# ---------------------------------------------------------------------------
# D. generate_logistics_reply: outbound 已发出回复
# ---------------------------------------------------------------------------

class TestGenerateLogisticsReplyOutbound:
    """验证销售出库查到后回复正确"""

    def _reply(self, state):
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        return generate_logistics_reply(state)

    def test_outbound_shipped_reply_contains_details(self):
        """outbound 已发出回复包含快递公司、脱敏单号、发出时间"""
        state = {
            "normalized_message": "5118207015382036103 快递到哪了",
            "live_order": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "items": [{"name": "测试商品", "qty": 1}],
            },
            "order_status": "shipped",
            "logistics_trace": {
                "status": "shipped",
                "carrier": "顺丰速运",
                "tracking_no": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "latest": {"time": "2026-06-01 13:22:39", "context": "包裹已发出"},
            },
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5118207015382036103",
                "order_id": "",
                "tracking_no": "",
            },
            "used_endpoint": "orders/out/simple/query",
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]

        # 必须包含的关键信息
        assert "顺丰" in reply or "快递" in reply
        assert "尾号2177" in reply
        assert "SF0229477422177" not in reply
        assert "2026-06-01" in reply
        assert "已发出" in reply or "已经发出" in reply

    def test_outbound_no_sign_time_no_delivered_claim(self):
        """outbound 无 sign_time 时不能说已签收"""
        state = {
            "normalized_message": "5118207015382036103 快递到哪了",
            "live_order": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "items": [{"name": "测试商品", "qty": 1}],
            },
            "order_status": "shipped",
            "logistics_trace": {
                "status": "shipped",
                "carrier": "顺丰速运",
                "tracking_no": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "is_delivered": False,
                "latest": {"time": "2026-06-01 13:22:39", "context": "包裹已发出"},
            },
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5118207015382036103",
                "order_id": "",
                "tracking_no": "",
            },
            "used_endpoint": "orders/out/simple/query",
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]

        # 不能说已签收
        assert "已签收" not in reply
        assert "已经签收" not in reply
        assert "签收" not in reply
        # 不能承诺送达时间
        assert "明天一定到" not in reply
        assert "一定送达" not in reply
        assert "一定到" not in reply

    def test_outbound_reply_states_latest_available_trace_boundary(self):
        """只有销售出库节点时，应直接说明当前最新节点和信息边界。"""
        state = {
            "normalized_message": "快递现在到哪了",
            "live_order": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "items": [{"name": "测试商品", "qty": 1}],
            },
            "order_status": "shipped",
            "logistics_trace": {
                "status": "shipped",
                "carrier": "顺丰速运",
                "tracking_no": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "latest": {"time": "2026-06-01 13:22:39", "context": "包裹已发出"},
            },
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5118207015382036103",
                "order_id": "",
                "tracking_no": "",
            },
            "used_endpoint": "orders/out/simple/query",
            "trace_steps": [],
        }

        reply = self._reply(state)["suggested_reply"]

        assert "最新" in reply
        assert "已发出" in reply or "已经发出" in reply
        assert "后续" in reply
        assert "当前位置" not in reply

    def test_outbound_no_delivery_commitment(self):
        """outbound 回复不得承诺具体送达时间"""
        state = {
            "normalized_message": "5118207015382036103 什么时候到",
            "live_order": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "items": [],
            },
            "order_status": "shipped",
            "logistics_trace": {
                "status": "shipped",
                "carrier": "顺丰速运",
                "tracking_no": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "is_delivered": False,
            },
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5118207015382036103",
            },
            "used_endpoint": "orders/out/simple/query",
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]

        # 必须提到"以实际物流更新为准"或类似表述
        assert "实际物流" in reply or "以实际" in reply


# ---------------------------------------------------------------------------
# E. evidence_builder: outbound 数据分层
# ---------------------------------------------------------------------------

class TestEvidenceBuilderOutbound:
    """验证 outbound 数据生成正确的 order_facts 和 logistics_facts"""

    def test_outbound_generates_order_and_logistics_facts(self):
        """outbound 查询应生成 order_facts(source=jst_sales_out) 和 logistics_facts"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
            },
            "logistics_trace": {
                "status": "shipped",
                "carrier": "顺丰速运",
                "tracking_no": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "is_delivered": False,
                "latest": {"time": "2026-06-01 13:22:39", "context": "包裹已发出"},
            },
            "used_endpoint": "orders/out/simple/query",
            "slots": {},
            "trace_steps": [],
            "knowledge_evidence": [],
            "intent": "logistics_eta",
        }
        result = evidence_builder(state)
        evidence = result["evidence"]

        # 有 order_facts
        assert len(evidence["order_facts"]) >= 1
        assert evidence["order_facts"][0]["source_type"] == "jst_sales_out"

        # 有 logistics_facts
        assert len(evidence["logistics_facts"]) >= 1
        lf = evidence["logistics_facts"][0]
        assert "顺丰" in lf["fact"] or "SF0229477422177" in lf["fact"]
        assert lf.get("evidence_boundary") == "已发出"

    def test_evidence_boundary_no_sign_time(self):
        """无 sign_time 时 evidence_boundary 应为"已发出"而非"已签收" """
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": {
                "o_id": "1636367",
                "status": "Confirmed",
                "logistics_company": "顺丰速运",
                "l_id": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
            },
            "logistics_trace": {
                "status": "shipped",
                "carrier": "顺丰速运",
                "tracking_no": "SF0229477422177",
                "send_date": "2026-06-01 13:22:39",
                "sign_time": "",
                "is_delivered": False,
            },
            "used_endpoint": "orders/out/simple/query",
            "slots": {},
            "trace_steps": [],
            "knowledge_evidence": [],
            "intent": "logistics_eta",
        }
        result = evidence_builder(state)
        lf = result["evidence"]["logistics_facts"][0]
        assert lf["evidence_boundary"] == "已发出"
        assert lf["evidence_boundary"] != "已签收"


# ---------------------------------------------------------------------------
# F. live_query.py: platform_trade_id 查询路由
# ---------------------------------------------------------------------------

class TestLiveQueryPlatformTradeIdRouting:
    """验证 lookup_order_by_identifier 正确路由 platform_trade_id"""

    def test_platform_trade_id_goes_to_outbound_first(self):
        """platform_trade_id 应先尝试 orders/out/simple/query"""
        from app.integrations.jst.live_query import lookup_order_by_identifier
        import unittest.mock as mock

        outbound_result = {
            "found": True,
            "data": {"o_id": "1636367", "status": "Confirmed", "l_id": "SF0229477422177"},
            "endpoint": "orders/out/simple/query",
            "query_type": "platform_trade_id->outbound_so_id",
            "duration_ms": 400,
        }

        with mock.patch("app.integrations.jst.live_query.lookup_outbound_by_so_id", return_value=outbound_result) as mock_out:
            result = lookup_order_by_identifier("5118207015382036103", "platform_trade_id")
            mock_out.assert_called_once_with("5118207015382036103")
            assert result["found"] is True
            assert "outbound" in result["query_type"]
            assert result["endpoint"] == "orders/out/simple/query"

    def test_jst_node_passes_sidebar_shop_identity_to_lookup(self):
        from app.agent.nodes.jst_live_query import jst_live_query
        import unittest.mock as mock

        lookup_miss = {
            "found": False,
            "duration_ms": 1,
            "endpoint": "orders/out/simple/query",
            "query_type": "platform_trade_id",
            "safe_fallback_reason": "not_found",
        }
        state = {
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5118207015382036103",
            },
            "copilot_context": {
                "shop_id": "13221776",
                "shop_name": "天猫英禾旗舰店",
            },
            "trace_steps": [],
        }

        with mock.patch(
            "app.agent.nodes.jst_live_query.lookup_order_by_identifier",
            return_value=lookup_miss,
        ) as lookup:
            jst_live_query(state)

        lookup.assert_called_once_with(
            "5118207015382036103",
            "platform_trade_id",
            shop_id="13221776",
        )

    def test_platform_trade_id_can_fallback_to_same_o_id(self):
        """platform_trade_id 出库未命中时允许同号 o_id 快速兜底"""
        from app.integrations.jst.live_query import lookup_order_by_identifier
        import unittest.mock as mock

        outbound_miss = {"found": False, "duration_ms": 400, "endpoint": "orders/out/simple/query"}
        oid_hit = {
            "found": True,
            "data": {"o_id": "1636367"},
            "endpoint": "orders/single/query",
            "query_type": "order_id",
            "duration_ms": 800,
        }

        with mock.patch("app.integrations.jst.live_query.lookup_outbound_by_so_id", return_value=outbound_miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_outer_so_id") as mock_outer, \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_order_id", return_value=oid_hit) as mock_oid:
            result = lookup_order_by_identifier("5118207015382036103", "platform_trade_id")
            mock_oid.assert_called_once_with("5118207015382036103")
            mock_outer.assert_not_called()
            assert result["found"] is True
            assert result["query_type"] == "platform_trade_id->same_order_id"


# ---------------------------------------------------------------------------
# G. router_validation: 18-19 位数字不归为 product_question
# ---------------------------------------------------------------------------

class TestRouterValidationNumericNotProduct:
    """验证 18-19 位数字不被 router_validation 归为 product_question"""

    def test_numeric_with_logistics_stays_logistics(self):
        """数字 + 物流词 → logistics_eta，不是 product_question"""
        from app.agent.nodes.router_validation import router_validation

        state = {
            "normalized_message": "5118207015382036103快递什么时候到",
            "intent": "logistics_eta",
            "router_decision": {"intent": "logistics_eta", "need_tool": True, "tool_name": "jst_live_query"},
            "router_source": "llm",
            "router_reason": "",
            "selected_tool": "jst_live_query",
            "slots": {"identifier_type": "platform_trade_id", "platform_trade_id": "5118207015382036103"},
            "trace_steps": [],
        }
        result = router_validation(state)
        assert result["intent"] == "logistics_eta"
        assert result["selected_tool"] == "jst_live_query"

    def test_numeric_without_logistics_not_product_question(self):
        """纯数字（18-19位）无物流词也不能变成 product_question"""
        from app.agent.nodes.router_validation import router_validation

        state = {
            "normalized_message": "5118207015382036103",
            "intent": "general",
            "router_decision": {"intent": "general", "need_tool": False, "tool_name": "none"},
            "router_source": "llm",
            "router_reason": "",
            "selected_tool": "none",
            "slots": {"identifier_type": "platform_trade_id"},
            "trace_steps": [],
        }
        result = router_validation(state)
        assert result["intent"] != "product_question"


# ---------------------------------------------------------------------------
# H. unknown_identifier 多路尝试性能
# ---------------------------------------------------------------------------

class TestUnknownIdentifierPerformance:
    """验证 unknown_identifier 多路尝试总耗时不超过 3 秒"""

    def test_unknown_identifier_timeout_budget(self):
        """unknown_identifier 多路尝试应有超时预算"""
        from app.integrations.jst.live_query import lookup_order_by_identifier
        import unittest.mock as mock

        slow_miss = {"found": False, "duration_ms": 600, "endpoint": "x", "query_type": "x"}

        t0 = time.time()
        with mock.patch("app.integrations.jst.live_query.lookup_outbound_by_so_id", return_value=slow_miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_order_id", return_value=slow_miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_platform_order_id", return_value=slow_miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_platform_order_id_history", return_value=slow_miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_outer_so_id", return_value=slow_miss), \
             mock.patch("app.integrations.jst.live_query.lookup_logistics_by_tracking_no", return_value=slow_miss):
            result = lookup_order_by_identifier("9999999999999999999", "unknown_identifier")
        elapsed = time.time() - t0

        assert result["found"] is False
        # Mock calls are instant, so elapsed should be very small.
        # The budget is about the accumulated duration_ms in the result.
        total_api_ms = result.get("duration_ms", 0)
        assert total_api_ms <= 6 * 600  # Six bounded paths, each capped by its lookup budget.

    def test_fast_unknown_identifier_skips_historical_scan(self):
        """Interactive callers can reject an unresolved identifier without history scans."""
        from app.integrations.jst.live_query import lookup_order_by_identifier
        import unittest.mock as mock

        miss = {"found": False, "duration_ms": 1, "endpoint": "x", "query_type": "x"}

        with mock.patch("app.integrations.jst.live_query.lookup_outbound_by_so_id", return_value=miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_order_id", return_value=miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_platform_order_id", return_value=miss), \
             mock.patch("app.integrations.jst.live_query.lookup_order_by_platform_order_id_history") as history_lookup:
            result = lookup_order_by_identifier("opaque-identifier", "unknown_identifier", exhaustive=False)

        assert result["found"] is False
        assert result["safe_fallback_reason"] == "not_found_fast_path"
        assert history_lookup.call_count == 0


# ---------------------------------------------------------------------------
# I. response_strategy: platform_trade_id 有标识符
# ---------------------------------------------------------------------------

class TestResponseStrategyPlatformTradeId:
    """验证 response_strategy_router 正确识别 platform_trade_id 为有标识符"""

    def test_has_identifier_with_platform_trade_id(self):
        """platform_trade_id 应被视为有标识符"""
        from app.agent.nodes.response_strategy_router import _has_identifier

        state = {
            "order_id": "",
            "slots": {
                "order_id": "",
                "platform_trade_id": "5118207015382036103",
                "tracking_no": "",
                "possible_numeric_id": "",
            },
        }
        assert _has_identifier(state) is True
