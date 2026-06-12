"""
query_jst_order 节点 - 查询聚水潭实时订单
支持按 order_id 查询，也支持按 tracking_no 反查（聚水潭内部会走 l_id 反查路径）
优化：timeout 3-5 秒，失败后进入 query_local_order_fallback
"""

import logging
import time
import os
from app.agent.tools.order_adapter import OrderAdapter

logger = logging.getLogger(__name__)

_JST_TIMEOUT = 3.0
_JST_MAX_TOTAL = 5.0  # _find_order 整体最大耗时（快速响应优先）


def _is_jst_configured() -> bool:
    """检查聚水潭 API 是否已配置"""
    return bool(
        os.environ.get("JUSHUITAN_APP_KEY", "")
        and os.environ.get("JUSHUITAN_APP_SECRET", "")
        and os.environ.get("JUSHUITAN_ACCESS_TOKEN", "")
    )


def query_jst_order(state: dict) -> dict:
    """优先查聚水潭订单。tracking_no 不做同步多页反查（太慢），走快速 o_ids/so_ids 直查。"""
    t0 = time.time()
    slots = state.get("slots", {})
    order_id = state.get("order_id", "")
    tracking_no = slots.get("tracking_no", "")
    identifier_type = slots.get("identifier_type", "")

    if not order_id:
        order_id = slots.get("possible_numeric_id", "")

    # tracking_no 不做同步反查：只走快速 o_ids/so_ids 路径
    # 如果要反查，应由后台异步任务完成
    is_tracking_lookup = False
    if not order_id and tracking_no:
        is_tracking_lookup = True
        order_id = tracking_no  # 尝试快速直查，但限制 max_total_seconds

    # 如果已有订单数据（如反查到），跳过
    if state.get("order_found"):
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "query_jst_order",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "已有订单数据，跳过聚水潭查询",
        }
        return {"trace_steps": state.get("trace_steps", []) + [trace]}

    # 没有任何查询参数
    if not order_id:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "query_jst_order",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "无订单号或快递单号，跳过聚水潭查询",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 聚水潭未配置时静默跳过
    if not _is_jst_configured():
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "query_jst_order",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "聚水潭 API 未配置，跳过实时查询",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    adapter = OrderAdapter()
    try:
        from app.main import get_live_query_service
        adapter = OrderAdapter(live_query_service=get_live_query_service())
    except Exception:
        pass

    try:
        # tracking_no 只允许快速直查（2s），不做多页反查
        effective_timeout = _JST_TIMEOUT
        effective_max = _JST_MAX_TOTAL
        if is_tracking_lookup:
            effective_timeout = 2.0
            effective_max = 2.0
        result = adapter.query_jst(order_id, timeout=effective_timeout, max_total_seconds=effective_max)
        duration_ms = int((time.time() - t0) * 1000)

        if result:
            trace = {
                "node": "query_jst_order",
                "status": "success",
                "duration_ms": duration_ms,
                "cache_hit": False,
                "summary": f"聚水潭查到订单 {order_id}",
            }
            return {
                "live_order": result.get("order"),
                "live_logistics": result.get("logistics", []),
                "order_found": True,
                "order_source": "jst",
                "trace_steps": state.get("trace_steps", []) + [trace],
            }

        trace = {
            "node": "query_jst_order",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"聚水潭未找到订单 {order_id}",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    except TimeoutError:
        duration_ms = int((time.time() - t0) * 1000)
        logger.warning("聚水潭查询超时(order=%s, timeout=%ss)", order_id, _JST_TIMEOUT)
        trace = {
            "node": "query_jst_order",
            "status": "jst_timeout",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"聚水潭查询超时 {order_id} ({_JST_TIMEOUT}s)",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        logger.warning("聚水潭查询失败(order=%s): %s", order_id, e)
        trace = {
            "node": "query_jst_order",
            "status": "jst_failed",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"聚水潭查询失败 {order_id}: {e}",
        }
        return {
            "order_found": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }
