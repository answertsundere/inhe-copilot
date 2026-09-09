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
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)


class ProductIdentityResolver:
    """统一商品身份解析器。"""

    def __init__(self):
        self._product_map = {}  # canonical_name -> product_info
        self._i_id_map = {}     # i_id -> product_info
        self._alias_map = {}    # alias -> canonical_name
        if os.getenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "").strip() != "product_hub_review_only":
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
        platform_product_id_hash: str = "",
        product_url: str = "",
        platform_title: str = "",
        order_id: str = "",
        product_candidates: list | None = None,
        internal_i_id: str = "",
        sku_id: str = "",
        customer_message: str = "",
    ) -> dict:
        """解析商品身份。"""
        if os.getenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "").strip() == "product_hub_review_only":
            # In the empty-store candidate, never fall back to samples/title guesses.
            if (
                not isinstance(sku_id, str) or not sku_id.strip()
                or any((platform_product_id, platform_product_id_hash, product_url,
                        order_id, internal_i_id))
            ):
                return _unresolved("product_hub_requires_sku_only_input")
            if product_candidates and (
                not isinstance(product_candidates, list)
                or any(
                    not isinstance(candidate, dict) or candidate.get("type") != "sku_code"
                    or candidate.get("value") != sku_id.strip()
                    or candidate.get("sku_code", sku_id.strip()) != sku_id.strip()
                    or any(candidate.get(key) for key in ("i_id", "item_id", "item_id_hash", "product_url", "product_id"))
                    for candidate in product_candidates
                )
            ):
                return _unresolved("product_hub_conflicting_identity_candidates")
            if (
                os.getenv("COPILOT_RUNTIME_ENV", "production").strip().lower() not in {"development", "test"}
                or os.getenv("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", "").strip().lower() not in {"1", "true", "yes", "on"}
            ):
                return _unresolved("product_hub_candidate_configuration_required")
            try:
                from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
                binding = ProductHubReviewedFactsClient().resolve_active_sku_identity(sku_id.strip())
            except Exception:
                return _unresolved("product_hub_identity_unavailable")
            if (
                not isinstance(binding, dict) or binding.get("state") != "ready"
                or binding.get("resolved_sku_code") != sku_id.strip()
                or binding.get("identity_source") != "product_hub_exact_sku"
                or not binding.get("product_code") or not binding.get("hub_product_id")
            ):
                return _unresolved("product_hub_identity_not_resolved")
            if platform_title and platform_title.strip() not in {binding.get("product_name"), binding["product_code"]}:
                return _unresolved("product_hub_title_conflicts_with_exact_sku")
            sku = binding["resolved_sku_code"]
            display_name = binding.get("product_name") or binding["product_code"]
            return {
                **_unresolved(""), "status": "resolved", "source": "product_hub_exact_sku",
                "confidence": 1.0, "identity_confidence": 1.0,
                "sku_id": sku, "sku_code": sku, "sku_family": _sku_family(sku),
                "canonical_product_name": display_name, "display_product_name": display_name,
                "knowledge_sku_scope": [sku], "identity_sources": ["product_hub_exact_sku"],
                "match_reason": "active_exact_hub_sku", "product_code": binding["product_code"],
                "hub_product_id": binding["hub_product_id"],
            }
        platform_product_id = _first_text(platform_product_id, _extract_product_id_from_url(product_url))
        kb_result = self._resolve_from_kb(
            platform_product_id=platform_product_id,
            platform_product_id_hash=platform_product_id_hash,
            product_url=product_url,
            platform_title=platform_title,
            product_candidates=product_candidates,
            internal_i_id=internal_i_id,
            sku_id=sku_id,
        )
        if kb_result.get("status") in {"resolved", "ambiguous"}:
            return kb_result

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
            "resolved_product_id": "",
            "i_id": "",
            "sku_code": sku_id,
            "sku_family": _sku_family(sku_id),
            "display_product_name": "",
            "matched_product_title": "",
            "identity_confidence": 0.0,
            "identity_sources": [],
            "match_reason": "",
            "ambiguous_candidates": [],
            "unresolved_reason": "",
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
        result["unresolved_reason"] = "no_matching_product_found"
        return result

    def _resolve_from_kb(
        self,
        *,
        platform_product_id: str = "",
        platform_product_id_hash: str = "",
        product_url: str = "",
        platform_title: str = "",
        product_candidates: list | None = None,
        internal_i_id: str = "",
        sku_id: str = "",
    ) -> dict:
        try:
            from app.db import SessionLocal
            from app.models.kb_tables import KBProduct, ProductIdentityMapping
            from sqlalchemy import or_
        except Exception as exc:
            return _unresolved("resolver_import_failed", error=type(exc).__name__)

        db = SessionLocal()
        try:
            sku = _first_text(sku_id)
            i_id = _first_text(internal_i_id)
            platform_id = _first_text(platform_product_id, _extract_product_id_from_url(product_url))
            platform_hash = _first_text(platform_product_id_hash)
            title = _first_text(platform_title, *[_candidate_title(c) for c in product_candidates or []])

            if sku:
                product = _find_product_by_sku(db, KBProduct, sku)
                if product:
                    return _resolved_from_product(
                        product,
                        source="sku_exact",
                        confidence=1.0,
                        sku_code=sku,
                        platform_product_id=platform_id,
                        match_reason="exact_sku_match",
                    )

            if i_id:
                product = db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
                if product:
                    return _resolved_from_product(
                        product,
                        source="i_id_exact",
                        confidence=1.0,
                        sku_code=sku,
                        platform_product_id=platform_id,
                        match_reason="exact_i_id_match",
                    )

            mapping_match = _resolve_from_identity_mapping(
                db,
                KBProduct,
                ProductIdentityMapping,
                platform_item_id=platform_id,
                platform_item_id_hash=platform_hash,
                product_url=product_url,
                sku_code=sku,
            )
            if mapping_match.get("status") in {"resolved", "ambiguous"}:
                return mapping_match

            if platform_id:
                like = f"%{platform_id}%"
                rows = (
                    db.query(KBProduct)
                    .filter(KBProduct.status == "published")
                    .filter(or_(
                        KBProduct.sku_list_json.like(like),
                        KBProduct.specs_json.like(like),
                        KBProduct.logistics_json.like(like),
                        KBProduct.warranty_json.like(like),
                    ))
                    .limit(20)
                    .all()
                )
                matched = [p for p in rows if _product_has_platform_item_id(p, platform_id)]
                if len(matched) == 1:
                    return _resolved_from_product(
                        matched[0],
                        source="platform_item_id_exact",
                        confidence=0.98,
                        sku_code=sku,
                        platform_product_id=platform_id,
                        match_reason="exact_platform_item_id_match",
                    )
                if len(matched) > 1:
                    return _ambiguous(
                        "multiple_products_share_platform_item_id",
                        matched,
                        confidence=0.75,
                        platform_product_id=platform_id,
                    )

            if platform_hash:
                like = f"%{platform_hash}%"
                rows = (
                    db.query(KBProduct)
                    .filter(KBProduct.status == "published")
                    .filter(or_(
                        KBProduct.sku_list_json.like(like),
                        KBProduct.specs_json.like(like),
                        KBProduct.logistics_json.like(like),
                        KBProduct.warranty_json.like(like),
                    ))
                    .limit(20)
                    .all()
                )
                matched = [p for p in rows if _product_has_platform_item_hash(p, platform_hash)]
                if len(matched) == 1:
                    return _resolved_from_product(
                        matched[0],
                        source="platform_item_id_hash_exact",
                        confidence=0.97,
                        sku_code=sku,
                        platform_product_id=platform_id,
                        match_reason="exact_platform_item_id_hash_match",
                    )
                if len(matched) > 1:
                    return _ambiguous(
                        "multiple_products_share_platform_item_id_hash",
                        matched,
                        confidence=0.74,
                        platform_product_id=platform_id,
                    )

            if title:
                title_match = _resolve_title_from_kb(db, KBProduct, title)
                if title_match.get("status") in {"resolved", "ambiguous"}:
                    title_match["platform_product_id"] = platform_id
                    return title_match

            return _unresolved(
                "no_kb_product_identity_match",
                platform_product_id=platform_id,
                platform_title=title,
                sku_code=sku,
                i_id=i_id,
            )
        finally:
            db.close()

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
    try:
        query = parse_qs(urlsplit(str(url)).query)
        if query.get("id") and str(query["id"][0]).isdigit():
            return str(query["id"][0])
    except Exception:
        pass
    m = re.search(r"(?:[?&]|%3F|%26)id(?:=|%3D)(\d+)", str(url), re.I)
    if m:
        return m.group(1)
    return ""


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _resolve_from_identity_mapping(
    db,
    KBProduct,
    ProductIdentityMapping,
    *,
    platform_item_id: str = "",
    platform_item_id_hash: str = "",
    product_url: str = "",
    sku_code: str = "",
) -> dict:
    filters = []
    if platform_item_id:
        filters.append(ProductIdentityMapping.platform_item_id == platform_item_id)
    if platform_item_id_hash:
        filters.append(ProductIdentityMapping.platform_item_id_hash == platform_item_id_hash)
    host = _url_host(product_url)
    if host and (platform_item_id or platform_item_id_hash):
        filters.append(ProductIdentityMapping.product_url_host == host)
    if not filters:
        return _unresolved("no_mapping_identity_signal")
    from sqlalchemy import or_

    rows = (
        db.query(ProductIdentityMapping)
        .filter(ProductIdentityMapping.status.in_(["active", "verified", "confirmed"]))
        .filter(or_(*filters))
        .limit(20)
        .all()
    )
    if not rows:
        return _unresolved("no_product_identity_mapping_found")
    product_ids = {row.kb_product_id for row in rows if row.kb_product_id}
    if len(product_ids) > 1:
        products = db.query(KBProduct).filter(KBProduct.id.in_(list(product_ids))).all()
        return _ambiguous("multiple_active_product_identity_mappings", products, confidence=0.8)
    row = rows[0]
    product = db.query(KBProduct).filter(KBProduct.id == row.kb_product_id).first()
    if not product:
        return _unresolved("mapped_kb_product_missing", i_id=row.i_id, sku_code=row.sku_code or sku_code)
    return _resolved_from_product(
        product,
        source="product_identity_mapping",
        confidence=float(row.confidence or 0.96),
        sku_code=row.sku_code or sku_code,
        platform_product_id=platform_item_id,
        match_reason="product_identity_mapping_match",
    )


def _url_host(value: str) -> str:
    try:
        return urlsplit(str(value or "")).netloc.lower()
    except Exception:
        return ""


def _find_product_by_sku(db, KBProduct, sku: str):
    sku = str(sku or "").strip()
    if not sku:
        return None
    product = db.query(KBProduct).filter(KBProduct.i_id == sku).first()
    if product:
        return product
    rows = (
        db.query(KBProduct)
        .filter(KBProduct.status == "published")
        .filter(KBProduct.sku_list_json.like(f"%{sku}%"))
        .limit(20)
        .all()
    )
    for product in rows:
        if _product_has_sku(product, sku):
            return product
    family = _sku_family(sku)
    if family:
        return db.query(KBProduct).filter(KBProduct.i_id == family).first()
    return None


def _product_has_sku(product: Any, sku: str) -> bool:
    target = str(sku or "").strip().upper()
    if not target:
        return False
    if str(getattr(product, "i_id", "") or "").strip().upper() == target:
        return True
    for item in product.get_sku_list() or []:
        values = []
        if isinstance(item, dict):
            values = [item.get("sku_code"), item.get("sku_id"), item.get("sku"), item.get("barcode_69")]
        elif item:
            values = [item]
        if any(str(value or "").strip().upper() == target for value in values):
            return True
    return False


_PLATFORM_ITEM_KEYS = {
    "platform_item_id",
    "platform_product_id",
    "taobao_item_id",
    "tmall_item_id",
    "item_id",
    "product_item_id",
}


_PLATFORM_ITEM_HASH_KEYS = {
    "platform_item_id_hash",
    "platform_product_id_hash",
    "taobao_item_id_hash",
    "tmall_item_id_hash",
    "item_id_hash",
    "product_item_id_hash",
}


def _product_has_platform_item_id(product: Any, platform_item_id: str) -> bool:
    target = str(platform_item_id or "").strip()
    if not target:
        return False
    values = []
    for obj in [
        *(product.get_sku_list() or []),
        product.get_specs() or {},
        product.get_logistics() or {},
        product.get_warranty() or {},
    ]:
        values.extend(_walk_platform_values(obj))
    for value in values:
        text = str(value or "").strip()
        if text == target or _extract_product_id_from_url(text) == target:
            return True
    return False


def _product_has_platform_item_hash(product: Any, platform_item_hash: str) -> bool:
    target = str(platform_item_hash or "").strip()
    if not target:
        return False
    for obj in [
        *(product.get_sku_list() or []),
        product.get_specs() or {},
        product.get_logistics() or {},
        product.get_warranty() or {},
    ]:
        for value in _walk_platform_hash_values(obj):
            if str(value or "").strip() == target:
                return True
    return False


def _walk_platform_values(value: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text in _PLATFORM_ITEM_KEYS or key_text in {"product_url", "item_url", "url", "link"}:
                found.append(item)
            found.extend(_walk_platform_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_platform_values(item))
    return found


def _walk_platform_hash_values(value: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text in _PLATFORM_ITEM_HASH_KEYS:
                found.append(item)
            found.extend(_walk_platform_hash_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_platform_hash_values(item))
    return found


def _sku_family(value: str) -> str:
    match = re.match(r"^(YH\d+K\d+)", str(value or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _resolve_title_from_kb(db, KBProduct, title: str) -> dict:
    title = str(title or "").strip()
    if not title:
        return _unresolved("empty_title")
    exact = db.query(KBProduct).filter(KBProduct.product_name == title).first()
    if exact:
        return _resolved_from_product(exact, source="title_exact", confidence=1.0, match_reason="exact_title_match")

    tokens = _title_tokens(title)
    if not tokens:
        return _unresolved("title_has_no_matchable_tokens", platform_title=title)
    from sqlalchemy import or_
    conditions = [KBProduct.product_name.like(f"%{token}%") for token in tokens[:6]]
    candidates = db.query(KBProduct).filter(KBProduct.status == "published").filter(or_(*conditions)).limit(50).all()
    scored = []
    for product in candidates:
        score = _title_similarity(title, product.product_name)
        if score >= 0.72:
            scored.append((score, product))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return _unresolved("low_confidence_title_match", platform_title=title)
    best_score = scored[0][0]
    close = [(score, product) for score, product in scored if best_score - score <= 0.08]
    if len(close) > 1:
        return _ambiguous("multiple_high_confidence_title_matches", [product for _score, product in close], confidence=best_score)
    return _resolved_from_product(
        scored[0][1],
        source="title_high_confidence",
        confidence=round(best_score, 4),
        match_reason="high_confidence_title_match",
    )


def _title_tokens(text: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", str(text or "").lower())
    tokens = []
    for token in raw:
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)
    return tokens


def _title_similarity(left: str, right: str) -> float:
    left = str(left or "").strip().lower()
    right = str(right or "").strip().lower()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if right in left:
        return min(0.96, max(0.78, len(right) / max(len(left), 1) + 0.25))
    if left in right:
        return min(0.92, max(0.74, len(left) / max(len(right), 1) + 0.2))
    left_tokens = set(_title_tokens(left))
    right_tokens = set(_title_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _resolved_from_product(
    product: Any,
    *,
    source: str,
    confidence: float,
    sku_code: str = "",
    platform_product_id: str = "",
    match_reason: str,
) -> dict:
    i_id = str(getattr(product, "i_id", "") or "")
    product_name = str(getattr(product, "product_name", "") or "")
    return {
        "status": "resolved",
        "source": source,
        "confidence": float(confidence),
        "platform_product_id": platform_product_id,
        "platform_title": "",
        "internal_i_id": i_id,
        "sku_id": sku_code,
        "canonical_product_name": product_name,
        "knowledge_product_scope": [item for item in [i_id, product_name] if item],
        "knowledge_sku_scope": [sku_code] if sku_code else [],
        "candidates": [],
        "reason": match_reason,
        "resolved_product_id": getattr(product, "id", None),
        "i_id": i_id,
        "sku_code": sku_code,
        "sku_family": _sku_family(sku_code),
        "display_product_name": product_name,
        "matched_product_title": product_name,
        "identity_confidence": float(confidence),
        "identity_sources": [source],
        "match_reason": match_reason,
        "ambiguous_candidates": [],
        "unresolved_reason": "",
    }


def _ambiguous(reason: str, products: list[Any], *, confidence: float, platform_product_id: str = "") -> dict:
    candidates = [_compact_product_candidate(product, confidence=confidence) for product in products[:5]]
    return {
        "status": "ambiguous",
        "source": "product_identity_resolver",
        "confidence": float(confidence),
        "platform_product_id": platform_product_id,
        "platform_title": "",
        "internal_i_id": "",
        "sku_id": "",
        "canonical_product_name": "",
        "knowledge_product_scope": [],
        "knowledge_sku_scope": [],
        "candidates": candidates,
        "reason": reason,
        "resolved_product_id": "",
        "i_id": "",
        "sku_code": "",
        "sku_family": "",
        "display_product_name": "",
        "matched_product_title": "",
        "identity_confidence": float(confidence),
        "identity_sources": [],
        "match_reason": "",
        "ambiguous_candidates": candidates,
        "unresolved_reason": reason,
    }


def _unresolved(reason: str, **extra: Any) -> dict:
    sku_code = str(extra.get("sku_code", "") or "")
    return {
        "status": "not_found",
        "source": "product_identity_resolver",
        "confidence": 0.0,
        "platform_product_id": extra.get("platform_product_id", ""),
        "platform_title": extra.get("platform_title", ""),
        "internal_i_id": extra.get("i_id", ""),
        "sku_id": sku_code,
        "canonical_product_name": "",
        "knowledge_product_scope": [],
        "knowledge_sku_scope": [],
        "candidates": [],
        "reason": reason,
        "resolved_product_id": "",
        "i_id": extra.get("i_id", ""),
        "sku_code": sku_code,
        "sku_family": _sku_family(sku_code),
        "display_product_name": "",
        "matched_product_title": "",
        "identity_confidence": 0.0,
        "identity_sources": [],
        "match_reason": "",
        "ambiguous_candidates": [],
        "unresolved_reason": reason,
    }


def _compact_product_candidate(product: Any, *, confidence: float) -> dict:
    return {
        "resolved_product_id": getattr(product, "id", None),
        "i_id": str(getattr(product, "i_id", "") or ""),
        "display_product_name": str(getattr(product, "product_name", "") or ""),
        "identity_confidence": float(confidence),
    }


def _candidate_title(candidate: Any) -> str:
    if isinstance(candidate, str):
        return candidate
    if not isinstance(candidate, dict):
        return ""
    candidate_type = str(candidate.get("type") or "").lower()
    return _first_text(
        candidate.get("product_name"),
        candidate.get("title"),
        candidate.get("name"),
        candidate.get("matched_product_name"),
        candidate.get("value") if "title" in candidate_type or "name" in candidate_type else "",
    )


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
