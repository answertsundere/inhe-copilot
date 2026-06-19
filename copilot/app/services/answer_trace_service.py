"""Unified answer trace helpers.

This module does not retrieve evidence or make business decisions. It only
normalizes the evidence and audit metadata that earlier nodes already produced
so the final API response has one stable trace shape.
"""

from __future__ import annotations

from typing import Any


def build_answer_trace(response: dict[str, Any], *, customer_message: str = "") -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
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
    query_fact_type = str(
        debug.get("query_fact_type")
        or response.get("query_fact_type")
        or ""
    )
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
    trace = {
        "mode": _trace_mode(response, composition, selected_assets),
        "customer_message": customer_message or debug.get("current_query") or response.get("current_query", ""),
        "query_fact_type": query_fact_type,
        "secondary_fact_types": secondary_fact_types,
        "required_fact_types": required_fact_types,
        "answered_fact_types": _ordered_unique(
            (composition.get("answered_fact_types") or composition.get("covered_fact_types") or [])
            if isinstance(composition, dict) else []
        ),
        "evidence_answered_fact_types": _ordered_unique(
            composition.get("evidence_answered_fact_types") or []
            if isinstance(composition, dict) else []
        ),
        "fallback_fact_types": _ordered_unique(
            composition.get("fallback_fact_types") or []
            if isinstance(composition, dict) else []
        ),
        "needs_followup_fact_types": _ordered_unique(
            composition.get("needs_followup_fact_types") or []
            if isinstance(composition, dict) else []
        ),
        "product_card_evidence_used": _dict_or_empty(composition.get("product_card_evidence_used") if isinstance(composition, dict) else {}),
        "media_evidence_used": _dict_or_empty(composition.get("media_evidence_used") if isinstance(composition, dict) else {}),
        "asset_evidence_used": _dict_or_empty(composition.get("asset_evidence_used") if isinstance(composition, dict) else {}),
        "selected_assets": selected_assets,
        "generic_rule_used": _generic_rule(response, debug),
        "final_audit": _audit_summary(response),
        "final_semantic_fit_audit": _semantic_audit_summary(response),
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


def attach_answer_trace(response: dict[str, Any], *, customer_message: str = "") -> dict[str, Any]:
    trace = build_answer_trace(response, customer_message=customer_message)
    response["answer_trace"] = trace
    response.setdefault("evidence_debug", {})["answer_trace"] = trace
    return response


def _trace_mode(response: dict[str, Any], composition: dict[str, Any], selected_assets: list[dict[str, Any]]) -> str:
    generation_mode = str(response.get("generation_mode") or "")
    if "audit" in generation_mode:
        return "final_audit_rewrite"
    if selected_assets:
        return "media_answer"
    if response.get("generic_service_rule_used") or (response.get("evidence_debug") or {}).get("generic_service_rule_used"):
        return "generic_rule_fallback"
    if isinstance(composition, dict) and composition.get("evidence_answered_fact_types"):
        return "evidence_answer"
    if response.get("requires_human_review"):
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
