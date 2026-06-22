"""Structured policy gate for agent tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.tools.tool_policy import (
    POLICY_VERSION,
    READ_ONLY_SENSITIVE,
    WRITE_OR_SIDE_EFFECT,
    get_tool_policy,
)


@dataclass(frozen=True)
class ToolPolicyDecision:
    tool_name: str
    allowed: bool
    reason: str
    required_entities_missing: tuple[str, ...]
    risk_level: str
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "reason": self.reason,
            "required_entities_missing": list(self.required_entities_missing),
            "risk_level": self.risk_level,
            "policy_version": self.policy_version,
        }


def evaluate_tool_call(tool_name: str, context: dict) -> ToolPolicyDecision:
    """Return whether a tool may run for the structured request context."""
    policy = get_tool_policy(tool_name)
    normalized = _normalize_context(context or {})

    if policy.max_calls_per_request <= 0 or policy.denied_when:
        return _decision(tool_name, False, policy.denied_when[0] if policy.denied_when else "tool_disabled", (), policy.risk_level)

    intent = normalized["intent"]
    if policy.allowed_intents and intent not in policy.allowed_intents:
        return _decision(tool_name, False, "intent_not_allowed", (), policy.risk_level)

    if policy.allowed_fact_types:
        fact_types = set(normalized["fact_types"])
        if not fact_types.intersection(policy.allowed_fact_types):
            return _decision(tool_name, False, "fact_type_not_allowed", (), policy.risk_level)

    missing = tuple(entity for entity in policy.required_entities if not _has_required_entity(entity, normalized))
    if missing:
        return _decision(tool_name, False, "required_entity_missing", missing, policy.risk_level)

    if policy.risk_level == READ_ONLY_SENSITIVE and not _has_sensitive_intent(intent):
        return _decision(tool_name, False, "sensitive_tool_requires_structured_intent", (), policy.risk_level)

    if policy.risk_level == WRITE_OR_SIDE_EFFECT:
        return _decision(tool_name, False, "write_tool_blocked", (), policy.risk_level)

    return _decision(tool_name, True, "allowed", (), policy.risk_level)


def _decision(tool_name: str, allowed: bool, reason: str, missing: tuple[str, ...], risk_level: str) -> ToolPolicyDecision:
    return ToolPolicyDecision(
        tool_name=str(tool_name or ""),
        allowed=bool(allowed),
        reason=str(reason or ""),
        required_entities_missing=missing,
        risk_level=str(risk_level or ""),
    )


def _normalize_context(context: dict) -> dict[str, Any]:
    understanding = context.get("query_understanding") if isinstance(context.get("query_understanding"), dict) else {}
    slots = context.get("slots") if isinstance(context.get("slots"), dict) else {}
    identity = context.get("order_product_identity") if isinstance(context.get("order_product_identity"), dict) else {}

    intent = _first_text(
        context.get("intent"),
        context.get("final_intent"),
        understanding.get("intent"),
        understanding.get("primary_intent"),
    )
    fact_types = _fact_types(context, understanding)
    product_entities = _list_values(context.get("product_entities")) + _list_values(understanding.get("product_entities"))
    order_entities = _list_values(context.get("order_entities")) + _list_values(understanding.get("order_entities"))
    message = _first_text(
        context.get("retrieval_query"),
        context.get("normalized_message"),
        context.get("customer_message"),
        context.get("message"),
        understanding.get("retrieval_query"),
        understanding.get("normalized_message"),
    )

    product_markers = [
        context.get("matched_product_name"),
        context.get("product_name"),
        slots.get("product_name"),
        slots.get("sku_name"),
        slots.get("sku_code"),
        identity.get("matched_product_name"),
        identity.get("sku_id"),
        identity.get("i_id"),
    ]
    order_markers = [
        context.get("order_id"),
        context.get("platform_order_id"),
        context.get("platform_trade_id"),
        slots.get("order_id"),
        slots.get("platform_order_id"),
        slots.get("platform_trade_id"),
        slots.get("possible_numeric_id"),
    ]
    tracking_markers = [context.get("tracking_no"), slots.get("tracking_no")]

    return {
        "intent": intent,
        "fact_types": fact_types,
        "message": message,
        "has_product_entity": bool(product_entities or any(_present(v) for v in product_markers)),
        "has_order_entity": bool(order_entities or any(_present(v) for v in order_markers)),
        "has_tracking_entity": bool(any(_present(v) for v in tracking_markers)),
    }


def _fact_types(context: dict, understanding: dict) -> list[str]:
    values: list[str] = []
    for key in ("query_fact_type", "required_fact_types"):
        values.extend(_list_values(context.get(key)))
        values.extend(_list_values(understanding.get(key)))
    for key in ("secondary_fact_types",):
        values.extend(_list_values(context.get(key)))
        values.extend(_list_values(understanding.get(key)))
    return [v for v in dict.fromkeys(values) if v]


def _has_required_entity(entity: str, normalized: dict[str, Any]) -> bool:
    if entity == "message":
        return bool(normalized["message"])
    if entity == "product_entity":
        return bool(normalized["has_product_entity"])
    if entity == "order_entity":
        return bool(normalized["has_order_entity"])
    if entity == "tracking_entity":
        return bool(normalized["has_tracking_entity"])
    if entity == "product_or_query":
        return bool(normalized["has_product_entity"] or normalized["message"])
    return False


def _has_sensitive_intent(intent: str) -> bool:
    return intent in {
        "logistics_eta",
        "logistics_trace",
        "delivery_not_received",
        "shipping",
        "logistics",
        "aftersales",
        "stock_query",
        "product_question",
    }


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        result = []
        for key in ("value", "name", "type", "fact_type", "query_fact_type", "sku_code", "order_id", "tracking_no"):
            if _present(value.get(key)):
                result.append(str(value.get(key)).strip())
        return result or ["dict_entity"]
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_list_values(item))
        return result
    return [str(value).strip()] if str(value).strip() else []


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True
