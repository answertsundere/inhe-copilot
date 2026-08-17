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
from app.services.product_structured_evidence_service import build_product_spec_evidence_candidates
from app.services.real_context_product_identity_service import (
    augment_state_with_real_context_identity,
    build_conversation_media_reference,
)


def build_product_context_pack(
    state: dict,
    *,
    query: str = "",
    allowed_source_types: list[str] | None = None,
    query_fact_type: str = "",
    top_k: int = 8,
) -> dict[str, Any]:
    state = dict(state or {})
    if state.get("copilot_context"):
        augment_state_with_real_context_identity(state)
    identity = _resolve_identity_for_pack(state, _state_identity(state))
    conversation_media_reference = build_conversation_media_reference(state.get("copilot_context") or {})
    if not (identity["sku"] or identity["i_id"] or identity["product_name"]):
        return _attach_media_context_trace(
            _empty_pack(identity, "no_product_identity"),
            conversation_media_reference,
        )

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
    semantic_query = state.get("semantic_query") if isinstance(state.get("semantic_query"), dict) else {}
    db = SessionLocal()
    try:
        candidates: list[dict[str, Any]] = []
        kb_product = _find_kb_product(db, KBProduct, identity)
        structured_profile = _build_structured_profile(
            kb_product,
            requested_sku=identity.get("sku", ""),
        )
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
        provisional_evidence = _collect_ai_provisional_evidence(
            db=db,
            identity=identity,
            structured_profile=structured_profile,
            query_fact_type=query_fact_type,
        )
        media_assets = _collect_media_assets(db, KBMediaAsset, identity, structured_profile, limit=300)
        signals = {
            "customer_message": query or "",
            "sku_code": identity.get("sku", ""),
            "i_id": identity.get("i_id", ""),
            "product_name": structured_profile.get("product_name") or identity.get("product_name", ""),
        }
        recommended_assets = _rank_media_assets_for_query(
            media_assets, query=query, query_fact_type=query_fact_type, limit=1, signals=signals
        )
        media_assets = [_media_asset_to_pack_item(a) for a in media_assets]
        recommended_assets = [_media_asset_to_pack_item(a) for a in recommended_assets]
        candidates.extend(_profile_facts_for_query(structured_profile, query=query, query_fact_type=query_fact_type))
        candidates.extend(provisional_evidence)
        if not allowed or "product_facts" in allowed:
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
        scope_filter = _knowledge_scope_filter(KnowledgeChunk, KnowledgeEntry, identity, structured_profile)
        if scope_filter is not None:
            chunk_query = chunk_query.filter(scope_filter)
        else:
            chunk_query = chunk_query.filter(False)

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
            qa_query = db.query(KBQA).filter(KBQA.status == "published").filter(KBQA.auto_reply == True)  # noqa: E712
            qa_filter = _qa_scope_filter(KBQA, identity, structured_profile)
            if qa_filter is not None:
                qa_query = qa_query.filter(qa_filter)
            else:
                qa_query = qa_query.filter(False)
            for qa in qa_query.limit(80).all():
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

        if query_fact_type and any(item.get("evidence_allowed_for_direct_answer") for item in candidates):
            candidates = [item for item in candidates if item.get("evidence_allowed_for_direct_answer")]

        candidates.sort(key=lambda item: item.get("rerank_score", 0), reverse=True)
        returned_facts = candidates[:top_k]
        evidence_pack = _build_evidence_pack(
            state=state,
            identity=identity,
            structured_profile=structured_profile,
            facts=returned_facts,
            media_assets=media_assets,
            recommended_assets=recommended_assets,
            generic_rules=generic_rules,
            provisional_evidence=provisional_evidence,
            query=query,
            query_fact_type=query_fact_type,
            top_k=top_k,
        )
        return _attach_media_context_trace({
            "identity": identity,
            "structured_profile": structured_profile,
            "facts": returned_facts,
            "media_assets": media_assets,
            "recommended_assets": recommended_assets,
            "activity_rules": activity_rules,
            "generic_rules": generic_rules,
            "evidence_pack": evidence_pack,
            "product_first_evidence_pack": evidence_pack,
            "stats": {
                "candidate_count": len(candidates),
                "returned_count": min(len(candidates), top_k),
                "media_count": len(media_assets),
                "recommended_media_count": len(recommended_assets),
                "activity_rule_count": len(activity_rules),
                "generic_rule_count": len(generic_rules),
                "provisional_knowledge_count": len(provisional_evidence),
                "has_structured_profile": bool(structured_profile),
                "query_fact_type": query_fact_type,
                "evidence_pack_answerability": evidence_pack.get("answerability", ""),
                "knowledge_mode": evidence_pack.get("knowledge_mode", "verified_only"),
            },
        }, conversation_media_reference)
    finally:
        db.close()


def _empty_pack(identity: dict[str, str], reason: str) -> dict[str, Any]:
    evidence_pack = _empty_evidence_pack(identity, reason)
    return {
        "identity": identity,
        "structured_profile": {},
        "facts": [],
        "media_assets": [],
        "recommended_assets": [],
        "activity_rules": [],
        "generic_rules": [],
        "evidence_pack": evidence_pack,
        "product_first_evidence_pack": evidence_pack,
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


def _attach_media_context_trace(pack: dict[str, Any], conversation_media_reference: dict[str, Any]) -> dict[str, Any]:
    media_ref = conversation_media_reference if isinstance(conversation_media_reference, dict) else {}
    media_context_count = int(media_ref.get("media_context_count") or 0)
    media_assets = pack.get("media_assets") or []
    recommended_assets = pack.get("recommended_assets") or []
    sendable_assets = [
        item for item in recommended_assets
        if item.get("asset_url") and item.get("auto_send_level", "auto") == "auto"
    ]
    rejected_reason = ""
    if media_context_count and not media_assets:
        rejected_reason = "no_approved_usable_media_asset_matched"
    elif media_context_count and media_assets and not recommended_assets:
        rejected_reason = "approved_media_asset_not_relevant_to_query"
    elif media_context_count and recommended_assets and not sendable_assets:
        rejected_reason = "matched_media_asset_requires_manual_review"
    elif media_context_count:
        rejected_reason = media_ref.get("rejected_media_reason", "")

    pack["conversation_media_reference"] = media_ref
    stats = pack.setdefault("stats", {})
    stats["media_context_count"] = media_context_count
    stats["matched_media_asset_count"] = len(media_assets)
    stats["sendable_media_asset_count"] = len(sendable_assets)
    stats["conversation_media_rejected_reason"] = rejected_reason
    evidence_pack = pack.setdefault("evidence_pack", {})
    evidence_pack["conversation_media_reference"] = {
        "evidence_role": "conversation_media_reference",
        "sendable": False,
        "media_context_count": media_context_count,
        "rejected_media_reason": media_ref.get("rejected_media_reason", "") if media_context_count else "",
    }
    evidence_pack["media_trace"] = {
        "media_context_count": media_context_count,
        "matched_media_asset_count": len(media_assets),
        "sendable_media_asset_count": len(sendable_assets),
        "rejected_media_reason": rejected_reason,
    }
    return pack


def _empty_evidence_pack(identity: dict[str, str], reason: str) -> dict[str, Any]:
    resolution = identity.get("product_identity_resolution") if isinstance(identity, dict) else {}
    return {
        "identity": identity,
        "resolved_product_identity": identity,
        "identity_confidence": float((resolution or {}).get("identity_confidence") or 0.0),
        "identity_sources": list((resolution or {}).get("identity_sources") or []),
        "retrieval_query": "",
        "query_fact_type": "",
        "requested_fact_type": "",
        "answerability": "no_product_identity" if reason == "no_product_identity" else "unavailable",
        "product_structured_facts": [],
        "product_media_assets": [],
        "product_scoped_chunks": [],
        "generic_fallback_rules": [],
        "missing_required_evidence": [],
        "evidence_pack_trace": {
            "product_identity_locked": False,
            "product_identity_resolution": resolution or {},
            "match_reason": (resolution or {}).get("match_reason", ""),
            "candidate_count": len((resolution or {}).get("ambiguous_candidates") or []),
            "ambiguous_candidates": (resolution or {}).get("ambiguous_candidates") or [],
            "unresolved_reason": (resolution or {}).get("unresolved_reason") or reason,
            "generic_rules_role": "fallback_only",
            "blocked_reason": (resolution or {}).get("unresolved_reason") or reason,
        },
        "matched_fields": [],
        "missing_fields": [],
        "matched_facts": [],
        "matched_media": [],
        "matched_generic_rules": [],
        "source_priority": ["product_profile", "product_media", "product_knowledge", "faq", "generic_rules"],
        "reason": reason,
        "unresolved_reason": (resolution or {}).get("unresolved_reason") or reason,
    }


def _build_evidence_pack(
    *,
    state: dict[str, Any],
    identity: dict[str, str],
    structured_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    media_assets: list[dict[str, Any]],
    recommended_assets: list[dict[str, Any]],
    generic_rules: list[dict[str, Any]],
    provisional_evidence: list[dict[str, Any]] | None = None,
    query: str,
    query_fact_type: str,
    top_k: int,
) -> dict[str, Any]:
    resolution = identity.get("product_identity_resolution") if isinstance(identity, dict) else {}
    matched_fields = _matched_profile_fields(structured_profile, facts, query_fact_type)
    matched_facts = [_compact_fact_for_evidence(item) for item in facts[:top_k]]
    matched_media = [_compact_media_for_evidence(item) for item in recommended_assets[:3]]
    matched_generic_rules = [_compact_generic_rule_for_evidence(item) for item in generic_rules[:3]]
    provisional_facts = [_compact_fact_for_evidence(item) for item in (provisional_evidence or [])]
    product_structured_facts = [
        _compact_fact_for_evidence(item)
        for item in facts
        if _is_product_structured_fact(item)
    ]
    product_scoped_chunks = [
        _compact_fact_for_evidence(item)
        for item in facts
        if _is_product_scoped_chunk(item)
    ]
    product_media_assets = [_compact_media_for_evidence(item) for item in media_assets[:12]]
    direct_facts = [
        item for item in facts
        if item.get("evidence_allowed_for_direct_answer") is not False
        and _fact_matches_query_type(query_fact_type, item)
        and not item.get("provisional_knowledge_used")
    ]

    missing_fields: list[str] = []
    if query_fact_type and not direct_facts and query_fact_type not in matched_fields:
        missing_fields.append(query_fact_type)
    missing_required_evidence = _missing_required_evidence(
        query_fact_type=query_fact_type,
        direct_facts=direct_facts,
        matched_fields=matched_fields,
        recommended_assets=recommended_assets,
    )

    if direct_facts:
        answerability = "direct_answer"
    elif matched_media and query_fact_type in {"installation", "dimensions", "space_fit", "detachable", "accessories", "packaging"}:
        answerability = "media_supported"
    elif provisional_facts:
        answerability = "provisional_answerable"
    elif matched_generic_rules:
        answerability = "generic_rule_fallback"
    elif structured_profile:
        answerability = "missing_product_fact" if query_fact_type else "product_identified"
    else:
        answerability = "no_product_profile"

    return {
        "identity": identity,
        "resolved_product_identity": _resolved_product_identity(identity, structured_profile),
        "identity_confidence": _identity_confidence(identity, structured_profile),
        "identity_sources": _identity_sources(state, identity),
        "product_identity_resolution": resolution or {},
        "retrieval_query": query or "",
        "query_fact_type": query_fact_type or "",
        "requested_fact_type": query_fact_type or "",
        "answerability": answerability,
        "knowledge_mode": _eval_knowledge_mode(),
        "provisional_knowledge_used": bool(provisional_facts),
        "product_structured_facts": product_structured_facts,
        "product_media_assets": product_media_assets,
        "product_scoped_chunks": product_scoped_chunks,
        "ai_provisional_knowledge": provisional_facts,
        "generic_fallback_rules": matched_generic_rules,
        "missing_required_evidence": missing_required_evidence,
        "evidence_pack_trace": {
            "product_identity_locked": bool(structured_profile),
            "product_identity_resolution": resolution or {},
            "match_reason": (resolution or {}).get("match_reason", ""),
            "candidate_count": len((resolution or {}).get("ambiguous_candidates") or []),
            "ambiguous_candidates": (resolution or {}).get("ambiguous_candidates") or [],
            "unresolved_reason": (resolution or {}).get("unresolved_reason", ""),
            "identity_sources": _identity_sources(state, identity),
            "used_product_fields": matched_fields,
            "structured_fact_count": len(product_structured_facts),
            "media_asset_count": len(product_media_assets),
            "recommended_media_count": len(matched_media),
            "product_scoped_chunk_count": len(product_scoped_chunks),
            "generic_rule_count": len(matched_generic_rules),
            "provisional_knowledge_count": len(provisional_facts),
            "provisional_draft_uids": [item.get("evidence_id") for item in provisional_facts if item.get("evidence_id")],
            "knowledge_mode": _eval_knowledge_mode(),
            "generic_rules_role": "fallback_only",
            "missing_required_evidence": missing_required_evidence,
            "answerability": answerability,
        },
        "matched_fields": matched_fields,
        "missing_fields": missing_fields,
        "matched_facts": matched_facts,
        "matched_media": matched_media,
        "matched_generic_rules": matched_generic_rules,
        "source_priority": ["product_profile", "product_media", "product_knowledge", "faq", "generic_rules"],
    }


def _eval_knowledge_mode() -> str:
    try:
        from app.services.ai_provisional_knowledge_service import current_eval_knowledge_mode
        return current_eval_knowledge_mode()
    except Exception:
        return "verified_only"


def _collect_ai_provisional_evidence(
    *,
    db,
    identity: dict[str, str],
    structured_profile: dict[str, Any],
    query_fact_type: str,
) -> list[dict[str, Any]]:
    try:
        from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService
        return AIProvisionalKnowledgeService().find_eval_evidence(
            db=db,
            i_id=structured_profile.get("i_id") or identity.get("i_id", ""),
            sku_code=identity.get("sku", ""),
            query_fact_type=query_fact_type,
            limit=5,
        )
    except Exception:
        return []


def _resolved_product_identity(identity: dict[str, str], structured_profile: dict[str, Any]) -> dict[str, Any]:
    resolution = identity.get("product_identity_resolution") if isinstance(identity, dict) else {}
    return {
        "product_id": structured_profile.get("product_id"),
        "i_id": structured_profile.get("i_id") or identity.get("i_id", ""),
        "sku": identity.get("sku", ""),
        "sku_family": identity.get("sku_family", ""),
        "product_name": structured_profile.get("product_name") or identity.get("product_name", ""),
        "identity_confidence": (resolution or {}).get("identity_confidence"),
        "identity_sources": (resolution or {}).get("identity_sources") or [],
        "match_reason": (resolution or {}).get("match_reason", ""),
        "unresolved_reason": (resolution or {}).get("unresolved_reason", ""),
    }


def _identity_confidence(identity: dict[str, str], structured_profile: dict[str, Any]) -> float:
    resolution = identity.get("product_identity_resolution") if isinstance(identity, dict) else {}
    if resolution and resolution.get("status") == "resolved":
        return float(resolution.get("identity_confidence") or resolution.get("confidence") or 0.0)
    if not structured_profile:
        return 0.0
    if identity.get("sku") or identity.get("i_id"):
        return 0.95
    if identity.get("product_name"):
        return 0.8
    return 0.5


def _identity_sources(state: dict[str, Any], identity: dict[str, str]) -> list[str]:
    sources: list[str] = []
    resolution = identity.get("product_identity_resolution") if isinstance(identity, dict) else {}
    for source in (resolution or {}).get("identity_sources") or []:
        if source:
            sources.append(str(source))
    slots = state.get("slots") if isinstance(state.get("slots"), dict) else {}
    ctx = state.get("copilot_context") if isinstance(state.get("copilot_context"), dict) else {}
    real_identity = state.get("real_context_product_identity") or ctx.get("real_context_product_identity") or {}
    order_identity = state.get("order_product_identity") if isinstance(state.get("order_product_identity"), dict) else {}
    if identity.get("sku"):
        if slots.get("sku_code"):
            sources.append("slots.sku_code")
        if ctx.get("sku_code"):
            sources.append("copilot_context.sku_code")
        if real_identity.get("sku_code"):
            sources.append("real_context_product_identity.sku_code")
        if order_identity.get("sku_id") or order_identity.get("internal_sku_code"):
            sources.append("order_product_identity.sku")
        if state.get("sku_code"):
            sources.append("state.sku_code")
    if identity.get("i_id"):
        if order_identity.get("i_id") or order_identity.get("internal_product_code"):
            sources.append("order_product_identity.item_id")
        if ctx.get("i_id"):
            sources.append("copilot_context.i_id")
        if real_identity.get("i_id"):
            sources.append("real_context_product_identity.i_id")
        if state.get("i_id"):
            sources.append("state.i_id")
        if identity.get("sku_family"):
            sources.append("sku_family")
    if identity.get("product_name"):
        if state.get("matched_product_name"):
            sources.append("matched_product_name")
        if ctx.get("product_name"):
            sources.append("copilot_context.product_name")
        if real_identity.get("display_product_name") or real_identity.get("product_title"):
            sources.append("real_context_product_identity.product_title")
        if state.get("product_candidates") or ctx.get("product_candidates") or real_identity.get("product_candidates"):
            sources.append("product_candidates")
    return list(dict.fromkeys(sources))


def _is_product_structured_fact(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return (
        bool(metadata.get("structured_profile_fact"))
        or item.get("source_table") == "kb_product"
        or item.get("protocol_source_type") == "product_spec"
    )


def _is_product_media_fact(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return (
        item.get("source_table") == "kb_media_asset"
        or item.get("protocol_source_type") == "media_asset"
        or metadata.get("source_table") == "kb_media_asset"
    )


def _is_product_scoped_chunk(item: dict[str, Any]) -> bool:
    if _is_product_structured_fact(item) or _is_product_media_fact(item):
        return False
    return bool(item.get("product_context_pack")) and item.get("source_type") != "generic_rules"


def _missing_required_evidence(
    *,
    query_fact_type: str,
    direct_facts: list[dict[str, Any]],
    matched_fields: list[str],
    recommended_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    if query_fact_type and not direct_facts and query_fact_type not in matched_fields:
        missing.append({"evidence_type": "product_fact", "fact_type": query_fact_type})
    media_requirement = _required_media_type_for_fact(query_fact_type)
    if media_requirement and not _has_sendable_media_type(recommended_assets, media_requirement):
        missing.append({"evidence_type": "media_asset", "asset_type": media_requirement})
    return missing


def _required_media_type_for_fact(query_fact_type: str) -> str:
    return {
        "installation": "installation_video",
        "dimensions": "size_chart",
        "space_fit": "size_chart",
        "accessories": "accessory_photo",
    }.get(query_fact_type or "", "")


def _normalized_media_type(asset_type: str) -> str:
    return {
        "install_video": "installation_video",
        "install_image": "manual",
        "pack_guide_image": "manual",
        "size_image": "size_chart",
        "accessory_image": "accessory_photo",
        "sku_image": "product_photo",
    }.get(asset_type or "", asset_type or "")


def _has_sendable_media_type(assets: list[dict[str, Any]], required_type: str) -> bool:
    for asset in assets or []:
        if _normalized_media_type(str(asset.get("asset_type") or "")) != required_type:
            continue
        if asset.get("asset_url") and asset.get("auto_send_level", "auto") == "auto":
            return True
    return False


def _matched_profile_fields(
    structured_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    query_fact_type: str,
) -> list[str]:
    fields: list[str] = []
    answerable_fields = structured_profile.get("answerable_fields", []) if isinstance(structured_profile, dict) else []
    requested_sku = str(structured_profile.get("requested_sku") or "").strip() if isinstance(structured_profile, dict) else ""
    has_matching_structured_fact = any(
        _is_product_structured_fact(item) and _fact_matches_query_type(query_fact_type, item)
        for item in facts
    )
    for field in answerable_fields:
        if not query_fact_type or field == query_fact_type:
            if requested_sku and field == query_fact_type and not has_matching_structured_fact:
                continue
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
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    protocol_metadata = {
        key: metadata[key]
        for key in (
            "product_evidence_protocol",
            "structured_profile_fact",
            "verification_status",
            "can_direct_answer",
            "material_provenance",
            "source_table",
            "source_id",
            "source_field_keys",
            "evidence_role",
            "reference_only",
        )
        if key in metadata
    }
    return {
        "evidence_id": item.get("evidence_id") or item.get("chunk_id") or item.get("entry_id"),
        "entry_id": item.get("entry_id"),
        "chunk_id": item.get("chunk_id"),
        "title": item.get("title", ""),
        "source_type": item.get("source_type", ""),
        "evidence_role": item.get("evidence_role") or metadata.get("evidence_role", ""),
        "reference_only": bool(item.get("reference_only") or metadata.get("reference_only")),
        "protocol_source_type": item.get("protocol_source_type", ""),
        "source_table": item.get("source_table", ""),
        "source_id": item.get("source_id", ""),
        "source_version": item.get("source_version", 0),
        "source_updated_at": item.get("source_updated_at", ""),
        "value_sha256": item.get("value_sha256", ""),
        "verification_status": item.get("verification_status", ""),
        "provisional_knowledge_used": bool(item.get("provisional_knowledge_used")),
        "provisional_draft_uid": item.get("provisional_draft_uid", ""),
        "usable_for_eval": bool(item.get("usable_for_eval", False)),
        "usable_for_auto_send": bool(item.get("usable_for_auto_send", True)),
        "can_direct_answer": item.get("can_direct_answer", item.get("evidence_allowed_for_direct_answer") is not False),
        "needs_human_review": bool(item.get("needs_human_review")),
        "block_reasons": item.get("block_reasons", []),
        "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or "",
        "attribute_key": item.get("attribute_key") or item.get("field_name") or item.get("fact_key") or "",
        "score": item.get("rerank_score", item.get("score", 0)),
        "direct_answer_allowed": item.get("evidence_allowed_for_direct_answer") is not False,
        "customer_text": item.get("customer_text") or text,
        "chunk_text": text,
        "sku_scope": list(item.get("sku_scope") or []),
        "product_scope": list(item.get("product_scope") or []),
        "material_provenance": item.get("material_provenance") or metadata.get("material_provenance", ""),
        "metadata": protocol_metadata,
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
    asset_type = item.get("asset_type", "")
    auto_send_level = item.get("auto_send_level", "auto")
    asset_url = item.get("asset_url", "")
    return {
        "evidence_id": f"kbmedia:{item.get('asset_id') or item.get('id')}",
        "asset_id": item.get("asset_id") or item.get("id"),
        "source_table": "kb_media_asset",
        "verification_status": "verified",
        "can_direct_answer": auto_send_level == "auto" and bool(asset_url),
        "asset_type": asset_type,
        "evidence_media_type": _normalized_media_type(str(asset_type or "")),
        "asset_title": item.get("asset_title", ""),
        "product_name": item.get("product_name", ""),
        "send_strategy": item.get("send_strategy", ""),
        "confidence": item.get("match_confidence", item.get("score", 0)),
        "approved": True,
        "usable": True,
        "auto_send_level": auto_send_level,
        "has_asset_url": bool(asset_url),
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


def _find_kb_product(db, KBProduct, identity: dict[str, str]):
    sku = identity.get("sku", "")
    i_id = identity.get("i_id", "")
    sku_family = identity.get("sku_family", "")
    product_name = identity.get("product_name", "")
    if i_id:
        product = (
            db.query(KBProduct)
            .filter(KBProduct.i_id == i_id)
            .filter(KBProduct.status == "published")
            .first()
        )
        if product:
            return product
    for code in (sku, sku_family):
        if not code:
            continue
        product = (
            db.query(KBProduct)
            .filter(KBProduct.i_id == code)
            .filter(KBProduct.status == "published")
            .first()
        )
        if product:
            return product

    products = _candidate_kb_products(db, KBProduct, identity)
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


def _candidate_kb_products(db, KBProduct, identity: dict[str, str]) -> list[Any]:
    seen: set[Any] = set()
    rows: list[Any] = []

    def add(query) -> None:
        for product in query.limit(30).all():
            product_id = getattr(product, "id", None)
            if product_id in seen:
                continue
            seen.add(product_id)
            rows.append(product)

    base = db.query(KBProduct).filter(KBProduct.status == "published")
    for code in (identity.get("sku", ""), identity.get("sku_family", ""), identity.get("i_id", "")):
        code = str(code or "").strip()
        if not code:
            continue
        add(base.filter(KBProduct.i_id == code))
        add(base.filter(KBProduct.sku_list_json.like(f"%{code}%")))
    product_name = str(identity.get("product_name") or "").strip()
    if product_name:
        add(base.filter(KBProduct.product_name.like(f"%{product_name}%")))
    return rows


def _build_structured_profile(product, *, requested_sku: str = "") -> dict[str, Any]:
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
        "source_version": int(product.version or 0),
        "source_updated_at": product.updated_at.isoformat() if product.updated_at else "",
        "requested_sku": str(requested_sku or "").strip(),
        "completeness_score": product.completeness_score,
        "missing_fields": product.get_missing_fields(),
    }
    profile["answerable_fields"] = _answerable_fields(specs, logistics, warranty, sku_list)
    return profile


def _clean_mapping(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for key, val in value.items():
        if str(key).startswith("_") or str(key) == "trusted_auto_backfill":
            continue
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
                and str(k) in {
                    "sku_code", "sku_id", "sku_name", "name", "color", "size", "spec",
                    "enabled", "properties", "sku_variant_key", "gross_weight_kg",
                    "gross_weight", "package_weight", "net_weight_kg", "carton_length_cm",
                    "carton_width_cm", "carton_height_cm", "packaging", "barcode_69",
                }
            }
            if compact:
                cleaned.append(compact)
        elif item:
            cleaned.append({"sku_code": str(item)})
    return cleaned


def _answerable_fields(
    specs: dict[str, Any],
    logistics: dict[str, Any],
    warranty: dict[str, Any],
    sku_list: list[dict[str, Any]] | None = None,
) -> list[str]:
    haystack = {str(k).lower(): v for k, v in {**specs, **logistics, **warranty}.items()}
    for item in sku_list or []:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if value not in (None, "", [], {}, "-"):
                haystack[f"sku_list.{key}".lower()] = value
    mapping = {
        "material": ("material", "材质", "材料", "用料"),
        "dimensions": ("size", "尺寸", "长宽高", "height", "width", "length"),
        "space_fit": ("size", "尺寸", "长宽高", "height", "width", "length"),
        "placement_scene": ("usage_scene", "scene", "room", "适用场景", "摆放", "卧室", "客厅", "书房", "厨房", "阳台"),
        "load_capacity": ("load_capacity", "承重", "载重"),
        "gross_weight": ("gross_weight", "gross_weight_kg", "package_weight", "product_weight", "weight", "毛重", "包装重量", "商品重量"),
        "installation": ("install_method", "installation", "安装", "组装方式"),
        "accessory_availability": ("accessory_availability", "accessory_purchase", "accessory_sale", "spare_part_purchase", "配件售卖", "配件补购", "配件单卖"),
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
    requested = query_fact_type or _infer_profile_fact_type_from_query(query)
    if not requested:
        return []
    protocol_candidates = build_product_spec_evidence_candidates(
        profile,
        requested_fact_type=requested,
    )
    if not protocol_candidates:
        return []

    protocol = protocol_candidates[0]
    body = str(protocol.get("customer_text") or protocol.get("value") or "").strip()
    title = f"{profile.get('product_name') or '当前商品'}商品资料"
    text_score = _text_overlap_score(query, title, body)
    return [{
        "score": round(18.0 + text_score, 4),
        "text_score": round(text_score, 4),
        "vector_score": 0.0,
        "scope_score": 1.0,
        "source_confidence": float(protocol.get("source_confidence") or 0.85),
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
        "metadata": {
            "source": "kb_product.specs",
            "structured_profile_fact": True,
            "product_evidence_protocol": True,
            "source_table": protocol.get("source_table", "kb_product"),
            "source_id": protocol.get("source_id", ""),
            "source_field_keys": protocol.get("source_field_keys", []),
            "source_version": protocol.get("source_version", 0),
            "source_updated_at": protocol.get("source_updated_at", ""),
            "value_sha256": protocol.get("value_sha256", ""),
            "material_provenance": protocol.get("material_provenance", ""),
            "verification_status": protocol.get("verification_status", ""),
            "can_direct_answer": bool(protocol.get("can_direct_answer")),
            "needs_human_review": bool(protocol.get("needs_human_review")),
            "block_reasons": protocol.get("block_reasons", []),
        },
        "semantic_alignment": _direct_semantic_alignment(requested, requested),
        "entry_status": "published",
        "index_status": "ready",
        "entry_risk_level": "low",
        "source_sheet": "",
        "row_number": 0,
        "sku_scope": list(protocol.get("sku_scope") or []),
        "product_scope": [profile.get("i_id", ""), profile.get("product_name", "")],
        "product_context_pack": True,
        "evidence_id": protocol.get("evidence_id", f"kbproduct:{profile.get('product_id')}:{requested}"),
        "protocol_source_type": protocol.get("source_type", "product_spec"),
        "source_table": protocol.get("source_table", "kb_product"),
        "source_id": protocol.get("source_id", ""),
        "source_version": protocol.get("source_version", 0),
        "source_updated_at": protocol.get("source_updated_at", ""),
        "value_sha256": protocol.get("value_sha256", ""),
        "requested_fact_type": protocol.get("requested_fact_type", requested),
        "verification_status": protocol.get("verification_status", ""),
        "material_provenance": protocol.get("material_provenance", ""),
        "can_direct_answer": bool(protocol.get("can_direct_answer")),
        "needs_human_review": bool(protocol.get("needs_human_review")),
        "block_reasons": protocol.get("block_reasons", []),
        "customer_text": body,
        "evidence_allowed_for_direct_answer": True,
        "evidence_allowed_for_exact_answer": True,
    }]


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


def _infer_profile_fact_type_from_query(query: str) -> str:
    text = str(query or "")
    cues = (
        ("space_fit", ("放得下", "放的下", "摆得下", "摆的下", "空间够", "够不够放", "几平方", "平方", "占空间", "占地方", "预留")),
        ("placement_scene", ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放")),
        ("installation", ("安装", "组装", "怎么装", "打孔", "租房")),
        ("detachable", ("可拆", "拆卸", "拆开", "拆下来", "能拆")),
        ("odor", ("味道", "气味", "异味", "刺鼻", "散味", "闻着")),
        ("material", ("材质", "材料", "用料", "防潮", "受潮")),
        ("gross_weight", ("毛重", "包装重量", "商品重量", "多重", "几斤", "几公斤", "gross_weight", "package_weight")),
        ("accessory_availability", ("配件有卖", "篮子有卖", "零件有卖", "配件单独买", "单独购买", "配件补买", "配件补购", "配件售卖")),
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
    if any(term in msg for term in ("图片", "照片", "图", "外观", "颜色", "样子", "实物")):
        return ["sku_image", "size_image"]
    return []


def _media_tag_priority(query_fact_type: str) -> list[str]:
    return {
        "detachable": ["detachable", "拆卸", "可拆", "拆装", "dimensions", "尺寸"],
        "dimensions": ["dimensions", "尺寸", "size", "规格"],
        "space_fit": ["dimensions", "尺寸", "size", "规格", "space_fit", "空间"],
        "installation": ["installation", "安装", "install", "video", "教程"],
        "accessories": ["accessories", "配件", "零件", "parts"],
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
    if query_fact_type not in {"detachable", "dimensions", "space_fit", "installation", "accessories"}:
        return []
    if not recommended_assets:
        return []
    asset = recommended_assets[0]
    if query_fact_type in {"dimensions", "space_fit"}:
        from app.services.media_asset_service import is_delivery_media_asset_eligible

        identity = {
            "product_id": profile.get("product_id"),
            "i_id": profile.get("i_id"),
            "sku_code": profile.get("sku_code"),
        }
        if not is_delivery_media_asset_eligible(
            asset,
            query_fact_type=query_fact_type,
            product_identity=identity,
        ):
            return []
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
        "source_type": "media_reference",
        "evidence_role": "media_reference",
        "reference_only": True,
        "intent": "product_question",
        "category": "structured_profile_media",
        "category_l3": query_fact_type,
        "fact_type": query_fact_type,
        "evidence_fact_type": query_fact_type,
        "metadata": {
            "source": "kb_media_asset",
            "product_evidence_protocol": True,
            "evidence_role": "media_reference",
            "reference_only": True,
            "source_table": "kb_media_asset",
            "source_id": str(asset_id),
            "verification_status": "verified",
            "can_direct_answer": False,
            "needs_human_review": True,
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
        "evidence_id": chunk_id,
        "protocol_source_type": "media_reference",
        "source_table": "kb_media_asset",
        "source_id": str(asset_id),
        "requested_fact_type": query_fact_type,
        "verification_status": "verified",
        "can_direct_answer": False,
        "needs_human_review": True,
        "media_asset_id": asset_id,
        "media_url": asset.get("asset_url", ""),
        "block_reasons": [],
        "customer_text": body,
        "evidence_allowed_for_direct_answer": False,
        "evidence_allowed_for_exact_answer": False,
    }]


def _state_identity(state: dict) -> dict[str, str]:
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots") or {}
    ctx = state.get("copilot_context") or {}
    real_identity = (
        state.get("real_context_product_identity")
        or ctx.get("real_context_product_identity")
        or {}
    )
    candidates = [
        *(state.get("product_candidates") or []),
        *(ctx.get("product_candidates") or []),
        *(real_identity.get("product_candidates") or []),
    ]
    sku = (
        slots.get("sku_code")
        or ctx.get("sku_code")
        or real_identity.get("sku_code")
        or identity.get("sku_id")
        or identity.get("internal_sku_code")
        or state.get("sku_code")
        or ""
    )
    i_id = (
        identity.get("i_id")
        or identity.get("internal_product_code")
        or ctx.get("i_id")
        or real_identity.get("i_id")
        or _sku_family(sku)
        or state.get("i_id")
        or ""
    )
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or ctx.get("product_name")
        or real_identity.get("display_product_name")
        or real_identity.get("product_title")
        or real_identity.get("order_product_title")
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


def _resolve_identity_for_pack(state: dict, identity: dict[str, str]) -> dict[str, Any]:
    signals = _identity_resolution_signals(state, identity)
    if not any(signals.get(key) for key in ("sku_id", "internal_i_id", "platform_product_id", "platform_product_id_hash", "product_url", "platform_title")):
        return {**identity, "product_identity_resolution": {"status": "not_found", "unresolved_reason": "no_identity_signal"}}
    try:
        from app.services.product_identity_resolver import ProductIdentityResolver
        resolution = ProductIdentityResolver().resolve(**signals)
    except Exception as exc:
        return {
            **identity,
            "product_identity_resolution": {
                "status": "error",
                "unresolved_reason": f"resolver_failed:{type(exc).__name__}",
            },
        }

    status = resolution.get("status")
    if status == "resolved":
        sku = resolution.get("sku_code") or resolution.get("sku_id") or identity.get("sku", "")
        i_id = resolution.get("i_id") or resolution.get("internal_i_id") or identity.get("i_id", "")
        return {
            **identity,
            "sku": str(sku or "").strip(),
            "sku_family": _sku_family(str(sku or "")),
            "i_id": str(i_id or "").strip(),
            "product_name": (
                resolution.get("display_product_name")
                or resolution.get("matched_product_title")
                or resolution.get("canonical_product_name")
                or identity.get("product_name", "")
            ),
            "resolved_product_id": resolution.get("resolved_product_id"),
            "product_identity_resolution": resolution,
        }
    if status == "ambiguous":
        return {
            "sku": "",
            "sku_family": "",
            "i_id": "",
            "product_name": "",
            "product_identity_resolution": resolution,
        }
    return {**identity, "product_identity_resolution": resolution}


def _identity_resolution_signals(state: dict, identity: dict[str, str]) -> dict[str, Any]:
    slots = state.get("slots") if isinstance(state.get("slots"), dict) else {}
    ctx = state.get("copilot_context") if isinstance(state.get("copilot_context"), dict) else {}
    real_identity = state.get("real_context_product_identity") or ctx.get("real_context_product_identity") or {}
    real_context = ctx.get("real_context") if isinstance(ctx.get("real_context"), dict) else {}
    product = real_context.get("product") if isinstance(real_context.get("product"), dict) else {}
    order = real_context.get("order") if isinstance(real_context.get("order"), dict) else {}
    candidates = [
        *(state.get("product_candidates") or []),
        *(ctx.get("product_candidates") or []),
        *(real_identity.get("product_candidates") or []),
    ]
    sku = identity.get("sku") or slots.get("sku_code") or ctx.get("sku_code") or real_identity.get("sku_code") or ""
    i_id = identity.get("i_id") or ctx.get("i_id") or real_identity.get("i_id") or product.get("i_id") or ""
    product_url = (
        product.get("product_url")
        or ctx.get("product_url")
        or real_identity.get("product_url")
        or _first_candidate_value(candidates, keys=("product_url",), types=("product_url",))
    )
    platform_item_id = (
        _platform_item_id(product.get("item_id"))
        or _platform_item_id(real_identity.get("item_id"))
        or _platform_item_id(_first_candidate_value(candidates, keys=("item_id",), types=("platform_product_id",)))
    )
    platform_item_id_hash = (
        _platform_item_hash(product.get("item_id_hash"))
        or _platform_item_hash(ctx.get("item_id_hash"))
        or _platform_item_hash(real_identity.get("item_id_hash"))
        or _platform_item_hash(_first_candidate_value(candidates, keys=("item_id_hash", "platform_item_id_hash", "value"), types=("platform_product_id", "platform_item_id_hash")))
    )
    title = (
        identity.get("product_name")
        or product.get("product_title")
        or order.get("order_product_title")
        or ctx.get("display_product_name")
        or ctx.get("platform_product_title")
        or real_identity.get("product_title")
        or real_identity.get("order_product_title")
        or _first_candidate_value(candidates, keys=("product_name", "title", "name", "value"), types=("product_title", "order_product_title", "product_name"))
        or ""
    )
    return {
        "platform_product_id": platform_item_id,
        "platform_product_id_hash": platform_item_id_hash,
        "product_url": str(product_url or ""),
        "platform_title": str(title or ""),
        "product_candidates": candidates,
        "internal_i_id": str(i_id or ""),
        "sku_id": str(sku or ""),
        "customer_message": str(state.get("customer_message") or state.get("normalized_message") or ""),
    }


def _platform_item_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or "REDACTED" in text:
        return ""
    if text.isdigit():
        return text
    try:
        from app.services.product_identity_resolver import _extract_product_id_from_url
        return _extract_product_id_from_url(text)
    except Exception:
        return ""


def _platform_item_hash(value: Any) -> str:
    text = str(value or "").strip()
    if not text or "REDACTED" in text:
        return ""
    if re.fullmatch(r"[0-9a-fA-F]{8,64}", text):
        return text.lower()
    return ""


def _first_candidate_value(candidates: list[Any], *, keys: tuple[str, ...], types: tuple[str, ...]) -> str:
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        candidate_type = str(candidate.get("type") or "").lower()
        if types and not any(t in candidate_type for t in types):
            continue
        for key in keys:
            value = str(candidate.get(key) or "").strip()
            if value:
                return value
    return ""


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


def _identity_scope_terms(identity: dict[str, str], structured_profile: dict[str, Any] | None = None) -> list[str]:
    structured_profile = structured_profile or {}
    terms = [
        identity.get("sku", ""),
        identity.get("sku_family", ""),
        identity.get("i_id", ""),
        identity.get("product_name", ""),
        structured_profile.get("i_id", ""),
        structured_profile.get("product_name", ""),
    ]
    return list(dict.fromkeys(str(term or "").strip() for term in terms if str(term or "").strip()))


def _knowledge_scope_filter(KnowledgeChunk, KnowledgeEntry, identity: dict[str, str], structured_profile: dict[str, Any]):
    from sqlalchemy import or_

    conditions = []
    product_id = structured_profile.get("product_id")
    if product_id:
        conditions.append(KnowledgeEntry.product_id == str(product_id))
    for term in _identity_scope_terms(identity, structured_profile):
        like = f"%{term}%"
        conditions.extend([
            KnowledgeChunk.product_scope_json.like(like),
            KnowledgeChunk.sku_scope_json.like(like),
            KnowledgeEntry.product_scope_json.like(like),
            KnowledgeEntry.sku_scope_json.like(like),
            KnowledgeEntry.product_id.like(like),
            KnowledgeEntry.sku_id.like(like),
            KnowledgeEntry.title.like(like),
        ])
    if not conditions:
        return None
    return or_(*conditions)


def _qa_scope_filter(KBQA, identity: dict[str, str], structured_profile: dict[str, Any]):
    from sqlalchemy import or_

    conditions = []
    product_id = structured_profile.get("product_id")
    if product_id:
        conditions.append(KBQA.product_id == product_id)
    for term in _identity_scope_terms(identity, structured_profile):
        like = f"%{term}%"
        conditions.extend([
            KBQA.sku_codes_json.like(like),
            KBQA.question.like(like),
        ])
    if not conditions:
        return None
    return or_(*conditions)


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
