"""Read-only model call operations APIs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

from app.db import SessionLocal
from app.models.model_call_log import ModelCallLog
from app.services.model_call_ledger_service import _sanitize_metadata


model_ops_bp = Blueprint("model_ops", __name__, url_prefix="/api/model-ops")


@model_ops_bp.route("/calls")
def api_model_ops_calls():
    limit = _limit(request.args.get("limit"))
    db = SessionLocal()
    try:
        query = _filtered_query(db.query(ModelCallLog))
        rows = query.order_by(ModelCallLog.created_at.desc(), ModelCallLog.id.desc()).limit(limit).all()
        return jsonify({
            "items": [_row_to_dict(row) for row in rows],
            "limit": limit,
        })
    finally:
        db.close()


@model_ops_bp.route("/summary")
def api_model_ops_summary():
    db = SessionLocal()
    try:
        query = _filtered_query(db.query(ModelCallLog))
        rows = query.all()
        latencies = [max(0, int(row.latency_ms or 0)) for row in rows if row.latency_ms is not None]
        return jsonify({
            "total_calls": len(rows),
            "success_calls": sum(1 for row in rows if row.status == "success"),
            "error_calls": sum(1 for row in rows if row.status == "error"),
            "total_tokens": sum(max(0, int(row.total_tokens or 0)) for row in rows),
            "total_estimated_cost": sum(float(row.estimated_cost or 0.0) for row in rows),
            "by_alias": _count_by(rows, "alias"),
            "by_node": _count_by(rows, "node_name"),
            "by_status": _count_by(rows, "status"),
            "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0,
            "cost_unknown_count": sum(1 for row in rows if _metadata(row).get("cost_unknown") is True),
        })
    finally:
        db.close()


def _filtered_query(query):
    args = request.args
    filters = {
        "alias": ModelCallLog.alias,
        "node_name": ModelCallLog.node_name,
        "status": ModelCallLog.status,
        "conversation_id": ModelCallLog.conversation_id,
        "trace_id": ModelCallLog.trace_id,
    }
    for key, column in filters.items():
        value = str(args.get(key) or "").strip()
        if value:
            query = query.filter(column == value)

    since = _parse_datetime(args.get("since"))
    until = _parse_datetime(args.get("until"))
    if since:
        query = query.filter(ModelCallLog.created_at >= since)
    if until:
        query = query.filter(ModelCallLog.created_at <= until)
    return query


def _row_to_dict(row: ModelCallLog) -> dict[str, Any]:
    metadata = _metadata(row)
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "trace_id": row.trace_id,
        "conversation_id": row.conversation_id,
        "request_id": row.request_id,
        "node_name": row.node_name,
        "alias": row.alias,
        "provider": row.provider,
        "model": row.model,
        "api_base_host": row.api_base_host,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "estimated_cost": row.estimated_cost,
        "currency": row.currency,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error_type": row.error_type,
        "metadata_json": metadata,
        "metadata": metadata,
    }


def _metadata(row: ModelCallLog) -> dict[str, Any]:
    try:
        parsed = json.loads(row.metadata_json or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return _sanitize_metadata(parsed)


def _count_by(rows: list[ModelCallLog], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, attr, "") or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _limit(raw: str | None) -> int:
    try:
        value = int(raw or 50)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, 200))


def _parse_datetime(raw: str | None) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)
