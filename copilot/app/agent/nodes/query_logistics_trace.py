"""
query_logistics_trace 节点 - 查询物流轨迹
从聚水潭获取订单的物流信息（快递公司、快递单号、发货时间等）
不再依赖快递100，全部走聚水潭 API
"""

import time
import logging

logger = logging.getLogger(__name__)


def _query_jst_logistics(order_id: str) -> dict | None:
    """通过聚水潭查询订单物流信息"""
    try:
        from app.main import get_live_query_service
        service = get_live_query_service()
        result = service.query_order_status(order_id, timeout=3.0, max_total_seconds=5.0)
        if result and result.get("order"):
            order = result["order"]
            logistics = result.get("logistics", [])
            summary = result.get("summary", {})

            l_id = order.get("l_id", "")
            logistics_company = order.get("logistics_company", "")
            send_date = order.get("shipping_time", "") or order.get("send_date", "")
            status = order.get("status", "")

            # 判断物流状态
            is_delivered = status in ("已签收", "已完成", "success", "delivered")
            is_shipped = bool(l_id and logistics_company) or status in ("已发货", "发货中", "shipped")

            # 从 logistics 记录补充信息
            if logistics and isinstance(logistics, list) and logistics[0]:
                first = logistics[0]
                if not l_id:
                    l_id = first.get("l_id", "")
                if not logistics_company:
                    logistics_company = first.get("logistics_company", "")
                if not send_date:
                    send_date = first.get("send_date", "")

            return {
                "status": "delivered" if is_delivered else ("shipped" if is_shipped else "no_trace"),
                "carrier": logistics_company,
                "tracking_no": l_id,
                "is_delivered": is_delivered,
                "confirmed_delivered": is_delivered,
                "send_date": send_date,
                "logistics_company": logistics_company,
                "order_status": status,
                "source": "jst",
            }
    except Exception as e:
        logger.warning("聚水潭物流查询失败(order=%s): %s", order_id, e)
    return None


def _query_local_logistics(order_id: str) -> dict | None:
    """通过本地仓库查询物流信息"""
    try:
        from app.main import get_order_repo
        repo = get_order_repo()
        order = repo.get_order(order_id)
        if not order:
            # 尝试按快递单号反查
            if hasattr(repo, 'get_order_by_tracking_no'):
                order = repo.get_order_by_tracking_no(order_id)
        if order:
            l_id = order.get("l_id", "")
            logistics_company = order.get("logistics_company", "")
            status = order.get("status", "")
            is_delivered = status in ("已签收", "已完成")
            is_shipped = bool(l_id) or status in ("已发货", "发货中")

            logistics = []
            if hasattr(repo, 'get_logistics'):
                logistics = repo.get_logistics(order.get("o_id", order_id))

            return {
                "status": "delivered" if is_delivered else ("shipped" if is_shipped else "no_trace"),
                "carrier": logistics_company,
                "tracking_no": l_id,
                "is_delivered": is_delivered,
                "confirmed_delivered": is_delivered,
                "send_date": "",
                "logistics_company": logistics_company,
                "order_status": status,
                "source": "local",
            }
    except Exception:
        pass
    return None


def query_logistics_trace(state: dict) -> dict:
    """查询物流轨迹（聚水潭优先，本地兜底）"""
    t0 = time.time()

    # 已有物流轨迹则跳过
    existing = state.get("logistics_trace")
    if existing and existing.get("status", "") not in ("no_trace", "api_failed", ""):
        duration_ms = int((time.time() - t0) * 1000)
        return {"trace_steps": state.get("trace_steps", []) + [{
            "node": "query_logistics_trace",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": True,
            "summary": "已有物流轨迹，跳过查询",
        }]}

    # 确定查询参数
    order = state.get("live_order") or state.get("order")
    order_id = ""
    tracking_no = ""

    if order:
        order_id = str(order.get("o_id", ""))
        tracking_no = order.get("l_id", "")

    if not order_id:
        order_id = state.get("order_id", "")

    if not order_id:
        slots = state.get("slots", {})
        order_id = slots.get("order_id", "")
        if not tracking_no:
            tracking_no = slots.get("tracking_no", "")

    # 先用 tracking_no 或 order_id 查聚水潭
    query_param = order_id or tracking_no
    logistics_trace = None

    if query_param:
        logistics_trace = _query_jst_logistics(query_param)

    # 聚水潭没查到或未配置，走本地
    source = "jst"
    if not logistics_trace:
        logistics_trace = _query_local_logistics(query_param)
        source = "local"

    duration_ms = int((time.time() - t0) * 1000)

    if logistics_trace:
        trace = {
            "node": "query_logistics_trace",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"{source}物流查询: {logistics_trace.get('carrier', '') or '无快递公司'}, "
                       f"单号 {logistics_trace.get('tracking_no', '') or '无'}, "
                       f"状态 {logistics_trace.get('order_status', '') or logistics_trace.get('status', '')}",
        }
        return {
            "logistics_trace": logistics_trace,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    trace = {
        "node": "query_logistics_trace",
        "status": "skipped",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"未查到物流信息 (param={query_param or '无'})",
    }
    return {
        "logistics_trace": {
            "status": "no_trace",
            "carrier": "",
            "tracking_no": tracking_no or "",
            "is_delivered": False,
            "confirmed_delivered": False,
            "send_date": "",
            "logistics_company": "",
            "source": source,
        },
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
