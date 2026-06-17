"""
知识分片仓库 - 纯 SQLite 检索，无内存索引
"""

import json
import math
import re
from datetime import datetime
from math import log
from typing import List

from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


_STOP_WORDS = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这"}


def _simple_tokenize(text: str) -> list:
    """简单分词：中文按字，英文按词"""
    tokens = []
    for t in re.findall(r"[a-zA-Z]+|\d+|[\u4e00-\u9fff]", text.lower()):
        if t in _STOP_WORDS:
            continue
        if len(t) > 1 or re.match(r"[\u4e00-\u9fff]", t):
            tokens.append(t)
    return tokens


_PREFIX_WORDS = {"这款", "这个", "那个", "亲", "请问", "我想问一下", "我想问"}


def _normalize_match_text(text: str) -> str:
    """Normalize short Chinese FAQ titles/questions for exact-ish matching."""
    text = re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]+", "", (text or "").lower())
    for w in _PREFIX_WORDS:
        text = text.replace(w, "")
    return text


def _extract_product_phrase(query: str) -> str:
    """Extract a likely product phrase before common attribute question words."""
    q = _normalize_match_text(query)
    for marker in ("材质", "防水", "能洗", "清洗", "尺寸", "承重", "适合", "安装", "吗", "么", "怎么"):
        if marker in q:
            return q.split(marker, 1)[0]
    return ""


# 匹配中文数字前缀，如"一号""十一号""二十号"
_NUMBER_PREFIX_RE = re.compile(r"[一二三四五六七八九十百千]+号")


def _extract_number_prefixes(text: str) -> set:
    """Extract all Chinese number prefixes like '一号', '十一号'."""
    return set(_NUMBER_PREFIX_RE.findall(text))


def _product_core_keyword(text: str) -> str:
    """提取商品核心词，如'防摔枕'、'围兜'、'书架'、'喂养柜'。"""
    # 按常见后缀匹配
    for suffix in ("防摔枕", "围兜", "书架", "收纳架", "置物架", "喂养柜", "书桌", "餐椅", "画板", "围栏", "乐园"):
        if suffix in text:
            return suffix
    return ""


class KnowledgeChunkRepository:
    """知识分片仓库"""

    @staticmethod
    def create_chunks(entry_id: int, content: str, source_type: str, intent: str,
                      product_scope: list, sku_scope: list, platform_scope: list,
                      auto_reply_allowed: bool = True, human_review_required: bool = False,
                      category: str = "", category_l3: str = "", search_keywords: str = "") -> List[KnowledgeChunk]:
        db = _get_db()
        try:
            # 先删除旧 chunks
            db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == entry_id).delete()

            # 按段落切分
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            chunks = []
            idx = 0
            for para in paragraphs:
                # 过长段落按句子切分
                if len(para) > 500:
                    sentences = re.split(r"(?<=[。！？\.\!\?])\s+", para)
                    buf = ""
                    for sent in sentences:
                        if len(buf) + len(sent) < 500:
                            buf += sent
                        else:
                            if buf:
                                chunk = _make_chunk(entry_id, buf, idx, source_type, intent,
                                                   product_scope, sku_scope, platform_scope,
                                                   auto_reply_allowed, human_review_required,
                                                   category, category_l3, search_keywords)
                                chunks.append(chunk)
                                idx += 1
                            buf = sent
                    if buf:
                        chunk = _make_chunk(entry_id, buf, idx, source_type, intent,
                                           product_scope, sku_scope, platform_scope,
                                           auto_reply_allowed, human_review_required,
                                           category, category_l3, search_keywords)
                        chunks.append(chunk)
                        idx += 1
                else:
                    chunk = _make_chunk(entry_id, para, idx, source_type, intent,
                                       product_scope, sku_scope, platform_scope,
                                       auto_reply_allowed, human_review_required,
                                       category, category_l3, search_keywords)
                    chunks.append(chunk)
                    idx += 1

            for c in chunks:
                db.add(c)
            db.commit()
            for c in chunks:
                db.refresh(c)
            return chunks
        finally:
            db.close()

    @staticmethod
    def delete_by_entry(entry_id: int):
        db = _get_db()
        try:
            db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == entry_id).delete()
            db.commit()
        finally:
            db.close()

    @staticmethod
    def search_chunks(
        query: str,
        source_types: list = None,
        intent: str = "",
        fact_type: str = "",
        product_scope: list = None,
        sku_scope: list = None,
        platform_scope: list = None,
        top_k: int = 5,
        min_score: float = 0.1,
        include_draft: bool = False,
        require_ready: bool = True,
    ) -> list:
        """
        基于 SQLite 的文本检索：metadata 过滤 + 关键词匹配 + 简单 BM25
        """
        db = _get_db()
        try:
            from sqlalchemy import or_
            q = db.query(KnowledgeChunk).join(KnowledgeEntry)

            # 正式 RAG 必须同时满足 published + index_status=ready
            # include_draft 仅保留参数兼容，实际不再召回 draft（非 ready 知识不得进入正式检索）
            q = q.filter(KnowledgeEntry.status == "published")
            if require_ready:
                q = q.filter(KnowledgeEntry.index_status == "ready")

            if source_types:
                q = q.filter(KnowledgeChunk.source_type.in_(source_types))
            # intent 过滤由 evidence_filter_node 处理（支持兼容映射），
            # 此处不过滤以避免中文 intent（如"商品咨询"）与英文 intent（如"product_question"）不匹配导致遗漏
            # if intent:
            #     q = q.filter(KnowledgeChunk.intent == intent)

            # 执行查询获取候选（不做过多的前置过滤，主要靠打分）
            candidates = q.all()

            if not candidates:
                return []

            # 构建简单 BM25
            query_tokens = _simple_tokenize(query)
            if not query_tokens:
                return []

            # 计算 IDF
            total_docs = len(candidates)
            token_doc_freq = {}
            for c in candidates:
                doc_text = f"{getattr(c.entry, 'title', '')} {c.chunk_text}"
                doc_tokens = set(_simple_tokenize(doc_text))
                for t in query_tokens:
                    if t in doc_tokens:
                        token_doc_freq[t] = token_doc_freq.get(t, 0) + 1

            idf = {}
            for t in query_tokens:
                df = token_doc_freq.get(t, 0)
                idf[t] = log((total_docs - df + 0.5) / (df + 0.5) + 1)

            # 打分
            k1 = 1.5
            b = 0.75
            avgdl = sum(len(_simple_tokenize(c.chunk_text)) for c in candidates) / total_docs if total_docs else 1
            if avgdl == 0:
                avgdl = 1

            results = []
            query_norm = _normalize_match_text(query)
            query_product_phrase = _extract_product_phrase(query)
            from app.services.fact_type_service import (
                fact_type_matches,
                infer_evidence_fact_type,
                is_strict_fact_type,
            )
            for c in candidates:
                title = getattr(c.entry, "title", "")
                title_norm = _normalize_match_text(title)
                doc_text = f"{title} {c.chunk_text}"
                entry_fact_type = getattr(c.entry, "fact_type", "") or infer_evidence_fact_type({
                    "title": title,
                    "chunk_text": c.chunk_text,
                    "source_type": c.source_type,
                    "category": c.category,
                    "category_l3": c.category_l3,
                    "metadata": c.get_metadata(),
                })
                if fact_type:
                    if fact_type_matches(fact_type, entry_fact_type):
                        score_bonus_for_fact_type = 20.0
                    elif is_strict_fact_type(fact_type):
                        continue
                    else:
                        score_bonus_for_fact_type = -5.0
                else:
                    score_bonus_for_fact_type = 0.0
                doc_tokens = _simple_tokenize(doc_text)
                dl = len(doc_tokens)
                tf_map = {}
                for t in doc_tokens:
                    tf_map[t] = tf_map.get(t, 0) + 1

                score = 0.0
                for t in query_tokens:
                    tf = tf_map.get(t, 0)
                    denom = tf + k1 * (1 - b + b * (dl / avgdl))
                    if denom > 0:
                        score += idf.get(t, 0) * (tf * (k1 + 1)) / denom

                # FAQ 标题对商品款式非常关键，避免“十号”被“十一号/十二号”单字误召回压过。
                if title_norm:
                    if title_norm == query_norm:
                        score += 100
                    elif title_norm in query_norm or query_norm in title_norm:
                        score += 60
                    elif query_product_phrase and query_product_phrase in title_norm:
                        score += 40

                    # 数字前缀精确匹配：如果查询和标题都有数字前缀且核心商品词相同，
                    # 但数字不同，则给予惩罚，防止“十号”被“十一号”误匹配。
                    query_numbers = _extract_number_prefixes(query_norm)
                    title_numbers = _extract_number_prefixes(title_norm)
                    if query_numbers and title_numbers:
                        query_core = _product_core_keyword(query_norm)
                        title_core = _product_core_keyword(title_norm)
                        if query_core and title_core and query_core == title_core:
                            if not query_numbers & title_numbers:
                                score -= 80

                # search_keywords 加分：关键词命中越多，分数越高
                if c.search_keywords:
                    kw_tokens = set(_simple_tokenize(c.search_keywords))
                    kw_overlap = len(set(query_tokens) & kw_tokens)
                    if kw_overlap > 0:
                        score += kw_overlap * 5  # 每命中一个关键词 +5 分

                score += score_bonus_for_fact_type

                # product_scope 过滤（子串匹配，支持"书架"匹配"儿童书架"）
                if product_scope:
                    c_products = set()
                    try:
                        import json
                        c_products = set(json.loads(c.product_scope_json or "[]"))
                    except Exception:
                        pass
                    if c_products and not any(p in cp or cp in p for cp in c_products for p in product_scope):
                        continue

                # sku_scope 过滤（大小写统一）
                if sku_scope:
                    c_skus = set()
                    try:
                        import json
                        c_skus = {str(s).upper() for s in json.loads(c.sku_scope_json or "[]") if s}
                    except Exception:
                        pass
                    norm_sku_scope = {str(s).upper() for s in sku_scope if s}
                    if c_skus and not any(s in c_skus for s in norm_sku_scope):
                        continue

                if score >= min_score:
                    results.append((score, c))

            results.sort(key=lambda x: -x[0])
            top = results[:top_k]

            return [
                {
                    "score": round(score, 4),
                    "chunk_id": c.id,
                    "entry_id": c.entry_id,
                    "title": getattr(c.entry, "title", ""),
                    "chunk_text": c.chunk_text,
                    "chunk_index": c.chunk_index,
                    "source_type": c.source_type,
                    "intent": c.intent,
                    "category": c.category or "",
                    "category_l3": c.category_l3 or "",
                    "fact_type": getattr(c.entry, "fact_type", "") or infer_evidence_fact_type({
                        "title": getattr(c.entry, "title", ""),
                        "chunk_text": c.chunk_text,
                        "source_type": c.source_type,
                        "category": c.category,
                        "category_l3": c.category_l3,
                        "metadata": c.get_metadata(),
                    }),
                    "metadata": c.get_metadata(),
                    "entry_status": getattr(c.entry, "status", "unknown"),
                    "index_status": getattr(c.entry, "index_status", "unknown"),
                    "entry_risk_level": getattr(c.entry, "risk_level", "low"),
                    "source_sheet": getattr(c.entry, "source_sheet", ""),
                    "row_number": getattr(c.entry, "row_number", 0),
                    "sku_scope": _parse_json_list(c.sku_scope_json),
                    "product_scope": _parse_json_list(c.product_scope_json),
                }
                for score, c in top
            ]
        finally:
            db.close()

    @staticmethod
    def search_hybrid(
        query: str,
        source_types: list = None,
        intent: str = "",
        product_scope: list = None,
        sku_scope: list = None,
        platform_scope: list = None,
        fact_type: str = "",
        top_k: int = 5,
        min_score: float = 0.1,
        include_draft: bool = False,
        sku_name: str = "",
        product_name: str = "",
        require_ready: bool = True,
    ) -> list:
        """
        混合检索：文本 BM25 + 向量相似度 + 商品范围匹配 + 来源可信度加权

        Args:
            query: 查询文本
            source_types: 限制的 source_type 列表
            intent: 意图
            product_scope: 商品范围列表
            sku_scope: SKU 范围列表
            platform_scope: 平台范围列表
            top_k: 返回数量
            min_score: 最低分数阈值
            include_draft: 是否包含草稿
            sku_name: 查询涉及的 SKU 编码
            product_name: 查询涉及的商品名称

        Returns:
            检索结果列表，每条包含 text_score, vector_score, scope_score, rerank_score 等字段
        """
        from app.config import RAG_VECTOR_WEIGHT, RAG_TEXT_WEIGHT, RAG_SCOPE_WEIGHT, EMBEDDING_ENABLED
        from app.config import EMBEDDING_SHADOW_MODE

        # 1. 调用现有文本检索
        text_results = KnowledgeChunkRepository.search_chunks(
            query=query,
            source_types=source_types,
            intent=intent,
            fact_type=fact_type,
            product_scope=product_scope,
            sku_scope=sku_scope,
            platform_scope=platform_scope,
            top_k=top_k * 3,  # 多取一些候选，用于重排
            min_score=0.0,    # 先不过滤，重排后统一过滤
            include_draft=include_draft,
            require_ready=require_ready,
        )

        if not text_results:
            return []

        # 建立 chunk_id -> text_result 映射
        text_map = {r["chunk_id"]: r for r in text_results}

        # 2. 向量检索（如果 embedding 启用或 shadow mode）
        vector_map = {}  # chunk_id -> vector_score (0~1)
        use_vector = EMBEDDING_ENABLED or EMBEDDING_SHADOW_MODE
        if use_vector:
            try:
                from app.services.metrics_service import get_metrics_service
                metrics = get_metrics_service()
                if EMBEDDING_ENABLED:
                    metrics.increment("embedding_enabled_query_count")
                else:
                    metrics.increment("embedding_shadow_query_count")

                from app.services.embedding_service import EmbeddingService

                query_embeddings = EmbeddingService.get_embeddings([query])
                if query_embeddings and len(query_embeddings) > 0:
                    query_vec = query_embeddings[0]

                    # 获取所有候选 chunks 的 embedding
                    chunk_ids = list(text_map.keys())
                    db = _get_db()
                    try:
                        chunks_with_emb = (
                            db.query(KnowledgeChunk)
                            .filter(
                                KnowledgeChunk.id.in_(chunk_ids),
                                KnowledgeChunk.embedding_json.isnot(None),
                            )
                            .all()
                        )
                        for chunk in chunks_with_emb:
                            try:
                                chunk_vec = json.loads(chunk.embedding_json)
                                sim = _cosine_similarity(query_vec, chunk_vec)
                                vector_map[chunk.id] = max(0.0, sim)
                            except (json.JSONDecodeError, ValueError) as e:
                                logger.warning(
                                    "shadow: invalid embedding for chunk %s: %s",
                                    chunk.id, e,
                                )
                    finally:
                        db.close()

                    # Track shadow success
                    if vector_map and not EMBEDDING_ENABLED:
                        try:
                            from app.services.metrics_service import get_metrics_service
                            get_metrics_service().increment("embedding_shadow_success_count")
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(
                    "shadow: vector scoring failed for query '%s': %s [%s]",
                    query[:50], type(e).__name__, e,
                )
                # Shadow mode failure must not affect official BM25 results.
                # The vector_map stays empty, so only text scores are used.
                if not EMBEDDING_ENABLED:
                    try:
                        from app.services.metrics_service import get_metrics_service
                        get_metrics_service().increment("embedding_shadow_error_count")
                    except Exception:
                        pass

        # 3. 对结果进行综合重排
        results = []
        for r in text_results:
            cid = r["chunk_id"]
            text_score = _normalize_score(r.get("score", 0))
            vector_score = vector_map.get(cid, 0.0)
            scope_score = _compute_scope_score(
                chunk=r,
                sku_name=sku_name,
                product_name=product_name,
            )

            # source_confidence 加成
            source_confidence_bonus = 0.0
            source_confidence = 0.5
            db = _get_db()
            try:
                chunk_obj = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == cid).first()
                if chunk_obj and chunk_obj.source_confidence is not None:
                    source_confidence = float(chunk_obj.source_confidence)
                    source_confidence_bonus = (source_confidence - 0.5) * 0.1
            except Exception:
                pass
            finally:
                db.close()

            # Shadow mode: vector_score does NOT affect official ranking
            # Only EMBEDDING_ENABLED actually uses vector in scoring
            official_vector_score = vector_score if EMBEDDING_ENABLED else 0.0

            rerank_score = (
                text_score * RAG_TEXT_WEIGHT
                + official_vector_score * RAG_VECTOR_WEIGHT
                + scope_score * RAG_SCOPE_WEIGHT
                + source_confidence_bonus
            )

            # scope mismatch 检测
            mismatch_reason = ""
            if scope_score < 0:
                if scope_score <= -1.0:
                    mismatch_reason = "sku_conflict"
                elif scope_score < 0:
                    mismatch_reason = "scope_mismatch"

            result = {
                **r,
                "text_score": round(text_score, 4),
                "vector_score": round(vector_score, 4),
                "scope_score": round(scope_score, 4),
                "source_confidence": round(source_confidence, 4),
                "rerank_score": round(rerank_score, 4),
                "mismatch_reason": mismatch_reason,
            }
            results.append(result)

        # 按 rerank_score 降序排列
        results.sort(key=lambda x: -x["rerank_score"])

        # 过滤低分并截取 top_k
        filtered = [r for r in results if r["rerank_score"] >= min_score]
        final = filtered[:top_k]

        # Shadow mode: log comparison without affecting official results
        if EMBEDDING_SHADOW_MODE and not EMBEDDING_ENABLED and vector_map:
            _log_shadow_comparison(query, text_results, results, final, top_k)

        return final


def _log_shadow_comparison(query, text_results, hybrid_results, official_results, top_k):
    """Log shadow mode comparison: BM25 ranking vs hybrid ranking."""
    import logging
    logger = logging.getLogger("shadow_mode")

    bm25_top = [r.get("chunk_id") for r in text_results[:top_k]]
    hybrid_top = [r.get("chunk_id") for r in hybrid_results[:top_k]]

    if bm25_top == hybrid_top:
        logger.debug("shadow: identical ranking for '%s'", query[:50])
    else:
        logger.info(
            "shadow: ranking diff for '%s' | bm25=%s | hybrid=%s",
            query[:50],
            bm25_top[:3],
            hybrid_top[:3],
        )


def _cosine_similarity(a: list, b: list) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 for empty vectors, mismatched lengths, zero-norm, or non-numeric elements.
    """
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    try:
        dot = 0.0
        norm_a_sq = 0.0
        norm_b_sq = 0.0
        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            norm_a_sq += fx * fx
            norm_b_sq += fy * fy
        if norm_a_sq == 0.0 or norm_b_sq == 0.0:
            return 0.0
        return dot / (math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq))
    except (ValueError, TypeError):
        return 0.0


def _parse_json_list(text: str) -> list:
    """安全解析 JSON 列表"""
    try:
        result = json.loads(text or "[]")
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _normalize_score(score: float) -> float:
    """将 BM25 原始分数归一化到 0~1 范围"""
    if score <= 0:
        return 0.0
    # 使用 sigmoid-like 归一化
    return 1.0 - 1.0 / (1.0 + score / 10.0)


def _compute_scope_score(chunk: dict, sku_name: str = "", product_name: str = "") -> float:
    """
    计算商品范围匹配分

    规则:
    - SKU 精确匹配: +1.0
    - product_scope 精确匹配: +0.8
    - 标题包含商品名: +0.7
    - 同 category: +0.2
    - 冲突(SKU 不匹配 或 product_scope 不匹配): -1.0
    """
    score = 0.0

    # 从返回结果中读取 sku_scope / product_scope
    chunk_skus = chunk.get("sku_scope", [])
    chunk_products = chunk.get("product_scope", [])

    # 如果没有指定 sku_name/product_name，不做范围打分
    if not sku_name and not product_name:
        return score

    # SKU 精确匹配 / 冲突（忽略大小写）
    if sku_name and chunk_skus:
        norm_sku = str(sku_name).upper()
        norm_chunk_skus = {str(s).upper() for s in chunk_skus}
        if norm_sku in norm_chunk_skus:
            score += 1.0
        else:
            score -= 1.0
            return score

    # product_scope 精确匹配 / 冲突
    if product_name and chunk_products:
        matched = any(product_name == cp or product_name in cp or cp in product_name for cp in chunk_products)
        if matched:
            score += 0.8
        else:
            # Cross-contamination: chunk has explicit scope for a DIFFERENT product
            # Strong penalty to prevent wrong-product recall
            score -= 2.0
            return score

    # 标题包含商品名
    title = chunk.get("title", "")
    if product_name and product_name in title:
        score += 0.7

    # 数字前缀 + 核心商品词匹配（增强对"十一号"vs"十号"的区分）
    if product_name and title:
        q_nums = _extract_number_prefixes(product_name)
        t_nums = _extract_number_prefixes(title)
        q_core = _product_core_keyword(product_name)
        t_core = _product_core_keyword(title)
        if q_core and q_core == t_core and q_nums and t_nums:
            if not (q_nums & t_nums):
                score -= 0.5

    # 同 category（一级类目）
    chunk_category = chunk.get("category", "")
    if product_name and chunk_category and product_name in chunk_category:
        score += 0.2

    # 同 category_l3（三级类目）- 更精准的匹配
    chunk_category_l3 = chunk.get("category_l3", "")
    if product_name and chunk_category_l3 and (product_name in chunk_category_l3 or chunk_category_l3 in product_name):
        score += 0.3

    return score


def _make_chunk(entry_id, text, idx, source_type, intent, product_scope, sku_scope, platform_scope, auto_reply_allowed=True, human_review_required=False, category="", category_l3="", search_keywords=""):
    chunk = KnowledgeChunk(
        entry_id=entry_id,
        chunk_text=text,
        chunk_index=idx,
        source_type=source_type,
        intent=intent,
        category=category,
        category_l3=category_l3,
        search_keywords=search_keywords,
        embedding_status="pending",
        created_at=datetime.utcnow(),
    )
    import json
    chunk.product_scope_json = json.dumps(product_scope if isinstance(product_scope, list) else [], ensure_ascii=False)
    chunk.sku_scope_json = json.dumps(sku_scope if isinstance(sku_scope, list) else [], ensure_ascii=False)
    chunk.platform_scope_json = json.dumps(platform_scope if isinstance(platform_scope, list) else [], ensure_ascii=False)
    chunk.set_metadata({
        "created_at": datetime.utcnow().isoformat(),
        "auto_reply_allowed": auto_reply_allowed,
        "human_review_required": human_review_required,
    })
    return chunk
