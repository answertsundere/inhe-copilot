"""Unified answer trace helpers.

This module does not retrieve evidence or make business decisions. It only
normalizes the evidence and audit metadata that earlier nodes already produced
so the final API response has one stable trace shape.
"""

from __future__ import annotations

from typing import Any

from app import config


def build_answer_trace(response: dict[str, Any], *, customer_message: str = "") -> dict[str, Any]:
    response = normalize_answer_trace_inputs(response)
    debug = response.get("evidence_debug") or {}
    existing_trace = (
        response.get("answer_trace")
        or debug.get("answer_trace")
        or {}
    )
    composition = (
        debug.get("answer_composition_trace")
        or response.get("answer_composition_trace")
        or {}
    )
    grouping = debug.get("evidence_grouping") or response.get("evidence_grouping") or {}
    coverage = grouping.get("coverage") if isinstance(grouping, dict) else {}
    context_used = response.get("context_used") or {}
    product_pack = context_used.get("product_context_pack") if isinstance(context_used, dict) else {}
    if not isinstance(product_pack, dict):
        product_pack = response.get("product_context_pack") or {}
    product_pack_summary = debug.get("product_context_pack_summary") or {}
    query_fact_type = str(debug.get("query_fact_type") or response.get("query_fact_type") or "")
    secondary_fact_types = [
        str(item)
        for item in (
            debug.get("secondary_fact_types")
            or response.get("secondary_fact_types")
            or []
        )
        if str(item or "").strip()
    ]
    required_fact_types = _ordered_unique([
        *(coverage.get("required_fact_types") or [] if isinstance(coverage, dict) else []),
        *(composition.get("required_fact_types") or [] if isinstance(composition, dict) else []),
        query_fact_type,
        *secondary_fact_types,
    ])
    selected_assets = _asset_summaries([
        *(response.get("selected_assets") or []),
        *(response.get("recommended_assets") or []),
        *(debug.get("selected_assets") or []),
        *(product_pack.get("recommended_assets") or []),
        *(product_pack_summary.get("recommended_assets") or [] if isinstance(product_pack_summary, dict) else []),
        *(product_pack_summary.get("media_assets") or [] if isinstance(product_pack_summary, dict) else []),
    ])
    rag_evidence_used = _rag_evidence_used(debug, composition, product_pack_summary, required_fact_types)
    evidence_rerank = debug.get("evidence_rerank") or response.get("evidence_rerank") or {}
    selected_evidence_trace = _evidence_trace_summaries(
        (evidence_rerank.get("selected_evidence") if isinstance(evidence_rerank, dict) else None)
        or debug.get("selected_evidence")
        or response.get("selected_evidence")
        or [],
        selected_default=True,
    )
    rejected_evidence_trace = _evidence_trace_summaries(
        (evidence_rerank.get("rejected_evidence") if isinstance(evidence_rerank, dict) else None)
        or debug.get("rejected_evidence")
        or response.get("rejected_evidence")
        or [],
        selected_default=False,
    )
    composition_evidence_answered_fact_types = _ordered_unique(
        composition.get("evidence_answered_fact_types") or []
        if isinstance(composition, dict) else []
    )
    rag_evidence_answered_fact_types = _ordered_unique(list(rag_evidence_used.keys()))
    evidence_answered_fact_types = _ordered_unique([
        *composition_evidence_answered_fact_types,
        *rag_evidence_answered_fact_types,
    ])
    answered_fact_types = _ordered_unique(
        (composition.get("answered_fact_types") or composition.get("covered_fact_types") or [])
        if isinstance(composition, dict) else []
    )
    answered_fact_types = _ordered_unique([*answered_fact_types, *rag_evidence_answered_fact_types])
    rerank_trace = (
        evidence_rerank.get("rerank_trace", []) if isinstance(evidence_rerank, dict)
        else debug.get("rerank_trace", [])
    )
    if not rerank_trace:
        rerank_trace = _fallback_rerank_trace(selected_evidence_trace, rejected_evidence_trace)
    trace = {
        "mode": _trace_mode(response, composition, selected_assets, evidence_answered_fact_types),
        "trace_contract_broken": not bool(query_fact_type),
        "trace_contract_reason": "" if query_fact_type else "missing_query_fact_type",
        "customer_message": customer_message or debug.get("current_query") or response.get("current_query", ""),
        "query_fact_type": query_fact_type,
        "secondary_fact_types": secondary_fact_types,
        "required_fact_types": required_fact_types,
        "answered_fact_types": answered_fact_types,
        "evidence_answered_fact_types": evidence_answered_fact_types,
        "fallback_fact_types": _ordered_unique(
            composition.get("fallback_fact_types") or []
            if isinstance(composition, dict) else []
        ),
        "needs_followup_fact_types": _ordered_unique(
            composition.get("needs_followup_fact_types") or []
            if isinstance(composition, dict) else []
        ),
        "product_card_evidence_used": _dict_or_empty(composition.get("product_card_evidence_used") if isinstance(composition, dict) else {}),
        "rag_evidence_used": rag_evidence_used,
        "media_evidence_used": _dict_or_empty(composition.get("media_evidence_used") if isinstance(composition, dict) else {}),
        "asset_evidence_used": _dict_or_empty(composition.get("asset_evidence_used") if isinstance(composition, dict) else {}),
        "retrieved_evidence_count": len(debug.get("retrieved_chunks_summary") or response.get("retrieved_chunks") or []),
        "selected_evidence_count": len(selected_evidence_trace),
        "rejected_evidence_count": len(rejected_evidence_trace),
        "selected_evidence": selected_evidence_trace,
        "rejected_evidence": rejected_evidence_trace,
        "selected_evidence_by_fact_type": _evidence_by_fact_type(selected_evidence_trace),
        "rejected_evidence_by_fact_type": _evidence_by_fact_type(rejected_evidence_trace),
        "rerank_trace": rerank_trace,
        "embedding_rerank_enabled": (
            bool(evidence_rerank.get("embedding_rerank_enabled")) if isinstance(evidence_rerank, dict) and evidence_rerank
            else bool(debug.get("embedding_rerank_enabled") or existing_trace.get("embedding_rerank_enabled") or config.EVIDENCE_EMBEDDING_RERANK_ENABLED)
        ),
        "embedding_rerank_used": (
            bool(evidence_rerank.get("embedding_rerank_used")) if isinstance(evidence_rerank, dict) and evidence_rerank
            else bool(debug.get("embedding_rerank_used") or existing_trace.get("embedding_rerank_used"))
        ),
        "embedding_provider": (
            evidence_rerank.get("embedding_provider", "disabled") if isinstance(evidence_rerank, dict) and evidence_rerank
            else debug.get("embedding_provider", existing_trace.get("embedding_provider", config.EVIDENCE_EMBEDDING_RERANK_PROVIDER if config.EVIDENCE_EMBEDDING_RERANK_ENABLED else "disabled"))
        ),
        "embedding_fallback_used": (
            bool(evidence_rerank.get("embedding_fallback_used")) if isinstance(evidence_rerank, dict) and evidence_rerank
            else bool(debug.get("embedding_fallback_used") or existing_trace.get("embedding_fallback_used"))
        ),
        "embedding_error": (
            evidence_rerank.get("embedding_error", "") if isinstance(evidence_rerank, dict) and evidence_rerank
            else debug.get("embedding_error", existing_trace.get("embedding_error", ""))
        ),
        "evidence_rerank_summary": (
            evidence_rerank.get("embedding_rerank_summary", {}) if isinstance(evidence_rerank, dict) and evidence_rerank
            else existing_trace.get("evidence_rerank_summary", {})
        ),
        "top_reject_reasons": _top_reject_reasons(rejected_evidence_trace),
        "evidence_origin_by_fact_type": (
            evidence_rerank.get("evidence_origin_by_fact_type", {}) if isinstance(evidence_rerank, dict)
            else debug.get("evidence_origin_by_fact_type", {})
        ),
        "selected_assets": selected_assets,
        "generic_rule_used": _generic_rule(response, debug),
        "final_audit": _audit_summary(response),
        "final_semantic_fit_audit": _semantic_audit_summary(response),
        "semantic_compiler_result": _semantic_compiler_summary(response),
        "answer_blocks": _answer_block_summaries(response, debug),
        "renderer_used": bool((response.get("semantic_compiler_result") or {}).get("renderer_used")),
        "blocked_raw_text": (response.get("semantic_compiler_result") or {}).get("blocked_raw_text", ""),
        "final_quality_pass": bool(response.get("final_quality_pass")),
        "reject_reason": (response.get("semantic_compiler_result") or {}).get("reject_reason", []),
        "rewrite_applied": _rewrite_applied(response),
        "reply_blocks": _reply_block_summaries(response.get("reply_blocks") or []),
        "reply_delivery": response.get("reply_delivery") or {},
    }
    if not trace["media_evidence_used"]:
        trace["media_evidence_used"] = _media_evidence_from_pack(product_pack)
    if not trace["media_evidence_used"] and isinstance(product_pack_summary, dict):
        trace["media_evidence_used"] = _media_evidence_from_pack(product_pack_summary)
    if not trace["asset_evidence_used"]:
        trace["asset_evidence_used"] = _asset_evidence_from_assets(selected_assets, required_fact_types)
    if not trace["selected_assets"]:
        trace["selected_assets"] = _asset_summaries(product_pack.get("selected_assets") or [])
    return trace


def normalize_answer_trace_inputs(response: dict[str, Any]) -> dict[str, Any]:
    """Preserve the fact-type contract from upstream understanding nodes.

    Evidence is not a valid source for the customer's intent. If the upstream
    contract is missing, leave it missing so trace/audit can expose the break
    instead of turning a retrieved evidence type into the query fact type.
    """
    if not isinstance(response, dict):
        return response
    debug = response.setdefault("evidence_debug", {})
    if not isinstance(debug, dict):
        debug = {}
        response["evidence_debug"] = debug

    query_fact_type = _recover_query_fact_type(response, debug)
    if query_fact_type:
        if not str(response.get("query_fact_type") or "").strip():
            response["query_fact_type"] = query_fact_type
        if not str(debug.get("query_fact_type") or "").strip():
            debug["query_fact_type"] = query_fact_type

    required_fact_types = _recover_required_fact_types(response, debug, query_fact_type)
    if required_fact_types:
        if not response.get("required_fact_types"):
            response["required_fact_types"] = required_fact_types
        if not debug.get("required_fact_types"):
            debug["required_fact_types"] = required_fact_types
        grouping = debug.setdefault("evidence_grouping", {})
        if isinstance(grouping, dict):
            coverage = grouping.setdefault("coverage", {})
            if isinstance(coverage, dict) and not coverage.get("required_fact_types"):
                coverage["required_fact_types"] = required_fact_types

    return response


def attach_answer_trace(response: dict[str, Any], *, customer_message: str = "") -> dict[str, Any]:
    response = normalize_answer_trace_inputs(response)
    trace = build_answer_trace(response, customer_message=customer_message)
    response["answer_trace"] = trace
    response.setdefault("evidence_debug", {})["answer_trace"] = trace
    return response


def _trace_mode(
    response: dict[str, Any],
    composition: dict[str, Any],
    selected_assets: list[dict[str, Any]],
    evidence_answered_fact_types: list[str],
) -> str:
    generation_mode = str(response.get("generation_mode") or "")
    if "audit" in generation_mode:
        return "final_audit_rewrite"
    requires_human_review = bool(response.get("requires_human_review"))
    if selected_assets:
        if requires_human_review:
            return "mixed_with_human_review"
        return "media_answer"
    if evidence_answered_fact_types:
        if requires_human_review:
            return "mixed_with_human_review"
        return "evidence_answer"
    if response.get("generic_service_rule_used") or (response.get("evidence_debug") or {}).get("generic_service_rule_used"):
        return "generic_rule_fallback"
    if requires_human_review:
        return "human_followup"
    return str(composition.get("mode") or "mixed") if isinstance(composition, dict) else "mixed"


def _ordered_unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _recover_query_fact_type(response: dict[str, Any], debug: dict[str, Any]) -> str:
    candidates: list[Any] = [
        debug.get("query_fact_type"),
        response.get("query_fact_type"),
        (debug.get("query_understanding") or {}).get("query_fact_type")
        if isinstance(debug.get("query_understanding"), dict) else "",
        (response.get("query_understanding") or {}).get("query_fact_type")
        if isinstance(response.get("query_understanding"), dict) else "",
        (debug.get("product_context_pack_stats") or {}).get("query_fact_type")
        if isinstance(debug.get("product_context_pack_stats"), dict) else "",
        (response.get("product_context_pack_stats") or {}).get("query_fact_type")
        if isinstance(response.get("product_context_pack_stats"), dict) else "",
    ]
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _recover_required_fact_types(
    response: dict[str, Any],
    debug: dict[str, Any],
    query_fact_type: str,
) -> list[str]:
    grouping = debug.get("evidence_grouping") or response.get("evidence_grouping") or {}
    coverage = grouping.get("coverage") if isinstance(grouping, dict) else {}
    composition = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    stats_debug = debug.get("product_context_pack_stats") or {}
    stats_response = response.get("product_context_pack_stats") or {}
    query_understanding = debug.get("query_understanding") or response.get("query_understanding") or {}
    return _ordered_unique([
        *(coverage.get("required_fact_types") or [] if isinstance(coverage, dict) else []),
        *(composition.get("required_fact_types") or [] if isinstance(composition, dict) else []),
        *(debug.get("required_fact_types") or []),
        *(response.get("required_fact_types") or []),
        *(query_understanding.get("required_fact_types") or [] if isinstance(query_understanding, dict) else []),
        *(stats_debug.get("required_fact_types") or [] if isinstance(stats_debug, dict) else []),
        *(stats_response.get("required_fact_types") or [] if isinstance(stats_response, dict) else []),
        query_fact_type,
    ])


def _rag_evidence_used(
    debug: dict[str, Any],
    composition: dict[str, Any],
    product_pack_summary: dict[str, Any],
    required_fact_types: list[str],
) -> dict[str, list[dict[str, Any]]]:
    allowed_fact_types = set(required_fact_types or [])
    if not allowed_fact_types:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str, str]] = set()

    def add_items(
        items: Any,
        *,
        source_bucket: str,
        selected_by_container: bool = False,
        excluded_origins: set[str] | None = None,
    ) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            origin = str(item.get("evidence_origin") or "").strip()
            if excluded_origins and origin in excluded_origins:
                continue
            if item.get("selected") is False:
                continue
            if not selected_by_container and item.get("selected") is not True:
                continue
            fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "").strip()
            if not fact_type or fact_type not in allowed_fact_types:
                continue
            source_type = str(item.get("source_type") or source_bucket or "").strip()
            summary = _knowledge_evidence_summary(item, fact_type, source_type)
            dedupe_key = (
                fact_type,
                str(summary.get("entry_id") or ""),
                str(summary.get("chunk_id") or ""),
                str(summary.get("evidence_id") or ""),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.setdefault(fact_type, []).append(summary)

    add_items(debug.get("selected_evidence"), source_bucket="selected_evidence", selected_by_container=True)
    add_items(debug.get("retrieved_chunks_summary"), source_bucket="retrieved_chunks_summary")
    if isinstance(composition, dict):
        evidence_used_by_fact_type = composition.get("evidence_used_by_fact_type") or {}
        if isinstance(evidence_used_by_fact_type, dict):
            for fact_type, items in evidence_used_by_fact_type.items():
                if not isinstance(items, list):
                    continue
                normalized_items = [
                    {**item, "fact_type": item.get("fact_type") or fact_type}
                    for item in items
                    if isinstance(item, dict)
                ]
                add_items(
                    normalized_items,
                    source_bucket="answer_composition_trace",
                    selected_by_container=True,
                    excluded_origins={"product_card", "product_media"},
                )

    evidence_pack = {}
    if isinstance(product_pack_summary, dict):
        evidence_pack = product_pack_summary.get("evidence_pack") or {}
    if isinstance(evidence_pack, dict):
        add_items(evidence_pack.get("matched_facts"), source_bucket="product_context_pack", selected_by_container=True)
        add_items(evidence_pack.get("evidence_evaluation"), source_bucket="product_context_pack")

    return result


def _knowledge_evidence_summary(item: dict[str, Any], fact_type: str, source_type: str) -> dict[str, Any]:
    text = str(
        item.get("preview")
        or item.get("chunk_preview")
        or item.get("text")
        or item.get("chunk_text")
        or item.get("content")
        or item.get("fact")
        or ""
    ).strip()
    return {
        "entry_id": item.get("entry_id", ""),
        "chunk_id": item.get("chunk_id", ""),
        "evidence_id": item.get("evidence_id") or item.get("id") or item.get("fact_id") or "",
        "fact_type": fact_type,
        "source_type": source_type,
        "title": item.get("title") or item.get("matched_title") or "",
        "score": item.get("score") or item.get("rerank_score") or item.get("relevance_score") or 0,
        "preview": text[:160],
    }


def _asset_summaries(values: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in values or []:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("asset_id") or item.get("id") or "").strip()
        asset_type = str(item.get("asset_type") or item.get("type") or "").strip()
        asset_url = str(item.get("asset_url") or item.get("url") or item.get("media_url") or item.get("thumbnail_url") or "").strip()
        if not asset_id and not asset_type and not asset_url:
            continue
        key = (asset_id, asset_type, asset_url.split("?", 1)[0].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "asset_id": asset_id,
            "asset_type": asset_type,
            "asset_title": item.get("asset_title") or item.get("title") or "",
            "asset_url": asset_url,
            "product_name": item.get("product_name") or "",
            "send_mode": item.get("send_mode") or "manual",
            "auto_send_level": item.get("auto_send_level") or "",
        })
    return out


def _generic_rule(response: dict[str, Any], debug: dict[str, Any]) -> dict[str, Any]:
    rule = response.get("generic_service_rule_used") or debug.get("generic_service_rule_used") or {}
    if not isinstance(rule, dict):
        return {}
    return {
        "rule_key": rule.get("rule_key", ""),
        "title": rule.get("title", ""),
        "fact_type": rule.get("fact_type", ""),
        "score": rule.get("score", 0),
    }


def _audit_summary(response: dict[str, Any]) -> dict[str, Any]:
    audit = response.get("final_answer_audit") or (response.get("evidence_debug") or {}).get("final_answer_audit") or {}
    return {
        "passed": bool(audit.get("passed", True)),
        "issues": audit.get("issues") or [],
        "mode": audit.get("mode", ""),
        "fallback_used": bool(audit.get("fallback_used", False)),
        "correction_source": audit.get("correction_source", ""),
    }


def _semantic_audit_summary(response: dict[str, Any]) -> dict[str, Any]:
    audit = response.get("final_semantic_fit_audit") or (response.get("evidence_debug") or {}).get("final_semantic_fit_audit") or {}
    return {
        "passed": bool(audit.get("passed", True)),
        "issues": audit.get("issues") or [],
        "mode": audit.get("mode", ""),
        "fallback_used": bool(audit.get("fallback_used", False)),
    }


def _evidence_trace_summaries(values: Any, *, selected_default: bool) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return out
    for item in values[:16]:
        if not isinstance(item, dict):
            continue
        preview = str(
            item.get("chunk_preview")
            or item.get("preview")
            or item.get("text")
            or item.get("chunk_text")
            or item.get("content")
            or item.get("fact")
            or ""
        ).strip()
        out.append({
            "entry_id": item.get("entry_id", ""),
            "chunk_id": item.get("chunk_id", ""),
            "asset_id": item.get("asset_id") or item.get("id") or "",
            "asset_type": item.get("asset_type", ""),
            "source_type": item.get("source_type", ""),
            "evidence_origin": item.get("evidence_origin", ""),
            "evidence_fact_type": item.get("evidence_fact_type") or item.get("fact_type") or "",
            "requested_fact_type": item.get("requested_fact_type") or item.get("query_fact_type") or "",
            "rank_score": item.get("rank_score", item.get("rerank_score", item.get("score", 0))),
            "role_score": item.get("role_score", 0),
            "origin_score": item.get("origin_score", 0),
            "deterministic_score": item.get("deterministic_score", 0),
            "embedding_score": item.get("embedding_score"),
            "embedding_reason": item.get("embedding_reason", ""),
            "final_rank_score": item.get("final_rank_score", item.get("rank_score", item.get("rerank_score", item.get("score", 0)))),
            "rank_reason": item.get("rank_reason") or _default_rank_reason(item),
            "selected": item.get("selected", selected_default),
            "reject_reason": item.get("reject_reason") or item.get("rejection_reasons") or item.get("mismatch_reason") or "",
            "role": item.get("role") or ("rejected" if item.get("selected", selected_default) is False else "direct_answer"),
            "preview": preview[:160],
        })
    return out


def _fallback_rerank_trace(selected: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in [*selected, *rejected]:
        rows.append({
            "evidence_id": item.get("entry_id") or item.get("chunk_id") or item.get("asset_id") or "",
            "entry_id": item.get("entry_id", ""),
            "chunk_id": item.get("chunk_id", ""),
            "asset_id": item.get("asset_id", ""),
            "evidence_origin": item.get("evidence_origin", ""),
            "source_type": item.get("source_type", ""),
            "evidence_fact_type": item.get("evidence_fact_type", ""),
            "requested_fact_type": item.get("requested_fact_type", ""),
            "rank_score": item.get("rank_score", 0),
            "embedding_score": item.get("embedding_score"),
            "embedding_reason": item.get("embedding_reason", ""),
            "final_rank_score": item.get("final_rank_score", item.get("rank_score", 0)),
            "rank_reason": item.get("rank_reason") or _default_rank_reason(item),
            "selected": bool(item.get("selected", False)),
            "reject_reason": "" if item.get("selected", False) else item.get("reject_reason", ""),
            "role": item.get("role") or ("direct_answer" if item.get("selected", False) else "rejected"),
        })
    return rows


def _default_rank_reason(item: dict[str, Any]) -> str:
    if item.get("selected") is False:
        return "evidence rejected by upstream evidence contract"
    if item.get("asset_id"):
        return "selected media evidence from upstream evidence contract"
    if item.get("evidence_fact_type") and item.get("requested_fact_type") == item.get("evidence_fact_type"):
        return "evidence fact_type matches requested fact_type"
    return "selected by upstream evidence contract"


def _evidence_by_fact_type(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        fact_type = str(item.get("evidence_fact_type") or "").strip()
        if fact_type:
            grouped.setdefault(fact_type, []).append(item)
    return grouped


def _top_reject_reasons(items: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for item in items:
        reason = item.get("reject_reason")
        if isinstance(reason, list):
            reason = ",".join(str(part) for part in reason if str(part or "").strip())
        reason = str(reason or "").strip()
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return [
        reason
        for reason, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    ]


def _semantic_compiler_summary(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("semantic_compiler_result") or (response.get("evidence_debug") or {}).get("semantic_compiler_result") or {}
    if not isinstance(result, dict):
        return {}
    return {
        "passed": bool(result.get("passed", True)),
        "issues": result.get("issues") or [],
        "deterministic_gate": bool(result.get("deterministic_gate", True)),
        "renderer_used": bool(result.get("renderer_used")),
        "post_compiler_validation": result.get("post_compiler_validation") or {},
        "final_text_passed": bool(result.get("final_text_passed", result.get("passed", True))),
        "blocked_raw_text": result.get("blocked_raw_text", ""),
        "reject_reason": result.get("reject_reason") or [],
    }


def _answer_block_summaries(response: dict[str, Any], debug: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = response.get("answer_blocks") or debug.get("answer_blocks") or []
    out: list[dict[str, Any]] = []
    for item in blocks or []:
        if not isinstance(item, dict):
            continue
        out.append({
            "type": item.get("type", ""),
            "fact_type": item.get("fact_type", ""),
            "can_send_to_customer": bool(item.get("can_send_to_customer", True)),
            "requires_human_review": bool(item.get("requires_human_review", False)),
            "evidence_refs": item.get("evidence_refs", []),
        })
    return out


def _rewrite_applied(response: dict[str, Any]) -> bool:
    audit = response.get("final_answer_audit") or {}
    semantic = response.get("final_semantic_fit_audit") or {}
    polish = response.get("customer_reply_polish") or {}
    return bool(
        audit.get("fallback_used")
        or semantic.get("fallback_used")
        or polish.get("applied")
        or (response.get("evidence_debug") or {}).get("post_polish_redline", {}).get("original_reply")
    )


def _reply_block_summaries(blocks: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        out.append({
            "type": block.get("type", ""),
            "asset_id": block.get("asset_id", ""),
            "asset_type": block.get("asset_type", ""),
            "title": block.get("title", ""),
            "send_mode": block.get("send_mode", ""),
            "has_url": bool(block.get("url")),
        })
    return out


def _media_evidence_from_pack(product_pack: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in product_pack.get("media_evidence") or []:
        if not isinstance(item, dict):
            continue
        fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "").strip()
        if not fact_type:
            continue
        result.setdefault(fact_type, []).append({
            "entry_id": item.get("entry_id", ""),
            "chunk_id": item.get("chunk_id", ""),
            "asset_id": item.get("asset_id") or item.get("id"),
            "asset_type": item.get("asset_type", ""),
            "asset_title": item.get("asset_title", ""),
            "source_type": item.get("source_type", ""),
            "evidence_origin": item.get("evidence_origin", ""),
        })
    return result


def _asset_evidence_from_assets(assets: list[dict[str, Any]], required_fact_types: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not assets:
        return {}
    fact_types = required_fact_types or ["visual_asset"]
    result: dict[str, list[dict[str, Any]]] = {}
    for fact_type in fact_types:
        if fact_type != "visual_asset" and not any(asset.get("asset_type") for asset in assets):
            continue
        result[fact_type] = [
            {
                "asset_id": asset.get("asset_id", ""),
                "asset_type": asset.get("asset_type", ""),
                "asset_title": asset.get("asset_title", ""),
                "asset_url": asset.get("asset_url", ""),
            }
            for asset in assets
        ]
    return result
