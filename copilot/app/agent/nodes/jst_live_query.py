"""
jst_live_query 节点 — 统一的聚水潭实时查询入口
替代旧的 query_jst_order + query_local_order_fallback + query_logistics_trace

支持 identifier_type:
  internal_order_id → lookup by o_ids
  platform_trade_id → lookup by outbound_so_id (orders/out/simple/query)
  platform_order_id → lookup by so_ids
  tracking_no       → logistic/query scan
  unknown_identifier → multi-path attempt
"""

import logging
import time

from app.integrations.jst.live_query import lookup_order_by_identifier

logger = logging.getLogger(__name__)

# 销售出库状态映射
_OUTBOUND_STATUS_MAP = {
    "Confirmed": "shipped",      # 已确认/已发货
    "WaitConfirm": "pending_shipment",  # 待确认
    "Cancelled": "canceled",     # 已取消
    "Sent": "shipped",           # 已发出
    "Delivered": "delivered",    # 已送达
}


def jst_live_query(state: dict) -> dict:
    """根据 identifier_type 调用对应的 JST 实时查询。
    查询前先写入即时回复，避免用户等太久没有反馈。
    """
    t0 = time.time()
    try:
        from app.agent.tools.executor import get_replay_tool_control
        replay_tool_control = get_replay_tool_control(state)
    except Exception:
        replay_tool_control = {"disable_external_tools": False, "external_tool_timeout_seconds": 0.0}
    if replay_tool_control.get("disable_external_tools"):
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "jst_live_query",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "provider": "jst",
            "error_code": "external_tools_disabled_for_replay",
            "requires_human_review": True,
            "summary": "JST live query skipped by eval replay external tool control",
        }
        return {
            "order_found": False,
            "requires_human_review": True,
            "reason_for_review": "external_tool_unavailable_for_replay",
            "jst_fallback_reason": "external_tools_disabled_for_replay",
            "external_tool_control": replay_tool_control,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }
    slots = state.get("slots", {})

    identifier = ""
    identifier_type = slots.get("identifier_type", "")

    if identifier_type == "internal_order_id":
        identifier = state.get("order_id", "") or slots.get("order_id", "")
    elif identifier_type == "platform_trade_id":
        identifier = slots.get("platform_trade_id", "")
    elif identifier_type == "platform_order_id":
        identifier = slots.get("platform_order_id", "") or slots.get("order_id", "")
    elif identifier_type == "tracking_no":
        identifier = slots.get("tracking_no", "")
    elif identifier_type == "unknown_identifier":
        identifier = slots.get("possible_numeric_id", "")
    elif identifier_type == "order_id":
        # 兼容旧 identifier_type
        identifier = state.get("order_id", "") or slots.get("order_id", "")
        identifier_type = "internal_order_id"

    if not identifier:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "jst_live_query",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "无标识符，跳过聚水潭查询",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 写入即时回复，让用户知道正在查询
    progress_trace = {
        "node": "jst_live_query",
        "status": "querying",
        "duration_ms": 0,
        "cache_hit": False,
        "summary": f"正在查询 {identifier} (type={identifier_type}) ...",
    }

    # ``shop_id`` is the platform-neutral store reference used by the control
    # plane. Only an explicit provider-scoped id may filter JST records.
    jst_shop_id = str(
        (state.get("copilot_context", {}) or {}).get("jst_shop_id") or ""
    ).strip()
    shop_platform = str(
        (state.get("copilot_context", {}) or {}).get("shop_platform") or ""
    ).strip().lower()
    lookup_kwargs = {}
    if jst_shop_id:
        lookup_kwargs["shop_id"] = jst_shop_id
    if shop_platform:
        lookup_kwargs["shop_platform"] = shop_platform
    result = lookup_order_by_identifier(identifier, identifier_type, **lookup_kwargs)
    duration_ms = int((time.time() - t0) * 1000)

    # 所有 trace 都包含 progress + result
    steps = state.get("trace_steps", []) + [progress_trace]

    if result["found"]:
        data = result["data"]
        # 从订单数据直接提取物流信息（不需要二次查 logistic/query）
        logistics_trace = _build_logistics_trace(data)

        # 提取 used_fact_tool 和 used_endpoint
        used_endpoint = result.get("endpoint", "")
        used_query_type = result.get("query_type", "")

        trace = {
            "node": "jst_live_query",
            "status": "success",
            "duration_ms": result.get("duration_ms", duration_ms),
            "cache_hit": False,
            "jst_endpoint": used_endpoint,
            "jst_query_type": used_query_type,
            "jst_attempted_paths": result.get("attempted_paths", []),
            "identifier_type": identifier_type,
            "provider": "jst",
            "summary": f"聚水潭查到订单 {data.get('o_id', identifier)} via {used_endpoint}",
        }
        return {
            "live_order": data,
            "order_found": True,
            "order_source": "jst_live",
            "order_status": _map_status(data.get("status", "")),
            "logistics_trace": logistics_trace,
            "used_fact_tool": "jst_live_query",
            "used_endpoint": used_endpoint,
            "used_identifier_type": identifier_type,
            "trace_steps": steps + [trace],
        }

    # 查不到 / 不支持 / 超时
    reason = result.get("safe_fallback_reason", "unknown")
    trace = {
        "node": "jst_live_query",
        "status": "not_found" if reason == "not_found" else reason,
        "duration_ms": result.get("duration_ms", duration_ms),
        "cache_hit": False,
        "jst_endpoint": result.get("endpoint", ""),
        "jst_query_type": result.get("query_type", ""),
        "jst_attempted_paths": result.get("attempted_paths", []),
        "jst_error_code": result.get("error_code"),
        "identifier_type": identifier_type,
        "provider": "jst",
        "summary": f"聚水潭未查到: {reason}",
    }
    return {
        "order_found": False,
        "jst_fallback_reason": reason,
        "used_fact_tool": "jst_live_query",
        "used_identifier_type": identifier_type,
        "trace_steps": steps + [trace],
    }


def _build_logistics_trace(order: dict) -> dict:
    """从订单数据直接构建 logistics_trace（不需要二次 API 调用）"""
    carrier = order.get("logistics_company", "")
    tracking_no = order.get("l_id", "")
    send_date = order.get("send_date", "")
    sign_time = order.get("sign_time", "")
    status = order.get("status", "")

    if not carrier and not tracking_no and not send_date:
        return {
            "status": "no_trace",
            "carrier": "",
            "tracking_no": "",
            "source": "jst_order",
            "is_delivered": False,
        }

    is_delivered = sign_time != "" and sign_time is not None
    trace_status = "delivered" if is_delivered else "shipped" if send_date else "pending"

    latest = {}
    if send_date:
        latest = {"time": send_date, "context": "包裹已发出"}

    return {
        "status": trace_status,
        "carrier": carrier,
        "tracking_no": tracking_no,
        "send_date": send_date,
        "sign_time": sign_time,
        "latest": latest,
        "order_status": status,
        "source": "jst_order",
        "is_delivered": is_delivered,
        "logistics_company": carrier,
    }


def _map_status(jst_status: str) -> str:
    """聚水潭订单状态映射（含销售出库状态）"""
    mapping = {
        "WaitSellerSend": "pending_shipment",
        "SellerSent": "shipped",
        "Confirmed": "shipped",
        "Signed": "signed",
        "Cancelled": "canceled",
        "Delete": "canceled",
        "Refund": "refunded",
        "Aftersale": "aftersales",
        "Unpaid": "unpaid",
        "TradeFinished": "finished",
        # 销售出库状态
        "WaitConfirm": "pending_shipment",
        "Sent": "shipped",
        "Delivered": "delivered",
    }
    return mapping.get(jst_status, jst_status.lower() if jst_status else "")
