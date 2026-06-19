"""Product-scoped context pack for RAG retrieval.

The normal retriever is query-first. This helper is product-first: once the
agent has resolved a product/SKU/order identity, collect published + ready facts
for that exact product and rank them by the customer's requested fact type.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.media_asset_service import (
    _applicable_style_score,
    _answer_scenario_score,
    _infer_answer_scenario,
    _style_scope_matches,
    get_answer_scenarios,
    get_applicable_style,
    get_auto_send_level,
    get_media_purpose,
)


def build_product_context_pack(
    state: dict,
    *,
    query: str = "",
    allowed_source_types: list[str] | None = None,
    query_fact_type: str = "",
    required_fact_types: list[str] | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    identity = _state_identity(state)
    if not (identity["sku"] or identity["i_id"] or identity["product_name"]):
        return _empty_pack(identity, "no_product_identity")

    try:
        from app.db import SessionLocal
        from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA
        from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry
        from app.services.fact_type_service import (
            infer_evidence_fact_type,
        )
        from app.services.evidence_alignment_service import align_evidence_to_query
        from app.services.generic_service_rule_service import search_generic_service_rules
        from app.services.product_activity_rule_service import get_active_activity_rules_for_product
    except Exception as exc:
        return _empty_pack(identity, f"import_failed:{type(exc).__name__}")

    allowed = set(allowed_source_types or [])
    required_types = _required_fact_types(state, query_fact_type, required_fact_types)
    semantic_query = state.get("semantic_query") if isinstance(state.get("semantic_query"), dict) else {}
    db = SessionLocal()
    try:
        candidates: list[dict[str, Any]] = []
        kb_product = _find_kb_product(db, KBProduct, identity)
        structured_profile = _build_structured_profile(kb_product)
        activity_identity = {**identity, "product_id": structured_profile.get("product_id")}
        activity_rules = get_active_activity_rules_for_product(db, KBProductActivityRule, activity_identity, limit=5)
        generic_rules = search_generic_service_rules(
            db=db,
            RuleModel=KBGenericServiceRule,
            query=query,
            intent=str(state.get("intent") or ""),
            fact_type=query_fact_type,
            limit=3,
        )
        media_assets = _collect_media_assets(db, KBMediaAsset, identity, structured_profile, limit=300)
        signals = {
            "customer_message": query or "",
            "sku_code": identity.get("sku", ""),
            "i_id": identity.get("i_id", ""),
            "product_name": structured_profile.get("product_name") or identity.get("product_name", ""),
        }
        recommended_assets = _rank_media_assets_for_required_types(
            media_assets, query=query, required_fact_types=required_types, limit=3, signals=signals
        )
        media_assets = [_media_asset_to_pack_item(a) for a in media_assets]
        recommended_assets = [_media_asset_to_pack_item(a) for a in recommended_assets]
        product_card_evidence = _product_card_evidence_items(
            structured_profile,
            query=query,
            query_fact_type=query_fact_type,
            required_fact_types=required_types,
        )
        media_evidence = _media_evidence_items(
            structured_profile,
            media_assets=media_assets,
            recommended_assets=recommended_assets,
            query=query,
            query_fact_type=query_fact_type,
            required_fact_types=required_types,
        )
        if not allowed or "product_facts" in allowed:
            candidates.extend(_profile_facts_for_query(structured_profile, query=query, query_fact_type=query_fact_type))
            candidates.extend(_activity_facts_for_query(activity_rules, query=query, query_fact_type=query_fact_type))
            candidates.extend(_media_facts_for_query(
                structured_profile,
                recommended_assets,
                query=query,
                query_fact_type=query_fact_type,
            ))
        chunk_query = (
            db.query(KnowledgeChunk)
            .join(KnowledgeEntry)
            .filter(KnowledgeEntry.status == "published")
            .filter(KnowledgeEntry.index_status == "ready")
        )
        if allowed:
            chunk_query = chunk_query.filter(KnowledgeChunk.source_type.in_(allowed))

        for chunk in chunk_query.all():
            entry = chunk.entry
            if not _scope_matches(
                identity,
                product_scope=_json_list(chunk.product_scope_json) or entry.get_product_scope(),
                sku_scope=_json_list(chunk.sku_scope_json) or entry.get_sku_scope(),
                product_id=getattr(entry, "product_id", "") or "",
                sku_id=getattr(entry, "sku_id", "") or "",
                title=getattr(entry, "title", "") or "",
            ):
                continue

            metadata = chunk.get_metadata()
            evidence_fact_type = (
                getattr(entry, "fact_type", "") or metadata.get("fact_type") or infer_evidence_fact_type({
                    "title": getattr(entry, "title", ""),
                    "chunk_text": chunk.chunk_text,
                    "source_type": chunk.source_type,
                    "category": chunk.category,
                    "category_l3": chunk.category_l3,
                    "metadata": metadata,
                })
            )
            if (
                query_fact_type == "odor"
                and evidence_fact_type == "material"
                and _has_odor_signal(f"{getattr(entry, 'title', '')} {chunk.chunk_text}")
            ):
                evidence_fact_type = "odor"
            fact_score, direct_allowed, skip = _fact_score(
                query_fact_type,
                evidence_fact_type,
                align_evidence_to_query,
                semantic_query,
            )
            if skip:
                continue
            semantic_alignment = align_evidence_to_query(
                query_fact_type=query_fact_type,
                evidence_fact_type=evidence_fact_type,
                semantic_query=semantic_query,
            )
            score = (
                10.0
                + _scope_score(identity, entry.get_product_scope(), entry.get_sku_scope(), getattr(entry, "title", ""))
                + fact_score
                + _text_overlap_score(query, getattr(entry, "title", ""), chunk.chunk_text)
                + _source_priority(chunk.source_type)
            )
            candidates.append({
                "score": round(score, 4),
                "text_score": round(_text_overlap_score(query, getattr(entry, "title", ""), chunk.chunk_text), 4),
                "vector_score": 0.0,
                "scope_score": 1.0,
                "source_confidence": float(chunk.source_confidence or getattr(entry, "source_confidence", 0.5) or 0.5),
                "rerank_score": round(score, 4),
                "mismatch_reason": "" if direct_allowed else "wrong_fact_type",
                "semantic_alignment": semantic_alignment,
                "chunk_id": chunk.id,
                "entry_id": entry.id,
                "title": getattr(entry, "title", ""),
                "chunk_text": chunk.chunk_text,
                "chunk_index": chunk.chunk_index,
                "source_type": chunk.source_type,
                "intent": chunk.intent,
                "category": chunk.category or getattr(entry, "category", "") or "",
                "category_l3": chunk.category_l3 or getattr(entry, "category_l3", "") or "",
                "fact_type": evidence_fact_type,
                "evidence_fact_type": evidence_fact_type,
                "metadata": metadata,
                "entry_status": "published",
                "index_status": "ready",
                "entry_risk_level": getattr(entry, "risk_level", "low"),
                "source_sheet": getattr(entry, "source_sheet", ""),
                "row_number": getattr(entry, "row_number", 0),
                "sku_scope": entry.get_sku_scope(),
                "product_scope": entry.get_product_scope(),
                "product_context_pack": True,
                "evidence_allowed_for_direct_answer": direct_allowed,
                "evidence_allowed_for_exact_answer": direct_allowed,
            })

        if not allowed or "faq" in allowed:
            for qa in db.query(KBQA).filter(KBQA.status == "published").filter(KBQA.auto_reply == True).all():  # noqa: E712
                product = qa.product
                product_scope = [getattr(product, "product_name", "")] if product else []
                if product:
                    product_scope.append(getattr(product, "i_id", ""))
                sku_scope = qa.get_sku_codes()
                if not _scope_matches(
                    identity,
                    product_scope=product_scope,
                    sku_scope=sku_scope,
                    product_id=getattr(product, "i_id", "") if product else "",
                    sku_id="",
                    title=qa.question,
                ):
                    continue
                evidence_fact_type = _infer_qa_fact_type(qa, infer_evidence_fact_type)
                if (
                    query_fact_type == "odor"
                    and evidence_fact_type == "material"
                    and _has_odor_signal(f"{qa.question} {qa.answer}")
                ):
                    evidence_fact_type = "odor"
                fact_score, direct_allowed, skip = _fact_score(
                    query_fact_type,
                    evidence_fact_type,
                    align_evidence_to_query,
                    semantic_query,
                )
                if skip:
                    continue
                semantic_alignment = align_evidence_to_query(
                    query_fact_type=query_fact_type,
                    evidence_fact_type=evidence_fact_type,
                    semantic_query=semantic_query,
                )
                text = _clean_qa_answer_text(qa.answer)
                score = (
                    8.0
                    + _scope_score(identity, product_scope, sku_scope, qa.question)
                    + fact_score
                    + _text_overlap_score(query, qa.question, qa.answer)
                    + _source_priority(qa.source_type or "faq")
                )
                candidates.append({
                    "score": round(score, 4),
                    "text_score": round(_text_overlap_score(query, qa.question, qa.answer), 4),
                    "vector_score": 0.0,
                    "scope_score": 1.0,
                    "source_confidence": 0.5,
                    "rerank_score": round(score, 4),
                    "mismatch_reason": "" if direct_allowed else "wrong_fact_type",
                    "semantic_alignment": semantic_alignment,
                    "chunk_id": f"kbqa:{qa.id}",
                    "entry_id": f"kbqa:{qa.id}",
                    "title": qa.question,
                    "chunk_text": text,
                    "chunk_index": 0,
                    "source_type": qa.source_type or "faq",
                    "intent": qa.intent,
                    "category": qa.category_l2 or qa.category_l1 or "",
                    "category_l3": qa.category_l3 or "",
                    "fact_type": evidence_fact_type,
                    "evidence_fact_type": evidence_fact_type,
                    "metadata": {"auto_reply_allowed": bool(qa.auto_reply), "human_review_required": bool(qa.human_review)},
                    "entry_status": "published",
                    "index_status": "ready",
                    "entry_risk_level": qa.risk_level or "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "sku_scope": sku_scope,
                    "product_scope": [p for p in product_scope if p],
                    "product_context_pack": True,
                    "evidence_allowed_for_direct_answer": direct_allowed,
                    "evidence_allowed_for_exact_answer": direct_allowed,
                })

        evaluated_candidates = list(candidates)
        if query_fact_type and any(item.get("evidence_allowed_for_direct_answer") for item in candidates):
            candidates = [item for item in candidates if item.get("evidence_allowed_for_direct_answer")]

        candidates.sort(key=lambda item: item.get("rerank_score", 0), reverse=True)
        returned_facts = candidates[:top_k]
        evidence_pack = _build_evidence_pack(
            identity=identity,
            structured_profile=structured_profile,
            facts=returned_facts,
            all_candidate_facts=evaluated_candidates,
            recommended_assets=recommended_assets,
            generic_rules=generic_rules,
            query=query,
            query_fact_type=query_fact_type,
            top_k=top_k,
        )
        return {
            "identity": identity,
            "structured_profile": structured_profile,
            "facts": returned_facts,
            "product_card_evidence": product_card_evidence,
            "media_evidence": media_evidence,
            "media_assets": media_assets,
            "recommended_assets": recommended_assets,
            "activity_rules": activity_rules,
            "generic_rules": generic_rules,
            "evidence_pack": evidence_pack,
            "stats": {
                "candidate_count": len(candidates),
                "returned_count": min(len(candidates), top_k),
                "media_count": len(media_assets),
                "recommended_media_count": len(recommended_assets),
                "activity_rule_count": len(activity_rules),
                "generic_rule_count": len(generic_rules),
                "product_card_evidence_count": len(product_card_evidence),
                "media_evidence_count": len(media_evidence),
                "has_structured_profile": bool(structured_profile),
                "query_fact_type": query_fact_type,
                "required_fact_types": required_types,
                "evidence_pack_answerability": evidence_pack.get("answerability", ""),
            },
        }
    finally:
        db.close()


def _empty_pack(identity: dict[str, str], reason: str) -> dict[str, Any]:
    evidence_pack = _empty_evidence_pack(identity, reason)
    return {
        "identity": identity,
        "structured_profile": {},
        "facts": [],
        "product_card_evidence": [],
        "media_evidence": [],
        "media_assets": [],
        "recommended_assets": [],
        "activity_rules": [],
        "generic_rules": [],
        "evidence_pack": evidence_pack,
        "stats": {
            "candidate_count": 0,
            "returned_count": 0,
            "media_count": 0,
            "recommended_media_count": 0,
            "activity_rule_count": 0,
            "generic_rule_count": 0,
            "reason": reason,
            "evidence_pack_answerability": evidence_pack.get("answerability", ""),
        },
    }


def _required_fact_types(
    state: dict[str, Any],
    query_fact_type: str,
    explicit_required: list[str] | None = None,
) -> list[str]:
    query_understanding = state.get("query_understanding") if isinstance(state.get("query_understanding"), dict) else {}
    values = [
        query_fact_type,
        query_understanding.get("query_fact_type", ""),
        state.get("query_fact_type", ""),
        *(explicit_required or []),
        *(query_understanding.get("secondary_fact_types") or []),
        *(state.get("secondary_fact_types") or []),
    ]
    rejected = str(query_understanding.get("llm_rejected_fact_type") or state.get("llm_rejected_fact_type") or "").strip()
    out: list[str] = []
    for value in values:
        fact_type = str(value or "").strip()
        if fact_type and fact_type != rejected and fact_type not in out:
            out.append(fact_type)
    return out


def _empty_evidence_pack(identity: dict[str, str], reason: str) -> dict[str, Any]:
    return {
        "identity": identity,
        "retrieval_query": "",
        "query_fact_type": "",
        "answerability": "no_product_identity" if reason == "no_product_identity" else "unavailable",
        "matched_fields": [],
        "missing_fields": [],
        "matched_facts": [],
        "matched_media": [],
        "matched_generic_rules": [],
        "evidence_evaluation": [],
        "source_priority": ["product_profile", "product_media", "product_knowledge", "faq", "generic_rules"],
        "reason": reason,
    }


def _build_evidence_pack(
    *,
    identity: dict[str, str],
    structured_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    all_candidate_facts: list[dict[str, Any]] | None = None,
    recommended_assets: list[dict[str, Any]],
    generic_rules: list[dict[str, Any]],
    query: str,
    query_fact_type: str,
    top_k: int,
) -> dict[str, Any]:
    matched_fields = _matched_profile_fields(structured_profile, facts, query_fact_type)
    matched_facts = [_compact_fact_for_evidence(item) for item in facts[:top_k]]
    matched_media = [_compact_media_for_evidence(item) for item in recommended_assets[:3]]
    matched_generic_rules = [_compact_generic_rule_for_evidence(item) for item in generic_rules[:3]]
    evidence_evaluation = _build_evidence_evaluation(
        facts=facts,
        all_candidate_facts=all_candidate_facts or facts,
        recommended_assets=recommended_assets,
        generic_rules=generic_rules,
        query_fact_type=query_fact_type,
    )
    direct_facts = [
        item for item in facts
        if item.get("evidence_allowed_for_direct_answer") is not False
        and _fact_matches_query_type(query_fact_type, item)
    ]

    missing_fields: list[str] = []
    if query_fact_type and not direct_facts and query_fact_type not in matched_fields:
        missing_fields.append(query_fact_type)

    if direct_facts:
        answerability = "direct_answer"
    elif matched_media and query_fact_type in {"installation", "dimensions", "space_fit", "detachable", "accessories", "packaging", "visual_asset"}:
        answerability = "media_supported"
    elif matched_generic_rules:
        answerability = "generic_rule_fallback"
    elif structured_profile:
        answerability = "missing_product_fact" if query_fact_type else "product_identified"
    else:
        answerability = "no_product_profile"

    return {
        "identity": identity,
        "retrieval_query": query or "",
        "query_fact_type": query_fact_type or "",
        "answerability": answerability,
        "matched_fields": matched_fields,
        "missing_fields": missing_fields,
        "matched_facts": matched_facts,
        "matched_media": matched_media,
        "matched_generic_rules": matched_generic_rules,
        "evidence_evaluation": evidence_evaluation,
        "source_priority": ["product_profile", "product_media", "product_knowledge", "faq", "generic_rules"],
    }


def _matched_profile_fields(
    structured_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    query_fact_type: str,
) -> list[str]:
    fields: list[str] = []
    answerable_fields = structured_profile.get("answerable_fields", []) if isinstance(structured_profile, dict) else []
    for field in answerable_fields:
        if not query_fact_type or field == query_fact_type:
            fields.append(field)
    for item in facts:
        fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "").strip()
        if fact_type and _fact_matches_query_type(query_fact_type, item) and fact_type not in fields:
            fields.append(fact_type)
    return fields


def _fact_matches_query_type(query_fact_type: str, item: dict[str, Any]) -> bool:
    if not query_fact_type:
        return True
    evidence_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "").strip()
    if not evidence_type:
        return False
    try:
        from app.services.fact_type_service import fact_type_matches
        return fact_type_matches(query_fact_type, evidence_type)
    except Exception:
        return evidence_type == query_fact_type


def _compact_fact_for_evidence(item: dict[str, Any]) -> dict[str, Any]:
    text = _clean_qa_answer_text(str(item.get("chunk_text") or ""))
    alignment = item.get("semantic_alignment") if isinstance(item.get("semantic_alignment"), dict) else {}
    return {
        "entry_id": item.get("entry_id"),
        "chunk_id": item.get("chunk_id"),
        "title": item.get("title", ""),
        "source_type": item.get("source_type", ""),
        "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or "",
        "score": item.get("rerank_score", item.get("score", 0)),
        "direct_answer_allowed": item.get("evidence_allowed_for_direct_answer") is not False,
        "semantic_alignment": {
            "alignment": alignment.get("alignment", ""),
            "reason": alignment.get("reason", ""),
        } if alignment else {},
        "preview": text[:240],
    }


def _clean_qa_answer_text(text: str) -> str:
    """Keep generated replies from leaking source QA labels such as Q:/A:."""
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(("q:", "q：", "question:", "问题：", "问题:")):
            continue
        if lower.startswith(("a:", "a：", "answer:", "答案：", "答案:")):
            line = line.split(":", 1)[-1].split("：", 1)[-1].strip()
        lines.append(line)
    return "\n".join(lines).strip()


def _compact_media_for_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": item.get("asset_id") or item.get("id"),
        "asset_type": item.get("asset_type", ""),
        "asset_title": item.get("asset_title", ""),
        "product_name": item.get("product_name", ""),
        "send_strategy": item.get("send_strategy", ""),
        "confidence": item.get("match_confidence", item.get("score", 0)),
    }


def _compact_generic_rule_for_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_key": item.get("rule_key", ""),
        "title": item.get("title", ""),
        "source_type": "generic_rules",
        "fact_type": item.get("fact_type", ""),
        "score": item.get("score", 0),
        "preview": str(item.get("content") or item.get("reply_template") or "")[:240],
        "forbidden_claims": item.get("forbidden_claims", []),
    }


def _build_evidence_evaluation(
    *,
    facts: list[dict[str, Any]],
    all_candidate_facts: list[dict[str, Any]],
    recommended_assets: list[dict[str, Any]],
    generic_rules: list[dict[str, Any]],
    query_fact_type: str,
) -> list[dict[str, Any]]:
    selected_keys = {_evidence_key(item) for item in facts}
    rows: list[dict[str, Any]] = []

    for item in all_candidate_facts:
        key = _evidence_key(item)
        selected = key in selected_keys
        fact_type_match = _fact_matches_query_type(query_fact_type, item)
        direct_allowed = item.get("evidence_allowed_for_direct_answer") is not False
        reject_reason = ""
        if not selected:
            if not fact_type_match:
                reject_reason = "fact_type_mismatch"
            elif not direct_allowed:
                reject_reason = "not_direct_answer_allowed"
            else:
                reject_reason = "lower_ranked_candidate"
        rows.append({
            "evidence_id": key,
            "source_type": item.get("source_type", ""),
            "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or "",
            "text": _clean_qa_answer_text(str(item.get("chunk_text") or ""))[:300],
            "asset_id": "",
            "relevance_score": float(item.get("rerank_score") or item.get("score") or 0),
            "answerability_score": _answerability_score(item, query_fact_type),
            "fact_type_match": bool(fact_type_match),
            "risk_match": _risk_match(item),
            "selected": bool(selected),
            "reject_reason": reject_reason,
        })

    for item in recommended_assets:
        key = f"asset:{item.get('asset_id') or item.get('id') or item.get('asset_url') or item.get('asset_title')}"
        selected = bool(item.get("asset_url"))
        rows.append({
            "evidence_id": key,
            "source_type": "product_media",
            "fact_type": query_fact_type or item.get("media_purpose") or "",
            "text": str(item.get("asset_title") or item.get("asset_type") or "")[:300],
            "asset_id": item.get("asset_id") or item.get("id") or "",
            "relevance_score": float(item.get("match_confidence") or item.get("score") or 0),
            "answerability_score": 0.8 if selected else 0.0,
            "fact_type_match": True,
            "risk_match": True,
            "selected": selected,
            "reject_reason": "" if selected else "missing_asset_url",
        })

    if not any(row["selected"] for row in rows):
        for item in generic_rules[:3]:
            fact_type_match = not query_fact_type or item.get("fact_type") == query_fact_type
            rows.append({
                "evidence_id": f"generic:{item.get('rule_key') or item.get('id') or item.get('title')}",
                "source_type": "generic_rules",
                "fact_type": item.get("fact_type", ""),
                "text": str(item.get("content") or item.get("reply_template") or "")[:300],
                "asset_id": "",
                "relevance_score": float(item.get("score") or item.get("source_confidence") or 0),
                "answerability_score": 0.55 if fact_type_match else 0.2,
                "fact_type_match": bool(fact_type_match),
                "risk_match": str(item.get("risk_level") or "low") in {"low", ""},
                "selected": bool(fact_type_match),
                "reject_reason": "" if fact_type_match else "fact_type_mismatch",
            })

    rows.sort(key=lambda row: (
        not row["selected"],
        -float(row["answerability_score"]),
        -float(row["relevance_score"]),
    ))
    return rows[:12]


def _evidence_key(item: dict[str, Any]) -> str:
    return str(item.get("entry_id") or item.get("chunk_id") or item.get("id") or "")


def _answerability_score(item: dict[str, Any], query_fact_type: str) -> float:
    if not _fact_matches_query_type(query_fact_type, item):
        return 0.0
    if item.get("evidence_allowed_for_direct_answer") is False:
        return 0.35
    source = str(item.get("source_type") or "")
    if source == "product_facts":
        return 1.0
    if source == "faq":
        return 0.9
    if source == "installation_guide":
        return 0.85
    return 0.7


def _risk_match(item: dict[str, Any]) -> bool:
    risk = str(item.get("entry_risk_level") or item.get("risk_level") or "low").lower()
    return risk in {"", "low", "medium"}


def _find_kb_product(db, KBProduct, identity: dict[str, str]):
    sku = identity.get("sku", "")
    i_id = identity.get("i_id", "")
    sku_family = identity.get("sku_family", "")
    product_name = identity.get("product_name", "")
    if i_id:
        product = db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
        if product:
            return product
    for code in (sku, sku_family):
        if not code:
            continue
        product = db.query(KBProduct).filter(KBProduct.i_id == code).first()
        if product:
            return product

    products = db.query(KBProduct).filter(KBProduct.status == "published").all()
    for product in products:
        if any(_code_matches(code, product.i_id) for code in (sku, sku_family, i_id)):
            return product
        sku_text = json.dumps(product.get_sku_list(), ensure_ascii=False)
        if any(code and code.upper() in sku_text.upper() for code in (sku, sku_family)):
            return product
    if product_name:
        for product in products:
            if _text_matches(product_name, product.product_name):
                return product
    return None


def _build_structured_profile(product) -> dict[str, Any]:
    if not product:
        return {}
    specs = _clean_mapping(product.get_specs())
    logistics = _clean_mapping(product.get_logistics())
    warranty = _clean_mapping(product.get_warranty())
    sku_list = _clean_sku_list(product.get_sku_list())
    profile = {
        "source": "kb_product",
        "product_id": product.id,
        "i_id": product.i_id,
        "product_name": product.product_name,
        "brand": product.brand,
        "category": {
            "l1": product.category_l1,
            "l2": product.category_l2,
            "l3": product.category_l3,
        },
        "sku_list": sku_list[:20],
        "specs": specs,
        "logistics": logistics,
        "warranty": warranty,
        "status": product.status,
        "completeness_score": product.completeness_score,
        "missing_fields": product.get_missing_fields(),
    }
    profile["answerable_fields"] = _answerable_fields(specs, logistics, warranty)
    return profile


def _clean_mapping(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for key, val in value.items():
        if val in (None, "", [], {}, "-"):
            continue
        cleaned[str(key)] = val
    return cleaned


def _clean_sku_list(value: list[Any]) -> list[dict[str, Any]]:
    cleaned = []
    if not isinstance(value, list):
        return cleaned
    for item in value:
        if isinstance(item, dict):
            compact = {
                str(k): v for k, v in item.items()
                if v not in (None, "", [], {}, "-")
                and str(k) in {"sku_code", "sku_id", "sku_name", "name", "color", "size", "price", "enabled", "properties"}
            }
            if compact:
                cleaned.append(compact)
        elif item:
            cleaned.append({"sku_code": str(item)})
    return cleaned


def _answerable_fields(specs: dict[str, Any], logistics: dict[str, Any], warranty: dict[str, Any]) -> list[str]:
    haystack = {str(k).lower(): v for k, v in {**specs, **logistics, **warranty}.items()}
    mapping = {
        "material": ("material", "材质", "材料", "用料"),
        "dimensions": ("size", "尺寸", "长宽高", "height", "width", "length"),
        "space_fit": ("size", "尺寸", "长宽高", "height", "width", "length"),
        "placement_scene": ("usage_scene", "scene", "room", "适用场景", "摆放", "卧室", "客厅", "书房", "厨房", "阳台"),
        "load_capacity": ("load_capacity", "承重", "载重"),
        "installation": ("install_method", "installation", "安装", "组装方式"),
        "detachable": ("detachable", "可拆", "拆卸", "拆装"),
        "odor": ("odor", "odor_note", "气味", "味道", "异味", "散味"),
        "cleaning_care": ("cleaning", "清洗", "保养", "水洗"),
        "age_range": ("age_range", "适用年龄", "月龄", "年龄"),
        "accessories": ("accessories", "配件", "清单", "parts"),
        "stock_shipping": ("shipping", "发货", "物流"),
        "aftersales_policy": ("warranty", "质保", "售后"),
    }
    fields = []
    for fact_type, keys in mapping.items():
        if any(any(token.lower() in key for token in keys) for key in haystack):
            fields.append(fact_type)
    return fields


def _profile_facts_for_query(profile: dict[str, Any], *, query: str, query_fact_type: str) -> list[dict[str, Any]]:
    """Turn explicit structured product fields into direct-answer evidence.

    This is intentionally narrow: only exact structured fields are used. It does
    not infer safety, certification, or pinch-risk from adjacent product data.
    """
    if not profile:
        return []
    specs = profile.get("specs") or {}
    logistics = profile.get("logistics") or {}
    warranty = profile.get("warranty") or {}
    field_map = _profile_field_map(specs, logistics, warranty)
    requested = query_fact_type or _infer_profile_fact_type_from_query(query)
    if not requested:
        return []
    if requested in {"pinch_safety", "certification_report", "safety_small_parts"}:
        return []

    fields = field_map.get(requested) or []
    values = [(label, value) for label, value in fields if value not in (None, "", [], {}, "-")]
    if not values:
        return []

    body = "\n".join(f"{label}: {value}" for label, value in values)
    title = f"{profile.get('product_name') or '当前商品'}商品资料"
    text_score = _text_overlap_score(query, title, body)
    return [{
        "score": round(18.0 + text_score, 4),
        "text_score": round(text_score, 4),
        "vector_score": 0.0,
        "scope_score": 1.0,
        "source_confidence": 0.85,
        "rerank_score": round(18.0 + text_score, 4),
        "mismatch_reason": "",
        "chunk_id": f"kbproduct:{profile.get('product_id')}:{requested}",
        "entry_id": f"kbproduct:{profile.get('product_id')}",
        "title": title,
        "chunk_text": body,
        "chunk_index": 0,
        "source_type": "product_facts",
        "intent": "product_question",
        "category": "structured_profile",
        "category_l3": requested,
        "fact_type": requested,
        "evidence_fact_type": requested,
        "metadata": {"source": "kb_product.specs", "structured_profile_fact": True},
        "semantic_alignment": _direct_semantic_alignment(requested, requested),
        "entry_status": "published",
        "index_status": "ready",
        "entry_risk_level": "low",
        "source_sheet": "",
        "row_number": 0,
        "sku_scope": [item.get("sku_code") for item in profile.get("sku_list", []) if isinstance(item, dict) and item.get("sku_code")],
        "product_scope": [profile.get("i_id", ""), profile.get("product_name", "")],
        "product_context_pack": True,
        "evidence_allowed_for_direct_answer": True,
        "evidence_allowed_for_exact_answer": True,
    }]


def _product_card_evidence_items(
    profile: dict[str, Any],
    *,
    query: str,
    query_fact_type: str,
    required_fact_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not profile:
        return []
    specs = profile.get("specs") or {}
    logistics = profile.get("logistics") or {}
    warranty = profile.get("warranty") or {}
    field_map = _profile_field_map(specs, logistics, warranty)
    requested = set(required_fact_types or ([query_fact_type] if query_fact_type else profile.get("answerable_fields") or []))
    blocked = {"pinch_safety", "certification_report", "safety_small_parts", "stability"}
    items: list[dict[str, Any]] = []
    for fact_type, fields in field_map.items():
        if fact_type in blocked:
            continue
        if requested and not _fact_type_in_required(fact_type, requested):
            continue
        values = [(label, value) for label, value in fields if _is_answerable_value(value)]
        if not values:
            continue
        body = "\n".join(f"{label}: {_stringify_profile_value(value)}" for label, value in values)
        title = f"{profile.get('product_name') or 'current product'} product card"
        text_score = _text_overlap_score(query, title, body)
        score = 20.0 + text_score + (2.0 if fact_type == query_fact_type else 0.0)
        items.append(_context_evidence_item(
            profile=profile,
            fact_type=fact_type,
            title=title,
            chunk_text=body,
            chunk_id=f"kbproduct:{profile.get('product_id')}:{fact_type}:card",
            entry_id=f"kbproduct:{profile.get('product_id')}",
            source_type="product_facts",
            category="product_card",
            source_confidence=0.9,
            score=score,
            metadata={
                "source": "kb_product",
                "evidence_origin": "product_card",
                "profile_fields": [label for label, _ in values],
            },
            origin="product_card",
        ))
    return sorted(items, key=lambda item: item.get("rerank_score", 0), reverse=True)


def _media_evidence_items(
    profile: dict[str, Any],
    *,
    media_assets: list[dict[str, Any]],
    recommended_assets: list[dict[str, Any]],
    query: str,
    query_fact_type: str,
    required_fact_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    requested = set(required_fact_types or ([query_fact_type] if query_fact_type else []))
    assets = _dedupe_media_assets([*(recommended_assets or []), *(media_assets or [])])
    items: list[dict[str, Any]] = []
    for asset in assets:
        if not _media_asset_is_usable(asset):
            continue
        fact_types = _media_fact_types_for_asset(asset)
        if requested:
            fact_types = [
                fact_type for fact_type in fact_types
                if _fact_type_in_required(fact_type, requested)
            ]
        for fact_type in fact_types:
            chunk_text = _media_evidence_text(asset, fact_type)
            title = asset.get("asset_title") or asset.get("title") or _media_fact_title(fact_type)
            score = 17.0 + _text_overlap_score(query, str(title), chunk_text)
            items.append(_context_evidence_item(
                profile=profile,
                fact_type=fact_type,
                title=str(title),
                chunk_text=chunk_text,
                chunk_id=f"kbmedia:{asset.get('asset_id') or asset.get('id')}:{fact_type}",
                entry_id=f"kbmedia:{asset.get('asset_id') or asset.get('id')}",
                source_type="product_media",
                category="product_media",
                source_confidence=float(asset.get("confidence") or asset.get("match_confidence") or 0.8),
                score=score,
                metadata={
                    "source": "kb_media_asset",
                    "evidence_origin": "product_media",
                    "media_asset_id": asset.get("asset_id") or asset.get("id"),
                    "asset_type": asset.get("asset_type", ""),
                    "media_purpose": asset.get("media_purpose", ""),
                    "scene_tags": asset.get("scene_tags") or [],
                    "answer_scenarios": asset.get("answer_scenarios") or [],
                    "auto_send_level": asset.get("auto_send_level", ""),
                },
                origin="product_media",
                extra={
                    "asset_id": asset.get("asset_id") or asset.get("id"),
                    "asset_type": asset.get("asset_type", ""),
                    "asset_title": asset.get("asset_title") or asset.get("title") or "",
                    "asset_url": asset.get("asset_url") or asset.get("url") or "",
                    "url": asset.get("asset_url") or asset.get("url") or "",
                    "thumbnail_url": asset.get("thumbnail_url") or asset.get("asset_url") or asset.get("url") or "",
                    "send_mode": asset.get("send_mode", "manual"),
                    "auto_send_level": asset.get("auto_send_level", ""),
                    "sendable": True,
                },
            ))
    return sorted(_dedupe_evidence_items(items), key=lambda item: item.get("rerank_score", 0), reverse=True)


def _fact_type_in_required(fact_type: str, required: set[str]) -> bool:
    if not required:
        return True
    if fact_type in required:
        return True
    return any(
        _fact_matches_query_type(required_type, {"fact_type": fact_type})
        or _fact_matches_query_type(fact_type, {"fact_type": required_type})
        for required_type in required
    )


def _context_evidence_item(
    *,
    profile: dict[str, Any],
    fact_type: str,
    title: str,
    chunk_text: str,
    chunk_id: str,
    entry_id: str,
    source_type: str,
    category: str,
    source_confidence: float,
    score: float,
    metadata: dict[str, Any],
    origin: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "score": round(score, 4),
        "text_score": 0.0,
        "vector_score": 0.0,
        "scope_score": 1.0,
        "source_confidence": source_confidence,
        "rerank_score": round(score, 4),
        "mismatch_reason": "",
        "chunk_id": chunk_id,
        "entry_id": entry_id,
        "title": title,
        "chunk_text": chunk_text,
        "chunk_index": 0,
        "source_type": source_type,
        "intent": "product_question",
        "category": category,
        "category_l3": fact_type,
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "metadata": metadata,
        "semantic_alignment": _direct_semantic_alignment(fact_type, fact_type),
        "entry_status": "published",
        "index_status": "ready",
        "entry_risk_level": "low",
        "source_sheet": "",
        "row_number": 0,
        "sku_scope": [item.get("sku_code") for item in profile.get("sku_list", []) if isinstance(item, dict) and item.get("sku_code")],
        "product_scope": [profile.get("i_id", ""), profile.get("product_name", "")],
        "product_context_pack": True,
        "evidence_origin": origin,
        "evidence_allowed_for_direct_answer": True,
        "evidence_allowed_for_exact_answer": True,
    }
    if extra:
        item.update(extra)
    return item


def _is_answerable_value(value: Any) -> bool:
    if value in (None, "", [], {}, "-"):
        return False
    text = _stringify_profile_value(value).strip()
    if not text:
        return False
    invalid_terms = (
        "\u8be6\u89c1\u5546\u54c1\u8be6\u60c5\u9875",
        "\u8be6\u89c1\u9875\u9762",
        "\u5f85\u8865\u5145",
        "\u6682\u65e0",
        "\u65e0",
        "n/a",
        "none",
        "null",
    )
    return text.lower() not in invalid_terms


def _stringify_profile_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _media_asset_is_usable(asset: dict[str, Any]) -> bool:
    if not isinstance(asset, dict):
        return False
    if not (asset.get("asset_id") or asset.get("id")):
        return False
    if not (asset.get("asset_url") or asset.get("url") or asset.get("thumbnail_url")):
        return False
    return str(asset.get("auto_send_level") or "auto") != "disabled"


def _media_fact_types_for_asset(asset: dict[str, Any]) -> list[str]:
    text = " ".join(str(part or "").lower() for part in (
        asset.get("asset_type"),
        asset.get("media_purpose"),
        asset.get("asset_title"),
        " ".join(str(tag or "") for tag in asset.get("scene_tags") or []),
        " ".join(str(tag or "") for tag in asset.get("answer_scenarios") or []),
    ))
    mapping = [
        ("dimensions", ("size_image", "dimensions", "size", "\u5c3a\u5bf8", "\u89c4\u683c")),
        ("installation", ("install_video", "install_image", "installation", "install", "\u5b89\u88c5", "\u6559\u7a0b")),
        ("accessories", ("accessory_image", "pack_guide_image", "packing_list", "accessories", "parts", "\u914d\u4ef6", "\u88c5\u7bb1")),
        ("certification_report", ("certificate_image", "certificate", "certification", "\u8bc1\u4e66", "\u68c0\u6d4b", "\u8d28\u68c0")),
        ("material", ("material_image", "material", "\u6750\u8d28", "\u6750\u6599")),
    ]
    fact_types = []
    for fact_type, tokens in mapping:
        if any(token in text for token in tokens):
            fact_types.append(fact_type)
    if "visual_asset" not in fact_types:
        fact_types.append("visual_asset")
    return list(dict.fromkeys(fact_types))


def _media_fact_title(fact_type: str) -> str:
    return {
        "dimensions": "size image",
        "installation": "installation media",
        "accessories": "packing list media",
        "certification_report": "certificate media",
        "material": "material media",
        "visual_asset": "product media",
    }.get(fact_type, "product media")


def _media_evidence_text(asset: dict[str, Any], fact_type: str) -> str:
    title = str(asset.get("asset_title") or _media_fact_title(fact_type))
    word = "\u89c6\u9891" if str(asset.get("asset_type") or "").endswith("_video") else "\u56fe\u7247"
    if fact_type == "dimensions":
        return f"\u5f53\u524d\u5546\u54c1\u6709\u5c3a\u5bf8/\u89c4\u683c{word}\u300a{title}\u300b\uff0c\u53ef\u53d1\u60a8\u53c2\u8003\uff0c\u5c3a\u5bf8\u4ee5\u56fe\u4e2d\u6807\u6ce8\u4e3a\u51c6\u3002"
    if fact_type == "installation":
        return f"\u5f53\u524d\u5546\u54c1\u6709\u5b89\u88c5\u8bf4\u660e{word}\u300a{title}\u300b\uff0c\u53ef\u53d1\u60a8\u5bf9\u7167\u5b89\u88c5\u6b65\u9aa4\u53c2\u8003\u3002"
    if fact_type == "accessories":
        return f"\u5f53\u524d\u5546\u54c1\u6709\u914d\u4ef6/\u88c5\u7bb1\u6e05\u5355{word}\u300a{title}\u300b\uff0c\u53ef\u53d1\u60a8\u6838\u5bf9\u3002"
    if fact_type == "certification_report":
        return f"\u5f53\u524d\u5546\u54c1\u6709\u8bc1\u4e66/\u68c0\u6d4b\u7c7b{word}\u300a{title}\u300b\uff0c\u53ef\u53d1\u60a8\u53c2\u8003\uff0c\u5177\u4f53\u7ed3\u8bba\u4ee5\u62a5\u544a\u6807\u6ce8\u4e3a\u51c6\u3002"
    if fact_type == "material":
        return f"\u5f53\u524d\u5546\u54c1\u6709\u6750\u8d28\u8bf4\u660e{word}\u300a{title}\u300b\uff0c\u53ef\u53d1\u60a8\u6838\u5bf9\uff0c\u4e0d\u4ee3\u66ff\u68c0\u6d4b\u62a5\u544a\u7ed3\u8bba\u3002"
    return f"\u5f53\u524d\u5546\u54c1\u6709{word}\u300a{title}\u300b\uff0c\u53ef\u4e00\u8d77\u53d1\u60a8\u53c2\u8003\u3002"


def _dedupe_media_assets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (item.get("asset_id") or item.get("id"), item.get("asset_type"), item.get("asset_title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (item.get("chunk_id"), item.get("entry_id"), item.get("fact_type"), item.get("asset_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _media_fact_customer_text(query_fact_type: str, media_word: str) -> str:
    if query_fact_type == "detachable":
        return (
            f"这款商品可以参考下面发送的拆装/结构说明{media_word}。"
            "请重点看图中标注的拆装位置、结构连接处和尺寸信息。"
        )
    if query_fact_type in {"dimensions", "space_fit"}:
        return (
            f"这款商品的尺寸可以参考下面发送的尺寸/规格{media_word}。"
            "请对照家里预留位置的宽度、进深和高度，必要时可以把预留尺寸发来一起判断。"
        )
    if query_fact_type == "installation":
        return (
            f"这款商品可以参考下面发送的安装说明{media_word}。"
            "按图里或视频里的步骤对照安装会更直观。"
        )
    if query_fact_type == "visual_asset":
        return (
            f"这款商品可以参考下面发送的商品{media_word}。"
            "您可以先看整体外观、颜色和页面展示效果；如果想看某个细节，也可以直接圈出来问我。"
        )
    if query_fact_type == "accessories":
        return (
            f"这款商品可以参考下面发送的配件/包装清单{media_word}。"
            "请按图中配件位置和数量逐一核对。"
        )
    return f"这款商品可以参考下面发送的商品说明{media_word}。"


def _activity_facts_for_query(
    activity_rules: list[dict[str, Any]],
    *,
    query: str,
    query_fact_type: str,
) -> list[dict[str, Any]]:
    if not activity_rules or not _activity_query_requested(query, query_fact_type):
        return []
    facts = []
    for rule in activity_rules:
        text = str(rule.get("customer_reply") or rule.get("customer_visible_benefit") or "").strip()
        if not text:
            continue
        title = str(rule.get("title") or "\u5546\u54c1\u6d3b\u52a8\u89c4\u5219")
        text_score = _text_overlap_score(query, title, text)
        score = 19.0 + text_score
        facts.append({
            "score": round(score, 4),
            "text_score": round(text_score, 4),
            "vector_score": 0.0,
            "scope_score": 1.0,
            "source_confidence": 0.9,
            "rerank_score": round(score, 4),
            "mismatch_reason": "",
            "chunk_id": f"activity:{rule.get('id')}",
            "entry_id": f"activity:{rule.get('id')}",
            "title": title,
            "chunk_text": text,
            "chunk_index": 0,
            "source_type": "product_activity_rule",
            "intent": "promotion_query",
            "category": "activity_rule",
            "category_l3": rule.get("activity_type", "promotion_policy"),
            "fact_type": "promotion_policy",
            "evidence_fact_type": "promotion_policy",
            "metadata": {
                "source": "kb_product_activity_rule",
                "activity_type": rule.get("activity_type", ""),
                "auto_reply_allowed": bool(rule.get("auto_reply_allowed")),
            },
            "semantic_alignment": _direct_semantic_alignment("promotion_policy", "promotion_policy"),
            "entry_status": rule.get("status", "active"),
            "index_status": "ready",
            "entry_risk_level": rule.get("risk_level", "low"),
            "source_sheet": "",
            "row_number": 0,
            "sku_scope": [rule.get("sku_code", "")] if rule.get("sku_code") else [],
            "product_scope": [v for v in (rule.get("i_id", ""), rule.get("product_name", "")) if v],
            "product_context_pack": True,
            "evidence_allowed_for_direct_answer": True,
            "evidence_allowed_for_exact_answer": True,
        })
    return facts


def _activity_query_requested(query: str, query_fact_type: str) -> bool:
    if query_fact_type in {"promotion_policy", "price_protection", "gift_policy"}:
        return True
    text = str(query or "")
    return any(term in text for term in (
        "\u4f18\u60e0",
        "\u6d3b\u52a8",
        "\u4f18\u60e0\u5238",
        "\u5238",
        "\u7ea2\u5305",
        "\u6652\u56fe",
        "\u597d\u8bc4",
        "\u8d60\u54c1",
        "\u4ef7\u4fdd",
        "\u4fdd\u4ef7",
    ))


def _profile_field_map(
    specs: dict[str, Any],
    logistics: dict[str, Any],
    warranty: dict[str, Any],
) -> dict[str, list[tuple[str, Any]]]:
    values = {**specs, **logistics, **warranty}

    def pick(*keys: str) -> list[tuple[str, Any]]:
        picked = []
        for key, value in values.items():
            key_text = str(key).lower()
            if any(token.lower() in key_text or token in str(key) for token in keys):
                picked.append((str(key), value))
        return picked

    return {
        "material": pick("material", "材质", "材料", "用料"),
        "dimensions": pick("size", "尺寸", "长宽高", "height", "width", "length", "规格"),
        "space_fit": pick("size", "尺寸", "长宽高", "height", "width", "length", "规格"),
        "placement_scene": pick("usage_scene", "scene", "room", "适用场景", "摆放", "卧室", "客厅", "书房", "厨房", "阳台"),
        "load_capacity": pick("load_capacity", "承重", "载重"),
        "installation": pick("install_method", "installation", "安装", "组装", "打孔"),
        "detachable": pick("detachable", "可拆", "拆卸", "拆装"),
        "odor": pick("odor", "odor_note", "气味", "味道", "异味", "散味"),
        "cleaning_care": pick("cleaning", "清洗", "保养", "水洗"),
        "age_range": pick("age_range", "适用年龄", "月龄", "年龄"),
        "accessories": pick("accessories", "配件", "清单", "parts"),
        "stock_shipping": pick("shipping", "发货", "物流", "库存"),
        "aftersales_policy": pick("warranty", "质保", "售后"),
    }


def _infer_profile_fact_type_from_query(query: str) -> str:
    text = str(query or "")
    cues = (
        ("space_fit", ("放得下", "放的下", "摆得下", "摆的下", "空间够", "够不够放", "几平方", "平方", "占空间", "占地方", "预留")),
        ("placement_scene", ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放")),
        ("installation", ("安装", "组装", "怎么装", "打孔", "租房")),
        ("detachable", ("可拆", "拆卸", "拆开", "拆下来", "能拆")),
        ("odor", ("味道", "气味", "异味", "刺鼻", "散味", "闻着")),
        ("material", ("材质", "材料", "用料", "防潮", "受潮")),
        ("dimensions", ("尺寸", "规格", "多高", "多宽", "长宽高")),
        ("load_capacity", ("承重", "放多重", "结实")),
        ("cleaning_care", ("清洗", "清洁", "怎么洗", "水洗", "保养")),
        ("age_range", ("适合多大", "几岁", "月龄", "年龄")),
        ("accessories", ("配件", "零件", "少件", "漏发")),
    )
    for fact_type, tokens in cues:
        if any(token in text for token in tokens):
            return fact_type
    return ""


def _has_odor_signal(text: str) -> bool:
    return any(term in str(text or "") for term in (
        "\u6c14\u5473",
        "\u5473\u9053",
        "\u6709\u5473",
        "\u65e0\u5473",
        "\u65e0\u5f02\u5473",
        "\u65e0\u6bd2\u65e0\u5473",
        "\u5f02\u5473",
        "\u523a\u9f3b",
        "\u6563\u5473",
        "\u901a\u98ce",
    ))


def _infer_qa_fact_type(qa, infer_evidence_fact_type) -> str:
    """Infer FAQ fact type without letting product names dominate."""
    text = f"{getattr(qa, 'question', '')} {getattr(qa, 'answer', '')}"
    prioritized = (
        ("material", ("材质", "材料", "用料", "PP", "环保")),
        ("installation", ("安装", "组装", "打孔", "教程", "说明书")),
        ("detachable", ("可拆", "拆卸", "拆开", "拆下来")),
        ("dimensions", ("尺寸", "规格", "长宽高")),
        ("load_capacity", ("承重", "载重", "放多重")),
        ("cleaning_care", ("清洗", "清洁", "水洗", "保养")),
        ("age_range", ("适合多大", "几岁", "月龄", "年龄")),
    )
    for fact_type, cues in prioritized:
        if any(cue in text for cue in cues):
            return fact_type
    return infer_evidence_fact_type({
        "title": getattr(qa, "question", ""),
        "chunk_text": getattr(qa, "answer", ""),
        "source_type": getattr(qa, "source_type", "") or "faq",
        "category_l3": getattr(qa, "category_l3", ""),
        "issue_type": getattr(qa, "issue_type", ""),
    })


def _collect_media_assets(db, KBMediaAsset, identity: dict[str, str], structured_profile: dict[str, Any], limit: int = 12) -> list[Any]:
    from datetime import datetime
    from sqlalchemy import or_

    now = datetime.utcnow()
    q = db.query(KBMediaAsset).filter(
        KBMediaAsset.status == "approved",
        KBMediaAsset.usable_for_agent == 1,
        KBMediaAsset.refresh_status != "needs_refresh",
        KBMediaAsset.refresh_status != "error",
        or_(KBMediaAsset.url_expires_at.is_(None), KBMediaAsset.url_expires_at > now),
    )
    conds = []
    product_id = structured_profile.get("product_id")
    if product_id:
        conds.append(KBMediaAsset.product_id == product_id)
    for field, column in (
        ("i_id", KBMediaAsset.i_id),
        ("sku", KBMediaAsset.sku_code),
        ("sku_family", KBMediaAsset.sku_code),
        ("product_name", KBMediaAsset.product_name),
    ):
        value = identity.get(field)
        if value:
            if field == "sku_family":
                conds.append(column.like(f"{value}%"))
            else:
                conds.append(column == value)
    if not conds:
        return []
    rows = (
        q.filter(or_(*conds))
        .order_by(KBMediaAsset.match_confidence.desc(), KBMediaAsset.updated_at.desc())
        .limit(limit)
        .all()
    )
    return rows


def _media_asset_to_pack_item(asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_id": asset.id,
        "asset_type": asset.asset_type,
        "media_purpose": get_media_purpose(asset),
        "asset_title": asset.asset_title,
        "asset_url": asset.asset_url,
        "thumbnail_url": asset.asset_url,
        "source": asset.source,
        "product_id": asset.product_id,
        "i_id": asset.i_id,
        "sku_code": asset.sku_code,
        "product_name": asset.product_name,
        "confidence": asset.match_confidence or 0.0,
        "match_reason": asset.match_reason,
        "scene_tags": asset.get_scene_tags(),
        "answer_scenarios": get_answer_scenarios(asset),
        "applicable_style": get_applicable_style(asset),
        "auto_send_level": get_auto_send_level(asset),
        "expires_at": asset.url_expires_at.isoformat() if asset.url_expires_at else None,
        "send_mode": "manual",
    }


def _rank_media_assets_for_query(
    media_assets: list[Any],
    *,
    query: str,
    query_fact_type: str,
    limit: int,
    signals: dict[str, Any] | None = None,
) -> list[Any]:
    if not media_assets:
        return []
    priority = _media_priority(query, query_fact_type)
    if not priority:
        return []
    order = {asset_type: idx for idx, asset_type in enumerate(priority)}
    scenario = _media_scenario_from_fact_type(query_fact_type) or _infer_answer_scenario(query or "", query_fact_type or "")
    signals = signals or {}
    ranked = [
        asset for asset in media_assets
        if asset.asset_type in order and _media_identity_safe_for_signals(asset, signals)
    ]
    ranked.sort(key=lambda asset: (
        -_applicable_style_score(asset, signals),
        -_answer_scenario_score(asset, scenario),
        order.get(asset.asset_type, 99),
        -float(asset.match_confidence or 0),
    ))
    return ranked[:limit]


def _rank_media_assets_for_required_types(
    media_assets: list[Any],
    *,
    query: str,
    required_fact_types: list[str],
    limit: int,
    signals: dict[str, Any] | None = None,
) -> list[Any]:
    if not media_assets:
        return []
    fact_types = required_fact_types or [""]
    ranked: list[Any] = []
    seen = set()
    for fact_type in fact_types:
        for asset in _rank_media_assets_for_query(
            media_assets,
            query=query,
            query_fact_type=fact_type,
            limit=limit,
            signals=signals,
        ):
            key = getattr(asset, "id", None) or (getattr(asset, "asset_type", ""), getattr(asset, "asset_title", ""))
            if key in seen:
                continue
            seen.add(key)
            ranked.append(asset)
    if len(ranked) < limit:
        for asset in _rank_media_assets_for_query(
            media_assets,
            query=query,
            query_fact_type="",
            limit=limit,
            signals=signals,
        ):
            key = getattr(asset, "id", None) or (getattr(asset, "asset_type", ""), getattr(asset, "asset_title", ""))
            if key in seen:
                continue
            seen.add(key)
            ranked.append(asset)
            if len(ranked) >= limit:
                break
    return ranked[:limit]


def _media_identity_safe_for_signals(asset: Any, signals: dict[str, Any]) -> bool:
    """Avoid sending a media asset for the wrong SKU/combo.

    A product-family image is safe when it is explicitly marked as all-scope or
    when its style scope matches the current customer/product signals. A
    concrete SKU image from another SKU variant is not safe for automatic send.
    """

    sku = str((signals or {}).get("sku_code") or "").strip().lower()
    i_id = str((signals or {}).get("i_id") or "").strip().lower()
    asset_sku = str(getattr(asset, "sku_code", "") or "").strip().lower()

    if sku and asset_sku and asset_sku not in {sku, i_id}:
        # Full SKU codes under the same i_id still describe a specific variant.
        if i_id and asset_sku.startswith(i_id) and len(asset_sku) > len(i_id):
            return False
        sku_prefix = _variant_prefix(sku)
        asset_prefix = _variant_prefix(asset_sku)
        if sku_prefix and asset_prefix and sku_prefix == asset_prefix:
            return False

    return _style_scope_matches(asset, signals or {})


def _variant_prefix(value: str) -> str:
    match = re.match(r"^(.+?)B\d+S\d+$", str(value or "").strip(), re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _media_scenario_from_fact_type(query_fact_type: str) -> str:
    return {
        "dimensions": "dimensions",
        "space_fit": "dimensions",
        "detachable": "detachable",
        "installation": "installation",
        "accessories": "accessories",
        "visual_asset": "product_image",
    }.get(query_fact_type or "", "")


def _media_priority(query: str, query_fact_type: str) -> list[str]:
    msg = query or ""
    if query_fact_type == "installation" or any(term in msg for term in ("安装", "组装", "教程", "视频", "打孔")):
        return ["install_video", "pack_guide_image", "install_image"]
    if query_fact_type == "detachable" or any(term in msg for term in ("可拆", "拆卸", "拆开", "拆下来", "能拆", "拆装")):
        return ["size_image", "pack_guide_image", "install_image", "sku_image"]
    if query_fact_type in {"dimensions", "space_fit"} or any(term in msg for term in ("尺寸", "多大", "长宽高", "规格", "放得下", "放的下", "几平方", "空间")):
        return ["size_image", "sku_image"]
    if any(term in msg for term in ("配件", "少件", "零件", "漏发", "装不上")):
        return ["accessory_image", "pack_guide_image", "install_image"]
    if query_fact_type == "visual_asset" or any(term in msg for term in ("图片", "照片", "图", "外观", "颜色", "样子", "实物")):
        return ["sku_image", "size_image"]
    return []


def _media_tag_priority(query_fact_type: str) -> list[str]:
    return {
        "detachable": ["detachable", "拆卸", "可拆", "拆装", "dimensions", "尺寸"],
        "dimensions": ["dimensions", "尺寸", "size", "规格"],
        "space_fit": ["dimensions", "尺寸", "size", "规格", "space_fit", "空间"],
        "installation": ["installation", "安装", "install", "video", "教程"],
        "accessories": ["accessories", "配件", "零件", "parts"],
        "visual_asset": ["sku", "image", "商品图", "实物图", "外观", "颜色"],
    }.get(query_fact_type or "", [])


def _scene_tag_score(scene_tags: list[Any], priority_tags: list[str]) -> int:
    if not scene_tags or not priority_tags:
        return 0
    normalized = [str(tag or "").strip().lower() for tag in scene_tags if str(tag or "").strip()]
    score = 0
    for idx, tag in enumerate(priority_tags):
        wanted = tag.lower()
        if any(wanted in current or current in wanted for current in normalized):
            score += max(1, len(priority_tags) - idx)
    return score


def _media_facts_for_query(
    profile: dict[str, Any],
    recommended_assets: list[dict[str, Any]],
    *,
    query: str,
    query_fact_type: str,
) -> list[dict[str, Any]]:
    if query_fact_type not in {"detachable", "dimensions", "space_fit", "installation", "accessories", "visual_asset"}:
        return []
    if not recommended_assets:
        return []
    asset = recommended_assets[0]
    asset_id = asset.get("asset_id") or asset.get("id")
    if not asset_id or not asset.get("asset_url"):
        return []
    # 只有明确允许自动发送的素材才能作为直接回答的证据
    if asset.get("auto_send_level") != "auto":
        return []
    label = {
        "detachable": "拆卸/结构说明",
        "dimensions": "尺寸/规格说明",
        "space_fit": "尺寸/空间适配说明",
        "installation": "安装说明",
        "accessories": "配件/零件核对",
        "visual_asset": "商品图片/视频",
    }.get(query_fact_type, "商品说明")
    asset_type = str(asset.get("asset_type") or "")
    media_word = "视频" if asset_type.endswith("_video") else "图片"
    title = asset.get("asset_title") or label
    answer_scenarios = asset.get("answer_scenarios") or []
    if query_fact_type == "detachable":
        has_detachable_mark = (
            "detachable" in answer_scenarios
            or any(term in str(title) for term in ("可拆", "拆卸", "拆装", "拆开", "拆下来"))
        )
        if not has_detachable_mark:
            return []
    if query_fact_type == "detachable":
        body = f"这款商品已匹配到{label}{media_word}「{title}」，我把图一起发您参考，您可以看图中标注的拆装位置和尺寸信息。"
    elif query_fact_type in {"dimensions", "space_fit"}:
        body = f"这款商品已匹配到{label}{media_word}「{title}」，我把图一起发您参考，尺寸以图片标注为准。"
    elif query_fact_type == "installation":
        body = f"这款商品已匹配到{label}{media_word}「{title}」，我一起发您参考。"
    else:
        body = f"这款商品已匹配到{label}{media_word}「{title}」，我一起发您核对。"
    body = _media_fact_customer_text(query_fact_type, media_word)
    text_score = _text_overlap_score(query, title, body)
    chunk_id = f"kbmedia:{asset_id}:{query_fact_type}"
    return [{
        "score": round(16.0 + text_score, 4),
        "text_score": round(text_score, 4),
        "vector_score": 0.0,
        "scope_score": 1.0,
        "source_confidence": 0.8,
        "rerank_score": round(16.0 + text_score, 4),
        "mismatch_reason": "",
        "chunk_id": chunk_id,
        "entry_id": chunk_id,
        "title": f"{profile.get('product_name') or asset.get('product_name') or '当前商品'}{label}",
        "chunk_text": body,
        "chunk_index": 0,
        "source_type": "product_facts",
        "intent": "product_question",
        "category": "structured_profile_media",
        "category_l3": query_fact_type,
        "fact_type": query_fact_type,
        "evidence_fact_type": query_fact_type,
        "metadata": {
            "source": "kb_media_asset",
            "media_asset_id": asset_id,
            "asset_type": asset_type,
            "media_purpose": asset.get("media_purpose"),
            "scene_tags": asset.get("scene_tags") or [],
            "answer_scenarios": answer_scenarios,
            "applicable_style": asset.get("applicable_style"),
            "auto_send_level": asset.get("auto_send_level"),
        },
        "semantic_alignment": _direct_semantic_alignment(query_fact_type, query_fact_type),
        "entry_status": "published",
        "index_status": "ready",
        "entry_risk_level": "low",
        "source_sheet": "",
        "row_number": 0,
        "sku_scope": [asset.get("sku_code", "")],
        "product_scope": [asset.get("i_id", ""), asset.get("product_name", "")],
        "product_context_pack": True,
        "evidence_allowed_for_direct_answer": True,
        "evidence_allowed_for_exact_answer": True,
    }]


def _state_identity(state: dict) -> dict[str, str]:
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots") or {}
    ctx = state.get("copilot_context") or {}
    candidates = state.get("product_candidates") or []
    sku = (
        slots.get("sku_code")
        or ctx.get("sku_code")
        or identity.get("sku_id")
        or identity.get("internal_sku_code")
        or state.get("sku_code")
        or ""
    )
    i_id = (
        identity.get("i_id")
        or identity.get("internal_product_code")
        or ctx.get("i_id")
        or _sku_family(sku)
        or state.get("i_id")
        or ""
    )
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or ctx.get("product_name")
        or state.get("product_name")
        or slots.get("product_name")
        or ""
    )
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_type = str(candidate.get("type") or "").lower()
        value = str(candidate.get("value") or "").strip()
        if not sku and "sku" in candidate_type and value:
            sku = value
        if not i_id and "i_id" in candidate_type and value:
            i_id = value
        if not product_name:
            product_name = (
                candidate.get("matched_product_name")
                or candidate.get("product_name")
                or candidate.get("title")
                or candidate.get("name")
                or (value if "sku" not in candidate_type and "i_id" not in candidate_type and "product_id" not in candidate_type else "")
                or ""
            )
    return {
        "sku": str(sku or "").strip(),
        "sku_family": _sku_family(str(sku or "")),
        "i_id": str(i_id or "").strip(),
        "product_name": str(product_name or "").strip(),
    }


def _sku_family(value: str) -> str:
    match = re.match(r"^(YH\d+K\d+)", str(value or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _norm_code(value: str) -> str:
    return str(value or "").strip().upper()


def _code_matches(target: str, candidate: str) -> bool:
    target = _norm_code(target)
    candidate = _norm_code(candidate)
    if not target or not candidate:
        return False
    if target == candidate:
        return True
    family = _sku_family(target)
    candidate_family = _sku_family(candidate)
    return bool(family and candidate_family and family == candidate_family)


def _text_matches(target: str, candidate: str) -> bool:
    target = str(target or "").strip()
    candidate = str(candidate or "").strip()
    return bool(target and candidate and (target in candidate or candidate in target))


def _scope_matches(
    identity: dict[str, str],
    *,
    product_scope: list[str],
    sku_scope: list[str],
    product_id: str,
    sku_id: str,
    title: str,
) -> bool:
    codes = [identity.get("sku", ""), identity.get("sku_family", ""), identity.get("i_id", "")]
    for code in codes:
        if any(_code_matches(code, item) for item in [product_id, sku_id, *sku_scope, *product_scope]):
            return True

    name = identity.get("product_name", "")
    if name:
        if any(_text_matches(name, item) for item in product_scope):
            return True
        if _text_matches(name, title):
            return True
    return False


def _scope_score(identity: dict[str, str], product_scope: list[str], sku_scope: list[str], title: str) -> float:
    score = 0.0
    if any(_code_matches(identity.get("sku", ""), item) for item in sku_scope):
        score += 4.0
    if any(_code_matches(identity.get("i_id", ""), item) for item in product_scope):
        score += 3.0
    if any(_text_matches(identity.get("product_name", ""), item) for item in product_scope):
        score += 2.0
    if _text_matches(identity.get("product_name", ""), title):
        score += 1.0
    return score


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", str(text or "").lower())
        if token.strip()
    }


def _text_overlap_score(query: str, title: str, body: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(f"{title} {body}")
    return min(6.0, len(query_tokens & doc_tokens) * 0.8)


def _fact_score(
    query_fact_type: str,
    evidence_fact_type: str,
    align_evidence_to_query,
    semantic_query: dict[str, Any] | None = None,
) -> tuple[float, bool, bool]:
    alignment = align_evidence_to_query(
        query_fact_type=query_fact_type,
        evidence_fact_type=evidence_fact_type,
        semantic_query=semantic_query,
    )
    return (
        float(alignment.get("score_delta", 0.0)),
        bool(alignment.get("direct_answer_allowed")),
        not bool(alignment.get("allowed")),
    )


def _direct_semantic_alignment(query_fact_type: str, evidence_fact_type: str) -> dict[str, Any]:
    return {
        "allowed": True,
        "direct_answer_allowed": True,
        "score_delta": 12.0,
        "alignment": "primary_match",
        "query_fact_type": str(query_fact_type or ""),
        "evidence_fact_type": str(evidence_fact_type or ""),
        "reason": "Generated product-card evidence directly matches the requested fact type.",
    }


def _source_priority(source_type: str) -> float:
    return {
        "product_facts": 3.0,
        "installation_guide": 2.5,
        "faq": 1.5,
        "aftersales_policy": 1.0,
        "shipping_policy": 1.0,
    }.get(source_type or "", 0.0)
