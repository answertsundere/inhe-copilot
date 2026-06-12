"""
Test real_data_sanitizer — 真实聊天数据脱敏测试。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.golden_set.real_data_sanitizer import (
    sanitize_text,
    sanitize_message,
    sanitize_order_id,
    sanitize_tracking_no,
    sanitize_session,
    _sanitize_url,
    check_sensitive_data,
)


# ---------------------------------------------------------------------------
# sanitize_text
# ---------------------------------------------------------------------------

class TestSanitizeText:
    """文本级脱敏测试。"""

    def test_phone_number_replaced(self):
        """手机号 13812345678 替换为 <PHONE>。"""
        text = "我的手机号是13812345678，请联系我"
        result = sanitize_text(text)
        assert "13812345678" not in result
        assert "<PHONE>" in result

    def test_multiple_phone_numbers(self):
        """多条手机号全部替换。"""
        text = "电话1: 13900001111 电话2: 15822223333"
        result = sanitize_text(text)
        assert "13900001111" not in result
        assert "15822223333" not in result
        assert result.count("<PHONE>") == 2

    def test_id_card_replaced(self):
        """身份证号替换为 <ID_CARD>。"""
        text = "身份证号：110101199001011234"
        result = sanitize_text(text)
        assert "110101199001011234" not in result
        assert "<ID_CARD>" in result

    def test_id_card_with_x(self):
        """身份证末位 X 也替换。"""
        text = "证件号码33010220051231234X"
        result = sanitize_text(text)
        assert "33010220051231234X" not in result
        assert "<ID_CARD>" in result

    def test_cookie_replaced(self):
        """Cookie 替换。"""
        text = 'cookie: abcdefgh12345678'
        result = sanitize_text(text)
        assert "abcdefgh12345678" not in result
        assert "<COOKIE>" in result

    def test_authorization_replaced(self):
        """authorization token 替换。"""
        text = "authorization: Bearer sk-abc123xyz"
        result = sanitize_text(text)
        assert "Bearer sk-abc123xyz" not in result
        assert "<REDACTED_CREDENTIAL>" in result

    def test_access_token_replaced(self):
        """access_token 替换。"""
        text = "access_token=secretvalue1234"
        result = sanitize_text(text)
        assert "secretvalue1234" not in result
        assert "<REDACTED_CREDENTIAL>" in result

    def test_api_key_replaced(self):
        """api_key 替换。"""
        text = "api_key=myapikey1234"
        result = sanitize_text(text)
        assert "myapikey1234" not in result
        assert "<REDACTED_CREDENTIAL>" in result

    def test_address_replaced(self):
        """收货地址替换。"""
        text = "收货地址：浙江省杭州市西湖区文三路123号"
        result = sanitize_text(text)
        assert "浙江省杭州市" not in result
        assert "<ADDRESS>" in result

    def test_recipient_replaced(self):
        """收件人姓名替换。"""
        text = "收件人：张三丰"
        result = sanitize_text(text)
        assert "张三丰" not in result
        assert "<RECIPIENT>" in result

    def test_no_false_positive_on_short_text(self):
        """不含敏感信息的文本不做替换。"""
        text = "这个商品多少钱？"
        assert sanitize_text(text) == text

    def test_clean_text_unchanged(self):
        """普通文本不被篡改。"""
        text = "您好，请问这个产品有什么优惠活动？"
        assert sanitize_text(text) == text


# ---------------------------------------------------------------------------
# sanitize_message — buyer/agent name mapping
# ---------------------------------------------------------------------------

class TestSanitizeMessage:
    """消息级脱敏测试。"""

    def test_buyer_name_mapped(self):
        """买家名称映射为 <BUYER_001>。"""
        msg = {
            "content": "你好",
            "sender_name": "张小明",
            "sender_type": "customer",
        }
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert result["sender_name"] == "<BUYER_001>"

    def test_agent_name_mapped(self):
        """客服名称映射为 <AGENT_001>。"""
        msg = {
            "content": "您好",
            "sender_name": "客服小美",
            "sender_type": "agent",
        }
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert result["sender_name"] == "<AGENT_001>"

    def test_same_buyer_name_consistent(self):
        """相同买家名称始终映射到同一占位符。"""
        msg1 = {"content": "你好", "sender_name": "李大鹏", "sender_type": "customer"}
        msg2 = {"content": "还在吗", "sender_name": "李大鹏", "sender_type": "customer"}

        name_map = {}
        counter = {"buyer": 0, "agent": 0}

        r1 = sanitize_message(msg1, name_map, counter)
        r2 = sanitize_message(msg2, name_map, counter)

        assert r1["sender_name"] == r2["sender_name"]
        assert r1["sender_name"] == "<BUYER_001>"

    def test_different_buyers_sequential(self):
        """不同买家名称递增编号。"""
        msg_a = {"content": "hi", "sender_name": "买家甲", "sender_type": "customer"}
        msg_b = {"content": "hello", "sender_name": "买家乙", "sender_type": "customer"}

        name_map = {}
        counter = {"buyer": 0, "agent": 0}

        ra = sanitize_message(msg_a, name_map, counter)
        rb = sanitize_message(msg_b, name_map, counter)

        assert ra["sender_name"] == "<BUYER_001>"
        assert rb["sender_name"] == "<BUYER_002>"

    def test_different_agents_sequential(self):
        """不同客服名称递增编号。"""
        msg_a = {"content": "hi", "sender_name": "客服A", "sender_type": "agent"}
        msg_b = {"content": "hello", "sender_name": "客服B", "sender_type": "agent"}

        name_map = {}
        counter = {"buyer": 0, "agent": 0}

        ra = sanitize_message(msg_a, name_map, counter)
        rb = sanitize_message(msg_b, name_map, counter)

        assert ra["sender_name"] == "<AGENT_001>"
        assert rb["sender_name"] == "<AGENT_002>"

    def test_content_is_sanitized(self):
        """消息内容也被脱敏。"""
        msg = {
            "content": "电话13800001111",
            "sender_name": "张三",
            "sender_type": "customer",
        }
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert "13800001111" not in result["content"]
        assert "<PHONE>" in result["content"]

    def test_system_sender_name_unchanged(self):
        """system 类型的 sender_name 不做映射。"""
        msg = {
            "content": "系统消息",
            "sender_name": "system_bot",
            "sender_type": "system",
        }
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert result["sender_name"] == "system_bot"

    def test_preserves_extra_fields(self):
        """保留消息中的额外字段。"""
        msg = {
            "content": "hello",
            "sender_name": "test",
            "sender_type": "customer",
            "sent_at": "2026-01-01T00:00:00",
            "custom_field": 42,
        }
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert result["sent_at"] == "2026-01-01T00:00:00"
        assert result["custom_field"] == 42

    def test_empty_content_handled(self):
        """空 content 不报错。"""
        msg = {"content": "", "sender_name": "买家", "sender_type": "customer"}
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert result["content"] == ""

    def test_none_content_handled(self):
        """None content 不报错。"""
        msg = {"content": None, "sender_name": "买家", "sender_type": "customer"}
        name_map = {}
        counter = {"buyer": 0, "agent": 0}
        result = sanitize_message(msg, name_map, counter)
        assert result["content"] == ""


# ---------------------------------------------------------------------------
# sanitize_order_id — stable order ID mapping
# ---------------------------------------------------------------------------

class TestSanitizeOrderId:
    """订单号脱敏测试。"""

    def test_first_order_gets_001(self):
        """第一个订单号映射为 <ORDER_ID_001>。"""
        result = sanitize_order_id("2026060100001", {})
        assert result == "<ORDER_ID_001>"

    def test_stable_mapping(self):
        """相同订单号始终映射到同一占位符。"""
        order_map = {}
        r1 = sanitize_order_id("ORD-ABC123", order_map)
        r2 = sanitize_order_id("ORD-ABC123", order_map)
        assert r1 == r2
        assert r1 == "<ORDER_ID_001>"

    def test_different_orders_sequential(self):
        """不同订单号递增编号。"""
        order_map = {}
        r1 = sanitize_order_id("ORD-001", order_map)
        r2 = sanitize_order_id("ORD-002", order_map)
        assert r1 == "<ORDER_ID_001>"
        assert r2 == "<ORDER_ID_002>"

    def test_empty_order_id(self):
        """空订单号返回空字符串。"""
        assert sanitize_order_id("", {}) == ""

    def test_mixed_lookup_and_insert(self):
        """混合查找和插入。"""
        order_map = {}
        r1 = sanitize_order_id("A", order_map)
        r2 = sanitize_order_id("B", order_map)
        r3 = sanitize_order_id("A", order_map)
        assert r1 == "<ORDER_ID_001>"
        assert r2 == "<ORDER_ID_002>"
        assert r3 == "<ORDER_ID_001>"


# ---------------------------------------------------------------------------
# sanitize_tracking_no — stable tracking number mapping
# ---------------------------------------------------------------------------

class TestSanitizeTrackingNo:
    """快递单号脱敏测试。"""

    def test_first_tracking_gets_001(self):
        """第一个快递单号映射为 <TRACKING_NO_001>。"""
        result = sanitize_tracking_no("SF1234567890", {})
        assert result == "<TRACKING_NO_001>"

    def test_stable_mapping(self):
        """相同快递单号始终映射到同一占位符。"""
        tracking_map = {}
        r1 = sanitize_tracking_no("YT9876543210", tracking_map)
        r2 = sanitize_tracking_no("YT9876543210", tracking_map)
        assert r1 == r2
        assert r1 == "<TRACKING_NO_001>"

    def test_different_trackings_sequential(self):
        """不同快递单号递增编号。"""
        tracking_map = {}
        r1 = sanitize_tracking_no("T1", tracking_map)
        r2 = sanitize_tracking_no("T2", tracking_map)
        assert r1 == "<TRACKING_NO_001>"
        assert r2 == "<TRACKING_NO_002>"

    def test_empty_tracking(self):
        """空快递单号返回空字符串。"""
        assert sanitize_tracking_no("", {}) == ""


# ---------------------------------------------------------------------------
# _sanitize_url — URL sensitive param stripping
# ---------------------------------------------------------------------------

class TestSanitizeUrl:
    """URL 敏感参数剥离测试。"""

    def test_strip_token_param(self):
        """移除 token 参数。"""
        url = "https://example.com/api?token=secret123&id=5"
        result = _sanitize_url(url)
        assert "secret123" not in result
        assert "<REDACTED>" in result
        assert "id=5" in result

    def test_strip_session_param(self):
        """移除 session 参数。"""
        url = "https://example.com/page?session=abc456&name=test"
        result = _sanitize_url(url)
        assert "abc456" not in result
        assert "<REDACTED>" in result

    def test_strip_key_param(self):
        """移除 key 参数。"""
        url = "https://example.com/api?key=mykey123"
        result = _sanitize_url(url)
        assert "mykey123" not in result

    def test_strip_secret_param(self):
        """移除 secret 参数。"""
        url = "https://example.com/api?secret=topsecret&data=ok"
        result = _sanitize_url(url)
        assert "topsecret" not in result
        assert "data=ok" in result

    def test_strip_auth_param(self):
        """移除 auth 参数。"""
        url = "https://example.com/api?auth=bearertoken&foo=bar"
        result = _sanitize_url(url)
        assert "bearertoken" not in result

    def test_strip_cookie_param(self):
        """移除 cookie 参数。"""
        url = "https://example.com/api?cookie=sessioncookie"
        result = _sanitize_url(url)
        assert "sessioncookie" not in result

    def test_clean_url_unchanged(self):
        """不含敏感参数的 URL 保持不变。"""
        url = "https://example.com/item?id=12345&category=books"
        assert _sanitize_url(url) == url

    def test_empty_url_returns_empty(self):
        """空 URL 返回空字符串。"""
        assert _sanitize_url("") == ""

    def test_multiple_sensitive_params(self):
        """多个敏感参数全部移除。"""
        url = "https://example.com/api?token=abc&key=def&data=ok"
        result = _sanitize_url(url)
        assert "abc" not in result
        assert "def" not in result
        assert "data=ok" in result

    def test_case_insensitive_param_strip(self):
        """参数名大小写不敏感。"""
        url = "https://example.com/api?Token=secret123"
        result = _sanitize_url(url)
        assert "secret123" not in result


# ---------------------------------------------------------------------------
# sanitize_session — full session sanitization
# ---------------------------------------------------------------------------

class TestSanitizeSession:
    """完整会话脱敏测试。"""

    def _make_session(self, **overrides):
        """构建测试用会话。"""
        session = {
            "messages": [
                {
                    "content": "你好",
                    "sender_name": "买家张",
                    "sender_type": "customer",
                    "sent_at": "2026-06-01T10:00:00",
                },
                {
                    "content": "您好，请问有什么可以帮您？",
                    "sender_name": "客服小丽",
                    "sender_type": "agent",
                    "sent_at": "2026-06-01T10:00:05",
                },
            ],
            "buyer_name": "买家张",
            "primary_agent": "客服小丽",
            "order_id": "2026060100001",
            "product_url": "https://example.com/item?id=123",
            "source_file": "D:/secret/path/data.xlsx",
        }
        session.update(overrides)
        return session

    def test_buyer_name_in_session_masked(self):
        """会话中的 buyer_name 被映射。"""
        session = self._make_session()
        result = sanitize_session(session)
        assert result["buyer_name"] == "<BUYER_001>"

    def test_primary_agent_masked(self):
        """会话中的 primary_agent 被映射。"""
        session = self._make_session()
        result = sanitize_session(session)
        assert result["primary_agent"] == "<AGENT_001>"

    def test_order_id_in_session_masked(self):
        """会话中的 order_id 被映射。"""
        session = self._make_session()
        result = sanitize_session(session)
        assert result["order_id"] == "<ORDER_ID_001>"

    def test_source_file_redacted(self):
        """源文件路径被替换。"""
        session = self._make_session()
        result = sanitize_session(session)
        assert result["source_file"] == "<REDACTED_PATH>"

    def test_product_url_with_sensitive_param(self):
        """product_url 中的敏感参数被移除。"""
        session = self._make_session(
            product_url="https://example.com/item?token=abc&id=123"
        )
        result = sanitize_session(session)
        assert "abc" not in result["product_url"]
        assert "<REDACTED>" in result["product_url"]

    def test_messages_sanitized(self):
        """消息中的内容被脱敏。"""
        session = self._make_session()
        session["messages"][0]["content"] = "电话13800001111"
        result = sanitize_session(session)
        assert "13800001111" not in result["messages"][0]["content"]
        assert "<PHONE>" in result["messages"][0]["content"]

    def test_empty_product_url(self):
        """空 product_url 处理。"""
        session = self._make_session(product_url="")
        result = sanitize_session(session)
        assert result["product_url"] == ""

    def test_unknown_buyer_name_fallback(self):
        """buyer_name 不在消息映射中时回退。"""
        session = self._make_session(buyer_name="未知买家")
        result = sanitize_session(session)
        # "未知买家" doesn't appear as a sender_name in messages, so fallback
        assert result["buyer_name"] == "<BUYER_MASKED>"

    def test_unknown_agent_name_fallback(self):
        """primary_agent 不在消息映射中时回退。"""
        session = self._make_session(primary_agent="未知客服")
        result = sanitize_session(session)
        assert result["primary_agent"] == "<AGENT_MASKED>"

    def test_no_messages(self):
        """空消息列表不报错。"""
        session = self._make_session()
        session["messages"] = []
        result = sanitize_session(session)
        assert result["messages"] == []


# ---------------------------------------------------------------------------
# check_sensitive_data — residual sensitive data detection
# ---------------------------------------------------------------------------

class TestCheckSensitiveData:
    """残留敏感数据检测测试。"""

    def test_catches_phone_numbers(self):
        """检测到残留手机号。"""
        data = {"content": "call me at 13900001111"}
        findings = check_sensitive_data(data)
        assert any("phone_numbers_remaining" in f for f in findings)

    def test_catches_id_cards(self):
        """检测到残留身份证号。"""
        data = {"content": "证件号110101199001011234"}
        findings = check_sensitive_data(data)
        assert any("id_cards_remaining" in f for f in findings)

    def test_catches_cookies(self):
        """检测到残留 Cookie。"""
        data = {"header": "cookie: abcdefgh12345678"}
        findings = check_sensitive_data(data)
        assert any("cookie_remaining" in f for f in findings)

    def test_catches_auth_tokens(self):
        """检测到残留 auth token。"""
        data = {"header": "authorization: Bearer sk-xyz1234567"}
        findings = check_sensitive_data(data)
        assert any("auth_remaining" in f for f in findings)

    def test_clean_data_no_findings(self):
        """干净数据不报告残留。"""
        data = {"content": "你好，请问这个商品多少钱？"}
        findings = check_sensitive_data(data)
        assert findings == []

    def test_sanitized_data_passes_check(self):
        """已脱敏数据通过检查。"""
        raw = "电话13812345678，身份证110101199001011234"
        sanitized = sanitize_text(raw)
        findings = check_sensitive_data({"content": sanitized})
        assert findings == []

    def test_returns_list(self):
        """返回列表类型。"""
        findings = check_sensitive_data({"content": "hello"})
        assert isinstance(findings, list)

    def test_multiple_violations(self):
        """多条违规同时检出。"""
        data = {"content": "13900001111 and 110101199001011234"}
        findings = check_sensitive_data(data)
        assert len(findings) >= 2


# ---------------------------------------------------------------------------
# Consistency & stability tests
# ---------------------------------------------------------------------------

class TestStabilityAndConsistency:
    """稳定性和一致性测试。"""

    def test_same_name_always_same_placeholder(self):
        """相同名称在不同调用中映射到相同占位符。"""
        name_map = {}
        counter = {"buyer": 0, "agent": 0}

        msg1 = {"content": "hi", "sender_name": "王五", "sender_type": "customer"}
        sanitize_message(msg1, name_map, counter)

        # Second call with same name_map and counter
        msg2 = {"content": "hello", "sender_name": "王五", "sender_type": "customer"}
        r2 = sanitize_message(msg2, name_map, counter)

        assert r2["sender_name"] == "<BUYER_001>"

    def test_order_id_stability_across_multiple_lookups(self):
        """订单号多次查找稳定。"""
        order_map = {}
        results = [
            sanitize_order_id("ORD-XYZ", order_map)
            for _ in range(10)
        ]
        assert all(r == "<ORDER_ID_001>" for r in results)

    def test_tracking_no_stability_across_multiple_lookups(self):
        """快递单号多次查找稳定。"""
        tracking_map = {}
        results = [
            sanitize_tracking_no("SF-999", tracking_map)
            for _ in range(10)
        ]
        assert all(r == "<TRACKING_NO_001>" for r in results)

    def test_full_session_deterministic(self):
        """完整会话脱敏是确定性的。"""
        session = {
            "messages": [
                {"content": "你好13800001111", "sender_name": "甲", "sender_type": "customer"},
                {"content": "好的", "sender_name": "客服A", "sender_type": "agent"},
            ],
            "buyer_name": "甲",
            "primary_agent": "客服A",
            "order_id": "OID-1",
            "product_url": "",
            "source_file": "test.xlsx",
        }
        r1 = sanitize_session(session)
        r2 = sanitize_session(session)
        # Both produce same buyer/agent/order mapping
        assert r1["buyer_name"] == r2["buyer_name"]
        assert r1["primary_agent"] == r2["primary_agent"]
        assert r1["order_id"] == r2["order_id"]
