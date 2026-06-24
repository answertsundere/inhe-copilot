"""Extract structured context from real conversation replay records."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from app.services.eval_sanitizer_service import hash_sensitive, sanitize_obj, sanitize_text
from app.services.real_context_product_identity_service import (
    build_real_context_product_identity,
)


URL_RE = re.compile(r"https?://[^\s\"'<>，。；、]+", re.I)
ORDER_ID_RE = re.compile(r"(?:订单号|订单|order[_\s-]*id|tid)[:：#\s]*([0-9]{8,})", re.I)
TRACKING_NO_RE = re.compile(r"(?:物流单号|快递单号|运单号|tracking[_\s-]*no)[:：#\s]*([A-Za-z0-9-]{8,})", re.I)
SKU_RE = re.compile(r"\b(?:sku|SKU|商品编码|货号|编码)[:：#\s]*([A-Za-z0-9_-]{4,64})")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".m4v", ".webm")


def empty_real_context() -> dict[str, Any]:
    return {
        "conversation_type": "unknown",
        "source_page": "unknown",
        "product": {
            "item_id": "",
            "item_id_hash": "",
            "item_id_masked": "",
            "product_url": "",
            "product_title": "",
            "sku_code": "",
            "sku_name": "",
            "i_id": "",
            "category": "",
        },
        "order": {
            "order_id": "",
            "order_id_hash": "",
            "order_id_masked": "",
            "tracking_no": "",
            "tracking_no_hash": "",
            "tracking_no_masked": "",
            "order_product_title": "",
            "order_sku_code": "",
            "order_sku_name": "",
        },
        "media": {
            "image_urls": [],
            "video_urls": [],
        },
        "raw_context_sources": [],
    }


def extract_real_context(text: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract product/order/media context without interpreting media contents."""
    metadata = metadata or {}
    raw_text = str(text or "")
    context = empty_real_context()
    sources: list[str] = []

    source_page = _detect_source_page(raw_text, metadata)
    if source_page != "unknown":
        context["source_page"] = source_page
        sources.append(f"source_page:{source_page}")

    product_title = _first_text(metadata, "product_title", "product_name", "item_title", "product_hint")
    if product_title:
        context["product"]["product_title"] = sanitize_text(product_title)[:255]
        sources.append("product_title")

    for url in URL_RE.findall(raw_text):
        _apply_url_context(context, url, sources, str(metadata.get("message_type") or ""))

    for key in ("product_url", "item_url", "url", "link", "media_url", "image_url", "video_url"):
        value = metadata.get(key)
        if value:
            for url in URL_RE.findall(str(value)):
                _apply_url_context(context, url, sources, str(metadata.get("message_type") or ""))

    sku_code = _first_match(SKU_RE, raw_text) or _first_text(metadata, "sku_code", "sku", "order_sku_code")
    if sku_code:
        context["product"]["sku_code"] = sanitize_text(sku_code)
        context["order"]["order_sku_code"] = sanitize_text(sku_code)
        sources.append("sku_code")

    order_id = _first_match(ORDER_ID_RE, raw_text) or _first_text(metadata, "order_id", "tid")
    if order_id:
        _set_sensitive_identifier(context["order"], "order_id", order_id)
        context["source_page"] = "order_detail" if context["source_page"] == "unknown" else context["source_page"]
        sources.append("order_id")

    tracking_no = _first_match(TRACKING_NO_RE, raw_text) or _first_text(metadata, "tracking_no", "logistics_no")
    if tracking_no:
        _set_sensitive_identifier(context["order"], "tracking_no", tracking_no)
        sources.append("tracking_no")

    order_product_title = _first_text(metadata, "order_product_title", "purchased_product_title")
    if order_product_title:
        context["order"]["order_product_title"] = sanitize_text(order_product_title)[:255]
        sources.append("order_product_title")

    context["conversation_type"] = _conversation_type_from_context(context)
    context["raw_context_sources"] = _dedupe(sources)
    return sanitize_obj(context)


def merge_real_context(base: dict[str, Any] | None, update: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(base) if isinstance(base, dict) else empty_real_context()
    incoming = update if isinstance(update, dict) else {}
    if not incoming:
        return sanitize_obj(merged)

    incoming_source = incoming.get("source_page")
    if incoming_source and incoming_source != "unknown" and (incoming_source != "chat" or merged.get("source_page") in {"", "unknown"}):
        merged["source_page"] = incoming["source_page"]
    if incoming.get("conversation_type") and incoming.get("conversation_type") != "unknown":
        merged["conversation_type"] = _merge_conversation_type(merged.get("conversation_type"), incoming.get("conversation_type"))

    for section in ("product", "order"):
        for key, value in (incoming.get(section) or {}).items():
            if value:
                merged.setdefault(section, {})[key] = value

    for kind in ("image_urls", "video_urls"):
        merged.setdefault("media", {}).setdefault(kind, [])
        for url in (incoming.get("media") or {}).get(kind) or []:
            if url and url not in merged["media"][kind]:
                merged["media"][kind].append(url)

    merged["raw_context_sources"] = _dedupe(
        list(merged.get("raw_context_sources") or []) + list(incoming.get("raw_context_sources") or [])
    )
    merged["conversation_type"] = _conversation_type_from_context(merged)
    return sanitize_obj(merged)


def summarize_real_context(context: dict[str, Any] | None) -> dict[str, Any]:
    value = context if isinstance(context, dict) else {}
    product = value.get("product") or {}
    order = value.get("order") or {}
    media = value.get("media") or {}
    item_id = product.get("item_id") or ""
    return sanitize_obj({
        "conversation_type": value.get("conversation_type") or "unknown",
        "source_page": value.get("source_page") or "unknown",
        "has_product_context": bool(product.get("product_title") or product.get("product_url") or item_id),
        "has_order_context": bool(order.get("order_id_hash") or order.get("order_id_masked") or order.get("order_product_title")),
        "has_media_context": bool(media.get("image_urls") or media.get("video_urls")),
        "product_title_preview": _preview(product.get("product_title") or order.get("order_product_title") or ""),
        "order_id_masked": order.get("order_id_masked") or "",
        "item_id_masked": product.get("item_id_masked") or _mask_identifier(item_id),
        "context_sources": list(value.get("raw_context_sources") or []),
    })


def build_agent_context_from_real_context(context: dict[str, Any] | None) -> dict[str, Any]:
    value = context if isinstance(context, dict) else {}
    product = value.get("product") or {}
    order = value.get("order") or {}
    media = value.get("media") or {}
    summary = summarize_real_context(value)
    agent_context = {
        "conversation_type": value.get("conversation_type") or "unknown",
        "source_page": value.get("source_page") or "unknown",
        "real_context": value,
        "product_name": product.get("product_title") or order.get("order_product_title") or "",
        "product_title": product.get("product_title") or "",
        "item_id": product.get("item_id") or "",
        "item_id_hash": product.get("item_id_hash") or "",
        "product_url": product.get("product_url") or "",
        "sku_code": product.get("sku_code") or order.get("order_sku_code") or "",
        "order_id": order.get("order_id") or "",
        "order_id_hash": order.get("order_id_hash") or "",
        "order_id_masked": order.get("order_id_masked") or "",
        "tracking_no": order.get("tracking_no") or "",
        "tracking_no_hash": order.get("tracking_no_hash") or "",
        "tracking_no_masked": order.get("tracking_no_masked") or "",
        "order_product_title": order.get("order_product_title") or "",
        "order_sku_code": order.get("order_sku_code") or "",
        "order_sku_name": order.get("order_sku_name") or "",
        "media_context": {
            "image_urls": list(media.get("image_urls") or []),
            "video_urls": list(media.get("video_urls") or []),
        },
        "real_context_summary": summary,
    }
    agent_context["real_context_product_identity"] = build_real_context_product_identity(agent_context)
    return sanitize_obj(agent_context)


def product_candidates_from_real_context(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    agent_context = build_agent_context_from_real_context(context)
    identity = agent_context.get("real_context_product_identity") or {}
    return list(identity.get("product_candidates") or [])


def _apply_url_context(context: dict[str, Any], url: str, sources: list[str], message_type: str = "") -> None:
    sanitized_url = _sanitize_context_url(url)
    host = urlsplit(url).netloc.lower()
    path = urlsplit(url).path.lower()
    query = parse_qs(urlsplit(url).query)
    if "item.taobao.com" in host or "detail.tmall.com" in host:
        item_id = (query.get("id") or [""])[0]
        context["source_page"] = "product_detail"
        context["product"]["product_url"] = sanitized_url
        if item_id:
            context["product"]["item_id"] = item_id
            context["product"]["item_id_hash"] = hash_sensitive(item_id)
            context["product"]["item_id_masked"] = _mask_identifier(item_id)
        sources.append("product_url")
        return
    if _looks_like_video(url, message_type):
        _append_unique(context["media"]["video_urls"], sanitized_url)
        sources.append("media_url:video")
        return
    if _looks_like_image(url, message_type) or path:
        _append_unique(context["media"]["image_urls"], sanitized_url)
        sources.append("media_url:image")


def _sanitize_context_url(raw_url: str) -> str:
    try:
        parts = urlsplit(raw_url)
    except Exception:
        return "[URL_REDACTED]"
    query = parse_qs(parts.query, keep_blank_values=False)
    if "item.taobao.com" in parts.netloc.lower() or "detail.tmall.com" in parts.netloc.lower():
        safe_query = {}
        if query.get("id"):
            safe_query["id"] = query["id"][0]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _detect_source_page(text: str, metadata: dict[str, Any]) -> str:
    combined = " ".join(str(x or "") for x in [
        text,
        metadata.get("source_page"),
        metadata.get("page"),
        metadata.get("page_type"),
        metadata.get("context"),
    ])
    lowered = combined.lower()
    if "product_detail" in lowered or "商品详情" in combined or "item.taobao.com" in lowered or "detail.tmall.com" in lowered:
        return "product_detail"
    if "order_detail" in lowered or "订单" in combined or ORDER_ID_RE.search(combined):
        return "order_detail"
    if combined.strip():
        return "chat"
    return "unknown"


def _conversation_type_from_context(context: dict[str, Any]) -> str:
    has_product = bool((context.get("product") or {}).get("product_url") or (context.get("product") or {}).get("product_title"))
    has_order = bool((context.get("order") or {}).get("order_id_hash") or (context.get("order") or {}).get("order_product_title"))
    if has_product and has_order:
        return "mixed"
    if has_order or context.get("source_page") == "order_detail":
        return "aftersales"
    if has_product or context.get("source_page") == "product_detail":
        return "presales"
    return "unknown"


def _merge_conversation_type(left: str | None, right: str | None) -> str:
    left = left or "unknown"
    right = right or "unknown"
    if left == right:
        return left
    if left == "unknown":
        return right
    if right == "unknown":
        return left
    return "mixed"


def _set_sensitive_identifier(target: dict[str, Any], key: str, raw: str) -> None:
    value = str(raw or "").strip()
    if not value:
        return
    target[key] = _mask_identifier(value)
    target[f"{key}_hash"] = hash_sensitive(value)
    target[f"{key}_masked"] = _mask_identifier(value)


def _mask_identifier(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return f"***{text[-4:]}"
    return f"{text[:3]}***{text[-4:]}"


def _preview(value: str, limit: int = 60) -> str:
    text = sanitize_text(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _first_text(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value:
            return str(value)
    return ""


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(str(text or ""))
    return match.group(1) if match else ""


def _looks_like_image(url: str, message_type: str = "") -> bool:
    lowered = (url + " " + message_type).lower()
    return any(ext in lowered for ext in IMAGE_EXTENSIONS) or "image" in lowered or "图片" in message_type


def _looks_like_video(url: str, message_type: str = "") -> bool:
    lowered = (url + " " + message_type).lower()
    if any(ext in url.lower() for ext in IMAGE_EXTENSIONS):
        return False
    return any(ext in url.lower() for ext in VIDEO_EXTENSIONS) or "video" in lowered or "视频" in message_type


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
