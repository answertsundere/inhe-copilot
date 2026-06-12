"""
verify_consistency 节点 - 验证 tracking_no 和 order_id 是否一致
如果订单中有 l_id，检查是否与 slot 中的 tracking_no 匹配
设置 consistency_status 供后续条件路由使用
"""


def verify_consistency(state: dict) -> dict:
    """验证订单号与快递单号一致性"""
    slots = state.get("slots", {})
    tracking_no = slots.get("tracking_no", "")
    order_id = slots.get("order_id", "")

    order = state.get("live_order") or state.get("order")
    order_found = state.get("order_found", False)

    # 只有 tracking_no，没有 order_id
    if tracking_no and not order_id:
        trace = {
            "node": "verify_consistency",
            "step": "consistency_check",
            "status": "success",
            "summary": f"仅有快递单号 {tracking_no}，无需一致性验证",
        }
        return {
            "consistency_status": "tracking_only",
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 同时有 order_id 和 tracking_no
    if order_id and tracking_no:
        # 订单已查到，检查一致性
        if order:
            l_id = order.get("l_id", "")
            if l_id and l_id != tracking_no:
                trace = {
                    "node": "verify_consistency",
                    "step": "consistency_check",
                    "status": "warning",
                    "summary": f"订单物流单号 {l_id} 与提供单号 {tracking_no} 不一致",
                }
                return {
                    "consistency_status": "conflict",
                    "order_status": "inconsistent_ids",
                    "requires_human_review": True,
                    "review_reason": "订单号与快递单号不一致",
                    "trace_steps": state.get("trace_steps", []) + [trace],
                }

            trace = {
                "node": "verify_consistency",
                "step": "consistency_check",
                "status": "success",
                "summary": f"订单号 {order_id} 与快递单号 {tracking_no} 一致",
            }
            return {
                "consistency_status": "matched",
                "trace_steps": state.get("trace_steps", []) + [trace],
            }

        # 订单还没查到，需要先查订单
        trace = {
            "node": "verify_consistency",
            "step": "consistency_check",
            "status": "success",
            "summary": f"同时有订单号 {order_id} 和快递单号 {tracking_no}，需要先查订单",
        }
        return {
            "consistency_status": "need_order_lookup",
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 都没有（理论上不应到这里，因为路由只有同时有两个才会来）
    trace = {
        "node": "verify_consistency",
        "step": "consistency_check",
        "status": "success",
        "summary": "无需验证",
    }
    return {
        "consistency_status": "",
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
