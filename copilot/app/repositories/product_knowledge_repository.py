"""
产品知识卡仓库 - 从 product_cards.json 读取产品知识
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class ProductKnowledgeRepository:
    """产品知识卡仓库 - 从 JSON 文件读取"""

    def __init__(self, knowledge_dir: str = ""):
        self._cards = []           # List[dict]
        self._by_i_id = {}         # i_id -> card
        self._by_sku_id = {}       # sku_id -> card (第一个匹配)
        self._loaded = False
        self._knowledge_dir = knowledge_dir

    def load(self):
        """加载 product_cards.json"""
        knowledge_dir = self._knowledge_dir
        path = os.path.join(knowledge_dir, "product_cards.json")

        if not os.path.exists(path):
            # 尝试 product_knowledge 目录
            parent = os.path.dirname(os.path.dirname(knowledge_dir))
            alt_path = os.path.join(parent, "product_knowledge", "product_cards.json")
            if os.path.exists(alt_path):
                path = alt_path
            else:
                logger.info("产品知识卡文件不存在: %s (降级为空)", path)
                self._loaded = True
                return

        try:
            with open(path, "r", encoding="utf-8") as f:
                self._cards = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取产品知识卡失败: %s", e)
            self._loaded = True
            return

        # 建立索引
        for card in self._cards:
            iid = card.get("i_id")
            if iid:
                self._by_i_id[str(iid)] = card
            # SKU 索引
            for sku in card.get("sku_summary", {}).get("sku_list", []):
                sid = sku.get("sku_id")
                if sid and str(sid) not in self._by_sku_id:
                    self._by_sku_id[str(sid)] = card

        self._loaded = True
        logger.info("产品知识卡: %d 张, i_id 索引 %d, sku_id 索引 %d",
                     len(self._cards), len(self._by_i_id), len(self._by_sku_id))

    def count(self) -> int:
        """返回知识卡数量"""
        return len(self._cards)

    def get_by_i_id(self, i_id: str) -> Optional[dict]:
        """按款号查询"""
        return self._by_i_id.get(str(i_id))

    def get_by_sku_id(self, sku_id: str) -> Optional[dict]:
        """按 SKU 查询"""
        return self._by_sku_id.get(str(sku_id))

    def search(self, query: str, limit: int = 5) -> list:
        """
        关键词搜索产品知识卡。
        匹配商品名称、类目、品牌、SKU 名称。
        双向子串匹配：query 包含 name 或 name 包含 query。
        """
        if not query or not self._cards:
            return []

        query_lower = query.lower()
        scored = []

        for card in self._cards:
            score = 0
            name = (card.get("product_name") or "").lower()
            category = (card.get("category") or "").lower()
            brand = (card.get("brand") or "").lower()

            # 双向子串匹配
            if query_lower in name or name in query_lower:
                score += 10
            if query_lower in category or category in query_lower:
                score += 5
            if query_lower in brand or brand in query_lower:
                score += 3
            # SKU 名称匹配
            for sku in card.get("sku_summary", {}).get("sku_list", []):
                sku_name = (sku.get("sku_name") or "").lower()
                sku_props = (sku.get("properties_value") or "").lower()
                if query_lower in sku_name or sku_name in query_lower:
                    score += 4
                    break
                if query_lower in sku_props or sku_props in query_lower:
                    score += 2
                    break

            if score > 0:
                scored.append((score, card))

        scored.sort(key=lambda x: -x[0])
        return [card for _, card in scored[:limit]]

    def get_summary(self, card: dict) -> dict:
        """
        提取知识卡的摘要字段（用于 prompt 注入，避免过长）。
        """
        cs = card.get("customer_service_facts", {})
        sku_list = card.get("sku_summary", {}).get("sku_list", [])

        return {
            "i_id": card.get("i_id"),
            "name": card.get("product_name"),
            "category": card.get("category"),
            "brand": card.get("brand"),
            "status": card.get("product_status"),
            "sku_count": card.get("sku_summary", {}).get("sku_count", 0),
            "price_range": _extract_price_range(sku_list),
            "material": cs.get("material"),
            "weight": cs.get("weight"),
            "color": cs.get("color"),
            "size": cs.get("size"),
            "stock_available": _has_stock(sku_list),
            "selling_points": cs.get("selling_points"),
            "after_sales_notes": cs.get("after_sales_notes"),
            "completeness_score": card.get("completeness_score"),
            "agent_level": card.get("agent_usable_level"),
        }


def _extract_price_range(sku_list: list) -> Optional[str]:
    """提取价格区间"""
    prices = [s["sale_price"] for s in sku_list if s.get("sale_price")]
    if not prices:
        return None
    if len(prices) == 1:
        return f"¥{prices[0]}"
    return f"¥{min(prices)}~¥{max(prices)}"


def _has_stock(sku_list: list) -> bool:
    """是否有库存"""
    return any(s.get("stock_qty") is not None and s["stock_qty"] > 0 for s in sku_list)
