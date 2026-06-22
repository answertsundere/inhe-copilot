"""LLM-first semantic classifier for the current customer question.

This module decides what fact field the customer is actually asking for. It is
not a reply generator and it must not choose evidence by keyword alone.
Deterministic rules are kept only as a fallback when the LLM is unavailable or
returns an unusably low-confidence result.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app import config
from app.llm.client import get_llm_client
from app.services.fact_type_service import FACT_TYPE_LABELS, classify_query_fact_type

logger = logging.getLogger(__name__)


ALLOWED_FACT_TYPES = set(FACT_TYPE_LABELS)

HIGH_RISK_BOUNDARY_TYPES = {
    "certification_report",
    "pinch_safety",
    "safety_small_parts",
    "stability",
    "aftersales_policy",
    "invoice_policy",
    "price_protection",
}

SYSTEM_PROMPT = """
You are the semantic question classifier for INHE customer-service Copilot.

Your only job is to identify what the customer is truly asking in the current
turn. Do not answer the customer. Do not select a canned response. Do not rely
on a single keyword when the whole sentence implies a different meaning.

Return JSON only.

Allowed query_fact_type values:
- material: material, material safety, environmental material, water resistance
- certification_report: test report, certificate, 3C, formaldehyde, compliance proof
- load_capacity: load bearing, how much weight it can hold, whether shelves bend
- stability: anti-tip, whether it will fall, stability when children touch it
- dimensions: exact size, length/width/height, specification image
- space_fit: whether it fits a room/space, how much space is needed, small bedroom, square meters, reserved width/depth/height
- placement_scene: whether it can be used in bedroom/living room/study/kitchen/balcony/bathroom, suitable placement scene
- age_range: suitable age or baby age range
- cleaning_care: cleaning, washing, wiping, maintenance
- odor: smell, odor, new-product smell, pungent smell, ventilation
- visual_asset: product image, real-item photo, display picture, visual reference without a more specific dimension/install/accessory request
- installation: installation, assembly, drilling, instruction manual, installation video
- detachable: detachable, can be disassembled, removable
- variant_compare: difference between versions/styles, which version is better
- stock_shipping: stock, shipping time, dispatch
- invoice_policy: invoice, title, tax number
- price_protection: price protection, bought expensive, price drop
- promotion_policy: coupon, discount, campaign, activity
- gift_policy: gift, freebie, missing gift
- pinch_safety: pinch hands, anti-pinch, structural safety around fingers
- safety_small_parts: small parts, battery, swallowing/choking risk
- aftersales_policy: return, refund, replacement, reissue, damaged, missing parts, wrong item

Semantic boundaries:
- If the customer asks "can it fit", "is my room enough", "small bedroom", or "how much space is needed", classify as space_fit. Do not classify as load_capacity.
- If the customer asks "can it be used/placed in bedroom/living room/study/etc.", classify as placement_scene. Do not classify as material just because an evidence sentence mentions material.
- If the customer asks "material has smell?" or "does it smell?", classify as odor, with material as secondary if useful.
- If the customer asks about safety promises, formaldehyde, certificates, baby injury, pinching, swallowing, aftersales, invoice, or price protection, keep the high-risk/compliance boundary clear.
- Use secondary_fact_types for related but non-primary needs.

Schema:
{
  "query_fact_type": "",
  "confidence": 0.0,
  "risk_hint": "low|medium|high",
  "secondary_fact_types": [],
  "needs_visual_asset": false,
  "visual_asset_reason": "",
  "retrieval_focus": "short phrase describing what evidence should be retrieved",
  "reason": "short reason"
}
"""


def classify_query_fact_type_llm_first(state: dict[str, Any]) -> dict[str, Any]:
    """Classify the current question with LLM as the primary decision maker."""

    message = state.get("normalized_message", state.get("customer_message", "")) or ""
    intent = state.get("intent", "general") or "general"
    deterministic = classify_query_fact_type(message, intent)

    llm_result: dict[str, Any] | None = None
    if config.COPILOT_FACT_TYPE_LLM_ENABLED:
        llm_result = _classify_with_llm(state, message, intent)

    if _is_usable_llm_result(llm_result):
        guarded = _semantic_consistency_guard(deterministic, llm_result)
        if guarded:
            guarded = _normalize_baby_safety_secondary(guarded, message)
            guarded["semantic_query"] = _semantic_query_from_result(guarded, message)
            return guarded
        result = dict(llm_result)
        result["deterministic_hint"] = _compact_hint(deterministic)
        result = _normalize_baby_safety_secondary(result, message)
        result["semantic_query"] = _semantic_query_from_result(result, message)
        return result

    fallback = _fallback_from_rule(deterministic, llm_result)
    fallback = _normalize_baby_safety_secondary(fallback, message)
    fallback["semantic_query"] = _semantic_query_from_result(fallback, message)
    return fallback


def _is_usable_llm_result(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    fact_type = str(result.get("query_fact_type") or "")
    confidence = float(result.get("confidence") or 0)
    if fact_type and confidence >= 0.55:
        return True
    return not fact_type and confidence >= 0.4


def _fallback_from_rule(deterministic: dict[str, Any], llm_result: dict[str, Any] | None) -> dict[str, Any]:
    fallback = dict(deterministic or {})
    fallback["source"] = "rule_fallback"
    fallback["fallback_reason"] = "llm_unavailable_or_low_confidence"
    if llm_result:
        fallback["llm_low_confidence_result"] = {
            "query_fact_type": llm_result.get("query_fact_type", ""),
            "confidence": llm_result.get("confidence", 0),
            "reason": llm_result.get("reason", ""),
        }
    fact_type = str(fallback.get("query_fact_type") or "")
    if fact_type in HIGH_RISK_BOUNDARY_TYPES:
        fallback["risk_hint"] = fallback.get("risk_hint") or "high"
    else:
        fallback.setdefault("risk_hint", "")
    fallback.setdefault("secondary_fact_types", [])
    fallback.setdefault("reason", fallback.get("fallback_reason", ""))
    fallback.setdefault("needs_visual_asset", _visual_need_for_fact_type(fact_type))
    fallback.setdefault("visual_asset_reason", "")
    fallback.setdefault("retrieval_focus", _retrieval_focus_for_fact_type(fact_type))
    return fallback


def _semantic_consistency_guard(
    deterministic: dict[str, Any],
    llm_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prevent a clearly off-topic LLM classification from poisoning retrieval.

    This is a consistency guard, not the primary router. It only activates when
    the fallback semantic channel has a high-confidence category and the LLM
    chooses a fact type that would retrieve a mutually incompatible evidence
    family, such as answering a size/installation/material question with load
    capacity.
    """

    if not llm_result:
        return None
    rule_type = str(deterministic.get("query_fact_type") or "")
    llm_type = str(llm_result.get("query_fact_type") or "")
    if not rule_type or not llm_type or rule_type == llm_type:
        return None
    if float(deterministic.get("confidence") or 0) < 0.75:
        return None
    if float(llm_result.get("confidence") or 0) < 0.55:
        return None

    incompatible = {
        "material": {"load_capacity", "installation", "dimensions"},
        "installation": {"load_capacity", "material", "dimensions"},
        "dimensions": {"load_capacity", "material", "installation"},
        "space_fit": {"load_capacity", "material", "installation", "placement_scene"},
        "placement_scene": {"load_capacity", "material", "installation"},
        "odor": {"load_capacity", "installation", "dimensions"},
        "pinch_safety": {"load_capacity", "material", "installation", "safety_small_parts"},
        "safety_small_parts": {"load_capacity", "material", "installation", "pinch_safety"},
        "aftersales_policy": {"installation", "load_capacity", "material"},
    }
    if llm_type not in incompatible.get(rule_type, set()):
        return None

    guarded = dict(deterministic)
    guarded["source"] = "semantic_consistency_guard"
    guarded["reason"] = "LLM classification conflicts with a high-confidence semantic guard"
    guarded["llm_rejected_fact_type"] = llm_type
    guarded["llm_rejected_confidence"] = llm_result.get("confidence", 0)
    guarded["secondary_fact_types"] = [
        item
        for item in list(dict.fromkeys(llm_result.get("secondary_fact_types") or []))
        if item not in {rule_type, llm_type}
    ][:5]
    fact_type = str(guarded.get("query_fact_type") or "")
    guarded["needs_visual_asset"] = _visual_need_for_fact_type(fact_type)
    guarded["retrieval_focus"] = _retrieval_focus_for_fact_type(fact_type)
    return guarded


def _classify_with_llm(state: dict[str, Any], message: str, intent: str) -> dict[str, Any] | None:
    client = get_llm_client()
    if hasattr(client, "is_configured"):
        if not client.is_configured("fast_model"):
            return None
    elif not getattr(client, "api_key", ""):
        return None

    payload = {
        "customer_message": message,
        "current_intent": intent,
        "risk_level": state.get("risk_level", ""),
        "resolved_product": state.get("resolved_product") or state.get("matched_product") or {},
        "product_name": state.get("product_name", ""),
        "product_candidates": state.get("product_candidates", [])[:5],
        "has_order_identifier": bool(state.get("order_id") or state.get("platform_order_id")),
        "conversation_context_summary": state.get("conversation_context_summary", {}),
        "deterministic_hint_for_reference_only": _compact_hint(classify_query_fact_type(message, intent)),
    }

    try:
        if hasattr(client, "chat_completion"):
            response = client.chat_completion(
                model_alias="fast_model",
                node_name="semantic_fact_type_classifier",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=360,
                response_format={"type": "json_object"},
            )
        else:
            response = client.client.chat.completions.create(
                model=client.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=360,
                response_format={"type": "json_object"},
            )
        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return _sanitize_llm_result(parsed)
    except Exception as exc:
        logger.warning("LLM fact type classifier failed, using fallback: %s", exc)
        return None


def _sanitize_llm_result(data: dict[str, Any]) -> dict[str, Any] | None:
    fact_type = str(data.get("query_fact_type") or data.get("fact_type") or "").strip()
    if fact_type and fact_type not in ALLOWED_FACT_TYPES:
        fact_type = ""

    try:
        confidence = float(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    risk_hint = str(data.get("risk_hint") or data.get("risk_level") or "").strip().lower()
    if risk_hint not in {"low", "medium", "high"}:
        risk_hint = ""
    if fact_type in HIGH_RISK_BOUNDARY_TYPES and not risk_hint:
        risk_hint = "high"

    secondary = data.get("secondary_fact_types") or []
    if not isinstance(secondary, list):
        secondary = []
    secondary = [str(item) for item in secondary if str(item) in ALLOWED_FACT_TYPES and str(item) != fact_type]

    needs_visual_asset = bool(data.get("needs_visual_asset"))
    if not needs_visual_asset:
        needs_visual_asset = _visual_need_for_fact_type(fact_type)

    return {
        "query_fact_type": fact_type,
        "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
        "confidence": confidence,
        "matched_terms": [],
        "source": "llm",
        "reason": str(data.get("reason", ""))[:300],
        "risk_hint": risk_hint,
        "secondary_fact_types": secondary[:5],
        "needs_visual_asset": needs_visual_asset,
        "visual_asset_reason": str(data.get("visual_asset_reason", ""))[:200],
        "retrieval_focus": str(data.get("retrieval_focus", ""))[:200] or _retrieval_focus_for_fact_type(fact_type),
    }


def _semantic_query_from_result(result: dict[str, Any], message: str) -> dict[str, Any]:
    fact_type = str(result.get("query_fact_type") or "")
    return {
        "current_query": message,
        "primary_fact_type": fact_type,
        "secondary_fact_types": result.get("secondary_fact_types") or [],
        "retrieval_focus": result.get("retrieval_focus") or _retrieval_focus_for_fact_type(fact_type),
        "needs_visual_asset": bool(result.get("needs_visual_asset") or _visual_need_for_fact_type(fact_type)),
        "source": result.get("source", ""),
        "confidence": float(result.get("confidence") or 0),
        "reason": result.get("reason", ""),
    }


def _normalize_baby_safety_secondary(result: dict[str, Any], message: str) -> dict[str, Any]:
    """Treat "宝宝/孩子能用吗" as material safety, not age range.

    Age range remains valid when the customer asks actual age/month cues. This
    only fixes mixed questions such as safety + shipping.
    """
    text = message or ""
    asks_baby_use_safety = any(
        cue in text
        for cue in ("宝宝能用", "孩子能用", "小孩能用", "宝宝用安全吗", "孩子用安全吗", "宝宝用", "孩子用")
    ) or ("宝宝" in text and "安全" in text)
    asks_age = any(
        cue in text
        for cue in ("适合多大", "适合几岁", "多大宝宝", "几个月", "月龄", "半岁", "一岁", "两岁", "三岁", "岁宝宝")
    )
    if not asks_baby_use_safety or asks_age:
        return result

    normalized = dict(result)
    primary = str(normalized.get("query_fact_type") or "")
    secondary = [
        str(item)
        for item in normalized.get("secondary_fact_types", []) or []
        if str(item) and str(item) != primary
    ]
    secondary = [item for item in secondary if item != "age_range"]
    if primary == "age_range":
        normalized["query_fact_type"] = "material"
        normalized["query_fact_type_label"] = FACT_TYPE_LABELS.get("material", "material")
        primary = "material"
    elif primary != "material" and "material" not in secondary:
        secondary.insert(0, "material")
    normalized["secondary_fact_types"] = secondary[:5]
    normalized["reason"] = (normalized.get("reason") or "") + " normalized_baby_use_as_material_safety"
    return normalized


def _compact_hint(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_fact_type": result.get("query_fact_type", ""),
        "confidence": result.get("confidence", 0),
        "matched_terms": result.get("matched_terms", []),
        "source": result.get("source", ""),
    }


def _visual_need_for_fact_type(fact_type: str) -> bool:
    return fact_type in {
        "dimensions",
        "space_fit",
        "detachable",
        "installation",
        "accessories",
        "gift_policy",
        "visual_asset",
    }


def _retrieval_focus_for_fact_type(fact_type: str) -> str:
    return {
        "space_fit": "product dimensions, size image, reserved width/depth/height, room fit",
        "placement_scene": "suitable placement scene and usage environment",
        "dimensions": "product dimensions and size image",
        "installation": "installation method, guide image or video",
        "detachable": "detachable structure and related size/install image",
        "odor": "new product smell and ventilation guidance",
        "material": "product material and verified material notes",
        "load_capacity": "load capacity and what items can be placed",
        "visual_asset": "approved product images or videos for the current item",
    }.get(fact_type, fact_type)
