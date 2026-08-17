"""
回归测试 - 订单号识别、意图路由、回复正确性
覆盖：
1. API order_id 能进入 slots/state
2. 已提供 order_id 时 planner 不设置 order_id 为 missing
3. API 单独传入订单号时 router_validation 能锁定 logistics
4. 规则物流意图不会被 LLM product/general 结果覆盖
5. 已有订单号但订单未查到时，不会再次索要订单号
6. 不同 conversation_id 的上下文相互隔离
7. 新会话不会继承旧会话的 intent、slots 或 active_issue
8. 待发货、已发货、已签收未收到分别进入正确流程
9. 退货退款不会被路由为商品咨询或普通物流
10. Grounding Guard 不会把一般性物流解释误判为具体状态声明
11. 原有投诉和高风险流程不回归
12. 正文订单号提取正常
"""

import sys
import os
import json
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _get_flask_client():
    """获取 Flask test client"""
    from app.main import create_app

    saved_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "test_fb_regression.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "test_rq_regression.jsonl")
    os.environ["COPILOT_LLM_API_KEY"] = ""

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    os.environ["COPILOT_LLM_API_KEY"] = saved_key
    return client


@pytest.fixture
def flask_client():
    c = _get_flask_client()
    yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _analyze(client, message, order_id="", tracking_no="", conversation_id="test_regression"):
    """Call /api/analyze and return JSON response."""
    resp = client.post("/api/analyze", json={
        "message": message,
        "order_id": order_id,
        "tracking_no": tracking_no,
        "conversation_id": conversation_id,
    })
    assert resp.status_code == 200, f"API returned {resp.status_code}: {resp.data[:500]}"
    return resp.get_json()


# ===========================================================================
# Test 1: API order_id enters slots/state
# ===========================================================================

class TestAPIOrderIdEntersState:
    """API order_id should be available in slots/state throughout the pipeline."""

    def test_api_order_id_in_slots(self):
        """slot_extract should populate order_id from API input."""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "快递到哪了",
            "order_id": "202501010001",
            "trace_steps": [],
        }
        result = slot_extract(state)
        slots = result["slots"]
        assert slots["order_id"] == "202501010001"
        assert slots["identifier_type"] == "internal_order_id"

    def test_long_api_order_id_is_platform_trade_id(self):
        """Real Qianniu/JST long numeric order ids should use platform trade lookup."""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "帮我查一下这个订单发货了吗？",
            "normalized_message": "帮我查一下这个订单发货了吗？",
            "order_id": "6926666820903533935",
            "trace_steps": [],
        }
        result = slot_extract(state)
        slots = result["slots"]
        assert slots["order_id"] == "6926666820903533935"
        assert slots["platform_trade_id"] == "6926666820903533935"
        assert slots["identifier_type"] == "platform_trade_id"

    def test_api_order_id_propagated_to_state(self):
        """slot_extract should set top-level order_id."""
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "快递到哪了",
            "order_id": "202501010001",
            "trace_steps": [],
        }
        result = slot_extract(state)
        assert result.get("order_id") == "202501010001"


# ===========================================================================
# Test 2: Planner doesn't set order_id as missing when already provided
# ===========================================================================

class TestPlannerNoDuplicateRequest:
    """response_strategy_planner should not add order_id to missing_slots when already present."""

    def test_logistics_intent_with_order_id_no_missing(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner
        state = {
            "intent": "logistics_eta",
            "customer_concern": "unknown",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "我的快递到哪了",
            "order_id": "202501010001",
            "slots": {"order_id": "202501010001", "tracking_no": "", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = response_strategy_planner(state)
        plan = result["response_strategy_plan"]
        assert "order_id" not in plan["missing_slots"], (
            f"order_id should not be in missing_slots when already provided, got: {plan['missing_slots']}"
        )
        assert plan["should_ask_slot"] is False

    def test_logistics_without_identifier_exposes_alternative_input_slots(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner

        result = response_strategy_planner({
            "intent": "logistics_trace",
            "customer_concern": "unknown",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "Please help check the shipment status.",
            "slots": {},
            "trace_steps": [],
        })

        plan = result["response_strategy_plan"]
        assert plan["should_ask_slot"] is True
        assert plan["missing_slots"] == ["order_id", "tracking_no"]
        assert plan["missing_slot_mode"] == "any_of"

    def test_eta_certainty_with_order_id_no_missing(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner
        state = {
            "intent": "logistics_eta",
            "customer_concern": "wants_eta_certainty",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "今天一定到吗",
            "order_id": "202501010001",
            "slots": {"order_id": "202501010001", "tracking_no": "", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = response_strategy_planner(state)
        plan = result["response_strategy_plan"]
        assert "order_id" not in plan["missing_slots"]

    def test_angry_about_delay_with_order_id_no_missing(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner
        state = {
            "intent": "logistics_eta",
            "customer_concern": "angry_about_delay",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "太慢了到底什么时候发货",
            "order_id": "202501010001",
            "slots": {"order_id": "202501010001", "tracking_no": "", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = response_strategy_planner(state)
        plan = result["response_strategy_plan"]
        assert "order_id" not in plan["missing_slots"]

    def test_delivery_not_received_with_order_id_no_missing(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner
        state = {
            "intent": "delivery_not_received",
            "customer_concern": "unknown",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "显示签收了但我没收到",
            "order_id": "202501010002",
            "slots": {"order_id": "202501010002", "tracking_no": "", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = response_strategy_planner(state)
        plan = result["response_strategy_plan"]
        assert "order_id" not in plan["missing_slots"]

    def test_live_logistics_fact_overrides_eta_certainty_strategy(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner

        result = response_strategy_planner({
            "intent": "logistics_eta",
            "customer_concern": "wants_eta_certainty",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "Where is the shipment now?",
            "slots": {
                "platform_trade_id": "PLATFORM-REFERENCE",
                "identifier_type": "platform_trade_id",
            },
            "order_found": True,
            "live_order": {
                "status": "Confirmed",
                "logistics_company": "carrier",
                "l_id": "TRACKING-REFERENCE",
            },
            "logistics_trace": {
                "found": True,
                "latest_status": "shipped",
            },
            "trace_steps": [],
        })

        plan = result["response_strategy_plan"]
        assert plan["reply_goal"] == "query_order_status"
        assert plan["should_answer_directly"] is True
        assert plan["should_ask_slot"] is False
        assert plan["missing_slots"] == []

    def test_aftersales_without_identifier_requests_one_order_reference(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner

        result = response_strategy_planner({
            "intent": "aftersales",
            "customer_concern": "unknown",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "Please explain how the applicable resolution is checked.",
            "slots": {},
            "trace_steps": [],
        })

        plan = result["response_strategy_plan"]
        assert plan["should_ask_slot"] is True
        assert plan["missing_slots"] == ["order_id", "tracking_no"]
        assert plan["missing_slot_mode"] == "any_of"
        assert result["requires_human_review"] is True

    def test_aftersales_with_identifier_does_not_request_it_again(self):
        from app.agent.nodes.response_strategy_planner import response_strategy_planner

        result = response_strategy_planner({
            "intent": "aftersales",
            "customer_concern": "unknown",
            "customer_state": {},
            "conversation_context": {},
            "normalized_message": "Please explain how the applicable resolution is checked.",
            "slots": {
                "order_id": "ORDER-REFERENCE",
                "identifier_type": "internal_order_id",
            },
            "trace_steps": [],
        })

        plan = result["response_strategy_plan"]
        assert plan["should_ask_slot"] is False
        assert plan["missing_slots"] == []
        assert plan["missing_slot_mode"] == "none"
        assert result["requires_human_review"] is True


# ===========================================================================
# Test 3: router_validation locks logistics when API order_id provided
# ===========================================================================

class TestRouterValidationWithAPIOrderId:
    """router_validation should set logistics intent when slots have order_id + logistics terms."""

    def test_api_order_id_logistics_terms(self):
        from app.agent.nodes.router_validation import router_validation
        state = {
            "normalized_message": "我的快递到哪了",
            "customer_message": "我的快递到哪了",
            "slots": {"order_id": "202501010001", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010001",
            "conversation_context": {},
            "router_decision": {"intent": "product_question"},
            "intent": "logistics_eta",
            "router_source": "llm",
            "router_reason": "",
            "selected_tool": "none",
            "trace_steps": [],
        }
        result = router_validation(state)
        assert result["intent"] in ("logistics_eta", "logistics_trace"), (
            f"Expected logistics intent with order_id + logistics terms, got: {result['intent']}"
        )

    def test_api_order_id_no_numeric_in_message(self):
        """When order_id is in API/slots but NOT in message text, logistics should still be set."""
        from app.agent.nodes.router_validation import router_validation
        state = {
            "normalized_message": "什么时候发货",
            "customer_message": "什么时候发货",
            "slots": {"order_id": "202501010003", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010003",
            "conversation_context": {},
            "router_decision": {"intent": "general"},
            "intent": "general",
            "router_source": "llm",
            "router_reason": "LLM routed to general",
            "selected_tool": "none",
            "trace_steps": [],
        }
        result = router_validation(state)
        assert result["intent"] in ("logistics_eta", "logistics_trace"), (
            f"Expected logistics intent, got: {result['intent']}, reason: {result.get('router_reason')}"
        )


# ===========================================================================
# Test 4: Rule logistics intent not overridden by LLM
# ===========================================================================

class TestLLMIntentRouterProtection:
    """LLM router should not override high-confidence rule-detected logistics intent."""

    def test_sanitize_blocks_logistics_to_product_override(self):
        from app.agent.nodes.llm_intent_router import _sanitize_decision
        state = {
            "intent": "logistics_eta",
            "slots": {"order_id": "202501010001", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010001",
            "normalized_message": "我的快递到哪了",
            "customer_message": "我的快递到哪了",
        }
        # LLM tries to override to product_question
        decision = {
            "intent": "product_question",
            "confidence": 0.9,
            "identifier_type": "none",
            "identifier_value": "",
            "product_name": "",
            "question_type": "unknown",
            "need_tool": False,
            "tool_name": "none",
            "reason": "LLM thinks it's product question",
        }
        result = _sanitize_decision(decision, state)
        assert result["intent"] in ("logistics_eta", "logistics_trace"), (
            f"LLM should not override logistics to product_question, got: {result['intent']}"
        )

    def test_sanitize_blocks_aftersales_to_product_override(self):
        from app.agent.nodes.llm_intent_router import _sanitize_decision
        state = {
            "intent": "aftersales",
            "slots": {"order_id": "202501010002", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010002",
            "normalized_message": "这个订单我要退货退款",
            "customer_message": "这个订单我要退货退款",
        }
        decision = {
            "intent": "product_question",
            "confidence": 0.8,
            "identifier_type": "none",
            "identifier_value": "",
            "product_name": "",
            "question_type": "unknown",
            "need_tool": False,
            "tool_name": "none",
            "reason": "LLM override",
        }
        result = _sanitize_decision(decision, state)
        assert result["intent"] == "aftersales"

    def test_sanitize_blocks_complaint_to_general_override(self):
        from app.agent.nodes.llm_intent_router import _sanitize_decision
        state = {
            "intent": "complaint",
            "slots": {},
            "normalized_message": "再不处理我就去12315投诉",
            "customer_message": "再不处理我就去12315投诉",
        }
        decision = {
            "intent": "general",
            "confidence": 0.7,
            "identifier_type": "none",
            "identifier_value": "",
            "product_name": "",
            "question_type": "unknown",
            "need_tool": False,
            "tool_name": "none",
            "reason": "LLM thinks general",
        }
        result = _sanitize_decision(decision, state)
        assert result["intent"] == "complaint"


# ===========================================================================
# Test 5: Grounding Guard doesn't re-request order number
# ===========================================================================

class TestGroundingGuardOrderHandling:
    """Grounding validation should not re-request order_id when already provided."""

    def test_rewrite_logistics_with_order_id_not_found(self):
        from app.services.grounding_validation_service import _rewrite_fallback_reply
        state = {
            "intent": "logistics_eta",
            "slots": {"order_id": "999999999999", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "999999999999",
            "matched_product_name": "",
        }
        reply = _rewrite_fallback_reply(state, "no_evidence_clarification")
        assert "订单号" not in reply or "收到" in reply, (
            f"Should not ask for order_id when already provided. Reply: {reply}"
        )
        assert "核对" in reply or "查询到" in reply, (
            f"Should say order not found. Reply: {reply}"
        )

    def test_rewrite_logistics_without_order_id(self):
        from app.services.grounding_validation_service import _rewrite_fallback_reply
        state = {
            "intent": "logistics_eta",
            "slots": {"order_id": "", "tracking_no": "", "identifier_type": "none"},
            "matched_product_name": "",
        }
        reply = _rewrite_fallback_reply(state, "no_evidence_clarification")
        assert "订单号" in reply or "物流单号" in reply, (
            f"Should ask for order_id when not provided. Reply: {reply}"
        )

    def test_rewrite_product_fact_with_order_id(self):
        from app.services.grounding_validation_service import _rewrite_fallback_reply
        state = {
            "intent": "product_question",
            "slots": {"order_id": "202501010001", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010001",
            "matched_product_name": "",
        }
        reply = _rewrite_fallback_reply(state, "product_fact_answer")
        assert "提供" not in reply or "订单" not in reply or "截图" not in reply or "收到" in reply, (
            f"Should not ask for order when already provided. Reply: {reply}"
        )


class TestLogisticsLookupFailureSemantics:
    """Tool availability failures must not be presented as customer ID errors."""

    @staticmethod
    def _state(reason: str) -> dict:
        return {
            "customer_message": "我的订单什么时候到",
            "normalized_message": "我的订单什么时候到",
            "intent": "logistics_eta",
            "slots": {
                "order_id": "",
                "tracking_no": "",
                "platform_trade_id": "masked-platform-order",
                "possible_numeric_id": "masked-platform-order",
                "identifier_type": "platform_trade_id",
            },
            "tool_results": {
                "jst_lookup_outbound_tool": {
                    "found": False,
                    "safe_fallback_reason": reason,
                },
            },
            "trace_steps": [],
        }

    def test_provider_not_configured_does_not_blame_order_number(self):
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply

        result = generate_logistics_reply(self._state("jst_not_configured"))
        reply = result["suggested_reply"]

        assert "订单号已经收到" in reply
        assert "不用重复提供" in reply
        assert "是否正确" not in reply
        assert result["requires_human_review"] is True
        assert result["review_reason"] == "order_lookup_service_unavailable"

    def test_real_not_found_can_still_request_order_screenshot(self):
        from app.agent.nodes.generate_logistics_reply import generate_logistics_reply

        result = generate_logistics_reply(self._state("not_found"))
        reply = result["suggested_reply"]

        assert "订单截图" in reply
        assert "是否正确" in reply
        assert result.get("review_reason") != "order_lookup_service_unavailable"

    def test_rewrite_aftersales_with_order_id(self):
        from app.services.grounding_validation_service import _rewrite_fallback_reply
        state = {
            "intent": "aftersales",
            "slots": {"order_id": "202501010002", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010002",
            "matched_product_name": "",
        }
        reply = _rewrite_fallback_reply(state, "no_evidence_clarification")
        # Should NOT ask for order_id again
        assert "提供一下订单号" not in reply


# ===========================================================================
# Test 6 & 7: Conversation isolation
# ===========================================================================

class TestConversationIsolation:
    """Different conversation_id should have isolated context."""

    def test_different_conversation_ids_isolated(self):
        from app.agent.context.conversation_context import load_conversation_context
        state_a = {"conversation_id": "conv_a_isolation_test", "trace_steps": []}
        result_a = load_conversation_context(state_a)

        state_b = {"conversation_id": "conv_b_isolation_test", "trace_steps": []}
        result_b = load_conversation_context(state_b)

        assert result_a["conversation_id"] == "conv_a_isolation_test"
        assert result_b["conversation_id"] == "conv_b_isolation_test"

    def test_new_session_no_inherit(self):
        """Fresh conversation_id should not inherit old context."""
        from app.agent.context.conversation_context import load_conversation_context
        new_id = "brand_new_conv_test_001"
        state = {"conversation_id": new_id, "trace_steps": []}
        result = load_conversation_context(state)
        ctx = result.get("conversation_context", {})
        # Should not have any previous intent/slots
        assert ctx.get("current_intent", "") == ""
        assert ctx.get("active_issue", "") == ""

    def test_context_resets_on_explicit_user_correction(self):
        from app.agent.context.conversation_context import apply_conversation_context

        result = apply_conversation_context({
            "normalized_message": "\u4e0d\u662f\u8fd9\u4e2a\uff0c\u6211\u95ee\u53e6\u4e00\u4e2a",
            "intent": "product_question",
            "slots": {},
            "conversation_context": {
                "active_issue": "installation",
                "confirmed_product": "\u65e7\u5546\u54c1",
                "last_requested_slots": ["sku"],
                "unresolved_slots": ["sku"],
                "order_product_identity": {"sku_id": "OLD001"},
            },
            "trace_steps": [],
        })

        assert result["context_reset_reason"] == "explicit_user_correction"
        ctx = result["conversation_context"]
        assert ctx["active_issue"] == ""
        assert ctx["confirmed_product"] == ""
        assert ctx["order_product_identity"] == {}

    def test_context_resets_when_product_entity_changes(self):
        from app.agent.context.conversation_context import apply_conversation_context

        result = apply_conversation_context({
            "normalized_message": "\u8fd9\u4e2a\u5c3a\u5bf8\u591a\u5927",
            "intent": "product_question",
            "slots": {"sku_code": "NEW001B01S01", "product_name": "\u65b0\u5546\u54c1"},
            "conversation_context": {
                "active_issue": "installation",
                "confirmed_product": "\u65e7\u5546\u54c1",
                "order_product_identity": {"sku_id": "OLD001B01S01", "matched_product_name": "\u65e7\u5546\u54c1"},
            },
            "trace_steps": [],
        })

        assert result["context_reset_reason"] == "product_entity_changed"
        assert result["conversation_context_summary"]["confirmed_product"] == ""


# ===========================================================================
# Test 8: Order status routing (pending, shipped, signed)
# ===========================================================================

class TestOrderStatusRouting:
    """detect_intent should correctly route different order-status scenarios."""

    def test_shipped_order_routes_logistics(self):
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "我的快递到哪了",
            "customer_message": "我的快递到哪了",
            "order_id": "202501010001",
            "slots": {"order_id": "202501010001", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] in ("logistics_eta", "logistics_trace")

    def test_pending_order_routes_logistics(self):
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "什么时候发货",
            "customer_message": "什么时候发货",
            "order_id": "202501010003",
            "slots": {"order_id": "202501010003", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] in ("logistics_eta", "logistics_trace")

    def test_signed_not_received_routes_delivery(self):
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "显示签收了但是我没收到",
            "customer_message": "显示签收了但是我没收到",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "delivery_not_received"


# ===========================================================================
# Test 9: Aftersales not routed as product or logistics
# ===========================================================================

class TestAftersalesRouting:
    """Return/refund should not be routed to product_question or logistics."""

    def test_refund_not_product(self):
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "这个订单我要退货退款",
            "customer_message": "这个订单我要退货退款",
            "order_id": "202501010002",
            "slots": {"order_id": "202501010002", "identifier_type": "internal_order_id"},
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "aftersales"
        assert result["intent"] not in ("product_question", "logistics_eta")

    def test_refund_via_router_validation(self):
        from app.agent.nodes.router_validation import router_validation
        state = {
            "normalized_message": "这个订单我要退货退款",
            "customer_message": "这个订单我要退货退款",
            "slots": {"order_id": "202501010002", "tracking_no": "", "identifier_type": "internal_order_id"},
            "order_id": "202501010002",
            "conversation_context": {},
            "router_decision": {"intent": "product_question"},
            "intent": "general",
            "router_source": "llm",
            "router_reason": "",
            "selected_tool": "none",
            "trace_steps": [],
        }
        result = router_validation(state)
        assert result["intent"] == "aftersales"


# ===========================================================================
# Test 10: Grounding doesn't flag general logistics explanations
# ===========================================================================

class TestGroundingGeneralLogistics:
    """General logistics explanation phrases should not be flagged as specific status claims."""

    def test_general_logistics_not_flagged(self):
        from app.services.grounding_validation_service import validate_reply_grounding
        # A reply with general explanation but no specific status claims
        state = {
            "intent": "logistics_eta",
            "suggested_reply": "亲，物流时效受天气、路况等多种因素影响，我无法对具体到货时间给出准确判断。具体送达时间以实际更新为准。",
            "evidence": {},
            "slots": {"order_id": "202501010001"},
            "trace_steps": [],
        }
        result = validate_reply_grounding(state)
        # General explanation should NOT have logistics_fact unsupported claims
        logistics_unsupported = [
            c for c in result["unsupported_claims"]
            if c.get("fact_type") == "logistics_fact"
        ]
        assert len(logistics_unsupported) == 0, (
            f"General logistics explanation should not be flagged. Unsupported: {logistics_unsupported}"
        )

    def test_specific_status_claim_flagged(self):
        from app.services.grounding_validation_service import validate_reply_grounding
        state = {
            "intent": "logistics_eta",
            "suggested_reply": "您的订单已发货，正在运输中，预计明天到达。",
            "evidence": {},
            "slots": {},
            "trace_steps": [],
        }
        result = validate_reply_grounding(state)
        assert not result["passed"], "Specific logistics claims without evidence should be flagged"


# ===========================================================================
# Test 11: Complaint and high-risk flow preserved
# ===========================================================================

class TestComplaintFlowPreserved:
    """Complaint and high-risk routing should not regress."""

    def test_complaint_detected(self):
        from app.agent.nodes.detect_intent import detect_intent
        state = {
            "normalized_message": "再不处理我就去12315投诉",
            "customer_message": "再不处理我就去12315投诉",
            "trace_steps": [],
        }
        result = detect_intent(state)
        assert result["intent"] == "complaint"

    def test_complaint_strategy_routed(self):
        from app.agent.nodes.response_strategy_router import response_strategy_router
        state = {
            "intent": "complaint",
            "risk_level": "high",
            "slots": {},
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        assert result["response_strategy"] == "high_risk"


# ===========================================================================
# Test 12: Order number extraction from message body
# ===========================================================================

class TestOrderNumberExtraction:
    """Order number in message body should be extracted even if API order_id is empty."""

    def test_order_number_in_message_body(self):
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "订单 202501010001 快递到哪了",
            "order_id": "",
            "trace_steps": [],
        }
        result = slot_extract(state)
        slots = result["slots"]
        assert slots["order_id"] == "202501010001" or slots["identifier_type"] != "none", (
            f"Should extract order_id from message body. slots: {slots}"
        )

    def test_order_semantic_extraction(self):
        from app.agent.nodes.slot_extract import slot_extract
        state = {
            "customer_message": "我的订单号是202501010001，查一下物流",
            "order_id": "",
            "trace_steps": [],
        }
        result = slot_extract(state)
        assert result["slots"]["order_id"] == "202501010001"


# ===========================================================================
# Test: JST error classification
# ===========================================================================

class TestJSTErrorClassification:
    """JST error code 110 should be classified as auth error."""

    def test_error_110_is_auth(self):
        from app.integrations.jst.errors import JSTAPIError
        err = JSTAPIError(code=110, message="access token expired", endpoint="test")
        assert err.is_auth_error is True
        assert "access_token" in err.classify() or "认证" in err.classify()

    def test_error_0_is_not_auth(self):
        from app.integrations.jst.errors import JSTAPIError
        err = JSTAPIError(code=50, message="some error", endpoint="test")
        assert err.is_auth_error is False
