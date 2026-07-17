"""Privacy boundary for read-only real-accuracy evaluation artifacts.

This module deliberately has no production Agent imports.  It converts raw
reviewed-chat fields into a bounded, structured representation and then scans
the *output* independently.  A build may only claim privacy success after the
scanner reports no violations.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from app.services.eval_sanitizer_service import sanitize_text


_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_LONG_ID_RE = re.compile(r"(?<!\d)\d{10,}(?!\d)")
_SECRET_RE = re.compile(r"(?i)\b(?:token|secret|api[_-]?key|authorization|cookie|password)\b")
_HTML_RE = re.compile(r"<[^>]+>|&(?:#\d+|#x[\da-f]+|[a-z]+);", re.I)
_DATA_URL_RE = re.compile(r"data:[^\s]+", re.I)
_ACCOUNT_RE = re.compile(r"(?i)(?:微信|vx|wx|旺旺|钉钉|dingtalk|账号|昵称)\s*[:：]\s*[^\s，。；;]{2,}")
_ADDRESS_RE = re.compile(r"[\u4e00-\u9fff]{2,}(?:省|市|区|县|镇|乡|街道|路|巷|小区|村|号楼|单元|室)[\u4e00-\u9fff0-9A-Za-z#\-]{2,}")
_SPEAKER_PREFIX_RE = re.compile(r"^\s*(买家|客户|顾客|用户|客服|商家|系统|订单系统|机器人)\s*[:：]\s*", re.I)
_UNCONTROLLED_SPEAKER_HEADER_RE = re.compile(r"^\s*[^\s:：]{2,32}\s*[:：]\s*")
_BLOCK_TAGS = {"p", "div", "li", "tr", "section", "article", "blockquote"}
_IMAGE_TAGS = {"img", "video", "audio"}


def _actor_uid(secret: str, role: str, source_hint: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"actor:{role}:{source_hint}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"actor_{digest[:16]}"


def _link_token(raw_url: str) -> str:
    path = urlsplit(raw_url).path.lower()
    if any(token in path for token in ("order", "trade", "logistics")):
        return "[ORDER_LINK]"
    if any(token in path for token in ("image", "img", "media", "upload", "attachment")):
        return "[MEDIA_LINK]"
    if any(token in path for token in ("product", "item", "sku", "detail")):
        return "[PRODUCT_LINK]"
    return "[EXTERNAL_LINK]"


def _safe_text(raw: str) -> str:
    value = html.unescape(raw or "")
    value = _URL_RE.sub(lambda match: _link_token(match.group(0)), value)
    value = sanitize_text(value)
    value = _EMAIL_RE.sub("[EMAIL_REDACTED]", value)
    value = _LANDLINE_RE.sub("[PHONE_REDACTED]", value)
    value = _ACCOUNT_RE.sub("[ACCOUNT_REDACTED]", value)
    value = _ADDRESS_RE.sub("[ADDRESS_REDACTED]", value)
    value = _LONG_ID_RE.sub("[IDENTIFIER_REDACTED]", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:1800]


def sanitize_gold_text(raw: Any) -> str:
    """Sanitise standalone Gold fields without retaining URL or identity text."""
    return _safe_text(str(raw or ""))


def _role_from_text(value: str) -> tuple[str, str]:
    match = _SPEAKER_PREFIX_RE.match(value)
    if not match:
        unknown = _UNCONTROLLED_SPEAKER_HEADER_RE.match(value)
        return "SYSTEM", value[unknown.end():].strip() if unknown else value
    label = match.group(1)
    role = "BUYER" if label in {"买家", "客户", "顾客", "用户"} else "AGENT" if label in {"客服", "商家"} else "SYSTEM"
    return role, value[match.end():].strip()


class _ConversationHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[tuple[str, str]] = []
        self._parts: list[str] = []
        self._current_type = "text"
        self._ignored_depth = 0

    def _flush(self) -> None:
        text = "".join(self._parts).strip()
        if text:
            self.fragments.append((self._current_type, text))
        self._parts = []
        self._current_type = "text"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"style", "script", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if lowered in _BLOCK_TAGS or lowered == "br":
            self._flush()
        if lowered in _IMAGE_TAGS:
            self._flush()
            self.fragments.append(("image", "[IMAGE]"))
        elif lowered == "a":
            href = attr_map.get("href", "")
            if href:
                self._parts.append(_link_token(href))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"style", "script", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if tag.lower() in _BLOCK_TAGS or tag.lower() == "br":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def parse_conversation_context(raw_context: Any, *, hmac_key: str, source_provenance: str = "reviewed_training_sample") -> dict[str, Any]:
    """Return only structured, sanitised turns; uncertainty is fail-closed."""
    raw = str(raw_context or "")
    parser = _ConversationHtmlParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return {"turns": [], "privacy_review_required": True, "reason_codes": ["conversation_parse_failed"]}

    turns: list[dict[str, Any]] = []
    for message_type, raw_text in parser.fragments:
        text = _safe_text(raw_text)
        if not text:
            continue
        role, text = _role_from_text(text)
        if not text:
            continue
        if message_type == "text" and text.startswith("[PRODUCT_LINK]"):
            message_type = "product_card"
        elif message_type == "text" and text.startswith("[ORDER_LINK]"):
            message_type = "order_card"
        elif message_type == "text" and text.startswith("[EXTERNAL_LINK]"):
            message_type = "link"
        turns.append({
            "turn_index": len(turns) + 1,
            "speaker_role": role,
            "speaker_uid": _actor_uid(hmac_key, role, source_provenance),
            "message_type": message_type,
            "text": text,
            "source_provenance": source_provenance,
        })

    result = {"turns": turns, "privacy_review_required": False, "reason_codes": []}
    findings = scan_privacy_output({"conversation": result})
    if findings:
        result["privacy_review_required"] = True
        result["reason_codes"] = sorted({item["reason_code"] for item in findings})
    return result


def scan_privacy_output(value: Any) -> list[dict[str, Any]]:
    """Return reason/count only; never expose matching source text."""
    serialized = str(value if isinstance(value, str) else _stable_json(value))
    checks = {
        "phone_number_detected": _PHONE_RE,
        "landline_detected": _LANDLINE_RE,
        "email_detected": _EMAIL_RE,
        "address_detected": _ADDRESS_RE,
        "long_identifier_detected": _LONG_ID_RE,
        "url_detected": _URL_RE,
        "credential_marker_detected": _SECRET_RE,
        "html_or_entity_detected": _HTML_RE,
        "data_url_detected": _DATA_URL_RE,
        "account_or_nickname_detected": _ACCOUNT_RE,
    }
    findings = [
        {"reason_code": reason, "count": len(pattern.findall(serialized))}
        for reason, pattern in checks.items()
        if pattern.search(serialized)
    ]
    if re.search(r"(?:买家|客户|顾客|用户|客服|商家)\s*(?:→|->)", serialized, re.I):
        findings.append({"reason_code": "speaker_identity_header_detected", "count": 1})
    return findings


def _stable_json(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
