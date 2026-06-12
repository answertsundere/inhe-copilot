"""
resolve_product_identity 节点 - 从消息中识别商品
支持唯一匹配、多候选追问、匹配不到引导
优化：无订单号时不返回查 JST 的信号
"""

import time
import re

from app.agent.tools.product_adapter import ProductAdapter

# 商品关键词映射
_PRODUCT_KEYWORDS = {
    "书架": ["书架", "绘本架", "置物架", "收纳架", "杂志架"],
    "书桌": ["书桌", "电脑桌", "学习桌", "办公桌"],
    "椅子": ["椅子", "餐椅", "办公椅", "凳子"],
    "柜子": ["柜子", "衣柜", "鞋柜", "书柜", "橱柜", "电视柜"],
    "沙发": ["沙发"],
    "床": ["床"],
    "茶几": ["茶几"],
    "餐桌": ["餐桌"],
    "花架": ["花架"],
    "鞋架": ["鞋架"],
}

_MODEL_PRODUCT_PATTERN = re.compile(
    r"([一二三四五六七八九十百千万两0-9]+号[\u4e00-\u9fff]{0,12}?(?:围兜|罩衣|防摔枕|枕头|书架|绘本架|收纳架|柜|凳|桌|椅))"
)


def _match_products_from_message(msg: str) -> list:
    """从消息中匹配商品候选"""
    candidates = []
    msg_lower = msg.lower()

    model_match = _MODEL_PRODUCT_PATTERN.search(msg)
    if model_match:
        candidates.append(model_match.group(1))

    for category, keywords in _PRODUCT_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                candidates.append(category)
                break

    seen = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def resolve_product_identity(state: dict) -> dict:
    """识别消息中的商品"""
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", ""))
    slots = state.get("slots", {})
    slot_product = slots.get("product_name", "")
    sidecar_candidates = state.get("product_candidates") or (state.get("copilot_context", {}) or {}).get("product_candidates") or []

    # 无订单号标记
    has_order_id = bool(slots.get("order_id") or slots.get("possible_numeric_id"))

    # === Check if product identity is already resolved upstream ===
    identity = state.get("order_product_identity") or {}
    matched_name = state.get("matched_product_name", "")
    if identity.get("status") == "resolved" and (identity.get("matched_product_name") or matched_name):
        resolved_name = identity.get("matched_product_name") or matched_name
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "resolve_product_identity",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"使用已解析商品身份: {resolved_name} (source={identity.get('source', '')})",
        }
        if not has_order_id:
            trace["no_order_skip_order_lookup"] = True
        return {
            "matched_product_name": resolved_name,
            "product_candidates": [resolved_name],
            "need_clarification": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 优先使用 slot_extract 已提取的商品名
    if slot_product:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "resolve_product_identity",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"唯一匹配商品: {slot_product}",
        }
        if not has_order_id:
            trace["no_order_skip_order_lookup"] = True
        return {
            "matched_product_name": slot_product,
            "product_candidates": [slot_product],
            "need_clarification": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if sidecar_candidates:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "resolve_product_identity",
            "status": "skipped",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": "已有侧边栏商品候选，跳过消息泛词匹配",
        }
        if not has_order_id:
            trace["no_order_skip_order_lookup"] = True
        return {
            "matched_product_name": "",
            "product_candidates": sidecar_candidates,
            "need_clarification": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 从消息中匹配
    candidates = _match_products_from_message(msg)

    if len(candidates) == 1:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "resolve_product_identity",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"唯一匹配商品: {candidates[0]}",
        }
        if not has_order_id:
            trace["no_order_skip_order_lookup"] = True
        return {
            "matched_product_name": candidates[0],
            "product_candidates": candidates,
            "need_clarification": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if len(candidates) > 1:
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "resolve_product_identity",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"多个候选商品: {', '.join(candidates)}",
        }
        if not has_order_id:
            trace["no_order_skip_order_lookup"] = True
        return {
            "matched_product_name": "",
            "product_candidates": candidates,
            "need_clarification": True,
            "clarification_question": f"亲亲，您咨询的是{'、'.join(candidates)}中的哪一款呢？可以提供一下具体的款式、颜色或订单号，我帮您精确查询哦～",
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 匹配不到，尝试用 ProductAdapter 搜索
    try:
        adapter = ProductAdapter()
        results = adapter.search_by_name(msg)
        if results and len(results) == 1:
            name = results[0].get("name", "")
            duration_ms = int((time.time() - t0) * 1000)
            trace = {
                "node": "resolve_product_identity",
                "status": "success",
                "duration_ms": duration_ms,
                "cache_hit": False,
                "summary": f"唯一匹配商品: {name}",
            }
            if not has_order_id:
                trace["no_order_skip_order_lookup"] = True
            return {
                "matched_product_name": name,
                "product_candidates": [name],
                "need_clarification": False,
                "trace_steps": state.get("trace_steps", []) + [trace],
            }
        if results and len(results) > 1:
            names = [r.get("name", "") for r in results[:3]]
            duration_ms = int((time.time() - t0) * 1000)
            trace = {
                "node": "resolve_product_identity",
                "status": "success",
                "duration_ms": duration_ms,
                "cache_hit": False,
                "summary": f"多个候选商品: {', '.join(names)}",
            }
            if not has_order_id:
                trace["no_order_skip_order_lookup"] = True
            return {
                "matched_product_name": "",
                "product_candidates": names,
                "need_clarification": True,
                "clarification_question": f"亲亲，您咨询的是{'、'.join(names)}中的哪一款呢？可以提供一下具体的款式、颜色或订单号，我帮您精确查询哦～",
                "trace_steps": state.get("trace_steps", []) + [trace],
            }
    except Exception:
        pass

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "resolve_product_identity",
        "status": "skipped",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": "未匹配到商品",
    }
    if not has_order_id:
        trace["no_order_skip_order_lookup"] = True
    return {
        "matched_product_name": "",
        "product_candidates": [],
        "need_clarification": False,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
