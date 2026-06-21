"""Deterministic evidence reranking contract for Phase 10.

This layer does not infer the user's intent from evidence. The caller must pass
the upstream query fact type and required fact types. Evidence is only ranked
against that contract and annotated as direct, supporting, fallback, or rejected.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.fact_type_service import fact_type_matches, infer_evidence_fact_type


SOURCE_PRIORITY = {
    "product_card": 50.0,
    "product_facts": 40.0,
    "product_fact": 40.0,
    "faq": 32.0,
    "installation_guide": 30.0,
    "product_media": 28.0,
    "media_evidence": 28.0,
    "generic_rules": 12.0,
    "generic_service_rule": 12.0,
}

SUPPORTING_FACT_TYPES = {
    "stability": {"load_capacity", "dimensions", "placement_scene"},
    "space_fit": {"dimensions", "placement_scene"},
    "material": {"certification_report", "odor"},
}

MEDIA_DIRECT_ASSET_TYPES = {
    "certification_report": {"certificate_image"},
    "installation": {"install_video", "install_image", "pack_guide_image"},
    "dimensions": {"size_image"},
    "space_fit": {"size_image", "sku_image"},
    "visual_asset": {"sku_image", "size_image", "image", "video"},
}


def rerank_evidence(
    *,
    retrieved_evidence: list[dict[str, Any]] | None = None,
    product_context_pack: dict[str, Any] | None = None,
    query_fact_type: str = "",
    required_fact_types: list[str] | None = None,
    secondary_fact_types: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    primary = str(query_fact_type or "").strip()
    required = _ordered_unique([primary, *(required_fact_types or []), *(secondary_fact_types or [])])
    candidates = _collect_candidates(retrieved_evidence or [], product_context_pack or {})
    ranked = [
        _rank_candidate(item, primary, required)
        for item in candidates
        if isinstance(item, dict)
    ]
    ranked.sort(key=lambda item: (-float(item.get("rank_score") or 0), item.get("rank_order", 999)))

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    selected_direct_by_fact_type: set[str] = set()

    for item in ranked:
        role = item.get("role", "rejected")
        fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "")
        if role == "direct_answer" and fact_type not in selected_direct_by_fact_type:
            selected.append({**item, "selected": True, "reject_reason": ""})
            selected_direct_by_fact_type.add(fact_type)
        elif role == "fallback" and not selected and fact_type in required:
            selected.append({**item, "selected": True, "reject_reason": ""})
        else:
            if role == "supporting_evidence":
                continue
            reason = item.get("reject_reason") or _default_reject_reason(item, primary, required)
            rejected.append({**item, "selected": False, "reject_reason": reason})

    selected_keys = {_evidence_key(item) for item in selected}
    for item in ranked:
        if item.get("role") != "supporting_evidence":
            continue
        key = _evidence_key(item)
        if key in selected_keys:
            continue
        if _supporting_allowed(item, primary, selected_direct_by_fact_type, selected):
            selected.append({**item, "selected": True, "reject_reason": ""})
            selected_keys.add(key)
        else:
            reason = item.get("reject_reason") or _default_reject_reason(item, primary, required)
            rejected.append({**item, "selected": False, "reject_reason": reason})

    selected = selected[:limit]
    selected_keys = {_evidence_key(item) for item in selected}
    for item in ranked:
        key = _evidence_key(item)
        if key in selected_keys:
            continue
        if any(_evidence_key(existing) == key for existing in rejected):
            continue
        rejected.append({
            **item,
            "selected": False,
            "reject_reason": item.get("reject_reason") or "lower_ranked_candidate",
        })

    return {
        "selected_evidence": selected,
        "rejected_evidence": rejected[: max(limit * 2, 12)],
        "rerank_trace": [_trace_row(item, selected_keys) for item in ranked[: max(limit * 3, 18)]],
        "evidence_origin_by_fact_type": _origin_by_fact_type(selected),
        "required_fact_types": required,
        "primary_fact_type": primary,
        "selected_assets": _selected_assets(selected),
    }


def _collect_candidates(retrieved: list[dict[str, Any]], product_pack: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(_with_origin(retrieved, fallback_origin="retrieved"))
    for key in ("product_card_evidence", "facts", "media_evidence", "recommended_assets", "generic_rules"):
        candidates.extend(_with_origin(product_pack.get(key) or [], fallback_origin=_origin_for_pack_key(key)))
    evidence_pack = product_pack.get("evidence_pack") or {}
    if isinstance(evidence_pack, dict):
        candidates.extend(_with_origin(evidence_pack.get("matched_facts") or [], fallback_origin="product_context_pack"))
        candidates.extend(_with_origin(evidence_pack.get("matched_media") or [], fallback_origin="product_media"))
        candidates.extend(_with_origin(evidence_pack.get("matched_generic_rules") or [], fallback_origin="generic_rules"))
        candidates.extend(_with_origin(evidence_pack.get("evidence_evaluation") or [], fallback_origin="product_context_pack"))
    return _dedupe(candidates)


def _with_origin(items: list[Any], *, fallback_origin: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        origin = item.get("evidence_origin") or metadata.get("evidence_origin") or fallback_origin
        source_type = item.get("source_type") or _source_type_from_origin(str(origin))
        out.append({**item, "evidence_origin": origin, "source_type": source_type})
    return out


def _rank_candidate(item: dict[str, Any], primary: str, required: list[str]) -> dict[str, Any]:
    evidence_fact_type = _evidence_fact_type(item)
    origin = str(item.get("evidence_origin") or "").strip()
    source_type = str(item.get("source_type") or "").strip()
    source_score = SOURCE_PRIORITY.get(origin, SOURCE_PRIORITY.get(source_type, 20.0))
    base_score = _float(item.get("rerank_score"), item.get("score"), item.get("relevance_score"), item.get("confidence"))
    role, reason, reject_reason = _role_and_reason(item, primary, required, evidence_fact_type)
    role_score = {
        "direct_answer": 100.0,
        "supporting_evidence": 55.0,
        "fallback": 20.0,
        "rejected": -100.0,
    }.get(role, -100.0)
    primary_bonus = 30.0 if primary and evidence_fact_type and fact_type_matches(primary, evidence_fact_type) else 0.0
    required_bonus = 12.0 if evidence_fact_type in required else 0.0
    media_bonus = _media_direct_bonus(item, primary)
    score = role_score + source_score + primary_bonus + required_bonus + media_bonus + base_score
    return {
        **item,
        "evidence_fact_type": evidence_fact_type,
        "fact_type": item.get("fact_type") or evidence_fact_type,
        "requested_fact_type": primary,
        "rank_score": round(score, 4),
        "rank_reason": reason,
        "reject_reason": reject_reason,
        "evidence_origin": origin,
        "source_type": source_type,
        "role": role,
    }


def _role_and_reason(
    item: dict[str, Any],
    primary: str,
    required: list[str],
    evidence_fact_type: str,
) -> tuple[str, str, str]:
    if item.get("selected") is False and item.get("reject_reason"):
        return "rejected", "upstream evidence evaluation rejected this item", str(item.get("reject_reason"))
    if primary == "certification_report":
        if _is_certification_evidence(item, evidence_fact_type):
            if _is_media_evidence(item) and not _is_sendable_media(item):
                return "rejected", "certificate media is not sendable", "media_not_sendable"
            return "direct_answer", "certification_report requires report/certificate evidence", ""
        return "rejected", "material or generic evidence cannot support certification_report", "certification_requires_report_evidence"

    if primary == "installation" and _asks_for_video(item):
        pass

    if primary == "installation" and _is_media_evidence(item):
        asset_type = str(item.get("asset_type") or "").lower()
        if asset_type == "install_video":
            return ("direct_answer", "installation video media directly answers installation video request", "") if _is_sendable_media(item) else ("rejected", "install video asset is not sendable", "media_not_sendable")
        if not _is_sendable_media(item):
            return "rejected", "installation media is not sendable", "media_not_sendable"

    if _is_media_evidence(item):
        if not _media_supports_fact_type(item, primary, evidence_fact_type):
            return "rejected", "media asset type does not match requested fact type", "media_fact_type_mismatch"
        if not _is_sendable_media(item):
            return "rejected", "media lacks approved usable asset id/url", "media_not_sendable"
        return "direct_answer", "sendable media matches requested fact type", ""

    origin = str(item.get("evidence_origin") or item.get("source_type") or "")
    if origin in {"generic_rules", "generic_service_rule"} and evidence_fact_type in required:
        return "fallback", "generic rule is fallback evidence", ""

    if primary and evidence_fact_type and fact_type_matches(primary, evidence_fact_type):
        return "direct_answer", "evidence fact_type matches primary query fact_type", ""

    if evidence_fact_type in SUPPORTING_FACT_TYPES.get(primary, set()):
        return "supporting_evidence", f"{evidence_fact_type} can only support {primary}", ""

    if evidence_fact_type in required and evidence_fact_type != primary:
        return "supporting_evidence", "secondary fact_type can support but not override primary", ""

    if primary and evidence_fact_type:
        return "rejected", "evidence fact_type does not match requested fact_type", "fact_type_mismatch"
    return "rejected", "evidence has no usable fact_type for this query", "missing_evidence_fact_type"


def _supporting_allowed(
    item: dict[str, Any],
    primary: str,
    selected_direct_by_fact_type: set[str],
    selected: list[dict[str, Any]],
) -> bool:
    if primary in {"certification_report", "installation"}:
        return False
    if primary in {"space_fit", "stability"}:
        return bool(selected_direct_by_fact_type or selected)
    return bool(selected_direct_by_fact_type)


def _is_certification_evidence(item: dict[str, Any], evidence_fact_type: str) -> bool:
    if evidence_fact_type == "certification_report":
        return True
    text = " ".join(str(item.get(key) or "") for key in ("asset_type", "media_purpose", "title", "asset_title", "chunk_text", "preview"))
    return any(term in text for term in ("certificate", "证书", "检测报告", "质检报告", "认证报告"))


def _media_supports_fact_type(item: dict[str, Any], primary: str, evidence_fact_type: str) -> bool:
    if not primary:
        return True
    asset_type = str(item.get("asset_type") or item.get("type") or "").lower()
    allowed = MEDIA_DIRECT_ASSET_TYPES.get(primary)
    if allowed and asset_type in allowed:
        return True
    return bool(evidence_fact_type and fact_type_matches(primary, evidence_fact_type))


def _media_direct_bonus(item: dict[str, Any], primary: str) -> float:
    if not _is_media_evidence(item):
        return 0.0
    asset_type = str(item.get("asset_type") or item.get("type") or "").lower()
    if asset_type in MEDIA_DIRECT_ASSET_TYPES.get(primary, set()):
        return 35.0
    return 0.0


def _is_media_evidence(item: dict[str, Any]) -> bool:
    source = str(item.get("source_type") or item.get("evidence_origin") or "").lower()
    return source in {"product_media", "media_evidence"} or bool(item.get("asset_type"))


def _is_sendable_media(item: dict[str, Any]) -> bool:
    asset_id = item.get("asset_id") or item.get("id")
    url = item.get("asset_url") or item.get("url") or item.get("media_url") or item.get("thumbnail_url")
    if not asset_id or not url:
        return False
    status = str(item.get("review_status") or item.get("status") or "approved").lower()
    usable = item.get("usable_for_agent")
    if status not in {"approved", "published", ""}:
        return False
    if usable is False or usable == 0:
        return False
    expires_at = item.get("expires_at") or item.get("url_expires_at")
    if expires_at and _is_expired(str(expires_at)):
        return False
    return True


def _is_expired(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc)
    except Exception:
        return False


def _asks_for_video(item: dict[str, Any]) -> bool:
    text = str(item.get("requested_fact_type") or "")
    return "视频" in text


def _evidence_fact_type(item: dict[str, Any]) -> str:
    value = str(item.get("evidence_fact_type") or item.get("fact_type") or item.get("query_fact_type") or "").strip()
    if value:
        return value
    return infer_evidence_fact_type(item)


def _origin_for_pack_key(key: str) -> str:
    return {
        "product_card_evidence": "product_card",
        "facts": "product_facts",
        "media_evidence": "product_media",
        "recommended_assets": "product_media",
        "generic_rules": "generic_rules",
    }.get(key, key)


def _source_type_from_origin(origin: str) -> str:
    return {
        "product_card": "product_facts",
        "product_media": "product_media",
        "generic_rules": "generic_rules",
    }.get(origin, origin)


def _default_reject_reason(item: dict[str, Any], primary: str, required: list[str]) -> str:
    if item.get("role") == "supporting_evidence":
        return "supporting_evidence_not_needed"
    if primary and item.get("evidence_fact_type") not in required:
        return "fact_type_mismatch"
    return "lower_ranked_candidate"


def _trace_row(item: dict[str, Any], selected_keys: set[str]) -> dict[str, Any]:
    key = _evidence_key(item)
    return {
        "evidence_id": key,
        "entry_id": item.get("entry_id", ""),
        "chunk_id": item.get("chunk_id", ""),
        "asset_id": item.get("asset_id") or item.get("id") or "",
        "evidence_origin": item.get("evidence_origin", ""),
        "source_type": item.get("source_type", ""),
        "evidence_fact_type": item.get("evidence_fact_type", ""),
        "requested_fact_type": item.get("requested_fact_type", ""),
        "rank_score": item.get("rank_score", 0),
        "rank_reason": item.get("rank_reason", ""),
        "selected": key in selected_keys,
        "reject_reason": "" if key in selected_keys else item.get("reject_reason", ""),
        "role": item.get("role", ""),
    }


def _origin_by_fact_type(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in items:
        fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "").strip()
        origin = str(item.get("evidence_origin") or item.get("source_type") or "").strip()
        if fact_type and origin:
            result.setdefault(fact_type, [])
            if origin not in result[fact_type]:
                result[fact_type].append(origin)
    return result


def _selected_assets(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets = []
    for item in items:
        if not _is_media_evidence(item) or not _is_sendable_media(item):
            continue
        assets.append({
            "asset_id": item.get("asset_id") or item.get("id") or "",
            "asset_type": item.get("asset_type", ""),
            "asset_title": item.get("asset_title") or item.get("title") or "",
            "asset_url": item.get("asset_url") or item.get("url") or item.get("media_url") or "",
            "send_mode": item.get("send_mode") or "manual",
            "auto_send_level": item.get("auto_send_level") or "",
            "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or "",
        })
    return assets


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = _evidence_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _evidence_key(item: dict[str, Any]) -> str:
    return str(
        item.get("evidence_id")
        or item.get("entry_id")
        or item.get("chunk_id")
        or item.get("asset_id")
        or item.get("id")
        or item.get("title")
        or item.get("asset_title")
        or id(item)
    )


def _ordered_unique(values: list[Any]) -> list[str]:
    out = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _float(*values: Any) -> float:
    for value in values:
        try:
            return float(value or 0)
        except Exception:
            continue
    return 0.0
