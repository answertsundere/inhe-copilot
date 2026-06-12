"""
match_order_products 节点 - 匹配订单中的商品信息
"""

from app.agent.tools.product_adapter import ProductAdapter


def match_order_products(state: dict) -> dict:
    """根据订单 SKU 匹配商品知识"""
    order = state.get("live_order") or state.get("order")
    if not order:
        trace = {
            "node": "match_order_products",
            "step": "product_match",
            "status": "skipped",
            "summary": "无订单，跳过商品匹配",
        }
        return {"trace_steps": state.get("trace_steps", []) + [trace]}

    items = order.get("items", [])
    if not items:
        trace = {
            "node": "match_order_products",
            "step": "product_match",
            "status": "skipped",
            "summary": "订单无商品明细",
        }
        return {"trace_steps": state.get("trace_steps", []) + [trace]}

    adapter = ProductAdapter()
    try:
        from app.main import get_product_repo, get_product_knowledge_repo
        adapter = ProductAdapter(
            product_repo=get_product_repo(),
            product_knowledge_repo=get_product_knowledge_repo(),
        )
    except Exception:
        pass

    products = []
    product_knowledge = []
    for item in items:
        sku_id = item.get("sku_id")
        i_id = item.get("i_id")
        if sku_id:
            sku = adapter.get_by_sku(sku_id)
            if sku:
                products.append(sku)
        if i_id:
            prod = adapter.get_by_i_id(i_id)
            if prod:
                products.append(prod)

    if products:
        product_knowledge = adapter.search_product_knowledge(
            state.get("customer_message", ""), context_products=products, limit=3
        )

    trace = {
        "node": "match_order_products",
        "step": "product_match",
        "status": "success" if products else "skipped",
        "summary": f"匹配到 {len(products)} 个商品, {len(product_knowledge)} 条知识",
    }
    return {
        "products": products,
        "product_knowledge": product_knowledge,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
