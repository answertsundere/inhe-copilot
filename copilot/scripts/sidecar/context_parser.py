from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SYSTEM_TEXT_BLACKLIST = (
    "1天内暂无导入或导出的文件",
    "模块可以手动展开收起",
    "咨询宝贝",
    "发送宝贝",
    "超级会员",
    "非会员",
    "非粉丝",
    "买家信用",
    "店铺消费",
    "平均客单价",
    "优惠券",
    "订单信息",
    "物流信息",
    "菜单",
    "按钮",
    "首页",
    "设置",
    "标签栏",
    "关闭",
    "最小化",
    "最大化",
)

LABEL_TEXT_PATTERNS = [
    r"^[\d.]+$",
    r"^已读$",
    r"^未读$",
    r"^\d+条新消息$",
    r"^在线$",
    r"^离线$",
]

CUSTOMER_PREFIXES = ("客户", "买家", "顾客", "用户", "访客", "buyer", "customer")
AGENT_PREFIXES = ("客服", "卖家", "商家", "客服助手", "机器人", "agent", "seller")


def is_system_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    for blacklisted in SYSTEM_TEXT_BLACKLIST:
        if stripped == blacklisted or stripped.startswith(blacklisted):
            return True

    for pattern in LABEL_TEXT_PATTERNS:
        if re.match(pattern, stripped):
            return True

    return False


def is_customer_message_candidate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if is_system_text(stripped):
        return False
    if len(stripped) < 2:
        return False
    if stripped.startswith("客服:") or stripped.startswith("客服："):
        return False
    for prefix in AGENT_PREFIXES:
        if stripped.lower().startswith(prefix.lower()):
            return False
    return True


def build_extract_status(
    customer_message: str,
    has_uia_sidebar: bool = False,
    has_vision: bool = False,
) -> dict[str, Any]:
    if customer_message:
        return {
            "extract_status": "ok",
            "needs_manual_confirm": False,
            "should_call_copilot_context": True,
        }

    if has_vision:
        return {
            "extract_status": "vision_only_no_customer_message",
            "needs_manual_confirm": True,
            "should_call_copilot_context": False,
        }

    return {
        "extract_status": "no_customer_message",
        "needs_manual_confirm": True,
        "should_call_copilot_context": False,
    }


@dataclass
class UIAConversationPreview:
    diagnostics: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict, repr=False)


def build_uia_preview(capture: Any) -> UIAConversationPreview:
    """Validate an adapter-scoped capture, not flattened window text.

    Actor refs must come from native speaker metadata and an independently
    selected conversation binding. They are not inferred from message content.
    This in-memory preview is neither an authenticated API payload nor a
    qualified new-message event. Only diagnostics may be logged or serialized.
    """
    diagnostics = {
        "schema_version": "qianniu_uia_preview/v1",
        "status": "blocked",
        "reason_code": "",
        "can_send": False,
        "requires_human_review": True,
        "should_call_copilot_context": False,
        "new_message_detection_qualified": False,
        "history_scope": "visible_conversation_document",
    }

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError(reason)

    def identifier(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip()) and len(value) <= 256

    def candidates(key: str, source: str) -> list[dict[str, Any]]:
        values = capture.get(key, [])
        require(isinstance(values, list) and len(values) <= 100, "candidate_list_invalid")
        require(all(identifier(value) for value in values), "candidate_list_invalid")
        return [
            {"value": value, "source": source, "verified": False}
            for value in dict.fromkeys(values)
        ]

    try:
        require(isinstance(capture, dict), "capture_schema_invalid")
        require(capture.get("schema_version") == "qianniu_uia_preview/v1", "capture_schema_invalid")
        require(capture.get("scope") == "visible_conversation_document", "conversation_scope_required")
        require(capture.get("truncated") is False, "capture_truncated_or_unknown")
        before, after = capture.get("binding_before"), capture.get("binding_after")
        require(all(
            isinstance(binding, dict)
            and set(binding) == {"window_ref", "conversation_ref"}
            and all(identifier(value) for value in binding.values())
            for binding in (before, after)
        ), "capture_binding_missing")
        require(before == after, "capture_binding_changed")
        buyer, agents = capture.get("buyer_ref"), capture.get("agent_refs")
        require(identifier(buyer) and isinstance(agents, list) and 0 < len(agents) <= 100,
                "actor_binding_invalid")
        require(all(identifier(agent) for agent in agents), "actor_binding_invalid")
        require(buyer not in agents and len(set(agents)) == len(agents), "actor_binding_invalid")
        messages = capture.get("messages")
        require(isinstance(messages, list) and 0 < len(messages) <= 200, "message_count_invalid")
        turns = []
        previous_timestamp = None
        media_tokens = {
            "image": "[IMAGE]", "video": "[VIDEO]", "link": "[LINK]",
            "order_card": "[ORDER_CARD]", "product_card": "[PRODUCT_CARD]",
        }
        for index, message in enumerate(messages):
            require(isinstance(message, dict), "message_invalid")
            sender, recipient = message.get("sender_ref"), message.get("recipient_ref")
            if sender == buyer and recipient in agents:
                role = "customer"
            elif sender in agents and recipient == buyer:
                role = "agent"
            else:
                raise ValueError("speaker_unresolved")
            raw_timestamp = message.get("timestamp")
            require(isinstance(raw_timestamp, str) and len(raw_timestamp) <= 40, "timestamp_invalid")
            try:
                timestamp = datetime.fromisoformat(raw_timestamp)
            except ValueError:
                raise ValueError("timestamp_invalid") from None
            require(timestamp.tzinfo is None and " " in raw_timestamp, "timestamp_invalid")
            require(previous_timestamp is None or timestamp >= previous_timestamp, "timestamp_out_of_order")
            previous_timestamp = timestamp
            parts = message.get("parts")
            require(isinstance(parts, list) and 0 < len(parts) <= 256, "message_parts_invalid")
            texts = []
            for part in parts:
                require(isinstance(part, dict), "message_parts_invalid")
                kind = part.get("type")
                require(isinstance(kind, str), "message_part_type_unknown")
                if kind == "text":
                    content = part.get("content")
                    require(isinstance(content, str) and bool(content.strip()), "message_text_invalid")
                    texts.append(content)
                elif kind in media_tokens:
                    texts.append(media_tokens[kind])
                else:
                    raise ValueError("message_part_type_unknown")
            content = "\n".join(texts)
            require(len(content) <= 8000, "message_text_too_large")
            turns.append({"role": role, "content": content, "turn_index": index,
                          "timestamp": timestamp.isoformat(sep=" ")})

        from app.services.canonical_conversation_turn_service import (
            ConversationContextContractError, normalize_conversation_turns,
        )
        try:
            canonical, contract = normalize_conversation_turns(turns, strict=True, max_turns=len(turns))
        except ConversationContextContractError:
            raise ValueError("canonical_turn_invalid") from None
        require(contract["status"] == "valid", "canonical_turn_invalid")
        orders = candidates("order_candidates", "uia_order_card")
        products = candidates("product_code_candidates", "uia_product_code")
        customer_tail = canonical[-1]["role"] == "customer"
        context = {
            "source": "qianniu_uia_preview",
            "customer_message": canonical[-1]["content"] if customer_tail else "",
            "conversation_history": canonical[:-1] if customer_tail else canonical,
            "order_candidates": orders,
            "product_candidates": products,
            "can_send": False,
            "requires_human_review": True,
        }
        diagnostics.update(
            status="preview_ready", turn_count=len(canonical),
            customer_turn_count=sum(turn["role"] == "customer" for turn in canonical),
            agent_turn_count=sum(turn["role"] == "agent" for turn in canonical),
            order_candidate_count=len(orders), product_code_candidate_count=len(products),
            last_turn_role=canonical[-1]["role"],
        )
        return UIAConversationPreview(diagnostics, context)
    except ValueError as exc:
        diagnostics["reason_code"] = str(exc)
        return UIAConversationPreview(diagnostics)
