"""
response_strategy_router 节点
根据当前 state 统一决定：
1. 是否需要事实工具
2. 是否需要知识库
3. 知识库检索应该在事实工具之前还是之后
4. 本轮 answer_mode
"""

import re
import time

from app.services.product_context_consistency import evaluate_product_context


# 策略映射表
# 优先级：high_risk > aftersales > installation > logistics > product_question > unknown

STRATEGY_MAP = [
    # (条件检查函数, 策略配置)
    # 高优先级在前
]

IMAGE_MARKER_RE = re.compile(r"\[\s*\u56fe\u7247\s*\d*\s*\]")
TEXT_PRODUCT_QUESTION_TERMS = (
    "\u5417", "\u5462", "\u600e\u4e48", "\u5982\u4f55", "\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd", "\u662f\u4e0d\u662f", "\u6709\u6ca1\u6709",
    "\u4f1a\u4e0d\u4f1a", "\u53ef\u62c6", "\u62c6\u5378", "\u5b89\u88c5",
    "\u7ec4\u88c5", "\u6750\u8d28", "\u627f\u91cd", "\u5c3a\u5bf8",
    "\u6e05\u6d17", "\u9632\u6f6e",
)


def _has_identifier(state: dict) -> bool:
    slots = state.get("slots", {})
    return bool(
        state.get("order_id", "")
        or slots.get("order_id", "")
        or slots.get("platform_trade_id", "")
        or slots.get("platform_order_id", "")
        or slots.get("tracking_no", "")
        or slots.get("possible_numeric_id", "")
    )


def _is_high_risk(state: dict) -> bool:
    intent = state.get("intent", "")
    risk_level = state.get("risk_level", "low")
    return intent in ("complaint", "high_risk") or risk_level in ("high", "critical")


def _is_aftersales(state: dict) -> bool:
    return state.get("intent", "") in (
        "aftersales", "invoice", "price_protection", "price_promotion",
        "promotion_query", "gift_missing", "stock_query", "image_attachment",
    )


def _is_installation(state: dict) -> bool:
    return state.get("intent", "") in ("installation",)


def _is_logistics(state: dict) -> bool:
    return state.get("intent", "") in (
        "logistics_eta", "logistics_trace", "shipping", "logistics", "delivery_not_received",
    )


def _has_sidecar_product_context(state: dict) -> bool:
    ctx = state.get("copilot_context", {}) or {}
    identity = state.get("order_product_identity") or {}
    return bool(
        state.get("matched_product_name")
        or state.get("product_candidates")
        or ctx.get("product_name")
        or ctx.get("product_candidates")
        or identity.get("status") == "resolved"
    )


def _has_text_product_question(state: dict) -> bool:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    text = IMAGE_MARKER_RE.sub("", msg).strip()
    return bool(text and any(term in text for term in TEXT_PRODUCT_QUESTION_TERMS))


def _has_embedded_product_question(state: dict) -> bool:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    product_terms = (
        "材质", "材料", "安全吗", "安全不", "受潮", "防潮", "甲醛", "检测报告",
        "承重", "尺寸", "大小", "多大", "几岁", "适合", "清洁", "水洗", "安装", "怎么装",
        "图片", "照片", "实物图", "效果图", "样子",
        "有味道", "味道", "刺鼻",
    )
    return _has_sidecar_product_context(state) and any(term in msg for term in product_terms)


def _looks_like_product_followup(state: dict) -> bool:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    if not _has_sidecar_product_context(state) or not msg:
        return False
    terms = (
        "这个", "这款", "它", "商品", "宝贝", "款", "基础款", "升级款", "升级版",
        "差什么", "差别", "差异", "区别", "对比", "哪个好", "怎么选", "能买吗",
        "能用吗", "好用吗", "适合吗", "靠谱吗",
    )
    if any(term in msg for term in terms):
        return True
    question_markers = ("吗", "么", "呢", "怎么", "如何", "是不是", "有没有", "能不能", "可以不", "可以吗")
    return len(msg) <= 30 and any(marker in msg for marker in question_markers)


def _is_product_question(state: dict) -> bool:
    return state.get("intent", "") in (
        "product_question", "product_consult", "child_safety",
        "competitor_compare", "odor_question", "cleaning_care", "material_safety",
    )


def _is_clarification(state: dict) -> bool:
    return state.get("intent", "") in ("needs_clarification", "image_attachment")


def _has_ambiguous_sidecar_product_name(state: dict) -> bool:
    """Check if there are truly multiple competing product candidates.

    Only returns True when there are 2+ distinct product identities (different i_id).
    A single candidate with low confidence is NOT ambiguous — it's low_confidence.
    """
    identity = state.get("order_product_identity") or {}
    if identity.get("source") != "sidecar_product_name":
        return False
    if identity.get("status") != "ambiguous":
        return False
    candidates = identity.get("candidates") or []
    # Count distinct products by i_id (or name if i_id missing)
    distinct_ids = set()
    for c in candidates:
        if not isinstance(c, dict):
            continue
        pid = c.get("i_id") or c.get("name") or ""
        if pid:
            distinct_ids.add(pid)
    # Only truly ambiguous if 2+ distinct products
    return len(distinct_ids) >= 2


def response_strategy_router(state: dict) -> dict:
    """统一策略路由：决定本轮需要事实工具、知识库、以及它们的执行顺序"""
    t0 = time.time()
    intent = state.get("intent", "general")
    risk_level = state.get("risk_level", "low")
    slots = state.get("slots", {})
    ctx = state.get("copilot_context", {}) or {}
    identity = state.get("order_product_identity") or {}
    has_id = _has_identifier(state)
    has_embedded_product_question = _has_embedded_product_question(state)
    has_product_followup = _looks_like_product_followup(state)
    force_product_clarification = _has_ambiguous_sidecar_product_name(state)

    # 品类冲突检测：买家问的品类与当前商品不一致（如问“放多少本绘本”却是水龙头延长器）
    _ctx_msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    _category_text = (
        identity.get("category_l3", "")
        or identity.get("category_l2", "")
        or identity.get("category", "")
    )
    product_context_validation = evaluate_product_context(
        _ctx_msg,
        state.get("matched_product_name", ""),
        _category_text,
    )

    # 默认策略
    strategy = "clarification"
    should_query_facts = False
    fact_tools = []
    should_query_knowledge = True
    allowed_source_types = ["faq", "response_templates"]
    knowledge_timing = "none"
    answer_mode = "clarification"

    # 1. 高风险 / 投诉（最高优先级）
    if force_product_clarification:
        strategy = "clarification"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = False
        allowed_source_types = []
        knowledge_timing = "none"
        answer_mode = "no_evidence_clarification"

    elif _is_high_risk(state):
        strategy = "high_risk"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = True
        allowed_source_types = ["high_risk_sop", "forbidden_rules", "response_templates"]
        knowledge_timing = "sop_only"
        answer_mode = "human_review"

    # 1.5 模糊问题/图片依赖：不查知识，直接要求补充信息
    elif intent == "image_attachment" and _has_sidecar_product_context(state) and _has_text_product_question(state):
        strategy = "product_question"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = True
        allowed_source_types = ["product_facts", "product_mapping", "faq"]
        knowledge_timing = "before_reply"
        answer_mode = "product_answer"

    elif _is_clarification(state):
        strategy = "clarification"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = False
        allowed_source_types = []
        knowledge_timing = "none"
        answer_mode = "no_evidence_clarification"

    # 2. 售后
    elif _is_aftersales(state):
        strategy = "aftersales"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = intent != "image_attachment"
        allowed_source_types = ["aftersales_policy", "forbidden_rules", "response_templates"]
        if state.get("query_fact_type") in {
            "pinch_safety",
            "safety_small_parts",
            "material",
            "certification_report",
            "aftersales_policy",
        }:
            allowed_source_types = [
                "aftersales_policy", "high_risk_sop", "product_facts",
                "faq", "forbidden_rules", "response_templates",
            ]
        knowledge_timing = "none" if intent == "image_attachment" else "before_reply"
        answer_mode = "aftersales_policy"

    # 3. 安装
    elif _is_installation(state):
        strategy = "installation"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = True
        allowed_source_types = ["installation_guide", "product_facts", "faq"]
        knowledge_timing = "before_reply"
        answer_mode = "installation_guide"

    # 4. 物流
    elif _is_logistics(state):
        is_commitment = state.get("is_logistics_time_commitment", False)
        if has_id:
            strategy = "logistics_with_order"
            should_query_facts = True
            fact_tools = ["jst_live_query"]
            should_query_knowledge = True
            allowed_source_types = ["shipping_policy", "response_templates"]
            if has_embedded_product_question:
                allowed_source_types = ["shipping_policy", "product_facts", "faq", "response_templates"]
            knowledge_timing = "after_facts"
            answer_mode = "logistics_time_commitment" if is_commitment else "verified"
        else:
            strategy = "logistics_policy_without_order"
            should_query_facts = False
            fact_tools = []
            should_query_knowledge = True
            allowed_source_types = ["shipping_policy", "product_facts", "response_templates"]
            if has_embedded_product_question:
                allowed_source_types = ["shipping_policy", "product_facts", "faq", "response_templates"]
            knowledge_timing = "policy_only"
            answer_mode = "logistics_time_commitment" if is_commitment else "policy"

    # 5. 商品咨询
    elif _is_product_question(state) or has_product_followup:
        if product_context_validation.get("mismatch"):
            # 品类冲突：问的不是这款商品，强制澄清，不查知识/工具，避免拿无关字段硬答
            strategy = "clarification"
            should_query_facts = False
            fact_tools = []
            should_query_knowledge = False
            allowed_source_types = []
            knowledge_timing = "none"
            answer_mode = "no_evidence_clarification"
        else:
            strategy = "product_question"
            should_query_facts = False
            fact_tools = []
            should_query_knowledge = True
            allowed_source_types = ["product_facts", "product_mapping", "faq"]
            knowledge_timing = "before_reply"
            answer_mode = "product_answer"

    # 6. 未知 / 通用
    else:
        strategy = "clarification"
        should_query_facts = False
        fact_tools = []
        should_query_knowledge = True
        allowed_source_types = ["faq", "response_templates"]
        knowledge_timing = "none"
        answer_mode = "clarification"

    # ========== 计算工具权限列表 ==========
    allowed_tools, required_tools, forbidden_tools = _compute_tool_lists(state, strategy, has_id)

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "response_strategy_router",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"策略={strategy}, required={required_tools}, allowed={allowed_tools}, forbidden={forbidden_tools}, 模式={answer_mode}",
        "product_context_debug": {
            "has_sidecar_product_context": _has_sidecar_product_context(state),
            "product_candidates_count": len(state.get("product_candidates") or []),
            "copilot_product_candidates_count": len(ctx.get("product_candidates") or []),
            "matched_product_name": state.get("matched_product_name", ""),
            "slot_product_name": (slots or {}).get("product_name", ""),
            "identity_status": identity.get("status", ""),
            "identity_source": identity.get("source", ""),
        },
    }

    return {
        "response_strategy": strategy,
        "should_query_facts": should_query_facts,
        "fact_tools": fact_tools,
        "should_query_knowledge": should_query_knowledge,
        "allowed_source_types": allowed_source_types,
        "knowledge_timing": knowledge_timing,
        "answer_mode": answer_mode,
        "allowed_tools": allowed_tools,
        "required_tools": required_tools,
        "forbidden_tools": forbidden_tools,
        "product_context_validation": product_context_validation,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _compute_tool_lists(state: dict, strategy: str, has_id: bool) -> tuple:
    """根据策略计算 allowed_tools, required_tools, forbidden_tools。
    Returns (allowed_tools, required_tools, forbidden_tools)
    """
    slots = state.get("slots", {})
    identifier_type = slots.get("identifier_type", "")
    intent = state.get("intent", "general")
    risk_level = state.get("risk_level", "low")

    # 公共可用工具（所有策略都可以选）
    has_embedded_product_question = _has_embedded_product_question(state)
    common_allowed = ["rag_search_tool", "template_select_tool"]

    if strategy == "high_risk":
        # 投诉/高风险：必须 SOP，禁止 JST 事实工具
        required = ["sop_lookup_tool"]
        allowed = ["sop_lookup_tool"] + common_allowed
        forbidden = [
            "jst_lookup_order_tool", "jst_lookup_outbound_tool",
            "jst_lookup_tracking_tool", "product_resolver_tool",
        ]

    elif strategy == "aftersales":
        if has_id:
            if identifier_type == "platform_trade_id":
                jst_tool = "jst_lookup_outbound_tool"
            elif identifier_type == "tracking_no":
                jst_tool = "jst_lookup_tracking_tool"
            else:
                jst_tool = "jst_lookup_order_tool"
            required = [jst_tool]
            allowed = [jst_tool] + common_allowed
            forbidden = [
                t for t in [
                    "jst_lookup_order_tool", "jst_lookup_outbound_tool",
                    "jst_lookup_tracking_tool",
                ] if t != jst_tool
            ]
        else:
            required = []
            allowed = common_allowed
            forbidden = [
                "jst_lookup_order_tool", "jst_lookup_outbound_tool",
                "jst_lookup_tracking_tool",
            ]

    elif strategy == "installation":
        # Installation always needs product resolver + RAG for install guides
        required = ["product_resolver_tool", "rag_search_tool"]
        allowed = ["product_resolver_tool"] + common_allowed
        forbidden = [
            "jst_lookup_order_tool", "jst_lookup_outbound_tool",
            "jst_lookup_tracking_tool",
        ]
        # If there's an order identifier, add the appropriate JST tool
        # so we can resolve product identity from the order
        if has_id and identifier_type == "platform_trade_id":
            required.append("jst_lookup_outbound_tool")
            allowed.append("jst_lookup_outbound_tool")
            forbidden = [t for t in forbidden if t != "jst_lookup_outbound_tool"]
        elif has_id and identifier_type in ("internal_order_id", "platform_order_id"):
            required.append("jst_lookup_order_tool")
            allowed.append("jst_lookup_order_tool")
            forbidden = [t for t in forbidden if t != "jst_lookup_order_tool"]
        elif has_id and identifier_type == "tracking_no":
            required.append("jst_lookup_tracking_tool")
            allowed.append("jst_lookup_tracking_tool")
            forbidden = [t for t in forbidden if t != "jst_lookup_tracking_tool"]

    elif strategy == "logistics_with_order":
        # 根据 identifier_type 选择正确的 JST 工具
        if identifier_type in ("platform_trade_id", "platform_order_id"):
            jst_tool = "jst_lookup_outbound_tool"
        elif identifier_type == "tracking_no":
            jst_tool = "jst_lookup_tracking_tool"
        else:
            jst_tool = "jst_lookup_order_tool"

        required = [jst_tool]
        allowed = [jst_tool] + common_allowed + ["product_resolver_tool"]
        if has_embedded_product_question:
            for tool in ("product_resolver_tool", "rag_search_tool"):
                if tool not in required:
                    required.append(tool)
        # 禁止使用错误的 JST 工具
        forbidden = [
            t for t in [
                "jst_lookup_order_tool", "jst_lookup_outbound_tool",
                "jst_lookup_tracking_tool",
            ] if t != jst_tool
        ]

    elif strategy == "logistics_policy_without_order":
        required = []
        allowed = common_allowed + ["product_resolver_tool"]
        if has_embedded_product_question:
            required = ["product_resolver_tool", "rag_search_tool"]
        forbidden = [
            "jst_lookup_order_tool", "jst_lookup_outbound_tool",
            "jst_lookup_tracking_tool",
        ]

    elif strategy == "product_question":
        required = ["product_resolver_tool", "rag_search_tool"]
        allowed = ["product_resolver_tool"] + common_allowed
        forbidden = [
            "jst_lookup_order_tool", "jst_lookup_outbound_tool",
            "jst_lookup_tracking_tool", "sop_lookup_tool",
        ]

    else:
        # clarification / general
        required = []
        allowed = common_allowed
        forbidden = [
            "jst_lookup_order_tool", "jst_lookup_outbound_tool",
            "jst_lookup_tracking_tool",
        ]

    # Only override with full block when there is a SEPARATELY resolved identity
    # from a stronger source (SKU code, order items). In that case the
    # ambiguity from sidecar title matching is irrelevant and we should
    # trust the resolved identity.
    if _has_ambiguous_sidecar_product_name(state):
        # Check if there's a resolved identity from a stronger source
        identity = state.get("order_product_identity") or {}
        has_resolved = (
            identity.get("status") == "resolved"
            and identity.get("source") in (
                "jst_order_items", "sidecar_product_code",
                "jst_sku_query", "jst_product_query", "jst_product_name_query",
            )
        )
        if not has_resolved:
            # Truly ambiguous: block tools to force clarification
            required = []
            allowed = []
            forbidden = [
                "jst_lookup_order_tool", "jst_lookup_outbound_tool",
                "jst_lookup_tracking_tool", "product_resolver_tool",
                "rag_search_tool", "sop_lookup_tool", "template_select_tool",
            ]

    return _validate_tool_invariants(allowed, required, forbidden, strategy)


def _validate_tool_invariants(allowed, required, forbidden, strategy):
    """Validate and fix tool list invariants.

    Rules:
    1. required ∩ forbidden must be empty
    2. required ⊆ allowed
    3. product_question/installation must have product_resolver + rag
    """
    import logging
    logger = logging.getLogger(__name__)

    allowed = list(allowed or [])
    required = list(required or [])
    forbidden = list(forbidden or [])

    # 1. Remove any required tool from forbidden
    overlap = set(required) & set(forbidden)
    if overlap:
        forbidden = [t for t in forbidden if t not in required]
        logger.warning("strategy=%s: removed %s from forbidden (conflicts with required)", strategy, overlap)

    # 2. Ensure all required are in allowed
    for rt in required:
        if rt not in allowed:
            allowed.append(rt)

    # 3. For product_question/installation, ensure minimum tools
    if strategy in ("product_question", "installation"):
        for tool in ("product_resolver_tool", "rag_search_tool"):
            if tool not in required:
                required.append(tool)
            if tool not in allowed:
                allowed.append(tool)
            if tool in forbidden:
                forbidden = [t for t in forbidden if t != tool]

    return allowed, required, forbidden
