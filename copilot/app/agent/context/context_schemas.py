"""Conversation context schema for multi-turn CSR behavior."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class ConversationContext:
    conversation_id: str
    current_turn_id: str = field(default_factory=lambda: uuid4().hex)
    last_intent: str = ""
    current_intent: str = ""
    active_issue: str = ""
    last_agent_question: str = ""
    last_requested_slots: list[str] = field(default_factory=list)
    known_order_id: str = ""
    known_platform_trade_id: str = ""
    known_tracking_no: str = ""
    known_product_candidates: list[str] = field(default_factory=list)
    confirmed_product: str = ""
    order_product_identity_key: str = ""
    order_product_identity: dict = field(default_factory=dict)
    customer_emotion: str = "neutral"
    customer_urgency: str = "low"
    customer_concern: str = "unknown"
    risk_level: str = "low"
    unresolved_slots: list[str] = field(default_factory=list)
    previous_agent_reply: str = ""
    has_already_asked_order_id: bool = False
    has_already_asked_product_info: bool = False
    has_already_apologized: bool = False
    needs_human_review: bool = False
    context_reset_reason: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def new(cls, conversation_id: str) -> "ConversationContext":
        return cls(conversation_id=conversation_id)

    @classmethod
    def from_dict(cls, data: dict | None, conversation_id: str) -> "ConversationContext":
        if not data:
            return cls.new(conversation_id)
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in allowed}
        clean["conversation_id"] = conversation_id
        clean["current_turn_id"] = uuid4().hex
        return cls(**clean)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return data


def summarize_context(ctx: dict) -> dict:
    """Return a privacy-safe context summary for API debug output."""
    if not ctx:
        return {}
    return {
        "conversation_id": ctx.get("conversation_id", ""),
        "last_intent": ctx.get("last_intent", ""),
        "current_intent": ctx.get("current_intent", ""),
        "active_issue": ctx.get("active_issue", ""),
        "last_requested_slots": ctx.get("last_requested_slots", []),
        "has_known_order_id": bool(ctx.get("known_order_id")),
        "has_known_platform_trade_id": bool(ctx.get("known_platform_trade_id")),
        "has_known_tracking_no": bool(ctx.get("known_tracking_no")),
        "confirmed_product": ctx.get("confirmed_product", ""),
        "has_order_product_identity": bool(ctx.get("order_product_identity")),
        "customer_emotion": ctx.get("customer_emotion", ""),
        "customer_urgency": ctx.get("customer_urgency", ""),
        "customer_concern": ctx.get("customer_concern", ""),
        "unresolved_slots": ctx.get("unresolved_slots", []),
        "has_already_asked_order_id": bool(ctx.get("has_already_asked_order_id")),
        "has_already_asked_product_info": bool(ctx.get("has_already_asked_product_info")),
        "needs_human_review": bool(ctx.get("needs_human_review")),
        "context_reset_reason": ctx.get("context_reset_reason", ""),
    }
