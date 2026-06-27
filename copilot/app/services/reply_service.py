"""
回复建议服务 - 统一编排风险检测、上下文组装、LLM 调用、输出守卫、复核队列
使用 LangGraph 重构业务编排链路。
"""

from app.models.reply import ReplySuggestion
from app.llm.client import get_llm_client
from app.llm.prompts import build_system_prompt, build_user_message
from app.services.risk_service import RiskService
from app.services.context_builder import ContextBuilder
from app.services.output_guard import OutputGuard

import logging
import threading

logger = logging.getLogger(__name__)


def _safe_product_context_pack(pack: dict) -> dict:
    if not isinstance(pack, dict) or not pack:
        return {}
    profile = pack.get("structured_profile") or {}
    return {
        "identity": pack.get("identity", {}),
        "stats": pack.get("stats", {}),
        "structured_profile": {
            "product_id": profile.get("product_id"),
            "i_id": profile.get("i_id", ""),
            "product_name": profile.get("product_name", ""),
            "category": profile.get("category", {}),
            "answerable_fields": profile.get("answerable_fields", []),
            "specs": profile.get("specs", {}),
            "logistics": profile.get("logistics", {}),
            "warranty": profile.get("warranty", {}),
            "sku_list": profile.get("sku_list", [])[:20],
            "missing_fields": profile.get("missing_fields", []),
        } if profile else {},
        "facts": [
            {
                "entry_id": item.get("entry_id"),
                "title": item.get("title", ""),
                "source_type": item.get("source_type", ""),
                "fact_type": item.get("fact_type", ""),
                "rerank_score": item.get("rerank_score", 0),
                "direct_answer_allowed": item.get("evidence_allowed_for_direct_answer", True),
            }
            for item in (pack.get("facts") or [])[:8]
        ],
        "media_assets": (pack.get("media_assets") or [])[:12],
        "recommended_assets": (pack.get("recommended_assets") or [])[:5],
        "conversation_media_reference": pack.get("conversation_media_reference", {}),
        "generic_rules": [
            {
                "rule_key": item.get("rule_key", ""),
                "title": item.get("title", ""),
                "fact_type": item.get("fact_type", ""),
                "score": item.get("score", 0),
                "reply_template": item.get("reply_template", ""),
                "risk_level": item.get("risk_level", "low"),
                "auto_reply_allowed": item.get("auto_reply_allowed", True),
            }
            for item in (pack.get("generic_rules") or [])[:5]
        ],
        "evidence_pack": pack.get("evidence_pack", {}),
    }


def _canonical_intent_for_response(intent: str, message: str = "") -> str:
    """Normalize internal intent labels to the canonical forms expected by clients/tests."""
    intent = str(intent or "").strip()
    if intent == "promotion_query":
        return "promotion"
    if intent == "delivery_not_received":
        # Signed-but-not-received is a logistics dispute, not generic aftersales.
        # Pure delivery ETA questions can still fall back to logistics_eta.
        if "签收" in message or "没收到" in message or "没拿到" in message:
            return "delivery_not_received"
        return "logistics_eta"
    return intent


def _turn_understanding_from_context(copilot_context: dict | None) -> dict:
    if not isinstance(copilot_context, dict):
        return {}
    value = copilot_context.get("turn_understanding") or {}
    return value if isinstance(value, dict) else {}


def _apply_turn_understanding_contract_to_state(state: dict, copilot_context: dict | None) -> None:
    understanding = _turn_understanding_from_context(copilot_context)
    if not understanding:
        return
    state["turn_understanding"] = understanding
    expected_fact_type = str(
        understanding.get("expected_query_fact_type")
        or understanding.get("query_fact_type")
        or ""
    ).strip()
    if expected_fact_type:
        state["query_fact_type"] = expected_fact_type
        state["required_fact_types"] = [expected_fact_type]
        state.setdefault("evidence_debug", {})["expected_query_fact_type"] = expected_fact_type
    state["turn_actionability"] = str(understanding.get("turn_actionability") or "")
    state["turn_reply_strategy"] = str(understanding.get("reply_strategy") or "")


def _selected_evidence_count(result: dict) -> int:
    debug = result.get("evidence_debug") or {}
    selected = (
        debug.get("selected_evidence")
        or debug.get("evidence_selected")
        or result.get("selected_evidence")
        or result.get("evidence")
        or []
    )
    return len(selected) if isinstance(selected, list) else int(bool(selected))


def _apply_turn_understanding_contract_to_result(result: dict, copilot_context: dict | None) -> dict:
    understanding = _turn_understanding_from_context(copilot_context)
    if not understanding:
        return result
    result = dict(result or {})
    expected_fact_type = str(
        understanding.get("expected_query_fact_type")
        or understanding.get("query_fact_type")
        or ""
    ).strip()
    actionability = str(understanding.get("turn_actionability") or "")
    reply = str(result.get("suggested_reply") or "")
    debug = dict(result.get("evidence_debug") or {})
    answer_trace = dict(result.get("answer_trace") or {})
    actual_fact_type = str(result.get("query_fact_type") or debug.get("query_fact_type") or answer_trace.get("query_fact_type") or "")
    selected_count = _selected_evidence_count(result)

    if expected_fact_type:
        result["query_fact_type"] = expected_fact_type
        result["required_fact_types"] = [expected_fact_type]
        debug["query_fact_type"] = expected_fact_type
        debug["required_fact_types"] = [expected_fact_type]
        debug["expected_query_fact_type"] = expected_fact_type
        answer_trace["query_fact_type"] = expected_fact_type
        if not answer_trace.get("required_fact_types"):
            answer_trace["required_fact_types"] = [expected_fact_type]

    should_control = False
    reason = ""
    if actionability in {"context_update", "deictic_followup"}:
        should_control = _reply_has_product_fact_topic(reply) or bool(actual_fact_type)
        reason = f"turn_{actionability}_should_not_expand_product_fact"
    elif actionability == "actionable_question" and not expected_fact_type and _reply_has_product_fact_topic(reply):
        should_control = True
        reason = "query_fact_type_missing_should_not_expand_product_fact"
    elif expected_fact_type and actual_fact_type and actual_fact_type != expected_fact_type and not _fact_types_compatible(expected_fact_type, actual_fact_type):
        should_control = True
        reason = "turn_contract_fact_type_mismatch"
    elif expected_fact_type and not selected_count and not result.get("requires_human_review"):
        should_control = True
        reason = "actionable_turn_without_evidence_needs_review"

    if should_control:
        result["suggested_reply"] = _controlled_turn_contract_reply(expected_fact_type, actionability, copilot_context)
        result["requires_human_review"] = True
        result["reason_for_review"] = reason
        result["review_reason"] = reason
        result["generation_mode"] = "turn_contract_controlled_handoff"
        debug["turn_contract_controlled"] = True
        debug["turn_contract_control_reason"] = reason

    result["evidence_debug"] = debug
    result["answer_trace"] = answer_trace
    result.setdefault("trace_steps", []).append({
        "node": "turn_understanding_contract",
        "status": "applied",
        "summary": f"expected_query_fact_type={expected_fact_type or '-'}, actionability={actionability or '-'}",
    })
    try:
        from app.services.no_evidence_reply_policy_service import apply_no_evidence_reply_policy
        result = apply_no_evidence_reply_policy(result, copilot_context)
    except Exception as exc:
        logger.warning("no_evidence_reply_policy failed: %s", exc)
    return result


def _fact_types_compatible(expected: str, actual: str) -> bool:
    groups = (
        {"aftersales", "aftersales_policy", "after_sales"},
        {"installation", "accessory_usage"},
        {"logistics", "order_status", "delivery_not_received"},
    )
    if expected == actual:
        return True
    return any(expected in group and actual in group for group in groups)


def _reply_has_product_fact_topic(reply: str) -> bool:
    try:
        from app.services.real_conversation_turn_understanding_service import detect_reply_topics
        return bool(detect_reply_topics(reply))
    except Exception:
        product_terms = ("尺寸", "材质", "承重", "安装", "组装", "发货", "物流")
        return any(term in str(reply or "") for term in product_terms)


def _controlled_turn_contract_reply(
    expected_fact_type: str,
    actionability: str,
    copilot_context: dict | None = None,
) -> str:
    if actionability == "context_update":
        return "亲，收到，我先记录这个情况。后续如果还有具体问题，您把对应位置或情况发我，我再帮您核对。"
    if actionability == "deictic_followup":
        return "亲，这句需要结合上文、图片或具体位置才能准确判断。您可以把对应位置圈一下，或再发一张图，我帮您确认。"
    if expected_fact_type in {"aftersales", "after_sales", "aftersales_policy"}:
        return (
            "亲，您反馈的资料或实物可能不一致，我先按售后核对处理。\n"
            "麻烦您发一下对应资料截图和实物照片，我这边需要人工确认后，再给您准确的补发或处理方案。"
        )
    if expected_fact_type in {"installation", "accessory_usage"}:
        return (
            "亲，这个部件的位置或用途需要按具体款式核对。\n"
            "麻烦您发一下部件照片或对应页面截图，我这边人工确认后再回复，避免把配件说错。"
        )
    if expected_fact_type in {"dimensions", "space_fit"}:
        if _has_product_context_for_policy(copilot_context):
            return "亲，我已经看到当前商品信息了，但这款具体尺寸还需要对照尺寸图/商品资料确认。我先帮您核对，避免不同款式尺寸说混。"
        return "亲，这个需要结合具体款式和尺寸图核对。麻烦您发一下商品链接、截图或预留位置尺寸，我再帮您确认。"
    return "亲，这个细节需要结合具体商品资料核对。我先转人工确认后再回复您，避免给您说错。"


def _has_product_context_for_policy(copilot_context: dict | None) -> bool:
    if not isinstance(copilot_context, dict):
        return False
    summary = copilot_context.get("real_context_summary") or {}
    identity = copilot_context.get("real_context_product_identity") or {}
    return bool(
        (isinstance(summary, dict) and summary.get("has_product_context"))
        or (isinstance(identity, dict) and identity.get("has_resolved_product_context"))
        or copilot_context.get("product_name")
        or copilot_context.get("sku_code")
        or copilot_context.get("i_id")
        or copilot_context.get("product_candidates")
    )


class ReplyService:
    """回复建议服务 - 主编排器（LangGraph 驱动）"""

    def __init__(
        self,
        risk_service: RiskService,
        context_builder: ContextBuilder,
        output_guard: OutputGuard,
        forbidden_claims: list = None,
        review_queue_service=None,
        quality_check_service=None,
    ):
        self.risk_service = risk_service
        self.context_builder = context_builder
        self.output_guard = output_guard
        self._forbidden_claims = forbidden_claims or []
        self._review_queue_service = review_queue_service
        self._quality_check_service = quality_check_service
        self._live_jst_repo = None
        self._live_query_service = None

    def analyze(
        self,
        customer_message: str,
        order_id: str = "",
        tracking_no: str = "",
        conversation_id: str = "default",
        product_name: str = "",
        product_candidates: list | None = None,
        copilot_context: dict | None = None,
        image_attachments: list | None = None,
        request_id: str = "",
        message_id: str = "",
        source: str = "",
        scenario: str = "",
    ) -> ReplySuggestion:
        """
        分析客户消息，生成建议回复。
        使用 LangGraph 编排业务链路：
        normalize -> detect_intent -> risk_check -> build_context -> route -> query -> reply -> guard -> review
        """
        from app.agent.graph import customer_service_graph
        from app.services.real_context_product_identity_service import (
            augment_copilot_context_with_real_identity,
            augment_state_with_real_context_identity,
            merge_product_candidates,
        )

        # 构造初始状态（每次全新，不复用旧 state）
        state = {
            "customer_message": customer_message,
            "conversation_id": conversation_id or "default",
            "order_id": order_id,
            "tracking_no": tracking_no,
            "trace_steps": [],
        }
        try:
            from app.services.fact_type_service import classify_query_fact_type
            fact_type = classify_query_fact_type(customer_message).get("query_fact_type", "")
            if fact_type:
                state["query_fact_type"] = fact_type
        except Exception:
            pass
        slots = {}
        if copilot_context:
            copilot_context = augment_copilot_context_with_real_identity(copilot_context)
            product_candidates = merge_product_candidates(
                product_candidates or [],
                copilot_context.get("product_candidates") or [],
            )
            if not product_name:
                product_name = str(copilot_context.get("display_product_name") or copilot_context.get("product_name") or "").strip()

        if product_name:
            state["matched_product_name"] = product_name
            slots["product_name"] = product_name
        if product_candidates:
            state["product_candidates"] = product_candidates
        if copilot_context:
            state["copilot_context"] = copilot_context
            for key in ("sku_code", "sku_name", "i_id", "product_name"):
                value = str(copilot_context.get(key) or "").strip()
                if value:
                    slots[key] = value
                    if key == "product_name" and not state.get("matched_product_name"):
                        state["matched_product_name"] = value
        _apply_turn_understanding_contract_to_state(state, copilot_context)
        for candidate in product_candidates or []:
            if not isinstance(candidate, dict):
                continue
            candidate_type = str(candidate.get("type") or "").lower()
            value = str(candidate.get("value") or "").strip()
            if ("sku" in candidate_type) and value and not slots.get("sku_code"):
                slots["sku_code"] = value
            if "i_id" in candidate_type and value and not slots.get("i_id"):
                slots["i_id"] = value
            if not slots.get("product_name"):
                name = str(candidate.get("product_name") or candidate.get("name") or candidate.get("title") or "").strip()
                if name:
                    slots["product_name"] = name
                    state.setdefault("matched_product_name", name)
        if slots:
            state["slots"] = slots
        if copilot_context:
            augment_state_with_real_context_identity(state)
        if image_attachments:
            state["image_attachments"] = image_attachments
            state.setdefault("copilot_context", {})["image_attachments"] = image_attachments
            state["copilot_context"]["has_image_attachment"] = True

        # 调用 LangGraph
        try:
            result = customer_service_graph.invoke(state)
        except Exception as e:
            logger.error("LangGraph 执行失败: %s", e, exc_info=True)
            # 极端降级：返回安全回复
            result = self._extreme_fallback(customer_message, order_id, str(e))
        if isinstance(result, dict):
            result.setdefault("customer_message", customer_message)
        result = _apply_turn_understanding_contract_to_result(result, copilot_context)
        from app.services.final_response_orchestrator import ensure_sendable_reply_contract
        result = ensure_sendable_reply_contract(result)

        # 构建白名单 context_used
        context_used = self._build_context_used(result)

        evidence_debug = dict(result.get("evidence_debug", {}) or {})
        generic_service_rule_used = result.get("generic_service_rule_used") or _generic_rule_used_from_trace(result.get("trace_steps", []))
        if generic_service_rule_used:
            evidence_debug["generic_service_rule_used"] = generic_service_rule_used

        # 组装 ReplySuggestion
        data = {
            "intent": _canonical_intent_for_response(result.get("intent", ""), customer_message),
            "risk_level": result.get("risk_level", "low"),
            "customer_emotion": result.get("customer_emotion", ""),
            "need_lookup": [],
            "suggested_reply": result.get("suggested_reply", ""),
            "draft_reply": result.get("draft_reply", ""),
            "sendable_reply": result.get("sendable_reply", ""),
            "can_send": result.get("can_send", False),
            "reply_status": result.get("reply_status", "blocked"),
            "block_reasons": result.get("block_reasons", []),
            "reply_style": result.get("reply_style", ""),
            "policy_warnings": result.get("policy_warnings", []),
            "action_proposal": result.get("action_proposal", {}),
            "requires_human_review": result.get("requires_human_review", False),
            "reason_for_review": result.get("reason_for_review", result.get("review_reason", "")),
            "reply_tone": result.get("reply_tone", ""),
            "evidence_used": result.get("evidence_used", ""),
            "tools_to_call": result.get("tools_to_call", []),
            "error": result.get("error", ""),
            "guard_warnings": result.get("guard_warnings", []),
            "context_used": context_used,
            "skill_route": {
                "skill": result.get("skill", ""),
                "intent": _canonical_intent_for_response(result.get("intent", ""), customer_message),
                "matched_keywords": result.get("matched_keywords", []),
            },
            "matched_sops": result.get("sop_scenarios", []),
            "matched_templates": result.get("reply_templates", []),
            "data_quality_warnings": result.get("data_quality_warnings", []),
            "trace_steps": self._reorder_trace_steps(result.get("trace_steps", [])),
            "evidence_debug": evidence_debug,
            "needs_clarification": result.get("needs_clarification", False),
            "used_fact_tool": result.get("used_fact_tool", ""),
            "used_endpoint": result.get("used_endpoint", ""),
            "identifier_type": result.get("identifier_type", ""),
            "generic_service_rule_used": generic_service_rule_used,
        }

        suggestion = ReplySuggestion.from_dict(data)

        # Build unified execution_debug from graph result
        try:
            from app.services.execution_debug_builder import build_execution_debug
            suggestion.execution_debug = build_execution_debug(
                result=result,
                request_id=request_id or conversation_id or "default",
                message_id=message_id or "",
                conversation_id=conversation_id or "default",
                source=source or "manual_simulation",
                scenario=scenario or "",
                request_duration_ms=0,
                copilot_context=copilot_context,
            )
        except Exception as e:
            logger.warning("execution_debug 构建失败: %s", e)

        # 高风险入复核队列
        if suggestion.requires_human_review and self._review_queue_service:
            try:
                queued = self._review_queue_service.enqueue(
                    suggestion_dict=suggestion.to_dict(),
                    customer_message=customer_message,
                    order_id=order_id,
                )
                suggestion.review_id = queued.get("id", "")
            except Exception as e:
                logger.warning("复核队列入队失败: %s", e)

        return suggestion

    def _build_context_used(self, result: dict) -> dict:
        """通过白名单构建 context_used，不含隐私字段"""
        order = result.get("live_order") or result.get("order")
        product_knowledge = result.get("product_knowledge", [])
        safe_pk = []
        for pk in product_knowledge:
            safe_pk.append({
                k: v for k, v in pk.items()
                if k not in ("buyer_id", "receiver_name", "receiver_phone",
                             "receiver_address", "receiver_state", "receiver_city")
            })

        # 知识库调试字段
        evidence = result.get("evidence", {})
        knowledge_evidence = result.get("knowledge_evidence", [])
        retrieved_chunks = result.get("retrieved_chunks", [])
        product_context_pack = result.get("product_context_pack") or {}

        # evidence 分层计数
        evidence_counts = {
            "order_facts_count": len(evidence.get("order_facts", [])),
            "logistics_facts_count": len(evidence.get("logistics_facts", [])),
            "product_facts_count": len(evidence.get("product_facts", [])),
            "policy_facts_count": len(evidence.get("policy_facts", [])),
            "sop_evidence_count": len(evidence.get("sop_evidence", [])),
            "template_evidence_count": len(evidence.get("template_evidence", [])),
            "faq_evidence_count": len(evidence.get("faq_evidence", [])),
            "unknowns_count": len(evidence.get("unknowns", [])),
            "conflicts_count": len(evidence.get("conflicts", [])),
        }

        summary = {
            "skill_route": result.get("skill_route", {}),
            "sources": [],
            "has_order": bool(order),
            "has_logistics": bool(result.get("logistics") or result.get("live_logistics")),
            "product_knowledge_count": len(product_knowledge),
            "knowledge_count": len(result.get("knowledge", [])),
            "sop_count": len(result.get("sop_scenarios", [])),
            "template_count": len(result.get("reply_templates", [])),
            "data_source": result.get("data_source", ""),
            "order_status": "",
            "order_items": [],
            # 策略路由调试字段
            "response_strategy": result.get("response_strategy", ""),
            "router_source": result.get("router_source", ""),
            "router_confidence": result.get("router_confidence", 0),
            "router_reason": result.get("router_reason", ""),
            "normalized_intent": result.get("intent", ""),
            "selected_tool": result.get("selected_tool", ""),
            "identifier_type": result.get("identifier_type", ""),
            "identifier_value": result.get("identifier_value", ""),
            "answer_mode": result.get("answer_mode", ""),
            "conversation_context_summary": result.get("conversation_context_summary", {}),
            "customer_urgency": result.get("customer_urgency", ""),
            "customer_concern": result.get("customer_concern", ""),
            "reply_goal": result.get("reply_goal", ""),
            "reply_structure": result.get("reply_structure", []),
            "missing_slots": result.get("missing_slots", []),
            "context_updated": result.get("context_updated", False),
            "generation_mode": result.get("generation_mode", ""),
            "llm_used": result.get("llm_used", False),
            "hallucination_guard": result.get("hallucination_guard", {}),
            "allowed_source_types": result.get("allowed_source_types", []),
            "used_fact_tools": result.get("fact_tools", []),
            "retrieved_knowledge_count": len(retrieved_chunks),
            "selected_evidence_count": len(knowledge_evidence),
            "evidence_sources": evidence.get("evidence_sources", []),
            "image_analysis": result.get("copilot_context", {}).get("image_analysis", []),
            "used_knowledge_entry_ids": result.get("used_knowledge_entry_ids") or list(set(
                c.get("entry_id") for c in knowledge_evidence if c.get("entry_id")
            )),
            "used_knowledge_titles": result.get("used_knowledge_titles") or list(set(
                c.get("title", "") for c in knowledge_evidence if c.get("title")
            )),
            "product_context_pack": _safe_product_context_pack(product_context_pack),
            **evidence_counts,
        }

        # sources
        sources = []
        if result.get("live_order"):
            sources.append("live_jst")
        elif order:
            sources.append("local_order")
        if product_knowledge:
            sources.append("product_knowledge")
        if result.get("knowledge"):
            sources.append("knowledge_base")
        if not sources:
            sources.append("fallback")
        summary["sources"] = sources

        # 订单安全字段
        if order:
            summary["order_status"] = order.get("status", "")
            items = order.get("items", [])
            if items:
                summary["order_items"] = [
                    {
                        "name": i.get("name", ""),
                        "sku_name": i.get("sku_name", i.get("name", "")),
                        "quantity": i.get("qty", i.get("quantity", 1)),
                        "category": i.get("category", ""),
                    }
                    for i in items[:3]
                ]

        return summary

    def _reorder_trace_steps(self, trace_steps: list) -> list:
        """调整 trace_steps 顺序以兼容现有测试：
        - 保留 normalize_input 放最前
        - 将 reply_generated 移到最后
        """
        norm = [s for s in trace_steps if s.get("step") == "normalize_input"]
        context_load = [s for s in trace_steps if (s.get("node") or s.get("step")) == "load_conversation_context"]
        parallel = [
            s for s in trace_steps
            if (s.get("node") or s.get("step")) in ("parallel_understanding", "decision_fusion")
        ]
        rest = [
            s for s in trace_steps
            if s.get("step") != "normalize_input"
            and (s.get("node") or s.get("step")) != "load_conversation_context"
            and (s.get("node") or s.get("step")) not in ("parallel_understanding", "decision_fusion")
        ]
        detect = [s for s in rest if (s.get("node") or s.get("step")) in ("detect_intent", "intent_detected")]
        rest_without_detect = [
            s for s in rest
            if (s.get("node") or s.get("step")) not in ("detect_intent", "intent_detected")
        ]
        reply_steps = [s for s in rest_without_detect if s.get("step") == "reply_generated"]
        others = [s for s in rest_without_detect if s.get("step") != "reply_generated"]
        return norm + detect + parallel + others + reply_steps

    def _extreme_fallback(self, customer_message: str, order_id: str, error: str) -> dict:
        """Graph 执行失败时的极端降级"""
        return {
            "intent": "其他",
            "risk_level": "low",
            "customer_emotion": "未知",
            "suggested_reply": "您好，系统暂时繁忙，请您稍后再试。如有紧急问题，请联系人工客服。",
            "reply_style": "简洁专业",
            "policy_warnings": [],
            "action_proposal": {"action_type": "无", "reason": ""},
            "requires_human_review": False,
            "error": "",
            "guard_warnings": [],
            "trace_steps": [
                {"node": "graph_fallback", "step": "graph_fallback", "status": "error", "summary": "系统暂时繁忙"}
            ],
        }

    # ------------------------------------------------------------------
    # 以下为保留的旧方法（供内部节点或兼容调用使用）
    # ------------------------------------------------------------------

    def _inject_tracking_reply(self, result: dict, tracking_info: dict, tracking_no: str) -> dict:
        """当 LLM 未包含物流信息时，用规则补充"""
        state_text = tracking_info.get("state_text", "未知")
        courier = tracking_info.get("courier_name", "")
        data = tracking_info.get("data", [])
        latest = data[0] if data else {}
        reply = f"亲亲，已为您查询到单号 {tracking_no} 的物流信息：当前状态为【{state_text}】"
        if courier:
            reply += f"，快递公司：{courier}"
        if latest.get("time"):
            reply += f"。最新轨迹：{latest['time']}"
        if latest.get("context"):
            reply += f" {latest['context'][:60]}"
        reply += "。如您需要进一步协助，欢迎随时联系我们哦～"
        result["suggested_reply"] = reply
        result["intent"] = "查物流"
        return result

    def _fetch_live_order_data(self, order_id: str) -> dict | None:
        """调用聚水潭实时 API 查询订单+物流+售后数据"""
        try:
            if self._live_query_service is None:
                from app.repositories.live_jst_repository import LiveJSTRepository
                from app.repositories.live_dingtalk_repository import LiveDingTalkRepository
                from app.services.live_query_service import LiveQueryService
                self._live_jst_repo = LiveJSTRepository()
                self._live_dingtalk_repo = LiveDingTalkRepository()
                self._live_query_service = LiveQueryService(
                    self._live_jst_repo, self._live_dingtalk_repo
                )
            return self._live_query_service.query_order_status(order_id)
        except Exception as e:
            logger.warning("聚水潭实时查询失败(order=%s): %s", order_id, e)
            return None

    def _generate_rule_based_reply(
        self,
        customer_message: str,
        context: dict,
        risk_hint: str,
    ) -> dict:
        """当 LLM 未配置时，使用规则引擎生成回复建议（保留供节点调用）"""
        skill_route = context.get("skill_route", {})
        intent = skill_route.get("intent", "general")

        templates = context.get("reply_templates", [])
        sops = context.get("sop_scenarios", [])

        # 选择最佳话术模板
        suggested_reply = ""
        if templates:
            suggested_reply = templates[0].get("template", "")

        # 兜底通用回复
        if not suggested_reply:
            suggested_reply = "您好，感谢您的咨询，我们会尽快为您处理，请您耐心等待。"

        # 简单情绪识别
        customer_emotion = "中性"
        negative_kw = ["急", "催", "怎么还没", "投诉", "差", "坏", "骗", "差评", "退货", "退款"]
        positive_kw = ["谢谢", "感谢", "好评", "满意", "喜欢"]
        if any(kw in customer_message for kw in negative_kw):
            customer_emotion = "焦急/不满"
        elif any(kw in customer_message for kw in positive_kw):
            customer_emotion = "满意"

        # 建议动作
        action_type = "无"
        reason = ""
        if sops:
            valid_steps = [
                step for step in sops[0].get("steps", [])
                if isinstance(step, str) and len(step) < 50
                and not any(b in step for b in ["Codex", ".py", "markdown", "```", "POST /", "GET /", "- code:", "- \""])
            ]
            if valid_steps:
                action_type = valid_steps[0]
                reason = f"根据SOP「{sops[0].get('scenario', '')}」"

        # 回复风格
        reply_style = sops[0].get("reply_style", "") if sops else "温和专业"

        # 规则提醒
        policy_warnings = []
        if sops and sops[0].get("forbidden_claims"):
            valid_claims = [c for c in sops[0]["forbidden_claims"] if isinstance(c, str) and len(c) < 40]
            if valid_claims:
                policy_warnings.append(f"禁止承诺: {', '.join(valid_claims[:2])}")
        if sops and sops[0].get("escalation_triggers"):
            valid_triggers = [c for c in sops[0]["escalation_triggers"] if isinstance(c, str) and len(c) < 40]
            if valid_triggers:
                policy_warnings.append(f"升级触发: {', '.join(valid_triggers[:2])}")

        # 如果提供了订单号，尝试根据订单真实状态生成针对性回复
        order_info = context.get("order")
        if order_info:
            suggested_reply = self._inject_order_status_reply(
                suggested_reply, customer_message, order_info, context
            )
        else:
            # 无订单号时的场景化回复
            is_shipping_intent = any(kw in customer_message for kw in [
                "发货", "物流", "快递", "到哪", "几天到", "什么时候到", "多久到",
                "运单", "单号", "到货", "配送", "签收", "没到",
            ])
            if is_shipping_intent:
                product_name = self._extract_product_name(customer_message, context)
                if product_name:
                    suggested_reply = self._generate_product_shipping_reply(
                        product_name, customer_message, context
                    )
                else:
                    suggested_reply = (
                        "亲亲，为了帮您准确查询物流信息，麻烦提供一下您的订单号哦～\n"
                        "如果您记得购买的商品名称，也可以告诉我，我帮您查看发货时效。"
                    )
            elif any(kw in customer_message for kw in ["退款", "退货", "售后", "质量", "破损"]):
                suggested_reply = "亲亲，为了帮您快速处理，麻烦提供一下您的订单号，我马上帮您核实处理。"
            elif "订单" not in suggested_reply and "查询" not in suggested_reply:
                suggested_reply += "\n如需查询具体信息，请提供您的订单号哦～"

        result = {
            "intent": intent,
            "risk_level": risk_hint,
            "customer_emotion": customer_emotion,
            "need_lookup": [],
            "suggested_reply": suggested_reply,
            "reply_style": reply_style,
            "policy_warnings": policy_warnings,
            "action_proposal": {"action_type": action_type, "reason": reason},
            "requires_human_review": risk_hint in ("high", "medium"),
            "error": "",
            "guard_warnings": [],
        }

        # 用质检服务检查生成的回复
        if self._quality_check_service:
            qc = self._quality_check_service.check(
                customer_message=customer_message,
                reply=suggested_reply,
            )
            serious_types = {"forbidden_claim", "offline_trade", "rude_tone", "refund_promise"}
            result["guard_warnings"] = [
                v["message"] for v in qc.get("violations", [])
                if v.get("type") in serious_types
            ]
            if qc.get("requires_human_review") and any(v.get("type") in serious_types for v in qc.get("violations", [])):
                result["requires_human_review"] = True
                result["risk_level"] = "high"

        return result

    def _extract_product_name(self, customer_message: str, context: dict) -> str:
        """从客户消息中提取商品名"""
        product_knowledge = context.get("product_knowledge", [])
        if product_knowledge:
            return product_knowledge[0].get("name", "")
        product_keywords = ["书桌", "书架", "餐椅", "椅子", "置物架", "桌子", "床", "沙发", "柜子", "茶几"]
        for kw in product_keywords:
            if kw in customer_message:
                return kw
        return ""

    def _generate_product_shipping_reply(
        self, product_name: str, customer_message: str, context: dict
    ) -> str:
        """根据产品信息生成发货/物流时效回复（无订单号时）"""
        knowledge = context.get("knowledge", [])
        shipping_info = ""
        for entry in knowledge:
            content = entry.get("content", "")
            if "发货时效" in content or "物流方式" in content or "快递" in content:
                shipping_info = content[:300]
                break

        reply = f"亲亲，关于{product_name}的发货情况："
        if shipping_info:
            if "48小时" in shipping_info:
                reply += "现货商品一般付款后48小时内发货（工作日）。"
            if "中通" in shipping_info or "韵达" in shipping_info:
                reply += "默认使用中通/韵达快递。"
            if "德邦" in shipping_info or "大件" in shipping_info:
                reply += "大件家具使用德邦/安能物流。"
        else:
            reply += "我们一般会在付款后48小时内安排发货（工作日）。"

        reply += "\n以上为一般参考时效，具体以实际物流为准。"
        reply += "\n麻烦您提供一下订单号，我可以帮您查询更准确的物流信息哦～"
        return reply

    def _inject_order_status_reply(
        self, base_reply: str, customer_message: str, order: dict, context: dict
    ) -> str:
        """根据订单真实状态，生成有针对性的回复"""
        status = order.get("status", "")
        shop_status = order.get("shop_status", "")
        logistics = context.get("logistics", [])
        refunds = context.get("refund", [])
        items = order.get("items", [])

        item_names = [i.get("name", "") for i in items if i.get("name")]
        items_text = "、".join(item_names[:3]) if item_names else "您购买的商品"

        reply = base_reply

        if refunds and any(kw in customer_message for kw in ["退款", "退货", "退钱", "退差"]):
            refund_status = refunds[0].get("status", "处理中") if isinstance(refunds, list) and refunds else "处理中"
            reply = f"亲，关于您的退款申请，目前状态是「{refund_status}」。我们会尽快为您处理，请您耐心等待。"
            return reply

        if any(kw in customer_message for kw in ["发货", "物流", "快递", "到哪", "到哪了", "什么时候到", "多久到"]):
            l_id = order.get("l_id", "")
            logistics_company = order.get("logistics_company", "")
            send_date = order.get("send_date", "")

            if status in ("已签收", "已完成"):
                reply = f"亲，您的订单（{items_text}）已签收。如对商品有任何问题，请及时联系我们处理哦。"
            elif l_id and logistics_company:
                reply = f"亲，您的订单（{items_text}）已由{logistics_company}发货，物流单号：{l_id}。"
                if send_date:
                    reply += f"发货日期：{send_date}。"
                reply += "具体物流动态可以关注快递官方通知，或提供订单号让我帮您查询。"
            elif status in ("已发货", "发货中"):
                reply = f"亲，您的订单（{items_text}）已安排发货，正在等待快递公司揽收，请耐心等待。"
            elif status in ("待发货", "备货中", "待处理"):
                reply = f"亲，您的订单（{items_text}）正在仓库加紧备货中，会尽快安排发货，请耐心等待。"
            else:
                reply = f"亲，您的订单（{items_text}）当前状态：{status}。我帮您跟进一下，稍后给您回复具体进度。"
            return reply

        if any(kw in customer_message for kw in ["订单", "状态", "进度", "情况"]):
            sign_time = order.get("sign_time", "")
            if status in ("已签收", "已完成") and sign_time:
                reply = f"亲，您的订单（{items_text}）已于 {sign_time} 签收。如有任何问题请随时联系。"
            elif status:
                reply = f"亲，您的订单（{items_text}）当前状态：{status}。"
                if logistics and isinstance(logistics, list) and logistics[0].get("l_id"):
                    l = logistics[0]
                    reply += f"物流公司：{l.get('logistics_company','')}，单号：{l.get('l_id','')}。"
                reply += "如有疑问请随时联系。"
            return reply

        if any(kw in customer_message for kw in ["破损", "损坏", "质量", "瑕疵", "坏", "烂"]):
            reply = f"亲，非常抱歉给您带来不好的体验。您的订单（{items_text}）如遇破损或质量问题，我们可以为您安排补发或退换货。请您提供一下问题照片，我们马上处理。"
            return reply

        if "订单" not in base_reply and "商品" not in base_reply:
            reply = f"亲，已为您查到订单（{items_text}）当前状态：{status}。"
            reply += f"\n{base_reply}"

        return reply

    def _build_knowledge_text(self, context: dict) -> str:
        """从上下文中提取知识文本（供 prompt 使用）"""
        parts = []

        knowledge = context.get("knowledge", [])
        if knowledge:
            parts.append("## 通用知识")
            for entry in knowledge:
                parts.append(f"- {entry['title']}: {entry['content'][:400]}")

        pk = context.get("product_knowledge", [])
        if pk:
            parts.append("\n## 产品知识")
            for p in pk:
                line = f"- {p.get('name', '?')} ({p.get('category', '')})"
                if p.get("price_range"):
                    line += f" 价格{p.get('price_range')}"
                if p.get("stock_available") is not None:
                    line += " 有库存" if p.get("stock_available") else " 无库存"
                if p.get("agent_level"):
                    line += f" [完整度:{p.get('agent_level')}"
                    if p.get("completeness_score"):
                        line += f"/{p.get('completeness_score')}分]"
                    else:
                        line += "]"
                parts.append(line)

        warnings = context.get("data_quality_warnings", [])
        if warnings:
            parts.append("\n## 数据质量提醒")
            for w in warnings:
                parts.append(f"- ⚠️ {w}")

        sops = context.get("sop_scenarios", [])
        if sops:
            parts.append("\n## SOP 参考")
            for s in sops:
                parts.append(f"- [{s.get('scenario', '?')}] 风格:{s.get('reply_style', '')}")
                if s.get("steps"):
                    parts.append(f"  步骤: {' → '.join(s['steps'][:3])}")
                if s.get("forbidden_claims"):
                    parts.append(f"  禁止: {', '.join(s['forbidden_claims'][:3])}")

        templates = context.get("reply_templates", [])
        if templates:
            parts.append("\n## 话术参考")
            for t in templates:
                parts.append(f"- [{t.get('scenario', '?')}] {t.get('template', '')[:200]}")

        skill = context.get("skill_route", {})
        if skill:
            parts.append(f"\n## 识别场景: {skill.get('skill', 'general')} | 意图: {skill.get('intent', '')}")

        return "\n".join(parts)


def _generic_rule_used_from_trace(trace_steps: list) -> dict:
    for step in reversed(trace_steps or []):
        if not isinstance(step, dict):
            continue
        used = step.get("generic_service_rule_used")
        if isinstance(used, dict) and used.get("rule_key"):
            return {
                "rule_key": used.get("rule_key", ""),
                "title": used.get("title", ""),
                "fact_type": used.get("fact_type", ""),
                "score": used.get("score", 0),
            }
    return {}


def format_suggestion(result: ReplySuggestion) -> str:
    """格式化输出建议（命令行用）"""
    lines = []
    lines.append("=" * 50)
    lines.append("  AI 客服建议")
    lines.append("=" * 50)

    risk = result.risk_level
    risk_emoji = {"high": "[!!!高风险]", "medium": "[!中风险]", "low": "[低风险]"}
    lines.append(f"\n{risk_emoji.get(risk, '')} 意图: {result.intent}")
    lines.append(f"客户情绪: {result.customer_emotion}")
    lines.append(f"回复风格: {result.reply_style}")

    if result.requires_human_review:
        lines.append("\n[!!! 需要人工复核]")

    if result.policy_warnings:
        lines.append("\n[规则提醒]")
        for w in result.policy_warnings:
            lines.append(f"  - {w}")

    lines.append("\n[建议回复]")
    lines.append(f"  {result.suggested_reply}")

    action = result.action_proposal
    if action and action.action_type and action.action_type != "无":
        lines.append(f"\n[建议动作] {action.action_type}")
        lines.append(f"  原因: {action.reason}")

    if result.error:
        lines.append(f"\n[错误] {result.error}")

    lines.append("=" * 50)
    return "\n".join(lines)
