"""
订单查询工具适配器 - 聚水潭 + 本地订单
不直接写死 API 逻辑，通过现有仓库/服务调用。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 聚水潭查询超时（秒）
_JST_TIMEOUT_SECONDS = 5


class OrderAdapter:
    """订单查询适配器"""

    def __init__(self, live_query_service=None, local_order_repo=None):
        self._live_query_service = live_query_service
        self._local_order_repo = local_order_repo

    def query_jst(self, order_id: str, timeout: float = _JST_TIMEOUT_SECONDS, max_total_seconds: float = 10.0) -> Optional[dict]:
        """
        查询聚水潭实时订单。
        返回 {"order": dict, "logistics": list, "refunds": list, "summary": dict}
        或 None。

        timeout: 单次 API 调用超时（秒），默认 5 秒。
        max_total_seconds: _find_order 整体最大耗时（秒），默认 10 秒。
        """
        if not order_id:
            return None
        if self._live_query_service is None:
            return None
        try:
            result = self._live_query_service.query_order_status(
                order_id, timeout=timeout, max_total_seconds=max_total_seconds,
            )
            if result and result.get("order"):
                return result
        except TimeoutError:
            logger.warning("聚水潭订单查询超时(order=%s, timeout=%ss)", order_id, timeout)
        except ConnectionError as e:
            logger.warning("聚水潭连接失败(order=%s): %s", order_id, e)
        except ValueError as e:
            logger.warning("聚水潭返回数据解析失败(order=%s): %s", order_id, e)
        except Exception as e:
            logger.warning("聚水潭订单查询失败(order=%s): %s", order_id, e)
        return None

    def query_local(self, order_id: str) -> Optional[dict]:
        """查询本地预加载订单。支持订单号和快递单号反查。"""
        if not order_id or self._local_order_repo is None:
            return None
        order = self._local_order_repo.get_order(order_id)
        if not order and hasattr(self._local_order_repo, 'get_order_by_tracking_no'):
            order = self._local_order_repo.get_order_by_tracking_no(order_id)
        if order:
            oid = order.get("o_id", order_id)
            logistics = self._local_order_repo.get_logistics(oid)
            return {
                "order": order,
                "logistics": logistics,
                "refunds": self._local_order_repo.get_refunds(oid),
                "summary": {},
            }
        return None

    def get_logistics(self, order_id: str) -> list:
        """获取本地物流信息"""
        if self._local_order_repo is None:
            return []
        return self._local_order_repo.get_logistics(order_id)
