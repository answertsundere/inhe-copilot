"""
Trace API Routes — /api/traces
"""

import json
import logging

from flask import Blueprint, request, jsonify

trace_api_bp = Blueprint("trace_api", __name__)

logger = logging.getLogger(__name__)


@trace_api_bp.route("/api/traces", methods=["GET"])
def list_traces():
    """List traces with filtering and pagination."""
    try:
        from app.tracing.repository import query_traces

        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 20, type=int)
        page = max(1, page)
        page_size = max(1, min(100, page_size))

        result = query_traces(
            conversation_id=request.args.get("conversation_id", ""),
            request_id=request.args.get("request_id", ""),
            message_id=request.args.get("message_id", ""),
            status=request.args.get("status", ""),
            source=request.args.get("source", ""),
            intent=request.args.get("intent", ""),
            risk_level=request.args.get("risk_level", ""),
            min_duration_ms=request.args.get("min_duration_ms", 0, type=int),
            has_error=request.args.get("has_error", "").lower() in ("true", "1"),
            date_from=request.args.get("date_from", ""),
            date_to=request.args.get("date_to", ""),
            page=page,
            page_size=page_size,
        )
        return jsonify(result)
    except Exception as e:
        logger.warning("list_traces failed: %s", e)
        return jsonify({"error": str(e)}), 500


@trace_api_bp.route("/api/traces/<trace_id>", methods=["GET"])
def get_trace_detail(trace_id: str):
    """Get full trace detail with spans, snapshot, and linked data."""
    try:
        from app.tracing.repository import get_trace_detail

        detail = get_trace_detail(trace_id)
        if not detail:
            return jsonify({"error": "trace not found"}), 404
        return jsonify(detail)
    except Exception as e:
        logger.warning("get_trace_detail failed: %s", e)
        return jsonify({"error": str(e)}), 500


@trace_api_bp.route("/api/traces/<trace_id>/spans", methods=["GET"])
def get_trace_spans(trace_id: str):
    """Get spans for a trace."""
    try:
        from app.tracing.repository import get_spans

        spans = get_spans(trace_id)
        return jsonify({"trace_id": trace_id, "spans": spans})
    except Exception as e:
        logger.warning("get_trace_spans failed: %s", e)
        return jsonify({"error": str(e)}), 500


@trace_api_bp.route("/api/traces/<trace_id>/waterfall", methods=["GET"])
def get_trace_waterfall(trace_id: str):
    """Get waterfall view of trace spans."""
    try:
        from app.tracing.repository import get_spans, get_trace_run

        run = get_trace_run(trace_id)
        if not run:
            return jsonify({"error": "trace not found"}), 404

        spans = get_spans(trace_id)
        # Build waterfall: group spans by parent
        span_map = {s["span_id"]: s for s in spans}
        root_spans = []
        children = {}
        for s in spans:
            pid = s.get("parent_span_id", "")
            if not pid or pid not in span_map:
                root_spans.append(s)
            else:
                children.setdefault(pid, []).append(s)

        def build_tree(span):
            return {
                "span_id": span["span_id"],
                "name": span["name"],
                "span_type": span.get("span_type", ""),
                "status": span.get("status", ""),
                "duration_ms": span.get("duration_ms"),
                "started_at": span.get("started_at", ""),
                "children": [build_tree(c) for c in children.get(span["span_id"], [])],
            }

        waterfall = [build_tree(s) for s in root_spans]
        return jsonify({
            "trace_id": trace_id,
            "status": run.get("status", ""),
            "started_at": run.get("started_at", ""),
            "duration_ms": run.get("duration_ms"),
            "waterfall": waterfall,
        })
    except Exception as e:
        logger.warning("get_trace_waterfall failed: %s", e)
        return jsonify({"error": str(e)}), 500


@trace_api_bp.route("/api/traces/<trace_id>/create-bad-case", methods=["POST"])
def create_bad_case_from_trace(trace_id: str):
    """Create a bad case from a trace."""
    try:
        from app.tracing.repository import get_trace_detail
        from app.services.bad_case_service import BadCaseStore

        detail = get_trace_detail(trace_id)
        if not detail:
            return jsonify({"error": "trace not found"}), 404

        data = request.json or {}
        reason = data.get("reason", "")
        expected = data.get("expected_reply", "")

        trace_data = detail.get("trace", {})
        snapshot = detail.get("snapshot", {})
        spans = detail.get("spans", [])

        bad_case_store = BadCaseStore()
        case = bad_case_store.create({
            "trace_id": trace_id,
            "snapshot_id": snapshot.get("snapshot_id", "") if snapshot else "",
            "message_id": trace_data.get("message_id", ""),
            "conversation_id": trace_data.get("conversation_id", ""),
            "customer_message": snapshot.get("customer_message", "") if snapshot else "",
            "actual_reply": snapshot.get("suggested_reply", "") if snapshot else "",
            "expected_reply": expected,
            "reason": reason,
            "intent": snapshot.get("intent", "") if snapshot else trace_data.get("outcome", {}).get("intent", ""),
            "risk_level": snapshot.get("risk_level", "") if snapshot else "",
            "span_count": len(spans),
            "trace_duration_ms": trace_data.get("duration_ms"),
            "source": "trace_ui",
        })
        return jsonify(case), 201
    except Exception as e:
        logger.warning("create_bad_case_from_trace failed: %s", e)
        return jsonify({"error": str(e)}), 500


@trace_api_bp.route("/api/messages/<message_id>/trace", methods=["GET"])
def get_trace_by_message(message_id: str):
    """Get trace by message_id."""
    try:
        from app.tracing.repository import get_session
        from app.tracing.models import TraceRun

        session = get_session()
        try:
            run = session.query(TraceRun).filter_by(message_id=message_id).first()
            if not run:
                return jsonify({"error": "no trace found for message_id"}), 404
            trace_id = run.trace_id
        finally:
            session.close()

        from app.tracing.repository import get_trace_detail
        detail = get_trace_detail(trace_id)
        return jsonify(detail or {"trace_id": trace_id})
    except Exception as e:
        logger.warning("get_trace_by_message failed: %s", e)
        return jsonify({"error": str(e)}), 500
