"""
仓库基类 - 定义数据访问接口
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseRepository(ABC):
    """仓库基类，所有仓库继承此类"""

    @abstractmethod
    def load(self):
        """加载数据"""
        ...


class OrderRepositoryBase(BaseRepository):
    """订单仓库接口"""

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[dict]:
        """查询订单"""
        ...

    @abstractmethod
    def get_logistics(self, order_id: str) -> list:
        """查询物流"""
        ...

    @abstractmethod
    def get_refunds(self, order_id: str) -> list:
        """查询退款"""
        ...

    @abstractmethod
    def count_orders(self) -> int:
        """统计订单数量"""
        ...


class ProductRepositoryBase(BaseRepository):
    """商品仓库接口"""

    @abstractmethod
    def get_sku(self, sku_id: str) -> Optional[dict]:
        """查询 SKU"""
        ...

    @abstractmethod
    def get_product(self, i_id: str) -> Optional[dict]:
        """查询商品"""
        ...

    @abstractmethod
    def count_skus(self) -> int:
        """统计 SKU 数量"""
        ...

    @abstractmethod
    def count_products(self) -> int:
        """统计商品数量"""
        ...


class KnowledgeRepositoryBase(BaseRepository):
    """知识库仓库接口"""

    @abstractmethod
    def search(self, query: str, category: str = "", limit: int = 5) -> list:
        """搜索知识"""
        ...


class PolicyRepositoryBase(BaseRepository):
    """规则仓库接口"""

    @abstractmethod
    def get_forbidden_claims(self) -> list:
        """获取禁止承诺列表"""
        ...

    @abstractmethod
    def get_risk_keywords(self) -> dict:
        """获取风险关键词"""
        ...

    @abstractmethod
    def get_reply_policies(self) -> list:
        """获取回复策略"""
        ...
