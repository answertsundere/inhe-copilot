"""
check_order_status 节点 - 将订单状态映射为细粒度状态
支持 11 种状态：unpaid, canceled, refunded, aftersales, pending_shipment,
presale, out_of_stock, partially_shipped, shipped, delivered, abnormal
"""

_STATUS_MAP = {
    # 未付款
    "未付款": "unpaid",
    "待付款": "unpaid",
    # 已取消
    "已取消": "canceled",
    "取消": "canceled",
    "关闭": "canceled",
    # 已退款
    "已退款": "refunded",
    "退款中": "refunded",
    "退款完成": "refunded",
    # 售后中
    "售后中": "aftersales",
    "售后处理中": "aftersales",
    "换货中": "aftersales",
    # 待发货
    "待发货": "pending_shipment",
    "未发货": "pending_shipment",
    # 预售
    "预售": "presale",
    "预售中": "presale",
    # 缺货/备货中
    "备货中": "out_of_stock",
    "缺货": "out_of_stock",
    "待备货": "out_of_stock",
    # 部分发货
    "部分发货": "partially_shipped",
    # 已发货
    "已发货": "shipped",
    "发货中": "shipped",
    # 已签收/已完成
    "已签收": "delivered",
    "已完成": "delivered",
    "签收": "delivered",
}

_STATUS_TEXT = {
    "unpaid": "未付款",
    "canceled": "已取消",
    "refunded": "已退款",
    "aftersales": "售后中",
    "pending_shipment": "待发货",
    "presale": "预售",
    "out_of_stock": "缺货/备货中",
    "partially_shipped": "部分发货",
    "shipped": "已发货",
    "delivered": "已签收",
    "abnormal": "异常",
}


def _map_status(status: str, shop_status: str = "") -> str:
    """将中文状态映射为内部状态码"""
    for s in (status, shop_status):
        if s in _STATUS_MAP:
            return _STATUS_MAP[s]
    # 如果都不匹配，根据字段推断
    if status in ("", "-") and shop_status in ("", "-"):
        return "abnormal"
    return "abnormal"


def check_order_status(state: dict) -> dict:
    """检查订单状态"""
    order = state.get("live_order") or state.get("order")

    if not order:
        trace = {
            "node": "check_order_status",
            "step": "order_status",
            "status": "skipped",
            "summary": "无订单信息",
        }
        return {
            "order_status": "",
            "order_status_text": "",
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    status = order.get("status", "")
    shop_status = order.get("shop_status", "")
    order_status = _map_status(status, shop_status)
    order_status_text = _STATUS_TEXT.get(order_status, "未知")

    # 部分发货判断：有多个物流记录或 items 中有部分未发
    logistics_list = state.get("logistics", []) or state.get("live_logistics", [])
    if len(logistics_list) > 1 and order_status == "shipped":
        order_status = "partially_shipped"
        order_status_text = _STATUS_TEXT["partially_shipped"]

    summary = f"订单状态: {order_status_text} ({order_status})"
    if order.get("l_id"):
        summary += f", 物流单号: {order['l_id']}"

    trace = {
        "node": "check_order_status",
        "step": "order_status",
        "status": "success",
        "summary": summary,
    }
    return {
        "order_status": order_status,
        "order_status_text": order_status_text,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
