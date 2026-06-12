"""
消息分析 API 路由
"""

import os
import time as _time

from flask import Blueprint, request, jsonify

analyze_bp = Blueprint("analyze", __name__)

# 运行时指纹，用于确认前端调用的是最新代码
_BOOT_TIME = _time.strftime("%Y-%m-%d %H:%M:%S")
_PID = os.getpid()
_VERSION = "jst-live-query-v1"


def get_services():
    """获取服务实例（延迟导入，避免循环依赖）"""
    from app.main import get_reply_service
    return get_reply_service()


@analyze_bp.route("/api/analyze", methods=["POST"])
def api_analyze():
    """分析客户消息"""
    t0 = _time.time()
    data = request.json or {}
    image_attachments = (
        data.get("image_attachments")
        or data.get("attachments")
        or data.get("images")
        or []
    )
    message = data.get("message", "").strip()
    if not message and image_attachments:
        message = "客户发来图片"
    order_id = data.get("order_id", "").strip() or None
    tracking_no = data.get("tracking_no", "").strip() or None
    platform_order_id = data.get("platform_order_id", "").strip() or None
    platform_trade_id = data.get("platform_trade_id", "").strip() or None
    conversation_id = data.get("conversation_id", "").strip() or "default"
    product_name = data.get("product_name", "").strip() or None
    product_candidates = data.get("product_candidates") or None
    copilot_context = data.get("copilot_context") or None
    if not product_candidates and isinstance(copilot_context, dict):
        product_candidates = copilot_context.get("product_candidates") or None
    if product_candidates and not isinstance(copilot_context, dict):
        copilot_context = {"product_candidates": product_candidates}
    if product_candidates and isinstance(copilot_context, dict):
        copilot_context.setdefault("product_candidates", product_candidates)
    if not product_name and product_candidates:
        for candidate in product_candidates:
            if isinstance(candidate, str) and candidate.strip():
                product_name = candidate.strip()
                break
            if isinstance(candidate, dict):
                value = str(
                    candidate.get("value")
                    or candidate.get("product_name")
                    or candidate.get("name")
                    or candidate.get("title")
                    or ""
                ).strip()
                if value:
                    product_name = value
                    break

    if not message:
        return jsonify({"error": "请输入客户消息"}), 400

    try:
        from app.services.metrics_service import get_metrics_service
        metrics = get_metrics_service()
        metrics.increment("request_count")

        reply_service = get_services()

        from app.services.analysis_execution_service import execute_analysis
        # Build copilot_context with platform identifiers if provided
        if platform_order_id or platform_trade_id:
            copilot_context = copilot_context or {}
            if platform_order_id:
                copilot_context.setdefault("platform_order_id", platform_order_id)
            if platform_trade_id:
                copilot_context.setdefault("platform_trade_id", platform_trade_id)

        if image_attachments:
            from app.services.customer_image_vlm_service import analyze_customer_images
            image_analysis = analyze_customer_images(image_attachments)
            if image_analysis:
                copilot_context = copilot_context or {}
                copilot_context["image_analysis"] = image_analysis
                copilot_context["has_image_attachment"] = True
                for idx, analysis in enumerate(image_analysis):
                    if idx >= len(image_attachments) or not isinstance(image_attachments[idx], dict):
                        continue
                    if analysis.get("summary") and not image_attachments[idx].get("description"):
                        image_attachments[idx]["description"] = analysis.get("summary")
                    image_attachments[idx]["vlm_analysis"] = analysis

        response = execute_analysis(
            reply_service=reply_service,
            customer_message=message,
            order_id=order_id or "",
            tracking_no=tracking_no or "",
            conversation_id=conversation_id,
            product_name=product_name or "",
            product_candidates=product_candidates,
            copilot_context=copilot_context,
            image_attachments=image_attachments,
            source="api",
        )

        duration_ms = int((_time.time() - t0) * 1000)
        metrics.record_latency(duration_ms)

        if response.get("requires_human_review"):
            metrics.increment("human_review_count")

        trace_steps = response.get("trace_steps", [])
        if any((s.get("node") or s.get("step")) == "graph_fallback" for s in trace_steps):
            metrics.increment("fallback_count")

        response.setdefault("evidence_debug", {})["request_duration_ms"] = duration_ms
        if "execution_debug" not in response:
            response["execution_debug"] = {}
        if response["execution_debug"]:
            response["execution_debug"].setdefault("timing", {})["total_ms"] = duration_ms

        # 注入运行时指纹
        response["debug_runtime"] = {
            "version": _VERSION,
            "pid": _PID,
            "boot_time": _BOOT_TIME,
            "graph_enabled": True,
            "jst_live_layer": True,
            "input_product_candidates_count": len(product_candidates or []),
            "input_copilot_product_candidates_count": len((copilot_context or {}).get("product_candidates", [])) if isinstance(copilot_context, dict) else 0,
            "input_has_product_name": bool(product_name),
        }

        status_code = 500 if response.get("error") else 200
        return jsonify(response), status_code
    except Exception as e:
        try:
            from app.services.metrics_service import get_metrics_service
            get_metrics_service().increment("fallback_count")
        except Exception:
            pass
        return jsonify({
            "error": str(e),
            "debug_runtime": {"version": _VERSION, "pid": _PID},
        }), 500
