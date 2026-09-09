from __future__ import annotations

import hashlib
import re
from typing import Any


CUSTOMER_PREFIXES = ("客户", "买家", "顾客", "用户", "访客", "buyer", "customer")
AGENT_PREFIXES = ("客服", "卖家", "商家", "客服助手", "机器人", "agent", "seller")
SYSTEM_PREFIXES = ("系统", "提示", "消息", "时间", "已读", "未读")
_ORDER_IDENTIFIER_TYPES = {
    "internal_order_id",
    "platform_trade_id",
    "platform_order_id",
    "tracking_no",
    "unknown_identifier",
}


def normalize_chat_line(line: str) -> str:
    text = (line or "").strip()
    text = re.sub(r"^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*", "", text)
    text = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?\s*", "", text)
    return text.strip()


def strip_speaker_prefix(line: str) -> tuple[str, str]:
    text = normalize_chat_line(line)
    match = re.match(r"^([^:：]{1,12})\s*[:：]\s*(.+)$", text)
    if not match:
        return "", text
    return match.group(1).strip(), match.group(2).strip()


def _has_any_prefix(speaker: str, prefixes: tuple[str, ...]) -> bool:
    normalized = speaker.strip().lower()
    return any(normalized.startswith(prefix.lower()) for prefix in prefixes)


def extract_latest_customer_message(chat_text: str) -> str:
    chat_text = (chat_text or "").replace("\\r\\n", "\n").replace("\\n", "\n")
    lines = [normalize_chat_line(line) for line in (chat_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    for line in reversed(lines):
        speaker, message = strip_speaker_prefix(line)
        if speaker and _has_any_prefix(speaker, CUSTOMER_PREFIXES):
            return message

    for line in reversed(lines):
        speaker, message = strip_speaker_prefix(line)
        if speaker and (
            _has_any_prefix(speaker, AGENT_PREFIXES)
            or _has_any_prefix(speaker, SYSTEM_PREFIXES)
        ):
            continue
        if message:
            return message
    return ""


def extract_identifiers(text: str) -> dict[str, Any]:
    from app.agent.nodes.slot_extract import slot_extract

    result = slot_extract({
        "customer_message": text or "",
        "normalized_message": text or "",
        "order_id": "",
        "tracking_no": "",
        "trace_steps": [],
    })
    slots = result.get("slots", {}) or {}
    return {
        "order_id": slots.get("order_id", ""),
        "platform_trade_id": slots.get("platform_trade_id", ""),
        "platform_order_id": slots.get("platform_order_id", ""),
        "tracking_no": slots.get("tracking_no", ""),
        "possible_numeric_id": slots.get("possible_numeric_id", ""),
        "identifier_type": slots.get("identifier_type", ""),
        "carrier": slots.get("carrier", ""),
        "product_name": slots.get("product_name", ""),
        "risk_keywords": slots.get("risk_keywords", []),
    }


def make_conversation_id(window_title: str, buyer_nick: str = "") -> str:
    raw = f"{window_title or ''}|{buyer_nick or ''}".strip("|") or "qianniu"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"qianniu-{digest}"


def _extract_candidates_from_payload(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "order_candidates": [],
        "tracking_candidates": [],
        "product_candidates": [],
    }

    for key in ("order_candidates", "tracking_candidates", "product_candidates"):
        candidates = payload.get(key)
        if isinstance(candidates, list):
            result[key] = [
                c for c in candidates
                if isinstance(c, dict) and c.get("value")
            ]

    return result


def normalize_explicit_order_reference(
    context: dict[str, Any],
    *,
    order_id: str,
) -> dict[str, Any]:
    """Attach server-normalized provenance to a structured order field.

    A sidebar order field is not customer-message text and cannot safely be
    classified by length alone. Preserve an adapter-provided canonical type
    when it is available; otherwise query the bounded JST identifier surface
    as an unknown reference.
    """
    normalized = dict(context or {})
    explicit_order_id = str(order_id or "").strip()
    if not explicit_order_id:
        return normalized

    identifier_type = str(
        normalized.get("order_identifier_type") or ""
    ).strip()
    if identifier_type not in _ORDER_IDENTIFIER_TYPES:
        for key, candidate_type in (
            ("platform_trade_id", "platform_trade_id"),
            ("platform_order_id", "platform_order_id"),
        ):
            if str(normalized.get(key) or "").strip() == explicit_order_id:
                identifier_type = candidate_type
                break
        else:
            identifier_type = "unknown_identifier"

    normalized["order_id"] = explicit_order_id
    normalized["order_identifier_type"] = identifier_type
    normalized["identifier_type"] = identifier_type
    normalized["order_reference_source"] = "explicit_request"
    return normalized


def best_candidate_value(candidates: list[dict[str, Any]]) -> str:
    usable = []
    for idx, cand in enumerate(candidates or []):
        if not isinstance(cand, dict):
            continue
        value = str(cand.get("value") or "").strip()
        if not value:
            continue
        if re.fullmatch(r"\(?\d+\)?", value):
            continue
        cand_type = str(cand.get("type") or "")
        if cand_type == "product_candidate":
            type_rank = 0
        elif cand_type in ("sku_id_candidate", "i_id_candidate"):
            type_rank = 1
        elif cand_type == "platform_product_id_candidate":
            type_rank = 3
        else:
            type_rank = 2
        usable.append((
            0 if cand.get("verified") else 1,
            type_rank,
            -float(cand.get("confidence") or 0),
            -min(len(value), 80),
            idx,
            value,
        ))
    if not usable:
        return ""
    usable.sort()
    return usable[0][-1]


def _normalize_conversation_history(
    payload: dict[str, Any],
    *,
    strict: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize sidecar turns without hiding malformed evaluation inputs."""
    from app.services.canonical_conversation_turn_service import normalize_conversation_turns

    return normalize_conversation_turns(
        payload.get("conversation_history") or payload.get("messages") or [],
        strict=strict,
        max_turns=8,
    )



def build_sidecar_context(payload: dict[str, Any], *, strict_conversation_history: bool = False) -> dict[str, Any]:
    chat_text = payload.get("chat_text", "") or payload.get("raw_text", "")
    customer_message = (payload.get("customer_message") or "").strip()
    if not customer_message:
        customer_message = extract_latest_customer_message(chat_text)

    identifiers = extract_identifiers(customer_message) if customer_message else {}
    window_title = payload.get("window_title", "") or ""
    buyer_nick = payload.get("buyer_nick", "") or ""
    shop_name = str(payload.get("shop_name") or payload.get("store_name") or "").strip()
    shop_id = str(payload.get("shop_id") or payload.get("store_id") or "").strip()
    conversation_id = (
        payload.get("conversation_id")
        or make_conversation_id(window_title=window_title, buyer_nick=buyer_nick)
    )

    candidates = _extract_candidates_from_payload(payload)
    conversation_history, conversation_context_contract = _normalize_conversation_history(
        payload,
        strict=strict_conversation_history,
    )
    if conversation_history and customer_message:
        from app.services.canonical_conversation_turn_service import turn_content

        last_turn = conversation_history[-1]
        if last_turn.get("role") == "customer" and turn_content(last_turn) == customer_message:
            conversation_history = conversation_history[:-1]
            conversation_context_contract = {
                **conversation_context_contract,
                "deduplicated_trailing_customer_turn": True,
            }

    context = {
        "source": payload.get("source", "qianniu_sidecar"),
        "window_title": window_title,
        "buyer_nick": buyer_nick,
        "shop_name": shop_name,
        "shop_id": shop_id,
        "conversation_id": conversation_id,
        "customer_message": customer_message,
        "customer_message_source": payload.get("customer_message_source", ""),
        "chat_text": chat_text,
        "conversation_history": conversation_history,
        "conversation_context_contract": conversation_context_contract,
        "raw_context": payload.get("raw_context", {}),
        **identifiers,
        **candidates,
        "needs_manual_confirm": payload.get("needs_manual_confirm", False),
        "extract_status": payload.get("extract_status", ""),
    }

    for key in ("order_id", "tracking_no", "platform_trade_id", "product_name"):
        explicit_value = (payload.get(key) or "").strip()
        if explicit_value:
            context[key] = explicit_value

    payload_identifier_type = str(payload.get("identifier_type") or "").strip()
    if payload_identifier_type in _ORDER_IDENTIFIER_TYPES:
        context["order_identifier_type"] = payload_identifier_type

    if not context.get("product_name"):
        context["product_name"] = best_candidate_value(context.get("product_candidates", []))

    return normalize_explicit_order_reference(
        context,
        order_id=str(payload.get("order_id") or ""),
    )
