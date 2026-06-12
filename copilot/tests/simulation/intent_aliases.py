"""
Intent alias mapping — centralized, no scattered keyword patches.
"""

INTENT_ALIASES = {
    "product_question": {
        "product_question", "product_consult", "material_question", "size_question",
        "product_inquiry", "商品咨询", "产品咨询",
    },
    "logistics_eta": {
        "logistics_eta", "shipping", "logistics", "logistics_trace",
        "delivery_not_received", "物流查询", "发货查询",
    },
    "aftersales": {
        "aftersales", "return_exchange", "refund", "after_sales_return",
        "售后", "退货退款",
    },
    "installation": {
        "installation", "assembly", "安装", "组装",
    },
    "complaint": {
        "complaint", "high_risk", "complaint_high_risk",
        "投诉", "高风险",
    },
    "clarification": {
        "clarification", "general", "unknown", "other",
        "其他", "澄清",
    },
}

STRATEGY_ALIASES = {
    "product_chain": {"product_chain", "product_question", "product_answer"},
    "logistics_with_order": {"logistics_with_order", "logistics_chain", "jst_order"},
    "logistics_policy_without_order": {"logistics_policy_without_order", "logistics_policy"},
    "aftersales_chain": {"aftersales_chain", "aftersales_policy"},
    "installation_chain": {"installation_chain", "installation_guide"},
    "high_risk": {"high_risk", "complaint", "human_review"},
}

VALID_SCENARIOS = {
    "pre_sale_product", "logistics", "after_sales_return",
    "installation", "complaint_high_risk", "edge_composite",
}

VALID_PRIORITIES = {"P0", "P1", "P2"}


def intent_matches(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    aliases = INTENT_ALIASES.get(expected, {expected})
    return actual in aliases


def strategy_matches(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    aliases = STRATEGY_ALIASES.get(expected, {expected})
    return actual in aliases
