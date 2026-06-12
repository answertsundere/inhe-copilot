"""
质检服务 API 路由
"""

from flask import Blueprint, request, jsonify, current_app

quality_bp = Blueprint("quality", __name__)


def _get_quality_check_service():
    svc = current_app.config.get("quality_check_service")
    if svc is not None:
        return svc
    from app.main import get_quality_check_service
    return get_quality_check_service()


@quality_bp.route("/api/quality/check-reply", methods=["POST"])
def api_check_reply():
    """检查客服回复质量"""
    data = request.json or {}
    customer_message = data.get("customer_message", "")
    reply = data.get("reply", "")
    order_id = data.get("order_id", "")
    scenario = data.get("scenario", "")

    if not customer_message or not reply:
        return jsonify({"error": "customer_message 和 reply 不能为空"}), 400

    service = _get_quality_check_service()
    result = service.check(
        customer_message=customer_message,
        reply=reply,
        order_id=order_id,
        scenario=scenario,
    )
    return jsonify(result)
