"""
健康检查 API 路由
"""

import os
import time

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)

_boot_time = time.time()


@health_bp.route("/api/health")
def api_health():
    """系统健康检查"""
    from app.main import (
        get_order_repo, get_product_repo,
        get_knowledge_repo, get_policy_repo,
        get_product_knowledge_repo,
        get_review_queue_service, get_feedback_service,
    )
    from app.config import LLM_API_KEY, LLM_MODEL, LLM_API_BASE
    from app.config import JST_APP_KEY, JST_APP_SECRET, JST_ACCESS_TOKEN
    from app.config import KNOWLEDGE_DB_PATH, EMBEDDING_ENABLED

    order_repo = get_order_repo()
    product_repo = get_product_repo()
    knowledge_repo = get_knowledge_repo()
    policy_repo = get_policy_repo()
    pk_repo = get_product_knowledge_repo()
    review_service = get_review_queue_service()
    fb_service = get_feedback_service()

    risk_keywords = policy_repo.get_risk_keywords()
    forbidden_claims = policy_repo.get_forbidden_claims()
    rules_ok = len(forbidden_claims) > 0 and len(risk_keywords) > 0

    # 数据库状态检查
    db_status = "ok"
    try:
        from app.db import init_db
        init_db()
    except Exception:
        db_status = "error"

    # 知识库数据库文件检查
    knowledge_db_status = "ok" if os.path.exists(KNOWLEDGE_DB_PATH) else "missing"
    knowledge_db_entries_count = 0
    if knowledge_db_status == "ok":
        try:
            import sqlite3
            conn = sqlite3.connect(KNOWLEDGE_DB_PATH)
            try:
                knowledge_db_entries_count = conn.execute("select count(*) from knowledge_entries").fetchone()[0]
            finally:
                conn.close()
        except Exception:
            knowledge_db_status = "error"

    return jsonify({
        "status": "ok",
        "version": "copilot-v2",
        "boot_time": _boot_time,
        "boot_time_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_boot_time)),
        "jst_configured": bool(JST_APP_KEY and JST_APP_SECRET and JST_ACCESS_TOKEN),
        "embedding_enabled": bool(EMBEDDING_ENABLED),
        "db_status": db_status,
        "knowledge_db_status": knowledge_db_status,
        "knowledge_db_entries_count": knowledge_db_entries_count,
        "data": {
            "orders": order_repo.count_orders(),
            "skus": product_repo.count_skus(),
            "products": product_repo.count_products(),
            "logistics": order_repo.count_logistics(),
            "refunds": order_repo.count_refunds(),
            "knowledge_entries": len(knowledge_repo.get_all()),
            "product_knowledge_cards": pk_repo.count(),
            "review_queue_pending": review_service.count_pending(),
            "feedback_total": fb_service.get_stats()["total"],
        },
        "llm": {
            "configured": bool(LLM_API_KEY),
            "model": LLM_MODEL if LLM_API_KEY else "(未配置)",
            "api_base": LLM_API_BASE,
        },
        "rules": {
            "loaded": rules_ok,
            "forbidden_claims": len(forbidden_claims),
            "risk_keywords": {
                "high": len(risk_keywords.get("high", [])),
                "medium": len(risk_keywords.get("medium", [])),
                "low": len(risk_keywords.get("low", [])),
            },
        },
        "knowledge": {
            "entries": len(knowledge_repo.get_all()),
            "categories": list({e["category"] for e in knowledge_repo.get_all()}),
        },
    })
