"""
normalize_input 节点 - 清洗输入
"""

import time


def normalize_input(state: dict) -> dict:
    """清洗客户消息和订单号"""
    t0 = time.time()
    msg = state.get("customer_message", "").strip()
    order_id = state.get("order_id", "").strip()

    normalized = " ".join(msg.split())
    duration_ms = int((time.time() - t0) * 1000)

    trace = {
        "node": "normalize_input",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"消息长度 {len(normalized)}, 订单号 {'有' if order_id else '无'}",
    }
    return {
        "normalized_message": normalized,
        "order_id": order_id,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
