"""Privacy boundary for read-only real-accuracy evaluation artifacts.

This module deliberately has no production Agent imports.  It converts raw
reviewed-chat fields into a bounded, structured representation and then scans
the *output* independently.  A build may only claim privacy success after the
scanner reports no violations.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import re
from html.parser import HTMLParser
from typing import Any, Iterable
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
_VOID_TAGS = _IMAGE_TAGS | {"br", "hr", "input", "meta", "link", "source"}
_MESSAGE_CONTAINER_CLASS = "imui-msg"
_BODY_CLASS_TOKENS = frozenset({"msg-body-text", "msg-body-html", "msg-content-nobody"})
_DIRECTION_ROLES = {
    "imui-msg-l": "BUYER",
    "imui-msg-r": "AGENT",
    "imui-msg-system": "SYSTEM",
}
_ALLOWED_ROLES = frozenset({"BUYER", "AGENT", "SYSTEM"})
_MAX_TURNS_PER_CASE = 500
_CONTROLLED_SCAN_FIELDS = frozenset({
    "case_uid", "turn_uid", "target_turn_uids", "speaker_uid", "pseudonymous_id", "sidecar_identity",
    "content_sha256", "dataset_hash", "reviewer_actor_hash", "manifest",
})
_ACTOR_UID_RE = re.compile(r"^actor_[A-Z2-7]{20}$")
_TURN_UID_RE = re.compile(r"^turn_[A-Z2-7]{20}$")
_PSEUDONYM_RE = re.compile(r"^(?:training_sample|product|sku|order)_[A-Z2-7]{20}$")


def _actor_uid(secret: str, role: str, source_hint: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"actor:{role}:{source_hint}".encode("utf-8"), hashlib.sha256).digest()
    return f"actor_{base64.b32encode(digest).decode('ascii').rstrip('=')[:20]}"


def _turn_uid(conversation_uid: str, index: int, turn: dict[str, Any]) -> str:
    payload = "\x1f".join((
        conversation_uid,
        str(index),
        str(turn.get("speaker_role") or "UNRESOLVED"),
        str(turn.get("message_type") or "text"),
        str(turn.get("text") or ""),
    ))
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return f"turn_{base64.b32encode(digest).decode('ascii').rstrip('=')[:20]}"


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


def _role_from_text(value: str) -> tuple[str | None, str, str]:
    match = _SPEAKER_PREFIX_RE.match(value)
    if not match:
        unknown = _UNCONTROLLED_SPEAKER_HEADER_RE.match(value)
        return None, value[unknown.end():].strip() if unknown else value, "role_unresolved"
    label = match.group(1)
    role = "BUYER" if label in {"买家", "客户", "顾客", "用户"} else "AGENT" if label in {"客服", "商家"} else "SYSTEM"
    return role, value[match.end():].strip(), "text_prefix"


class _ConversationHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.messages: list[dict[str, Any]] = []
        self.fragments: list[str] = []
        self._fragment_parts: list[str] = []
        self._ignored_depth = 0
        self._stack: list[tuple[str, bool]] = []
        self._active: dict[str, Any] | None = None
        self._body_depth = 0

    def _flush_fragment(self) -> None:
        text = "".join(self._fragment_parts).strip()
        if text:
            self.fragments.append(text)
        self._fragment_parts = []

    def _finish_active(self) -> None:
        if not self._active:
            return
        text = "".join(self._active["parts"]).strip()
        if text:
            self.messages.append({
                "role": self._active["role"],
                "role_resolution": "dom_direction",
                "message_type": self._active["message_type"],
                "text": text,
            })
        self._active = None
        self._body_depth = 0

    @staticmethod
    def _direction_role(classes: set[str]) -> str | None:
        for class_name, role in _DIRECTION_ROLES.items():
            if class_name in classes:
                return role
        return None

    def _append_token(self, token: str, message_type: str) -> None:
        if not self._active:
            return
        if token not in self._active["tokens"]:
            self._active["tokens"].add(token)
            self._active["parts"].append(f" {token} ")
        if self._active["message_type"] == "text":
            self._active["message_type"] = message_type

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"style", "script", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        classes = set(attr_map.get("class", "").split())
        is_message = _MESSAGE_CONTAINER_CLASS in classes
        if is_message:
            self._finish_active()
            self._active = {
                "role": self._direction_role(classes),
                "parts": [],
                "tokens": set(),
                "message_type": "text",
                "root_depth": len(self._stack),
            }
        is_body = bool(self._active and classes.intersection(_BODY_CLASS_TOKENS))
        if lowered not in _VOID_TAGS:
            self._stack.append((lowered, is_body))
        if is_body:
            self._body_depth += 1
        if self._active:
            if lowered == "br" and self._body_depth:
                self._active["parts"].append(" ")
            elif lowered in _IMAGE_TAGS and (self._body_depth or classes.intersection({"imui-msg-img", "j_imimage", "item-pic"})):
                self._append_token("[IMAGE]", "image")
            elif lowered == "a" and self._body_depth and attr_map.get("href"):
                self._append_token(_link_token(attr_map["href"]), "link")
            elif attr_map.get("data-targettype"):
                target = attr_map["data-targettype"].lower()
                if any(value in target for value in ("order", "trade", "logistics")):
                    self._append_token("[ORDER_CARD]", "order_card")
                elif any(value in target for value in ("product", "item", "sku")):
                    self._append_token("[PRODUCT_CARD]", "product_card")
        else:
            if lowered in _BLOCK_TAGS or lowered == "br":
                self._flush_fragment()
            if lowered in _IMAGE_TAGS:
                self._flush_fragment()
                self.fragments.append("[IMAGE]")
            elif lowered == "a" and attr_map.get("href"):
                self._fragment_parts.append(_link_token(attr_map["href"]))

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"style", "script", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if not self._stack:
            return
        stack_index = len(self._stack) - 1
        opened_tag, is_body = self._stack.pop()
        if is_body:
            self._body_depth = max(0, self._body_depth - 1)
            if self._active:
                self._active["parts"].append(" ")
        if self._active and stack_index == self._active["root_depth"] and opened_tag == lowered:
            self._finish_active()
        elif not self._active and lowered in _BLOCK_TAGS:
            self._flush_fragment()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._active and self._body_depth:
            self._active["parts"].append(data)
        elif not self._active:
            self._fragment_parts.append(data)

    def close(self) -> None:
        super().close()
        self._finish_active()
        self._flush_fragment()


def _append_turn(turns: list[dict[str, Any]], turn: dict[str, Any]) -> None:
    turns.append(turn)


def _conversation_turn(
    *, raw_text: str, role: str | None, role_resolution: str, message_type: str,
    hmac_key: str, source_provenance: str,
) -> dict[str, Any] | None:
    text = _safe_text(raw_text)
    if not text:
        return None
    if role is None:
        role, text, role_resolution = _role_from_text(text)
    if role not in _ALLOWED_ROLES:
        role = None
        role_resolution = "role_unresolved"
    if message_type == "text":
        if text == "[IMAGE]":
            message_type = "image"
        elif text.startswith("[PRODUCT_LINK]"):
            message_type = "product_card"
        elif text.startswith("[ORDER_LINK]"):
            message_type = "order_card"
        elif text.startswith("[EXTERNAL_LINK]"):
            message_type = "link"
    return {
        "speaker_role": role,
        "speaker_uid": _actor_uid(hmac_key, role, source_provenance) if role else None,
        "role_resolution": role_resolution,
        "message_type": message_type,
        "text": text,
        "source_provenance": source_provenance,
    }


def parse_conversation_context(
    raw_context: Any,
    *,
    hmac_key: str,
    source_provenance: str = "reviewed_training_sample",
    conversation_uid: str = "",
) -> dict[str, Any]:
    """Return only structured, sanitised turns; uncertainty is fail-closed."""
    raw = str(raw_context or "")
    parser = _ConversationHtmlParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return {"turns": [], "privacy_review_required": True, "reason_codes": ["conversation_parse_failed"]}

    source_messages: Iterable[dict[str, Any]]
    if parser.messages:
        source_messages = parser.messages
    else:
        source_messages = ({"role": None, "role_resolution": "role_unresolved", "message_type": "text", "text": text} for text in parser.fragments)
    turns: list[dict[str, Any]] = []
    for message in source_messages:
        turn = _conversation_turn(
            raw_text=message["text"], role=message.get("role"), role_resolution=message.get("role_resolution", "role_unresolved"),
            message_type=message.get("message_type", "text"), hmac_key=hmac_key, source_provenance=source_provenance,
        )
        if turn:
            _append_turn(turns, turn)
    conversation_truncated = len(turns) > _MAX_TURNS_PER_CASE
    if conversation_truncated:
        turns = turns[:_MAX_TURNS_PER_CASE]
    uid_scope = conversation_uid or hashlib.sha256(
        f"{source_provenance}\x1f{raw}".encode("utf-8")
    ).hexdigest()
    for index, turn in enumerate(turns, start=1):
        turn["turn_index"] = index
        turn["turn_uid"] = _turn_uid(uid_scope, index, turn)
    role_counts = {role: sum(1 for turn in turns if turn.get("speaker_role") == role) for role in sorted(_ALLOWED_ROLES)}
    role_unresolved_count = sum(1 for turn in turns if turn.get("role_resolution") == "role_unresolved")
    result = {
        "turns": turns,
        "role_counts": role_counts,
        "role_unresolved_count": role_unresolved_count,
        "conversation_truncated": conversation_truncated,
        "privacy_review_required": False,
        "reason_codes": [],
    }
    findings = scan_privacy_output({"conversation": result})
    if findings:
        result["privacy_review_required"] = True
        result["reason_codes"] = sorted({item["reason_code"] for item in findings})
    return result


def _content_scan_projection(value: Any) -> Any:
    if isinstance(value, list):
        return [_content_scan_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _content_scan_projection(item)
        for key, item in value.items()
        if key not in _CONTROLLED_SCAN_FIELDS
    }


def validate_controlled_identifiers(value: Any) -> list[dict[str, Any]]:
    """Validate generated pseudonyms separately from customer-content scanning."""
    invalid_actor_count = 0
    invalid_turn_count = 0
    invalid_pseudonym_count = 0

    def visit(item: Any) -> None:
        nonlocal invalid_actor_count, invalid_turn_count, invalid_pseudonym_count
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        speaker_uid = item.get("speaker_uid")
        if speaker_uid is not None and not _ACTOR_UID_RE.fullmatch(str(speaker_uid)):
            invalid_actor_count += 1
        turn_uid = item.get("turn_uid")
        if turn_uid is not None and not _TURN_UID_RE.fullmatch(str(turn_uid)):
            invalid_turn_count += 1
        target_turn_uids = item.get("target_turn_uids")
        if target_turn_uids is not None:
            if not isinstance(target_turn_uids, list):
                invalid_turn_count += 1
            else:
                invalid_turn_count += sum(
                    1 for identifier in target_turn_uids
                    if not _TURN_UID_RE.fullmatch(str(identifier))
                )
        for key in ("case_uid", "pseudonymous_id"):
            identifier = item.get(key)
            if identifier is not None and not _PSEUDONYM_RE.fullmatch(str(identifier)):
                invalid_pseudonym_count += 1
        sidecar = item.get("sidecar_identity")
        if isinstance(sidecar, dict):
            for namespace in ("product", "sku", "order"):
                identifier = sidecar.get(namespace)
                if identifier is not None and not _PSEUDONYM_RE.fullmatch(str(identifier)):
                    invalid_pseudonym_count += 1
        for child in item.values():
            visit(child)

    visit(value)
    findings: list[dict[str, Any]] = []
    if invalid_actor_count:
        findings.append({"reason_code": "controlled_actor_identifier_invalid", "count": invalid_actor_count})
    if invalid_turn_count:
        findings.append({"reason_code": "controlled_turn_identifier_invalid", "count": invalid_turn_count})
    if invalid_pseudonym_count:
        findings.append({"reason_code": "controlled_pseudonym_invalid", "count": invalid_pseudonym_count})
    return findings


def scan_privacy_output(value: Any) -> list[dict[str, Any]]:
    """Return reason/count only; never expose matching source text."""
    projected = _content_scan_projection(value)
    serialized = str(projected if isinstance(projected, str) else _stable_json(projected))
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
