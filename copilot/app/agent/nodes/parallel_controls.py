from __future__ import annotations

import time

from app import config


JST_TOOLS = ["jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"]
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def apply_parallel_pre_strategy_controls(state: dict) -> dict:
    """Apply Phase 2 high-risk/fusion routing controls before strategy routing.

    This node intentionally avoids broad routing takeover. By default it only
    enforces high-risk human review from decision_fusion.
    """
    t0 = time.time()
    fusion = state.get("decision_fusion") or {}
    updates: dict = {}
    actions: list[str] = []

    if config.ENABLE_PARALLEL_HIGH_RISK_GATE:
        fusion_risk = fusion.get("risk_level", "")
        if fusion.get("need_human_review") or fusion_risk == "high":
            updates["requires_human_review"] = True
            updates["needs_human_review"] = True
            if _risk_rank(fusion_risk) > _risk_rank(state.get("risk_level", "low")):
                updates["risk_level"] = fusion_risk
            final_intent = fusion.get("final_intent", "")
            if final_intent in ("missing_item", "damaged_item", "wrong_item", "refund_request", "return_request"):
                current = state.get("intent", "")
                if current in ("general", "product_question", "product_consult", "installation"):
                    updates["intent"] = "aftersales"
                    actions.append(f"manual_review_intent={final_intent}")
            if not state.get("review_reason"):
                updates["review_reason"] = "parallel_understanding_high_risk"
            actions.append("high_risk_gate")

    if config.ENABLE_PARALLEL_FUSION_ROUTING:
        final_intent = fusion.get("final_intent", "")
        if final_intent and _can_minimally_override_intent(state, final_intent):
            updates["intent"] = _legacy_intent(final_intent)
            actions.append(f"intent={final_intent}")

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "parallel_pre_strategy_controls",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "actions": actions,
        "summary": "parallel controls: " + (", ".join(actions) if actions else "observation/no-op"),
    }
    return {**updates, "trace_steps": state.get("trace_steps", []) + [trace]}


def apply_parallel_post_strategy_controls(state: dict) -> dict:
    """Apply Phase 2 identifier tool overrides after legacy strategy routing."""
    t0 = time.time()
    fusion = state.get("decision_fusion") or {}
    required = list(state.get("required_tools") or [])
    allowed = list(state.get("allowed_tools") or [])
    forbidden = list(state.get("forbidden_tools") or [])
    actions: list[str] = []

    if config.ENABLE_PARALLEL_IDENTIFIER_ROUTING:
        fusion_required = list(fusion.get("required_tools") or [])
        selected = _selected_identifier_tool(state, fusion_required)
        if selected:
            required = [selected]
            allowed = _unique([selected] + [t for t in allowed if t not in JST_TOOLS] + ["rag_search_tool", "template_select_tool"])
            forbidden = [t for t in JST_TOOLS if t != selected]
            actions.append(f"identifier_tool={selected}")

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "parallel_post_strategy_controls",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "actions": actions,
        "summary": "parallel post controls: " + (", ".join(actions) if actions else "observation/no-op"),
    }
    return {
        "intent": state.get("intent", ""),
        "response_strategy": state.get("response_strategy", ""),
        "required_tools": required,
        "allowed_tools": allowed,
        "forbidden_tools": forbidden,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _can_minimally_override_intent(state: dict, final_intent: str) -> bool:
    current = state.get("intent", "")
    if final_intent in ("complaint", "missing_item", "damaged_item", "wrong_item", "delivery_not_received"):
        return current in ("general", "product_question", "aftersales", "logistics_eta", "shipping", "logistics")
    if final_intent in ("logistics_eta", "logistics_tracking"):
        return _has_identifier(state) and current in ("general", "product_question", "shipping", "logistics")
    return False


def _legacy_intent(final_intent: str) -> str:
    if final_intent in ("missing_item", "damaged_item", "wrong_item", "refund_request", "return_request"):
        return "aftersales"
    if final_intent in ("logistics_tracking",):
        return "logistics_eta"
    if final_intent in ("material_question", "size_question", "installation_question"):
        return "product_question"
    return final_intent


def _selected_identifier_tool(state: dict, fusion_required: list[str]) -> str:
    intent = state.get("intent", "")
    if intent not in ("logistics_eta", "shipping", "logistics", "delivery_not_received"):
        return ""
    for tool in ("jst_lookup_outbound_tool", "jst_lookup_tracking_tool", "jst_lookup_order_tool"):
        if tool in fusion_required:
            return tool
    return ""


def _has_identifier(state: dict) -> bool:
    from app.agent.state import has_order_identifier
    return has_order_identifier(state)


def _unique(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _risk_rank(risk_level: str) -> int:
    return RISK_ORDER.get(risk_level or "low", 0)
