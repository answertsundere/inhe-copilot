"""
Product Identity Resolver — 统一商品身份解析器。

输入:
  - 平台商品 ID
  - 商品链接
  - 平台标题
  - 订单号
  - Sidecar 商品候选
  - 内部 i_id
  - SKU

输出:
  {
    "status": "resolved|ambiguous|not_found|error",
    "source": "",
    "confidence": 0.0,
    "platform_product_id": "",
    "platform_title": "",
    "internal_i_id": "",
    "sku_id": "",
    "canonical_product_name": "",
    "knowledge_product_scope": [],
    "knowledge_sku_scope": [],
    "candidates": [],
    "reason": ""
  }
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


class ProductIdentityResolver:
    """统一商品身份解析器。"""

    def __init__(self):
        self._product_map = {}  # canonical_name -> product_info
        self._i_id_map = {}     # i_id -> product_info
        self._alias_map = {}    # alias -> canonical_name
        self._load_product_data()

    def _load_product_data(self):
        """加载商品数据构建映射。"""
        # Load from sample_products.json
        data_dir = os.environ.get(
            "COPILOT_SAMPLE_DATA_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "data"),
        )
        products_path = os.path.join(data_dir, "sample_products.json")
        if os.path.exists(products_path):
            with open(products_path, "r", encoding="utf-8") as f:
                products = json.load(f)
            for p in products:
                i_id = p.get("i_id", "")
                name = p.get("name", "")
                info = {
                    "i_id": i_id,
                    "name": name,
                    "brand": p.get("brand", ""),
                    "category": p.get("c_name", ""),
                    "skus": p.get("skus", []),
                }
                if i_id:
                    self._i_id_map[i_id] = info
                if name:
                    self._product_map[name] = info

                # Build aliases from SKU names
                for sku in p.get("skus", []):
                    sku_name = sku.get("name", "")
                    if sku_name:
                        self._alias_map[sku_name] = name
                    sku_id = sku.get("sku_id", "")
                    if sku_id:
                        self._alias_map[sku_id] = name

        # Load knowledge base product scope for richer mapping
        self._load_knowledge_scope()

    def _load_knowledge_scope(self):
        """从知识库加载 product_scope 映射。"""
        try:
            from app.db import SessionLocal, init_db
            from app.models.knowledge_base import KnowledgeEntry
            init_db()
            db = SessionLocal()
            try:
                entries = db.query(KnowledgeEntry).filter(
                    KnowledgeEntry.status == "published",
                    KnowledgeEntry.product_scope_json != "[]",
                ).all()
                for e in entries:
                    scope = e.get_product_scope()
                    title = e.title
                    for s in scope:
                        if s and s not in self._alias_map:
                            self._alias_map[s] = s
                        # Map from title keywords to scope
                        if title and s:
                            # Extract core product keywords from title
                            for keyword in _extract_product_keywords(title):
                                if keyword not in self._alias_map:
                                    self._alias_map[keyword] = s
            finally:
                db.close()
        except Exception as e:
            logger.debug("Knowledge scope loading skipped: %s", e)

    def resolve(
        self,
        platform_product_id: str = "",
        product_url: str = "",
        platform_title: str = "",
        order_id: str = "",
        product_candidates: list | None = None,
        internal_i_id: str = "",
        sku_id: str = "",
        customer_message: str = "",
    ) -> dict:
        """解析商品身份。"""
        result = {
            "status": "not_found",
            "source": "",
            "confidence": 0.0,
            "platform_product_id": platform_product_id,
            "platform_title": platform_title,
            "internal_i_id": internal_i_id,
            "sku_id": sku_id,
            "canonical_product_name": "",
            "knowledge_product_scope": [],
            "knowledge_sku_scope": [],
            "candidates": [],
            "reason": "",
        }

        # Strategy 1: Direct i_id match
        if internal_i_id and internal_i_id in self._i_id_map:
            info = self._i_id_map[internal_i_id]
            result.update({
                "status": "resolved",
                "source": "i_id_direct",
                "confidence": 1.0,
                "internal_i_id": internal_i_id,
                "canonical_product_name": info["name"],
                "knowledge_product_scope": [info["name"]],
            })
            if sku_id:
                result["sku_id"] = sku_id
                result["knowledge_sku_scope"] = [sku_id]
            return result

        # Strategy 2: SKU ID match
        if sku_id and sku_id in self._alias_map:
            canonical = self._alias_map[sku_id]
            if canonical in self._product_map:
                info = self._product_map[canonical]
                result.update({
                    "status": "resolved",
                    "source": "sku_id_match",
                    "confidence": 0.95,
                    "internal_i_id": info["i_id"],
                    "sku_id": sku_id,
                    "canonical_product_name": info["name"],
                    "knowledge_product_scope": [info["name"]],
                    "knowledge_sku_scope": [sku_id],
                })
                return result

        # Strategy 3: Platform title matching
        if platform_title:
            match = self._match_title(platform_title)
            if match:
                result.update(match)
                return result

        # Strategy 4: URL extract
        if product_url:
            pid = _extract_product_id_from_url(product_url)
            if pid:
                # Platform product ID cannot be used directly as i_id
                # Check if it's in our mapping
                if pid in self._alias_map:
                    canonical = self._alias_map[pid]
                    if canonical in self._product_map:
                        info = self._product_map[canonical]
                        result.update({
                            "status": "resolved",
                            "source": "url_product_id",
                            "confidence": 0.9,
                            "platform_product_id": pid,
                            "internal_i_id": info["i_id"],
                            "canonical_product_name": info["name"],
                            "knowledge_product_scope": [info["name"]],
                        })
                        return result

        # Strategy 5: Customer message keyword matching
        if customer_message:
            match = self._match_from_message(customer_message)
            if match:
                result.update(match)
                return result

        # Strategy 6: Product candidates from Sidecar
        if product_candidates:
            for cand in product_candidates:
                cand_value = ""
                if isinstance(cand, dict):
                    cand_value = str(cand.get("value") or cand.get("name") or "")
                elif isinstance(cand, str):
                    cand_value = cand
                if cand_value:
                    match = self._match_title(cand_value)
                    if match and match.get("confidence", 0) >= 0.8:
                        result.update(match)
                        result["source"] = "sidecar_candidate"
                        return result

        # Low confidence match
        if result["candidates"]:
            best = result["candidates"][0]
            if best.get("confidence", 0) >= 0.5:
                result["status"] = "ambiguous"
                result["reason"] = "low_confidence_match_needs_human_review"
                return result

        result["status"] = "not_found"
        result["reason"] = "no_matching_product_found"
        return result

    def _match_title(self, title: str) -> Optional[dict]:
        """Match a product title against known products."""
        # Direct match
        if title in self._product_map:
            info = self._product_map[title]
            return {
                "status": "resolved",
                "source": "title_exact",
                "confidence": 1.0,
                "internal_i_id": info["i_id"],
                "canonical_product_name": info["name"],
                "knowledge_product_scope": [info["name"]],
            }

        # Alias match
        if title in self._alias_map:
            canonical = self._alias_map[title]
            if canonical in self._product_map:
                info = self._product_map[canonical]
                return {
                    "status": "resolved",
                    "source": "alias_match",
                    "confidence": 0.9,
                    "internal_i_id": info["i_id"],
                    "canonical_product_name": info["name"],
                    "knowledge_product_scope": [info["name"]],
                }

        # Keyword matching
        keywords = _extract_product_keywords(title)
        candidates = []
        for kw in keywords:
            for canonical, info in self._product_map.items():
                if kw in canonical or canonical in kw:
                    candidates.append({
                        "confidence": 0.7 if kw in canonical else 0.5,
                        "internal_i_id": info["i_id"],
                        "canonical_product_name": info["name"],
                        "knowledge_product_scope": [info["name"]],
                        "match_keyword": kw,
                    })

        if len(candidates) == 1:
            c = candidates[0]
            return {
                "status": "resolved",
                "source": "keyword_match",
                "confidence": c["confidence"],
                "internal_i_id": c["internal_i_id"],
                "canonical_product_name": c["canonical_product_name"],
                "knowledge_product_scope": c["knowledge_product_scope"],
            }
        if len(candidates) > 1:
            # Deduplicate
            seen = set()
            unique = []
            for c in sorted(candidates, key=lambda x: -x["confidence"]):
                if c["internal_i_id"] not in seen:
                    seen.add(c["internal_i_id"])
                    unique.append(c)
            if len(unique) == 1:
                c = unique[0]
                return {
                    "status": "resolved",
                    "source": "keyword_match_deduped",
                    "confidence": c["confidence"],
                    "internal_i_id": c["internal_i_id"],
                    "canonical_product_name": c["canonical_product_name"],
                    "knowledge_product_scope": c["knowledge_product_scope"],
                }
            return {
                "status": "ambiguous",
                "source": "keyword_match_multi",
                "confidence": unique[0]["confidence"],
                "candidates": unique,
                "reason": f"multiple_products_match: {len(unique)}",
            }

        return None

    def _match_from_message(self, message: str) -> Optional[dict]:
        """从客户消息中匹配商品。"""
        # Try model number pattern like "一号XXX" "六号XXX"
        model_match = re.search(
            r"([一二三四五六七八九十百千万两0-9]+号[一-鿿]{0,12}?"
            r"(?:围兜|罩衣|防摔枕|枕头|书架|绘本架|收纳架|柜|凳|桌|椅|围栏|画板))",
            message,
        )
        if model_match:
            product_phrase = model_match.group(1)
            match = self._match_title(product_phrase)
            if match:
                match["source"] = "message_model_pattern"
                return match

        # Try general keyword match
        keywords = _extract_product_keywords(message)
        for kw in keywords:
            match = self._match_title(kw)
            if match:
                match["source"] = "message_keyword"
                return match

        return None


# ---------- Helper functions ----------

_PRODUCT_SUFFIXES = [
    "防摔枕", "围兜", "书架", "收纳架", "置物架",
    "喂养柜", "书桌", "餐椅", "画板", "围栏", "乐园",
    "爬行垫", "摇篮", "枕头", "罩衣", "脸盆",
    "收纳箱", "玩具", "画架", "折叠桌",
]


def _extract_product_keywords(text: str) -> list[str]:
    """从文本中提取商品关键词。"""
    keywords = []
    for suffix in _PRODUCT_SUFFIXES:
        if suffix in text:
            # Try to extract the full product name with prefix
            idx = text.find(suffix)
            # Look backwards for qualifier
            start = max(0, idx - 10)
            prefix = text[start:idx]
            # Look for "N号" prefix
            m = re.search(r"([一二三四五六七八九十百千万两0-9]+号)", prefix)
            if m:
                keywords.append(m.group(1) + suffix)
            else:
                keywords.append(suffix)
    if not keywords:
        for suffix in _PRODUCT_SUFFIXES:
            if suffix in text:
                keywords.append(suffix)
    return keywords


def _extract_product_id_from_url(url: str) -> str:
    """从 URL 中提取平台商品 ID。"""
    if not url:
        return ""
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"item\.htm.*?id=(\d+)", url)
    if m:
        return m.group(1)
    return ""


def resolve_product_from_context(
    customer_message: str = "",
    product_name: str = "",
    product_candidates: list | None = None,
    order_id: str = "",
    product_url: str = "",
) -> dict:
    """便捷函数：从上下文解析商品身份。"""
    resolver = ProductIdentityResolver()
    return resolver.resolve(
        platform_title=product_name,
        product_url=product_url,
        order_id=order_id,
        product_candidates=product_candidates,
        customer_message=customer_message,
    )
