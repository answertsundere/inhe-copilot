"""Read-only helpers for AI provisional evidence usage in replay traces."""

from __future__ import annotations

import json
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


PACK_LIST_KEYS = ("ai_provisional_knowledge", "matched_facts", "product_scoped_chunks")


def extract_ai_provisional_usage_from_trace(trace) -> dict[str, Any]:
    """Extract provisional usage from an EvalTrace-like object."""
    raw_response = trace.get_raw_response() if hasattr(trace, "get_raw_response") else {}
    answer_trace = trace.get_answer_trace() if hasattr(trace, "get_answer_trace") else {}
    failure_labels = trace.get_failure_labels() if hasattr(trace, "get_failure_labels") else []
    usage = extract_ai_provisional_usage(
        raw_response=raw_response,
        answer_trace=answer_trace,
        failure_labels=failure_labels,
    )
    usage.update({
        "case_uid": sanitize_text(getattr(trace, "case_uid", "")),
        "turn_uid": sanitize_text(getattr(trace, "turn_uid", "")),
        "buyer_message_preview": sanitize_text(getattr(trace, "buyer_message", ""))[:120],
        "query_fact_type": sanitize_text(getattr(trace, "query_fact_type", "")),
        "requires_human_review": bool(usage.get("requires_human_review") or getattr(trace, "requires_human_review", False)),
        "failure_labels": failure_labels or usage.get("failure_labels") or [],
    })
    return sanitize_obj(usage)


def extract_ai_provisional_usage(
    *,
    raw_response: dict[str, Any] | None,
    answer_trace: dict[str, Any] | None = None,
    failure_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Extract provisional evidence usage from known replay response paths.

    The function only reads explicit trace/evidence fields. It never infers a
    product identity from buyer text, product titles, or fuzzy matching.
    """
    raw = raw_response if isinstance(raw_response, dict) else {}
    answer = answer_trace if isinstance(answer_trace, dict) else {}
    evidence = _collect_provisional_evidence(raw, answer)
    reply_delivery = raw.get("reply_delivery") if isinstance(raw.get("reply_delivery"), dict) else {}
    quality = raw.get("quality_bucket") if isinstance(raw.get("quality_bucket"), dict) else {}
    can_send = bool(raw.get("can_send"))
    auto_ready = bool(reply_delivery.get("auto_send_ready"))
    return sanitize_obj({
        "provisional_used": bool(evidence),
        "provisional_used_turn": bool(evidence),
        "provisional_evidence_count": len(evidence),
        "provisional_used_draft_count": len({
            item.get("draft_uid") or item.get("evidence_id")
            for item in evidence
            if item.get("draft_uid") or item.get("evidence_id")
        }),
        "provisional_evidence": evidence,
        "can_send": can_send,
        "sendable_reply_empty": not bool(sanitize_text(raw.get("sendable_reply"))),
        "requires_human_review": bool(raw.get("requires_human_review") or answer.get("requires_human_review")),
        "reply_delivery_auto_send_ready": auto_ready,
        "auto_send_with_provisional": bool(evidence and auto_ready),
        "quality_bucket": sanitize_text(quality.get("quality_bucket") if quality else raw.get("quality_bucket")),
        "failure_labels": failure_labels or [],
    })


def _collect_provisional_evidence(raw: dict[str, Any], answer_trace: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, Any]] = []

    for pack, pack_path in _iter_packs(raw):
        pack_identity = _identity_from_pack(pack)
        for list_name in PACK_LIST_KEYS:
            values = pack.get(list_name)
            if isinstance(values, list):
                for index, item in enumerate(values):
                    _append_evidence(
                        result,
                        seen,
                        item,
                        pack_identity,
                        f"{pack_path}.{list_name}[{index}]",
                    )
        selected = pack.get("selected_product_first_evidence")
        _append_selected(result, seen, selected, pack_identity, f"{pack_path}.selected_product_first_evidence")

    for source, path in (
        (raw.get("selected_product_first_evidence"), "raw_response.selected_product_first_evidence"),
        (answer_trace.get("selected_product_first_evidence"), "answer_trace.selected_product_first_evidence"),
        (answer_trace.get("selected_product_first"), "answer_trace.selected_product_first"),
    ):
        _append_selected(result, seen, source, {}, path)

    for item, path in _iter_flagged_evidence(raw, "raw_response"):
        _append_evidence(result, seen, item, {}, path)
    for item, path in _iter_flagged_evidence(answer_trace, "answer_trace"):
        _append_evidence(result, seen, item, {}, path)

    return result


def _append_selected(
    result: list[dict[str, Any]],
    seen: set[tuple[str, str, str, str]],
    selected: Any,
    pack_identity: dict[str, Any],
    path: str,
) -> None:
    if isinstance(selected, list):
        for index, item in enumerate(selected):
            _append_evidence(result, seen, item, pack_identity, f"{path}[{index}]")
    else:
        _append_evidence(result, seen, selected, pack_identity, path)


def _append_evidence(
    result: list[dict[str, Any]],
    seen: set[tuple[str, str, str, str]],
    item: Any,
    pack_identity: dict[str, Any],
    source_path: str,
) -> None:
    if not isinstance(item, dict) or not _is_provisional_evidence(item):
        return
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    draft_uid = sanitize_text(
        item.get("provisional_draft_uid")
        or item.get("draft_uid")
        or item.get("source_id")
        or item.get("evidence_id")
        or item.get("entry_id")
        or item.get("chunk_id")
    )
    evidence_id = sanitize_text(item.get("evidence_id") or item.get("entry_id") or item.get("chunk_id") or draft_uid)
    query_fact_type = sanitize_text(item.get("fact_type") or item.get("evidence_fact_type") or metadata.get("query_fact_type"))
    i_id = sanitize_text(item.get("i_id") or item.get("item_id") or metadata.get("i_id") or pack_identity.get("i_id"))
    sku_code = sanitize_text(item.get("sku_code") or item.get("sku") or metadata.get("sku_code") or pack_identity.get("sku_code"))
    key = (draft_uid or evidence_id, i_id, sku_code, query_fact_type)
    if key in seen:
        return
    loose_key = (draft_uid or evidence_id, query_fact_type)
    for index, existing in enumerate(result):
        existing_loose_key = (
            existing.get("draft_uid") or existing.get("evidence_id"),
            existing.get("query_fact_type"),
        )
        if existing_loose_key != loose_key:
            continue
        existing_has_identity = bool(existing.get("i_id") or existing.get("sku_code") or existing.get("kb_product_id"))
        current_has_identity = bool(i_id or sku_code or item.get("kb_product_id") or metadata.get("kb_product_id") or pack_identity.get("kb_product_id"))
        if existing_has_identity or not current_has_identity:
            return
        result.pop(index)
        break
    seen.add(key)
    kb_product_id = item.get("kb_product_id") or metadata.get("kb_product_id") or pack_identity.get("kb_product_id")
    identity_status = sanitize_text(item.get("identity_status") or metadata.get("identity_status") or pack_identity.get("identity_status"))
    if not identity_status and (i_id or sku_code or kb_product_id):
        identity_status = "resolved"
    result.append(sanitize_obj({
        "draft_uid": draft_uid,
        "provisional_draft_uid": draft_uid,
        "evidence_id": evidence_id,
        "i_id": i_id,
        "sku_code": sku_code,
        "kb_product_id": kb_product_id,
        "query_fact_type": query_fact_type,
        "identity_status": identity_status,
        "identity_sources": _identity_sources(item, metadata, pack_identity),
        "usable_for_eval": _bool_from_item(item, metadata, "usable_for_eval"),
        "usable_for_auto_send": _bool_from_item(item, metadata, "usable_for_auto_send"),
        "needs_human_review": bool(item.get("needs_human_review")),
        "verification_status": sanitize_text(item.get("verification_status") or metadata.get("verification_status")),
        "source_path": source_path,
    }))


def _iter_packs(raw: dict[str, Any]):
    candidates = (
        ("product_first_evidence_pack", raw.get("product_first_evidence_pack")),
        ("product_context_pack.product_first_evidence_pack", _dig(raw, "product_context_pack", "product_first_evidence_pack")),
        ("product_context_pack.evidence_pack", _dig(raw, "product_context_pack", "evidence_pack")),
        (
            "evidence_debug.product_context_pack_summary.evidence_pack",
            _dig(raw, "evidence_debug", "product_context_pack_summary", "evidence_pack"),
        ),
        (
            "evidence_debug.product_context_pack_summary.product_first_evidence_pack",
            _dig(raw, "evidence_debug", "product_context_pack_summary", "product_first_evidence_pack"),
        ),
    )
    seen: set[int] = set()
    for path, pack in candidates:
        if isinstance(pack, dict) and id(pack) not in seen:
            seen.add(id(pack))
            yield pack, path


def _iter_flagged_evidence(value: Any, path: str):
    if isinstance(value, dict):
        if value.get("provisional_knowledge_used") is True and _has_evidence_identity(value):
            yield value, path
        for key, child in value.items():
            yield from _iter_flagged_evidence(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_flagged_evidence(child, f"{path}[{index}]")


def _identity_from_pack(pack: dict[str, Any]) -> dict[str, Any]:
    identity = pack.get("resolved_product_identity") if isinstance(pack.get("resolved_product_identity"), dict) else {}
    return {
        "i_id": sanitize_text(identity.get("i_id") or identity.get("item_id") or ""),
        "sku_code": sanitize_text(identity.get("sku") or identity.get("sku_code") or ""),
        "kb_product_id": identity.get("product_id") or identity.get("kb_product_id"),
        "identity_sources": identity.get("identity_sources") or [],
        "identity_status": "resolved" if (identity.get("i_id") or identity.get("sku") or identity.get("product_id")) else "",
    }


def _identity_sources(item: dict[str, Any], metadata: dict[str, Any], pack_identity: dict[str, Any]) -> list[str]:
    raw = item.get("identity_sources") or metadata.get("identity_sources") or pack_identity.get("identity_sources") or []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [sanitize_text(value) for value in raw if sanitize_text(value)]
    return []


def _is_provisional_evidence(item: dict[str, Any]) -> bool:
    return bool(
        item.get("provisional_knowledge_used")
        or item.get("provisional_draft_uid")
        or item.get("source_table") == "ai_provisional_knowledge"
        or item.get("protocol_source_type") == "ai_prefill"
    )


def _has_evidence_identity(item: dict[str, Any]) -> bool:
    return bool(
        item.get("provisional_draft_uid")
        or item.get("draft_uid")
        or item.get("source_id")
        or item.get("evidence_id")
        or item.get("entry_id")
        or item.get("chunk_id")
        or item.get("source_table") == "ai_provisional_knowledge"
    )


def _bool_from_item(item: dict[str, Any], metadata: dict[str, Any], key: str) -> bool:
    if key in item:
        return bool(item.get(key))
    if key in metadata:
        return bool(metadata.get(key))
    return False


def _dig(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def json_key(value: Any) -> str:
    return json.dumps(sanitize_obj(value), ensure_ascii=False, sort_keys=True)
