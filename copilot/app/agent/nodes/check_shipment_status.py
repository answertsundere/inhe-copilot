"""
check_shipment_status 节点 - 检查订单发货状态
全部走聚水潭，不依赖快递100
"""


def check_shipment_status(state: dict) -> dict:
    """检查订单是否已发货"""
    import time
    t0 = time.time()

    order = state.get("live_order") or state.get("order")

    if order:
        status = order.get("status", "")
        shop_status = order.get("shop_status", "")
        l_id = order.get("l_id", "")
        logistics_company = order.get("logistics_company", "")

        if status in ("已签收", "已完成") or shop_status in ("已签收",):
            shipment = "signed"
        elif l_id and logistics_company:
            shipment = "shipped"
        elif status in ("已发货", "发货中") or shop_status in ("已发货",):
            shipment = "shipped"
        elif status in ("待发货", "备货中", "待处理"):
            shipment = "pending"
        else:
            shipment = "unknown"

        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "check_shipment_status",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"发货状态 {shipment}, 快递 {logistics_company or '无'}, 单号 {l_id or '无'}",
        }
        return {
            "shipment_status": shipment,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "check_shipment_status",
        "status": "skipped",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": "无订单信息，跳过发货检查",
    }
    return {
        "shipment_status": "unknown",
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
