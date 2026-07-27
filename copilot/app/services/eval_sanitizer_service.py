"""Sanitizers for real conversation evaluation data."""

import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LONG_ID_RE = re.compile(r"(?<!\d)\d{12,}(?!\d)")
_SECRET_RE = re.compile(
    r"(?i)\b(token|secret|api[_-]?key|access[_-]?key|signature|password)\b\s*[:=]\s*[^\s&]+"
)
_SIGNED_URL_KEYS_RE = re.compile(
    r"(?i)(Expires|Signature|OSSAccessKeyId|security-token|x-oss-signature|X-Amz-Signature|token|secret|key)="
)
_DATA_URL_RE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]{80,}")
_BARE_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{160,}={0,2}(?![A-Za-z0-9+/=])")
_ACCOUNT_RE = re.compile(r"(?i)(微信|VX|wx|旺旺|钉钉|DingTalk|买家昵称|昵称|账号)[:：]?\s*[\w@\-.一-龥]{2,32}")
_ADDRESS_RE = re.compile(
    r"(?:"
    r"(?:收货地址|地址|寄往|送到|收件人住址)\s*[:：]?\s*"
    r"(?=[^，。；;\n]{0,64}(?:省|市|区|县|镇|乡|街道|路|街|巷|小区|村|号楼|单元|室|\d))"
    r"[^，。；;\n]{4,80}"
    r"|(?:[\u4e00-\u9fff]{2,}(?:省|自治区))?"
    r"[\u4e00-\u9fff]{2,}(?:市|自治州)"
    r"[\u4e00-\u9fff]{2,}(?:区|县|市)"
    r"[\u4e00-\u9fff0-9A-Za-z#\-]{2,}"
    r"|[\u4e00-\u9fff]{2,}(?:路|街|巷|道|小区|村)\s*"
    r"\d+(?:号|弄|栋|幢|号楼|单元|室)?"
    r")"
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_SAFE_INTERNAL_ID_KEYS = {
    "task_uid",
    "draft_uid",
    "queue_uid",
    "run_uid",
    "case_uid",
    "turn_uid",
    "conversation_uid",
}
_PRODUCT_TITLE_KEYS = {
    "product_name",
    "product_title",
    "platform_product_title",
    "display_product_name",
    "front_product_title",
    "sidecar_front_title",
    "item_title",
    "order_product_title",
    "matched_product_name",
    "internal_product_name",
}
_PRODUCT_TITLE_CANDIDATE_TYPES = (
    "product_candidate",
    "product_title",
    "order_product_title",
    "product_name",
)


def stable_hash(value: str, length: int = 16) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def hash_sensitive(value: str) -> str:
    return stable_hash(value, 16)


def _redact_long_id(match: re.Match) -> str:
    raw = match.group(0)
    return f"[LONG_ID_REDACTED:{stable_hash(raw, 10)}]"


def _sanitize_url(raw_url: str) -> str:
    try:
        parts = urlsplit(raw_url)
    except Exception:
        return "[URL_REDACTED]"
    query = parts.query or ""
    host = parts.netloc
    if query and _SIGNED_URL_KEYS_RE.search(query):
        digest = stable_hash(raw_url, 12)
        return urlunsplit((parts.scheme, host, f"/[SIGNED_URL_REDACTED:{digest}]", "", ""))
    if len(raw_url) > 300:
        digest = stable_hash(raw_url, 12)
        return urlunsplit((parts.scheme, host, f"/[LONG_URL_REDACTED:{digest}]", "", ""))
    return raw_url


def sanitize_text(text: str | None) -> str:
    """Remove customer PII/secrets while keeping enough semantics for QA replay."""
    value = str(text or "")
    if not value:
        return ""
    value = _DATA_URL_RE.sub("[BASE64_IMAGE_REDACTED]", value)
    value = _BARE_BASE64_RE.sub("[BASE64_REDACTED]", value)
    value = _URL_RE.sub(lambda m: _sanitize_url(m.group(0)), value)
    value = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[SECRET_REDACTED]", value)
    value = _PHONE_RE.sub("[PHONE_REDACTED]", value)
    value = _ADDRESS_RE.sub("[ADDRESS_REDACTED]", value)
    value = _ACCOUNT_RE.sub("[ACCOUNT_REDACTED]", value)
    value = _LONG_ID_RE.sub(_redact_long_id, value)
    return value.strip()


def sanitize_product_title(text: str | None) -> str:
    """Sanitize a product title without treating room/category words as address PII.

    QianNiu product titles often contain words like 客厅、卧室、桌面、儿童. The generic
    sanitizer applies concrete-address detection to buyer messages, while product
    titles do not carry buyer address authority. Product-title fields still go
    through URL, secret, phone/account, and long-id redaction.
    """
    value = str(text or "")
    if not value:
        return ""
    value = _DATA_URL_RE.sub("[BASE64_IMAGE_REDACTED]", value)
    value = _BARE_BASE64_RE.sub("[BASE64_REDACTED]", value)
    value = _URL_RE.sub(lambda m: _sanitize_url(m.group(0)), value)
    value = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[SECRET_REDACTED]", value)
    value = _PHONE_RE.sub("[PHONE_REDACTED]", value)
    value = _ACCOUNT_RE.sub("[ACCOUNT_REDACTED]", value)
    value = _LONG_ID_RE.sub(_redact_long_id, value)
    return value.strip()


def sanitize_obj(value):
    """Recursively sanitize text fields in JSON-like objects."""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_obj(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_obj(item) for item in value]
    if isinstance(value, dict):
        sanitized = {}
        candidate_type = str(value.get("type") or value.get("identifier_type") or "").lower()
        title_like_candidate = (
            any(token in candidate_type for token in _PRODUCT_TITLE_CANDIDATE_TYPES)
            and "product_id" not in candidate_type
            and "item_id" not in candidate_type
        )
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_text.lower() in {"token", "secret", "password", "api_key", "apikey", "signature"}:
                sanitized[key_text] = "[SECRET_REDACTED]"
            elif key_lower in _SAFE_INTERNAL_ID_KEYS:
                sanitized[key_text] = str(item or "")
            elif (
                key_lower in _PRODUCT_TITLE_KEYS
                or (title_like_candidate and key_lower in {"value", "title", "name"})
            ):
                sanitized[key_text] = sanitize_product_title(item)
            else:
                sanitized[key_text] = sanitize_obj(item)
        return sanitized
    return value


def json_sanitized(value) -> str:
    return json.dumps(sanitize_obj(value), ensure_ascii=False)
