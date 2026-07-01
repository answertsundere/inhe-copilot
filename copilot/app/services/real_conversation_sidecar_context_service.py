"""Build QianNiu-like sidecar context for real-conversation replay."""

from __future__ import annotations

from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


ORDER_REQUIRED_FACT_TYPES = {
    "aftersales",
    "aftersales_policy",
    "after_sales",
    "delivery_not_received",
    "logistics",
    "order_status",
}

ORDER_INTENT_TERMS = (
    "订单",
    "物流",
    "快递",
    "签收",
    "没收到",
    "未收到",
    "少了",
    "少件",
    "缺件",
    "漏发",
    "补发",
    "退",
    "换",
    "售后",
    "破损",
    "坏了",
    "错发",
)


def build_sidecar_context(
    *,
    case_metadata: dict[str, Any] | None = None,
    turn_metadata: dict[str, Any] | None = None,
    real_context: dict[str, Any] | None = None,
    agent_context: dict[str, Any] | None = None,
    turn_understanding: dict[str, Any] | None = None,
    buyer_message: str = "",
    product_hint: str = "",
) -> dict[str, Any]:
    """Return normalized sidecar context for replay payload construction.

    The service treats product title/SKU/order from the QianNiu sidecar as the
    primary replay context. Platform item id/hash/url are retained as
    supplemental identity hints, but they do not make context complete by
    themselves.
    """
    case_meta = case_metadata if isinstance(case_metadata, dict) else {}
    turn_meta = turn_metadata if isinstance(turn_metadata, dict) else {}
    context = real_context if isinstance(real_context, dict) else {}
    agent = agent_context if isinstance(agent_context, dict) else {}
    understanding = turn_understanding if isinstance(turn_understanding, dict) else {}
    product = context.get("product") if isinstance(context.get("product"), dict) else {}
    order = context.get("order") if isinstance(context.get("order"), dict) else {}

    product_title = _first_text(
        turn_meta,
        case_meta,
        context,
        product,
        order,
        agent,
        keys=(
            "sidecar_product_title",
            "sidecar_product_name",
            "product_title",
            "product_name",
            "product_hint",
            "item_title",
            "order_product_title",
            "purchased_product_title",
        ),
        fallback=product_hint,
    )
    sku_code = _first_text(
        turn_meta,
        case_meta,
        context,
        product,
        order,
        agent,
        keys=("sidecar_sku_code", "sku_code", "sku", "order_sku_code", "sidecar_sku"),
    )
    i_id = _first_text(
        turn_meta,
        case_meta,
        context,
        product,
        agent,
        keys=("sidecar_i_id", "i_id", "internal_i_id", "product_i_id"),
    )
    order_id = _first_text(
        turn_meta,
        case_meta,
        context,
        order,
        agent,
        keys=("sidecar_order_id", "order_id", "order_no", "tid"),
    )
    platform_order_id = _first_text(
        turn_meta,
        case_meta,
        context,
        order,
        agent,
        keys=("sidecar_platform_order_id", "platform_order_id", "order_id_hash", "order_id_masked"),
    )
    item_hash = _first_text(context, product, agent, turn_meta, case_meta, keys=("item_id_hash", "platform_item_id_hash"))
    item_id = _first_text(context, product, agent, turn_meta, case_meta, keys=("item_id", "platform_item_id"))
    product_url = _first_text(context, product, agent, turn_meta, case_meta, keys=("product_url", "item_url", "url", "link"))

    sources: list[str] = []
    if product_title:
        sources.append("sidecar_product_title")
    if sku_code:
        sources.append("sidecar_sku_code")
    if i_id:
        sources.append("sidecar_i_id")
    if order_id or platform_order_id:
        sources.append("sidecar_order_id")
    if item_hash or item_id or product_url:
        sources.append("supplemental_platform_identity")

    has_product_context = bool(product_title or sku_code or i_id)
    has_order_context = bool(order_id or platform_order_id)
    needs_order = _needs_order_context(understanding, buyer_message)
    missing: list[str] = []

    if needs_order:
        if not has_order_context:
            missing.append("order")
        quality = "complete" if has_order_context else ("partial" if has_product_context else "missing")
    else:
        if not has_product_context:
            missing.append("product")
        quality = "complete" if has_product_context else "missing"

    candidates = _build_product_candidates(product_title=product_title, sku_code=sku_code, i_id=i_id)
    result = {
        "product_name": product_title,
        "product_title": product_title,
        "sku_code": sku_code,
        "i_id": i_id,
        "order_id": order_id,
        "platform_order_id": platform_order_id,
        "product_candidates": candidates,
        "sidecar_context_quality": quality,
        "sidecar_context_sources": _dedupe(sources),
        "missing_context_fields": missing,
        "has_sidecar_product_context": has_product_context,
        "has_sidecar_order_context": has_order_context,
        "requires_order_context": needs_order,
        "supplemental_platform_identity": {
            "item_id": item_id,
            "item_id_hash": item_hash,
            "product_url": product_url,
        },
    }
    return sanitize_obj(result)


def apply_sidecar_to_context_sufficiency(
    context_sufficiency: dict[str, Any],
    sidecar_context: dict[str, Any],
) -> dict[str, Any]:
    """Adjust replay sufficiency using sidecar context as the primary signal."""
    result = dict(context_sufficiency or {})
    sidecar = sidecar_context or {}
    quality = sanitize_text(sidecar.get("sidecar_context_quality"))
    missing = list(sidecar.get("missing_context_fields") or [])
    result["sidecar_context_quality"] = quality
    result["sidecar_context_sources"] = list(sidecar.get("sidecar_context_sources") or [])
    result["has_sidecar_product_context"] = bool(sidecar.get("has_sidecar_product_context"))
    result["has_sidecar_order_context"] = bool(sidecar.get("has_sidecar_order_context"))

    if result.get("should_count_in_agent_accuracy") is False and result.get("is_sufficient") is not False:
        return sanitize_obj(result)

    if quality == "complete":
        result["is_sufficient"] = True
        result["reason"] = "sidecar context is available"
        result["missing_context_fields"] = []
        result["should_count_in_agent_accuracy"] = True
    elif quality in {"missing", "insufficient"}:
        result["is_sufficient"] = False
        result["reason"] = "missing required sidecar context"
        result["missing_context_fields"] = missing or list(result.get("missing_context_fields") or [])
        result["should_count_in_agent_accuracy"] = False
    elif quality == "partial" and sidecar.get("requires_order_context"):
        result["is_sufficient"] = False
        result["reason"] = "sidecar order context is missing"
        result["missing_context_fields"] = missing or ["order"]
        result["should_count_in_agent_accuracy"] = False
    return sanitize_obj(result)


def _needs_order_context(understanding: dict[str, Any], buyer_message: str) -> bool:
    fact_type = sanitize_text(
        understanding.get("effective_query_fact_type")
        or understanding.get("expected_query_fact_type")
        or understanding.get("query_fact_type")
    )
    secondary = {sanitize_text(item) for item in understanding.get("secondary_fact_types") or [] if sanitize_text(item)}
    if fact_type in ORDER_REQUIRED_FACT_TYPES or secondary & ORDER_REQUIRED_FACT_TYPES:
        return True
    message = str(buyer_message or "")
    return any(term in message for term in ORDER_INTENT_TERMS)


def _build_product_candidates(*, product_title: str, sku_code: str, i_id: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if sku_code:
        candidates.append({
            "type": "sku_code",
            "value": sku_code,
            "sku_code": sku_code,
            "product_name": product_title,
            "title": product_title,
            "source": "sidecar_sku_code",
            "verified": True,
        })
    if i_id:
        candidates.append({
            "type": "i_id",
            "value": i_id,
            "i_id": i_id,
            "product_name": product_title,
            "title": product_title,
            "source": "sidecar_i_id",
            "verified": True,
        })
    if product_title:
        candidates.append({
            "type": "product_title",
            "value": product_title,
            "product_name": product_title,
            "title": product_title,
            "source": "sidecar_product_title",
            "verified": bool(sku_code or i_id),
        })
    return candidates


def _first_text(*sources: dict[str, Any], keys: tuple[str, ...], fallback: str = "") -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value:
                return sanitize_text(value)
    return sanitize_text(fallback)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
