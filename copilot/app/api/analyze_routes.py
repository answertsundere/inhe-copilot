"""
消息分析 API 路由
"""

import os
import re
import time as _time

from flask import Blueprint, request, jsonify

analyze_bp = Blueprint("analyze", __name__)

# 运行时指纹，用于确认前端调用的是最新代码
_BOOT_TIME = _time.strftime("%Y-%m-%d %H:%M:%S")
_PID = os.getpid()
_VERSION = "jst-live-query-v1"
IMAGE_MARKER_RE = re.compile(r"\[\s*\u56fe\u7247\s*\d*\s*\]")
TEXT_PRODUCT_QUESTION_TERMS = (
    "\u5417", "\u5462", "\u600e\u4e48", "\u5982\u4f55", "\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd", "\u662f\u4e0d\u662f", "\u6709\u6ca1\u6709",
    "\u4f1a\u4e0d\u4f1a", "\u53ef\u62c6", "\u62c6\u5378", "\u5b89\u88c5",
    "\u7ec4\u88c5", "\u6750\u8d28", "\u627f\u91cd", "\u5c3a\u5bf8",
    "\u6e05\u6d17", "\u9632\u6f6e",
)


def get_services():
    """获取服务实例（延迟导入，避免循环依赖）"""
    from app.main import get_reply_service
    return get_reply_service()


def _extract_identifiers(product_candidates):
    """从 product_candidates 提取 i_id / sku_code / product_id，用于素材范围匹配。"""
    i_id = sku_code = None
    product_id = None
    if not product_candidates:
        return i_id, sku_code, product_id
    for cand in product_candidates:
        if not isinstance(cand, dict):
            continue
        value = str(cand.get("value") or "").strip()
        if not value:
            continue
        ctype = str(cand.get("type") or "").lower()
        if "product_id" in ctype:
            try:
                product_id = int(value)
            except Exception:
                pass
        elif "sku" in ctype or "i_id" in ctype:
            if i_id is None:
                i_id = value
            if sku_code is None:
                sku_code = value
    return i_id, sku_code, product_id


def _has_text_product_question(message: str) -> bool:
    text = IMAGE_MARKER_RE.sub("", message or "").strip()
    return bool(text and any(term in text for term in TEXT_PRODUCT_QUESTION_TERMS))


def _has_product_or_order_context(
    *,
    product_name: str | None,
    product_candidates,
    order_id: str | None,
    tracking_no: str | None,
    platform_order_id: str | None,
    platform_trade_id: str | None,
    copilot_context,
) -> bool:
    ctx = copilot_context if isinstance(copilot_context, dict) else {}
    return bool(
        product_name
        or product_candidates
        or order_id
        or tracking_no
        or platform_order_id
        or platform_trade_id
        or ctx.get("product_name")
        or ctx.get("product_candidates")
        or ctx.get("order_id")
        or ctx.get("platform_order_id")
        or ctx.get("platform_trade_id")
        or ctx.get("tracking_no")
    )


def _looks_like_customer_product_title(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if len(text) >= 16:
        return True
    return "英禾" in text or "INHE" in text.upper()


def _candidate_product_name(candidate: dict) -> str:
    for key in (
        "display_product_name", "platform_product_title", "product_title",
        "item_title", "title", "front_product_title", "sidecar_front_title",
        "product_name", "name",
    ):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # An identifier's value is not a name, even when it is a long string.
    kind = str(candidate.get("type") or "").strip().lower()
    if kind in {"", "product_name", "product_title", "title", "item_title", "platform_product_title"}:
        value = candidate.get("value")
        if isinstance(value, str):
            return value.strip()
    return ""


def _sanitize_media_promise_without_assets(reply: str, recommended_assets: list[dict]) -> str:
    if recommended_assets or not reply:
        return reply
    risky_terms = ("\u53d1\u5b89\u88c5\u89c6\u9891", "\u53d1\u89c6\u9891", "\u53d1\u56fe", "\u56fe\u7247\u53d1\u60a8")
    if not any(term in reply for term in risky_terms):
        return reply
    safe_line = "\u5982\u679c\u60a8\u5b89\u88c5\u6216\u6838\u5bf9\u8fc7\u7a0b\u4e2d\u5361\u5728\u5177\u4f53\u6b65\u9aa4\uff0c\u53ef\u4ee5\u628a\u5361\u4f4f\u7684\u4f4d\u7f6e\u6216\u9875\u9762\u622a\u56fe\u53d1\u6211\uff0c\u6211\u8fd9\u8fb9\u6309\u5df2\u6709\u8bf4\u660e\u5e2e\u60a8\u6838\u5bf9\u3002"
    cleaned_lines = []
    inserted_safe_line = False
    for line in reply.splitlines():
        if any(term in line for term in risky_terms):
            if not inserted_safe_line:
                cleaned_lines.append(safe_line)
                inserted_safe_line = True
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _align_media_promise_with_assets(reply: str, recommended_assets: list[dict]) -> str:
    if not reply or not recommended_assets:
        return reply
    asset_types = {str(asset.get("asset_type") or "") for asset in recommended_assets}
    if "install_video" in asset_types and "\u5b89\u88c5\u89c6\u9891" in reply:
        reply = reply.replace(
            "\u5982\u679c\u9700\u8981\u5b89\u88c5\u89c6\u9891\uff0c\u53ef\u4ee5\u8054\u7cfb\u5ba2\u670d\uff0c\u6211\u4eec\u53d1\u7ed9\u60a8\u53c2\u8003",
            "\u6211\u628a\u5b89\u88c5\u89c6\u9891\u4e00\u8d77\u53d1\u60a8\u53c2\u8003\u3002",
        )
    return reply


def _is_visual_media_question(message: str, response: dict) -> bool:
    """Only attach media when the current turn is actually asking for visual help."""
    debug = response.get("evidence_debug") or {}
    semantic_query = debug.get("semantic_query") or response.get("semantic_query") or {}
    if isinstance(semantic_query, dict) and semantic_query.get("needs_visual_asset"):
        return True
    fact_type = str(debug.get("query_fact_type") or "").strip()
    visual_fact_types = {"installation", "detachable", "dimensions", "space_fit", "accessories", "packaging"}
    if fact_type in visual_fact_types:
        return True

    intent = str(response.get("intent") or "").strip()
    if intent == "image_attachment":
        return True

    text = IMAGE_MARKER_RE.sub("", message or "")
    visual_terms = (
        "\u56fe\u7247", "\u7167\u7247", "\u5b9e\u7269\u56fe", "\u5546\u54c1\u56fe",
        "\u5c3a\u5bf8\u56fe", "\u89c6\u9891", "\u5b89\u88c5\u56fe", "\u5b89\u88c5\u89c6\u9891",
        "\u914d\u4ef6\u56fe", "\u6253\u5305\u56fe", "\u8bf4\u660e\u4e66",
    )
    return any(term in text for term in visual_terms)


@analyze_bp.route("/api/analyze", methods=["POST"])
def api_analyze():
    return _analyze_customer_message()


@analyze_bp.route("/api/kb/analyze", methods=["POST"])
def api_kb_analyze():
    """Legacy knowledge-workbench entry; never shares the public policy."""
    return _analyze_customer_message()


def _analyze_customer_message():
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
    product_name = (
        data.get("product_name", "")
        or data.get("product_title", "")
        or data.get("item_title", "")
        or data.get("title", "")
    ).strip() or None
    sku_code = (
        data.get("sku_code", "")
        or data.get("sku", "")
        or data.get("sku_id", "")
        or data.get("internal_sku_code", "")
    ).strip()
    i_id = (
        data.get("i_id", "")
        or data.get("product_code", "")
        or data.get("internal_product_code", "")
    ).strip()
    sku_name = data.get("sku_name", "").strip()
    product_candidates = data.get("product_candidates") or None
    copilot_context = data.get("copilot_context") or None
    # Sidecar clients may keep structured identifiers inside copilot_context.
    # Treat them exactly like the matching top-level fields without guessing an
    # identifier type from customer text or its shape. The Pipeline will attach
    # the explicit-reference provenance contract before Graph execution.
    if isinstance(copilot_context, dict):
        if not order_id:
            order_id = str(copilot_context.get("order_id") or "").strip() or None
        if not tracking_no:
            tracking_no = str(copilot_context.get("tracking_no") or "").strip() or None
        if not platform_order_id:
            platform_order_id = str(copilot_context.get("platform_order_id") or "").strip() or None
        if not platform_trade_id:
            platform_trade_id = str(copilot_context.get("platform_trade_id") or "").strip() or None
    conversation_history = data.get("conversation_history") or None
    if conversation_history and not isinstance(copilot_context, dict):
        copilot_context = {"conversation_history": conversation_history}
    if conversation_history and isinstance(copilot_context, dict):
        copilot_context.setdefault("conversation_history", conversation_history)
    if not product_candidates and isinstance(copilot_context, dict):
        product_candidates = copilot_context.get("product_candidates") or None
    if product_candidates and not isinstance(copilot_context, dict):
        copilot_context = {"product_candidates": product_candidates}
    if product_candidates and isinstance(copilot_context, dict):
        copilot_context.setdefault("product_candidates", product_candidates)
    if product_name or sku_code or i_id or sku_name:
        copilot_context = copilot_context or {}
        if product_name:
            copilot_context.setdefault("product_name", product_name)
            # Preserve the explicitly supplied product name from the current turn
            # so downstream polish can prefer it over historical context.
            copilot_context.setdefault("explicit_product_name", product_name)
            if _looks_like_customer_product_title(product_name):
                copilot_context.setdefault("display_product_name", product_name)
                copilot_context.setdefault("platform_product_title", product_name)
        if sku_code:
            copilot_context.setdefault("sku_code", sku_code)
        if i_id:
            copilot_context.setdefault("i_id", i_id)
        if sku_name:
            copilot_context.setdefault("sku_name", sku_name)
        product_candidates = list(product_candidates or [])
        if product_name and not any(
            isinstance(c, dict) and (c.get("product_name") == product_name or c.get("value") == product_name)
            for c in product_candidates
        ):
            candidate = {"type": "product_name", "value": product_name, "product_name": product_name}
            if _looks_like_customer_product_title(product_name):
                candidate["display_product_name"] = product_name
                candidate["platform_product_title"] = product_name
            product_candidates.append(candidate)
        if sku_code and not any(isinstance(c, dict) and c.get("value") == sku_code for c in product_candidates):
            product_candidates.append({"type": "sku_code", "value": sku_code, "sku_code": sku_code})
        if i_id and not any(isinstance(c, dict) and c.get("value") == i_id for c in product_candidates):
            product_candidates.append({"type": "i_id", "value": i_id, "i_id": i_id})
        copilot_context["product_candidates"] = product_candidates
    if not product_name and product_candidates:
        for candidate in product_candidates:
            if isinstance(candidate, str) and candidate.strip():
                product_name = candidate.strip()
                if _looks_like_customer_product_title(product_name):
                    copilot_context = copilot_context or {}
                    copilot_context.setdefault("display_product_name", product_name)
                    copilot_context.setdefault("platform_product_title", product_name)
                break
            if isinstance(candidate, dict):
                value = _candidate_product_name(candidate)
                if value and _looks_like_customer_product_title(value):
                    copilot_context = copilot_context or {}
                    copilot_context.setdefault("display_product_name", value)
                    copilot_context.setdefault("platform_product_title", value)
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

        # Build copilot_context with platform identifiers if provided
        if platform_order_id or platform_trade_id:
            copilot_context = copilot_context or {}
            if platform_order_id:
                copilot_context.setdefault("platform_order_id", platform_order_id)
            if platform_trade_id:
                copilot_context.setdefault("platform_trade_id", platform_trade_id)

        from app.services.analysis_pipeline_service import AnalysisPipelineRequest, AnalysisPipelineService

        response = AnalysisPipelineService().run(
            AnalysisPipelineRequest(
                reply_service=reply_service,
                customer_message=message,
                delivery_message=message,
                order_id=order_id or "",
                tracking_no=tracking_no or "",
                conversation_id=conversation_id,
                product_name=product_name or "",
                product_candidates=product_candidates or [],
                copilot_context=copilot_context or {},
                image_attachments=image_attachments,
                source="api",
                scenario=str(data.get("scenario") or ""),
                capabilities=data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {},
            )
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

        status_code = 422 if response.get("error") == "invalid_conversation_context" else (500 if response.get("error") else 200)
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
