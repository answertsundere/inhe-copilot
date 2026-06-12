"""
隔离与标识符区分测试 - 验证订单号/快递单号/数字编号正确区分，
以及请求之间不会复用旧 tracking_no
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------------------------------------------------------------------------
# A. slot_extract 单元测试
# ---------------------------------------------------------------------------

class TestSlotExtract:
    """测试 slot_extract 节点的标识符区分逻辑"""

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

    def test_a1_sf_tracking_recognized(self):
        """SF 开头的单号被识别为快递单号"""
        result = self._extract("SF0221700958051 这个快递到哪了")
        slots = result["slots"]
        assert slots["tracking_no"] == "SF0221700958051"
        assert not slots["order_id"]

    def test_a2_jt_tracking_recognized(self):
        """JT 开头的单号被识别为快递单号"""
        result = self._extract("JT3164846725758这个快递什么时候到")
        slots = result["slots"]
        assert slots["tracking_no"] == "JT3164846725758"

    def test_a3_pure_numeric_not_tracking(self):
        """纯数字编号不应被默认当成快递单号"""
        result = self._extract("订单 202501010001 快递到哪了")
        slots = result["slots"]
        assert slots["order_id"] == "202501010001"
        assert not slots["tracking_no"]

    def test_a4_pure_numeric_as_possible_id(self):
        """纯数字编号无明确语义时放入 possible_numeric_id"""
        result = self._extract("202501010001 这个查一下")
        slots = result["slots"]
        assert slots["possible_numeric_id"] == "202501010001"
        assert not slots["tracking_no"]
        assert not slots["order_id"]

    def test_a5_api_order_id_preserved(self):
        """API 传入的 order_id 被保留为 order_id"""
        result = self._extract("这个单还要多久", order_id="202501010001")
        slots = result["slots"]
        assert slots["order_id"] == "202501010001"
        assert not slots["tracking_no"]

    def test_a6_api_tracking_no_preserved(self):
        """API 传入的 tracking_no 被保留"""
        result = self._extract("快递到了吗", tracking_no="SF0221700958051")
        slots = result["slots"]
        assert slots["tracking_no"] == "SF0221700958051"
        assert not slots["order_id"]

    def test_a7_both_api_params(self):
        """同时传入 order_id 和 tracking_no"""
        result = self._extract("帮我查一下", order_id="202501010001", tracking_no="SF1234567890123")
        slots = result["slots"]
        assert slots["order_id"] == "202501010001"
        assert slots["tracking_no"] == "SF1234567890123"

    def test_a8_no_ids(self):
        """没有任何标识符"""
        result = self._extract("我快递大概几天会到")
        slots = result["slots"]
        assert not slots["order_id"]
        assert not slots["tracking_no"]
        assert not slots["possible_numeric_id"]

    def test_a9_trace_has_source_info(self):
        """trace 包含标识符来源"""
        result = self._extract("订单 202501010001 快递到哪了")
        trace = result["trace_steps"][-1]
        summary = trace.get("summary", "")
        assert "订单号" in summary or "抽取" in summary

    def test_a10_product_name_extracted(self):
        """商品名被正确提取"""
        result = self._extract("这个书架什么时候发货")
        slots = result["slots"]
        assert slots["product_name"] == "书架"


# ---------------------------------------------------------------------------
# B. identifier_router 单元测试
# ---------------------------------------------------------------------------

class TestIdentifierRouter:
    """测试 identifier_router 节点的路由决策"""

    def _route(self, slots, intent="logistics", risk_level="low"):
        from app.agent.nodes.identifier_router import _route_identifier
        state = {
            "slots": slots,
            "risk_level": risk_level,
            "intent": intent,
        }
        return _route_identifier(state)

    def test_b1_order_id_routes_to_query_order(self):
        """有 order_id 走 query_order"""
        result = self._route({"order_id": "202501010001", "tracking_no": "", "possible_numeric_id": "", "product_name": ""})
        assert result == "query_order"

    def test_b2_tracking_no_routes_to_query_order(self):
        """只有 tracking_no 走聚水潭查订单"""
        result = self._route({"order_id": "", "tracking_no": "SF1234567890123", "possible_numeric_id": "", "product_name": ""})
        assert result == "query_order"

    def test_b3_possible_numeric_routes_to_query_order(self):
        """possible_numeric_id 走 query_order（先查订单）"""
        result = self._route({"order_id": "", "tracking_no": "", "possible_numeric_id": "202501010001", "product_name": ""})
        assert result == "query_order"

    def test_b4_both_ids_routes_to_verify(self):
        """同时有 order_id 和 tracking_no 走 verify_consistency"""
        result = self._route({"order_id": "202501010001", "tracking_no": "SF123", "possible_numeric_id": "", "product_name": ""})
        assert result == "verify_consistency"

    def test_b5_product_only_routes_to_resolve(self):
        """只有商品名走 resolve_product"""
        result = self._route({"order_id": "", "tracking_no": "", "possible_numeric_id": "", "product_name": "书架"})
        assert result == "resolve_product"

    def test_b6_nothing_routes_to_clarification(self):
        """什么都没有走 clarification"""
        result = self._route({"order_id": "", "tracking_no": "", "possible_numeric_id": "", "product_name": ""})
        assert result == "clarification"

    def test_b7_high_risk_routes_to_human_review(self):
        """高风险走 human_review"""
        result = self._route({"order_id": "202501010001", "tracking_no": "", "possible_numeric_id": "", "product_name": ""}, risk_level="high")
        assert result == "human_review"


# ---------------------------------------------------------------------------
# C. 隔离性测试（连续请求不污染）
# ---------------------------------------------------------------------------

class TestRequestIsolation:
    """验证不同请求之间不会复用旧的 tracking_no"""

    def _invoke(self, msg, order_id="", tracking_no=""):
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": msg,
            "normalized_message": msg,
            "order_id": order_id,
            "tracking_no": tracking_no,
            "trace_steps": [],
        }
        return slot_extract(state)

    def test_c1_no_tracking_contamination(self):
        """查询不含快递单号的消息时不应出现旧的 tracking_no"""
        # 第一次请求有 tracking_no
        result1 = self._invoke("SF0221700958051 这个快递到哪了", tracking_no="SF0221700958051")
        assert result1["slots"]["tracking_no"] == "SF0221700958051"

        # 第二次请求完全无关
        result2 = self._invoke("书架什么时候发货", order_id="", tracking_no="")
        slots2 = result2["slots"]
        assert not slots2["tracking_no"]
        assert not slots2["order_id"]
        # trace 中也不应有旧 tracking_no
        trace_summary = result2["trace_steps"][-1]["summary"]
        assert "SF0221700958051" not in trace_summary

    def test_c2_order_id_not_tracking(self):
        """API order_id 不应变成 tracking_no"""
        result = self._invoke("这单还要多久", order_id="202501010001", tracking_no="")
        slots = result["slots"]
        assert slots["order_id"] == "202501010001"
        assert not slots["tracking_no"]

    def test_c3_fresh_state_each_time(self):
        """每次调用都是全新的 state，不继承旧数据"""
        from app.agent.nodes.slot_extract import slot_extract

        # 第一次
        state1 = {"customer_message": "SF1234 快递到了吗", "order_id": "", "tracking_no": "SF1234", "trace_steps": []}
        r1 = slot_extract(state1)
        assert r1["slots"]["tracking_no"] == "SF1234"

        # 第二次（全新 state）
        state2 = {"customer_message": "我快递几天会到", "order_id": "", "tracking_no": "", "trace_steps": []}
        r2 = slot_extract(state2)
        assert not r2["slots"]["tracking_no"]


# ---------------------------------------------------------------------------
# D. generate_logistics_reply 输出安全测试
# ---------------------------------------------------------------------------

class TestReplySafety:
    """验证回复中不包含内部标记"""

    def _reply(self, state):
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        return generate_logistics_reply(state)

    def test_d1_no_internal_markers(self):
        """回复中不应出现内部标记"""
        state = {
            "normalized_message": "快递到了吗",
            "slots": {},
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]
        assert "低可信度" not in reply
        assert "系统提示" not in reply
        assert "GRAPH_EXECUTION_ERROR" not in reply
        assert "low_confidence" not in reply

    def test_d2_low_confidence_no_affirm_delivered(self):
        """低可信度时不应肯定说已签收"""
        state = {
            "normalized_message": "快递到了吗",
            "logistics_trace": {
                "status": "delivered",
                "is_delivered": True,
                "low_confidence": True,
                "carrier": "顺丰速运",
                "tracking_no": "SF0221700958051",
                "latest": {"time": "2026-05-01", "context": "查无结果"},
            },
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]
        # 不应肯定说签收
        assert "已经签收啦" not in reply
        assert "已签收" not in reply
        # 应该引导核实
        assert "核实" in reply or "官网" in reply

    def test_d3_no_tracking_no_in_generic_reply(self):
        """无快递单号的查询，回复中不应出现快递单号"""
        state = {
            "normalized_message": "我快递大概几天会到",
            "slots": {},
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]
        assert "SF0221700958051" not in reply
        assert "SF" not in reply or "顺丰" not in reply

    def test_d4_no_exposed_internal_fields(self):
        """回复中不应暴露内部字段名"""
        state = {
            "normalized_message": "查快递",
            "slots": {"tracking_no": "SF1234567890123"},
            "logistics_trace": {
                "status": "no_trace",
                "tracking_no": "SF1234567890123",
            },
            "trace_steps": [],
        }
        result = self._reply(state)
        reply = result["suggested_reply"]
        assert "logistics_trace" not in reply
        assert "slots" not in reply
        assert "answer_type" not in reply
        assert "order_found" not in reply


# ---------------------------------------------------------------------------
# E. build_response 不追加温馨提示
# ---------------------------------------------------------------------------

class TestBuildResponse:
    """验证 build_response 不把 guard_warnings 追加到 suggested_reply"""

    def test_e1_no_warm_tip_in_reply(self):
        from app.agent.nodes.build_response import build_response
        state = {
            "suggested_reply": "亲，您的快递已发出。",
            "guard_warnings": ["已替换不安全表述"],
            "requires_human_review": False,
            "trace_steps": [],
        }
        result = build_response(state)
        assert "温馨提示" not in result["suggested_reply"]
        assert result["suggested_reply"] == "亲，您的快递已发出。"
        assert result["guard_warnings"] == ["已替换不安全表述"]


# ---------------------------------------------------------------------------
# F. slot_extract 回归测试 - 快递单号格式
# ---------------------------------------------------------------------------

class TestTrackingFormats:
    """验证各种快递单号格式被正确识别"""

    def _extract(self, msg):
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": msg,
            "normalized_message": msg,
            "order_id": "",
            "tracking_no": "",
            "trace_steps": [],
        }
        return slot_extract(state)

    def test_f1_sf_format(self):
        result = self._extract("SF0221700958051这个快递")
        assert result["slots"]["tracking_no"] == "SF0221700958051"

    def test_f2_jt_format(self):
        result = self._extract("JT3164846725758什么时候到")
        assert result["slots"]["tracking_no"] == "JT3164846725758"

    def test_f3_jd_format(self):
        result = self._extract("JD001234567890帮我查下")
        assert result["slots"]["tracking_no"] == "JD001234567890"

    def test_f4_yt_format(self):
        result = self._extract("YT1234567890到哪了")
        assert result["slots"]["tracking_no"] == "YT1234567890"

    def test_f5_zto_format(self):
        result = self._extract("ZTO1234567890物流状态")
        assert result["slots"]["tracking_no"] == "ZTO1234567890"

    def test_f6_pure_numeric_not_confused_as_tracking(self):
        """纯数字不应被当成快递单号"""
        result = self._extract("202501010001 这个查一下")
        assert not result["slots"]["tracking_no"]

    def test_f7_order_semantic_with_number(self):
        """'订单号 202501010001' 应被识别为 order_id"""
        result = self._extract("订单号202501010001这个订单")
        assert result["slots"]["order_id"] == "202501010001"
        assert not result["slots"]["tracking_no"]
