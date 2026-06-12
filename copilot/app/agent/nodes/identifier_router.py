"""
identifier_router 节点 - 根据抽取到的标识符决定查询路径
优先级：
1. 高风险 → human_review_gate
2. 同时有 order_id 和 tracking_no → verify_consistency
3. 有 platform_trade_id → query_order
4. 有 order_id → query_order
5. 有 possible_numeric_id → query_order（先查订单，查不到再查快递）
6. 只有 tracking_no → query_order（聚水潭反查）
7. 有 product_name → resolve_product
8. 什么都没有 → clarification_needed
"""

import time


def identifier_router(state: dict) -> dict:
    """标识符路由，记录分支决策"""
    t0 = time.time()
    slots = state.get("slots", {})

    tracking_no = slots.get("tracking_no", "")
    order_id = slots.get("order_id", "")
    platform_trade_id = slots.get("platform_trade_id", "")
    possible_numeric_id = slots.get("possible_numeric_id", "")
    product_name = slots.get("product_name", "")
    identifier_type = slots.get("identifier_type", "")

    summary_parts = []
    if identifier_type:
        summary_parts.append(f"identifier_type={identifier_type}")
    if order_id:
        summary_parts.append(f"订单号={order_id}")
    if platform_trade_id:
        summary_parts.append(f"平台交易号={platform_trade_id}")
    if tracking_no:
        summary_parts.append(f"快递单号={tracking_no}")
    if possible_numeric_id:
        summary_parts.append(f"数字编号={possible_numeric_id}")
    if product_name:
        summary_parts.append(f"商品={product_name}")

    summary = "; ".join(summary_parts) if summary_parts else "无标识符"
    duration_ms = int((time.time() - t0) * 1000)

    trace = {
        "node": "identifier_router",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"路由决策: {summary}",
    }
    return {
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


# ========== 条件边函数 ==========

def _route_identifier(state: dict) -> str:
    """主路由决策"""
    slots = state.get("slots", {})
    risk_level = state.get("risk_level", "low")
    intent = state.get("intent", "")

    if risk_level in ("high", "critical"):
        return "human_review"

    tracking_no = slots.get("tracking_no", "")
    order_id = slots.get("order_id", "")
    platform_trade_id = slots.get("platform_trade_id", "")
    possible_numeric_id = slots.get("possible_numeric_id", "")
    product_name = slots.get("product_name", "")
    identifier_type = slots.get("identifier_type", "")

    # 非物流意图路由
    if intent not in ("logistics_eta", "shipping", "logistics", "delivery_not_received"):
        if product_name:
            return "resolve_product"
        # platform_trade_id with non-logistics intent still needs order lookup
        if identifier_type in ("platform_trade_id", "internal_order_id", "platform_order_id", "unknown_identifier"):
            return "query_order"
        return "clarification"

    # 物流意图 + platform_trade_id
    if identifier_type == "platform_trade_id":
        return "query_order"

    if order_id and tracking_no:
        return "verify_consistency"

    if order_id:
        return "query_order"

    if platform_trade_id:
        return "query_order"

    if possible_numeric_id:
        return "query_order"

    if tracking_no:
        # 有快递单号走聚水潭查订单（JST 支持 l_id 反查）
        if order_id:
            return "verify_consistency"
        return "query_order"

    if product_name:
        return "resolve_product"

    return "clarification"


def route_from_identifier(state: dict) -> str:
    """从 identifier_router 出发的条件边"""
    return _route_identifier(state)


def route_after_order_query(state: dict) -> str:
    """查完订单后的路由"""
    order_found = state.get("order_found", False)
    order = state.get("live_order") or state.get("order")

    if order_found and order:
        return "check_order_status"

    slots = state.get("slots", {})
    if slots.get("tracking_no"):
        return "query_order"

    possible_numeric_id = slots.get("possible_numeric_id", "")
    if possible_numeric_id and not slots.get("order_id"):
        return "query_order"

    if slots.get("product_name"):
        return "resolve_product"

    return "clarification"


def route_after_tracking_query(state: dict) -> str:
    """查完物流后的路由"""
    logistics_trace = state.get("logistics_trace")
    order = state.get("live_order") or state.get("order")

    if logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", ""):
        return "has_logistics"

    if order:
        return "check_order_status"

    slots = state.get("slots", {})
    if slots.get("product_name"):
        return "resolve_product"

    return "clarification"


def route_after_product_resolve(state: dict) -> str:
    """商品识别后的路由"""
    need_clarification = state.get("need_clarification", False)
    if need_clarification:
        return "clarification"
    return "match_shipping_policy"


def route_after_order_status(state: dict) -> str:
    """订单状态检查后的路由"""
    order_status = state.get("order_status", "")

    if order_status in ("shipped", "delivered", "partially_shipped"):
        return "query_logistics"

    return "generate_reply"


def route_after_tracking_query(state: dict) -> str:
    """查完物流后的路由"""
    logistics_trace = state.get("logistics_trace")
    order = state.get("live_order") or state.get("order")

    if logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", ""):
        return "has_logistics"

    if order:
        return "check_order_status"

    slots = state.get("slots", {})
    if slots.get("product_name"):
        return "resolve_product"

    return "clarification"
