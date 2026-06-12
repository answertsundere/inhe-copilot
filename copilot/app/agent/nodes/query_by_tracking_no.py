"""
query_by_tracking_no 节点 - LEGACY：直接根据物流单号查询快递100
此节点已从正式链路移除（graph.py 不再使用）。
物流查询已统一走聚水潭（query_jst_order + query_logistics_trace）。
仅保留用于测试和向后兼容。
"""

import time

from app.services.tracking_service import query_tracking
from app.agent.tools.order_adapter import OrderAdapter

# "查无结果"类关键词，出现时标记为 no_trace
_NO_RESULT_KEYWORDS = ("查无结果", "暂无", "无轨迹", "暂无物流", "查询失败", "无此单号")


def _query_kuaidi100(tracking_no: str) -> dict | None:
    """查询快递100，返回标准化物流轨迹或 None"""
    tracking = query_tracking(tracking_no)
    valid_states = {"0", "1", "2", "3", "4", "5", "6"}
    state_code = str(tracking.get("state", ""))
    events = tracking.get("data", [])
    has_error = tracking.get("error")

    elapsed_ms = tracking.get("elapsed_ms", 0)
    cache_hit = tracking.get("cache_hit", False)
    timed_out = tracking.get("timeout", False)

    # 超时或 API 错误
    if timed_out:
        return {
            "status": "api_failed",
            "carrier": "",
            "tracking_no": tracking_no,
            "is_delivered": False,
            "confirmed_delivered": False,
            "state": "",
            "events": [],
            "latest": {},
            "low_confidence": True,
            "elapsed_ms": elapsed_ms,
            "cache_hit": cache_hit,
            "timeout": True,
        }

    if has_error or state_code not in valid_states or not events:
        return None

    courier = tracking.get("courier_name") or tracking.get("courier", "")
    is_delivered = state_code == "3"

    # 低可信度判断
    low_confidence = False
    latest_ctx = events[0].get("context", "") if events else ""

    # "查无结果"类关键词 → 直接标记为 no_trace，不是有效签收
    if is_delivered and any(kw in latest_ctx for kw in _NO_RESULT_KEYWORDS):
        return {
            "status": "no_trace",
            "carrier": courier,
            "tracking_no": tracking.get("tracking_no", tracking_no),
            "is_delivered": False,
            "confirmed_delivered": False,
            "state": state_code,
            "events": events,
            "latest": events[0] if events else {},
            "low_confidence": True,
            "elapsed_ms": elapsed_ms,
            "cache_hit": cache_hit,
            "timeout": False,
        }

    if is_delivered:
        if len(events) < 2:
            low_confidence = True
        if not latest_ctx.strip():
            low_confidence = True
        if len(events) == 1:
            ctx_lower = latest_ctx.lower()
            if not any(kw in ctx_lower for kw in ("签收", "代收", "本人", "门卫", "快递柜", "驿站", "丰巢", "代签")):
                low_confidence = True

    status_map = {
        "0": "in_transit",
        "1": "picked_up",
        "2": "stalled",
        "3": "delivered",
        "4": "returned",
        "5": "out_for_delivery",
        "6": "returned",
    }

    internal_status = status_map.get(state_code, "in_transit")
    if low_confidence and internal_status == "delivered":
        internal_status = "uncertain"

    return {
        "status": internal_status,
        "carrier": courier,
        "tracking_no": tracking.get("tracking_no", tracking_no),
        "is_delivered": is_delivered and not low_confidence,
        "confirmed_delivered": is_delivered and not low_confidence,
        "state": state_code,
        "events": events,
        "latest": events[0] if events else {},
        "low_confidence": low_confidence,
        "elapsed_ms": elapsed_ms,
        "cache_hit": cache_hit,
        "timeout": False,
    }


def query_by_tracking_no(state: dict) -> dict:
    """根据物流单号查询快递100"""
    t0 = time.time()
    slots = state.get("slots", {})
    tracking_no = slots.get("tracking_no", "")

    if not tracking_no:
        trace = {
            "node": "query_by_tracking_no",
            "step": "tracking_query",
            "status": "skipped",
            "summary": "无物流单号，跳过查询",
            "duration_ms": 0,
        }
        return {"trace_steps": state.get("trace_steps", []) + [trace]}

    trace_base = {
        "node": "query_by_tracking_no",
        "step": "tracking_query",
        "source": "kuaidi100",
    }

    logistics_trace = _query_kuaidi100(tracking_no)
    duration_ms = int((time.time() - t0) * 1000)

    if logistics_trace:
        latest = logistics_trace["latest"]
        lc_tag = " [信息较少,需核实]" if logistics_trace.get("low_confidence") else ""
        cache_tag = " (cached)" if logistics_trace.get("cache_hit") else ""
        trace = {
            **trace_base,
            "status": "success",
            "duration_ms": logistics_trace.get("elapsed_ms", duration_ms),
            "cache_hit": logistics_trace.get("cache_hit", False),
            "summary": f"快递100查询 {logistics_trace['carrier']}, 状态 {logistics_trace['state']}{lc_tag}{cache_tag}, 最新 {latest.get('time','')} {latest.get('context','')}",
        }
        result = {
            "logistics_trace": logistics_trace,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }
        # 同时用快递单号反查本地订单，补充商品信息
        adapter = OrderAdapter()
        try:
            from app.main import get_order_repo
            adapter = OrderAdapter(local_order_repo=get_order_repo())
        except Exception:
            pass
        local_result = adapter.query_local(tracking_no)
        if local_result and local_result.get("order"):
            order = local_result["order"]
            result["order"] = order
            result["logistics"] = local_result.get("logistics", [])
            result["order_found"] = True
            result["order_source"] = "local"
            result["trace_steps"].append({
                "node": "query_by_tracking_no",
                "step": "order_reverse_lookup",
                "status": "success",
                "source": "local_order",
                "summary": f"通过物流单号反查本地订单成功: {order.get('o_id', '')}",
                "duration_ms": int((time.time() - t0) * 1000) - duration_ms,
            })
        return result
    else:
        # 快递100 查不到，尝试本地反查
        adapter = OrderAdapter()
        try:
            from app.main import get_order_repo
            adapter = OrderAdapter(local_order_repo=get_order_repo())
        except Exception:
            pass

        local_result = adapter.query_local(tracking_no)
        if local_result and local_result.get("order"):
            order = local_result["order"]
            trace = {
                **trace_base,
                "status": "success",
                "source": "local_order",
                "duration_ms": duration_ms,
                "summary": f"通过物流单号反查本地订单成功: {order.get('o_id', '')}",
            }
            return {
                "order": order,
                "logistics": local_result.get("logistics", []),
                "order_found": True,
                "order_source": "local",
                "trace_steps": state.get("trace_steps", []) + [trace],
            }

        trace = {
            **trace_base,
            "status": "skipped",
            "duration_ms": duration_ms,
            "summary": f"快递100未查到 {tracking_no}",
        }
        return {
            "trace_steps": state.get("trace_steps", []) + [trace],
        }
