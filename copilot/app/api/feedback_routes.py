"""Feedback API routes."""

from flask import Blueprint, jsonify, request

feedback_bp = Blueprint("feedback", __name__)


def get_feedback_service():
    from app.main import get_feedback_service as _get

    return _get()


def _validate_sendable_feedback(data: dict, action: str):
    if action == "accepted":
        sendable_reply = str(data.get("sendable_reply") or "")
        final_reply = str(data.get("final_reply") or "")
        if not bool(data.get("can_send")) or not sendable_reply:
            return jsonify({"error": "accepted requires can_send=true and non-empty sendable_reply"}), 400
        if final_reply and final_reply != sendable_reply:
            return jsonify({"error": "accepted final_reply must match sendable_reply; use edited for manual changes"}), 400
    if action == "edited" and not str(data.get("final_reply") or "").strip():
        return jsonify({"error": "edited requires final_reply"}), 400
    return None


@feedback_bp.route("/api/feedback", methods=["POST"])
def api_feedback():
    """Save feedback."""
    data = request.json or {}
    action = data.get("action", "").strip()
    if action not in ("accepted", "edited", "rejected", "escalated"):
        return jsonify({"error": "action must be accepted/edited/rejected/escalated"}), 400

    validation_error = _validate_sendable_feedback(data, action)
    if validation_error is not None:
        return validation_error

    fb_service = get_feedback_service()
    record = fb_service.save(
        customer_message=data.get("customer_message", ""),
        suggested_reply=data.get("suggested_reply", ""),
        action=action,
        order_id=data.get("order_id", ""),
        final_reply=data.get("final_reply", ""),
        risk_level=data.get("risk_level", ""),
        source=data.get("source", "analysis"),
        review_id=data.get("review_id", ""),
    )
    return jsonify({"ok": True, "record": record})


@feedback_bp.route("/api/feedback", methods=["GET"])
def api_feedback_list():
    """List feedback."""
    fb_service = get_feedback_service()
    limit = request.args.get("limit", 50, type=int)
    records = fb_service.load_all(limit=limit)
    return jsonify({"records": records, "count": len(records)})


@feedback_bp.route("/api/feedback/stats", methods=["GET"])
def api_feedback_stats():
    """Feedback statistics."""
    fb_service = get_feedback_service()
    stats = fb_service.get_stats()
    return jsonify(stats)
