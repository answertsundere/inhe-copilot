"""Read-only tool call operations APIs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

from app.api.admin_auth import require_supervisor
from app.models.tool_call_log import ToolCallLog
from app.services.eval_sanitizer_service import sanitize_payload

tool_ops_bp = Blueprint("tool_ops", __name__, url_prefix="/api/tool-ops")


@tool_ops_bp.route("/calls")
def api_tool_ops_calls():
    denied = require_supervisor()
    if denied:
        return denied
    limit = _limit(request.args.get("limit"))
    db = _session()
    try:
        query = _filtered_query(db.query(ToolCallLog))
        rows = query.order_by(ToolCallLog.created_at.desc(), ToolCallLog.id.desc()).limit(limit).all()
        return jsonify({"items": [_row_to_dict(row) for row in rows], "limit": limit})
    finally:
        db.close()


@tool_ops_bp.route("/summary")
def api_tool_ops_summary():
    denied = require_supervisor()
    if denied:
        return denied
    db = _session()
    try:
        rows = _filtered_query(db.query(ToolCallLog)).all()
        latencies = [max(0, int(row.latency_ms or 0)) for row in rows if row.latency_ms is not None]
        return jsonify({
            "total_calls": len(rows),
            "allowed_calls": sum(1 for row in rows if row.allowed),
            "blocked_calls": sum(1 for row in rows if row.status == "blocked" or not row.allowed),
            "error_calls": sum(1 for row in rows if row.status == "error"),
            "by_tool": _count_by(rows, "tool_name"),
            "by_status": _count_by(rows, "status"),
            "by_risk_level": _count_by(rows, "tool_risk_level"),
            "high_risk_calls": sum(1 for row in rows if row.tool_risk_level == "read_only_sensitive"),
            "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else 0,
        })
    finally:
        db.close()


def _filtered_query(query):
    args = request.args
    filters = {
        "tool_name": ToolCallLog.tool_name,
        "status": ToolCallLog.status,
        "intent": ToolCallLog.intent,
        "query_fact_type": ToolCallLog.query_fact_type,
        "trace_id": ToolCallLog.trace_id,
        "conversation_id": ToolCallLog.conversation_id,
    }
    for key, column in filters.items():
        value = str(args.get(key) or "").strip()
        if value:
            query = query.filter(column == value)

    if str(args.get("allowed") or "").strip():
        allowed = str(args.get("allowed")).lower() in {"1", "true", "yes", "allowed"}
        query = query.filter(ToolCallLog.allowed == allowed)

    since = _parse_datetime(args.get("since"))
    until = _parse_datetime(args.get("until"))
    if since:
        query = query.filter(ToolCallLog.created_at >= since)
    if until:
        query = query.filter(ToolCallLog.created_at <= until)
    return query


def _row_to_dict(row: ToolCallLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "trace_id": row.trace_id,
        "conversation_id": row.conversation_id,
        "request_id": row.request_id,
        "node_name": row.node_name,
        "tool_name": row.tool_name,
        "tool_risk_level": row.tool_risk_level,
        "intent": row.intent,
        "query_fact_type": row.query_fact_type,
        "allowed": bool(row.allowed),
        "blocked_reason": row.blocked_reason,
        "status": row.status,
        "error_type": row.error_type,
        "latency_ms": row.latency_ms,
        "input_summary": _loads_summary(row.input_summary_json),
        "output_summary": _loads_summary(row.output_summary_json),
        "entity_summary": _loads_summary(row.entity_summary_json),
        "evidence_summary": _loads_summary(row.evidence_summary_json),
    }


def _loads_summary(raw: str) -> Any:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return sanitize_payload(parsed)


def _count_by(rows: list[ToolCallLog], attr: str) -> dict[str, int]:
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


def _session():
    from app import db as db_module

    return db_module.SessionLocal()
