"""Sanitization helpers for eval cases, traces, and APIs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "access_token", "token", "secret", "app_secret",
    "phone", "mobile", "address", "id_card", "identity_no", "receiver", "recipient",
    "customer_message", "message_raw", "raw_message", "prompt", "messages", "full_context",
    "base64", "image_b64", "data_url", "image_url", "url", "asset_url", "media_url",
    "oss_url", "signed_url", "video_url", "contact", "wechat", "weixin", "wangwang", "dingtalk",
}

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_CARD_RE = re.compile(r"(?<![0-9Xx])\d{17}[0-9Xx](?![0-9Xx])")
LONG_NUMBER_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")
BASE64_RE = re.compile(r"data:[^,\s]+,[-A-Za-z0-9+/=]+")
URL_RE = re.compile(r"(https?|oss)://[^\s\"'<>]+", re.IGNORECASE)
TOKEN_RE = re.compile(r"(?i)(api[_-]?key|token|secret|signature|access_token)=((?!\[redacted\])[^&\s]+)")
ADDRESS_RE = re.compile(r"[\u4e00-\u9fff]{2,}(省|市|区|县|镇|乡|路|街|小区|楼|单元|室|号)")
CONTACT_RE = re.compile(r"(?i)(微信|vx|weixin|旺旺|钉钉|dingtalk)[:：]?\s*[A-Za-z0-9_\-]{4,}")


def sanitize_text(value: Any, *, max_len: int = 500) -> str:
    text = str(value or "")
    text = BASE64_RE.sub("[base64_redacted]", text)
    text = URL_RE.sub(_sanitize_url_match, text)
    text = TOKEN_RE.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    text = PHONE_RE.sub("[phone_redacted]", text)
    text = ID_CARD_RE.sub("[id_card_redacted]", text)
    text = LONG_NUMBER_RE.sub(_mask_long_number, text)
    text = ADDRESS_RE.sub("[address_redacted]", text)
    text = CONTACT_RE.sub("[contact_redacted]", text)
    if len(text) > max_len:
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{text[:max_len]}...#{digest}"
    return text


def sanitize_payload(value: Any, *, max_depth: int = 4, max_items: int = 20) -> Any:
    if max_depth <= 0:
        return _shape(value)
    if isinstance(value, dict):
        safe = {}
        for key, item in list(value.items())[:max_items]:
            key_text = str(key)
            if _is_sensitive_key(key_text):
                continue
            safe[key_text] = sanitize_payload(item, max_depth=max_depth - 1, max_items=max_items)
        return safe
    if isinstance(value, (list, tuple, set)):
        result = [sanitize_payload(item, max_depth=max_depth - 1, max_items=max_items) for item in list(value)[:max_items]]
        if len(value) > max_items:
            result.append(f"{len(value) - max_items} more")
        return result
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(str(value))


def sanitize_json(value: Any) -> str:
    return json.dumps(sanitize_payload(value), ensure_ascii=False, sort_keys=True)


def sanitize_case_payload(data: dict[str, Any]) -> dict[str, Any]:
    data = data or {}
    return {
        "customer_message_sanitized": sanitize_text(
            data.get("customer_message")
            or data.get("customer_message_sanitized")
            or data.get("message")
            or "",
            max_len=500,
        ),
        "context_sanitized": sanitize_payload(
            data.get("context")
            or data.get("context_sanitized")
            or data.get("copilot_context")
            or {},
        ),
        "metadata": sanitize_payload(data.get("metadata") or {}),
        "product_scope": sanitize_payload(data.get("product_scope") or []),
    }


def has_sensitive_leak(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return bool(
        PHONE_RE.search(text)
        or ID_CARD_RE.search(text)
        or BASE64_RE.search(text)
        or TOKEN_RE.search(text)
        or re.search(r"https?://[^\s]+(signature|token|access_key)", text, re.IGNORECASE)
    )


def _sanitize_url_match(match: re.Match) -> str:
    raw = match.group(0)
    parsed = urlparse(raw)
    return f"url_host:{parsed.netloc or parsed.path.split('/')[0]}"


def _mask_long_number(match: re.Match) -> str:
    value = match.group(0)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"***{value[-4:]}#{digest}"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(
        marker in lowered
        for marker in ("token", "secret", "authorization", "base64", "phone", "address", "url")
    )


def _shape(value: Any) -> str:
    if isinstance(value, dict):
        return f"dict({len(value)})"
    if isinstance(value, (list, tuple, set)):
        return f"list({len(value)})"
    return sanitize_text(value, max_len=80)
