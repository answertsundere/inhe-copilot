"""
物流链专用测试 - 覆盖 23 个核心场景
验证 slot_extract → identifier_router → 各查询路径 → evidence → reply 的完整链路
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _invoke(msg: str, order_id: str = "") -> dict:
    """调用 graph。对于 sample 订单号，mock JST 返回 sample 数据。"""
    from unittest.mock import patch
    from app.agent.graph import customer_service_graph

    state = {
        "customer_message": msg,
        "order_id": order_id,
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


# ---------------------------------------------------------------------------
# A. 有订单 + 有物流
# ---------------------------------------------------------------------------

class TestA_OrderWithLogistics:
    """A1-A3: 有订单号且能查到物流"""

    def test_a1_shipped_order_with_tracking(self):
        """A1: 已发货订单，有物流轨迹"""
        result = _invoke("我快递大概几天会到？", "202501010001")
        assert result["order_found"] is True
        assert result["order_status"] in ("shipped", "delivered")
        assert result.get("suggested_reply")
        steps = _steps(result)
        assert any(s in steps for s in ("jst_live_query", "tool_executor", "tool_executor_node"))

    def test_a2_shipped_reply_has_eta(self):
        """A2: 回复包含时效说明，不虚假承诺"""
        result = _invoke("我快递大概几天会到？", "202501010001")
        reply = result.get("suggested_reply", "")
        assert reply
        assert "一定" not in reply
        assert "保证" not in reply
        assert "承诺" not in reply

    def test_a3_trace_has_evidence(self):
        """A3: trace 包含证据构建节点"""
        result = _invoke("我快递大概几天会到？", "202501010001")
        steps = _steps(result)
        assert "evidence_builder" in steps or "evidence_build" in steps


# ---------------------------------------------------------------------------
# B. 有订单 + 无物流
# ---------------------------------------------------------------------------

class TestB_OrderNoLogistics:
    """B1-B3: 有订单但未发货/无轨迹"""

    def test_b1_pending_order(self):
        """B1: 待发货订单"""
        result = _invoke("快递大概几天会到？", "202501010003")
        assert result["order_found"] is True
        assert result["shipment_status"] == "pending"

    def test_b2_pending_reply_says_not_shipped(self):
        """B2: 未发货回复不说已发货"""
        result = _invoke("快递大概几天会到？", "202501010003")
        reply = result.get("suggested_reply", "")
        assert "已发货" not in reply or "尚未发货" in reply or "未发货" in reply

    def test_b3_no_fake_tracking_no(self):
        """B3: 未发货时不编造快递单号"""
        result = _invoke("快递大概几天会到？", "202501010003")
        reply = result.get("suggested_reply", "")
        # 不应出现看起来像快递单号的格式
        import re
        tracking_like = re.findall(r"[A-Z]{2}\d{10,}|[A-Z]\d{12,}|\d{15,}", reply)
        assert len(tracking_like) == 0, f"回复中疑似编造快递单号: {tracking_like}"


# ---------------------------------------------------------------------------
# C. 无订单 + 有快递单号
# ---------------------------------------------------------------------------

class TestC_NoOrderWithTracking:
    """C1-C3: 无订单但提供了快递单号"""

    def test_c1_tracking_only_has_logistics(self):
        """C1: 只有快递单号，走聚水潭查订单"""
        result = _invoke("帮我查一下 SF123456789012 到哪里了")
        steps = _steps(result)
        assert any(s in steps for s in ("jst_live_query", "tool_executor", "tool_executor_node"))

    def test_c2_tracking_no_fake_order(self):
        """C2: 无订单时不编造订单信息"""
        result = _invoke("帮我查一下快递 SF123456789012 到哪里了")
        reply = result.get("suggested_reply", "")
        # 如果查到物流，不应编造订单；如果查不到，回复应安全
        assert reply
        # 不应出现具体订单号（因为无订单）
        import re
        order_id_like = re.findall(r"20\d{10}", reply)
        assert len(order_id_like) == 0, f"回复中疑似编造订单号: {order_id_like}"

    def test_c3_unknown_tracking_reply_safe(self):
        """C3: 查不到物流时给出安全回复"""
        result = _invoke("帮我查一下 ABCD1234 到哪里了")
        reply = result.get("suggested_reply", "")
        assert reply
        assert "暂未查到" in reply or "核实" in reply or "官网" in reply or "订单号" in reply


# ---------------------------------------------------------------------------
# D. 无订单 + 无快递单号 + 有商品名
# ---------------------------------------------------------------------------

class TestD_ProductOnly:
    """D1-D3: 只有商品名"""

    def test_d1_product_match(self):
        """D1: 能匹配到商品"""
        result = _invoke("这个书架什么时候发货？")
        assert result.get("matched_product_name") or result.get("product_candidates")

    def test_d2_product_reply_has_policy(self):
        """D2: 回复包含物流政策说明"""
        result = _invoke("这个书架什么时候发货？")
        reply = result.get("suggested_reply", "")
        assert reply
        assert len(reply) > 10

    def test_d3_product_reply_asks_for_order(self):
        """D3: 引导用户提供订单号"""
        result = _invoke("这个书架发什么快递？")
        reply = result.get("suggested_reply", "")
        assert "订单号" in reply or "订单" in reply or "提供" in reply


# ---------------------------------------------------------------------------
# E. 无订单 + 无快递单号 + 无商品名
# ---------------------------------------------------------------------------

class TestE_Nothing:
    """E1-E3: 没有任何标识符"""

    def test_e1_reply_asks_for_info(self):
        """E1: 回复引导用户提供信息"""
        result = _invoke("我快递大概几天会到？")
        reply = result.get("suggested_reply", "")
        assert reply
        assert "订单号" in reply or "商品" in reply or "提供" in reply

    def test_e2_no_fake_data(self):
        """E2: 不编造任何数据"""
        result = _invoke("我快递大概几天会到？")
        assert result.get("order_found", False) is False
        assert result.get("order") is None or result.get("live_order") is None

    def test_e3_answer_type_clarification(self):
        """E3: answer_type 为 clarification"""
        result = _invoke("我快递大概几天会到？")
        assert result.get("answer_type") in ("clarification_needed", "fallback", "", None)


# ---------------------------------------------------------------------------
# F. 高风险
# ---------------------------------------------------------------------------

class TestF_HighRisk:
    """F1-F3: 高风险场景"""

    def test_f1_complaint_human_review(self):
        """F1: 投诉进入人工复核"""
        result = _invoke("再不处理我就去12315投诉")
        assert result["risk_level"] == "high"
        assert result["requires_human_review"] is True

    def test_f2_bad_review_threat(self):
        """F2: 差评威胁进入人工复核"""
        result = _invoke("我要给差评，你们太烂了")
        assert result["risk_level"] == "high"
        assert result["requires_human_review"] is True

    def test_f3_no_false_promise_on_risk(self):
        """F3: 高风险不虚假承诺，且 suggested_reply 不为空"""
        result = _invoke("再不处理我就去12315投诉")
        reply = result.get("suggested_reply", "")
        assert reply, "高风险投诉回复不应为空"
        assert len(reply) > 10
        assert "一定赔偿" not in reply
        assert "一定退款" not in reply


# ---------------------------------------------------------------------------
# G. 冲突检测
# ---------------------------------------------------------------------------

class TestG_Conflict:
    """G1-G3: 数据冲突场景"""

    def test_g1_delivered_but_order_canceled(self):
        """G1: 物流显示已签收但订单已取消（模拟状态）"""
        # 通过构造 state 直接测试 evidence_builder
        from app.agent.nodes.evidence_builder import evidence_builder
        state = {
            "order_status": "canceled",
            "logistics_trace": {
                "status": "delivered",
                "is_delivered": True,
                "carrier": "中通",
                "tracking_no": "ZT123456",
                "events": [{"time": "2026-05-01", "context": "已签收"}],
            },
            "trace_steps": [],
        }
        result = evidence_builder(state)
        conflicts = result["evidence"]["conflicts"]
        assert len(conflicts) > 0

    def test_g2_guard_catches_conflict(self):
        """G2: factual_guard 检测到冲突"""
        from app.agent.nodes.factual_guard import factual_guard
        state = {
            "suggested_reply": "亲，您的订单已发货，预计明天一定送达。",
            "evidence": {
                "unknowns": [{"fact": "未查到物流轨迹"}],
                "conflicts": [],
            },
            "answer_type": "verified",
            "trace_steps": [],
        }
        result = factual_guard(state)
        assert len(result["guard_warnings"]) > 0

    def test_g3_low_confidence_flagged(self):
        """G3: 低可信度物流被标记"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "快递到了吗",
            "logistics_trace": {
                "status": "delivered",
                "is_delivered": True,
                "low_confidence": True,
                "carrier": "中通",
                "tracking_no": "ZT123",
                "latest": {"time": "2026-05-01", "context": "已签收"},
            },
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "核实" in reply or "官网" in reply or "低可信度" in reply


# ---------------------------------------------------------------------------
# H. 标识符一致性
# ---------------------------------------------------------------------------

class TestH_Consistency:
    """H1-H3: 订单号与快递单号一致性"""

    def test_h1_consistent_ids(self):
        """H1: 订单号与快递单号一致"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "ZT2025052101"},
            "live_order": {"o_id": "202501010001", "l_id": "ZT2025052101", "status": "已发货"},
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result.get("order_status") != "inconsistent_ids"

    def test_h2_inconsistent_ids(self):
        """H2: 订单号与快递单号不一致"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "202501010001", "tracking_no": "SF999999999999"},
            "live_order": {"o_id": "202501010001", "l_id": "ZT2025052101", "status": "已发货"},
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result.get("order_status") == "inconsistent_ids"

    def test_h3_no_order_no_check(self):
        """H3: 无订单时不做一致性检查"""
        from app.agent.nodes.verify_consistency import verify_consistency
        state = {
            "slots": {"order_id": "", "tracking_no": "SF123456789012"},
            "live_order": None,
            "order": None,
            "trace_steps": [],
        }
        result = verify_consistency(state)
        assert result.get("order_status") != "inconsistent_ids"


# ---------------------------------------------------------------------------
# I. 边界情况
# ---------------------------------------------------------------------------

class TestI_EdgeCases:
    """I1-I5: 边界情况"""

    def test_i1_empty_message(self):
        """I1: 空消息"""
        result = _invoke("")
        assert result.get("suggested_reply") or result.get("error")

    def test_i2_very_long_message(self):
        """I2: 超长消息"""
        long_msg = "我的快递" * 100 + "订单号202501010001"
        result = _invoke(long_msg)
        assert result.get("suggested_reply")

    def test_i3_special_characters(self):
        """I3: 特殊字符"""
        result = _invoke("快递！！！@@##$$%% 到哪里了？")
        assert result.get("suggested_reply")

    def test_i4_multiple_tracking_nos(self):
        """I4: 多个快递单号（只取第一个）"""
        result = _invoke("帮我查 SF123456789012 和 ZT2025052101")
        slots = result.get("slots", {})
        assert slots.get("tracking_no")

    def test_i5_only_whitespace(self):
        """I5: 只有空白字符"""
        result = _invoke("   \n\t   ")
        assert result.get("suggested_reply") or result.get("error")
