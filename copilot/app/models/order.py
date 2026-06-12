"""
订单数据模型
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrderItem:
    """订单商品明细"""
    sku_id: str = ""
    i_id: str = ""
    name: str = ""
    qty: int = 1
    price: float = 0.0


@dataclass
class Order:
    """订单"""
    o_id: str = ""
    shop_name: str = ""
    status: str = ""
    shop_status: str = ""
    buyer_id: str = ""
    amount: float = 0.0
    pay_amount: float = 0.0
    freight: float = 0.0
    receiver_name: str = ""
    receiver_state: str = ""
    receiver_city: str = ""
    receiver_address: str = ""
    buyer_message: str = ""
    remark: str = ""
    created: str = ""
    pay_date: str = ""
    send_date: Optional[str] = None
    sign_time: Optional[str] = None
    logistics_company: str = ""
    l_id: str = ""
    items: list = field(default_factory=list)  # List[OrderItem]

    def to_dict(self) -> dict:
        return {
            "o_id": self.o_id,
            "shop_name": self.shop_name,
            "status": self.status,
            "shop_status": self.shop_status,
            "buyer_id": self.buyer_id,
            "amount": self.amount,
            "pay_amount": self.pay_amount,
            "freight": self.freight,
            "receiver_name": self.receiver_name,
            "receiver_state": self.receiver_state,
            "receiver_city": self.receiver_city,
            "receiver_address": self.receiver_address,
            "buyer_message": self.buyer_message,
            "remark": self.remark,
            "created": self.created,
            "pay_date": self.pay_date,
            "send_date": self.send_date,
            "sign_time": self.sign_time,
            "logistics_company": self.logistics_company,
            "l_id": self.l_id,
            "items": [i.to_dict() if isinstance(i, OrderItem) else i for i in self.items],
        }


@dataclass
class Logistics:
    """物流信息"""
    o_id: str = ""
    l_id: str = ""
    logistics_company: str = ""
    send_date: str = ""
    items: list = field(default_factory=list)


@dataclass
class Refund:
    """退款/售后"""
    o_id: str = ""
    as_id: str = ""
    type: str = ""
    status: str = ""
    refund: float = 0.0
    remark: str = ""
    created: str = ""
    items: list = field(default_factory=list)
