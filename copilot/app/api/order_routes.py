"""
订单/商品查询 API 路由
"""

from flask import Blueprint, jsonify

order_bp = Blueprint("order", __name__)


def get_repos():
    """获取仓库实例"""
    from app.main import get_order_repo, get_product_repo
    return get_order_repo(), get_product_repo()


@order_bp.route("/api/order/<order_id>")
def api_order(order_id):
    """查询订单 — 优先聚水潭实时查询，仅在 API 未配置时回退到本地缓存"""
    order_repo, _ = get_repos()

    # 优先聚水潭实时查询
    from app.config import JST_APP_KEY, JST_ACCESS_TOKEN
    if JST_APP_KEY and JST_ACCESS_TOKEN:
        try:
            from app.main import get_live_query_service
            service = get_live_query_service()
            result = service.query_order_status(order_id)
            if result.get("order"):
                jst_order = result["order"]
                order = {
                    "o_id": str(jst_order.get("o_id", order_id)),
                    "so_id": str(jst_order.get("so_id", "")),
                    "outer_so_id": str(jst_order.get("outer_so_id", "")),
                    "shop_name": jst_order.get("shop_name", ""),
                    "status": jst_order.get("status", ""),
                    "shop_status": jst_order.get("shop_status", ""),
                    "pay_amount": jst_order.get("pay_amount", 0),
                    "amount": jst_order.get("amount", 0),
                    "created": jst_order.get("created", ""),
                    "pay_date": jst_order.get("pay_date", ""),
                    "send_date": jst_order.get("send_date", ""),
                    "sign_time": jst_order.get("sign_time", ""),
                    "logistics_company": jst_order.get("logistics_company", ""),
                    "l_id": jst_order.get("l_id", ""),
                    "buyer_message": jst_order.get("buyer_message", ""),
                    "remark": jst_order.get("remark", ""),
                    "items": jst_order.get("items", []),
                }
                return jsonify({
                    "order": order,
                    "logistics": result.get("logistics", []),
                    "refunds": result.get("refunds", []),
                    "source": "jst_live",
                    "note": "聚水潭实时查询",
                })
            else:
                return jsonify({
                    "error": f"聚水潭实时查询未找到订单 {order_id}",
                    "source": "jst_not_found",
                    "hint": "请确认订单号是否正确。支持聚水潭订单号、店铺订单号、快递单号查询。",
                }), 404
        except Exception as e:
            return jsonify({
                "error": f"聚水潭实时查询失败: {str(e)}",
                "source": "jst_error",
            }), 500

    # 聚水潭未配置时回退到本地缓存
    order = order_repo.get_order(order_id)
    if not order:
        return jsonify({
            "error": f"未找到订单 {order_id}",
            "source": "local_not_found",
            "hint": "聚水潭 API 未配置，请在 .env 中配置 JUSHUITAN_APP_KEY、JUSHUITAN_APP_SECRET、JUSHUITAN_ACCESS_TOKEN",
        }), 404

    logistics = order_repo.get_logistics(order_id)
    refunds = order_repo.get_refunds(order_id)
    return jsonify({
        "order": order,
        "logistics": logistics,
        "refunds": refunds,
        "source": "local",
    })


@order_bp.route("/api/sku/<sku_id>")
def api_sku(sku_id):
    """查询 SKU"""
    _, product_repo = get_repos()
    sku = product_repo.get_sku(sku_id)
    if not sku:
        return jsonify({"error": f"未找到SKU {sku_id}"}), 404
    return jsonify(sku)


@order_bp.route("/api/product/<i_id>")
def api_product(i_id):
    """查询商品"""
    _, product_repo = get_repos()
    product = product_repo.get_product(i_id)
    if not product:
        return jsonify({"error": f"未找到商品 {i_id}"}), 404
    return jsonify(product)


@order_bp.route("/api/sku/search")
def api_sku_search():
    """按名称搜索 SKU"""
    from flask import request
    _, product_repo = get_repos()
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "请输入搜索关键词"}), 400
    results = product_repo.search_skus_by_name(q, limit=20)
    return jsonify({"query": q, "count": len(results), "results": results})


@order_bp.route("/api/stats")
def api_stats():
    """数据统计"""
    order_repo, product_repo = get_repos()
    from app.main import get_feedback_service, get_product_knowledge_repo, get_reply_template_repo, get_sop_repo
    fb_service = get_feedback_service()
    pk_repo = get_product_knowledge_repo()
    rt_repo = get_reply_template_repo()
    sop_repo = get_sop_repo()

    return jsonify({
        "orders": order_repo.count_orders(),
        "skus": product_repo.count_skus(),
        "items": product_repo.count_products(),
        "logistics": order_repo.count_logistics(),
        "refunds": order_repo.count_refunds(),
        "product_knowledge_cards": pk_repo.count(),
        "reply_templates": rt_repo.count(),
        "sop_scenarios": sop_repo.count(),
        "feedback": fb_service.get_stats(),
    })
