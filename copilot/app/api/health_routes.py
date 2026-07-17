"""
健康检查 API 路由
"""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)

@health_bp.route("/api/health")
@health_bp.route("/health")
def api_health():
    """系统健康检查"""
    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService
    from app.api.runtime_routes import _with_admin_auth_readiness, public_readiness_payload

    readiness = _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    public_readiness = public_readiness_payload(readiness)

    return jsonify({
        "status": "ok",
        "version": "copilot-v2",
        "ready": public_readiness["ready"],
        "readiness_status": public_readiness["status"],
        "readiness_reasons": public_readiness["reasons"],
    })
