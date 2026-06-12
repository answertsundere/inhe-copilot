"""
resolve_order_status 节点 - 解析订单状态
根据 live_order / local_order / tracking 结果综合判断
优化：记录是否已有 logistics_trace，避免后续重复查询
"""

import time


def _map_order_status(status: str) -> str:
    """映射订单状态到统一状态码"""
    s = str(status).lower().strip()
    if s in ("已签收", "已完成", "success", "delivered"):
        return "delivered"
    if s in ("已发货", "发货中", "shipped"):
        return "shipped"
    if s in ("待发货", "未发货", "pending", "pending_shipment"):
        return "pending_shipment"
    if s in ("未付款", "待付款", "unpaid"):
        return "unpaid"
    if s in ("已取消", "取消", "canceled", "cancelled"):
        return "canceled"
    if s in ("已退款", "退款", "refunded"):
        return "refunded"
    if s in ("售后中", "aftersales", "after_sale"):
        return "aftersales"
    if s in ("预售", "presale"):
        return "presale"
    if s in ("缺货", "out_of_stock"):
        return "out_of_stock"
    if s in ("部分发货", "partially_shipped"):
        return "partially_shipped"
    return s if s else "unknown"


def resolve_order_status(state: dict) -> dict:
    """解析订单状态"""
    t0 = time.time()
    order = state.get("live_order") or state.get("order")
    logistics_trace = state.get("logistics_trace")
    tracking_info = state.get("tracking_info")

    order_status = ""
    order_source = ""
    shipment_status = ""

    if order:
        raw_status = order.get("status", "")
        order_status = _map_order_status(raw_status)
        order_source = "jst" if state.get("live_order") else "local"

        if order_status == "delivered":
            shipment_status = "signed"
        elif order_status == "shipped":
            shipment_status = "shipped"
        elif order_status == "pending_shipment":
            shipment_status = "pending"
        else:
            shipment_status = order_status

    if not order and logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", ""):
        if logistics_trace.get("is_delivered"):
            shipment_status = "signed"
            order_status = "delivered"
        else:
            shipment_status = "shipped"
            order_status = "shipped"
        order_source = "tracking"

    if not order and tracking_info and tracking_info.get("success"):
        if tracking_info.get("is_delivered"):
            shipment_status = "signed"
            order_status = "delivered"
        else:
            shipment_status = "shipped"
            order_status = "shipped"
        order_source = "tracking"

    duration_ms = int((time.time() - t0) * 1000)

    # 检查是否已有物流轨迹（避免后续重复查询）
    already_has_trace = bool(
        logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", "")
    )

    trace = {
        "node": "resolve_order_status",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"订单状态: {order_status}, 来源: {order_source}, 物流状态: {shipment_status}, 已有物流轨迹: {already_has_trace}",
    }

    # 如果已有物流轨迹且 tracking_no 一致，记录 skip_duplicate_logistics_query
    if already_has_trace:
        trace["skip_duplicate_logistics_query"] = True

    return {
        "order_status": order_status,
        "order_source": order_source,
        "shipment_status": shipment_status,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
