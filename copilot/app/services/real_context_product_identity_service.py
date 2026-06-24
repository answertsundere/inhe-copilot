"""Bridge real-conversation context into product identity and media trace data."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


INTERNAL_PRODUCT_CODE_RE = re.compile(r"^YH[A-Za-z0-9_-]{4,40}$", re.I)
SKU_FAMILY_RE = re.compile(r"^(YH\d+K\d+)", re.I)


def build_real_context_product_identity(copilot_context: dict[str, Any] | None) -> dict[str, Any]:
    """Build normalized product identity candidates from real replay context.

    The output is intentionally candidate-based. It gives existing resolver and
    product-card code more product signals without declaring that a platform
    item id or URL is already a verified internal product id.
    """
    ctx = copilot_context if isinstance(copilot_context, dict) else {}
    real_context = ctx.get("real_context") if isinstance(ctx.get("real_context"), dict) else {}
    product = real_context.get("product") if isinstance(real_context.get("product"), dict) else {}
    order = real_context.get("order") if isinstance(real_context.get("order"), dict) else {}

    product_title = _first_text(
        product.get("product_title"),
        ctx.get("product_title"),
        ctx.get("platform_product_title"),
        ctx.get("front_product_title"),
        ctx.get("item_title"),
        ctx.get("product_name"),
    )
    order_product_title = _first_text(
        order.get("order_product_title"),
        ctx.get("order_product_title"),
    )
    sku_code = _first_text(
        product.get("sku_code"),
        order.get("order_sku_code"),
        ctx.get("sku_code"),
        ctx.get("order_sku_code"),
    )
    item_id = _first_text(product.get("item_id"), ctx.get("item_id"))
    product_url = _first_text(product.get("product_url"), ctx.get("product_url"))
    i_id = _first_text(product.get("i_id"), ctx.get("i_id"))

    candidates: list[dict[str, Any]] = []
    sources: list[str] = []

    if sku_code:
        _add_candidate(candidates, "sku_code", sku_code, "real_context.sku_code", sku_code=sku_code)
        sources.append("sku_code")
        family = _sku_family(sku_code)
        if family:
            _add_candidate(candidates, "i_id", family, "real_context.sku_family", i_id=family)
    if i_id:
        _add_candidate(candidates, "i_id", i_id, "real_context.i_id", i_id=i_id)
        sources.append("i_id")
    if item_id:
        if _looks_like_internal_product_code(item_id):
            _add_candidate(candidates, "i_id", item_id, "real_context.item_id", i_id=item_id, item_id=item_id)
        else:
            _add_candidate(candidates, "platform_product_id", item_id, "real_context.item_id", item_id=item_id)
        sources.append("item_id")
    if product_url:
        _add_candidate(candidates, "product_url", product_url, "real_context.product_url", product_url=product_url)
        sources.append("product_url")
    if product_title:
        _add_candidate(candidates, "product_title", product_title, "real_context.product_title", product_name=product_title)
        sources.append("product_title")
    if order_product_title and order_product_title != product_title:
        _add_candidate(
            candidates,
            "order_product_title",
            order_product_title,
            "real_context.order_product_title",
            product_name=order_product_title,
        )
        sources.append("order_product_title")

    display_name = product_title or order_product_title or ""
    identity = {
        "identity_sources": _dedupe(sources),
        "product_candidates": candidates,
        "display_product_name": display_name,
        "sku_code": sku_code,
        "i_id": i_id or _sku_family(sku_code),
        "item_id": item_id,
        "product_url": product_url,
        "product_title": product_title,
        "order_product_title": order_product_title,
        "has_resolved_product_context": bool(candidates or display_name),
    }
    return sanitize_obj(identity)


def build_conversation_media_reference(copilot_context: dict[str, Any] | None) -> dict[str, Any]:
    """Return historical chat media references without promoting them to assets."""
    ctx = copilot_context if isinstance(copilot_context, dict) else {}
    real_context = ctx.get("real_context") if isinstance(ctx.get("real_context"), dict) else {}
    real_media = real_context.get("media") if isinstance(real_context.get("media"), dict) else {}
    media_context = ctx.get("media_context") if isinstance(ctx.get("media_context"), dict) else {}
    image_urls = _dedupe([
        *[str(x) for x in (real_media.get("image_urls") or []) if x],
        *[str(x) for x in (media_context.get("image_urls") or []) if x],
    ])
    video_urls = _dedupe([
        *[str(x) for x in (real_media.get("video_urls") or []) if x],
        *[str(x) for x in (media_context.get("video_urls") or []) if x],
    ])
    return sanitize_obj({
        "evidence_role": "conversation_media_reference",
        "sendable": False,
        "image_urls": image_urls,
        "video_urls": video_urls,
        "media_context_count": len(image_urls) + len(video_urls),
        "rejected_media_reason": (
            "historical_conversation_media_is_not_sendable_asset"
            if image_urls or video_urls else ""
        ),
    })


def augment_copilot_context_with_real_identity(copilot_context: dict[str, Any] | None) -> dict[str, Any]:
    """Add normalized real-context identity and media reference to copilot context."""
    ctx = deepcopy(copilot_context) if isinstance(copilot_context, dict) else {}
    identity = build_real_context_product_identity(ctx)
    media_ref = build_conversation_media_reference(ctx)
    merged_candidates = merge_product_candidates(
        ctx.get("product_candidates") if isinstance(ctx.get("product_candidates"), list) else [],
        identity.get("product_candidates") or [],
    )
    if merged_candidates:
        ctx["product_candidates"] = merged_candidates
    if identity.get("display_product_name"):
        ctx.setdefault("display_product_name", identity["display_product_name"])
        ctx.setdefault("platform_product_title", identity["display_product_name"])
        ctx.setdefault("product_name", identity["display_product_name"])
    if identity.get("sku_code"):
        ctx.setdefault("sku_code", identity["sku_code"])
    if identity.get("i_id") and _looks_like_internal_product_code(identity["i_id"]):
        ctx.setdefault("i_id", identity["i_id"])
    ctx["real_context_product_identity"] = identity
    ctx["conversation_media_reference"] = media_ref
    return sanitize_obj(ctx)


def augment_state_with_real_context_identity(state: dict[str, Any]) -> dict[str, Any]:
    """Mutate a graph state with normalized real-context identity fields."""
    ctx = augment_copilot_context_with_real_identity(state.get("copilot_context") or {})
    state["copilot_context"] = ctx
    identity = ctx.get("real_context_product_identity") or {}
    state["real_context_product_identity"] = identity
    state["conversation_media_reference"] = ctx.get("conversation_media_reference") or {}
    state["product_candidates"] = merge_product_candidates(
        state.get("product_candidates") if isinstance(state.get("product_candidates"), list) else [],
        ctx.get("product_candidates") if isinstance(ctx.get("product_candidates"), list) else [],
    )
    slots = dict(state.get("slots") or {})
    if identity.get("display_product_name") and not state.get("matched_product_name"):
        state["matched_product_name"] = identity["display_product_name"]
    if identity.get("display_product_name") and not slots.get("product_name"):
        slots["product_name"] = identity["display_product_name"]
    if identity.get("sku_code") and not slots.get("sku_code"):
        slots["sku_code"] = identity["sku_code"]
    if identity.get("i_id") and _looks_like_internal_product_code(identity["i_id"]) and not slots.get("i_id"):
        slots["i_id"] = identity["i_id"]
    if slots:
        state["slots"] = slots
    state.setdefault("trace_steps", []).append({
        "node": "real_context_product_identity",
        "status": "resolved" if identity.get("has_resolved_product_context") else "empty",
        "identity_sources": identity.get("identity_sources", []),
        "product_candidates_count": len(identity.get("product_candidates") or []),
        "media_context_count": (ctx.get("conversation_media_reference") or {}).get("media_context_count", 0),
        "summary": "real conversation context normalized for product/media evidence",
    })
    return state


def merge_product_candidates(*candidate_lists: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidates in candidate_lists:
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            candidate_type = str(candidate.get("type") or "").strip()
            value = str(candidate.get("value") or candidate.get("product_name") or candidate.get("title") or "").strip()
            if not value:
                continue
            key = (candidate_type.lower(), value)
            if key in seen:
                continue
            seen.add(key)
            merged.append(sanitize_obj(dict(candidate)))
    return merged


def _add_candidate(candidates: list[dict[str, Any]], candidate_type: str, value: str, source: str, **extra: Any) -> None:
    text = sanitize_text(value).strip()
    if not text:
        return
    candidate = {
        "type": candidate_type,
        "value": text,
        "source": source,
        **{k: v for k, v in extra.items() if v},
    }
    if candidate_type in {"product_title", "order_product_title"}:
        candidate.setdefault("product_name", text)
        candidate.setdefault("title", text)
    if candidate_type == "sku_code":
        candidate.setdefault("sku_code", text)
    if candidate_type == "i_id":
        candidate.setdefault("i_id", text)
    candidates.append(candidate)


def _looks_like_internal_product_code(value: str) -> bool:
    return bool(INTERNAL_PRODUCT_CODE_RE.match(str(value or "").strip()))


def _sku_family(value: str) -> str:
    match = SKU_FAMILY_RE.match(str(value or "").strip())
    return match.group(1).upper() if match else ""


def _first_text(*values: Any) -> str:
    for value in values:
        text = sanitize_text(str(value or "")).strip()
        if text:
            return text
    return ""


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
