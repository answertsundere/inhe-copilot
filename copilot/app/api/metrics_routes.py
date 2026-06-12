"""
指标 API 路由
"""

from flask import Blueprint, jsonify

metrics_bp = Blueprint("metrics", __name__)


@metrics_bp.route("/api/metrics")
def api_metrics():
    from app.services.metrics_service import get_metrics_service
    service = get_metrics_service()
    return jsonify(service.get_snapshot())
