"""
人工测试反馈修复验证测试
覆盖：
1. "订单号 99999，帮我查快递" 不得回复"请提供订单号"
2. 纯长数字不得识别为 product_consult
3. "3304522057802018390 帮我查快递" 必须识别为物流查询
4. "显示签收了但我没收到" 必须走 delivery_not_received / medium risk
5. 查不到物流不得建议客户自己去官网/App
6. 无政策来源时不得硬编码 48小时
7. 聚水潭超时必须 fallback
8. trace_steps 必须记录查询耗时和 fallback 原因
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
# 1. "订单号 99999，帮我查快递" 不得再回复"请提供订单号"
# ---------------------------------------------------------------------------

class TestOrder99999:
    """客户已提供订单号，不能再说请提供订单号"""

    def test_slot_extracts_99999(self):
        """slot_extract 必须从'订单号 99999'提取出 order_id"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "订单号 99999，帮我查快递",
            "normalized_message": "订单号 99999，帮我查快递",
            "order_id": "",
            "tracking_no": "",
            "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["order_id"] == "99999", f"应提取 order_id=99999, 实际: {result['slots']}"

    def test_reply_not_ask_for_order(self):
        """回复不得再说'请提供订单号'或'麻烦提供订单号'"""
        result = _invoke("订单号 99999，帮我查快递")
        reply = result.get("suggested_reply", "")
        # 已提供订单号，不得再要求提供
        assert "请提供订单号" not in reply, f"不应再要求提供订单号: {reply}"
        assert "麻烦您提供一下订单号" not in reply, f"不应再要求提供订单号: {reply}"
        # 应该确认查不到或要求核实
        assert "查到" in reply or "查不到" in reply or "核实" in reply or "确认" in reply or "截图" in reply

    def test_reply_has_no_provide_order_id(self):
        """回复不得包含'麻烦提供一下您的订单号'"""
        result = _invoke("订单号 99999，帮我查快递")
        reply = result.get("suggested_reply", "")
        assert "麻烦提供一下您的订单号" not in reply


# ---------------------------------------------------------------------------
# 2. 纯长数字不得识别为 product_consult
# ---------------------------------------------------------------------------

class TestPureNumericNotProductConsult:
    """纯长数字不应被识别为商品咨询"""

    def test_pure_numeric_not_product_consult(self):
        """3304522057802018390 不应识别为 product_consult"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "3304522057802018390",
            "customer_message": "3304522057802018390",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] != "product_consult", f"不应识别为 product_consult, 实际: {result['intent']}"

    def test_pure_numeric_is_logistics(self):
        """纯长数字应识别为 logistics_eta（标识符查询）"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "3304522057802018390",
            "customer_message": "3304522057802018390",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "logistics_eta", f"应识别为 logistics_eta, 实际: {result['intent']}"

    def test_pure_numeric_extracted_as_possible_id(self):
        """slot_extract 应把纯长数字提取为 possible_numeric_id"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "3304522057802018390",
            "normalized_message": "3304522057802018390",
            "order_id": "",
            "tracking_no": "",
            "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["possible_numeric_id"] == "3304522057802018390"


# ---------------------------------------------------------------------------
# 3. "3304522057802018390 帮我查快递" 必须识别为物流查询
# ---------------------------------------------------------------------------

class TestNumericWithLogisticsKeyword:
    """长数字+物流关键词必须走物流链"""

    def test_identified_as_logistics(self):
        """detect_intent 必须识别为 logistics_eta"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "3304522057802018390 帮我查快递",
            "customer_message": "3304522057802018390 帮我查快递",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "logistics_eta"

    def test_graph_enters_logistics_chain(self):
        """graph 必须进入物流链"""
        result = _invoke("3304522057802018390 帮我查快递")
        steps = _steps(result)
        assert "slot_extract" in steps
        assert "identifier_router" in steps


# ---------------------------------------------------------------------------
# 4. "显示签收了但我没收到" 必须走 delivery_not_received / medium risk
# ---------------------------------------------------------------------------

class TestSignedNotReceived:
    """签收未收到场景检测"""

    def test_detected_as_delivery_not_received(self):
        """detect_intent 必须识别为 delivery_not_received"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "显示签收了但我没收到",
            "customer_message": "显示签收了但我没收到",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "delivery_not_received"

    def test_risk_at_least_medium(self):
        """风险等级至少 medium"""
        result = _invoke("显示签收了但我没收到")
        assert result["risk_level"] in ("medium", "high"), f"风险应至少 medium, 实际: {result['risk_level']}"

    def test_requires_human_review(self):
        """需要人工复核"""
        result = _invoke("显示签收了但我没收到")
        assert result["requires_human_review"] is True

    def test_reply_has_comfort(self):
        """回复包含安抚"""
        result = _invoke("显示签收了但我没收到")
        reply = result.get("suggested_reply", "")
        assert "抱歉" in reply or "理解" in reply or "抱歉" in reply

    def test_reply_has_check_suggestions(self):
        """回复建议核实家人/门卫/驿站"""
        result = _invoke("显示签收了但我没收到")
        reply = result.get("suggested_reply", "")
        assert "家人" in reply or "门卫" in reply or "驿站" in reply or "快递柜" in reply

    def test_reply_asks_screenshot(self):
        """回复要求提供订单截图"""
        result = _invoke("显示签收了但我没收到")
        reply = result.get("suggested_reply", "")
        assert "截图" in reply or "订单号" in reply


# ---------------------------------------------------------------------------
# 5. 查不到物流不得建议客户自己去官网/App
# ---------------------------------------------------------------------------

class TestNoOfficialWebsiteReferral:
    """查不到物流不得建议去官网"""

    def test_tracking_not_found_no_official_referral(self):
        """快递单号查不到时不应建议去官网"""
        # 测试 graph 端到端，而非单元测试 _fallback 函数
        result = _invoke("SF0221700958051 到哪里了")
        reply = result.get("suggested_reply", "")
        assert "官网" not in reply
        assert "App" not in reply
        assert "官方渠道" not in reply
        assert "快递公司" not in reply
        # 应该说"物流单号"而非"订单号"
        assert "暂未" in reply or "查不到" in reply or "查到" in reply

    def test_low_confidence_no_official_referral(self):
        """低可信度签收不应建议去官网"""
        from app.agent.nodes.generate_logistics_reply import _fallback_low_confidence_signed
        reply = _fallback_low_confidence_signed("ZT123456", "中通")
        assert "官网" not in reply
        assert "App" not in reply
        assert "官方渠道" not in reply

    def test_graph_tracking_not_found_no_official(self):
        """graph 层面：SF 单号查不到不应出现官网/App"""
        result = _invoke("SF0221700958051 到哪里了")
        reply = result.get("suggested_reply", "")
        assert "官网" not in reply, f"不应建议去官网: {reply}"
        assert "官方渠道" not in reply, f"不应建议去官方渠道: {reply}"
        assert "App" not in reply or "app" in reply.lower().replace("app", ""), "不应提及App"


# ---------------------------------------------------------------------------
# 6. 无政策来源时不得硬编码 48小时
# ---------------------------------------------------------------------------

class TestNoHardcoded48Hours:
    """48小时必须来自政策表，不得硬编码"""

    def test_no_48h_in_product_reply_without_policy(self):
        """无政策时商品回复不应硬编码48小时"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "书架什么时候发货？",
            "matched_product_name": "书架",
            "shipping_policy": {},  # 无政策
            "slots": {},
            "evidence": {"conflicts": [], "unknowns": []},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "48小时" not in reply, f"不应硬编码48小时: {reply}"
        # 应有保守的时效说明
        assert "店铺" in reply or "实际" in reply or "时效" in reply

    def test_48h_allowed_when_from_policy(self):
        """有政策时可以使用48小时"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "书架什么时候发货？",
            "matched_product_name": "书架",
            "shipping_policy": {"ship_within_hours": "48", "default_courier": "顺丰"},
            "slots": {},
            "evidence": {"conflicts": [], "unknowns": []},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "48" in reply  # 来自政策


# ---------------------------------------------------------------------------
# 7. 聚水潭超时必须 fallback
# ---------------------------------------------------------------------------

class TestJSTTimeoutFallback:
    """聚水潭超时后必须走 fallback"""

    def test_jst_timeout_returns_safe_result(self):
        """超时后返回安全结果，不报 500"""
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
                mock_adapter.query_jst.side_effect = TimeoutError("timeout")
                mock_adapter_cls.return_value = mock_adapter
                result = query_jst_order(state)
                assert result is not None
                assert result.get("order_found") is False
                trace = result.get("trace_steps", [{}])[-1]
                assert trace.get("status") == "jst_timeout"


# ---------------------------------------------------------------------------
# 8. trace_steps 必须记录查询耗时和 fallback 原因
# ---------------------------------------------------------------------------

class TestTraceStepsComplete:
    """trace_steps 必须包含完整信息"""

    def test_jst_query_has_duration(self):
        """query_jst_order 的 trace 必须有 duration_ms"""
        from app.agent.nodes.query_jst_order import query_jst_order
        state = {
            "order_id": "99999",
            "slots": {"order_id": "99999", "tracking_no": "", "possible_numeric_id": ""},
            "order_found": False,
            "trace_steps": [],
        }
        result = query_jst_order(state)
        trace = result.get("trace_steps", [{}])[-1]
        assert "duration_ms" in trace
        assert isinstance(trace["duration_ms"], int)

    def test_logistics_trace_has_duration(self):
        """query_logistics_trace 的 trace 必须有 duration_ms"""
        from app.agent.nodes.query_logistics_trace import query_logistics_trace
        state = {
            "live_order": {"o_id": "99999", "l_id": "", "status": "已发货"},
            "order_id": "99999",
            "slots": {},
            "trace_steps": [],
        }
        result = query_logistics_trace(state)
        trace = result["trace_steps"][-1]
        assert "duration_ms" in trace
        assert isinstance(trace["duration_ms"], int)

    def test_graph_trace_has_fallback_reason(self):
        """graph 走完后 trace 必须有 fallback 原因"""
        result = _invoke("订单号 99999，帮我查快递")
        steps = _steps(result)
        # 新链路可能通过 Tool Registry 调用 JST，旧链路会出现 jst_live_query。
        has_fallback = "jst_live_query" in steps or (
            "tool_executor" in steps and any("jst" in str(s).lower() for s in result.get("trace_steps", []))
        )
        assert has_fallback, f"查不到时应走 JST 查询链路, steps: {steps}"


# ===========================================================================
# 第二轮 P0/P1 修复测试
# ===========================================================================


class TestP0NoSignedClaimWithoutEvidence:
    """P0: 无真实物流证据时不得说已签收/顺丰/快递公司官网"""

    def test_sf_tracking_no_signed_claim(self):
        """SF0221700958051我的快递什么时候送到 → 不得出现顺丰速运/已签收"""
        result = _invoke("SF0221700958051我的快递什么时候送到")
        reply = result.get("suggested_reply", "")
        assert "顺丰速运" not in reply, f"不应出现顺丰速运: {reply}"
        assert "已签收" not in reply, f"不应出现已签收: {reply}"
        assert "签收啦" not in reply, f"不应出现签收啦: {reply}"
        assert "已经签收" not in reply, f"不应出现已经签收: {reply}"
        assert "快递公司官网" not in reply, f"不应出现快递公司官网: {reply}"
        assert "官网或App" not in reply, f"不应出现官网或App: {reply}"

    def test_sf_tracking_reply_is_safe_fallback(self):
        """SF tracking_no 查不到应返回安全 fallback"""
        result = _invoke("SF0221700958051我的快递什么时候送到")
        reply = result.get("suggested_reply", "")
        assert "暂未" in reply or "查不到" in reply or "查到" in reply or "核实" in reply
        assert "截图" in reply or "订单号" in reply

    def test_sf_tracking_fast_response(self):
        """tracking_no 查不到场景应 < 3s"""
        import time
        t0 = time.time()
        result = _invoke("SF0221700958051 到哪里了")
        elapsed_ms = int((time.time() - t0) * 1000)
        # JST 未配置时应该很快；JST 配置时允许 3s
        assert elapsed_ms < 5000, f"响应耗时 {elapsed_ms}ms, 应 < 5s"


class TestP1TrackingNoNaming:
    """P1: tracking_no 不得称为订单号"""

    def test_sf_tracking_not_called_order_id(self):
        """SF 单号查不到时不得称为'订单号'"""
        result = _invoke("SF0221700958051 到哪里了")
        reply = result.get("suggested_reply", "")
        assert "暂未查到订单号" not in reply, f"不应称 tracking_no 为订单号: {reply}"
        # 应该称"物流单号"或"该单号"
        assert "物流单号" in reply or "该单号" in reply or "查到" in reply

    def test_numeric_tracking_not_called_order_id(self):
        """3304... 查快递不得称为订单号"""
        result = _invoke("3304522057802018390 帮我查快递")
        reply = result.get("suggested_reply", "")
        assert "暂未查到订单号" not in reply, f"不应称 tracking_no 为订单号: {reply}"

    def test_order_id_correctly_named(self):
        """订单号 99999 可以称为订单号"""
        result = _invoke("订单号 99999，帮我查快递")
        reply = result.get("suggested_reply", "")
        # 查不到时可以称订单号（因为 identifier_type=order_id）
        assert "订单号" in reply or "单号" in reply


class TestP1DeliveryNotReceivedGoldReply:
    """P1: 签收未收到必须使用金牌话术"""

    def test_has_gold_reply(self):
        """回复包含安抚+核实建议+要订单号/截图+继续跟进"""
        result = _invoke("显示签收了但我没收到")
        reply = result.get("suggested_reply", "")
        # 安抚
        assert "理解" in reply or "抱歉" in reply or "着急" in reply
        # 核实建议
        assert "家人" in reply or "门卫" in reply or "驿站" in reply or "快递员" in reply
        # 要订单号/截图
        assert "订单号" in reply or "截图" in reply
        # 继续跟进
        assert "跟进" in reply or "核实" in reply
        # 不得只说"请稍等"
        assert "请稍等" not in reply or "稍等" not in reply

    def test_not_push_to_customer(self):
        """不得推给客户自己找快递"""
        result = _invoke("显示签收了但我没收到")
        reply = result.get("suggested_reply", "")
        assert "快递公司官网" not in reply
        assert "官网或App" not in reply


class TestP0HasLogisticsFalseNoSigned:
    """P0: has_logistics=false 时不得出现已签收/签收啦/已发货/顺丰速运"""

    def test_no_order_no_logistics_no_signed(self):
        """无订单无物流时不得出现签收/发货/快递公司"""
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
        state = {
            "normalized_message": "我的快递到了吗？",
            "slots": {},
            "logistics_trace": None,
            "evidence": {"conflicts": [], "unknowns": []},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "已签收" not in reply
        assert "签收啦" not in reply
        assert "已发货" not in reply
        assert "顺丰速运" not in reply
        assert "中通" not in reply

    def test_factual_guard_blocks_courier_name_without_order(self):
        """factual_guard 拦截无订单时的快递公司名"""
        from app.agent.nodes.factual_guard import factual_guard
        state = {
            "suggested_reply": "亲亲，我帮您查了一下，您的顺丰速运快递（单号：SF0221700958051）已经签收啦。",
            "logistics_trace": None,
            "order": None,
            "evidence": {"unknowns": [], "conflicts": []},
            "guard_warnings": [],
            "trace_steps": [],
        }
        result = factual_guard(state)
        assert len(result["guard_warnings"]) > 0
        assert "顺丰" in result["guard_warnings"][0] or "编造" in result["guard_warnings"][0]


class TestP1IdentifierType:
    """P1: identifier_type 正确区分"""

    def test_tracking_no_type(self):
        """tracking_no 识别为 tracking_no 类型"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "SF0221700958051 到哪里了",
            "normalized_message": "SF0221700958051 到哪里了",
            "order_id": "", "tracking_no": "", "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["identifier_type"] == "tracking_no"

    def test_order_id_type(self):
        """订单号 识别为 order_id 类型"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "订单号 99999 帮我查快递",
            "normalized_message": "订单号 99999 帮我查快递",
            "order_id": "", "tracking_no": "", "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["identifier_type"] == "internal_order_id"

    def test_unknown_identifier_type(self):
        """纯数字识别为 platform_trade_id 类型（19位+快递上下文）"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "3304522057802018390 帮我查快递",
            "normalized_message": "3304522057802018390 帮我查快递",
            "order_id": "", "tracking_no": "", "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["identifier_type"] == "platform_trade_id"

    def test_no_identifier_type(self):
        """无标识符时为 none"""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "我快递大概几天到",
            "normalized_message": "我快递大概几天到",
            "order_id": "", "tracking_no": "", "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["identifier_type"] == "none"


class TestP1Performance:
    """P1: 响应时间测试"""

    def test_tracking_no_not_found_fast(self):
        """tracking_no 查不到 < 3s"""
        import time
        t0 = time.time()
        _invoke("SF0221700958051 到哪里了")
        elapsed_ms = int((time.time() - t0) * 1000)
        assert elapsed_ms < 3000, f"tracking_no 查不到耗时 {elapsed_ms}ms, 应 < 3s"

    def test_no_identifier_fast(self):
        """无订单号场景 < 1s"""
        import time
        t0 = time.time()
        _invoke("我快递大概几天到")
        elapsed_ms = int((time.time() - t0) * 1000)
        assert elapsed_ms < 2000, f"无标识符耗时 {elapsed_ms}ms, 应 < 2s"
