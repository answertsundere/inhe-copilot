"""Model call cost ledger.

The ledger records routing metadata, token usage, latency, and estimated cost.
It never stores API keys or full sensitive URLs.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

_TABLE_READY = False


def record_model_call(
    *,
    trace_id: str = "",
    conversation_id: str = "",
    request_id: str = "",
    node_name: str = "",
    alias: str = "",
    provider: str = "",
    model: str = "",
    api_base: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "success",
    error_type: str = "",
    error_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = _sanitize_metadata(metadata or {})
    estimate = estimate_cost(provider, model, prompt_tokens, completion_tokens)
    if estimate["cost_unknown"]:
        metadata["cost_unknown"] = True
    api_base_host = _api_base_host(api_base)
    try:
        _ensure_table()
        from app.db import SessionLocal
        from app.models.model_call_log import ModelCallLog

        db = SessionLocal()
        try:
            row = ModelCallLog(
                trace_id=str(trace_id or ""),
                conversation_id=str(conversation_id or ""),
                request_id=str(request_id or ""),
                node_name=str(node_name or ""),
                alias=str(alias or ""),
                provider=str(provider or ""),
                model=str(model or ""),
                api_base_host=api_base_host,
                prompt_tokens=max(0, int(prompt_tokens or 0)),
                completion_tokens=max(0, int(completion_tokens or 0)),
                total_tokens=max(0, int(total_tokens or 0)),
                estimated_cost=float(estimate["estimated_cost"]),
                currency=str(estimate["currency"]),
                latency_ms=max(0, int(latency_ms or 0)),
                status=str(status or ""),
                error_type=str(error_type or "")[:128],
                error_message=str(error_message or "")[:500],
                metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            )
            db.add(row)
            db.commit()
            return {
                "ledger_recorded": True,
                "ledger_id": row.id,
                "estimated_cost": row.estimated_cost,
                "currency": row.currency,
                "cost_unknown": bool(metadata.get("cost_unknown")),
                "api_base_host": api_base_host,
            }
        finally:
            db.close()
    except Exception as exc:
        return {
            "ledger_recorded": False,
            "ledger_error": type(exc).__name__,
            "estimated_cost": float(estimate["estimated_cost"]),
            "currency": str(estimate["currency"]),
            "cost_unknown": bool(metadata.get("cost_unknown")),
            "api_base_host": api_base_host,
        }


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> dict[str, Any]:
    """Return a conservative cost estimate.

    Unknown provider/model prices are allowed and return zero with
    ``cost_unknown=true``. We do not invent prices.
    """
    return {
        "estimated_cost": 0.0,
        "currency": "USD",
        "cost_unknown": True,
    }


def _ensure_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    from app import db as db_module
    from app.models.model_call_log import ModelCallLog

    db_module.Base.metadata.create_all(bind=db_module.engine, tables=[ModelCallLog.__table__])
    _TABLE_READY = True


def _api_base_host(api_base: str) -> str:
    value = str(api_base or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.netloc:
        return parsed.netloc
    if parsed.scheme:
        return parsed.hostname or ""
    return value.split("/", 1)[0].split("?", 1)[0]


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    blocked = {
        "api_key", "apikey", "authorization", "access_token", "token", "secret", "app_secret",
        "base64", "image_b64", "data_url", "image_url", "url", "asset_url", "media_url",
    }
    for key, value in (metadata or {}).items():
        key_text = str(key)
        if key_text.lower() in blocked:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_text] = value
        else:
            safe[key_text] = str(value)[:500]
    return safe
