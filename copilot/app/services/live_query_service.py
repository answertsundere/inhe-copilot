"""
Live Query Service - 聚合聚水潭 + 钉钉两个数据源，提供实时查询
"""

from typing import Optional, List


class LiveQueryService:
    """实时查询服务 - 聚合多个数据源"""

    def __init__(self, jst_repo, dingtalk_repo):
        self._jst = jst_repo
        self._dt = dingtalk_repo

    def query_product_detail(self, sku_id: str) -> dict:
        """
        聚合聚水潭+钉钉，返回完整产品信息

        数据来源:
        1. 聚水潭 SKU → 基础信息（名称、成本价、重量、规格属性）
        2. 钉钉 SKU数据库 → 颜色、安装视频、打包指南、纸箱尺寸、多级价格
        3. 钉钉商品知识库 → 平台标题、类目、图片、关联店铺
        """
        result = {
            "sku_id": sku_id,
            "jst": None,
            "dingtalk": None,
            "platform_info": [],
            "combined": {},
        }

        # 1. 聚水潭 SKU 信息
        jst_sku = self._jst.query_sku(sku_id)
        if jst_sku:
            result["jst"] = {
                "sku_id": jst_sku.get("sku_id"),
                "name": jst_sku.get("name"),
                "i_id": jst_sku.get("i_id"),
                "cost_price": jst_sku.get("cost_price"),
                "sale_price": jst_sku.get("sale_price"),
                "weight": jst_sku.get("weight"),
                "length": jst_sku.get("length"),
                "width": jst_sku.get("width"),
                "height": jst_sku.get("height"),
                "properties": jst_sku.get("properties_value"),
                "sku_code": jst_sku.get("sku_code"),
                "brand": jst_sku.get("brand"),
                "category": jst_sku.get("category"),
                "enabled": jst_sku.get("enabled"),
            }

        # 2. 钉钉 SKU数据库
        dt_sku = self._dt.query_sku(sku_id)
        if dt_sku:
            result["dingtalk"] = dt_sku

        # 3. 钉钉商品知识库（多平台信息）
        dt_knowledge = self._dt.query_knowledge(sku_id)
        if dt_knowledge:
            result["platform_info"] = dt_knowledge

        # 4. 合并关键信息到 combined（方便快速查看）
        combined = {}
        if jst_sku:
            combined["name"] = jst_sku.get("name", "")
            combined["cost_price"] = jst_sku.get("cost_price")
            combined["sale_price"] = jst_sku.get("sale_price")
            combined["weight_kg"] = jst_sku.get("weight")
            combined["dimensions_cm"] = {
                "length": jst_sku.get("length"),
                "width": jst_sku.get("width"),
                "height": jst_sku.get("height"),
            }
        if dt_sku:
            combined["color"] = dt_sku.get("color", "")
            combined["spec"] = dt_sku.get("spec", "")
            combined["product_name"] = dt_sku.get("product_name", "")
            combined["install_videos"] = dt_sku.get("install_videos", {})
            combined["pack_guide_count"] = len(dt_sku.get("pack_guide_images", []))
            combined["box_dimensions_cm"] = {
                "length": dt_sku.get("box_length_cm"),
                "width": dt_sku.get("box_width_cm"),
                "height": dt_sku.get("box_height_cm"),
            }
            combined["gross_weight_kg"] = dt_sku.get("gross_weight_kg")
            combined["net_weight_kg"] = dt_sku.get("net_weight_kg")
            combined["production_type"] = dt_sku.get("production_type", "")
            combined["stock_status"] = dt_sku.get("stock_status", "")
            combined["prices"] = {
                "retail": dt_sku.get("price_retail"),
                "promo": dt_sku.get("price_promo"),
                "cost_high": dt_sku.get("price_cost_high"),
                "cost_mid": dt_sku.get("price_cost_mid"),
                "cost_low": dt_sku.get("price_cost_low"),
                "dist_high": dt_sku.get("price_dist_high"),
                "dist_low": dt_sku.get("price_dist_low"),
                "freight_avg": dt_sku.get("freight_avg"),
            }
            combined["sku_images"] = dt_sku.get("sku_images", [])
            combined["pack_guide_images"] = dt_sku.get("pack_guide_images", [])

        if dt_knowledge:
            shops = list({k.get("shop", "") for k in dt_knowledge if k.get("shop")})
            combined["shops"] = shops
            combined["platform_count"] = len(dt_knowledge)

        result["combined"] = combined
        return result

    def query_order_status(self, order_id: str, timeout: float = 5.0, max_total_seconds: float = 15.0) -> dict:
        """
        查询订单状态 + 物流 + 售后

        数据来源: 聚水潭
        order_id 可以是：聚水潭订单号、店铺订单号、平台订单号、快递单号

        timeout: 聚水潭单次 API 调用超时（秒），默认 5 秒。
        max_total_seconds: _find_order 整体最大耗时（秒），默认 15 秒。
        """
        result = {
            "order_id": order_id,
            "order": None,
            "logistics": [],
            "refunds": [],
            "summary": {},
        }

        order = self._jst.query_order(order_id, timeout=timeout, max_total_seconds=max_total_seconds)

        if order:
            result["order"] = order
            result["summary"] = {
                "status": order.get("status"),
                "shop_name": order.get("shop_name"),
                "pay_time": order.get("pay_time"),
                "shipping_time": order.get("shipping_time"),
                "finish_time": order.get("finish_time"),
                "total_amount": order.get("total_amount"),
                "item_count": len(order.get("items", [])),
            }

            # 用查到的 o_id 查询物流和退款
            real_o_id = str(order.get("o_id", order_id))

            logistics = self._jst.query_logistics(real_o_id)
            if logistics:
                result["logistics"] = logistics
                if logistics:
                    first = logistics[0]
                    result["summary"]["logistics_company"] = first.get("logistics_company", "")
                    result["summary"]["tracking_no"] = first.get("l_id", "")
                    result["summary"]["send_date"] = first.get("send_date", "")

            refunds = self._jst.query_refunds(real_o_id)
            if refunds:
                result["refunds"] = refunds
                result["summary"]["refund_status"] = refunds[0].get("status")

        return result

    def query_sku_detail(self, sku_id: str) -> dict:
        """单个 SKU 的完整实时信息（含库存）"""
        result = {
            "sku_id": sku_id,
            "sku": None,
            "inventory": None,
            "dingtalk": None,
        }

        sku = self._jst.query_sku(sku_id)
        if sku:
            result["sku"] = sku

        inv = self._jst.query_inventory(sku_id)
        if inv:
            result["inventory"] = inv

        dt = self._dt.query_sku(sku_id)
        if dt:
            result["dingtalk"] = dt

        return result

    def search_products(self, keyword: str, limit: int = 20) -> dict:
        """按关键词搜索产品（聚水潭 + 钉钉）"""
        jst_results = self._jst.search_skus(keyword, limit=limit)
        dt_results = self._dt.search_products(keyword, limit=limit)

        return {
            "keyword": keyword,
            "jst_results": jst_results,
            "dingtalk_results": dt_results,
            "jst_count": len(jst_results),
            "dingtalk_count": len(dt_results),
        }
