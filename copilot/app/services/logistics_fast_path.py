"""Shared eligibility check for deterministic logistics routing."""

from __future__ import annotations

from app import config


EXPLICIT_LOGISTICS_INTENTS = {
    "logistics_eta",
    "logistics_trace",
    "shipping",
    "logistics",
}
ORDER_OPERATION_TERMS = ("改地址", "收货地址", "转寄", "拦截", "拒收")


def get_explicit_logistics_identifier(state: dict) -> dict | None:
    """Return a verified identifier descriptor when the fast path is safe."""
    if not config.COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED:
        return None

    intent = str(state.get("intent") or "")
    message = str(
        state.get("normalized_message") or state.get("customer_message") or ""
    )
    is_order_operation = any(term in message for term in ORDER_OPERATION_TERMS)
    if intent not in EXPLICIT_LOGISTICS_INTENTS and not is_order_operation:
        return None

    if state.get("risk_level", "low") not in (
        ("low", "medium") if is_order_operation else ("low",)
    ):
        return None
    if (
        not is_order_operation
        and (state.get("requires_human_review") or state.get("needs_human_review"))
    ):
        return None

    fusion = state.get("decision_fusion") or {}
    if fusion.get("risk_level") in ("high", "critical"):
        return None
    if fusion.get("need_human_review") and not is_order_operation:
        return None

    slots = state.get("slots") or {}
    identifier_type = str(slots.get("identifier_type") or "")
    if identifier_type in ("unknown_identifier", "possible_numeric_id"):
        return None

    candidates = (
        ("platform_trade_id", slots.get("platform_trade_id")),
        ("platform_order_id", slots.get("platform_order_id")),
        ("tracking_no", slots.get("tracking_no") or state.get("tracking_no")),
        (
            "internal_order_id",
            (slots.get("order_id") or state.get("order_id"))
            if identifier_type in ("internal_order_id", "order_id")
            else "",
        ),
    )
    for candidate_type, value in candidates:
        value = str(value or "").strip()
        if value:
            return {
                "identifier_type": candidate_type,
                "identifier_value": value,
            }
    return None


def get_semantic_free_logistics_identifier(state: dict) -> dict | None:
    """Return an identifier only when logistics semantics are unambiguous.

    An order identifier proves that an order lookup is possible, but it does
    not prove that the customer only wants tracking or ETA.  A carrier-issued
    tracking number is the narrower transport identity required to skip Turn
    Understanding.  Order operations retain their customer-goal analysis even
    when a tracking number is present.
    """
    descriptor = get_explicit_logistics_identifier(state)
    if not descriptor or descriptor.get("identifier_type") != "tracking_no":
        return None

    message = str(
        state.get("normalized_message") or state.get("customer_message") or ""
    )
    if any(term in message for term in ORDER_OPERATION_TERMS):
        return None
    return descriptor
