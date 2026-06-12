"""
实时查询 API 路由 - 提供 4 个端点供 Agent 调用
"""

from flask import Blueprint, jsonify, request

live_query_bp = Blueprint("live_query", __name__)


def _get_service():
    from app.main import get_live_query_service
    return get_live_query_service()


@live_query_bp.route("/api/live/product/<sku_id>")
def api_live_product(sku_id):
    """
    完整产品信息（聚水潭 + 钉钉）

    返回:
    - jst: 聚水潭 SKU 基础信息
    - dingtalk: 钉钉 SKU 数据库详情（颜色、安装视频、打包指南、纸箱尺寸、价格）
    - platform_info: 钉钉商品知识库（各平台标题、类目、图片、店铺）
    - combined: 合并后的关键字段
    """
    service = _get_service()
    try:
        result = service.query_product_detail(sku_id)
        if not result["jst"] and not result["dingtalk"]:
            return jsonify({
                "error": f"未找到 SKU {sku_id} 的信息",
                "sku_id": sku_id,
            }), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "sku_id": sku_id}), 500


@live_query_bp.route("/api/live/order/<order_id>")
def api_live_order(order_id):
    """
    订单状态 + 物流 + 售后（聚水潭实时）

    返回:
    - order: 订单详情
    - logistics: 物流信息列表
    - refunds: 退款/售后列表
    - summary: 关键摘要
    """
    service = _get_service()
    try:
        result = service.query_order_status(order_id)
        if not result["order"]:
            return jsonify({
                "error": f"未找到订单 {order_id}",
                "order_id": order_id,
            }), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "order_id": order_id}), 500


@live_query_bp.route("/api/live/sku/<sku_id>")
def api_live_sku(sku_id):
    """
    单个 SKU 实时信息（聚水潭 + 钉钉 + 库存）

    返回:
    - sku: 聚水潭 SKU 信息
    - inventory: 聚水潭库存
    - dingtalk: 钉钉 SKU 数据库详情
    """
    service = _get_service()
    try:
        result = service.query_sku_detail(sku_id)
        if not result["sku"] and not result["dingtalk"]:
            return jsonify({
                "error": f"未找到 SKU {sku_id}",
                "sku_id": sku_id,
            }), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "sku_id": sku_id}), 500


@live_query_bp.route("/api/live/search")
def api_live_search():
    """
    按关键词搜索产品（聚水潭 + 钉钉）

    参数: ?q=关键词
    """
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify({"error": "请提供搜索关键词 ?q=xxx"}), 400

    limit = int(request.args.get("limit", 20))
    service = _get_service()
    try:
        result = service.search_products(keyword, limit=limit)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "keyword": keyword}), 500
