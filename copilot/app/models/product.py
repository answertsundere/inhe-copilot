"""
商品数据模型
"""

from dataclasses import dataclass, field


@dataclass
class SKU:
    """SKU"""
    sku_id: str = ""
    i_id: str = ""
    name: str = ""
    brand: str = ""
    sale_price: float = 0.0
    cost_price: float = 0.0
    weight: float = 0.0
    properties_value: str = ""
    category: str = ""
    labels: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sku_id": self.sku_id,
            "i_id": self.i_id,
            "name": self.name,
            "brand": self.brand,
            "sale_price": self.sale_price,
            "cost_price": self.cost_price,
            "weight": self.weight,
            "properties_value": self.properties_value,
            "category": self.category,
            "labels": self.labels,
        }


@dataclass
class Product:
    """商品（款号级别）"""
    i_id: str = ""
    name: str = ""
    brand: str = ""
    category: str = ""
    skus: list = field(default_factory=list)  # List[SKU]

    def to_dict(self) -> dict:
        return {
            "i_id": self.i_id,
            "name": self.name,
            "brand": self.brand,
            "category": self.category,
            "skus": [s.to_dict() if isinstance(s, SKU) else s for s in self.skus],
        }
