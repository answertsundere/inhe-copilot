"""Persistent tool call audit ledger with privacy-safe summaries."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

_TABLE_READY = False

SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "access_token", "token", "secret", "app_secret",
    "phone", "mobile", "address", "id_card", "identity_no", "receiver", "recipient",
    "customer_message", "message", "normalized_message", "raw", "prompt", "messages",
    "base64", "image_b64", "data_url", "image_url", "url", "asset_url", "media_url",
    "oss_url", "signed_url",
}


def record_tool_call(
    *,
    trace_id: str = "",
    conversation_id: str = "",
    request_id: str = "",
    node_name: str = "tool_executor",
    tool_name: str = "",
    tool_risk_level: str = "",
    intent: str = "",
    query_fact_type: str = "",
    allowed: bool = False,
    blocked_reason: str = "",
    status: str = "",
    error_type: str = "",
    error_message: str = "",
    latency_ms: int = 0,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    entity_summary: dict[str, Any] | None = None,
    evidence_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        _ensure_table()
        from app.db import SessionLocal
        from app.models.tool_call_log import ToolCallLog

        db = SessionLocal()
        try:
            row = ToolCallLog(
                trace_id=str(trace_id or "")[:64],
                conversation_id=str(conversation_id or "")[:128],
                request_id=str(request_id or "")[:128],
                node_name=str(node_name or "")[:128],
                tool_name=str(tool_name or "")[:128],
                tool_risk_level=str(tool_risk_level or "")[:64],
                intent=str(intent or "")[:64],
                query_fact_type=str(query_fact_type or "")[:64],
                allowed=bool(allowed),
                blocked_reason=str(blocked_reason or "")[:255],
                status=str(status or "")[:32],
                error_type=str(error_type or "")[:128],
                error_message=str(error_message or "")[:500],
                latency_ms=max(0, int(latency_ms or 0)),
                input_summary_json=_json_summary(input_summary or {}),
                output_summary_json=_json_summary(output_summary or {}),
                entity_summary_json=_json_summary(entity_summary or {}),
                evidence_summary_json=_json_summary(evidence_summary or {}),
            )
            db.add(row)
            db.commit()
            return {"ledger_recorded": True, "ledger_id": row.id}
        finally:
            db.close()
    except Exception as exc:
        return {"ledger_recorded": False, "ledger_error": type(exc).__name__}


def sanitize_summary(value: Any, *, max_items: int = 6) -> Any:
    if isinstance(value, dict):
        safe = {}
        for key, item in list(value.items())[:max_items]:
            key_text = str(key)
            if _blocked_key(key_text):
                continue
            safe[key_text] = sanitize_summary(item, max_items=max_items)
        return safe
    if isinstance(value, (list, tuple, set)):
        items = [sanitize_summary(item, max_items=max_items) for item in list(value)[:max_items]]
        if len(value) > max_items:
            items.append(f"{len(value) - max_items} more")
        return items
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize_text(str(value))


def summarize_entities(context: dict[str, Any]) -> dict[str, Any]:
    slots = context.get("slots") if isinstance(context.get("slots"), dict) else {}
    return sanitize_summary({
        "intent": context.get("intent") or context.get("final_intent") or "",
        "query_fact_type": context.get("query_fact_type") or "",
        "product_entities_count": len(context.get("product_entities") or []),
        "order_entities_count": len(context.get("order_entities") or []),
        "has_product_name": bool(context.get("matched_product_name") or slots.get("product_name")),
        "order_id": context.get("order_id") or slots.get("order_id") or slots.get("possible_numeric_id") or "",
        "platform_trade_id": context.get("platform_trade_id") or slots.get("platform_trade_id") or "",
        "tracking_no": context.get("tracking_no") or slots.get("tracking_no") or "",
    })


def summarize_evidence(result: dict[str, Any] | None) -> dict[str, Any]:
    result = result or {}
    return sanitize_summary({
        "found": result.get("found"),
        "count": result.get("count"),
        "chunks_count": len(result.get("chunks") or []) if isinstance(result.get("chunks"), list) else 0,
        "assets_count": len(result.get("recommended_assets") or []) if isinstance(result.get("recommended_assets"), list) else 0,
        "endpoint": result.get("endpoint", ""),
        "safe_fallback_reason": result.get("safe_fallback_reason", ""),
    })


def _ensure_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    from app import db as db_module
    from app.models.tool_call_log import ToolCallLog

    db_module.Base.metadata.create_all(bind=db_module.engine, tables=[ToolCallLog.__table__])
    _TABLE_READY = True


def _json_summary(value: Any) -> str:
    return json.dumps(sanitize_summary(value), ensure_ascii=False, sort_keys=True)


def _blocked_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(marker in lowered for marker in ("token", "secret", "authorization", "base64"))


def _sanitize_text(value: str) -> str:
    text = str(value or "")
    if _looks_like_url(text):
        parsed = urlparse(text)
        return f"url_host:{parsed.netloc or parsed.path.split('/')[0]}"
    text = re.sub(r"\b\d{8,}\b", _mask_long_number, text)
    text = re.sub(r"data:[^,\s]+,[-A-Za-z0-9+/=]+", "[base64_redacted]", text)
    if len(text) > 120:
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{text[:80]}...#{digest}"
    return text


def _mask_long_number(match: re.Match) -> str:
    value = match.group(0)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"***{value[-4:]}#{digest}"


def _looks_like_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "oss://")) or "signature=" in lowered
