"""Build a compact, observable understanding snapshot for the current turn."""

from __future__ import annotations

from typing import Any


_FACT_TYPE_TO_SUB_INTENT = {
    "material": "material_safety",
    "certification_report": "material_safety",
    "pinch_safety": "child_safety",
    "safety_small_parts": "child_safety",
    "odor": "odor_question",
    "cleaning_care": "cleaning_care",
    "installation": "installation",
    "detachable": "installation",
    "stock_shipping": "stock_query",
    "invoice_policy": "invoice",
    "price_protection": "price_protection",
    "promotion_policy": "promotion_query",
    "gift_policy": "gift_missing",
    "aftersales_policy": "aftersales",
}


def build_query_understanding(state: dict[str, Any], fact_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a stable query-understanding dict without changing routing semantics."""

    fact_result = fact_result or {}
    original_message = str(state.get("customer_message") or "")
    normalized_message = str(state.get("normalized_message") or original_message)
    query_fact_type = str(fact_result.get("query_fact_type") or state.get("query_fact_type") or "")
    rejected_fact_type = str(fact_result.get("llm_rejected_fact_type") or "").strip()
    secondary_fact_types = _unique([
        *list(fact_result.get("secondary_fact_types") or []),
        *list(state.get("secondary_fact_types") or []),
    ])
    if rejected_fact_type:
        secondary_fact_types = [item for item in secondary_fact_types if item != rejected_fact_type]
    intent = str(state.get("intent") or state.get("final_intent") or "general")
    sub_intents = _unique([
        *list(state.get("secondary_intents") or []),
        *[_FACT_TYPE_TO_SUB_INTENT.get(ft, "product_question") for ft in [query_fact_type, *secondary_fact_types] if ft],
    ])
    semantic_query = fact_result.get("semantic_query") or state.get("semantic_query") or {}
    retrieval_focus = str(semantic_query.get("retrieval_focus") or fact_result.get("retrieval_focus") or "")
    retrieval_query = _build_retrieval_query(normalized_message, retrieval_focus, state)

    return {
        "original_message": original_message,
        "normalized_message": normalized_message,
        "retrieval_query": retrieval_query,
        "intent": intent,
        "sub_intents": sub_intents,
        "query_fact_type": query_fact_type,
        "secondary_fact_types": secondary_fact_types,
        "risk_level": state.get("risk_level", ""),
        "product_entities": _product_entities(state),
        "order_entities": _order_entities(state),
        "history_context": state.get("history_snapshot") or state.get("conversation_context_summary") or {},
        "generation_context": state.get("generation_context") or state.get("generated_context") or {},
        "context_reset_reason": state.get("context_reset_reason", ""),
        "confidence": fact_result.get("confidence", state.get("query_fact_type_confidence", 0)),
        "source": fact_result.get("source", state.get("query_fact_type_source", "")),
        "llm_rejected_fact_type": rejected_fact_type,
    }


def refresh_query_understanding(state: dict[str, Any], **updates: Any) -> dict[str, Any]:
    current = dict(state.get("query_understanding") or {})
    current.update({key: value for key, value in updates.items() if value not in (None, "", [], {})})
    return current


def _build_retrieval_query(message: str, retrieval_focus: str, state: dict[str, Any]) -> str:
    parts = [message]
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots") or {}
    for value in (
        state.get("matched_product_name"),
        identity.get("matched_product_name"),
        slots.get("product_name"),
        slots.get("sku_name"),
        slots.get("sku_code"),
        identity.get("sku_id"),
        identity.get("i_id"),
    ):
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    if retrieval_focus and retrieval_focus not in parts:
        parts.append(retrieval_focus)
    return " ".join(parts)[:500]


def _product_entities(state: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    slots = state.get("slots") or {}
    identity = state.get("order_product_identity") or {}
    for key, source in (
        ("matched_product_name", "state"),
        ("product_name", "slots"),
        ("sku_name", "slots"),
        ("sku_code", "slots"),
        ("sku_id", "identity"),
        ("i_id", "identity"),
    ):
        container = identity if source == "identity" else slots if source == "slots" else state
        value = str(container.get(key) or "").strip()
        if value:
            entities.append({"type": key, "value": value, "source": source})
    for candidate in state.get("product_candidates") or []:
        if isinstance(candidate, str):
            entities.append({"type": "candidate", "value": candidate, "source": "product_candidates"})
        elif isinstance(candidate, dict):
            value = str(candidate.get("value") or candidate.get("product_name") or candidate.get("title") or "").strip()
            if value:
                entities.append({
                    "type": str(candidate.get("type") or "candidate"),
                    "value": value,
                    "source": "product_candidates",
                })
    return _dedupe_entities(entities)


def _order_entities(state: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    slots = state.get("slots") or {}
    for key in ("order_id", "platform_order_id", "platform_trade_id", "tracking_no", "possible_numeric_id"):
        value = str(slots.get(key) or state.get(key) or "").strip()
        if value:
            entities.append({"type": key, "value": value, "source": "slots_or_state"})
    identifier_type = str(state.get("identifier_type") or slots.get("identifier_type") or "").strip()
    identifier_value = str(state.get("identifier_value") or "").strip()
    if identifier_type and identifier_value:
        entities.append({"type": identifier_type, "value": identifier_value, "source": "identifier_router"})
    return _dedupe_entities(entities)


def _dedupe_entities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = (item.get("type"), item.get("value"))
        if not item.get("value") or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:12]


def _unique(items: list[str]) -> list[str]:
    out = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out
