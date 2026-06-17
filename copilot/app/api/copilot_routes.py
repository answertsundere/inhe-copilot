from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

from app.services.sidecar_context_service import best_candidate_value, build_sidecar_context

copilot_bp = Blueprint("copilot", __name__)


def get_reply_service():
    from app.main import get_reply_service as _get
    return _get()


def get_feedback_service():
    from app.main import get_feedback_service as _get
    return _get()


def _extract_media_identifiers(context: dict):
    """从 sidecar context 提取 i_id / sku_code / product_name / product_id。"""
    i_id = sku_code = product_name = None
    product_id = None
    for cand in context.get("product_candidates", []) or []:
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
        elif "product_name" in ctype or "name" in ctype:
            if product_name is None:
                product_name = value
    if not product_name:
        product_name = context.get("product_name") or ""
    return i_id, sku_code, product_name, product_id


def _resolve_identifiers(context: dict) -> tuple[str, str, str, str]:
    """Resolve order_id, tracking_no, platform_trade_id, product_name from context candidates."""
    order_id = context.get("order_id", "")
    tracking_no = context.get("tracking_no", "")
    platform_trade_id = context.get("platform_trade_id", "")
    product_name = context.get("product_name", "")

    if not order_id:
        for cand in context.get("order_candidates", []):
            if cand.get("value"):
                cand_type = str(cand.get("type") or cand.get("identifier_type") or "").lower()
                if not platform_trade_id and ("platform_trade" in cand_type or "outer" in cand_type):
                    platform_trade_id = cand["value"]
                    context["platform_trade_id"] = platform_trade_id
                    context["identifier_type"] = "platform_trade_id"
                if cand.get("verified"):
                    order_id = cand["value"]
                    break
                if not order_id:
                    order_id = cand["value"]

    if not tracking_no:
        for cand in context.get("tracking_candidates", []):
            if cand.get("value"):
                if cand.get("verified"):
                    tracking_no = cand["value"]
                    break
                if not tracking_no:
                    tracking_no = cand["value"]

    return order_id, tracking_no, platform_trade_id, product_name


def _to_copilot_response(
    response: dict,
    context: dict,
    duration_ms: int,
    recommended_assets: list | None = None,
    reply_blocks: list | None = None,
    reply_delivery: dict | None = None,
) -> dict:
    """Transform execute_analysis response to copilot panel format."""
    if response.get("error"):
        return {
            "ok": False,
            "error": response["error"],
            "request_id": response.get("request_id", ""),
            "message_id": response.get("message_id", ""),
            "trace_id": response.get("trace_id", ""),
            "conversation_id": response.get("conversation_id", ""),
        }

    # Extract copilot-specific evidence enrichment
    evidence_debug = response.get("evidence_debug", {})
    evidence_debug["copilot_context"] = {
        "source": context.get("source", ""),
        "window_title": context.get("window_title", ""),
        "conversation_id": context.get("conversation_id", ""),
        "identifier_type": context.get("identifier_type", ""),
        "order_id": context.get("order_id", ""),
        "platform_trade_id": context.get("platform_trade_id", ""),
        "tracking_no": context.get("tracking_no", ""),
        "product_name": context.get("product_name", ""),
        "customer_message_source": context.get("customer_message_source", ""),
        "conversation_history": context.get("conversation_history", []),
    }

    for cand_key in ("order_candidates", "tracking_candidates", "product_candidates"):
        candidates = context.get(cand_key, [])
        if candidates:
            evidence_debug[cand_key] = candidates

    evidence_debug["copilot_context_duration_ms"] = duration_ms

    execution_debug = response.get("execution_debug", {})
    if execution_debug:
        execution_debug.setdefault("timing", {})["total_ms"] = duration_ms
        execution_debug.setdefault("request", {})["source"] = context.get("source", "manual_simulation")
        execution_debug.setdefault("request", {})["conversation_id"] = context.get("conversation_id", "")

    used_knowledge_entry_ids = evidence_debug.get("used_knowledge_entry_ids", [])
    used_knowledge_titles = evidence_debug.get("used_knowledge_titles", [])
    used_fact_tools = response.get("used_fact_tool", "")
    need_human_review = response.get("requires_human_review", False)

    return {
        "ok": True,
        "request_id": response.get("request_id", ""),
        "message_id": response.get("message_id", ""),
        "trace_id": response.get("trace_id", ""),
        "conversation_id": context.get("conversation_id", ""),
        "suggested_reply": response.get("suggested_reply", ""),
        "recommended_assets": recommended_assets or [],
        "reply_blocks": reply_blocks or [],
        "reply_delivery": reply_delivery or {"mode": "blocks", "auto_send_ready": False, "reason": "not_built"},
        "intent": response.get("intent", ""),
        "risk_level": response.get("risk_level", ""),
        "customer_emotion": response.get("customer_emotion", ""),
        "requires_human_review": need_human_review,
        "need_human_review": need_human_review,
        "used_knowledge_titles": used_knowledge_titles,
        "used_knowledge_entry_ids": used_knowledge_entry_ids,
        "used_fact_tools": used_fact_tools,
        "evidence_debug": evidence_debug,
        "execution_debug": execution_debug,
        "final_response_pipeline": response.get("final_response_pipeline", {}),
        "final_answer_audit": response.get("final_answer_audit", {}),
        "customer_reply_polish": response.get("customer_reply_polish", {}),
        "trace_steps": response.get("trace_steps", []),
        "context_echo": {
            "source": context.get("source", ""),
            "window_title": context.get("window_title", ""),
            "conversation_id": context.get("conversation_id", ""),
            "customer_message": context.get("customer_message", ""),
            "conversation_history": context.get("conversation_history", []),
            "order_id": context.get("order_id", ""),
            "platform_trade_id": context.get("platform_trade_id", ""),
            "tracking_no": context.get("tracking_no", ""),
            "product_name": context.get("product_name", ""),
            "identifier_type": context.get("identifier_type", ""),
            "customer_message_source": context.get("customer_message_source", ""),
        },
    }


@copilot_bp.route("/api/copilot/context", methods=["POST"])
def api_copilot_context():
    t0 = time.time()
    payload = request.get_json(silent=True) or {}

    # 1. Parse Sidecar payload
    context = build_sidecar_context(payload)
    message = context.get("customer_message", "").strip()
    if not message:
        return jsonify({
            "ok": False,
            "error": "missing_customer_message",
            "message": "没有从千牛会话中读取到可分析的客户消息",
            "context_echo": context,
        }), 400

    # 2. Build enriched analysis message with conversation history
    analysis_message = _build_analysis_message(context)

    # 3. Resolve identifiers from candidates
    order_id, tracking_no, platform_trade_id, product_name = _resolve_identifiers(context)

    # 4. Enrich analysis message with identifiers
    if platform_trade_id and platform_trade_id not in analysis_message:
        analysis_message = f"{platform_trade_id} {analysis_message}"
    if not product_name:
        product_name = best_candidate_value(context.get("product_candidates", []))
    if product_name and product_name not in analysis_message:
        analysis_message = f"当前千牛侧边栏已识别商品：{product_name}\n{analysis_message}"

    source = context.get("source", "manual_simulation")
    scenario = payload.get("scenario", "")
    conversation_id = context.get("conversation_id", "qianniu")

    # 5. Delegate to unified AnalysisExecutionService
    reply_service = get_reply_service()
    from app.services.analysis_execution_service import execute_analysis
    response = execute_analysis(
        reply_service=reply_service,
        customer_message=analysis_message,
        order_id=order_id,
        tracking_no=tracking_no,
        conversation_id=conversation_id,
        product_name=product_name,
        product_candidates=context.get("product_candidates", []),
        copilot_context=context,
        source=source,
        scenario=scenario,
        final_orchestration=False,
    )

    # 6. 推荐已审核素材（不自动发送，仅作客服参考）
    recommended_assets = []
    reply_blocks = []
    reply_delivery = {"mode": "blocks", "auto_send_ready": False, "reason": "not_built"}
    try:
        from app.services.media_asset_service import build_reply_blocks, recommend_for_analyze_response, select_delivery_assets
        reco_i_id, reco_sku, reco_product_name, reco_product_id = _extract_media_identifiers(context)
        reco = recommend_for_analyze_response(
            response,
            customer_message=message,
            product_name=reco_product_name or None,
            i_id=reco_i_id,
            sku_code=reco_sku,
            product_id=reco_product_id,
        )
        recommended_assets = select_delivery_assets(reco.get("recommended_assets") or [], max_assets=1)
        block_result = build_reply_blocks(
            response.get("suggested_reply", ""),
            recommended_assets,
            requires_human_review=bool(response.get("requires_human_review")),
        )
        reply_blocks = block_result["reply_blocks"]
        reply_delivery = block_result["reply_delivery"]
    except Exception:
        pass

    try:
        from app.services.final_response_orchestrator import orchestrate_final_response
        response["recommended_assets"] = recommended_assets
        response["reply_blocks"] = reply_blocks
        response["reply_delivery"] = reply_delivery
        response = orchestrate_final_response(
            response,
            customer_message=message,
            copilot_context=context,
        )
        reply_blocks = response.get("reply_blocks", reply_blocks)
        reply_delivery = response.get("reply_delivery", reply_delivery)
    except Exception:
        pass

    # 7. Transform to copilot panel response format
    duration_ms = int((time.time() - t0) * 1000)
    response = _to_copilot_response(
        response,
        context,
        duration_ms,
        recommended_assets=recommended_assets,
        reply_blocks=reply_blocks,
        reply_delivery=reply_delivery,
    )

    return jsonify(response)


def _build_analysis_message(context: dict) -> str:
    message = context.get("customer_message", "").strip()
    history = context.get("conversation_history", []) or []
    if not history:
        return message

    lines = []
    role_names = {
        "customer": "客户",
        "agent": "客服",
        "system": "系统",
        "unknown": "未知",
    }
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        role = role_names.get((item.get("role") or "unknown").lower(), "未知")
        lines.append(f"{role}: {text}")

    if not lines:
        return message
    return (
        "以下是千牛当前会话最近消息，请结合上下文理解客户最后一句，"
        "不要把客服已回复内容当成客户问题。\n"
        + "\n".join(lines)
        + f"\n\n当前需要回复的客户最新消息：{message}"
    )


@copilot_bp.route("/api/copilot/feedback", methods=["POST"])
def api_copilot_feedback():
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip()
    valid_actions = ("accepted", "edited", "rejected", "escalated", "human_review")
    if action not in valid_actions:
        return jsonify({"ok": False, "error": f"action must be one of {valid_actions}"}), 400

    reject_reason = payload.get("reject_reason", "")
    if action == "rejected" and not reject_reason:
        return jsonify({"ok": False, "error": "reject_reason is required when action=rejected"}), 400

    # Look up server-side snapshot if message_id provided
    message_id = payload.get("message_id", "")
    snapshot = None
    snapshot_missing = False
    if message_id:
        try:
            from app.services.analysis_snapshot import get_snapshot
            snapshot = get_snapshot(message_id)
        except Exception:
            pass
        if not snapshot:
            snapshot_missing = True

    # Use snapshot data when available, fall back to client data for compatibility
    customer_message = payload.get("customer_message", "")
    suggested_reply = payload.get("suggested_reply", "")
    risk_level = payload.get("risk_level", "")
    execution_debug = payload.get("execution_debug", {})
    evidence_debug = payload.get("evidence_debug", {})
    used_knowledge_entry_ids = payload.get("used_knowledge_entry_ids", [])
    used_fact_tools = payload.get("used_fact_tools", "")

    if snapshot:
        customer_message = customer_message or snapshot.get("customer_message", "")
        suggested_reply = suggested_reply or snapshot.get("suggested_reply", "")
        risk_level = risk_level or snapshot.get("risk_level", "")
        try:
            execution_debug = json.loads(snapshot.get("execution_debug_json", "{}"))
        except Exception:
            pass
        try:
            evidence_debug = json.loads(snapshot.get("evidence_debug_json", "{}"))
        except Exception:
            pass
        try:
            used_knowledge_entry_ids = json.loads(snapshot.get("used_knowledge_entry_ids_json", "[]"))
        except Exception:
            pass
        used_fact_tools = used_fact_tools or snapshot.get("used_fact_tools_json", "")

    record = get_feedback_service().save(
        customer_message=customer_message,
        suggested_reply=suggested_reply,
        action=action,
        order_id=payload.get("order_id", ""),
        final_reply=payload.get("final_reply", ""),
        risk_level=risk_level,
        source=payload.get("source", "copilot_panel"),
        review_id=payload.get("review_id", ""),
        reject_reason=reject_reason,
        used_knowledge_entry_ids=used_knowledge_entry_ids,
        used_fact_tools=used_fact_tools,
        need_human_review=payload.get("need_human_review", False),
    )

    # Auto-create Bad Case candidate from server-side snapshot
    try:
        from app.services.bad_case_service import (
            should_auto_create_bad_case, create_bad_case_from_context, BadCaseStore,
        )
        should, reason = should_auto_create_bad_case(
            action=action,
            execution_debug=execution_debug if isinstance(execution_debug, dict) else None,
            evidence_debug=evidence_debug if isinstance(evidence_debug, dict) else None,
            final_reply=payload.get("final_reply", ""),
            suggested_reply=suggested_reply,
        )
        if should:
            create_bad_case_from_context(
                store=BadCaseStore(),
                action=action,
                reason=reason,
                execution_debug=execution_debug if isinstance(execution_debug, dict) else None,
                evidence_debug=evidence_debug if isinstance(evidence_debug, dict) else None,
                customer_message=customer_message,
                suggested_reply=suggested_reply,
                final_reply=payload.get("final_reply", ""),
                conversation_id=payload.get("conversation_id", "") or (snapshot.get("conversation_id", "") if snapshot else ""),
                scenario=payload.get("scenario", "") or (snapshot.get("scenario", "") if snapshot else ""),
                source=payload.get("source", "copilot_panel"),
                reject_reason=reject_reason,
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Bad Case auto-creation failed: %s", e)

    return jsonify({
        "ok": True,
        "record": record,
        "snapshot_missing": snapshot_missing,
    })


import json


@copilot_bp.route("/api/copilot/metrics", methods=["GET"])
def api_copilot_metrics():
    """Copilot panel metrics."""
    feedback_svc = get_feedback_service()
    stats = feedback_svc.get_stats()
    records = feedback_svc.load_all(limit=10000)

    high_risk_count = sum(1 for r in records if r.get("risk_level") == "high")
    reject_reasons = {}
    for r in records:
        if r.get("action") == "rejected" and r.get("reject_reason"):
            reason = r["reject_reason"]
            reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    top_reject = sorted(reject_reasons.items(), key=lambda x: -x[1])[:5]

    total = stats.get("total", 0)
    accepted = stats.get("accepted", 0)
    edited = stats.get("edited", 0)
    rejected = stats.get("rejected", 0)
    escalated = stats.get("escalated", 0)

    return jsonify({
        "total_suggestions": total,
        "accepted_count": accepted,
        "edited_count": edited,
        "rejected_count": rejected,
        "human_review_count": escalated,
        "acceptance_rate": round((accepted + edited) / total * 100, 1) if total else 0.0,
        "edit_rate": round(edited / total * 100, 1) if total else 0.0,
        "reject_rate": round(rejected / total * 100, 1) if total else 0.0,
        "high_risk_count": high_risk_count,
        "top_reject_reasons": top_reject,
        "tool_success_rate": _tool_success_rate(),
        "tool_timeout_rate": _tool_timeout_rate(),
        "jst_success_rate": _jst_success_rate(),
        "rag_used_rate": _rag_used_rate(),
        "hallucination_fallback_rate": _hallucination_rate(),
    })


def _tool_success_rate() -> float:
    try:
        from app.services.metrics_service import get_metrics_service
        m = get_metrics_service().get_snapshot()["counters"]
        total = m.get("jst_call_count", 0)
        if not total:
            return 0.0
        return round(m.get("jst_success_count", 0) / total * 100, 1)
    except Exception:
        return 0.0


def _tool_timeout_rate() -> float:
    try:
        from app.services.metrics_service import get_metrics_service
        m = get_metrics_service().get_snapshot()["counters"]
        total = m.get("jst_call_count", 0)
        if not total:
            return 0.0
        return round(m.get("jst_timeout_count", 0) / total * 100, 1)
    except Exception:
        return 0.0


def _jst_success_rate() -> float:
    return _tool_success_rate()


def _rag_used_rate() -> float:
    try:
        from app.services.metrics_service import get_metrics_service
        m = get_metrics_service().get_snapshot()["counters"]
        total = m.get("request_count", 0)
        if not total:
            return 0.0
        return round(m.get("rag_retrieval_count", 0) / total * 100, 1)
    except Exception:
        return 0.0


def _hallucination_rate() -> float:
    try:
        from app.services.metrics_service import get_metrics_service
        m = get_metrics_service().get_snapshot()["counters"]
        total = m.get("request_count", 0)
        if not total:
            return 0.0
        return round(m.get("hallucination_guard_block_count", 0) / total * 100, 1)
    except Exception:
        return 0.0
