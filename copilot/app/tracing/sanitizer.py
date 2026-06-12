"""
Sanitizer — 脱敏 Trace 数据中的敏感信息。
"""

from __future__ import annotations

import re

_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "api_secret", "app_secret", "secret",
    "authorization", "cookie", "token", "access_token", "refresh_token",
    "password", "passwd", "credential",
})

_PHONE_RE = re.compile(r'1[3-9]\d{9}')
_ID_CARD_RE = re.compile(r'[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]')


def sanitize_dict(data: dict, max_str_len: int = 500) -> dict:
    """递归脱敏字典中的敏感字段和长文本。"""
    if not isinstance(data, dict):
        return data
    out = {}
    for k, v in data.items():
        key_lower = k.lower()
        # Drop sensitive keys entirely
        if key_lower in _SENSITIVE_KEYS:
            out[k] = "***REDACTED***"
            continue
        if isinstance(v, dict):
            out[k] = sanitize_dict(v, max_str_len)
        elif isinstance(v, str):
            out[k] = sanitize_text(v, max_str_len)
        elif isinstance(v, list):
            out[k] = [sanitize_dict(i, max_str_len) if isinstance(i, dict) else (sanitize_text(i, max_str_len) if isinstance(i, str) else i) for i in v[:20]]
            if len(v) > 20:
                out[k] = out[k][:20]  # truncate long lists
        else:
            out[k] = v
    return out


def sanitize_text(text: str, max_len: int = 500) -> str:
    """脱敏文本中的手机号和身份证号，截断长文本。"""
    if not isinstance(text, str):
        return str(text)
    # Phone numbers
    text = _PHONE_RE.sub(lambda m: m.group()[:3] + "****" + m.group()[-4:], text)
    # ID cards
    text = _ID_CARD_RE.sub(lambda m: m.group()[:6] + "********" + m.group()[-4:], text)
    # Truncate
    if len(text) > max_len:
        text = text[:max_len] + "...[truncated]"
    return text


def sanitize_prompt(text: str, max_len: int = 500) -> str:
    """脱敏 prompt 文本用于保存。"""
    return sanitize_text(text, max_len)
