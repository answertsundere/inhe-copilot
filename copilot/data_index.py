"""
数据索引层 - 加载聚水潭数据并建立内存索引
"""

import json
import os
from config import DATA_DIR


class DataIndex:
    def __init__(self):
        self.orders = {}        # o_id -> order
        self.skus = {}          # sku_id -> sku
        self.items = {}         # i_id -> item
        self.logistics = {}     # o_id -> [logistics]
        self.refunds = {}       # o_id -> [refund]
        self.shops = {}         # shop_id -> shop
        self.inventory = {}     # sku_id -> [inventory]
        self.aftersale = {}     # o_id -> [aftersale]
        self.loaded = False

    def load_all(self):
        """加载所有数据文件"""
        print("正在加载数据索引...")
        self._load_orders()
        self._load_skus()
        self._load_items()
        self._load_logistics()
        self._load_refunds()
        self._load_shops()
        self._load_inventory()
        self._load_aftersale()
        self.loaded = True
        print(f"数据加载完成: 订单{len(self.orders)} SKU{len(self.skus)} "
              f"商品{len(self.items)} 物流{len(self.logistics)} "
              f"退款{len(self.refunds)} 店铺{len(self.shops)}")

    def _load_json(self, filename):
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_orders(self):
        data = self._load_json("orders.json")
        for order in data:
            oid = str(order.get("o_id", ""))
            if oid:
                self.orders[oid] = order

    def _load_skus(self):
        data = self._load_json("skus.json")
        for sku in data:
            sid = str(sku.get("sku_id", ""))
            if sid:
                self.skus[sid] = sku

    def _load_items(self):
        data = self._load_json("items.json")
        for item in data:
            iid = str(item.get("i_id", ""))
            if iid:
                self.items[iid] = item

    def _load_logistics(self):
        data = self._load_json("logistics.json")
        for log in data:
            oid = str(log.get("o_id", ""))
            if oid:
                self.logistics.setdefault(oid, []).append(log)

    def _load_refunds(self):
        data = self._load_json("refunds.json")
        for refund in data:
            oid = str(refund.get("o_id", ""))
            if oid:
                self.refunds.setdefault(oid, []).append(refund)

    def _load_shops(self):
        data = self._load_json("shops_all.json")
        for shop in data:
            sid = str(shop.get("shop_id", ""))
            if sid:
                self.shops[sid] = shop

    def _load_inventory(self):
        data = self._load_json("inventory.json")
        for inv in data:
            sid = str(inv.get("sku_id", ""))
            if sid:
                self.inventory.setdefault(sid, []).append(inv)

    def _load_aftersale(self):
        data = self._load_json("aftersale_received.json")
        for aft in data:
            oid = str(aft.get("o_id", ""))
            if oid:
                self.aftersale.setdefault(oid, []).append(aft)

    # ============ 查询工具 ============

    def query_order(self, order_id):
        """根据订单号查询订单详情"""
        oid = str(order_id)
        order = self.orders.get(oid)
        if not order:
            return None
        return self._format_order(order)

    def query_order_by_buyer(self, buyer_id):
        """根据买家ID查询最近订单"""
        bid = str(buyer_id)
        results = []
        for oid, order in self.orders.items():
            if str(order.get("buyer_id", "")) == bid:
                results.append(self._format_order(order))
        # 按时间倒序
        results.sort(key=lambda x: x.get("created", ""), reverse=True)
        return results[:10]

    def query_sku(self, sku_id):
        """根据SKU查询商品信息"""
        sid = str(sku_id)
        sku = self.skus.get(sid)
        if not sku:
            return None
        return {
            "sku_id": sku.get("sku_id"),
            "i_id": sku.get("i_id"),
            "name": sku.get("name"),
            "brand": sku.get("brand"),
            "sale_price": sku.get("sale_price"),
            "cost_price": sku.get("cost_price"),
            "weight": sku.get("weight"),
            "properties_value": sku.get("properties_value"),
            "category": sku.get("category"),
            "labels": sku.get("labels"),
        }

    def query_product(self, i_id):
        """根据款号查询商品详情"""
        iid = str(i_id)
        item = self.items.get(iid)
        if not item:
            return None
        # 关联的SKU
        related_skus = [s for s in self.skus.values() if s.get("i_id") == iid]
        return {
            "i_id": item.get("i_id"),
            "name": item.get("name"),
            "brand": item.get("brand"),
            "category": item.get("c_name"),
            "skus": [{
                "sku_id": s.get("sku_id"),
                "properties": s.get("properties_value"),
                "sale_price": s.get("sale_price"),
            } for s in related_skus],
        }

    def query_logistics(self, order_id):
        """根据订单号查询物流信息"""
        oid = str(order_id)
        logs = self.logistics.get(oid, [])
        return [{
            "l_id": l.get("l_id"),
            "logistics_company": l.get("logistics_company"),
            "send_date": l.get("send_date"),
            "items": [{"sku_id": i.get("sku_id"), "qty": i.get("qty")} for i in l.get("items", [])],
        } for l in logs]

    def query_refund(self, order_id):
        """根据订单号查询退款/售后信息"""
        oid = str(order_id)
        refs = self.refunds.get(oid, [])
        return [{
            "as_id": r.get("as_id"),
            "type": r.get("type"),
            "status": r.get("status"),
            "refund": r.get("refund"),
            "reason": r.get("remark"),
            "created": r.get("created"),
            "items": [{"sku_id": i.get("sku_id"), "qty": i.get("qty")} for i in r.get("items", [])],
        } for r in refs]

    def query_inventory(self, sku_id):
        """根据SKU查询库存"""
        sid = str(sku_id)
        invs = self.inventory.get(sid, [])
        return [{"qty": inv.get("qty"), "wms_co_id": inv.get("wms_co_id")} for inv in invs]

    def search_orders_by_status(self, status, limit=20):
        """按状态搜索订单"""
        results = []
        for oid, order in self.orders.items():
            if order.get("status") == status or order.get("shop_status") == status:
                results.append(self._format_order(order))
                if len(results) >= limit:
                    break
        return results

    def _format_order(self, order):
        """格式化订单信息"""
        return {
            "o_id": order.get("o_id"),
            "shop_id": order.get("shop_id"),
            "shop_name": order.get("shop_name"),
            "status": order.get("status"),
            "shop_status": order.get("shop_status"),
            "buyer_id": order.get("buyer_id"),
            "amount": order.get("amount"),
            "pay_amount": order.get("pay_amount"),
            "freight": order.get("freight"),
            "receiver_name": order.get("receiver_name"),
            "receiver_address": order.get("receiver_address"),
            "receiver_state": order.get("receiver_state"),
            "receiver_city": order.get("receiver_city"),
            "buyer_message": order.get("buyer_message"),
            "remark": order.get("remark"),
            "created": order.get("created"),
            "pay_date": order.get("pay_date"),
            "send_date": order.get("send_date"),
            "sign_time": order.get("sign_time"),
            "logistics_company": order.get("logistics_company"),
            "l_id": order.get("l_id"),
            "items": [{
                "sku_id": i.get("sku_id"),
                "i_id": i.get("i_id"),
                "name": i.get("name"),
                "qty": i.get("qty"),
                "price": i.get("price"),
            } for i in order.get("items", [])],
        }


# 全局单例
_index = None

def get_index():
    global _index
    if _index is None:
        _index = DataIndex()
        _index.load_all()
    return _index
