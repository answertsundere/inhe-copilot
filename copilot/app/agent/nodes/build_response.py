"""
build_response 节点 - 最终组装
将回复、证据、trace、guard_warnings 组装为最终 AgentState
"""

import logging
import time

from app.services.reply_style_service import beautify_customer_reply

logger = logging.getLogger(__name__)


def build_response(state: dict) -> dict:
    """组装最终回复"""
    t0 = time.time()
    suggested_reply = state.get("suggested_reply", "")
    suggested_reply = _append_aftersales_issue_followup(suggested_reply, state)
    suggested_reply = beautify_customer_reply(suggested_reply, state)
    guard_warnings = state.get("guard_warnings", [])
    requires_human_review = state.get("requires_human_review", False)
    review_reason = state.get("review_reason", "")

    risk_level = state.get("risk_level", "low")
    if risk_level in ("high", "critical") and not requires_human_review:
        requires_human_review = True
        review_reason = review_reason or "高风险内容需人工复核"

    evidence_review_reason = _evidence_requires_human_review(state)
    if evidence_review_reason:
        requires_human_review = True
        review_reason = review_reason or evidence_review_reason

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
            "direct_answer_allowed": c.get("direct_answer_allowed", c.get("evidence_allowed_for_direct_answer", True)),
            "requires_human_review": c.get("requires_human_review", c.get("needs_human_review", False)),
            "evidence_allowed_for_exact_answer": c.get("evidence_allowed_for_exact_answer", False),
            "chunk_preview": c.get("chunk_text", "")[:80],
        })

    evidence_debug["retrieved_chunks_summary"] = retrieved_chunks_summary
    evidence_debug["filtered_evidence_summary"] = filtered_evidence_summary
    evidence_debug["knowledge_evidence_summary"] = knowledge_evidence_summary
    evidence_debug["evidence_gate_summary"] = _summarize_evidence_gate(knowledge_evidence_summary)
    evidence_debug["answer_mode"] = state.get("answer_mode", "")
    evidence_debug["query_fact_type"] = state.get("query_fact_type", "")
    evidence_debug["query_fact_type_label"] = state.get("query_fact_type_label", "")
    evidence_debug["query_fact_type_confidence"] = state.get("query_fact_type_confidence", state.get("confidence", 0))
    evidence_debug["query_fact_type_terms"] = state.get("query_fact_type_terms", state.get("matched_terms", []))
    evidence_debug["query_fact_type_source"] = state.get("query_fact_type_source", state.get("source", ""))
    evidence_debug["query_fact_type_reason"] = state.get("query_fact_type_reason", "")
    evidence_debug["secondary_fact_types"] = state.get("secondary_fact_types", [])
    evidence_debug["query_fact_type_risk_hint"] = state.get("query_fact_type_risk_hint", "")
    evidence_debug["knowledge_gap"] = _summarize_knowledge_gap(state)
    evidence_debug["router_source"] = state.get("router_source", "")
    evidence_debug["router_confidence"] = state.get("router_confidence", 0)
    evidence_debug["router_reason"] = state.get("router_reason", "")
    evidence_debug["normalized_intent"] = state.get("intent", "")
    evidence_debug["selected_tool"] = state.get("selected_tool", "")
    evidence_debug["identifier_type"] = state.get("identifier_type", "")
    evidence_debug["identifier_value"] = state.get("identifier_value", "")
    evidence_debug["conversation_context_summary"] = state.get("conversation_context_summary", {})
    evidence_debug["customer_emotion"] = state.get("customer_emotion", "")
    evidence_debug["customer_urgency"] = state.get("customer_urgency", "")
    evidence_debug["customer_concern"] = state.get("customer_concern", "")
    evidence_debug["reply_goal"] = state.get("reply_goal", "")
    evidence_debug["reply_structure"] = state.get("reply_structure", [])
    evidence_debug["missing_slots"] = state.get("missing_slots", [])
    evidence_debug["context_updated"] = state.get("context_updated", False)
    evidence_debug["generation_mode"] = state.get("generation_mode", "")
    evidence_debug["llm_used"] = state.get("llm_used", False)
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

    verified_evidence = _summarize_verified_evidence(evidence)
    tools_to_call = _summarize_tools_to_call(state)
    reply_tone = _infer_reply_tone(state, requires_human_review)

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
        "hallucination_guard": state.get("hallucination_guard", {}),
        "used_knowledge_entry_ids": evidence_debug["used_knowledge_entry_ids"],
        "used_knowledge_titles": evidence_debug["used_knowledge_titles"],
        "used_fact_tool": state.get("used_fact_tool", ""),
        "used_endpoint": state.get("used_endpoint", ""),
        "trace_steps": state.get("trace_steps", []) + [trace],
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
    followup = (
        "\n\n另外，您说收到的商品和下单不一致、还少配件，这个需要先帮您核对订单商品和实物情况。"
        "麻烦您发一下订单截图、收到的商品整体图、外箱面单和缺少配件的位置/清单，"
        "我这边核实后再按情况给您处理补发、换货或退换方案。"
    )
    return (reply or "").strip() + followup



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
