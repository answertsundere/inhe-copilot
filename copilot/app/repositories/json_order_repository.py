"""
JSON 文件订单仓库 - 优先读取外部真实数据，无则回退样例数据
"""

import json
import logging
import os
from typing import Optional

from .base import OrderRepositoryBase
from app.config import SAMPLE_DATA_DIR, EXTERNAL_DATA_DIR

logger = logging.getLogger(__name__)


class JsonOrderRepository(OrderRepositoryBase):
    """从 JSON 文件加载的订单仓库"""

    def __init__(self):
        self.orders = {}
        self.logistics = {}
        self.refunds = {}
        self.aftersale = {}
        self._loaded = False

    def load(self):
        """加载订单相关数据，优先外部真实数据"""
        data_dir = EXTERNAL_DATA_DIR or SAMPLE_DATA_DIR
        using_external = bool(EXTERNAL_DATA_DIR) and os.path.isdir(EXTERNAL_DATA_DIR)
        source = "外部数据" if using_external else "样例数据"
        logger.info("订单仓库数据来源: %s (%s)", source, data_dir)

        # 加载订单
        orders = self._load_json(data_dir, "orders.json")
        if not orders:
            orders = self._load_json(SAMPLE_DATA_DIR, "sample_orders.json")
        for o in orders:
            oid = str(o.get("o_id", ""))
            if oid:
                self.orders[oid] = o
        logger.info("  订单: %d 条", len(self.orders))

        # 加载物流
        logistics = self._load_json(data_dir, "logistics.json")
        if not logistics:
            logistics = self._load_json(SAMPLE_DATA_DIR, "sample_logistics.json")
        for l in logistics:
            oid = str(l.get("o_id", ""))
            if oid:
                self.logistics.setdefault(oid, []).append(l)
        logger.info("  物流: %d 条", sum(len(v) for v in self.logistics.values()))

        # 加载退款
        refunds = self._load_json(data_dir, "refunds.json")
        if not refunds:
            refunds = self._load_json(SAMPLE_DATA_DIR, "sample_refunds.json")
        for r in refunds:
            oid = str(r.get("o_id", ""))
            if oid:
                self.refunds.setdefault(oid, []).append(r)
        logger.info("  退款: %d 条", sum(len(v) for v in self.refunds.values()))

        # 加载售后
        aftersale = self._load_json(data_dir, "aftersale_received.json")
        if aftersale:
            for a in aftersale:
                oid = str(a.get("o_id", ""))
                if oid:
                    self.aftersale.setdefault(oid, []).append(a)
            logger.info("  售后: %d 条", sum(len(v) for v in self.aftersale.values()))

        self._loaded = True

    def _load_json(self, directory: str, filename: str) -> list:
        """加载 JSON 文件"""
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取 %s 失败: %s", path, e)
            return []

    def get_order(self, order_id: str) -> Optional[dict]:
        """查询订单"""
        return self.orders.get(str(order_id))

    def get_order_by_tracking_no(self, tracking_no: str) -> Optional[dict]:
        """通过快递单号反查订单"""
        tn = str(tracking_no).upper().strip()
        for order in self.orders.values():
            if str(order.get("l_id", "")).upper().strip() == tn:
                return order
        return None

    def get_logistics(self, order_id: str) -> list:
        """查询物流"""
        return self.logistics.get(str(order_id), [])

    def get_refunds(self, order_id: str) -> list:
        """查询退款"""
        return self.refunds.get(str(order_id), [])

    def get_aftersale(self, order_id: str) -> list:
        """查询售后"""
        return self.aftersale.get(str(order_id), [])

    def search_orders_by_status(self, status: str, limit: int = 20) -> list:
        """按状态搜索订单"""
        results = []
        for oid, order in self.orders.items():
            if order.get("status") == status or order.get("shop_status") == status:
                results.append(order)
                if len(results) >= limit:
                    break
        return results

    def count_orders(self) -> int:
        return len(self.orders)

    def count_logistics(self) -> int:
        return sum(len(v) for v in self.logistics.values())

    def count_refunds(self) -> int:
        return sum(len(v) for v in self.refunds.values())

    def count_aftersale(self) -> int:
        return sum(len(v) for v in self.aftersale.values())
