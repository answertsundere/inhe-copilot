"""
物流链路短路、话术去重测试
（已移除快递100依赖，全部走聚水潭）
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------------------------------------------------------------------------
# 1. 话术去重：不重复提示"提供订单号"
# ---------------------------------------------------------------------------

class TestReplyNotDuplicate:
    def test_tracking_low_confidence_reply_not_duplicate(self):
        """低可信度回复中'订单号'只出现一次"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "SF0221700958051我的快递什么时候送到",
            "slots": {"tracking_no": "SF0221700958051", "order_id": ""},
            "logistics_trace": {
                "status": "uncertain",
                "carrier": "顺丰速运",
                "tracking_no": "SF0221700958051",
                "is_delivered": False,
                "low_confidence": True,
                "latest": {"time": "2026-05-01", "context": "查无结果"},
            },
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "已签收" not in reply
        assert "已经签收" not in reply
        assert "签收啦" not in reply
        assert "低可信度" not in reply
        assert "系统提示" not in reply
        assert reply.count("订单号") <= 1, f"'订单号'出现{reply.count('订单号')}次，回复: {reply}"


# ---------------------------------------------------------------------------
# 2. 快递单号走聚水潭查订单（不再走快递100）
# ---------------------------------------------------------------------------

class TestTrackingViaJST:
    def test_tracking_no_routes_to_jst(self):
        """有快递单号时走聚水潭查订单（identifier_router）"""
        from app.agent.nodes.identifier_router import _route_identifier
        state = {
            "slots": {"tracking_no": "SF0221700958051", "order_id": "", "possible_numeric_id": "", "product_name": ""},
            "risk_level": "low",
            "intent": "logistics_eta",
        }
        route = _route_identifier(state)
        assert route == "query_order"

    def test_tracking_and_order_routes_to_verify(self):
        """同时有快递单号和订单号走 verify_consistency"""
        from app.agent.nodes.identifier_router import _route_identifier
        state = {
            "slots": {"tracking_no": "SF0221700958051", "order_id": "202501010001", "possible_numeric_id": "", "product_name": ""},
            "risk_level": "low",
            "intent": "logistics_eta",
        }
        route = _route_identifier(state)
        assert route == "verify_consistency"


# ---------------------------------------------------------------------------
# 3. build_response 不追加温馨提示
# ---------------------------------------------------------------------------

class TestBuildResponse:
    def test_no_system_suffix(self):
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
# 4. query_logistics_trace 走聚水潭
# ---------------------------------------------------------------------------

class TestLogisticsTraceJST:
    def test_logistics_trace_has_duration(self):
        """query_logistics_trace 的 trace 包含 duration_ms"""
        from app.agent.nodes.query_logistics_trace import query_logistics_trace
        state = {
            "live_order": {"o_id": "202501010001", "l_id": "ZT2025052101", "status": "已发货"},
            "order_id": "202501010001",
            "slots": {},
            "trace_steps": [],
        }
        result = query_logistics_trace(state)
        trace = result["trace_steps"][-1]
        assert "duration_ms" in trace
        assert isinstance(trace["duration_ms"], int)
        assert trace.get("status") in ("success", "skipped")

    def test_logistics_trace_no_duplicate(self):
        """已有 logistics_trace 时跳过"""
        from app.agent.nodes.query_logistics_trace import query_logistics_trace
        state = {
            "live_order": {"o_id": "202501010001", "l_id": "ZT123", "status": "已发货"},
            "logistics_trace": {
                "status": "delivered",
                "carrier": "中通",
                "tracking_no": "ZT123",
                "is_delivered": True,
            },
            "trace_steps": [],
        }
        result = query_logistics_trace(state)
        trace = result["trace_steps"][-1]
        assert trace.get("cache_hit") is True or "跳过" in trace.get("summary", "")
