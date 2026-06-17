"""
customer_service_graph - LangGraph 状态图（策略路由版 + Tool Registry）
统一知识检索接入，按 response_strategy 条件分支
支持 Tool Registry 新链路，旧链路保留为 fallback
"""

from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.context.conversation_context import (
    apply_conversation_context,
    load_conversation_context,
    update_conversation_context,
)
from app.agent.nodes.normalize_input import normalize_input
from app.agent.nodes.parallel_understanding import parallel_understanding
from app.agent.nodes.decision_fusion import decision_fusion
from app.agent.nodes.parallel_controls import (
    apply_parallel_pre_strategy_controls,
    apply_parallel_post_strategy_controls,
)
from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.risk_check import risk_check
from app.agent.nodes.build_base_context import build_base_context
from app.agent.nodes.route_by_intent import route_by_intent
from app.agent.nodes.knowledge_scope_router import knowledge_scope_router
from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.quality_guard import quality_guard
from app.agent.nodes.human_review_gate import human_review_gate

from app.agent.nodes.slot_extract import slot_extract
from app.agent.nodes.llm_intent_router import llm_intent_router
from app.agent.nodes.router_validation import router_validation
from app.agent.nodes.query_fact_type_classifier import query_fact_type_classifier
from app.agent.nodes.order_product_resolver import order_product_resolver
from app.agent.nodes.identifier_router import identifier_router, route_from_identifier
from app.agent.nodes.verify_consistency import verify_consistency
from app.agent.nodes.jst_live_query import jst_live_query
from app.agent.nodes.resolve_order_status import resolve_order_status
from app.agent.nodes.resolve_product_identity import resolve_product_identity
from app.agent.nodes.match_shipping_policy import match_shipping_policy
from app.agent.nodes.evidence_builder import evidence_builder
from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
from app.agent.nodes.hallucination_guard import hallucination_guard
from app.agent.nodes.factual_guard import factual_guard
from app.agent.nodes.post_generation_grounding_guard import post_generation_grounding_guard
from app.agent.nodes.build_response import build_response
from app.agent.nodes.reply_relevance_guard import reply_relevance_guard

from app.agent.nodes.rag_retrieve import rag_retrieve
from app.agent.nodes.evidence_filter_node import evidence_filter_node
from app.agent.nodes.rag_judge_node import rag_judge_node

from app.agent.nodes.response_strategy_router import response_strategy_router
from app.agent.nodes.customer_state_analyzer import customer_state_analyzer
from app.agent.nodes.response_strategy_planner import response_strategy_planner
from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder

from app.agent.tools.executor import plan_tools, tool_executor_node


# ========== JST 工具名集合 ==========
_JST_TOOLS = {"jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"}
_PRODUCT_KNOWLEDGE_INTENTS = {
    "product_question",
    "product_consult",
    "material_question",
    "size_question",
    "installation_question",
    "material_safety",
    "child_safety",
    "odor_question",
    "cleaning_care",
    "competitor_compare",
}


# ========== 条件路由函数 ==========

def _route_after_risk_check(state: dict) -> str:
    """risk_check 之后的条件路由"""
    return "build_context"


def _route_after_strategy(state: dict) -> str:
    """response_strategy_router 之后的条件路由"""
    strategy = state.get("response_strategy", "clarification")
    intent = state.get("intent", "")

    if strategy == "high_risk":
        return "high_risk_chain"

    if strategy == "aftersales":
        return "aftersales_chain"

    if strategy == "installation":
        return "installation_chain"

    if strategy == "logistics_with_order":
        return "logistics_chain"

    if strategy == "logistics_policy_without_order":
        return "logistics_policy_chain"

    if strategy == "product_question" or intent in _PRODUCT_KNOWLEDGE_INTENTS:
        return "product_chain"

    return "clarification_chain"


def _route_after_identifier(state: dict) -> str:
    """identifier_router 之后的条件路由"""
    return route_from_identifier(state)


def _route_after_verify_consistency(state: dict) -> str:
    """verify_consistency 之后 — 一致时走 tool_planner，冲突走人工"""
    cs = state.get("consistency_status", "")
    if cs == "conflict":
        return "human_review"
    return "tool_planner"


def _route_after_resolve_product(state: dict) -> str:
    """resolve_product_identity 之后"""
    slots = state.get("slots", {})
    order_id = slots.get("order_id", "")
    possible_numeric_id = slots.get("possible_numeric_id", "")

    if order_id or possible_numeric_id:
        return "jst_live_query"

    need_clarification = state.get("need_clarification", False)
    if need_clarification:
        return "clarification_reply"

    # 商品咨询和安装策略 → Tool Registry 链路（product_resolver + RAG）
    strategy = state.get("response_strategy", "")
    intent = state.get("intent", "")
    if strategy in ("product_question", "installation") or intent in _PRODUCT_KNOWLEDGE_INTENTS:
        return "tool_planner"

    return "match_shipping_policy"


def _route_after_evidence(state: dict) -> str:
    """evidence_builder 之后的条件路由"""
    strategy = state.get("response_strategy", "")
    if strategy in ("logistics_with_order", "logistics_policy_without_order"):
        return "logistics_reply"
    return "general_reply"


def _route_after_strategy_plan(state: dict) -> str:
    strategy = state.get("response_strategy", "")
    if strategy in ("logistics_with_order", "logistics_policy_without_order"):
        return "logistics_reply"
    return "general_reply"


def _route_after_tool_executor(state: dict) -> str:
    """tool_executor_node 之后：检查 JST 工具是否成功，失败则 fallback 到旧链路"""
    strategy = state.get("response_strategy", "")
    tool_results = state.get("tool_results", {})
    required_tools = state.get("required_tools", [])

    # 非 JST 场景（product_question 等）直接走 evidence_builder
    jst_required = [t for t in required_tools if t in _JST_TOOLS]
    if not jst_required:
        return "tool_success"

    # JST 场景：检查是否成功
    for jst_tool in jst_required:
        tr = tool_results.get(jst_tool)
        if isinstance(tr, dict) and tr.get("found"):
            return "tool_success"

    if state.get("tool_planner_source") == "explicit_logistics_identifier_fast_path":
        return "tool_success"

    # JST 工具未成功 → fallback 到旧 jst_live_query 链路
    return "jst_fallback"


def _route_after_knowledge_scope(state: dict) -> str:
    """knowledge_scope_router 之后：高风险/售后 → tool_planner，其他 → rag_retrieve"""
    strategy = state.get("response_strategy", "")
    tool_already_attempted = any(
        (step.get("node") or "") in ("tool_executor", "tool_executor_node")
        for step in state.get("trace_steps", []) or []
        if isinstance(step, dict)
    )
    # 若 required_tools 已在 tool_results 中（即使 found=False，也算已尝试过），不重复调用
    required_tools = state.get("required_tools") or []
    tool_results = state.get("tool_results") or {}
    if required_tools and all(t in tool_results for t in required_tools):
        tool_already_attempted = True
    if state.get("required_tools") and not tool_already_attempted:
        return "tool_planner"
    if strategy in ("high_risk",):
        return "tool_planner"
    return "rag_retrieve"


# ========== 公共子链构建函数 ==========

def _add_tail(builder):
    """添加尾部链: build_response → quality_guard → human_review_gate → END"""
    builder.add_edge("build_response", "update_conversation_context")
    builder.add_edge("update_conversation_context", "quality_guard")
    builder.add_edge("quality_guard", "human_review_gate")
    builder.add_edge("human_review_gate", END)


def build_graph():
    """构建客服业务状态图（策略路由 + Tool Registry 版）"""
    builder = StateGraph(AgentState)

    # ========== 公共节点 ==========
    builder.add_node("normalize_input", normalize_input)
    builder.add_node("parallel_understanding", parallel_understanding)
    builder.add_node("decision_fusion", decision_fusion)
    builder.add_node("parallel_pre_strategy_controls", apply_parallel_pre_strategy_controls)
    builder.add_node("parallel_post_strategy_controls", apply_parallel_post_strategy_controls)
    builder.add_node("load_conversation_context", load_conversation_context)
    builder.add_node("apply_conversation_context", apply_conversation_context)
    builder.add_node("update_conversation_context", update_conversation_context)
    builder.add_node("detect_intent", detect_intent)
    builder.add_node("risk_check", risk_check)
    builder.add_node("build_base_context", build_base_context)
    builder.add_node("route_by_intent", route_by_intent)
    builder.add_node("slot_extract", slot_extract)
    builder.add_node("llm_intent_router", llm_intent_router)
    builder.add_node("router_validation", router_validation)
    builder.add_node("query_fact_type_classifier", query_fact_type_classifier)
    builder.add_node("order_product_resolver", order_product_resolver)
    builder.add_node("response_strategy_router", response_strategy_router)
    builder.add_node("customer_state_analyzer", customer_state_analyzer)
    builder.add_node("response_strategy_planner", response_strategy_planner)
    builder.add_node("gold_csr_reply_builder", gold_csr_reply_builder)
    builder.add_node("knowledge_scope_router", knowledge_scope_router)

    # 物流链节点
    builder.add_node("identifier_router", identifier_router)
    builder.add_node("verify_consistency", verify_consistency)
    builder.add_node("jst_live_query", jst_live_query)
    builder.add_node("resolve_order_status", resolve_order_status)
    builder.add_node("resolve_product_identity", resolve_product_identity)
    builder.add_node("match_shipping_policy", match_shipping_policy)
    builder.add_node("evidence_builder", evidence_builder)
    builder.add_node("generate_logistics_reply", generate_logistics_reply)
    builder.add_node("hallucination_guard", hallucination_guard)
    builder.add_node("post_generation_grounding_guard", post_generation_grounding_guard)
    builder.add_node("factual_guard", factual_guard)
    builder.add_node("reply_relevance_guard", reply_relevance_guard)
    builder.add_node("build_response", build_response)

    # RAG 链节点
    builder.add_node("rag_retrieve", rag_retrieve)
    builder.add_node("evidence_filter_node", evidence_filter_node)
    builder.add_node("rag_judge_node", rag_judge_node)

    # Tool Registry 节点
    builder.add_node("tool_planner", plan_tools)
    builder.add_node("tool_executor_node", tool_executor_node)

    # 公共尾部节点
    builder.add_node("generate_reply", generate_reply)
    builder.add_node("quality_guard", quality_guard)
    builder.add_node("human_review_gate", human_review_gate)

    # ========== 公共前段 ==========
    builder.set_entry_point("normalize_input")
    builder.add_edge("normalize_input", "load_conversation_context")
    builder.add_edge("load_conversation_context", "parallel_understanding")
    builder.add_edge("parallel_understanding", "decision_fusion")
    builder.add_edge("decision_fusion", "detect_intent")
    builder.add_edge("detect_intent", "risk_check")

    builder.add_conditional_edges(
        "risk_check",
        _route_after_risk_check,
        {
            "build_context": "build_base_context",
        },
    )

    builder.add_edge("build_base_context", "route_by_intent")
    builder.add_edge("route_by_intent", "slot_extract")
    builder.add_edge("slot_extract", "apply_conversation_context")
    builder.add_edge("apply_conversation_context", "order_product_resolver")
    builder.add_edge("order_product_resolver", "llm_intent_router")
    builder.add_edge("llm_intent_router", "router_validation")
    builder.add_edge("router_validation", "query_fact_type_classifier")
    builder.add_edge("query_fact_type_classifier", "parallel_pre_strategy_controls")
    builder.add_edge("parallel_pre_strategy_controls", "customer_state_analyzer")
    builder.add_edge("customer_state_analyzer", "response_strategy_router")
    builder.add_edge("response_strategy_router", "parallel_post_strategy_controls")

    # ========== 策略分支 ==========
    builder.add_conditional_edges(
        "parallel_post_strategy_controls",
        _route_after_strategy,
        {
            "high_risk_chain": "knowledge_scope_router",
            "aftersales_chain": "knowledge_scope_router",
            "installation_chain": "resolve_product_identity",
            "logistics_chain": "identifier_router",
            "logistics_policy_chain": "resolve_product_identity",
            "product_chain": "resolve_product_identity",
            "clarification_chain": "response_strategy_planner",
        },
    )

    # === Tool Registry 链路：tool_planner → tool_executor_node → 分支 ===
    builder.add_edge("tool_planner", "tool_executor_node")

    # tool_executor_node 之后：JST 成功 → evidence_builder，失败 → fallback 旧链路
    builder.add_conditional_edges(
        "tool_executor_node",
        _route_after_tool_executor,
        {
            "tool_success": "evidence_builder",
            "jst_fallback": "jst_live_query",
        },
    )

    # === 1. 高风险链 ===
    # knowledge_scope_router → tool_planner（SOP 工具优先）或 rag_retrieve
    builder.add_conditional_edges(
        "knowledge_scope_router",
        _route_after_knowledge_scope,
        {
            "tool_planner": "tool_planner",
            "rag_retrieve": "rag_retrieve",
        },
    )

    # rag_retrieve → evidence_filter_node → rag_judge_node → evidence_builder
    builder.add_edge("rag_retrieve", "evidence_filter_node")
    builder.add_edge("evidence_filter_node", "rag_judge_node")
    builder.add_edge("rag_judge_node", "evidence_builder")

    # evidence_builder → response_strategy_planner
    builder.add_conditional_edges(
        "evidence_builder",
        lambda state: "strategy_plan",
        {
            "strategy_plan": "response_strategy_planner",
        },
    )

    builder.add_conditional_edges(
        "response_strategy_planner",
        _route_after_strategy_plan,
        {
            "logistics_reply": "generate_logistics_reply",
            "general_reply": "generate_reply",
        },
    )

    # === 2. 售后链 ===
    # 与高风险共享 knowledge_scope_router 入口

    # === 3. 安装链 ===
    builder.add_conditional_edges(
        "resolve_product_identity",
        _route_after_resolve_product,
        {
            "jst_live_query": "jst_live_query",
            "match_shipping_policy": "match_shipping_policy",
            "tool_planner": "tool_planner",
            "clarification_reply": "generate_logistics_reply",
        },
    )

    # === 4. 物流有订单号链（Tool Registry 新链路） ===
    # identifier_router → [conditional] →
    #   query_order → tool_planner → tool_executor_node → tool_success → evidence_builder
    #   verify_consistency → tool_planner (一致时) / human_review (冲突时)
    #   resolve_product → resolve_product_identity
    #   clarification → generate_reply
    #   human_review → human_review_gate
    builder.add_conditional_edges(
        "identifier_router",
        _route_after_identifier,
        {
            "verify_consistency": "verify_consistency",
            "query_order": "tool_planner",
            "resolve_product": "resolve_product_identity",
            "clarification": "generate_reply",
            "human_review": "human_review_gate",
        },
    )

    builder.add_conditional_edges(
        "verify_consistency",
        _route_after_verify_consistency,
        {
            "human_review": "human_review_gate",
            "tool_planner": "tool_planner",
        },
    )

    # 旧 JST fallback 链路：jst_live_query → resolve_order_status → match_shipping_policy → knowledge_scope_router
    builder.add_edge("jst_live_query", "resolve_order_status")
    builder.add_edge("resolve_order_status", "match_shipping_policy")
    builder.add_edge("match_shipping_policy", "knowledge_scope_router")

    # === 尾部 ===
    # 所有可能改写 suggested_reply 的节点（generate_reply, generate_logistics_reply,
    # hallucination_guard, gold_csr_reply_builder, factual_guard）执行完毕后，
    # 最终 grounding guard 放在 factual_guard 之后，
    # 确保最终输出只经过一次 grounding 校验。

    # 物流链
    builder.add_edge("generate_logistics_reply", "gold_csr_reply_builder")
    builder.add_edge("gold_csr_reply_builder", "factual_guard")
    builder.add_edge("factual_guard", "post_generation_grounding_guard")
    builder.add_edge("post_generation_grounding_guard", "reply_relevance_guard")

    # 通用链
    builder.add_edge("generate_reply", "hallucination_guard")
    builder.add_edge("hallucination_guard", "gold_csr_reply_builder")
    builder.add_edge("gold_csr_reply_builder", "factual_guard")
    builder.add_edge("factual_guard", "post_generation_grounding_guard")
    builder.add_edge("post_generation_grounding_guard", "reply_relevance_guard")

    # reply_relevance_guard 作为最终答非所问闸门，在 build_response 之前执行
    builder.add_edge("reply_relevance_guard", "build_response")

    _add_tail(builder)

    return builder.compile()


customer_service_graph = build_graph()
