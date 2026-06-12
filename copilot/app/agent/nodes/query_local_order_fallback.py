"""
query_local_order_fallback 节点 - 聚水潭不可用或无结果时降级查询本地订单
支持按 order_id 查询，也支持按 tracking_no 反查
"""

import time

from app.agent.tools.order_adapter import OrderAdapter


def query_local_order_fallback(state: dict) -> dict:
    """降级查询本地订单"""
    t0 = time.time()
    slots = state.get("slots", {})
    order_id = state.get("order_id", "")

    if not order_id:
        order_id = slots.get("possible_numeric_id", "")
    if not order_id:
        order_id = slots.get("tracking_no", "")

    if state.get("order_found"):
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "query_local_order_fallback",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "已查到订单，跳过本地查询",
        }
        return {"trace_steps": state.get("trace_steps", []) + [trace]}

    if not order_id:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "query_local_order_fallback",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "无订单号或快递单号，跳过本地查询",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    adapter = OrderAdapter()
    try:
        from app.main import get_order_repo
        adapter = OrderAdapter(local_order_repo=get_order_repo())
    except Exception:
        pass

    result = adapter.query_local(order_id)
    if result:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "query_local_order_fallback",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"本地查到订单 {order_id}",
        }
        return {
            "order": result.get("order"),
            "logistics": result.get("logistics", []),
            "order_found": True,
            "order_source": "local",
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "query_local_order_fallback",
        "status": "skipped",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"本地未找到订单 {order_id}",
    }
    updates = {
        "order_found": False,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
    possible_numeric_id = slots.get("possible_numeric_id", "")
    if possible_numeric_id and not slots.get("tracking_no") and not state.get("order_id"):
        updates["tracking_no"] = possible_numeric_id
        updates["_numeric_promoted"] = True
        updates["slots"] = {**slots, "tracking_no": possible_numeric_id, "possible_numeric_id": ""}
    return updates
