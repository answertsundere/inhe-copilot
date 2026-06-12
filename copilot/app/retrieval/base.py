"""
检索抽象基类

所有检索实现必须继承 BaseKnowledgeRetriever。
Tool Registry 中的 rag_search_tool 只能依赖此接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseKnowledgeRetriever(ABC):
    """知识检索抽象基类。"""

    @abstractmethod
    def retrieve(
        self,
        query: str,
        product_scope: list[str] | None = None,
        sku_scope: list[str] | None = None,
        source_types: list[str] | None = None,
        fact_type: str = "",
        top_k: int = 5,
        min_score: float = 0.1,
        sku_name: str = "",
        product_name: str = "",
    ) -> list[dict]:
        """检索知识分片。

        Args:
            query: 查询文本
            product_scope: 商品范围过滤
            sku_scope: SKU 范围过滤
            source_types: 限制的 source_type 列表
            fact_type: 期望的事实类型
            top_k: 返回数量
            min_score: 最低分数阈值
            sku_name: 查询涉及的 SKU 编码
            product_name: 查询涉及的商品名称

        Returns:
            检索结果列表，每条包含:
            - chunk_id: int
            - entry_id: int
            - title: str
            - chunk_text: str
            - score: float
            - source_type: str
            - product_scope: list[str]
            - sku_scope: list[str]
            - entry_status: str
            - entry_risk_level: str
            - rerank_score: float
        """
        ...
