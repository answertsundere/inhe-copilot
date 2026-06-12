"""
match_product_from_message 节点 - 无订单号时从消息中匹配商品名
"""

from app.agent.tools.product_adapter import ProductAdapter


def match_product_from_message(state: dict) -> dict:
    """从客户消息中匹配商品"""
    msg = state.get("normalized_message", state.get("customer_message", ""))
    adapter = ProductAdapter()
    try:
        from app.main import get_product_repo, get_product_knowledge_repo
        adapter = ProductAdapter(
            product_repo=get_product_repo(),
            product_knowledge_repo=get_product_knowledge_repo(),
        )
    except Exception:
        pass

    product_name = adapter.match_product_from_message(msg)
    product_knowledge = []
    if product_name:
        product_knowledge = adapter.search_product_knowledge(product_name, limit=2)

    trace = {
        "node": "match_product_from_message",
        "step": "product_match",
        "status": "success" if product_name else "skipped",
        "summary": f"匹配到商品 {product_name or '无'}",
    }
    return {
        "matched_product_name": product_name or "",
        "product_knowledge": product_knowledge,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
