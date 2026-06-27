"""Context sufficiency checks for real-conversation replay scoring.

The goal is to separate sample/context quality from Agent answer quality. A
turn can still be replayed through the Agent, but if the source conversation
lacks the product/order identity required by the task, it should not count in
the Agent accuracy denominator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


CONTEXT_GAP = "context_gap"

ORDER_FACT_TYPES = {
    "delivery_not_received",
    "invoice_policy",
    "logistics",
    "order_status",
}

AFTERSALES_FACT_TYPES = {
    "after_sales",
    "aftersales",
    "aftersales_policy",
}

PRODUCT_FACT_TYPES = {
    "accessory_usage",
    "certification_report",
    "dimensions",
    "installation",
    "load_capacity",
    "material",
    "material_safety",
    "odor",
    "placement_scene",
    "promotion",
    "promotion_policy",
    "space_fit",
    "stability",
    "stock_shipping",
    "visual_asset",
}


@dataclass(frozen=True)
class ContextSufficiencyResult:
    is_sufficient: bool
    reason: str
    required_context_fields: tuple[str, ...] = ()
    missing_context_fields: tuple[str, ...] = ()
    has_product_context: bool = False
    has_order_context: bool = False
    has_media_context: bool = False
    should_count_in_agent_accuracy: bool = True

    def to_dict(self) -> dict[str, Any]:
        return sanitize_obj({
            "is_sufficient": self.is_sufficient,
            "reason": self.reason,
            "required_context_fields": list(self.required_context_fields),
            "missing_context_fields": list(self.missing_context_fields),
            "has_product_context": self.has_product_context,
            "has_order_context": self.has_order_context,
            "has_media_context": self.has_media_context,
            "should_count_in_agent_accuracy": self.should_count_in_agent_accuracy,
        })


def assess_context_sufficiency(
    *,
    turn_understanding: dict[str, Any] | None,
    real_context_summary: dict[str, Any] | None,
    real_context_identity: dict[str, Any] | None,
) -> ContextSufficiencyResult:
    understanding = turn_understanding or {}
    summary = real_context_summary or {}
    identity = real_context_identity or {}
    should_score = understanding.get("should_score")
    actionability = sanitize_text(understanding.get("turn_actionability"))
    query_fact_type = sanitize_text(
        understanding.get("effective_query_fact_type")
        or understanding.get("expected_query_fact_type")
        or understanding.get("query_fact_type")
    )
    secondary_fact_types = {
        sanitize_text(item)
        for item in (understanding.get("secondary_fact_types") or [])
        if sanitize_text(item)
    }
    fact_types = {query_fact_type, *secondary_fact_types} - {""}

    has_product_context = _has_product_context(summary, identity)
    has_order_context = _has_order_context(summary, identity)
    has_media_context = bool(summary.get("has_media_context"))

    if should_score is False:
        return ContextSufficiencyResult(
            is_sufficient=True,
            reason="turn is not scored",
            has_product_context=has_product_context,
            has_order_context=has_order_context,
            has_media_context=has_media_context,
            should_count_in_agent_accuracy=False,
        )

    if sanitize_text(understanding.get("skip_reason")) == "context_insufficient":
        return ContextSufficiencyResult(
            is_sufficient=False,
            reason="turn depends on missing conversation context",
            required_context_fields=("conversation_context",),
            missing_context_fields=("conversation_context",),
            has_product_context=has_product_context,
            has_order_context=has_order_context,
            has_media_context=has_media_context,
            should_count_in_agent_accuracy=False,
        )

    if actionability not in {"actionable_question", "deictic_followup", "media_reference"}:
        return ContextSufficiencyResult(
            is_sufficient=True,
            reason="turn does not require product/order identity",
            has_product_context=has_product_context,
            has_order_context=has_order_context,
            has_media_context=has_media_context,
            should_count_in_agent_accuracy=False,
        )

    required = _required_context_fields(fact_types)
    missing = []
    if "order_or_product" in required and not (has_order_context or has_product_context):
        missing.append("order_or_product")
    if "order" in required and not has_order_context:
        missing.append("order")
    if "product" in required and not (has_product_context or has_order_context):
        missing.append("product")

    if missing:
        return ContextSufficiencyResult(
            is_sufficient=False,
            reason=f"missing required replay context: {', '.join(missing)}",
            required_context_fields=tuple(sorted(required)),
            missing_context_fields=tuple(missing),
            has_product_context=has_product_context,
            has_order_context=has_order_context,
            has_media_context=has_media_context,
            should_count_in_agent_accuracy=False,
        )

    return ContextSufficiencyResult(
        is_sufficient=True,
        reason="required replay context is available",
        required_context_fields=tuple(sorted(required)),
        has_product_context=has_product_context,
        has_order_context=has_order_context,
        has_media_context=has_media_context,
        should_count_in_agent_accuracy=True,
    )


def _required_context_fields(fact_types: set[str]) -> set[str]:
    if fact_types & ORDER_FACT_TYPES:
        return {"order"}
    if fact_types & AFTERSALES_FACT_TYPES:
        return {"order_or_product"}
    if fact_types & PRODUCT_FACT_TYPES:
        return {"product"}
    return set()


def _has_product_context(summary: dict[str, Any], identity: dict[str, Any]) -> bool:
    return bool(
        summary.get("has_product_context")
        or summary.get("product_title_preview")
        or summary.get("item_id_masked")
        or identity.get("has_resolved_product_context")
        or identity.get("display_product_name")
        or identity.get("product_title")
        or identity.get("sku_code")
        or identity.get("i_id")
        or identity.get("item_id")
        or identity.get("product_url")
        or identity.get("product_candidates")
    )


def _has_order_context(summary: dict[str, Any], identity: dict[str, Any]) -> bool:
    return bool(
        summary.get("has_order_context")
        or summary.get("order_id_masked")
        or identity.get("order_id_hash")
        or identity.get("order_id_masked")
        or identity.get("order_product_title")
        or identity.get("order_sku_code")
    )
