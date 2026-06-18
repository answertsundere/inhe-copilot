"""
build_response 节点 - 最终组装
将回复、证据、trace、guard_warnings 组装为最终 AgentState
"""

import logging
import time

from app.services.reply_style_service import beautify_customer_reply
from app.services.fact_type_service import FACT_TYPE_LABELS
from app.agent.query_understanding import refresh_query_understanding

logger = logging.getLogger(__name__)


_PRODUCT_CARD_REQUIRED_FACT_TYPES = {
    "material",
    "certification_report",
    "pinch_safety",
    "safety_small_parts",
    "installation",
    "detachable",
    "odor",
    "dimensions",
    "load_capacity",
    "stability",
    "age_range",
    "cleaning_care",
}


def build_response(state: dict) -> dict:
    """组装最终回复"""
    t0 = time.time()
    suggested_reply = state.get("suggested_reply", "")
    suggested_reply = _append_aftersales_issue_followup(suggested_reply, state)
    suggested_reply = _append_image_degrade_notice(suggested_reply, state)
    suggested_reply = beautify_customer_reply(suggested_reply, state)
    suggested_reply = _ensure_tracking_reference(suggested_reply, state)
    guard_warnings = state.get("guard_warnings", [])
    requires_human_review = state.get("requires_human_review", False)
    review_reason = state.get("review_reason", "")

    risk_level = state.get("risk_level", "low")
    if risk_level in ("high", "critical") and not requires_human_review:
        requires_human_review = True
        review_reason = review_reason or "高风险内容需人工复核"
    if state.get("intent") == "material_safety" and not requires_human_review:
        requires_human_review = True
        review_reason = review_reason or "材质/安全类商品事实需复核"

    evidence_review_reason = _evidence_requires_human_review(state)
    if evidence_review_reason:
        requires_human_review = True
        review_reason = review_reason or evidence_review_reason

    # 原则8：回复里承诺了人工核实/转人工，requires_human_review 必须与回复一致
    reply_review_reason = _reply_promises_human_review(suggested_reply)
    if reply_review_reason:
        requires_human_review = True
        review_reason = review_reason or reply_review_reason

    evidence = state.get("evidence", {})
    answer_type = state.get("answer_type", "")

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "build_response",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "answer_type": answer_type,
        "summary": f"组装最终回复: answer_type={answer_type}, guard_warnings={len(guard_warnings)}, human_review={requires_human_review}",
    }

    # 组装 evidence_debug（摘要，不泄露隐私）
    # Phase 2.5: 每条证据包含 fact_review_status, fact_confidence, high_risk_fact_fields,
    # evidence_allowed_for_direct_answer, matched_entry_id, matched_title
    def _fact_debug(f: dict) -> dict:
        return {
            "fact": f.get("fact", "")[:100],
            "source_type": f.get("source_type", ""),
            "confidence": f.get("confidence", ""),
            "entry_status": f.get("entry_status", ""),
            "fact_review_status": f.get("fact_review_status", ""),
            "matched_entry_id": f.get("matched_entry_id") or f.get("entry_id"),
            "matched_title": f.get("matched_title") or f.get("title", ""),
            "query_fact_type": f.get("query_fact_type", ""),
            "evidence_fact_type": f.get("evidence_fact_type") or f.get("fact_type", ""),
            "high_risk_fact_fields": f.get("high_risk_fact_fields") or f.get("high_risk_fields", []),
            "evidence_allowed_for_direct_answer": f.get("evidence_allowed_for_direct_answer", True),
            "direct_answer_allowed": f.get("direct_answer_allowed", f.get("evidence_allowed_for_direct_answer", True)),
            "requires_human_review": f.get("requires_human_review", f.get("needs_human_review", False)),
            "gate_status": f.get("gate_status", ""),
            "gate_reasons": f.get("gate_reasons", []),
        }

    evidence_debug = {
        "order_facts": [_fact_debug(f) for f in evidence.get("order_facts", [])],
        "logistics_facts": [_fact_debug(f) for f in evidence.get("logistics_facts", [])],
        "product_facts": [_fact_debug(f) for f in evidence.get("product_facts", [])],
        "policy_facts": [_fact_debug(f) for f in evidence.get("policy_facts", [])],
        "sop_evidence": [_fact_debug(f) for f in evidence.get("sop_evidence", [])],
        "template_evidence": [_fact_debug(f) for f in evidence.get("template_evidence", [])],
        "faq_evidence": [_fact_debug(f) for f in evidence.get("faq_evidence", [])],
        "unknowns": [_fact_debug(f) for f in evidence.get("unknowns", [])],
        "conflicts": [_fact_debug(f) for f in evidence.get("conflicts", [])],
    }

    # retrieved_chunks / filtered_evidence 摘要
    retrieved_chunks_summary = []
    for c in state.get("retrieved_chunks", [])[:10]:
        retrieved_chunks_summary.append({
            "chunk_id": c.get("chunk_id", ""),
            "entry_id": c.get("entry_id", ""),
            "source_type": c.get("source_type", ""),
            "fact_type": c.get("fact_type", ""),
            "intent": c.get("intent", ""),
            "score": c.get("score", 0),
            "text_score": c.get("text_score", 0),
            "vector_score": c.get("vector_score", 0),
            "scope_score": c.get("scope_score", 0),
            "source_confidence": c.get("source_confidence", ""),
            "rerank_score": c.get("rerank_score", 0),
            "mismatch_reason": c.get("mismatch_reason", ""),
            "semantic_alignment": c.get("semantic_alignment", {}),
            "chunk_preview": c.get("chunk_text", "")[:80],
        })

    filtered_evidence_summary = []
    for c in state.get("filtered_evidence", [])[:10]:
        filtered_evidence_summary.append({
            "chunk_id": c.get("chunk_id", ""),
            "entry_id": c.get("entry_id", ""),
            "source_type": c.get("source_type", ""),
            "query_fact_type": c.get("query_fact_type", ""),
            "evidence_fact_type": c.get("evidence_fact_type") or c.get("fact_type", ""),
            "confidence": c.get("confidence", ""),
            "reference_only": c.get("reference_only", False),
            "score": c.get("score", 0),
            "text_score": c.get("text_score", 0),
            "vector_score": c.get("vector_score", 0),
            "scope_score": c.get("scope_score", 0),
            "source_confidence": c.get("source_confidence", ""),
            "rerank_score": c.get("rerank_score", 0),
            "mismatch_reason": c.get("mismatch_reason", ""),
            "gate_status": c.get("gate_status", ""),
            "gate_reasons": c.get("gate_reasons", []),
            "semantic_alignment": c.get("semantic_alignment", {}),
            "direct_answer_allowed": c.get("direct_answer_allowed", c.get("evidence_allowed_for_direct_answer", True)),
            "requires_human_review": c.get("requires_human_review", c.get("needs_human_review", False)),
            "evidence_allowed_for_exact_answer": c.get("evidence_allowed_for_exact_answer", False),
            "chunk_preview": c.get("chunk_text", "")[:80],
        })

    knowledge_evidence_summary = []
    for c in state.get("knowledge_evidence", [])[:10]:
        knowledge_evidence_summary.append({
            "chunk_id": c.get("chunk_id", ""),
            "entry_id": c.get("entry_id", ""),
            "source_type": c.get("source_type", ""),
            "query_fact_type": c.get("query_fact_type", ""),
            "evidence_fact_type": c.get("evidence_fact_type") or c.get("fact_type", ""),
            "score": c.get("score", 0),
            "rerank_score": c.get("rerank_score", 0),
            "mismatch_reason": c.get("mismatch_reason", ""),
            "gate_status": c.get("gate_status", ""),
            "gate_reasons": c.get("gate_reasons", []),
            "semantic_alignment": c.get("semantic_alignment", {}),
            "direct_answer_allowed": c.get("direct_answer_allowed", c.get("evidence_allowed_for_direct_answer", True)),
            "requires_human_review": c.get("requires_human_review", c.get("needs_human_review", False)),
            "evidence_allowed_for_exact_answer": c.get("evidence_allowed_for_exact_answer", False),
            "chunk_preview": c.get("chunk_text", "")[:80],
        })

    rejected_evidence_summary = []
    for c in state.get("rejected_evidence", [])[:10]:
        rejected_evidence_summary.append({
            "chunk_id": c.get("chunk_id", ""),
            "entry_id": c.get("entry_id", ""),
            "source_type": c.get("source_type", ""),
            "query_fact_type": c.get("query_fact_type", ""),
            "evidence_fact_type": c.get("evidence_fact_type") or c.get("fact_type", ""),
            "score": c.get("score", 0),
            "rerank_score": c.get("rerank_score", 0),
            "rejection_reasons": c.get("rejection_reasons") or c.get("reasons") or c.get("gate_reasons", []),
            "semantic_alignment": c.get("semantic_alignment", {}),
            "chunk_preview": c.get("chunk_text", "")[:80],
        })

    evidence_debug["retrieved_chunks_summary"] = retrieved_chunks_summary
    evidence_debug["filtered_evidence_summary"] = filtered_evidence_summary
    evidence_debug["knowledge_evidence_summary"] = knowledge_evidence_summary
    evidence_debug["selected_evidence"] = knowledge_evidence_summary or [
        item for item in filtered_evidence_summary
        if item.get("direct_answer_allowed") and item.get("gate_status") != "blocked"
    ][:10]
    evidence_debug["rejected_evidence"] = rejected_evidence_summary
    evidence_debug["evidence_gate_summary"] = _summarize_evidence_gate(knowledge_evidence_summary)
    product_context_pack = state.get("product_context_pack") or {}
    generic_service_rule_used = state.get("generic_service_rule_used") or _generic_rule_used_from_trace(state.get("trace_steps", []))
    evidence_debug["product_context_pack_stats"] = state.get("product_context_pack_stats", product_context_pack.get("stats", {}))
    evidence_debug["product_context_pack_summary"] = _summarize_product_context_pack(product_context_pack)
    evidence_evaluation = (product_context_pack.get("evidence_pack") or {}).get("evidence_evaluation") or []
    if evidence_evaluation:
        evidence_debug["evidence_evaluation"] = evidence_evaluation
        evidence_debug["selected_evidence"] = [
            item for item in evidence_evaluation
            if isinstance(item, dict) and item.get("selected") and item.get("source_type") != "product_media"
        ][:10] or evidence_debug["selected_evidence"]
        evaluation_rejected = [
            item for item in evidence_evaluation
            if isinstance(item, dict) and not item.get("selected")
        ][:10]
        if evaluation_rejected:
            evidence_debug["rejected_evidence"] = evaluation_rejected
    evidence_debug["selected_assets"] = [
        {
            "asset_id": item.get("asset_id") or item.get("id"),
            "asset_type": item.get("asset_type", ""),
            "asset_title": item.get("asset_title", ""),
            "product_name": item.get("product_name", ""),
            "send_mode": item.get("send_mode", "manual"),
        }
        for item in (product_context_pack.get("recommended_assets") or [])[:5]
        if isinstance(item, dict)
    ]
    evidence_debug["answer_mode"] = state.get("answer_mode", "")
    evidence_debug["query_fact_type"] = state.get("query_fact_type", "")
    evidence_debug["query_fact_type_label"] = state.get("query_fact_type_label", "")
    evidence_debug["query_fact_type_confidence"] = state.get("query_fact_type_confidence", state.get("confidence", 0))
    evidence_debug["query_fact_type_terms"] = state.get("query_fact_type_terms", state.get("matched_terms", []))
    evidence_debug["query_fact_type_source"] = state.get("query_fact_type_source", state.get("source", ""))
    evidence_debug["query_fact_type_reason"] = state.get("query_fact_type_reason", "")
    evidence_debug["secondary_fact_types"] = state.get("secondary_fact_types", [])
    evidence_debug["query_fact_type_risk_hint"] = state.get("query_fact_type_risk_hint", "")
    evidence_debug["semantic_query"] = state.get("semantic_query", {})
    evidence_debug["needs_visual_asset"] = state.get("needs_visual_asset", False)
    evidence_debug["knowledge_gap"] = _summarize_knowledge_gap(state)
    evidence_debug["router_source"] = state.get("router_source", "")
    evidence_debug["router_confidence"] = state.get("router_confidence", 0)
    evidence_debug["router_reason"] = state.get("router_reason", "")
    evidence_debug["normalized_intent"] = state.get("intent", "")
    evidence_debug["selected_tool"] = state.get("selected_tool", "")
    evidence_debug["identifier_type"] = state.get("identifier_type", "")
    evidence_debug["identifier_value"] = state.get("identifier_value", "")
    evidence_debug["conversation_context_summary"] = state.get("conversation_context_summary", {})
    evidence_debug["current_query"] = state.get("current_query", state.get("normalized_message", state.get("customer_message", "")))
    evidence_debug["retrieval_query"] = state.get("retrieval_query", state.get("rag_search_query", ""))
    evidence_debug["history_snapshot"] = state.get("history_snapshot", {})
    evidence_debug["generated_context"] = state.get("generated_context", {})
    evidence_debug["context_reset_reason"] = state.get("context_reset_reason", "")
    evidence_debug["customer_emotion"] = state.get("customer_emotion", "")
    evidence_debug["customer_urgency"] = state.get("customer_urgency", "")
    evidence_debug["customer_concern"] = state.get("customer_concern", "")
    evidence_debug["reply_goal"] = state.get("reply_goal", "")
    evidence_debug["reply_structure"] = state.get("reply_structure", [])
    evidence_debug["missing_slots"] = state.get("missing_slots", [])
    evidence_debug["context_updated"] = state.get("context_updated", False)
    evidence_debug["generation_mode"] = state.get("generation_mode", "")
    evidence_debug["llm_used"] = state.get("llm_used", False)
    evidence_debug["generic_service_rule_used"] = generic_service_rule_used
    evidence_debug["hallucination_guard"] = state.get("hallucination_guard", {
        "passed": True,
        "unsupported_terms": [],
        "fallback_used": False,
    })
    evidence_debug["used_knowledge_entry_ids"] = state.get("used_knowledge_entry_ids", list({
        c.get("entry_id") for c in state.get("knowledge_evidence", []) if c.get("entry_id")
    }))
    evidence_debug["used_knowledge_titles"] = state.get("used_knowledge_titles", list({
        c.get("title", "") for c in state.get("knowledge_evidence", []) if c.get("title")
    }))

    # 记录查询路由信息
    evidence_debug["used_fact_tool"] = state.get("used_fact_tool", "")
    evidence_debug["used_endpoint"] = state.get("used_endpoint", "")
    evidence_debug["used_identifier_type"] = state.get("identifier_type", "")
    evidence_debug["order_product_identity"] = state.get("order_product_identity", {})
    evidence_debug["product_identity_source"] = state.get("product_identity_source", "")

    # 记录 unverified_fact_fields（来自 evidence_builder）
    evidence_debug["unverified_fact_fields"] = evidence.get("unverified_fact_fields", [])

    # Phase 2.5: Knowledge Evidence Quality Gate 结果
    evidence_debug["evidence_quality"] = state.get("evidence_quality", {})

    # Tool Registry 调试字段
    trace_steps = state.get("trace_steps", [])
    evidence_debug["tool_plan"] = [c.get("tool_name") for c in state.get("tool_plan", [])]
    evidence_debug["tool_results_summary"] = {
        k: {
            "found": v.get("found"),
            "count": v.get("count"),
            "endpoint": v.get("endpoint", ""),
            "query_type": v.get("query_type", ""),
            "safe_fallback_reason": v.get("safe_fallback_reason", ""),
            "attempted_paths": v.get("attempted_paths", []),
            "debug": v.get("debug", {}),
        }
        for k, v in state.get("tool_results", {}).items() if isinstance(v, dict)
    }
    evidence_debug["tool_executor_used"] = any(
        t.get("node") == "tool_executor" and t.get("status") == "success"
        for t in trace_steps
    )
    evidence_debug["tool_executor_fallback_used"] = "jst_fallback" in {
        t.get("summary", "") for t in trace_steps
    } or any("fallback" in t.get("summary", "").lower() for t in trace_steps)
    evidence_debug["tool_planner_source"] = state.get("tool_planner_source", "")
    evidence_debug["rag_retrieval_mode"] = state.get("rag_retrieval_mode", "")

    # Parallel Understanding Layer is Phase 1 observation-only data.
    # Keep it in debug output without overriding the legacy main route.
    fusion = state.get("decision_fusion", {}) or {}
    evidence_debug["parallel_understanding"] = state.get("parallel_understanding", {})
    evidence_debug["decision_fusion"] = fusion
    evidence_debug["safety_contract"] = state.get("safety_contract", {})
    evidence_debug["analyzer_durations"] = state.get("analyzer_durations", {})
    evidence_debug["fusion_reasons"] = state.get("fusion_reasons", [])
    evidence_debug["final_intent"] = state.get("final_intent", "")
    evidence_debug["secondary_intents"] = state.get("secondary_intents", [])
    evidence_debug["parallel_observation_mode"] = state.get("parallel_observation_mode", False)
    evidence_debug["fusion_required_tools"] = fusion.get("required_tools", [])
    evidence_debug["fusion_allowed_tools"] = fusion.get("allowed_tools", [])
    evidence_debug["fusion_forbidden_tools"] = fusion.get("forbidden_tools", [])
    evidence_debug["fusion_allowed_source_types"] = fusion.get("allowed_source_types", [])
    evidence_debug["fusion_forbidden_source_types"] = fusion.get("forbidden_source_types", [])

    # 节点耗时统计
    node_durations = {}
    for t in trace_steps:
        node = t.get("node", "")
        dur = t.get("duration_ms", 0)
        if node and dur:
            node_durations[node] = dur
    evidence_debug["node_durations"] = node_durations
    evidence_debug["jst_duration_ms"] = node_durations.get("jst_live_query", 0)
    evidence_debug["rag_duration_ms"] = node_durations.get("rag_retrieve", 0)
    evidence_debug["llm_duration_ms"] = node_durations.get("generate_reply", 0)
    evidence_debug["tool_executor_duration_ms"] = node_durations.get("tool_executor", 0)

    sufficiency = _compute_evidence_sufficiency(state)
    evidence_debug["evidence_sufficient"] = sufficiency["evidence_sufficient"]
    evidence_debug["answer_relevance_passed"] = sufficiency["answer_relevance_passed"]
    evidence_debug["direct_answer_supported"] = sufficiency["direct_answer_supported"]
    evidence_debug["missing_required_fact_fields"] = sufficiency["missing_required_fact_fields"]
    evidence_debug["needs_clarification"] = sufficiency["needs_clarification"]
    evidence_debug["quality_result"] = {
        "stage": "build_response_evidence_sufficiency",
        "passed": bool(sufficiency["answer_relevance_passed"]),
        "evidence_sufficient": bool(sufficiency["evidence_sufficient"]),
        "direct_answer_supported": bool(sufficiency["direct_answer_supported"]),
        "missing_required_fact_fields": sufficiency["missing_required_fact_fields"],
    }

    verified_evidence = _summarize_verified_evidence(evidence)
    tools_to_call = _summarize_tools_to_call(state)
    reply_tone = _infer_reply_tone(state, requires_human_review)
    generated_context = state.get("generated_context") or {
        "current_query": state.get("current_query", state.get("normalized_message", state.get("customer_message", ""))),
        "retrieval_query": state.get("retrieval_query", state.get("rag_search_query", "")),
        "history_in_retrieval": False,
        "product_context_pack_stats": state.get("product_context_pack_stats", product_context_pack.get("stats", {})),
        "evidence_counts": {
            "product_facts": len(evidence.get("product_facts", []) or []),
            "policy_facts": len(evidence.get("policy_facts", []) or []),
            "faq_evidence": len(evidence.get("faq_evidence", []) or []),
            "sop_evidence": len(evidence.get("sop_evidence", []) or []),
            "unknowns": len(evidence.get("unknowns", []) or []),
            "conflicts": len(evidence.get("conflicts", []) or []),
        },
    }
    generation_context = state.get("generation_context") or {
        **generated_context,
        "history_context": state.get("history_snapshot", {}),
        "selected_evidence": evidence_debug["selected_evidence"],
        "rejected_evidence": evidence_debug["rejected_evidence"],
        "risk_hints": {
            "risk_level": risk_level,
            "requires_human_review": requires_human_review,
            "guard_warnings": guard_warnings,
        },
    }
    query_understanding = refresh_query_understanding(
        state,
        retrieval_query=generated_context.get("retrieval_query", ""),
        generation_context=generation_context,
        context_reset_reason=state.get("context_reset_reason", ""),
    )
    evidence_debug["generated_context"] = generated_context
    evidence_debug["generation_context"] = generation_context
    evidence_debug["query_understanding"] = query_understanding

    logger.debug("build_response: reply assembled, warnings=%d", len(guard_warnings))
    return {
        "suggested_reply": suggested_reply,
        "requires_human_review": requires_human_review,
        "review_reason": review_reason,
        "reason_for_review": review_reason,
        "reply_tone": reply_tone,
        "evidence_used": verified_evidence,
        "tools_to_call": tools_to_call,
        "guard_warnings": guard_warnings,
        "evidence": evidence,
        "evidence_debug": evidence_debug,
        "product_context_pack": product_context_pack,
        "product_context_pack_stats": state.get("product_context_pack_stats", product_context_pack.get("stats", {})),
        "current_query": generated_context["current_query"],
        "retrieval_query": generated_context["retrieval_query"],
        "generated_context": generated_context,
        "generation_context": generation_context,
        "query_understanding": query_understanding,
        "history_snapshot": state.get("history_snapshot", {}),
        "context_reset_reason": state.get("context_reset_reason", ""),
        "answer_mode": state.get("answer_mode", ""),
        "router_source": state.get("router_source", ""),
        "router_confidence": state.get("router_confidence", 0),
        "router_reason": state.get("router_reason", ""),
        "selected_tool": state.get("selected_tool", ""),
        "identifier_type": state.get("identifier_type", ""),
        "identifier_value": state.get("identifier_value", ""),
        "conversation_context_summary": state.get("conversation_context_summary", {}),
        "customer_urgency": state.get("customer_urgency", ""),
        "customer_concern": state.get("customer_concern", ""),
        "reply_goal": state.get("reply_goal", ""),
        "reply_structure": state.get("reply_structure", []),
        "missing_slots": state.get("missing_slots", []),
        "context_updated": state.get("context_updated", False),
        "generation_mode": state.get("generation_mode", ""),
        "llm_used": state.get("llm_used", False),
        "generic_service_rule_used": generic_service_rule_used,
        "hallucination_guard": state.get("hallucination_guard", {}),
        "used_knowledge_entry_ids": evidence_debug["used_knowledge_entry_ids"],
        "used_knowledge_titles": evidence_debug["used_knowledge_titles"],
        "used_fact_tool": state.get("used_fact_tool", ""),
        "used_endpoint": state.get("used_endpoint", ""),
        "trace_steps": state.get("trace_steps", []) + [trace],
        "evidence_sufficient": sufficiency["evidence_sufficient"],
        "answer_relevance_passed": sufficiency["answer_relevance_passed"],
        "direct_answer_supported": sufficiency["direct_answer_supported"],
        "missing_required_fact_fields": sufficiency["missing_required_fact_fields"],
        "needs_clarification": sufficiency["needs_clarification"],
    }


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


def _compute_evidence_sufficiency(state: dict) -> dict:
    """计算证据是否足以直接回答当前问题（事实类型必须匹配）。"""
    intent = state.get("intent", "")
    answer_mode = state.get("answer_mode", "")
    query_fact_type = state.get("query_fact_type", "")
    product_pack = state.get("product_context_pack") or {}
    card_evidence = (
        state.get("product_card_evidence_pack")
        or product_pack.get("evidence_pack")
        or {}
    )
    card_answerability = str(card_evidence.get("answerability") or "")
    needs_clarification = state.get("needs_clarification", False) or intent == "needs_clarification"

    if needs_clarification or answer_mode == "no_evidence_clarification":
        return {
            "evidence_sufficient": False,
            "answer_relevance_passed": False,
            "direct_answer_supported": False,
            "missing_required_fact_fields": ["具体问题/图片/异常位置"],
            "needs_clarification": True,
        }

    # 纯政策类意图：政策本身就是直接回答依据
    pure_policy_intents = {
        "invoice", "price_protection", "price_promotion", "promotion_query",
        "stock_query", "gift_missing", "aftersales",
    }
    # 事实依赖型政策/指南：必须有与 query_fact_type 匹配的证据
    fact_dependent_modes = {
        "exact_faq_answer", "product_fact_answer", "installation_guide",
    }
    fact_dependent_intents = {
        "material_safety", "child_safety", "competitor_compare", "odor_question",
        "cleaning_care", "image_attachment", "installation",
    }

    # 收集所有可能用于直接回答的证据
    candidate_items = (
        state.get("knowledge_evidence", [])
        + state.get("filtered_evidence", [])
        + state.get("evidence", {}).get("product_facts", [])
        + state.get("evidence", {}).get("faq_evidence", [])
    )
    card_fact_items = card_evidence.get("matched_facts") or []
    if isinstance(card_fact_items, list):
        candidate_items += [item for item in card_fact_items if isinstance(item, dict)]
    card_media_items = card_evidence.get("matched_media") or []
    if isinstance(card_media_items, list):
        candidate_items += [item for item in card_media_items if isinstance(item, dict)]

    direct_answer_supported = answer_mode in (
        {"exact_faq_answer", "product_fact_answer", "policy_grounded_answer",
         "verified", "installation_guide", "aftersales_policy"}
    )
    if card_answerability in {"direct_answer", "media_supported"}:
        direct_answer_supported = True

    used_ids = set(state.get("used_knowledge_entry_ids", []) or [])
    if not used_ids:
        used_ids = {
            item.get("entry_id") or item.get("matched_entry_id") or item.get("chunk_id") or item.get("asset_id")
            for item in candidate_items
            if isinstance(item, dict) and (
                item.get("entry_id") or item.get("matched_entry_id") or item.get("chunk_id") or item.get("asset_id")
            )
        }
    if not used_ids:
        direct_answer_supported = False

    has_matching_fact = False
    if query_fact_type:
        matched_fields = card_evidence.get("matched_fields") or []
        if isinstance(matched_fields, list) and query_fact_type in matched_fields:
            has_matching_fact = True
        for item in candidate_items:
            ev_ft = item.get("evidence_fact_type") or item.get("fact_type") or ""
            if ev_ft and ev_ft == query_fact_type:
                has_matching_fact = True
                break

    answer_relevance_passed = False
    if direct_answer_supported:
        if answer_mode in fact_dependent_modes or intent in fact_dependent_intents:
            # 必须有问题事实类型与证据事实类型一致的证据
            answer_relevance_passed = bool(query_fact_type and has_matching_fact)
        elif intent in pure_policy_intents:
            # 政策类：有政策证据即视为相关
            answer_relevance_passed = True
        elif answer_mode == "policy_grounded_answer":
            # 其他 policy_grounded_answer（如 cleaning_care 无事实时）：需要匹配事实
            answer_relevance_passed = bool(query_fact_type and has_matching_fact)
        else:
            answer_relevance_passed = True

    evidence_sufficient = direct_answer_supported and answer_relevance_passed
    if (
        query_fact_type in _PRODUCT_CARD_REQUIRED_FACT_TYPES
        and card_answerability in {"missing_product_fact", "no_product_profile", "no_product_identity"}
        and not has_matching_fact
    ):
        evidence_sufficient = False
        answer_relevance_passed = False

    missing_required_fact_fields = []
    if not evidence_sufficient:
        card_missing = card_evidence.get("missing_fields") or []
        if isinstance(card_missing, list) and card_missing:
            missing_required_fact_fields.extend([
                FACT_TYPE_LABELS.get(str(field), str(field))
                for field in card_missing
            ])
        elif query_fact_type:
            missing_required_fact_fields.append(FACT_TYPE_LABELS.get(query_fact_type, query_fact_type))
        else:
            missing_required_fact_fields.append("具体问题/图片/异常位置")

    return {
        "evidence_sufficient": evidence_sufficient,
        "answer_relevance_passed": answer_relevance_passed,
        "direct_answer_supported": direct_answer_supported,
        "missing_required_fact_fields": missing_required_fact_fields,
        "needs_clarification": needs_clarification,
    }


def _summarize_product_context_pack(pack: dict) -> dict:
    if not isinstance(pack, dict) or not pack:
        return {}
    profile = pack.get("structured_profile") or {}
    media_assets = pack.get("media_assets") or []
    recommended_assets = pack.get("recommended_assets") or []
    generic_rules = pack.get("generic_rules") or []
    return {
        "identity": pack.get("identity", {}),
        "stats": pack.get("stats", {}),
        "evidence_pack": pack.get("evidence_pack", {}),
        "structured_profile": {
            "product_id": profile.get("product_id"),
            "i_id": profile.get("i_id", ""),
            "product_name": profile.get("product_name", ""),
            "category": profile.get("category", {}),
            "answerable_fields": profile.get("answerable_fields", []),
            "spec_keys": list((profile.get("specs") or {}).keys())[:20],
            "logistics_keys": list((profile.get("logistics") or {}).keys())[:20],
            "warranty_keys": list((profile.get("warranty") or {}).keys())[:20],
        } if profile else {},
        "fact_titles": [item.get("title", "") for item in (pack.get("facts") or [])[:8]],
        "generic_rule_titles": [item.get("title", "") for item in generic_rules[:5]],
        "media_assets": [
            {
                "asset_id": item.get("asset_id") or item.get("id"),
                "asset_type": item.get("asset_type", ""),
                "asset_title": item.get("asset_title", ""),
                "product_name": item.get("product_name", ""),
            }
            for item in media_assets[:8]
        ],
        "recommended_assets": [
            {
                "asset_id": item.get("asset_id") or item.get("id"),
                "asset_type": item.get("asset_type", ""),
                "asset_title": item.get("asset_title", ""),
                "product_name": item.get("product_name", ""),
            }
            for item in recommended_assets[:5]
        ],
    }


def _summarize_verified_evidence(evidence: dict) -> str:
    rows = []
    bucket_order = [
        "product_facts", "faq_evidence", "policy_facts", "template_evidence",
        "sop_evidence", "logistics_facts", "order_facts",
    ]
    template_evidence = evidence.get("template_evidence", []) or []
    if any(str(item.get("entry_id", "")).startswith("builtin_") for item in template_evidence):
        bucket_order = [
            "template_evidence", "product_facts", "faq_evidence", "policy_facts",
            "sop_evidence", "logistics_facts", "order_facts",
        ]
    for bucket in bucket_order:
        for item in evidence.get(bucket, []) or []:
            review_status = item.get("fact_review_status") or item.get("entry_status") or item.get("confidence")
            if review_status not in ("verified", "published", "high"):
                continue
            title = item.get("matched_title") or item.get("title") or item.get("source_type") or bucket
            entry_id = item.get("matched_entry_id") or item.get("entry_id") or item.get("chunk_id") or ""
            label = f"{title}({entry_id})" if entry_id else str(title)
            if label and label not in rows:
                rows.append(label)
    return "；".join(rows[:5])


def _summarize_evidence_gate(rows: list[dict]) -> dict:
    summary = {
        "total": len(rows or []),
        "allowed": 0,
        "blocked": 0,
        "reference_only": 0,
        "unknown": 0,
        "reasons": {},
    }
    for row in rows or []:
        status = row.get("gate_status") or "unknown"
        if status not in ("allowed", "blocked", "reference_only"):
            status = "unknown"
        summary[status] += 1
        for reason in row.get("gate_reasons", []) or []:
            summary["reasons"][reason] = summary["reasons"].get(reason, 0) + 1
    return summary


def _summarize_knowledge_gap(state: dict) -> dict:
    """Summarize missing knowledge for product/RAG misses."""
    if state.get("response_strategy") != "product_question":
        return {}

    tool_results = state.get("tool_results", {}) or {}
    rag_result = tool_results.get("rag_search_tool") if isinstance(tool_results, dict) else None
    rag_ran = isinstance(rag_result, dict)
    retrieved_count = len(state.get("retrieved_chunks", []) or [])
    knowledge_count = len(state.get("knowledge_evidence", []) or [])
    if not rag_ran or retrieved_count or knowledge_count:
        return {}

    identity = state.get("order_product_identity") or {}
    slots = state.get("slots", {}) or {}
    fact_type = state.get("query_fact_type", "")
    fact_label = state.get("query_fact_type_label", "") or fact_type
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or slots.get("product_name", "")
    )
    sku = slots.get("sku_code") or identity.get("sku_id") or identity.get("i_id") or ""
    rag_debug = rag_result.get("debug", {})

    return {
        "type": "rag_miss",
        "needs_department": "货品/客服",
        "missing_fact_type": fact_type,
        "missing_fact_label": fact_label,
        "product_name": product_name,
        "sku": sku,
        "retrieval_query": rag_debug.get("query", ""),
        "product_scope": rag_debug.get("product_scope", []),
        "sku_scope": rag_debug.get("sku_scope", []),
        "action": "补充对应商品的已审核问答/商品事实，并发布后更新索引",
    }


def _summarize_tools_to_call(state: dict) -> list[str]:
    tool_names = []
    for call in state.get("tool_plan", []) or []:
        if isinstance(call, dict) and call.get("tool_name"):
            tool_names.append(call["tool_name"])
    tool_names.extend(state.get("required_tools", []) or [])
    used_fact_tool = state.get("used_fact_tool")
    if used_fact_tool:
        tool_names.append(used_fact_tool)

    mapped = []
    for name in tool_names:
        label = {
            "product_resolver_tool": "ProductIdentityResolver",
            "rag_search_tool": "RAG",
            "template_select_tool": "RAG",
            "jst_lookup_order_tool": "JST订单查询",
            "jst_lookup_outbound_tool": "JST订单/出库查询",
            "jst_lookup_tracking_tool": "JST物流查询",
            "sop_lookup_tool": "SOP",
        }.get(name, name)
        if label and label not in mapped:
            mapped.append(label)
    return mapped


def _append_aftersales_issue_followup(reply: str, state: dict) -> str:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    fusion = state.get("decision_fusion") or {}
    final_intent = fusion.get("final_intent", "")
    has_after_sales_issue = final_intent in {"missing_item", "wrong_item", "damaged_item"}
    if not has_after_sales_issue:
        has_after_sales_issue = any(term in msg for term in (
            "\u4e0d\u662f\u6211\u62cd\u7684",
            "\u53d1\u9519",
            "\u9519\u53d1",
            "\u5c11\u4e86\u914d\u4ef6",
            "\u5c11\u914d\u4ef6",
            "\u5c11\u4ef6",
            "\u7f3a\u4ef6",
            "\u6f0f\u53d1",
            "\u7834\u635f",
        ))
    if not has_after_sales_issue:
        return reply
    if any(term in (reply or "") for term in ("\u5c11\u4ef6", "\u7f3a\u4ef6", "\u53d1\u9519", "\u9519\u53d1", "\u4e0d\u662f\u6211\u62cd\u7684")):
        return reply
    if final_intent == "wrong_item" or any(term in msg for term in ("\u4e0d\u662f\u6211\u62cd\u7684", "\u53d1\u9519", "\u9519\u53d1")):
        followup = (
            "\n\n另外，您说的是发错商品问题，这个可以按售后流程核对退货、换货或补发处理。"
            "我会先核对订单商品和实物情况；如果方便，补充收到的商品整体图、外箱面单和发错位置，"
            "我这边核实后再给您明确处理路径。"
        )
    elif final_intent == "missing_item" or any(term in msg for term in ("\u5c11\u4e86\u914d\u4ef6", "\u5c11\u914d\u4ef6", "\u5c11\u4ef6", "\u7f3a\u4ef6", "\u6f0f\u53d1")):
        followup = (
            "\n\n另外，您说的是少件/缺配件问题，这个需要先帮您核对发货记录和实物情况。"
            "麻烦您发一下订单截图、收到的商品整体图、外箱面单和缺少配件的位置或清单，"
            "我这边核实后再按情况给您处理补发或退换方案。"
        )
    else:
        followup = (
            "\n\n另外，您反馈的售后问题需要先帮您核对订单和实物情况。"
            "麻烦您发一下订单截图、收到的商品整体图和外箱面单，"
            "我这边核实后再按情况给您处理。"
        )
    return (reply or "").strip() + followup


def _append_image_degrade_notice(reply: str, state: dict) -> str:
    image_results = (state.get("copilot_context") or {}).get("image_analysis") or []
    degraded = any(
        isinstance(item, dict)
        and (item.get("fallback_to_text") or item.get("success") is False)
        and ("vlm_timeout_fallback" in (item.get("warnings") or []) or item.get("fallback_to_text"))
        for item in image_results
    )
    if not degraded:
        return reply
    text = reply or ""
    if "图片细节" in text or "未识别清楚" in text:
        return text
    notice = (
        "\n\n图片细节这边可能看不清，麻烦您再补充一下想核对的位置或问题，"
        "我不会只按未识别清楚的图片来判断，避免给您说错。"
    )
    return text.strip() + notice


def _ensure_tracking_reference(reply: str, state: dict) -> str:
    if state.get("intent") != "delivery_not_received":
        return reply
    trace = state.get("logistics_trace") or {}
    order = state.get("live_order") or state.get("order") or {}
    tracking_no = str(trace.get("tracking_no") or order.get("l_id") or "").strip()
    carrier = str(trace.get("carrier") or trace.get("logistics_company") or order.get("logistics_company") or "").strip()
    if not tracking_no or tracking_no in (reply or ""):
        return reply
    prefix = f"{carrier} " if carrier else ""
    return (reply or "").strip() + f"\n我先按这个物流单号帮您继续核实：{prefix}{tracking_no}。"



def _evidence_requires_human_review(state: dict) -> str:
    for item in state.get("knowledge_evidence", []) or []:
        if item.get("requires_human_review") or item.get("needs_human_review"):
            reasons = item.get("gate_reasons") or []
            if "absolute_stability_request" in reasons:
                return "客户询问绝对稳定或绝对不倒，涉及宝宝使用安全，需要人工复核后回复"
            if "semantic_high_risk_stability" in reasons:
                return "客户询问宝宝使用场景下的稳定/防倾倒安全，需要人工复核后回复"
            if "unverified_high_risk_fact" in reasons:
                return "高风险商品事实尚未完成审核，需要人工复核后回复"
            return "RAG 证据门控要求人工复核"
    for item in state.get("filtered_evidence", []) or []:
        if item.get("requires_human_review") or item.get("needs_human_review"):
            return "RAG 证据门控要求人工复核"
    return ""


# 原则8：回复中承诺了人工核实/转人工的措辞时，必须与 requires_human_review 一致
_HUMAN_REVIEW_REPLY_PHRASES = (
    "转人工", "转给人工", "人工核实", "人工复核", "人工确认",
    "帮您核实", "帮您继续核实", "帮您转", "核实后再回复", "核实后再给",
    "需要客服", "客服确认", "客服核实", "货品同事", "货品核实",
    "转货品", "升级给主管", "升级处理", "帮您升级",
)


def _reply_promises_human_review(reply: str) -> str:
    """如果回复里承诺了人工核实/转人工，返回 reason，否则返回空串。"""
    text = reply or ""
    for phrase in _HUMAN_REVIEW_REPLY_PHRASES:
        if phrase in text:
            return "最终回复包含人工处理动作"
    return ""


def _infer_reply_tone(state: dict, requires_human_review: bool) -> str:
    if requires_human_review or state.get("risk_level") in ("high", "critical"):
        return "empathetic"
    intent = state.get("intent", "")
    if intent in (
        "product_question", "product_consult", "child_safety", "odor_question",
        "competitor_compare", "cleaning_care", "material_safety", "image_attachment",
    ):
        return "warm"
    return "professional"
