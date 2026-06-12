"""
人工复核队列 API 路由
"""

from flask import Blueprint, request, jsonify

review_bp = Blueprint("review", __name__)


def _get_review_service():
    from app.main import get_review_queue_service
    return get_review_queue_service()


def _get_feedback_service():
    from app.main import get_feedback_service
    return get_feedback_service()


@review_bp.route("/api/reviews", methods=["GET"])
def api_reviews_list():
    """获取复核列表"""
    status = request.args.get("status", "").strip()
    limit = request.args.get("limit", 50, type=int)

    service = _get_review_service()
    records = service.list_reviews(status=status, limit=limit)
    return jsonify({"records": records, "count": len(records)})


@review_bp.route("/api/reviews/<review_id>", methods=["GET"])
def api_review_detail(review_id):
    """获取单条复核记录"""
    service = _get_review_service()
    record = service.get_by_id(review_id)
    if not record:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify(record)


@review_bp.route("/api/reviews/<review_id>/decision", methods=["POST"])
def api_review_decision(review_id):
    """提交复核决策"""
    data = request.json or {}
    status = data.get("status", "").strip()
    final_reply = data.get("final_reply", "")
    reviewed_by = data.get("reviewed_by", "")
    review_note = data.get("review_note", "")

    service = _get_review_service()
    try:
        record = service.decide(
            review_id=review_id,
            status=status,
            final_reply=final_reply,
            reviewed_by=reviewed_by,
            review_note=review_note,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if record is None:
        return jsonify({"error": "记录不存在"}), 404

    # 同步写入 feedback_service（approved 映射为 accepted）
    fb_action = "accepted" if status == "approved" else status
    fb_service = _get_feedback_service()
    fb_service.save(
        customer_message=record.get("customer_message", ""),
        suggested_reply=record.get("suggested_reply", ""),
        action=fb_action,
        order_id=record.get("order_id", ""),
        final_reply=record.get("final_reply", ""),
        risk_level=record.get("risk_level", ""),
        source="review",
        review_id=review_id,
    )

    return jsonify({"ok": True, "record": record})
