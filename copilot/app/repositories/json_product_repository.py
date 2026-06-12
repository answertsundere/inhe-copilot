"""
JSON 文件商品仓库 - 优先读取外部真实数据，无则回退样例数据
"""

import json
import logging
import os
from typing import Optional

from .base import ProductRepositoryBase
from app.config import SAMPLE_DATA_DIR, EXTERNAL_DATA_DIR

logger = logging.getLogger(__name__)


class JsonProductRepository(ProductRepositoryBase):
    """从 JSON 文件加载的商品仓库"""

    def __init__(self):
        self.skus = {}
        self.products = {}  # i_id -> product dict with skus
        self.inventory = {}  # sku_id -> [inventory]
        self._loaded = False

    def load(self):
        """加载商品数据，优先外部真实数据"""
        data_dir = EXTERNAL_DATA_DIR or SAMPLE_DATA_DIR
        using_external = bool(EXTERNAL_DATA_DIR) and os.path.isdir(EXTERNAL_DATA_DIR)
        source = "外部数据" if using_external else "样例数据"
        logger.info("商品仓库数据来源: %s (%s)", source, data_dir)

        # 尝试加载外部数据
        skus_data = self._load_json(data_dir, "skus.json")
        items_data = self._load_json(data_dir, "items.json")

        if not skus_data and not items_data:
            # 外部数据不存在，使用样例数据
            products_data = self._load_json(SAMPLE_DATA_DIR, "sample_products.json")
            self._load_from_products(products_data)
        else:
            # 从外部 skus.json 加载
            for s in skus_data:
                sid = str(s.get("sku_id", ""))
                if sid:
                    self.skus[sid] = s
            # 从外部 items.json 构建商品
            for item in items_data:
                iid = str(item.get("i_id", ""))
                if iid:
                    related = [s for s in skus_data if s.get("i_id") == iid]
                    self.products[iid] = {
                        "i_id": item.get("i_id"),
                        "name": item.get("name"),
                        "brand": item.get("brand"),
                        "category": item.get("c_name"),
                        "skus": related,
                    }

        # 加载库存（外部数据才有）
        inv_data = self._load_json(data_dir, "inventory.json")
        if inv_data:
            for inv in inv_data:
                sid = str(inv.get("sku_id", ""))
                if sid:
                    self.inventory.setdefault(sid, []).append(inv)
            logger.info("  库存: %d 条", sum(len(v) for v in self.inventory.values()))

        logger.info("  SKU: %d 条, 商品: %d 款", len(self.skus), len(self.products))
        self._loaded = True

    def _load_from_products(self, products_data: list):
        """从合并的 products JSON 加载（样例数据格式）"""
        for p in products_data:
            iid = str(p.get("i_id", ""))
            skus_list = p.get("skus", [])
            for s in skus_list:
                sid = str(s.get("sku_id", ""))
                if sid:
                    self.skus[sid] = s
            if iid:
                self.products[iid] = p

    def _load_json(self, directory: str, filename: str) -> list:
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

    def get_sku(self, sku_id: str) -> Optional[dict]:
        return self.skus.get(str(sku_id))

    def get_product(self, i_id: str) -> Optional[dict]:
        return self.products.get(str(i_id))

    def get_inventory(self, sku_id: str) -> list:
        """查询 SKU 库存"""
        return self.inventory.get(str(sku_id), [])

    def search_skus_by_name(self, keyword: str, limit: int = 20) -> list:
        """按名称搜索 SKU"""
        results = []
        for sid, sku in self.skus.items():
            if keyword.lower() in (sku.get("name", "") or "").lower():
                results.append(sku)
                if len(results) >= limit:
                    break
        return results

    def count_skus(self) -> int:
        return len(self.skus)

    def count_products(self) -> int:
        return len(self.products)
