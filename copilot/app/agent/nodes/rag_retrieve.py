"""
rag_retrieve 节点 - 条件式检索 published 知识分片
只有 should_query_knowledge=true 才执行
通过 RetrieverFactory 调用检索
"""

import logging
import re
import time

logger = logging.getLogger(__name__)


def _candidate_texts(candidate) -> list[str]:
    if isinstance(candidate, str):
        return [candidate] if candidate.strip() else []
    if not isinstance(candidate, dict):
        return []
    texts = []
    for key in ("value", "name", "product_name", "title", "sku_name", "sku_id", "i_id"):
        val = str(candidate.get(key) or "").strip()
        if val and val not in texts:
            texts.append(val)
    return texts


def _candidate_sku_texts(candidate) -> list[str]:
    if isinstance(candidate, str):
        val = candidate.strip()
        return [val] if _looks_like_product_code(val) else []
    if not isinstance(candidate, dict):
        return []
    texts = []
    for key in ("sku_code", "sku_id", "i_id"):
        val = str(candidate.get(key) or "").strip()
        if val and val not in texts:
            texts.append(val)
    return texts


def _looks_like_product_code(value: str) -> bool:
    return bool(re.match(r"^YH[A-Za-z0-9_-]{4,40}$", str(value or "").strip(), re.IGNORECASE))


def _first_product_candidate_text(candidates: list) -> str:
    """Pick a product-like candidate for query expansion without treating SKU as a product name."""
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        candidate_type = str(candidate.get("type") or "").lower()
        if "sku" in candidate_type:
            continue
        for key in ("matched_product_name", "product_name", "title", "name", "value"):
            val = str(candidate.get(key) or "").strip()
            if val:
                return val
    return ""


def _append_unique(parts: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in parts:
        parts.append(value)


def _build_search_query(message: str, product_name: str, sku_name: str, product_scope: list[str]) -> str:
    """Build a context-aware retrieval query.

    Customer messages are often short ("这个安全吗", "基础款和升级版差什么").
    Retrieval should therefore search with the resolved product context, while
    keeping the original message as the strongest first segment.
    """
    parts: list[str] = []
    _append_unique(parts, message)
    _append_unique(parts, product_name)
    _append_unique(parts, sku_name)
    for item in product_scope[:4]:
        _append_unique(parts, item)
    return " ".join(parts)[:500]


def _merge_ranked_results(primary: list[dict], supplemental: list[dict], limit: int = 8) -> list[dict]:
    merged: list[dict] = []
    seen = set()
    for item in [*(primary or []), *(supplemental or [])]:
        if not isinstance(item, dict):
            continue
        key = item.get("chunk_id") or item.get("entry_id") or item.get("title")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(item)
    merged.sort(key=lambda r: float(r.get("rerank_score", r.get("score", 0)) or 0), reverse=True)
    return merged[:limit]


def _prefer_matching_fact_type(results: list[dict], query_fact_type: str) -> list[dict]:
    if not query_fact_type or not results:
        return results
    try:
        from app.services.fact_type_service import fact_type_matches
    except Exception:
        return results
    matched = [
        item for item in results
        if fact_type_matches(query_fact_type, str(item.get("fact_type") or item.get("evidence_fact_type") or ""))
    ]
    return matched if matched else results


def rag_retrieve(state: dict) -> dict:
    """检索 published 知识分片（条件执行）"""
    t0 = time.time()

    # 条件执行：只有 should_query_knowledge=true 才检索
    should_query = state.get("should_query_knowledge", True)
    if not should_query:
        trace = {
            "node": "rag_retrieve",
            "status": "skipped",
            "duration_ms": 0,
            "cache_hit": False,
            "summary": "跳过检索: should_query_knowledge=false",
        }
        return {
            "retrieved_chunks": [],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    msg = state.get("normalized_message", state.get("customer_message", ""))
    intent = state.get("intent", "general")
    allowed_source_types = state.get("allowed_source_types", [])
    identity = state.get("order_product_identity") or {}
    product_candidates = state.get("product_candidates", [])
    slots = state.get("slots", {})
    product_name = (
        str(state.get("matched_product_name") or "").strip()
        or str(identity.get("matched_product_name") or "").strip()
        or str(slots.get("product_name") or "").strip()
        or _first_product_candidate_text(product_candidates)
    )
    sku_code = slots.get("sku_code", "")
    identity_sku = str(identity.get("sku_id") or "").strip()
    identity_i_id = str(identity.get("i_id") or "").strip()
    sku_name = slots.get("sku_name") or sku_code or identity_sku
    query_fact_type = state.get("query_fact_type", "")

    # 如果 allowed_source_types 为空，直接跳过
    if not allowed_source_types:
        trace = {
            "node": "rag_retrieve",
            "status": "skipped",
            "duration_ms": 0,
            "cache_hit": False,
            "summary": "跳过检索: allowed_source_types 为空",
        }
        return {
            "retrieved_chunks": [],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 构建检索参数
    product_scope = []
    if product_name:
        product_scope.append(product_name)
    if product_candidates:
        for pc in product_candidates:
            for text in _candidate_texts(pc):
                if text not in product_scope:
                    product_scope.append(text)

    # Also include product_id/i_id from order_product_identity for stable matching.
    # SKU belongs in sku_scope below; mixing it into product_scope weakens scope checks.
    for key in ("i_id",):
        val = str(identity.get(key) or "").strip()
        if val and val not in product_scope:
            product_scope.append(val)

    sku_scope = []
    if sku_code:
        sku_scope.append(sku_code)
    # Also add sku_id from identity if different from sku_code
    if identity_sku and identity_sku not in sku_scope:
        sku_scope.append(identity_sku)
    if identity_i_id and identity_i_id not in sku_scope:
        sku_scope.append(identity_i_id)
    for pc in product_candidates or []:
        for text in _candidate_sku_texts(pc):
            if text not in sku_scope:
                sku_scope.append(text)

    # intent 兼容映射
    search_intent = intent if intent != "general" else ""
    if intent == "product_consult":
        search_intent = "product_question"

    retrieval_mode = "retriever_hybrid"
    include_draft = False
    try:
        from app.services.metrics_service import get_metrics_service
        get_metrics_service().increment("rag_retrieval_count")
    except Exception:
        pass

    # First pass: use RetrieverFactory (published only)
    results = []
    try:
        from app.retrieval.retriever_factory import get_retriever
        retriever = get_retriever()
        search_query = _build_search_query(
            message=msg,
            product_name=product_name,
            sku_name=sku_name,
            product_scope=product_scope,
        )
        results = retriever.retrieve(
            query=search_query,
            source_types=allowed_source_types,
            product_scope=product_scope if product_scope else None,
            sku_scope=sku_scope if sku_scope else None,
            fact_type=query_fact_type,
            top_k=5,
            min_score=0.1,
            sku_name=sku_name,
            product_name=product_name,
        )
    except Exception as exc:
        logger.warning("Retriever 检索失败: %s", exc)
        retrieval_mode = "retriever_fallback_text"

    if not results:
        try:
            from app.services.metrics_service import get_metrics_service
            get_metrics_service().increment("rag_no_evidence_count")
        except Exception:
            pass

    product_context_pack = {"facts": [], "stats": {}}
    try:
        from app.services.product_context_pack_service import build_product_context_pack
        product_context_pack = build_product_context_pack(
            state,
            query=locals().get("search_query", msg),
            allowed_source_types=allowed_source_types,
            query_fact_type=query_fact_type,
            top_k=8,
        )
        results = _merge_ranked_results(results, product_context_pack.get("facts", []), limit=8)
        results = _prefer_matching_fact_type(results, query_fact_type)
    except Exception as exc:
        logger.warning("Product context pack failed: %s", exc)

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "rag_retrieve",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "retrieval_mode": retrieval_mode,
        "original_query": msg,
        "current_query": msg,
        "search_query": locals().get("search_query", msg),
        "retrieval_query": locals().get("search_query", msg),
        "history_included": False,
        "product_name": product_name,
        "sku_name": sku_name,
        "query_fact_type": query_fact_type,
        "product_context_pack_stats": product_context_pack.get("stats", {}),
        "product_card_evidence": product_context_pack.get("evidence_pack", {}),
        "summary": f"RAG检索: {len(results)}条结果, mode={retrieval_mode}, allowed={allowed_source_types}, intent={search_intent}",
    }

    return {
        "retrieved_chunks": results,
        "product_context_pack": product_context_pack,
        "product_context_pack_stats": product_context_pack.get("stats", {}),
        "product_card_evidence_pack": product_context_pack.get("evidence_pack", {}),
        "current_query": msg,
        "retrieval_query": locals().get("search_query", msg),
        "rag_search_query": locals().get("search_query", msg),
        "rag_retrieval_mode": retrieval_mode,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
