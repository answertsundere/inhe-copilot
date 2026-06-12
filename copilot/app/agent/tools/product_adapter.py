"""
商品知识查询工具适配器
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProductAdapter:
    """商品知识查询适配器"""

    def __init__(self, product_repo=None, product_knowledge_repo=None):
        self._product_repo = product_repo
        self._product_knowledge_repo = product_knowledge_repo

    def get_by_sku(self, sku_id: str) -> Optional[dict]:
        if self._product_repo is None:
            return None
        return self._product_repo.get_sku(sku_id)

    def get_by_i_id(self, i_id: str) -> Optional[dict]:
        if self._product_repo is None:
            return None
        return self._product_repo.get_product(i_id)

    def search_by_name(self, keyword: str, limit: int = 5) -> list:
        if self._product_repo is None:
            return []
        return self._product_repo.search_skus_by_name(keyword, limit)

    def search_product_knowledge(self, message: str, context_products: list = None, limit: int = 3) -> list:
        """从产品知识库搜索"""
        if self._product_knowledge_repo is None:
            return []
        results = []
        # 1. 通过上下文中的 SKU/i_id 匹配
        if context_products:
            for product in context_products:
                sku_id = product.get("sku_id")
                i_id = product.get("i_id")
                card = None
                if i_id:
                    card = self._product_knowledge_repo.get_by_i_id(i_id)
                if not card and sku_id:
                    card = self._product_knowledge_repo.get_by_sku_id(sku_id)
                if card:
                    summary = self._product_knowledge_repo.get_summary(card)
                    if summary:
                        results.append(summary)
        # 2. 关键词搜索补充
        if len(results) < limit:
            searched = self._product_knowledge_repo.search(message, limit=limit)
            existing = {r.get("i_id") for r in results}
            for card in searched:
                if card.get("i_id") not in existing:
                    summary = self._product_knowledge_repo.get_summary(card)
                    if summary:
                        results.append(summary)
        return results[:limit]

    def match_product_from_message(self, message: str) -> Optional[str]:
        """从消息中匹配商品名关键词"""
        keywords = ["书桌", "书架", "餐椅", "椅子", "置物架", "桌子", "床", "沙发", "柜子", "茶几"]
        for kw in keywords:
            if kw in message:
                return kw
        # 尝试从商品库搜索
        if self._product_repo is not None:
            for kw in keywords:
                found = self._product_repo.search_skus_by_name(kw, limit=1)
                if found:
                    return kw
        return None
