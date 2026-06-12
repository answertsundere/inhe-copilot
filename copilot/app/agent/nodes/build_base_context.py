"""
build_base_context 节点 - 构建基础上下文
优化：优先使用 app/main.py 已初始化的单例仓库，避免每次请求 new repo + load()。
物流场景只加载必要上下文。
"""

import time

# 延迟初始化：本地 fallback（仅当 app/main.py 单例不可用时）
_context_builder = None
_init_ms = None


def _get_context_builder():
    """优先使用 app/main.py 单例，fallback 到本地 lazy singleton"""
    global _context_builder, _init_ms
    if _context_builder is not None:
        return _context_builder

    # 尝试使用 app/main.py 的单例仓库
    try:
        from app.main import (
            get_order_repo, get_product_repo, get_knowledge_repo,
            get_product_knowledge_repo, get_reply_template_repo, get_sop_repo,
        )
        from app.services.context_builder import ContextBuilder

        t0 = time.time()
        _context_builder = ContextBuilder(
            order_repo=get_order_repo(),
            product_repo=get_product_repo(),
            knowledge_repo=get_knowledge_repo(),
            product_knowledge_repo=get_product_knowledge_repo(),
            reply_template_repo=get_reply_template_repo(),
            sop_repo=get_sop_repo(),
        )
        _init_ms = int((time.time() - t0) * 1000)
        return _context_builder
    except Exception:
        pass

    # Fallback：本地创建（仅在测试或独立运行时）
    from app.services.context_builder import ContextBuilder
    from app.repositories.json_order_repository import JsonOrderRepository
    from app.repositories.json_product_repository import JsonProductRepository
    from app.repositories.file_knowledge_repository import FileKnowledgeRepository
    from app.repositories.product_knowledge_repository import ProductKnowledgeRepository
    from app.repositories.reply_template_repository import ReplyTemplateRepository
    from app.repositories.sop_repository import SOPRepository
    from app.config import KNOWLEDGE_DIR

    t0 = time.time()
    order_repo = JsonOrderRepository()
    order_repo.load()
    product_repo = JsonProductRepository()
    product_repo.load()
    knowledge_repo = FileKnowledgeRepository()
    knowledge_repo.load()
    pk_repo = ProductKnowledgeRepository(knowledge_dir=KNOWLEDGE_DIR)
    pk_repo.load()
    rt_repo = ReplyTemplateRepository(knowledge_dir=KNOWLEDGE_DIR)
    rt_repo.load()
    sop_repo = SOPRepository(knowledge_dir=KNOWLEDGE_DIR)
    sop_repo.load()
    _context_builder = ContextBuilder(
        order_repo=order_repo,
        product_repo=product_repo,
        knowledge_repo=knowledge_repo,
        product_knowledge_repo=pk_repo,
        reply_template_repo=rt_repo,
        sop_repo=sop_repo,
    )
    _init_ms = int((time.time() - t0) * 1000)
    return _context_builder


def build_base_context(state: dict) -> dict:
    """构建基础上下文（复用单例仓库，物流场景轻量加载）"""
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", ""))
    order_id = state.get("order_id", "")
    intent = state.get("intent", "")
    builder = _get_context_builder()

    cache_hit = _init_ms is not None and _init_ms < 50

    # 物流场景：只构建轻量上下文
    is_logistics = intent in ("logistics_eta", "shipping", "logistics")
    if is_logistics and not order_id:
        context = _build_lightweight_logistics_context(builder, msg)
    else:
        context = builder.build(msg, order_id)

    duration_ms = int((time.time() - t0) * 1000)
    trace_steps = state.get("trace_steps", [])

    trace_steps.append({
        "node": "build_base_context",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": cache_hit,
        "summary": f"使用{'已初始化' if cache_hit else '新创建'}仓库，{'物流场景加载轻量上下文' if is_logistics and not order_id else '标准加载'}，"
                    f"订单 {'有' if context.get('order') else '无'}, 知识 {len(context.get('knowledge', []))} 条",
    })

    # 知识库命中
    knowledge = context.get("knowledge", [])
    if knowledge:
        trace_steps.append({
            "node": "build_base_context",
            "status": "success",
            "duration_ms": 0,
            "cache_hit": False,
            "summary": f"知识库命中 {len(knowledge)} 条: {[k.get('title', '') for k in knowledge[:3]]}",
        })

    # 商品匹配
    products = context.get("products", [])
    product_knowledge = context.get("product_knowledge", [])
    if products:
        trace_steps.append({
            "node": "build_base_context",
            "status": "success",
            "duration_ms": 0,
            "cache_hit": False,
            "summary": f"商品匹配 {len(products)} 个: {[p.get('name', p.get('sku_id', '')) for p in products[:3]]}",
        })
    elif product_knowledge:
        trace_steps.append({
            "node": "build_base_context",
            "status": "success",
            "duration_ms": 0,
            "cache_hit": False,
            "summary": f"商品知识匹配 {len(product_knowledge)} 个: {[p.get('name', '') for p in product_knowledge[:3]]}",
        })

    return {
        "order": context.get("order"),
        "logistics": context.get("logistics", []),
        "products": context.get("products", []),
        "product_knowledge": context.get("product_knowledge", []),
        "knowledge": context.get("knowledge", []),
        "sop_scenarios": context.get("sop_scenarios", []),
        "reply_templates": context.get("reply_templates", []),
        "data_quality_warnings": context.get("data_quality_warnings", []),
        "trace_steps": trace_steps,
    }


def _build_lightweight_logistics_context(builder, msg: str) -> dict:
    """物流场景轻量上下文：只加载物流政策 + 商品摘要 + 回复模板"""
    try:
        full = builder.build(msg, "")
        return {
            "order": None,
            "logistics": [],
            "products": full.get("products", [])[:5],
            "product_knowledge": full.get("product_knowledge", [])[:5],
            "knowledge": [k for k in full.get("knowledge", [])
                          if any(kw in k.get("title", "").lower()
                                 for kw in ("物流", "发货", "快递", "时效", "配送"))],
            "sop_scenarios": full.get("sop_scenarios", [])[:3],
            "reply_templates": full.get("reply_templates", [])[:5],
            "data_quality_warnings": [],
        }
    except Exception:
        return {
            "order": None, "logistics": [], "products": [],
            "product_knowledge": [], "knowledge": [],
            "sop_scenarios": [], "reply_templates": [],
            "data_quality_warnings": [],
        }
