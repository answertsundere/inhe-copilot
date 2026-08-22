"""
物流链路可信度与路由修复测试
验证：低可信度不肯定签收、verify_consistency 条件路由、订单优先级、无污染
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------------------------------------------------------------------------
# A. 低可信度物流不能肯定签收
# ---------------------------------------------------------------------------

class TestTrackingLowConfidence:
    """验证低可信度快递信息不会生成"已签收"的肯定回复"""

    def test_a1_low_confidence_not_confirm_delivered(self):
        """低可信度时 suggested_reply 不含"已签收"等肯定性表述"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "SF0221700958051我的快递什么时候送到",
            "slots": {"tracking_no": "SF0221700958051", "order_id": ""},
            "logistics_trace": {
                "status": "uncertain",
                "carrier": "顺丰速运",
                "tracking_no": "SF0221700958051",
                "is_delivered": False,
                "confirmed_delivered": False,
                "low_confidence": True,
                "state": "3",
                "events": [{"time": "2026-05-01", "context": "查无结果"}],
                "latest": {"time": "2026-05-01", "context": "查无结果"},
            },
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "已签收" not in reply
        assert "已经签收" not in reply
        assert "签收啦" not in reply
        assert "核实" in reply or "确认" in reply or "提供订单号" in reply
        assert "低可信度" not in reply
        assert "系统提示" not in reply

    def test_a2_low_confidence_no_product_fabrication(self):
        """无订单时不得编造商品名"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "SF0221700958051快递到哪了",
            "slots": {"tracking_no": "SF0221700958051", "order_id": ""},
            "logistics_trace": {
                "status": "uncertain",
                "carrier": "顺丰速运",
                "tracking_no": "SF0221700958051",
                "is_delivered": False,
                "low_confidence": True,
                "latest": {"time": "2026-05-01", "context": "暂无"},
            },
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        # 不应出现具体商品名
        assert "书架" not in reply
        assert "绘本" not in reply
        assert "书桌" not in reply

    def test_a3_factual_guard_catches_delivered_claim(self):
        """factual_guard 拦截低可信度时肯定签收"""
        from app.agent.nodes.factual_guard import factual_guard
        state = {
            "suggested_reply": "亲亲，您的顺丰速运快递（单号：SF0221700958051）已经签收啦。",
            "logistics_trace": {
                "status": "uncertain",
                "low_confidence": True,
                "is_delivered": False,
                "confirmed_delivered": False,
                "carrier": "顺丰速运",
                "tracking_no": "SF0221700958051",
            },
            "guard_warnings": [],
            "trace_steps": [],
        }
        result = factual_guard(state)
        assert len(result["guard_warnings"]) > 0
        # 应该改写回复
        assert "已经签收" not in result.get("suggested_reply", "")
        assert "签收啦" not in result.get("suggested_reply", "")

    def test_a4_factual_guard_no_order_no_product(self):
        """无订单时回复出现具体商品，factual_guard 拦截"""
        from app.agent.nodes.factual_guard import factual_guard
        state = {
            "suggested_reply": "亲，您的订单（北欧风书架）已经发货了。",
            "guard_warnings": [],
            "trace_steps": [],
        }
        result = factual_guard(state)
        assert len(result["guard_warnings"]) > 0

    def test_a5_query_by_tracking_no_uncertain_status(self):
        """query_by_tracking_no 对低可信度返回 status=uncertain"""
        from app.agent.nodes.query_by_tracking_no import _query_kuaidi100
        # 模拟快递100返回低可信度结果
        import unittest.mock as mock
        with mock.patch("app.agent.nodes.query_by_tracking_no.query_tracking") as m:
            m.return_value = {
                "state": "3",
                "data": [{"time": "2026-05-01", "context": "查无结果"}],
                "courier_name": "顺丰速运",
                "tracking_no": "SF0221700958051",
            }
            result = _query_kuaidi100("SF0221700958051")
            assert result is not None
            assert result["low_confidence"] is True
            assert result["status"] in ("no_trace", "uncertain")
            assert result["is_delivered"] is False
            assert result["confirmed_delivered"] is False

    def test_a6_single_event_no_sign_context(self):
        """只有一条事件且无签收上下文 → low_confidence"""
        from app.agent.nodes.query_by_tracking_no import _query_kuaidi100
        import unittest.mock as mock
        with mock.patch("app.agent.nodes.query_by_tracking_no.query_tracking") as m:
            m.return_value = {
                "state": "3",
                "data": [{"time": "2026-05-01", "context": "快件已到达"}],
                "courier_name": "极兔速递",
                "tracking_no": "JT3164846725758",
            }
            result = _query_kuaidi100("JT3164846725758")
            assert result["low_confidence"] is True
            assert result["status"] == "uncertain"

    def test_a7_confirmed_delivered_with_sign_info(self):
        """有明确签收信息时 confirmed_delivered=True"""
        from app.agent.nodes.query_by_tracking_no import _query_kuaidi100
        import unittest.mock as mock
        with mock.patch("app.agent.nodes.query_by_tracking_no.query_tracking") as m:
            m.return_value = {
                "state": "3",
                "data": [
                    {"time": "2026-05-02 10:00", "context": "已签收，本人签收"},
                    {"time": "2026-05-01 08:00", "context": "派件中"},
                ],
                "courier_name": "顺丰速运",
                "tracking_no": "SF1234567890123",
            }
            result = _query_kuaidi100("SF1234567890123")
            assert result["low_confidence"] is False
            assert result["status"] == "delivered"
            assert result["confirmed_delivered"] is True


# ---------------------------------------------------------------------------
# B. verify_consistency 条件路由
# ---------------------------------------------------------------------------

class TestVerifyConsistency:
    """验证 verify_consistency 不再无条件进入 query_by_tracking_no"""

    def test_b1_conflict_routes_to_human_review(self):
        """冲突时 consistency_status=conflict"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "SF999999999999"},
            "live_order": {"o_id": "202501010001", "l_id": "ZT2025052101", "status": "已发货"},
            "order_found": True,
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result["consistency_status"] == "conflict"
        assert result["requires_human_review"] is True

    def test_b2_matched_with_order(self):
        """订单一致时 consistency_status=matched"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "ZT2025052101"},
            "live_order": {"o_id": "202501010001", "l_id": "ZT2025052101", "status": "已发货"},
            "order_found": True,
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result["consistency_status"] == "matched"

    def test_b3_need_order_lookup(self):
        """有 order_id 和 tracking_no 但订单还没查到"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "SF1234567890123"},
            "order_found": False,
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result["consistency_status"] == "need_order_lookup"

    def test_b4_tracking_only(self):
        """只有 tracking_no"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "", "tracking_no": "SF1234567890123"},
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result["consistency_status"] == "tracking_only"

    def test_b5_graph_routes_verify_properly(self):
        """图路由：verify_consistency 后根据 consistency_status 分流"""
        from app.agent.graph import _route_after_verify_consistency

        assert _route_after_verify_consistency({"consistency_status": "conflict"}) == "human_review"
        # 一致时走 tool_planner（新链路），不再直接走 jst_live_query
        assert _route_after_verify_consistency({"consistency_status": "matched"}) == "tool_planner"
        assert _route_after_verify_consistency({"consistency_status": "need_order_lookup"}) == "tool_planner"
        assert _route_after_verify_consistency({"consistency_status": "tracking_only"}) == "tool_planner"


# ---------------------------------------------------------------------------
# C. 订单优先级
# ---------------------------------------------------------------------------

class TestOrderPriority:
    """验证有订单号时优先查订单，不走快递查询"""

    def test_c1_order_id_routes_to_query_order(self):
        """有 order_id 时走 query_order 而非 query_tracking"""
        from app.agent.nodes.identifier_router import _route_identifier
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "", "possible_numeric_id": "", "product_name": ""},
            "risk_level": "low",
            "intent": "logistics",
        }
        assert _route_identifier(state) == "query_order"

    def test_c2_order_id_with_tracking_goes_verify(self):
        """同时有 order_id 和 tracking_no 走 verify_consistency"""
        from app.agent.nodes.identifier_router import _route_identifier
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "SF123", "possible_numeric_id": "", "product_name": ""},
            "risk_level": "low",
            "intent": "logistics",
        }
        assert _route_identifier(state) == "verify_consistency"

    def test_c3_slot_extract_order_id_from_semantic(self):
        """'订单 202501010001' 识别为 order_id"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "订单 202501010001 快递到哪了",
            "normalized_message": "订单 202501010001 快递到哪了",
            "order_id": "",
            "tracking_no": "",
            "trace_steps": [],
        }
        result = slot_extract(state)
        slots = result["slots"]
        assert slots["order_id"] == "202501010001"
        assert not slots["tracking_no"]


# ---------------------------------------------------------------------------
# D. 请求隔离 - 无旧单号污染
# ---------------------------------------------------------------------------

class TestNoPollution:
    """验证连续请求不会复用旧 tracking_no"""

    def test_d1_no_old_tracking_in_second_request(self):
        """第二次请求不包含第一次的 tracking_no"""
        from app.agent.nodes.slot_extract import slot_extract

        # 第一次
        state1 = {
            "customer_message": "SF0221700958051 快递到哪了",
            "normalized_message": "SF0221700958051 快递到哪了",
            "order_id": "",
            "tracking_no": "SF0221700958051",
            "trace_steps": [],
        }
        r1 = slot_extract(state1)
        assert r1["slots"]["tracking_no"] == "SF0221700958051"

        # 第二次（全新 state）
        state2 = {
            "customer_message": "书架什么时候发货",
            "normalized_message": "书架什么时候发货",
            "order_id": "",
            "tracking_no": "",
            "trace_steps": [],
        }
        r2 = slot_extract(state2)
        assert not r2["slots"]["tracking_no"]
        trace_summary = r2["trace_steps"][-1]["summary"]
        assert "SF0221700958051" not in trace_summary

    def test_d2_reply_no_old_tracking(self):
        """无快递单号的请求，回复不包含旧单号"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "书架什么时候发货",
            "slots": {"order_id": "", "tracking_no": "", "product_name": "书架"},
            "matched_product_name": "书架",
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "SF0221700958051" not in reply


# ---------------------------------------------------------------------------
# E. 回复安全 - 不暴露内部信息
# ---------------------------------------------------------------------------

class TestReplySafety:
    """验证回复不含内部标记"""

    def test_e1_no_internal_markers(self):
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "快递到哪了",
            "slots": {},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "低可信度" not in reply
        assert "系统提示" not in reply
        assert "GRAPH_EXECUTION_ERROR" not in reply
        assert "快递100" not in reply
        assert "low_confidence" not in reply

    def test_e2_no_internal_in_rewrite(self):
        """factual_guard 改写的回复不含内部标记"""
        from app.agent.nodes.factual_guard import _rewrite_low_confidence_reply
        state = {
            "logistics_trace": {
                "tracking_no": "SF0221700958051",
                "carrier": "顺丰速运",
                "low_confidence": True,
            },
        }
        reply = _rewrite_low_confidence_reply(state, "")
        assert "低可信度" not in reply
        assert "系统提示" not in reply
        assert "快递100" not in reply
        assert "low_confidence" not in reply

    def test_e3_outbound_rewrite_does_not_expose_identifier_or_fake_trace(self):
        """销售出库记录只能证明已发出，不能冒充快递在途节点。"""
        from app.agent.nodes.factual_guard import _rewrite_safe_reply

        reply = _rewrite_safe_reply({
            "intent": "logistics",
            "order_status": "shipped",
            "live_order": {
                "o_id": "INTERNAL-ORDER",
                "items": [{"name": "测试商品"}],
                "logistics_company": "德邦快递",
                "l_id": "DPK379205847601",
                "send_date": "2026-08-22 10:52:49",
            },
            "slots": {},
        }, "")

        assert "已经发出" in reply
        assert "德邦快递" in reply
        assert "中转" in reply or "派送" in reply
        assert "不能准确判断" in reply
        assert "DPK379205847601" not in reply
        assert "47601" not in reply
        assert "2026-08-22 10:52:49" not in reply
        assert "最新物流记录" not in reply
