"""Conversation context load/apply/update nodes."""

from __future__ import annotations

import re
import time

from app.agent.context.context_schemas import ConversationContext, summarize_context
from app.agent.context.context_store import context_store

NUMERIC_RE = re.compile(r"^\s*(\d{12,20})\s*$")


def load_conversation_context(state: dict) -> dict:
    t0 = time.time()
    conversation_id = state.get("conversation_id") or "default"
    raw = context_store.get(conversation_id)
    ctx = ConversationContext.from_dict(raw, conversation_id).to_dict()
    trace = {
        "node": "load_conversation_context",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": bool(raw),
        "summary": f"loaded conversation {conversation_id}",
    }
    return {
        "conversation_id": conversation_id,
        "conversation_context": ctx,
        "conversation_context_summary": summarize_context(ctx),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def apply_conversation_context(state: dict) -> dict:
    """Use previous turn context to disambiguate terse follow-up messages."""
    t0 = time.time()
    ctx = state.get("conversation_context", {}) or {}
    msg = state.get("normalized_message", state.get("customer_message", ""))
    slots = dict(state.get("slots", {}) or {})
    match = NUMERIC_RE.match(msg or "")
    updates = {}
    applied = []

    if match and (
        "order_id" in ctx.get("last_requested_slots", [])
        or "tracking_no" in ctx.get("last_requested_slots", [])
        or ctx.get("active_issue") in ("delivery_not_received", "logistics_eta", "logistics_trace")
    ):
        ident = match.group(1)
        slots["possible_numeric_id"] = ident
        slots["identifier_type"] = "unknown_identifier"
        updates.update({
            "slots": slots,
            "intent": ctx.get("active_issue") if ctx.get("active_issue") == "delivery_not_received" else "logistics_eta",
            "skill": "logistics",
            "selected_tool": "jst_live_query",
            "identifier_type": "unknown_identifier",
            "identifier_value": ident,
        })
        applied.append("numeric_followup_as_order_identifier")

    trace = {
        "node": "apply_conversation_context",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": bool(ctx),
        "summary": ", ".join(applied) if applied else "no context override",
    }
    updates["trace_steps"] = state.get("trace_steps", []) + [trace]
    return updates


def update_conversation_context(state: dict) -> dict:
    t0 = time.time()
    conversation_id = state.get("conversation_id") or "default"
    ctx = dict(state.get("conversation_context", {}) or {})
    slots = state.get("slots", {}) or {}
    reply = state.get("suggested_reply", "")
    intent = state.get("intent", "")
    response_plan = state.get("response_strategy_plan", {}) or {}

    ctx["last_intent"] = ctx.get("current_intent", "")
    ctx["current_intent"] = intent
    if intent:
        ctx["active_issue"] = intent
    ctx["customer_emotion"] = state.get("customer_emotion", ctx.get("customer_emotion", "neutral"))
    ctx["customer_urgency"] = state.get("customer_urgency", ctx.get("customer_urgency", "low"))
    ctx["customer_concern"] = state.get("customer_concern", ctx.get("customer_concern", "unknown"))
    ctx["risk_level"] = state.get("risk_level", ctx.get("risk_level", "low"))
    ctx["previous_agent_reply"] = reply[:500]
    ctx["needs_human_review"] = bool(state.get("requires_human_review") or state.get("needs_human_review"))

    identifier = (
        slots.get("platform_trade_id")
        or slots.get("order_id")
        or slots.get("tracking_no")
        or slots.get("possible_numeric_id")
        or state.get("identifier_value", "")
    )
    id_type = slots.get("identifier_type") or state.get("identifier_type", "")
    if identifier:
        if id_type in ("platform_trade_id", "unknown_identifier"):
            ctx["known_platform_trade_id"] = identifier
        elif id_type in ("tracking_no",):
            ctx["known_tracking_no"] = identifier
        else:
            ctx["known_order_id"] = identifier

    product = slots.get("product_name") or state.get("matched_product_name", "")
    if product:
        ctx["confirmed_product"] = product

    identity = state.get("order_product_identity") or {}
    if identity:
        identity_key = ""
        if identity.get("identifier"):
            if identity.get("source") in ("sidecar_product_code", "jst_sku_query"):
                identity_key = f"product_code:{identity.get('identifier_type', '')}:{identity.get('identifier', '')}"
            elif identity.get("source") == "sidecar_product_name":
                identity_key = f"product_name:{identity.get('identifier', '')}"
            else:
                identity_key = f"{identity.get('identifier_type', '')}:{identity.get('identifier', '')}"
        ctx["order_product_identity"] = identity
        ctx["order_product_identity_key"] = identity_key
        if identity.get("matched_product_name"):
            ctx["confirmed_product"] = identity["matched_product_name"]

    missing_slots = response_plan.get("missing_slots") or state.get("missing_slots", [])
    ctx["unresolved_slots"] = missing_slots
    if missing_slots:
        ctx["last_requested_slots"] = missing_slots
        if any(s in missing_slots for s in ("order_id", "tracking_no")):
            ctx["has_already_asked_order_id"] = True
        if any(s in missing_slots for s in ("product_link", "product_screenshot", "sku")):
            ctx["has_already_asked_product_info"] = True

    if "抱歉" in reply or "不好意思" in reply or "理解" in reply:
        ctx["has_already_apologized"] = True

    context_store.set(conversation_id, ctx)
    trace = {
        "node": "update_conversation_context",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": False,
        "summary": "conversation context updated",
    }
    return {
        "conversation_context": ctx,
        "conversation_context_summary": summarize_context(ctx),
        "context_updated": True,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
