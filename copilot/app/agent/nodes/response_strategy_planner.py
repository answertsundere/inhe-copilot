"""Gold CSR response strategy planner."""

from __future__ import annotations

import re
import time


MODEL_MARKER_RE = re.compile(r"([一二三四五六七八九十百千万两0-9]+号)")


def _has_product_evidence(state: dict) -> bool:
    evidence = state.get("evidence", {}) or {}
    return bool(evidence.get("product_facts") or evidence.get("faq_evidence") or state.get("knowledge_evidence"))


def _has_clear_product_identity(state: dict) -> bool:
    slots = state.get("slots", {}) or {}
    msg = state.get("normalized_message", state.get("customer_message", ""))
    product = slots.get("product_name") or state.get("matched_product_name", "")
    identity = state.get("order_product_identity") or {}
    copilot_context = state.get("copilot_context", {}) or {}
    if (
        (identity.get("status") == "resolved" and identity.get("matched_product_name"))
        or state.get("product_candidates")
        or copilot_context.get("product_candidates")
        or copilot_context.get("product_name")
    ):
        return True
    has_model_marker = bool(MODEL_MARKER_RE.search(msg))
    if has_model_marker:
        return True
    if not product or product in ("实木", "材质", "安全", "无毒", "填充"):
        return False
    if "这个" in msg or "这款" in msg:
        return False
    return True


def _has_ambiguous_sidecar_product_name(state: dict) -> bool:
    """Only truly ambiguous when 2+ distinct product candidates exist."""
    identity = state.get("order_product_identity") or {}
    if identity.get("source") != "sidecar_product_name" or identity.get("status") != "ambiguous":
        return False
    candidates = identity.get("candidates") or []
    distinct_ids = set()
    for c in candidates:
        if not isinstance(c, dict):
            continue
        pid = c.get("i_id") or c.get("name") or ""
        if pid:
            distinct_ids.add(pid)
    return len(distinct_ids) >= 2


def _has_order_identifier(state: dict) -> bool:
    """Check if slots/state already contain an order identifier (order_id, tracking_no, etc.)."""
    from app.agent.state import has_order_identifier
    return has_order_identifier(state)


def _compute_missing_order_slots(state: dict) -> list[str]:
    """Return only the order-related slots that are actually missing.
    Order identifiers are substitutable: if any one is present, don't ask for others."""
    if _has_order_identifier(state):
        return []  # Any identifier suffices; don't ask for more
    return ["order_id", "tracking_no"]


def _has_known_product_identity(state: dict) -> bool:
    """Check if we already have a resolved product identity (SKU, i_id, or product name)."""
    slots = state.get("slots", {}) or {}
    identity = state.get("order_product_identity") or {}
    return bool(
        slots.get("sku_code") or slots.get("sku_name")
        or (identity.get("status") == "resolved" and identity.get("matched_product_name"))
        or state.get("matched_product_name")
    )


def _compute_missing_product_slots(state: dict) -> list[str]:
    """Return only the product-related slots that are actually missing.
    If we already have SKU, product name, or a resolved identity, don't ask for more."""
    if _has_known_product_identity(state):
        return []  # Already identified; don't ask for more
    # Only ask for what's truly missing
    missing = []
    slots = state.get("slots", {}) or {}
    if not slots.get("product_name") and not state.get("matched_product_name"):
        missing.append("product_link")
    return missing


def response_strategy_planner(state: dict) -> dict:
    t0 = time.time()
    intent = state.get("intent", "")
    concern = state.get("customer_concern", "unknown")
    customer_state = state.get("customer_state", {}) or {}
    ctx = state.get("conversation_context", {}) or {}
    msg = state.get("normalized_message", state.get("customer_message", ""))

    reply_goal = "ask_for_missing_info"
    tone = "professional"
    empathy_level = "low"
    should_answer_directly = False
    should_set_boundary = False
    should_explain_reason = False
    should_ask_slot = False
    should_offer_next_step = True
    should_escalate = bool(customer_state.get("needs_human_review"))
    missing_slots: list[str] = []

    if _has_ambiguous_sidecar_product_name(state):
        reply_goal = "clarify_product_identity"
        tone = "careful"
        empathy_level = "low"
        should_answer_directly = False
        should_ask_slot = True
        missing_slots = ["product_link", "product_screenshot", "sku"]

    elif concern == "wants_eta_certainty":
        reply_goal = "explain_no_guarantee"
        tone = "reassuring"
        empathy_level = "medium"
        should_answer_directly = True
        should_set_boundary = True
        should_explain_reason = True
        missing_slots = _compute_missing_order_slots(state)
        should_ask_slot = bool(missing_slots)

    elif concern in ("social_frustration", "smalltalk"):
        reply_goal = "social_reply"
        tone = "calm"
        empathy_level = "medium"
        should_answer_directly = True
        should_offer_next_step = True
        missing_slots = []

    elif intent == "delivery_not_received" or concern == "worries_package_lost":
        reply_goal = "handle_delivery_not_received"
        tone = "empathetic"
        empathy_level = "high"
        should_answer_directly = True
        should_explain_reason = True
        should_ask_slot = not (state.get("order_found") or state.get("live_order") or _has_order_identifier(state))
        should_escalate = True
        if should_ask_slot:
            missing_slots = _compute_missing_order_slots(state)

    elif concern == "angry_about_delay":
        reply_goal = "deescalate_complaint"
        tone = "empathetic"
        empathy_level = "high"
        should_answer_directly = True
        should_explain_reason = True
        should_escalate = True
        missing_slots = _compute_missing_order_slots(state)
        should_ask_slot = bool(missing_slots)

    elif intent in ("logistics_eta", "logistics_trace", "shipping", "logistics"):
        has_order = state.get("order_found") or state.get("live_order") or _has_order_identifier(state)
        reply_goal = "query_order_status" if has_order else "ask_for_missing_info"
        should_answer_directly = bool(state.get("order_found") or state.get("logistics_trace"))
        missing_slots = _compute_missing_order_slots(state) if not has_order else []
        should_ask_slot = bool(missing_slots)

    elif concern in ("worries_material", "worries_product_safety"):
        if _has_clear_product_identity(state) and _has_product_evidence(state):
            reply_goal = "answer_product_fact"
            should_answer_directly = True
        else:
            reply_goal = "clarify_product_identity"
            should_ask_slot = True
            missing_slots = _compute_missing_product_slots(state)
        tone = "careful"
        empathy_level = "low"

    elif intent in ("logistics_eta", "logistics_trace"):
        has_order = state.get("order_found") or state.get("live_order") or _has_order_identifier(state)
        reply_goal = "query_order_status" if has_order else "ask_for_missing_info"
        should_answer_directly = bool(state.get("order_found") or state.get("logistics_trace"))
        missing_slots = _compute_missing_order_slots(state) if not has_order else []
        should_ask_slot = bool(missing_slots)

    elif intent == "product_question":
        reply_goal = "answer_product_fact" if _has_clear_product_identity(state) and _has_product_evidence(state) else "clarify_product_identity"
        should_answer_directly = reply_goal == "answer_product_fact"
        should_ask_slot = not should_answer_directly
        if should_ask_slot:
            missing_slots = _compute_missing_product_slots(state)

    if ctx.get("has_already_asked_order_id") and missing_slots:
        tone = "patient"
    if "安装" in msg:
        reply_goal = "guide_installation"

    reply_structure = [
        "empathy",
        "direct_answer_or_boundary",
        "evidence_or_reason",
        "next_action",
        "human_review_if_needed",
    ]
    plan = {
        "reply_goal": reply_goal,
        "tone": tone,
        "empathy_level": empathy_level,
        "should_answer_directly": should_answer_directly,
        "should_set_boundary": should_set_boundary,
        "should_explain_reason": should_explain_reason,
        "should_ask_slot": should_ask_slot,
        "should_offer_next_step": should_offer_next_step,
        "should_escalate": should_escalate,
        "reply_structure": reply_structure,
        "missing_slots": missing_slots,
    }
    trace = {
        "node": "response_strategy_planner",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": False,
        "summary": f"reply_goal={reply_goal}, tone={tone}",
    }
    return {
        "response_strategy_plan": plan,
        "reply_goal": reply_goal,
        "reply_structure": reply_structure,
        "missing_slots": missing_slots,
        "requires_human_review": bool(state.get("requires_human_review", False) or should_escalate),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
