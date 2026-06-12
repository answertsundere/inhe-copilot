"""
execution_debug_builder — 从 LangGraph 结果构建统一 execution_debug 结构。

修正语义：
- request_id: 每次请求唯一，不由 conversation_id 代替
- guards.passed: 表示守卫是否正确执行，而非是否低风险
- tool status: not_found → miss, not error
- RAG used: 严格从 used_knowledge_entry_ids 判定
- citations: used_in_reply 只对实际引用为 true
- timing: JST 只统计 JST 工具调用
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from app.config import (
    GRAPH_VERSION, PROMPT_VERSION, ROUTING_CONFIG_VERSION,
    TOOL_REGISTRY_VERSION, APP_VERSION,
    MASK_ORDER_IDS, MASK_TRACKING_NOS,
    LLM_MODEL, LLM_API_BASE,
)


def _mask_sensitive(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'1[3-9]\d{9}', lambda m: m.group()[:3] + '****' + m.group()[-4:], text)
    return text


def _mask_id(id_value: str, mask: bool) -> str:
    if not id_value or not mask:
        return id_value
    if len(id_value) <= 8:
        return id_value[:2] + '***'
    return id_value[:4] + '****' + id_value[-4:]


def _shortid() -> str:
    return uuid.uuid4().hex[:12]


def build_execution_debug(
    result: dict,
    request_id: str = "",
    message_id: str = "",
    conversation_id: str = "",
    source: str = "manual_simulation",
    scenario: str = "",
    request_duration_ms: int = 0,
    copilot_context: dict | None = None,
) -> dict:
    request_id = request_id or _shortid()
    message_id = message_id or _shortid()

    evidence_debug = result.get("evidence_debug", {})
    trace_steps = result.get("trace_steps", [])
    tool_traces = result.get("tool_traces", [])
    tool_results = result.get("tool_results", {})
    evidence = result.get("evidence", {})
    copilot_context = copilot_context or {}

    return {
        "request": _build_request(
            result, request_id, message_id, conversation_id,
            source, scenario, copilot_context,
        ),
        "versions": _build_versions(result),
        "routing": _build_routing(result, evidence_debug, trace_steps),
        "tool_calls": _build_tool_calls(tool_traces, tool_results, result),
        "rag": _build_rag(result, evidence_debug, evidence),
        "citations": _build_citations(result, evidence),
        "generation": _build_generation(result, evidence_debug),
        "guards": _build_guards(result, evidence_debug, trace_steps),
        "timing": _build_timing(result, trace_steps, request_duration_ms),
        "outcome": _build_outcome(result, evidence_debug),
    }


def _build_request(
    result, request_id, message_id, conversation_id,
    source, scenario, copilot_context,
) -> dict:
    customer_message = result.get("customer_message", "")
    history = copilot_context.get("conversation_history", [])
    order_candidates = copilot_context.get("order_candidates", [])
    tracking_candidates = copilot_context.get("tracking_candidates", [])
    product_candidates = copilot_context.get("product_candidates", [])

    return {
        "request_id": request_id,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "source": source,
        "scenario": scenario,
        "customer_message": _mask_sensitive(customer_message),
        "conversation_history_count": len(history),
        "has_order_candidate": bool(order_candidates),
        "has_tracking_candidate": bool(tracking_candidates),
        "has_product_candidate": bool(product_candidates),
        "order_candidates": [
            {"value": _mask_id(c.get("value", ""), MASK_ORDER_IDS), "type": c.get("type", "")}
            for c in order_candidates[:3]
        ],
        "tracking_candidates": [
            {"value": _mask_id(c.get("value", ""), MASK_TRACKING_NOS), "type": c.get("type", "")}
            for c in tracking_candidates[:3]
        ],
        "product_candidates": [
            {"value": c.get("value", ""), "type": c.get("type", "")}
            for c in product_candidates[:3]
        ],
    }


def _build_versions(result: dict) -> dict:
    knowledge_version = "unknown"
    try:
        from app.config import KNOWLEDGE_DB_PATH
        if os.path.exists(KNOWLEDGE_DB_PATH):
            mtime = os.path.getmtime(KNOWLEDGE_DB_PATH)
            knowledge_version = f"kb-{int(mtime)}"
    except Exception:
        pass

    model_name = LLM_MODEL
    model_provider = ""
    if "dashscope" in LLM_API_BASE:
        model_provider = "alibaba_qwen"
    elif "openai" in LLM_API_BASE:
        model_provider = "openai"
    elif LLM_API_BASE:
        model_provider = LLM_API_BASE.split("//")[1].split(".")[0] if "//" in LLM_API_BASE else ""

    return {
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "routing_config_version": ROUTING_CONFIG_VERSION,
        "knowledge_version": knowledge_version,
        "model_provider": model_provider,
        "model_name": model_name,
        "tool_registry_version": TOOL_REGISTRY_VERSION,
        "app_version": APP_VERSION,
    }


import os


def _build_routing(result: dict, evidence_debug: dict, trace_steps: list) -> dict:
    old_intent = ""
    llm_intent = ""
    fusion_final_intent = ""
    final_intent = result.get("intent", "")

    # Extract intent journey from structured fields first
    pu = result.get("parallel_understanding", {})
    df = result.get("decision_fusion", {})
    if isinstance(pu, dict):
        old_intent = pu.get("intent", "")
        ic = pu.get("intent_classifier", {})
        if isinstance(ic, dict) and ic.get("primary_intent"):
            old_intent = ic["primary_intent"]
    if isinstance(df, dict):
        fusion_final_intent = df.get("final_intent", "")

    # LLM intent from llm_intent_router trace — use structured intent, not summary
    for ts in trace_steps:
        node = ts.get("node") or ts.get("step") or ""
        if "llm_intent" in node:
            # Prefer structured fields over summary
            llm_intent = ts.get("intent", "") or ts.get("final_intent", "")
            if not llm_intent:
                # Only fall back to summary if no structured field exists
                llm_intent = ts.get("summary", "")
                # Save separately as reason if it's natural language
                if llm_intent and len(llm_intent) > 20:
                    # It's likely a natural language explanation
                    pass

    router_source = result.get("router_source", "")
    router_reason = result.get("router_reason", "")
    selected_route = result.get("response_strategy", "")
    answer_mode = result.get("answer_mode", "") or evidence_debug.get("answer_mode", "")

    overrides = []
    for ts in trace_steps:
        node = ts.get("node") or ts.get("step") or ""
        if "validation" in node:
            status = ts.get("status", "")
            if status == "override" or (ts.get("from_intent") and ts.get("to_intent")):
                overrides.append({
                    "from": ts.get("from_intent", ""),
                    "to": ts.get("to_intent", final_intent),
                    "node": node,
                    "reason": ts.get("summary", "") or ts.get("reason", ""),
                })
            elif "router_source" in ts and ts.get("router_source") == "validation_override":
                overrides.append({
                    "from": ts.get("from_intent", ""),
                    "to": ts.get("to_intent", final_intent),
                    "node": node,
                    "reason": ts.get("summary", ""),
                })

    return {
        "old_intent": old_intent,
        "llm_intent": llm_intent,
        "fusion_final_intent": fusion_final_intent,
        "final_intent": final_intent,
        "intent_confidence": result.get("router_confidence", 0),
        "risk_level": result.get("risk_level", "low"),
        "need_human_review": bool(result.get("requires_human_review")),
        "router_source": router_source,
        "router_reason": router_reason,
        "selected_route": selected_route,
        "answer_mode": answer_mode,
        "required_tools": result.get("required_tools", []),
        "allowed_tools": result.get("allowed_tools", []),
        "forbidden_tools": result.get("forbidden_tools", []),
        "safety_contract": result.get("safety_contract", {}),
        "overrides": overrides,
    }


def _build_tool_calls(tool_traces: list, tool_results: dict, result: dict) -> list:
    calls = []
    seen = set()

    for trace in tool_traces:
        tool_name = trace.get("tool_name", "")
        if not tool_name or tool_name == "budget_exhausted":
            calls.append({
                "call_id": _shortid(),
                "tool_name": trace.get("tool_name", "unknown"),
                "provider": trace.get("provider", "tool_registry"),
                "status": "skipped",
                "started_at": "",
                "duration_ms": trace.get("duration_ms", 0),
                "input_summary": {},
                "output_summary": {},
                "found": False,
                "error_code": trace.get("error_code", "budget_exhausted"),
                "error_message": trace.get("summary", ""),
                "fallback_to": "",
                "created_fact_types": [],
            })
            continue

        raw_status = trace.get("status", "unknown")
        # Map not_found → miss (not error)
        if raw_status == "not_found":
            status = "miss"
        elif raw_status == "no_handler":
            status = "miss"
        else:
            status = raw_status

        tr = tool_results.get(tool_name, {})
        # Determine found from multiple sources
        is_found = False
        if isinstance(tr, dict):
            if tr.get("found"):
                is_found = True
            elif tr.get("count", 0) > 0:
                is_found = True
            elif tr.get("chunks") and len(tr["chunks"]) > 0:
                is_found = True
            elif tr.get("items") and len(tr["items"]) > 0:
                is_found = True

        error_code = trace.get("error_code", "")
        if status == "error" and not error_code:
            error_code = "execution_error"

        calls.append({
            "call_id": _shortid(),
            "tool_name": tool_name,
            "provider": trace.get("provider", "tool_registry"),
            "status": status,
            "started_at": "",
            "duration_ms": trace.get("duration_ms", 0),
            "input_summary": trace.get("input_summary", {}),
            "output_summary": trace.get("output_summary", {}),
            "found": is_found,
            "error_code": error_code,
            "error_message": trace.get("summary", "") if status not in ("success", "miss") else "",
            "fallback_to": "",
            "created_fact_types": trace.get("can_create_fact_types", []),
        })
        seen.add(tool_name)

    # Planned but not executed
    tool_plan = result.get("tool_plan", [])
    for planned in tool_plan:
        tn = planned.get("tool_name", "") if isinstance(planned, dict) else str(planned)
        if tn and tn not in seen:
            calls.append({
                "call_id": _shortid(),
                "tool_name": tn,
                "provider": "tool_registry",
                "status": "planned",
                "started_at": "",
                "duration_ms": 0,
                "input_summary": {},
                "output_summary": {},
                "found": False,
                "error_code": "planned_not_executed",
                "error_message": "",
                "fallback_to": "",
                "created_fact_types": [],
            })

    return calls


def _build_rag(result: dict, evidence_debug: dict, evidence: dict) -> dict:
    retrieved_chunks = result.get("retrieved_chunks", [])
    knowledge_evidence = result.get("knowledge_evidence", [])
    filtered_evidence = result.get("filtered_evidence", [])
    allowed_source_types = result.get("allowed_source_types", [])
    retrieval_mode = result.get("rag_retrieval_mode", "")

    slots = result.get("slots", {}) or {}
    product_scope = [p for p in [result.get("matched_product_name", "") or slots.get("product_name", "")] if p]
    sku_scope = [s for s in [slots.get("sku_name", "") or slots.get("sku_code", "")] if s]

    # Build retrieved list, deduplicate by chunk_id (not just entry_id)
    all_chunks = []
    seen_keys = set()
    for chunk in (retrieved_chunks + knowledge_evidence + filtered_evidence):
        entry_id = chunk.get("entry_id") or 0
        chunk_id = chunk.get("chunk_id", "")
        dedup_key = f"{entry_id}_{chunk_id}" if chunk_id else f"{entry_id}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        all_chunks.append({
            "entry_id": entry_id,
            "chunk_id": chunk_id,
            "title": chunk.get("title", ""),
            "source_type": chunk.get("source_type", ""),
            "score": chunk.get("score", 0),
            "rerank_score": chunk.get("rerank_score", 0),
            "product_scope": chunk.get("product_scope", []),
            "sku_scope": chunk.get("sku_scope", []),
            "source_sheet": chunk.get("source_sheet", ""),
            "row_number": chunk.get("row_number", 0),
            "content_preview": (chunk.get("chunk_text") or chunk.get("fact") or "")[:200],
            "used_in_answer": False,  # Will be set below
            "rejection_reasons": chunk.get("rejection_reasons", []),
        })

    # Determine used: only from used_knowledge_entry_ids (server-side truth)
    used_ids = set(result.get("used_knowledge_entry_ids", []))
    # Also check evidence_debug
    ed_used = evidence_debug.get("used_knowledge_entry_ids", [])
    if ed_used:
        used_ids.update(ed_used)

    used = []
    used_chunk_keys = set()
    for c in all_chunks:
        if c["entry_id"] in used_ids:
            c["used_in_answer"] = True
            used.append(c)
            key = f"{c['entry_id']}_{c['chunk_id']}" if c["chunk_id"] else f"{c['entry_id']}"
            used_chunk_keys.add(key)

    # Rejected: has explicit rejection_reasons
    rejected = [c for c in all_chunks if c.get("rejection_reasons")]

    rag_duration_ms = evidence_debug.get("rag_duration_ms", 0)

    return {
        "query": result.get("normalized_message", "") or result.get("customer_message", ""),
        "retrieval_mode": retrieval_mode,
        "product_scope": product_scope,
        "sku_scope": sku_scope,
        "source_types": allowed_source_types,
        "top_k": 5,
        "retrieved": all_chunks,
        "used": used,
        "rejected": rejected,
        "metrics": {
            "retrieved_count": len(all_chunks),
            "used_count": len(used),
            "rejected_count": len(rejected),
            "top_score": all_chunks[0]["score"] if all_chunks else 0,
            "duration_ms": rag_duration_ms,
        },
    }


def _build_citations(result: dict, evidence: dict) -> list:
    citations = []

    used_ids = set(result.get("used_knowledge_entry_ids", []))
    ed_used = result.get("evidence_debug", {}).get("used_knowledge_entry_ids", [])
    if ed_used:
        used_ids.update(ed_used)

    knowledge_evidence = result.get("knowledge_evidence", []) + result.get("filtered_evidence", [])

    seen_entry_ids = set()
    for item in knowledge_evidence:
        entry_id = item.get("entry_id") or item.get("matched_entry_id", "")
        if not entry_id or entry_id in seen_entry_ids:
            continue
        seen_entry_ids.add(entry_id)

        chunk_id = item.get("chunk_id", "")
        source_type = item.get("source_type", "")
        title = item.get("title", "") or item.get("matched_title", "")
        is_used = entry_id in used_ids

        fact_types = []
        if source_type == "product_facts":
            fact_types.append("material")
        elif source_type == "faq":
            fact_types.append("faq")
        elif source_type == "shipping_policy":
            fact_types.append("shipping")

        # Stable citation_id using entry_id AND chunk_id
        cid = f"K_{entry_id}_{chunk_id}" if chunk_id else f"K_{entry_id}"

        citations.append({
            "citation_id": cid,
            "citation_type": "knowledge",
            "source_id": entry_id,
            "title": title,
            "source_type": source_type,
            "fact_types": fact_types,
            "content_preview": (item.get("chunk_text") or item.get("fact") or "")[:200],
            "used_in_reply": is_used,
        })

    # Tool citations
    tool_results = result.get("tool_results", {})
    tool_traces = result.get("tool_traces", [])
    tool_idx = 0
    for trace in tool_traces:
        tool_name = trace.get("tool_name", "")
        if not tool_name or tool_name == "budget_exhausted":
            continue
        tr = tool_results.get(tool_name, {})
        if not isinstance(tr, dict):
            continue
        # Check if tool actually found something
        is_found = tr.get("found", False)
        if not is_found:
            continue

        tool_idx += 1
        fact_types = []
        if tool_name.startswith("jst_lookup"):
            fact_types.append("order_status")
            if tr.get("logistics_company") or tr.get("l_id"):
                fact_types.append("tracking_no")
            if tr.get("send_date"):
                fact_types.append("send_date")

        # Determine if this tool's output was actually used in reply
        # Only mark used_in_reply=true if the tool is the used_fact_tool
        used_fact_tool = result.get("used_fact_tool", "")
        is_used = tool_name == used_fact_tool

        citations.append({
            "citation_id": f"T_{tool_name}_{tool_idx}",
            "citation_type": "tool_fact",
            "tool_name": tool_name,
            "fact_types": fact_types,
            "used_in_reply": is_used,
        })

    return citations


def _build_generation(result: dict, evidence_debug: dict) -> dict:
    llm_used = result.get("llm_used", False)
    generation_mode = result.get("generation_mode", "") or evidence_debug.get("generation_mode", "rule_based")
    answer_mode = result.get("answer_mode", "") or evidence_debug.get("answer_mode", "")

    used_citation_ids = []
    used_ids = set(result.get("used_knowledge_entry_ids", []))
    ed_used = evidence_debug.get("used_knowledge_entry_ids", [])
    if ed_used:
        used_ids.update(ed_used)
    for eid in used_ids:
        used_citation_ids.append(f"K_{eid}")

    evidence_count = 0
    evidence = result.get("evidence", {})
    for bucket in ("order_facts", "logistics_facts", "product_facts", "policy_facts",
                   "sop_evidence", "template_evidence", "faq_evidence"):
        evidence_count += len(evidence.get(bucket, []))

    reply = result.get("suggested_reply", "")

    return {
        "answer_mode": answer_mode,
        "generation_mode": generation_mode,
        "llm_used": llm_used,
        "model_name": LLM_MODEL,
        "prompt_version": PROMPT_VERSION,
        "evidence_count": evidence_count,
        "used_citation_ids": used_citation_ids,
        "fallback_reason": evidence_debug.get("fallback_reason", ""),
        "reply_length": len(reply),
    }


def _build_guards(result: dict, evidence_debug: dict, trace_steps: list) -> list:
    guards = []
    risk_level = result.get("risk_level", "low")

    # risk_check: passed=true means guard correctly identified risk level
    guards.append({
        "guard_name": "risk_check",
        "passed": True,  # Guard executed correctly
        "triggered": risk_level in ("high", "medium"),
        "action_taken": "flag_for_review" if risk_level == "high" else "",
        "reason": f"risk_level={risk_level}",
        "duration_ms": _find_node_duration(trace_steps, "risk_check"),
        "details": {"risk_level": risk_level},
    })

    # safety_contract
    sc = result.get("safety_contract", {})
    if sc:
        guards.append({
            "guard_name": "safety_contract",
            "passed": sc.get("passed", True),
            "triggered": not sc.get("passed", True),
            "action_taken": "",
            "reason": "",
            "duration_ms": _find_node_duration(trace_steps, "parallel_pre_strategy_controls"),
            "details": sc,
        })

    # hallucination_guard
    hg = result.get("hallucination_guard", {})
    if hg:
        guards.append({
            "guard_name": "hallucination_guard",
            "passed": hg.get("passed", True),
            "triggered": not hg.get("passed", True),
            "action_taken": "fallback" if hg.get("fallback_used") else "",
            "reason": ", ".join(hg.get("unsupported_terms", [])) if not hg.get("passed") else "",
            "duration_ms": _find_node_duration(trace_steps, "hallucination_guard"),
            "details": {
                "unsupported_terms": hg.get("unsupported_terms", []),
                "fallback_used": hg.get("fallback_used", False),
                "fallback_mode": result.get("answer_mode", "") if hg.get("fallback_used") else "",
            },
        })

    # factual_guard
    fg_trace = _find_trace(trace_steps, "factual_guard")
    if fg_trace:
        guards.append({
            "guard_name": "factual_guard",
            "passed": fg_trace.get("passed", True),
            "triggered": not fg_trace.get("passed", True),
            "action_taken": "rewrite" if not fg_trace.get("passed", True) else "",
            "reason": fg_trace.get("summary", ""),
            "duration_ms": fg_trace.get("duration_ms", 0),
            "details": {"summary": fg_trace.get("summary", "")},
        })

    # quality_guard
    qg_trace = _find_trace(trace_steps, "quality_guard")
    if qg_trace:
        guards.append({
            "guard_name": "quality_guard",
            "passed": qg_trace.get("passed", True),
            "triggered": not qg_trace.get("passed", True),
            "action_taken": "",
            "reason": qg_trace.get("summary", ""),
            "duration_ms": qg_trace.get("duration_ms", 0),
            "details": {"summary": qg_trace.get("summary", "")},
        })

    # human_review_gate: passed=true means gate executed correctly
    # requires_review is separate from passed
    hrg_trace = _find_trace(trace_steps, "human_review_gate")
    if hrg_trace:
        requires_review = result.get("requires_human_review", False)
        guards.append({
            "guard_name": "human_review_gate",
            "passed": True,  # Gate executed correctly regardless of outcome
            "triggered": requires_review,
            "action_taken": "queue_for_review" if requires_review else "",
            "reason": "high_risk_or_policy_requirement" if requires_review else "",
            "duration_ms": hrg_trace.get("duration_ms", 0),
            "details": {"requires_review": requires_review},
        })

    return guards


def _build_timing(result: dict, trace_steps: list, request_duration_ms: int) -> dict:
    node_durations = {}
    for ts in trace_steps:
        node = ts.get("node") or ts.get("step") or ""
        dur = ts.get("duration_ms", 0)
        if node and dur:
            node_durations[node] = node_durations.get(node, 0) + dur

    evidence_debug = result.get("evidence_debug", {})

    # JST time: only JST tool traces, not entire tool_executor
    jst_ms = 0
    tool_traces = result.get("tool_traces", [])
    jst_tools = {"jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"}
    for tr in tool_traces:
        if tr.get("tool_name", "") in jst_tools:
            jst_ms += tr.get("duration_ms", 0)
    if jst_ms == 0:
        jst_ms = evidence_debug.get("jst_duration_ms", 0)

    return {
        "total_ms": request_duration_ms,
        "understanding_ms": (
            _find_node_duration(trace_steps, "parallel_understanding")
            + _find_node_duration(trace_steps, "decision_fusion")
        ),
        "routing_ms": (
            _find_node_duration(trace_steps, "detect_intent")
            + _find_node_duration(trace_steps, "route_by_intent")
            + _find_node_duration(trace_steps, "llm_intent_router")
            + _find_node_duration(trace_steps, "router_validation")
        ),
        "jst_ms": jst_ms,
        "rag_ms": evidence_debug.get("rag_duration_ms", 0) or _find_node_duration(trace_steps, "rag_retrieve"),
        "llm_ms": evidence_debug.get("llm_duration_ms", 0),
        "generation_ms": (
            _find_node_duration(trace_steps, "generate_reply")
            + _find_node_duration(trace_steps, "generate_logistics_reply")
            + _find_node_duration(trace_steps, "response_strategy_planner")
        ),
        "guard_ms": (
            _find_node_duration(trace_steps, "hallucination_guard")
            + _find_node_duration(trace_steps, "factual_guard")
            + _find_node_duration(trace_steps, "quality_guard")
            + _find_node_duration(trace_steps, "human_review_gate")
        ),
        "node_durations": node_durations,
    }


def _build_outcome(result: dict, evidence_debug: dict) -> dict:
    hallucination = result.get("hallucination_guard", {})
    tool_results = result.get("tool_results", {})

    tool_failure = False
    for tr in tool_results.values():
        if isinstance(tr, dict) and tr.get("error"):
            tool_failure = True
            break

    # RAG miss only for product questions where RAG should have found something
    rag_miss = False
    evidence = result.get("evidence", {})
    intent = result.get("intent", "")
    has_knowledge = bool(evidence.get("product_facts") or evidence.get("faq_evidence"))
    if intent in ("product_question", "product_consult") and not has_knowledge:
        rag_miss = True

    fallback_used = False
    gen_mode = result.get("generation_mode", "")
    if gen_mode and ("fallback" in gen_mode or "blocked" in gen_mode):
        fallback_used = True

    return {
        "reply_generated": bool(result.get("suggested_reply")),
        "need_human_review": bool(result.get("requires_human_review")),
        "fallback_used": fallback_used,
        "fallback_type": result.get("answer_mode", "") if fallback_used else "",
        "no_evidence": result.get("answer_mode", "") == "no_evidence_clarification",
        "tool_failure": tool_failure,
        "rag_miss": rag_miss,
        "hallucination_blocked": hallucination.get("fallback_used", False),
    }


def _find_node_duration(trace_steps: list, node_name: str) -> int:
    for ts in trace_steps:
        n = ts.get("node") or ts.get("step") or ""
        if n == node_name:
            return ts.get("duration_ms", 0)
    return 0


def _find_trace(trace_steps: list, partial_name: str) -> dict | None:
    for ts in trace_steps:
        n = ts.get("node") or ts.get("step") or ""
        if partial_name in n:
            return ts
    return None
