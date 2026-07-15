"""
AgentState - LangGraph 状态定义
"""

from typing import TypedDict, Optional


class AgentState(TypedDict, total=False):
    """客服 Copilot Agent 状态"""

    # ========== 输入字段 ==========
    customer_message: str
    conversation_id: str
    order_id: str
    tracking_no: str  # 前端/API 传入的快递单号
    image_attachments: list  # 客户消息中的图片附件元数据，不保存原图

    # ========== Slot 抽取结果 ==========
    slots: dict  # {
    #   "order_id": "", "platform_order_id": "", "jst_order_id": "",
    #   "tracking_no": "", "carrier": "",
    #   "identifier_type": "",  # "order_id" | "tracking_no" | "unknown_identifier" | ""
    #   "product_name": "", "sku_name": "", "sku_code": "",
    #   "platform": "", "time_hint": "", "location_hint": "",
    #   "risk_keywords": [], "has_screenshot": False
    # }

    # ========== 规范化与意图 ==========
    normalized_message: str
    intent: str
    skill: str
    matched_keywords: list
    is_logistics_time_commitment: bool
    query_fact_type: str
    query_fact_type_label: str
    query_fact_type_confidence: float
    query_fact_type_source: str
    query_fact_type_terms: list
    query_fact_type_reason: str
    query_fact_type_risk_hint: str
    secondary_fact_types: list
    semantic_query: dict
    needs_visual_asset: bool

    # ========== 风险 ==========
    risk_level: str
    requires_human_review: bool
    review_reason: str
    reason_for_review: str
    reply_tone: str
    evidence_used: str
    tools_to_call: list

    # ========== 订单/物流查询结果（旧字段保留兼容） ==========
    order: Optional[dict]
    logistics: list
    live_order: Optional[dict]
    live_logistics: list
    order_found: bool
    order_source: str  # "jst" | "local" | ""
    shipment_status: str  # "shipped" | "pending" | "signed" | "unknown"
    tracking_info: Optional[dict]  # 物流查询结果（legacy, 已由 logistics_trace 替代）

    # ========== 新增：订单细粒度状态 ==========
    order_status: str  # unpaid/canceled/refunded/aftersales/pending_shipment/
                       # presale/out_of_stock/partially_shipped/shipped/delivered/abnormal
    order_status_text: str  # 中文描述

    # ========== 新增：物流轨迹 ==========
    logistics_trace: Optional[dict]  # {
    #   "status": "picked_up/in_transit/out_for_delivery/delivered/no_trace/stalled/returned/damaged/lost/api_failed",
    #   "carrier": "", "tracking_no": "", "events": [], "latest": {}, "low_confidence": False
    # }

    # ========== 新增：商品识别 ==========
    product_candidates: list  # 多候选商品列表
    need_clarification: bool  # 是否需要追问
    clarification_question: str  # 追问内容
    needs_clarification: bool  # 是否需要买家补充信息（模糊问题）

    # ========== 新增：证据与事实 ==========
    evidence: dict  # {
    #   "verified_facts": [], "estimated_facts": [],
    #   "unknowns": [], "conflicts": [], "evidence_sources": []
    # }

    # ========== 新增：回答类型 ==========
    answer_type: str  # verified/estimated/clarification_needed/fallback/human_review
    consistency_status: str  # matched/conflict/need_order_lookup/tracking_only

    # ========== 商品与知识 ==========
    products: list
    product_knowledge: list
    knowledge: list
    matched_product_name: str
    order_product_identity: dict
    product_identity_source: str
    shipping_policy: dict

    # ========== SOP / 模板 ==========
    sop_scenarios: list
    reply_templates: list

    # ========== 策略路由 ==========
    response_strategy: str
    response_strategy_plan: dict
    reply_goal: str
    reply_structure: list
    missing_slots: list
    customer_state: dict
    customer_urgency: str
    customer_concern: str
    needs_human_review: bool
    router_decision: dict
    router_source: str
    router_confidence: float
    router_reason: str
    selected_tool: str
    identifier_type: str
    identifier_value: str
    should_query_facts: bool
    fact_tools: list
    should_query_knowledge: bool
    knowledge_timing: str
    answer_mode: str

    # ========== 知识库 RAG ==========
    allowed_source_types: list
    retrieved_chunks: list
    filtered_evidence: list
    knowledge_evidence: list
    current_query: str
    retrieval_query: str
    generated_context: dict
    history_snapshot: dict
    context_reset_reason: str
    rag_retrieval_mode: str
    product_context_pack: dict
    product_context_pack_stats: dict
    # Opt-in formal evidence convergence.  These fields are emitted by the
    # existing evidence-builder node and are intentionally separate from raw
    # retrieval candidates and customer-facing delivery fields.
    selected_evidence: list
    admitted_answer_context: dict
    minimal_decision_context: dict
    supervisor_candidate_preview: dict
    formal_evidence_convergence: dict

    # ========== LLM / 回复生成 ==========
    suggested_reply: str
    customer_emotion: str
    reply_style: str
    policy_warnings: list
    action_proposal: dict
    llm_error: str
    llm_skipped: bool
    llm_used: bool
    generation_mode: str
    hallucination_guard: dict
    used_knowledge_entry_ids: list
    used_knowledge_titles: list

    # ========== 守卫与输出 ==========
    guard_warnings: list
    error: str

    # ========== 上下文与溯源 ==========
    context_used: dict
    copilot_context: dict
    conversation_context: dict
    conversation_context_summary: dict
    context_updated: bool
    trace_steps: list
    data_source: str
    sources: list
    _numeric_promoted: bool  # possible_numeric_id 被提升为 tracking_no 的标记

    # ========== 调试：证据分层摘要 ==========
    evidence_debug: dict

    # ========== Parallel Understanding Layer (Phase 1 observation mode) ==========
    parallel_understanding: dict
    decision_fusion: dict
    safety_contract: dict
    final_intent: str
    secondary_intents: list
    analyzer_durations: dict
    fusion_reasons: list
    parallel_observation_mode: bool

    # ========== 工具注册层 ==========
    allowed_tools: list       # 当前策略允许使用的工具名列表
    required_tools: list      # 当前策略必须使用的工具名列表
    forbidden_tools: list     # 当前策略禁止使用的工具名列表
    tool_plan: list           # tool_planner 输出的工具调用计划
    tool_results: dict        # tool_executor 输出的工具执行结果
    tool_traces: list         # tool_executor 输出的工具执行 trace
    tool_planner_source: str  # "llm" | "auto_required"
    used_fact_tool: str       # 实际使用的事实工具名
    used_endpoint: str        # 实际使用的 JST endpoint


# ---------------------------------------------------------------------------
# Shared helper: order identifier detection
# ---------------------------------------------------------------------------
def has_order_identifier(state: dict) -> bool:
    """Check if slots/state contain ANY order identifier.

    Supported identifiers (any one suffices):
      - slots.order_id / state.order_id
      - slots.platform_trade_id
      - slots.platform_order_id
      - slots.tracking_no / state.tracking_no
      - slots.possible_numeric_id
    """
    slots = state.get("slots", {}) or {}
    return bool(
        slots.get("order_id")
        or state.get("order_id", "")
        or slots.get("platform_trade_id")
        or slots.get("platform_order_id")
        or slots.get("tracking_no")
        or state.get("tracking_no", "")
        or slots.get("possible_numeric_id")
    )
