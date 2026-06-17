"""
Real Data Sanitizer — 真实聊天数据脱敏。

必须在写入 Copilot 项目前完成脱敏。
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

# ---------- 脱敏模式 ----------

_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ID_CARD_RE = re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]")
_COOKIE_RE = re.compile(r"cookie[\s:=]+[^\s;]{8,}", re.IGNORECASE)
_AUTH_RE = re.compile(r"(?:authorization|access_token|api[_-]?key|app[_-]?secret)[\s:=]+[^\s;]{4,}", re.IGNORECASE)
_ADDRESS_RE = re.compile(r"(?:收货地址|地址|收件地址)[:：]\s*.{5,50}")
_RECIPIENT_RE = re.compile(r"(?:收件人|收货人)[:：]\s*[一-鿿]{2,4}")


def sanitize_message(msg: dict, name_map: dict, counter: dict) -> dict:
    """脱敏单条消息，返回脱敏后的副本。"""
    content = msg.get("content", "") or ""
    sender_name = msg.get("sender_name", "") or ""
    sender_type = msg.get("sender_type", "")

    # Map sender names to stable placeholders
    if sender_type == "customer":
        if sender_name not in name_map:
            counter["buyer"] = counter.get("buyer", 0) + 1
            name_map[sender_name] = f"<BUYER_{counter['buyer']:03d}>"
        sender_name = name_map[sender_name]
    elif sender_type == "agent":
        if sender_name not in name_map:
            counter["agent"] = counter.get("agent", 0) + 1
            name_map[sender_name] = f"<AGENT_{counter['agent']:03d}>"
        sender_name = name_map[sender_name]

    # Sanitize content
    content = sanitize_text(content)

    return {
        **msg,
        "sender_name": sender_name,
        "content": content,
    }


def sanitize_text(text: str) -> str:
    """脱敏文本内容。"""
    # ID cards first (before phone numbers, since ID cards contain digit sequences)
    text = _ID_CARD_RE.sub("<ID_CARD>", text)
    # Phone numbers
    text = _PHONE_RE.sub("<PHONE>", text)
    # Cookies, tokens, keys
    text = _COOKIE_RE.sub("<COOKIE>", text)
    text = _AUTH_RE.sub("<REDACTED_CREDENTIAL>", text)
    # Addresses
    text = _ADDRESS_RE.sub("收货地址: <ADDRESS>", text)
    # Recipient names
    text = _RECIPIENT_RE.sub("收件人: <RECIPIENT>", text)
    return text


def sanitize_order_id(order_id: str, order_map: dict) -> str:
    """脱敏订单号，使用稳定映射。"""
    if not order_id:
        return ""
    if order_id in order_map:
        return order_map[order_id]
    idx = len(order_map) + 1
    masked = f"<ORDER_ID_{idx:03d}>"
    order_map[order_id] = masked
    return masked


def sanitize_tracking_no(tracking_no: str, tracking_map: dict) -> str:
    """脱敏快递单号，使用稳定映射。"""
    if not tracking_no:
        return ""
    if tracking_no in tracking_map:
        return tracking_map[tracking_no]
    idx = len(tracking_map) + 1
    masked = f"<TRACKING_NO_{idx:03d}>"
    tracking_map[tracking_no] = masked
    return masked


def sanitize_session(session: dict) -> dict:
    """脱敏整个会话。"""
    name_map = {}
    counter = {"buyer": 0, "agent": 0}
    order_map = {}
    tracking_map = {}

    sanitized_messages = []
    for msg in session.get("messages", []):
        sm = sanitize_message(msg, name_map, counter)
        sanitized_messages.append(sm)

    return {
        **session,
        "messages": sanitized_messages,
        "buyer_name": name_map.get(session.get("buyer_name", ""), "<BUYER_MASKED>"),
        "primary_agent": name_map.get(session.get("primary_agent", ""), "<AGENT_MASKED>"),
        "order_id": sanitize_order_id(session.get("order_id", ""), order_map),
        "product_url": _sanitize_url(session.get("product_url", "")),
        "source_file": "<REDACTED_PATH>",
    }


def _sanitize_url(url: str) -> str:
    """Remove sensitive params from URLs."""
    if not url:
        return ""
    # Remove common sensitive parameters
    url = re.sub(r"([?&])(?:token|session|key|secret|cookie|auth)=[^&]+", r"\1<REDACTED>", url, flags=re.IGNORECASE)
    return url


def check_sensitive_data(data: dict) -> list[str]:
    """检查脱敏后的数据是否还有残留敏感信息。"""
    findings = []
    text = str(data)

    phones = _PHONE_RE.findall(text)
    if phones:
        findings.append(f"phone_numbers_remaining: {len(phones)}")

    id_cards = _ID_CARD_RE.findall(text)
    if id_cards:
        findings.append(f"id_cards_remaining: {len(id_cards)}")

    for pattern_name, pattern in [("cookie", _COOKIE_RE), ("auth", _AUTH_RE)]:
        matches = pattern.findall(text)
        if matches:
            findings.append(f"{pattern_name}_remaining: {len(matches)}")

    return findings


# ---------- 乱码修复 ----------

# Common mojibake pattern: UTF-8 bytes interpreted as GBK/Latin-1
_Mojibake_PATTERNS = [
    # UTF-8 3-byte Chinese decoded as GBK → produces 2 GBK chars per Chinese char
    (re.compile(r"[\xc0-\xff][\x80-\xff]{1,2}"), "latin1_to_utf8"),
    # Replacement character sequences
    (re.compile(r"�{2,}"), "replacement_chars"),
]


def repair_mojibake(text: str) -> tuple[str, str, bool]:
    """Attempt to repair mojibake in text.

    Returns (repaired_text, strategy, repair_applied):
    - strategy: "none", "utf8_from_latin1", or "keep_original"
    - repair_applied: True if text was changed
    """
    if not text:
        return text, "none", False

    # Check 1: replacement characters (can't repair, keep original)
    if "�" in text and text.count("�") > len(text) * 0.1:
        return text, "keep_original", False

    # Check 2: try decoding as latin-1 → re-encoding as utf-8
    # This fixes the common case where UTF-8 was stored as Latin-1 bytes
    try:
        raw_bytes = text.encode("latin-1")
        repaired = raw_bytes.decode("utf-8")
        # Verify repair improved readability: more CJK chars = better
        cjk_original = sum(1 for c in text if "一" <= c <= "鿿")
        cjk_repaired = sum(1 for c in repaired if "一" <= c <= "鿿")
        if cjk_repaired > cjk_original and cjk_repaired > 0:
            return repaired, "utf8_from_latin1", True
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    # Check 3: try decoding as gbk → re-encoding as utf-8
    try:
        raw_bytes = text.encode("latin-1")
        repaired = raw_bytes.decode("gbk")
        cjk_original = sum(1 for c in text if "一" <= c <= "鿿")
        cjk_repaired = sum(1 for c in repaired if "一" <= c <= "鿿")
        if cjk_repaired > cjk_original and cjk_repaired > 0:
            return repaired, "utf8_from_gbk", True
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    # No repair needed or possible
    return text, "none", False
