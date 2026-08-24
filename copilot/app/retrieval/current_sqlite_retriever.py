"""
Current SQLite retriever.

Primary source: published + ready knowledge_chunks.
Fallback source: published KBQA rows, used while legacy QA data has not yet
been materialized into knowledge_chunks.
"""

from __future__ import annotations

import json
import logging
import re

from app.retrieval.base import BaseKnowledgeRetriever

logger = logging.getLogger(__name__)


def _sku_family(sku: str) -> str:
    """Map concrete SKU like YH06K53B05S13 to family code YH06K53."""
    sku = str(sku or "").strip()
    match = re.match(r"^([A-Z]{2}\d{2}K\d{2})", sku, re.IGNORECASE)
    return match.group(1).upper() if match else sku


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", (text or "").lower()))


def _is_compare_query(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u57fa\u7840\u6b3e",
        "\u5347\u7ea7\u6b3e",
        "\u5347\u7ea7\u7248",
        "\u5dee\u4ec0\u4e48",
        "\u5dee\u522b",
        "\u5dee\u5f02",
        "\u533a\u522b",
        "\u5bf9\u6bd4",
        "\u54ea\u4e2a\u597d",
    ))


def _has_compare_evidence(text: str) -> bool:
    text = text or ""
    explicit_markers = (
        "\u57fa\u7840\u6b3e",
        "\u5347\u7ea7\u6b3e",
        "\u5347\u7ea7\u7248",
        "\u8c6a\u534e\u6b3e",
        "\u5dee\u522b",
        "\u5dee\u5f02",
        "\u533a\u522b",
        "\u5bf9\u6bd4",
        "\u6b3e\u5f0f",
    )
    if any(word in text for word in explicit_markers):
        return True
    return (
        ("\u4fbf\u5b9c" in text and "\u8d35" in text)
        or ("\u504f\u8584" in text and "\u52a0\u539a" in text)
    )


def _json_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _semantic_boost(query: str, qa) -> float:
    title = qa.question or ""
    weak_text = " ".join([qa.category_l3 or ""])
    boost = 0.0
    pairs = [
        (
            ("\u6750\u8d28", "\u6750\u6599", "\u5b89\u5168", "\u5b89\u5168\u5417", "\u6709\u6bd2", "\u73af\u4fdd"),
            ("\u6750\u8d28", "\u6750\u6599", "\u5b89\u5168", "\u73af\u4fdd", "\u9632\u6f6e"),
        ),
        (
            ("\u9002\u5408", "\u591a\u5927", "\u5e74\u9f84", "\u5b9d\u5b9d"),
            ("\u9002\u5408", "\u5e74\u9f84", "\u5b9d\u5b9d", "\u4f7f\u7528"),
        ),
        (
            ("\u5b89\u88c5", "\u600e\u4e48\u88c5", "\u6253\u5b54"),
            ("\u5b89\u88c5", "\u6253\u5b54", "\u5de5\u5177"),
        ),
        (
            ("\u627f\u91cd", "\u7ed3\u5b9e", "\u7a33"),
            ("\u627f\u91cd", "\u7ed3\u5b9e", "\u7a33\u56fa"),
        ),
        (
            ("\u53a8\u623f", "\u5ba2\u5385", "\u9633\u53f0", "\u6536\u7eb3"),
            ("\u53a8\u623f", "\u5ba2\u5385", "\u9633\u53f0", "\u6536\u7eb3"),
        ),
    ]
    for query_words, qa_words in pairs:
        if any(word in query for word in query_words):
            if any(word in title for word in qa_words):
                boost += 0.8
            elif any(word in weak_text for word in qa_words):
                boost += 0.12
    return boost


def _product_sku_codes(product) -> set[str]:
    if not product:
        return set()
    codes: set[str] = set()
    for item in product.get_sku_list():
        if isinstance(item, dict):
            code = item.get("sku_code") or item.get("sku_id") or item.get("value")
        else:
            code = item
        if code:
            codes.add(str(code).strip().upper())
    return codes


def _retrieve_from_kbqa(
    query: str,
    product_scope: list[str] | None,
    sku_scope: list[str] | None,
    source_types: list[str] | None,
    fact_type: str,
    top_k: int,
    min_score: float,
) -> list[dict]:
    if source_types and "faq" not in source_types:
        return []

    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA

    sku_candidates = {str(s).strip().upper() for s in (sku_scope or []) if str(s).strip()}
    sku_candidates.update({_sku_family(s) for s in list(sku_candidates)})
    product_terms = [str(p).strip() for p in (product_scope or []) if str(p).strip()]
    query_tokens = _tokens(query)
    from app.services.fact_type_service import (
        fact_type_matches,
        infer_evidence_fact_type,
        is_strict_fact_type,
    )

    db = SessionLocal()
    try:
        rows = (
            db.query(KBQA, KBProduct)
            .outerjoin(KBProduct, KBQA.product_id == KBProduct.id)
            .filter(KBQA.status == "published")
            .filter(KBQA.auto_reply == True)  # noqa: E712
            .all()
        )

        results: list[dict] = []
        for qa, product in rows:
            qa_skus = {str(s).strip().upper() for s in _json_list(qa.sku_codes_json) if str(s).strip()}
            qa_skus.update({s.upper() for s in _product_sku_codes(product)})
            product_i_id = str(getattr(product, "i_id", "") or "").strip().upper()
            if product_i_id:
                qa_skus.add(product_i_id)
            qa_skus.update({_sku_family(s) for s in list(qa_skus)})

            sku_match = bool(sku_candidates and qa_skus and (sku_candidates & qa_skus))
            sku_conflict = bool(sku_candidates and qa_skus and not sku_match)
            product_name = product.product_name if product else ""
            product_match = bool(
                product_terms
                and product_name
                and any(term in product_name or product_name in term for term in product_terms)
            )

            # An explicit source SKU namespace is authoritative. Similar names
            # cannot convert evidence owned by another product into this request.
            if sku_conflict:
                continue
            if (sku_candidates or product_terms) and not (sku_match or product_match):
                continue

            keyword_text = " ".join(str(x) for x in _json_list(qa.keywords_json))
            doc = " ".join([
                qa.question or "",
                qa.answer or "",
                qa.category_l1 or "",
                qa.category_l2 or "",
                qa.category_l3 or "",
                qa.issue_type or "",
                product_name or "",
                keyword_text,
            ])
            if _is_compare_query(query) and not _has_compare_evidence(doc):
                continue
            evidence_fact_type = infer_evidence_fact_type({
                "title": qa.question,
                "chunk_text": qa.answer,
                "source_type": qa.source_type or "faq",
                "category": qa.category_l2 or qa.category_l1 or "",
                "category_l3": qa.category_l3 or "",
                "issue_type": qa.issue_type or "",
            })
            if fact_type:
                if fact_type_matches(fact_type, evidence_fact_type):
                    fact_type_score = 1.2
                elif is_strict_fact_type(fact_type):
                    continue
                else:
                    fact_type_score = -0.4
            else:
                fact_type_score = 0.0
            overlap = len(query_tokens & _tokens(doc))
            score = overlap * 0.12
            if sku_match:
                score += 1.0
            if product_match:
                score += 0.8
            score += _semantic_boost(query, qa)
            if query and qa.question and (query in qa.question or qa.question in query):
                score += 0.5
            score += fact_type_score
            if score < min_score:
                continue

            scope_score = 1.0 if sku_match else (0.8 if product_match else 0.0)
            results.append({
                "score": round(score, 4),
                "text_score": round(min(score, 1.0), 4),
                "vector_score": 0.0,
                "scope_score": round(scope_score, 4),
                "source_confidence": 0.8,
                "rerank_score": round(score, 4),
                "mismatch_reason": "",
                "chunk_id": f"kbqa:{qa.id}",
                "entry_id": f"kbqa:{qa.id}",
                "title": qa.question,
                "chunk_text": qa.answer,
                "chunk_index": 0,
                "source_type": qa.source_type or "faq",
                "intent": qa.intent or "general",
                "category": qa.category_l2 or qa.category_l1 or "",
                "category_l3": qa.category_l3 or "",
                "fact_type": evidence_fact_type,
                "metadata": {
                    "auto_reply_allowed": bool(qa.auto_reply),
                    "human_review_required": bool(qa.human_review),
                    "fact_type": evidence_fact_type,
                    "qa_id": qa.id,
                    "question": qa.question,
                    "product_id": qa.product_id,
                },
                "entry_status": qa.status,
                "index_status": "ready",
                "entry_risk_level": qa.risk_level or "low",
                "source_sheet": qa.import_batch_id or "",
                "row_number": qa.id,
                "sku_scope": sorted(qa_skus),
                "product_scope": [p for p in [product_name, product_i_id] if p],
            })

        results.sort(key=lambda x: -x["rerank_score"])
        return results[:top_k]
    finally:
        db.close()


def _retrieve_from_reply_templates(
    query: str,
    source_types: list[str] | None,
    fact_type: str,
    top_k: int,
    min_score: float,
) -> list[dict]:
    allowed = set(source_types or [])
    if allowed and not ({"response_templates", "aftersales_policy"} & allowed):
        return []
    if fact_type and fact_type != "aftersales_policy":
        return []

    from app.repositories.reply_template_repository import ReplyTemplateRepository
    from app.services.fact_type_service import infer_evidence_fact_type

    repo = ReplyTemplateRepository()
    repo.load()
    query_tokens = _tokens(query)
    query_text = query or ""
    is_return_query = any(term in query_text for term in ("\u9000", "\u9000\u8d27", "\u9000\u6b3e", "\u4e0d\u5408\u9002", "\u4e0d\u60f3\u8981"))

    scored: list[tuple[float, dict]] = []
    for tmpl in repo._templates:
        intent = str(tmpl.get("intent") or "")
        scenario = str(tmpl.get("scenario") or "")
        template = str(tmpl.get("template") or "")
        doc = " ".join([scenario, template, " ".join(tmpl.get("tags", []) or [])])
        if not template:
            continue
        if fact_type == "aftersales_policy" and intent not in ("refund", "aftersales", "general"):
            continue

        evidence_fact_type = infer_evidence_fact_type({
            "source_type": "response_templates",
            "title": scenario,
            "chunk_text": template,
            "category": intent,
        })
        if fact_type and evidence_fact_type != fact_type:
            continue

        overlap = len(query_tokens & _tokens(doc))
        score = overlap * 0.1
        if query_text and (query_text in doc or scenario in query_text):
            score += 0.5
        if is_return_query:
            if "\u4e03\u5929\u65e0\u7406\u7531" in doc or "7\u5929\u65e0\u7406\u7531" in doc:
                score += 1.0
            if "\u4e0d\u5f71\u54cd\u4e8c\u6b21\u9500\u552e" in doc:
                score += 1.0
            if "\u8fd0\u8d39" in doc:
                score += 0.35
            if "\u7533\u8bf7\u9000\u8d27\u9000\u6b3e" in doc or "\u7533\u8bf7\u9000\u6b3e" in doc:
                score += 0.45
            if any(term in doc for term in ("\u79c1\u5bc6\u4ea7\u54c1", "\u5b9a\u5236\u4ea7\u54c1", "\u8fc7\u654f", "\u6625\u8282", "\u633d\u7559")):
                score -= 0.8
        if score < min_score:
            continue

        source_type = "aftersales_policy" if evidence_fact_type == "aftersales_policy" else "response_templates"
        scored.append((score, {
            "score": round(score, 4),
            "text_score": round(min(score, 1.0), 4),
            "vector_score": 0.0,
            "scope_score": 0.0,
            "source_confidence": 0.75,
            "rerank_score": round(score, 4),
            "mismatch_reason": "",
            "chunk_id": f"template:{tmpl.get('id', '')}",
            "entry_id": f"template:{tmpl.get('id', '')}",
            "title": scenario,
            "chunk_text": template,
            "chunk_index": 0,
            "source_type": source_type,
            "intent": "aftersales",
            "category": intent,
            "category_l3": scenario,
            "fact_type": evidence_fact_type,
            "metadata": {
                "auto_reply_allowed": True,
                "human_review_required": False,
                "fact_type": evidence_fact_type,
                "template_id": tmpl.get("id", ""),
                "scenario": scenario,
            },
            "entry_status": "published",
            "index_status": "ready",
            "entry_risk_level": "low",
            "source_sheet": "reply_templates.json",
            "row_number": 0,
            "sku_scope": [],
            "product_scope": [],
        }))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:top_k]]


class CurrentSQLiteRetriever(BaseKnowledgeRetriever):
    """SQLite BM25 retriever with a KBQA compatibility fallback."""

    def retrieve(
        self,
        query: str,
        product_scope: list[str] | None = None,
        sku_scope: list[str] | None = None,
        source_types: list[str] | None = None,
        fact_type: str = "",
        top_k: int = 5,
        min_score: float = 0.1,
        sku_name: str = "",
        product_name: str = "",
    ) -> list[dict]:
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        if not fact_type:
            try:
                from app.services.fact_type_service import classify_query_fact_type
                fact_type = classify_query_fact_type(query).get("query_fact_type", "")
            except Exception:
                fact_type = ""

        results = KnowledgeChunkRepository.search_hybrid(
            query=query,
            source_types=source_types,
            intent="",
            fact_type=fact_type,
            product_scope=product_scope,
            sku_scope=sku_scope,
            top_k=top_k,
            min_score=min_score,
            include_draft=False,
            sku_name=sku_name,
            product_name=product_name,
            require_ready=True,
        )

        if not results:
            try:
                results = _retrieve_from_kbqa(
                    query=query,
                    product_scope=product_scope,
                    sku_scope=sku_scope,
                    source_types=source_types,
                    fact_type=fact_type,
                    top_k=top_k,
                    min_score=min_score,
                )
            except Exception as exc:
                logger.warning("KBQA fallback retrieval skipped: %s", exc)
                results = []

        if not results:
            results = _retrieve_from_reply_templates(
                query=query,
                source_types=source_types,
                fact_type=fact_type,
                top_k=top_k,
                min_score=min_score,
            )

        filtered = []
        for result in results:
            entry_status = result.get("entry_status", "unknown")
            index_status = result.get("index_status", "unknown")
            if entry_status != "published":
                logger.warning(
                    "Non-published entry in retrieval results: entry_id=%s status=%s",
                    result.get("entry_id"), entry_status,
                )
                continue
            if index_status != "ready":
                logger.warning(
                    "Non-ready entry in retrieval results: entry_id=%s index_status=%s",
                    result.get("entry_id"), index_status,
                )
                continue
            filtered.append(result)

        return filtered
