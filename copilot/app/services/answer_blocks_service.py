"""Structured customer answer blocks for final rendering.

This layer separates evidence references from customer-facing text. Evidence can
explain why a block exists, but raw product-card field names must not become the
text sent to a customer.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.fact_type_service import fact_type_matches, infer_evidence_fact_type


INTERNAL_CUSTOMER_TERMS = (
    "fact_type",
    "query_fact_type",
    "load_capacity",
    "score",
    "confidence",
    "evidence_debug",
    "RAG",
    "知识库",
    "系统检索",
)

RAW_FIELD_LABELS = (
    "承重",
    "承重/容量",
    "容量",
    "尺寸",
    "材质",
    "材料",
    "规格",
    "score",
    "confidence",
    "load_capacity",
    "fact_type",
    "query_fact_type",
)

_RAW_FIELD_RE = re.compile(
    r"(?P<label>[A-Za-z_/\-\u4e00-\u9fff]{1,24})\s*[:：]\s*(?P<value>[A-Za-z0-9_.%/\-\u4e00-\u9fff]{1,32})"
)
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def build_answer_blocks(
    response: dict[str, Any],
    *,
    customer_message: str = "",
) -> dict[str, Any]:
    """Build validated answer blocks from already-selected evidence/trace."""
    required = _required_fact_types(response)
    if not required:
        required = [_query_fact_type(response)] if _query_fact_type(response) else []

    evidence_by_type = {
        fact_type: _evidence_for_fact_type(response, fact_type)
        for fact_type in required
        if fact_type
    }
    blocks: list[dict[str, Any]] = []
    for fact_type in required:
        block = _block_for_fact_type(
            fact_type,
            evidence_by_type.get(fact_type, []),
            customer_message=customer_message,
            response=response,
        )
        if block:
            blocks.append(block)

    validated = validate_answer_blocks(blocks)
    result = {
        "answer_blocks": validated["blocks"],
        "rejected_blocks": validated["rejected_blocks"],
        "required_fact_types": required,
        "block_count": len(validated["blocks"]),
        "rejected_count": len(validated["rejected_blocks"]),
    }
    response["answer_blocks"] = result["answer_blocks"]
    response.setdefault("evidence_debug", {})["answer_blocks"] = result["answer_blocks"]
    response.setdefault("evidence_debug", {})["answer_block_validation"] = {
        "rejected_blocks": result["rejected_blocks"],
        "block_count": result["block_count"],
        "rejected_count": result["rejected_count"],
    }
    return result


def validate_answer_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        issues = validate_customer_text(str(block.get("customer_text") or ""))
        if not block.get("type"):
            issues.append("missing_block_type")
        if not block.get("fact_type"):
            issues.append("missing_fact_type")
        if issues:
            rejected.append({**block, "reject_reason": issues})
            continue
        valid.append({**block, "can_send_to_customer": bool(block.get("can_send_to_customer", True))})
    return {"blocks": valid, "rejected_blocks": rejected}


def validate_customer_text(text: str) -> list[str]:
    issues: list[str] = []
    value = str(text or "").strip()
    if not value:
        issues.append("empty_customer_text")
        return issues
    lower = value.lower()
    leaked = [term for term in INTERNAL_CUSTOMER_TERMS if term.lower() in lower]
    if leaked:
        issues.append("internal_metadata_leak:" + ",".join(leaked[:3]))
    raw = raw_field_leakage_issues(value)
    issues.extend(raw)
    if _is_isolated_number_answer(value):
        issues.append("isolated_number_without_unit_or_explanation")
    return issues


def raw_field_leakage_issues(text: str) -> list[str]:
    issues: list[str] = []
    for match in _RAW_FIELD_RE.finditer(str(text or "")):
        label = match.group("label").strip()
        raw_value = match.group("value").strip()
        if _is_blocked_raw_field(label, raw_value):
            issues.append(f"raw_field_leak:{label}")
    return issues


def has_raw_field_leakage(text: str) -> bool:
    return bool(raw_field_leakage_issues(text))


def _is_blocked_raw_field(label: str, raw_value: str) -> bool:
    normalized_label = label.strip().lower()
    if any(item.lower() == normalized_label for item in RAW_FIELD_LABELS):
        return True
    if any(item.lower() in normalized_label for item in ("score", "confidence", "fact_type")):
        return True
    if _NUMBER_RE.fullmatch(raw_value) and any(
        cue in label for cue in ("承重", "容量", "尺寸", "规格", "高度", "宽度", "长度")
    ):
        return True
    if len(raw_value) <= 8 and any(cue in label for cue in ("材质", "材料")):
        return True
    return False


def _is_isolated_number_answer(text: str) -> bool:
    value = re.sub(r"[。.!！?？~～\s]", "", text)
    return bool(_NUMBER_RE.fullmatch(value))


def _block_for_fact_type(
    fact_type: str,
    evidence_items: list[dict[str, Any]],
    *,
    customer_message: str,
    response: dict[str, Any],
) -> dict[str, Any] | None:
    evidence_refs = [_evidence_ref(item, fact_type) for item in evidence_items[:4]]
    payload = _semantic_payload(fact_type, evidence_items, customer_message=customer_message)
    text = _customer_text_for_payload(fact_type, payload, evidence_items, response=response)
    if not text:
        return None
    return {
        "type": _block_type_for_fact_type(fact_type, customer_message),
        "fact_type": fact_type,
        "customer_text": text,
        "semantic_payload": payload,
        "evidence_refs": [item for item in evidence_refs if item],
        "can_send_to_customer": True,
        "requires_human_review": bool(payload.get("requires_human_review")),
        "risk_level": payload.get("risk_level", "low"),
    }


def _block_type_for_fact_type(fact_type: str, customer_message: str) -> str:
    if fact_type in {"load_capacity", "stability"}:
        if any(cue in customer_message for cue in ("稳", "晃", "倒", "压塌", "压弯")):
            return "usage_stability"
        return "usage_advice"
    return {
        "material": "material_safety",
        "certification_report": "boundary_notice",
        "dimensions": "dimension_answer",
        "visual_asset": "media_reference",
        "installation": "installation_guidance",
        "aftersales_policy": "aftersales_guidance",
        "stock_shipping": "logistics_status",
        "promotion_policy": "promotion_rule",
        "space_fit": "dimension_answer",
        "placement_scene": "usage_advice",
    }.get(fact_type, "direct_answer")


def _semantic_payload(
    fact_type: str,
    evidence_items: list[dict[str, Any]],
    *,
    customer_message: str,
) -> dict[str, Any]:
    texts = [_evidence_text(item) for item in evidence_items if _evidence_text(item)]
    clean_texts = [_clean_evidence_text(text) for text in texts]
    clean_texts = [text for text in clean_texts if text]
    first = clean_texts[0] if clean_texts else ""
    payload: dict[str, Any] = {
        "fact_text": first,
        "evidence_count": len(evidence_items),
        "risk_level": "low",
    }
    if fact_type in {"load_capacity", "stability"}:
        payload.update({
            "customer_point": _usage_point(customer_message),
            "boundary": "重一点的东西建议放在下层，具体承重以商品页面标注为准。",
            "stability_advice": "日常摆放建议放在平整位置，并尽量均匀分层摆放。",
        })
    if fact_type == "certification_report" and not evidence_items:
        payload["requires_human_review"] = True
    return payload


def _customer_text_for_payload(
    fact_type: str,
    payload: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    *,
    response: dict[str, Any],
) -> str:
    fact = str(payload.get("fact_text") or "").strip()
    if fact_type in {"load_capacity", "stability"}:
        point = payload.get("customer_point") or "玩具、绘本、日用品这类常见物品"
        parts = [f"这款更适合放{point}。"]
        if fact:
            parts.append(_load_capacity_sentence(fact))
        parts.append(str(payload.get("stability_advice") or ""))
        parts.append(str(payload.get("boundary") or ""))
        return _join_clean(parts)
    if fact_type == "dimensions":
        if fact:
            return f"尺寸可以先按页面标注参考：{fact}。如果担心放不下，可以把预留空间的宽度、深度发我，我帮您一起核对。"
        return "当前没有明确尺寸证据，建议以商品页面标注为准；如果是确认家里能不能放下，可以把预留空间发我一起核对。"
    if fact_type == "installation":
        has_video = _has_asset(response, "video")
        text = "安装一般建议先核对配件，再按说明书从主体框架开始装，卡扣或螺丝位置可以先不要一次性拧太紧，整体对齐后再固定会更稳。"
        if has_video:
            return text + "我这边也会把对应安装视频一起给您参考。"
        return text + "目前没有可直接发送的安装视频，如果安装到某一步卡住，可以把卡住的位置拍给我，我帮您对照看一下。"
    if fact_type == "visual_asset":
        if _has_asset(response, "image") or _has_asset(response, "video"):
            return "我这边可以把当前商品对应的图片或视频素材一起发您参考，文字说明也以页面标注为准。"
        return "当前没有可直接发送的图片或视频素材；如果您想确认外观或细节，可以把页面截图或关心的位置发我，我帮您对照核对。"
    if fact_type == "certification_report":
        if fact and _has_certification_evidence(evidence_items, response):
            return f"检测报告/证书这块可以参考对应报告素材：{fact}。具体结论以报告标注为准。"
        return "检测报告/证书需要以页面展示或可发送的报告素材为准；如果当前没有对应报告证据，我不能直接替您下检测结论。"
    if fact:
        return fact
    return ""


def _load_capacity_sentence(text: str) -> str:
    cleaned = _clean_evidence_text(text)
    if not cleaned:
        return ""
    if any(unit in cleaned.lower() for unit in ("kg", "斤", "千克", "公斤")):
        return f"页面承重说明可以作为参考：{cleaned}。"
    if _NUMBER_RE.search(cleaned):
        return f"页面有承重相关标注，但具体单位和适用方式建议以商品页面完整说明为准。"
    return f"页面承重说明可以作为参考：{cleaned}。"


def _join_clean(parts: list[str]) -> str:
    return "".join(part for part in parts if str(part or "").strip())


def _usage_point(message: str) -> str:
    text = message or ""
    if "绘本" in text:
        return "绘本、薄书和日用品这类常见物品"
    if "书" in text:
        return "书本和日用品这类常见物品"
    if "客厅" in text or "杂物" in text:
        return "客厅杂物、日用品这类常见物品"
    if "小朋友" in text or "宝宝" in text or "玩具" in text:
        return "儿童用品、绘本、日用品这类常见物品"
    return "玩具、绘本、日用品这类常见物品"


def _required_fact_types(response: dict[str, Any]) -> list[str]:
    debug = response.get("evidence_debug") or {}
    trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    composition = response.get("answer_composition_trace") or debug.get("answer_composition_trace") or {}
    grouping = response.get("evidence_grouping") or debug.get("evidence_grouping") or {}
    coverage = grouping.get("coverage") if isinstance(grouping, dict) else {}
    values: list[Any] = []
    for container in (trace, composition, coverage, response, debug):
        if isinstance(container, dict):
            values.extend(container.get("required_fact_types") or [])
    values.append(_query_fact_type(response))
    for container in (response, debug):
        if isinstance(container, dict):
            values.extend(container.get("secondary_fact_types") or [])
    return _ordered_unique(values)


def _query_fact_type(response: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") or {}
    trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    for container in (trace, response, debug):
        if isinstance(container, dict):
            value = str(container.get("query_fact_type") or "").strip()
            if value:
                return value
    return ""


def _evidence_for_fact_type(response: dict[str, Any], fact_type: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    debug = response.get("evidence_debug") or {}
    composition = response.get("answer_composition_trace") or debug.get("answer_composition_trace") or {}
    evidence_by_type = composition.get("evidence_used_by_fact_type") if isinstance(composition, dict) else {}
    if isinstance(evidence_by_type, dict):
        candidates.extend([item for item in evidence_by_type.get(fact_type, []) or [] if isinstance(item, dict)])
    for key in ("selected_evidence", "recommended_evidence"):
        candidates.extend([item for item in debug.get(key, []) or [] if isinstance(item, dict)])
    for key in ("selected_evidence", "recommended_evidence"):
        candidates.extend([item for item in response.get(key, []) or [] if isinstance(item, dict)])
    product_pack_summary = debug.get("product_context_pack_summary") or {}
    evidence_pack = product_pack_summary.get("evidence_pack") if isinstance(product_pack_summary, dict) else {}
    if isinstance(evidence_pack, dict):
        candidates.extend([item for item in evidence_pack.get("matched_facts", []) or [] if isinstance(item, dict)])
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in candidates:
        ev_type = str(item.get("evidence_fact_type") or item.get("fact_type") or infer_evidence_fact_type(item) or "")
        if not fact_type_matches(fact_type, ev_type):
            continue
        key = (
            str(item.get("entry_id") or item.get("matched_entry_id") or ""),
            str(item.get("chunk_id") or ""),
            _evidence_text(item)[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _evidence_ref(item: dict[str, Any], fact_type: str) -> dict[str, Any]:
    return {
        "fact_type": fact_type,
        "entry_id": item.get("entry_id") or item.get("matched_entry_id") or "",
        "chunk_id": item.get("chunk_id") or "",
        "asset_id": item.get("asset_id") or item.get("id") or "",
        "source_type": item.get("source_type") or item.get("evidence_origin") or "",
    }


def _evidence_text(item: dict[str, Any]) -> str:
    for key in ("fact", "chunk_text", "content", "text", "answer", "preview"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    title = str(item.get("title") or item.get("matched_title") or "").strip()
    return title


def _clean_evidence_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    for match in list(_RAW_FIELD_RE.finditer(value)):
        label = match.group("label").strip()
        raw_value = match.group("value").strip()
        if _is_blocked_raw_field(label, raw_value):
            if label in {"承重", "承重/容量", "容量"}:
                replacement = f"页面有承重相关标注 {raw_value}"
            elif label in {"尺寸", "规格"}:
                replacement = f"页面尺寸标注为 {raw_value}"
            elif label in {"材质", "材料"}:
                replacement = f"页面材质标注为 {raw_value}"
            else:
                replacement = ""
            value = value.replace(match.group(0), replacement)
    value = value.strip("，,。；; ")
    return value


def _has_asset(response: dict[str, Any], asset_kind: str) -> bool:
    debug = response.get("evidence_debug") or {}
    candidates = [
        *(response.get("selected_assets") or []),
        *(response.get("recommended_assets") or []),
        *(debug.get("selected_assets") or []),
    ]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        asset_type = str(item.get("asset_type") or item.get("type") or item.get("media_type") or "").lower()
        has_ref = bool(item.get("asset_id") or item.get("id") or item.get("url") or item.get("asset_url") or item.get("media_url"))
        if not has_ref:
            continue
        if asset_kind == "image" and asset_type in {"image", "picture", "photo", "size_image", "certificate_image"}:
            return True
        if asset_kind == "video" and asset_type in {"video", "install_video", "installation_video"}:
            return True
    return False


def _has_certification_evidence(evidence_items: list[dict[str, Any]], response: dict[str, Any]) -> bool:
    for item in evidence_items:
        fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or infer_evidence_fact_type(item) or "")
        asset_type = str(item.get("asset_type") or "").lower()
        text = _evidence_text(item)
        if asset_type == "certificate_image":
            return True
        if fact_type == "certification_report" and _looks_like_certification_text(text):
            return True
    return _has_asset(response, "image") and "certification_report" in _required_fact_types(response)


def _looks_like_certification_text(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in (
        "检测报告",
        "质检报告",
        "检验报告",
        "合格证",
        "认证",
        "证书",
        "报告编号",
        "检测结论",
        "certificate",
        "certification",
    ))


def _ordered_unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out
