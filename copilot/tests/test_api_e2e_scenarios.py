"""
API 端到端测试 - 通过 /api/analyze 验证业务场景
每个测试必须检查最终 JSON 的 intent、reply 和关键字段。
"""

import sys
import os
import time
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
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "test_fb_e2e.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "test_rq_e2e.jsonl")
    os.environ["COPILOT_LLM_API_KEY"] = ""

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    os.environ["COPILOT_LLM_API_KEY"] = saved_key
    return client


@pytest.fixture(scope="module")
def client():
    c = _get_flask_client()
    yield c


_counter = 0


def _analyze(client, message, order_id="", tracking_no="", conversation_id=None,
             platform_order_id="", platform_trade_id="", **kwargs):
    """Call /api/analyze and return JSON."""
    global _counter
    _counter += 1
    if conversation_id is None:
        conversation_id = f"e2e_{_counter}_{int(time.time()*1000)}"
    payload = {
        "message": message,
        "order_id": order_id,
        "tracking_no": tracking_no,
        "conversation_id": conversation_id,
    }
    if platform_order_id:
        payload["platform_order_id"] = platform_order_id
    if platform_trade_id:
        payload["platform_trade_id"] = platform_trade_id
    payload.update(kwargs)
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200, f"API error {resp.status_code}: {resp.data[:300]}"
    return resp.get_json()


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_ASK_IDENTIFIER_PATTERNS = (
    "请提供订单号", "提供一下订单号", "发一下订单号", "麻烦提供订单号",
    "补充订单号", "需要订单号", "请提供物流单号", "提供一下物流单号",
    "发一下物流单号", "补充物流单号", "麻烦您提供一下订单号",
    "麻烦您提供订单号", "麻烦您发一下订单号",
)


def assert_not_asking_for_identifier(reply: str, context: str = ""):
    """Assert the reply does not forcefully ask the user to provide an order/tracking identifier.

    Allowed: '已收到您的订单号', '请核对订单号', '订单号或物流单号' (as general info).
    Forbidden: '请提供订单号', '发一下订单号', etc. when an identifier was already given.
    """
    for pattern in _ASK_IDENTIFIER_PATTERNS:
        assert pattern not in reply, (
            f"{context}Reply should not forcefully ask for identifier. "
            f"Found '{pattern}' in: {reply[:200]}"
        )


def assert_no_overpromise(reply: str, context: str = ""):
    """Assert the reply does not contain overpromising language."""
    forbidden = ("负责到底", "一定赔偿", "保证退款", "肯定找回", "保证找回")
    for phrase in forbidden:
        assert phrase not in reply, (
            f"{context}Reply contains overpromising phrase '{phrase}': {reply[:200]}"
        )


def assert_not_asking_for_order_screenshot(reply: str, context: str = ""):
    assert "订单截图" not in reply, (
        f"{context}Reply should not ask for order screenshot when order/logistics context exists: {reply[:200]}"
    )


# ===========================================================================
# Scenario 1: Shipped order
# ===========================================================================

class TestShippedOrder:
    """已发货订单查物流"""

    def test_intent_is_logistics(self, client):
        data = _analyze(client, "我的快递到哪了", order_id="202501010001")
        assert data["intent"] in ("logistics_eta", "logistics_trace")

    def test_reply_mentions_shipped_or_tracking(self, client):
        data = _analyze(client, "我的快递到哪了", order_id="202501010001")
        reply = data["suggested_reply"]
        assert any(kw in reply for kw in ("已发货", "已发出", "已经发出", "中通", "ZT", "物流单号")), (
            f"Reply should mention shipping facts: {reply}"
        )

    def test_reply_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "我的快递到哪了", order_id="202501010001")
        assert_not_asking_for_identifier(data["suggested_reply"], "Shipped order: ")

    def test_full_product_name(self, client):
        """商品名称不应被截断为前三个字符"""
        data = _analyze(client, "我的快递到哪了", order_id="202501010001")
        reply = data["suggested_reply"]
        # Should NOT contain truncated name "北欧实" (first 3 chars of "北欧实木书桌")
        assert "北欧实）" not in reply, f"Product name truncated: {reply}"
        # Should contain either full name or no product name mention
        if "（" in reply and "）" in reply:
            # If product name is shown, it should be the full name
            assert "北欧实木书桌" in reply or "您购买的商品" in reply, (
                f"Expected full product name: {reply}"
            )


# ===========================================================================
# Scenario 2: Pending shipment
# ===========================================================================

class TestPendingShipment:
    """待发货订单"""

    def test_reply_says_pending(self, client):
        data = _analyze(client, "什么时候发货", order_id="202501010003")
        reply = data["suggested_reply"]
        assert any(kw in reply for kw in ("待发货", "尚未发货", "未发货", "尚未发出", "备货")), (
            f"Reply should mention pending shipment: {reply}"
        )

    def test_reply_does_not_say_shipped(self, client):
        data = _analyze(client, "什么时候发货", order_id="202501010003")
        reply = data["suggested_reply"]
        assert "已经发出" not in reply
        assert "已发货" not in reply

    def test_reply_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "什么时候发货", order_id="202501010003")
        assert_not_asking_for_identifier(data["suggested_reply"], "Pending shipment: ")

    def test_full_product_name(self, client):
        """商品名称不应被截断"""
        data = _analyze(client, "什么时候发货", order_id="202501010003")
        reply = data["suggested_reply"]
        # "多功能置物架" should not appear as "多功能）"
        assert "多功能）" not in reply, f"Product name truncated: {reply}"


# ===========================================================================
# Scenario 3: Signed but not received
# ===========================================================================

class TestSignedNotReceived:
    """签收未收到"""

    def test_intent_is_delivery_not_received(self, client):
        data = _analyze(client, "显示签收了，但是我没收到", order_id="202501010002")
        assert data["intent"] == "delivery_not_received"

    def test_reply_has_verification_guidance(self, client):
        data = _analyze(client, "显示签收了，但是我没收到", order_id="202501010002")
        reply = data["suggested_reply"]
        assert any(kw in reply for kw in ("家人", "门卫", "驿站", "快递柜", "快递员")), (
            f"Reply should guide verification: {reply}"
        )

    def test_reply_not_generic_shipped(self, client):
        data = _analyze(client, "显示签收了，但是我没收到", order_id="202501010002")
        reply = data["suggested_reply"]
        assert "已经发出" not in reply or "签收" in reply

    def test_reply_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "显示签收了，但是我没收到", order_id="202501010002")
        assert_not_asking_for_identifier(data["suggested_reply"], "DNR: ")

    def test_reply_does_not_ask_for_order_screenshot_when_order_known(self, client):
        data = _analyze(client, "显示签收了，但是我没收到", order_id="202501010002")
        assert_not_asking_for_order_screenshot(data["suggested_reply"], "DNR known order: ")

    def test_without_order_can_ask_for_identifier(self, client):
        data = _analyze(client, "显示签收了但是我没收到", conversation_id="dnr_no_order_v1")
        reply = data["suggested_reply"]
        assert "订单号" in reply or "物流单号" in reply

    def test_no_overpromise(self, client):
        """签收未收到回复不得包含过度承诺"""
        data = _analyze(client, "显示签收了，但是我没收到", order_id="202501010002")
        assert_no_overpromise(data["suggested_reply"], "DNR: ")


# ===========================================================================
# Scenario 4: Return/refund
# ===========================================================================

class TestReturnRefund:
    """退货退款"""

    def test_intent_is_aftersales(self, client):
        data = _analyze(client, "这个订单我要退货退款", order_id="202501010002")
        assert data["intent"] == "aftersales"

    def test_reply_is_aftersales_context(self, client):
        data = _analyze(client, "这个订单我要退货退款", order_id="202501010002")
        reply = data["suggested_reply"]
        assert "已发货" not in reply or "退款" in reply or "售后" in reply

    def test_reply_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "这个订单我要退货退款", order_id="202501010002")
        assert_not_asking_for_identifier(data["suggested_reply"], "Aftersales: ")

    def test_reply_does_not_promise_refund(self, client):
        data = _analyze(client, "这个订单我要退货退款", order_id="202501010002")
        reply = data["suggested_reply"]
        assert "已退款" not in reply
        assert "已经退" not in reply


class TestWrongItemReturn:
    """发错货 + 退货应先说明售后路径，再温和补充核对材料。"""

    @pytest.mark.parametrize("message", [
        "你们发错了，我想退，怎么弄？",
        "发错颜色了，我想退",
        "收到不是我拍的款，怎么退",
        "发错了能不能直接退",
    ])
    def test_wrong_item_return_flow_first(self, client, message):
        data = _analyze(client, message, order_id="202501010002")
        reply = data["suggested_reply"]

        assert data["intent"] == "aftersales"
        assert "退货" in reply or "售后" in reply
        assert "少件/缺配件" not in reply
        assert_not_asking_for_identifier(reply, "Wrong item return: ")
        assert_not_asking_for_order_screenshot(reply, "Wrong item return: ")
        if "拍" in reply:
            flow_pos = min(
                pos for pos in [reply.find("退货"), reply.find("售后")] if pos >= 0
            )
            assert flow_pos < reply.find("拍"), f"Should explain return/aftersales flow before asking photos: {reply}"


# ===========================================================================
# Scenario 5: Invalid order
# ===========================================================================

class TestInvalidOrder:
    """无效订单"""

    def test_reply_says_not_found(self, client):
        data = _analyze(client, "帮我查一下订单物流", order_id="999999999999")
        reply = data["suggested_reply"]
        assert any(kw in reply for kw in ("未查询到", "未查到", "没有查询到", "暂未", "没有在系统中查到", "核对")), (
            f"Reply should say order not found: {reply}"
        )

    def test_reply_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "帮我查一下订单物流", order_id="999999999999")
        assert_not_asking_for_identifier(data["suggested_reply"], "Invalid order: ")


# ===========================================================================
# Scenario 6: Order number in message body
# ===========================================================================

class TestOrderInMessageBody:
    """正文订单号"""

    def test_extracts_and_queries(self, client):
        data = _analyze(client, "订单 202501010001 快递到哪了", order_id="")
        reply = data["suggested_reply"]
        assert any(kw in reply for kw in ("已发货", "已发出", "已经发出", "中通", "ZT", "发货")), (
            f"Should query order from body text: {reply}"
        )

    def test_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "订单 202501010001 快递到哪了", order_id="")
        assert_not_asking_for_identifier(data["suggested_reply"], "Body order: ")


# ===========================================================================
# Scenario 7: Tracking number only
# ===========================================================================

class TestTrackingOnly:
    """只有物流单号 — 不得索要 order_id"""

    def test_does_not_ask_for_order_id(self, client):
        data = _analyze(client, "SF0221700958051 到哪了", tracking_no="SF0221700958051")
        assert_not_asking_for_identifier(data["suggested_reply"], "Tracking only: ")

    def test_mentions_tracking_no(self, client):
        data = _analyze(client, "SF0221700958051 到哪了", tracking_no="SF0221700958051")
        reply = data["suggested_reply"]
        # Should confirm receipt of the tracking number
        assert any(kw in reply for kw in (
            "物流单号", "SF0221700958051", "快递单号", "单号", "收到", "已收到",
            "暂未", "未查询到", "未查到", "核对",
        )), f"Should reference tracking number: {reply}"

    def test_intent_is_logistics(self, client):
        data = _analyze(client, "SF0221700958051 到哪了", tracking_no="SF0221700958051")
        assert data["intent"] in ("logistics_eta", "logistics_trace"), (
            f"Expected logistics intent, got: {data['intent']}"
        )

    def test_no_fabricated_logistics(self, client):
        """不得伪造物流状态"""
        data = _analyze(client, "SF0221700958051 到哪了", tracking_no="SF0221700958051")
        reply = data["suggested_reply"]
        assert "已发货" not in reply or "暂未" in reply or "未查询到" in reply
        assert "已经发出" not in reply or "暂未" in reply or "未查询到" in reply


# ===========================================================================
# Scenario 8: No identifier at all
# ===========================================================================

class TestNoIdentifier:
    """没有任何标识 — 允许要求订单号"""

    def test_can_ask_for_order(self, client):
        data = _analyze(client, "我快递大概几天会到")
        reply = data["suggested_reply"]
        assert "订单号" in reply or "物流单号" in reply, (
            f"Should ask for order when no identifier: {reply}"
        )


# ===========================================================================
# Scenario 9: Complaint / high risk
# ===========================================================================

class TestComplaintHighRisk:
    """投诉高风险"""

    def test_intent_is_complaint(self, client):
        data = _analyze(client, "再不处理我就去12315投诉")
        assert data["intent"] == "complaint"

    def test_requires_human_review(self, client):
        data = _analyze(client, "再不处理我就去12315投诉")
        assert data["requires_human_review"] is True


# ===========================================================================
# Scenario 10: Conversation isolation
# ===========================================================================

class TestConversationIsolation:
    """会话隔离"""

    def test_different_sessions_isolated(self, client):
        data_a = _analyze(client, "这个订单我要退货退款", order_id="202501010002",
                          conversation_id="iso_conv_a_v2")
        assert data_a["intent"] == "aftersales"

        data_b = _analyze(client, "我的快递到哪了", order_id="202501010001",
                          conversation_id="iso_conv_b_v2")
        assert data_b["intent"] != "aftersales"
        assert data_b["intent"] in ("logistics_eta", "logistics_trace")


# ===========================================================================
# Scenario 11: Invalid tracking_no
# ===========================================================================

class TestInvalidTrackingNo:
    """无效物流单号"""

    def test_says_not_found(self, client):
        data = _analyze(client, "快递到哪了", tracking_no="INVALID_TRACKING_999")
        reply = data["suggested_reply"]
        assert any(kw in reply for kw in ("暂未", "未查询到", "未查到", "没有查询到", "核对")), (
            f"Should say tracking not found: {reply}"
        )

    def test_does_not_ask_for_order_id(self, client):
        """已有 tracking_no 时不得索要 order_id"""
        data = _analyze(client, "快递到哪了", tracking_no="INVALID_TRACKING_999")
        assert_not_asking_for_identifier(data["suggested_reply"], "Invalid tracking: ")

    def test_no_fabricated_status(self, client):
        data = _analyze(client, "快递到哪了", tracking_no="INVALID_TRACKING_999")
        reply = data["suggested_reply"]
        # Should not claim the package was shipped/delivered
        assert "已经发出" not in reply or "暂未" in reply or "未查询到" in reply


# ===========================================================================
# Scenario 12: Only order_id (confirm no tracking_no requested)
# ===========================================================================

class TestOnlyOrderId:
    """只有 order_id — 不得索要 tracking_no"""

    def test_shipped_no_tracking_request(self, client):
        data = _analyze(client, "我的快递到哪了", order_id="202501010001")
        assert_not_asking_for_identifier(data["suggested_reply"], "Only order_id: ")

    def test_pending_no_tracking_request(self, client):
        data = _analyze(client, "什么时候发货", order_id="202501010003")
        assert_not_asking_for_identifier(data["suggested_reply"], "Only order_id pending: ")


# ===========================================================================
# Scenario 13: Only platform_order_id
# ===========================================================================

class TestPlatformOrderId:
    """只有 platform_order_id — 不得索要其他标识"""

    def test_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "快递到哪了", platform_order_id="202501010001")
        assert_not_asking_for_identifier(data["suggested_reply"], "Platform order id: ")

    def test_intent_is_logistics(self, client):
        data = _analyze(client, "快递到哪了", platform_order_id="202501010001")
        assert data["intent"] in ("logistics_eta", "logistics_trace", "logistics"), (
            f"Expected logistics intent, got: {data['intent']}"
        )


# ===========================================================================
# Scenario 14: Only platform_trade_id
# ===========================================================================

class TestPlatformTradeId:
    """只有 platform_trade_id — 不得索要其他标识"""

    def test_does_not_ask_for_identifier(self, client):
        data = _analyze(client, "快递到哪了", platform_trade_id="202501010001")
        assert_not_asking_for_identifier(data["suggested_reply"], "Platform trade id: ")
