"""
route_by_intent 节点 - 根据意图路由
第一阶段只实现 logistics_eta 链路，其他意图直接生成回复。
"""

import time


def route_by_intent(state: dict) -> dict:
    """意图路由，记录分支"""
    t0 = time.time()
    intent = state.get("intent", "general")
    order_id = state.get("order_id", "")
    msg = state.get("customer_message", "")

    summary = f"意图 {intent}"
    if intent in ("logistics_eta", "shipping", "logistics"):
        has_tracking = bool(_extract_tracking(order_id) or _extract_tracking(msg))
        summary += f", 订单号/快递单号 {'有' if has_tracking else '无'}"

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "route_by_intent",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": summary,
    }
    return {
        "order_found": state.get("order_found", False),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _extract_tracking(text: str) -> str | None:
    """从文本中提取快递单号"""
    if not text:
        return None
    from app.services.tracking_service import extract_tracking_no
    return extract_tracking_no(text)


def should_query_order(state: dict) -> str:
    """条件边：是否查询订单/物流"""
    intent = state.get("intent", "")
    order_id = state.get("order_id", "")
    msg = state.get("customer_message", "")

    if intent not in ("logistics_eta", "shipping", "logistics"):
        return "skip_order"

    if order_id or _extract_tracking(msg):
        return "query_order"

    return "skip_order"


def should_match_product(state: dict) -> str:
    """条件边：是否从消息匹配商品"""
    intent = state.get("intent", "")
    order = state.get("order")
    if intent in ("logistics_eta", "shipping", "logistics") and not order:
        return "match_product"
    return "skip_product"
