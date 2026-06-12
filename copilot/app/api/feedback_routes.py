"""
反馈 API 路由
"""

from flask import Blueprint, request, jsonify

feedback_bp = Blueprint("feedback", __name__)


def get_feedback_service():
    from app.main import get_feedback_service as _get
    return _get()


@feedback_bp.route("/api/feedback", methods=["POST"])
def api_feedback():
    """保存反馈"""
    data = request.json
    action = data.get("action", "").strip()
    if action not in ("accepted", "edited", "rejected", "escalated"):
        return jsonify({"error": "action 必须是 accepted/edited/rejected/escalated"}), 400

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
    """获取反馈列表"""
    fb_service = get_feedback_service()
    limit = request.args.get("limit", 50, type=int)
    records = fb_service.load_all(limit=limit)
    return jsonify({"records": records, "count": len(records)})


@feedback_bp.route("/api/feedback/stats", methods=["GET"])
def api_feedback_stats():
    """反馈统计"""
    fb_service = get_feedback_service()
    stats = fb_service.get_stats()
    return jsonify(stats)
