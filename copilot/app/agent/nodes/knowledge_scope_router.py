"""
knowledge_scope_router 节点
根据 intent、risk_level、product_identity 决定允许检索哪些 source_type
"""

import time


# intent → 允许 source_type 映射
INTENT_SOURCE_MAP = {
    "logistics_eta": ["shipping_policy", "product_facts", "response_templates"],
    "shipping": ["shipping_policy", "product_facts", "response_templates"],
    "logistics": ["shipping_policy", "product_facts", "response_templates"],
    "product_question": ["product_facts", "product_mapping", "faq"],
    "product_consult": ["product_facts", "product_mapping", "faq"],
    "installation": ["installation_guide", "product_facts", "faq"],
    "aftersales": ["aftersales_policy", "forbidden_rules", "response_templates"],
    "complaint": ["high_risk_sop", "forbidden_rules", "response_templates"],
    "high_risk": ["high_risk_sop", "forbidden_rules", "response_templates"],
}

# 禁止的 source_type（按 intent）
INTENT_FORBIDDEN_MAP = {
    "logistics_eta": ["aftersales_policy", "installation_guide", "real_cases"],
    "shipping": ["aftersales_policy", "installation_guide", "real_cases"],
    "logistics": ["aftersales_policy", "installation_guide", "real_cases"],
    "product_question": ["shipping_policy", "aftersales_policy", "real_cases"],
}


def knowledge_scope_router(state: dict) -> dict:
    """知识范围路由：优先读取 response_strategy_router 输出，避免重复判断"""
    t0 = time.time()
    intent = state.get("intent", "general")
    risk_level = state.get("risk_level", "low")

    # 优先使用 response_strategy_router 已决定的 allowed_source_types
    strategy_allowed = state.get("allowed_source_types", [])
    if strategy_allowed:
        allowed = strategy_allowed
        forbidden = []
    else:
        allowed = INTENT_SOURCE_MAP.get(intent, ["faq", "response_templates"])
        forbidden = INTENT_FORBIDDEN_MAP.get(intent, [])

    # 高风险投诉强制人工复核
    required_human_review = False
    if intent in ("complaint", "high_risk") or risk_level in ("high", "critical"):
        required_human_review = True

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "knowledge_scope_router",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"意图 {intent}: 允许 {allowed}, 需人工复核 {required_human_review}",
    }

    result = {
        "allowed_source_types": allowed,
        "forbidden_source_types": forbidden,
        "requires_human_review": required_human_review or state.get("requires_human_review", False),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
    return result
