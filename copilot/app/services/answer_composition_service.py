"""Customer-facing answer composition from already-selected evidence.

This service does not retrieve data, call an LLM, or relax any guard. It turns
the existing fact-type plan into a cohesive customer reply and records which
fact type each sentence is meant to cover.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.fact_type_service import FACT_TYPE_LABELS, fact_type_matches, infer_evidence_fact_type


COMPOSABLE_SINGLE_FACT_TYPES = {
    "odor",
    "space_fit",
    "placement_scene",
    "visual_asset",
}

COMPOSABLE_INTENTS = {
    "complaint",
    "high_risk",
    "aftersales",
}

FACT_EVIDENCE_REQUIRED_TYPES = {
    "material",
    "certification_report",
    "dimensions",
    "load_capacity",
    "age_range",
    "odor",
    "cleaning_care",
    "safety_small_parts",
    "pinch_safety",
    "stability",
}

SERVICE_GUIDANCE_FACT_TYPES = {
    "stock_shipping",
    "aftersales_policy",
    "installation",
    "space_fit",
    "placement_scene",
}

PRODUCT_IDENTITY_FACT_TYPES = {
    "material",
    "certification_report",
    "dimensions",
    "visual_asset",
    "space_fit",
    "placement_scene",
    "age_range",
    "odor",
    "cleaning_care",
    "load_capacity",
    "stability",
    "pinch_safety",
    "safety_small_parts",
}

BUSINESS_PRIORITY = {
    "aftersales_policy": 10,
    "installation": 20,
}

IDENTITY_PROMPT_TERMS = (
    "商品链接",
    "商品截图",
    "商品页面截图",
    "订单号",
    "商品标题",
    "发一下链接",
    "发个截图",
    "提供商品信息",
    "链接",
    "SKU",
    "sku",
)

FORBIDDEN_CLAIMS = (
    "绝对安全",
    "100%安全",
    "百分百安全",
    "一定今天发",
    "今天一定发",
    "一定能发",
    "保证今天发",
    "保证能到",
    "一定能到",
    "肯定能到",
    "保证无味",
    "绝对无味",
    "0甲醛",
    "零甲醛",
    "一定适合",
    "直接赔",
    "一定赔",
)

INTERNAL_TERMS = (
    "系统",
    "知识库",
    "RAG",
    "rag",
    "fact_type",
    "query_fact_type",
    "evidence",
    "tool",
)


def should_compose_answer(
    *,
    intent: str = "",
    risk_level: str = "",
    query_understanding: dict[str, Any] | None = None,
    evidence_grouping: dict[str, Any] | None = None,
) -> bool:
    """Return True when the current reply benefits from deterministic composition."""
    required = _required_fact_types(query_understanding or {}, evidence_grouping or {})
    if len(required) >= 2:
        return True
    if required and required[0] in COMPOSABLE_SINGLE_FACT_TYPES:
        return True
    if str(intent or "") in COMPOSABLE_INTENTS:
        return True
    if str(risk_level or "").lower() in {"high", "critical"}:
        return True
    return False


def compose_customer_reply(
    *,
    customer_message: str,
    base_reply: str,
    query_understanding: dict[str, Any] | None,
    evidence_grouping: dict[str, Any] | None,
    multi_intent_answer_plan: list[dict[str, Any]] | None = None,
    selected_evidence: list[dict[str, Any]] | None = None,
    selected_assets: list[dict[str, Any]] | None = None,
    product_name: str = "",
    risk_level: str = "",
    intent: str = "",
    identity_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose a concise reply and a section-level trace.

    The output is intentionally conservative: explicit product facts are only
    copied from selected evidence. Missing facts use generic service guidance.
    """
    query_understanding = query_understanding or {}
    evidence_grouping = evidence_grouping or {}
    required = _required_fact_types(query_understanding, evidence_grouping)
    groups = {
        str(group.get("fact_type") or ""): group
        for group in evidence_grouping.get("groups") or []
        if isinstance(group, dict)
    }
    selected_evidence = selected_evidence or []
    selected_assets = selected_assets or []
    identity_context = identity_context or {}
    customer_tone = _customer_tone(customer_message, risk_level, intent)

    if not required:
        required = _fallback_required_fact_types(query_understanding, intent)
    if _needs_aftersales_policy(customer_message, intent):
        required = _prepend_unique(required, ["aftersales_policy"])
        if _mentions_installation(customer_message):
            required = _append_unique(required, ["installation"])

    sections: list[dict[str, Any]] = []
    evidence_used_by_fact_type: dict[str, list[dict[str, Any]]] = {}
    evidence_origin_by_fact_type: dict[str, list[str]] = {}
    fallback_used_by_fact_type: dict[str, bool] = {}

    for fact_type in _ordered_fact_types(required, customer_message):
        group = groups.get(fact_type, {})
        evidence_items = _evidence_for_fact_type(
            fact_type,
            group,
            selected_evidence,
            selected_assets,
            product_name=product_name,
        )
        section = _section_for_fact_type(
            fact_type,
            evidence_items,
            customer_message=customer_message,
            product_name=product_name,
            customer_tone=customer_tone,
        )
        if not section:
            continue
        section_source = _section_source(fact_type, evidence_items)
        evidence_used_by_fact_type[fact_type] = [_summarize_evidence(item) for item in evidence_items[:3]]
        evidence_origin_by_fact_type[fact_type] = _evidence_origins(evidence_items)
        fallback_used_by_fact_type[fact_type] = not bool(evidence_items)
        sections.append({
            "fact_type": fact_type,
            "fact_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
            "source": "evidence" if evidence_items else "fallback",
            "answer_source": section_source,
            "answered": _section_counts_as_answered(fact_type, section_source, section, evidence_items),
            "needs_followup": section_source == "handoff_guidance",
            "text": section,
        })

    if not sections and base_reply:
        sections.append({
            "fact_type": "base_reply",
            "fact_label": "基础回复",
            "source": "base_reply",
            "text": _clean_reply(base_reply),
        })

    reply = _join_sections(sections, customer_tone)
    reply, blocked_claims = _remove_forbidden_claims(reply)
    reply = _remove_internal_terms(reply)
    reply = _clean_reply(reply)
    reply, identity_suppression = _suppress_identity_prompt_when_product_resolved(
        reply,
        identity_context,
        intent=intent,
        required_fact_types=required,
    )

    answered = [
        section["fact_type"]
        for section in sections
        if section.get("fact_type") != "base_reply" and section.get("answered")
    ]
    evidence_answered = [
        section["fact_type"]
        for section in sections
        if section.get("fact_type") != "base_reply" and section.get("answer_source") == "evidence_answer"
    ]
    fallback_fact_types = [
        section["fact_type"]
        for section in sections
        if section.get("fact_type") != "base_reply" and section.get("answer_source") in {"service_guidance", "handoff_guidance"}
    ]
    needs_followup = [
        section["fact_type"]
        for section in sections
        if section.get("fact_type") != "base_reply" and section.get("needs_followup")
    ]
    covered = answered
    missing = [fact_type for fact_type in required if fact_type not in covered]
    trace = {
        "mode": "multi_intent" if len(required) >= 2 else "single_intent",
        "covered_fact_types": covered,
        "answered_fact_types": answered,
        "evidence_answered_fact_types": evidence_answered,
        "fallback_fact_types": fallback_fact_types,
        "needs_followup_fact_types": needs_followup,
        "missing_fact_types": missing,
        "evidence_used_by_fact_type": evidence_used_by_fact_type,
        "evidence_origin_by_fact_type": evidence_origin_by_fact_type,
        "product_card_evidence_used": _trace_items_by_origin(evidence_used_by_fact_type, "product_card"),
        "media_evidence_used": _trace_items_by_origin(evidence_used_by_fact_type, "product_media"),
        "asset_evidence_used": _trace_asset_items(evidence_used_by_fact_type),
        "fallback_used_by_fact_type": fallback_used_by_fact_type,
        "blocked_claims": blocked_claims,
        "suppressed_identity_prompt": identity_suppression.get("suppressed", False),
        "identity_prompt_suppression_reason": identity_suppression.get("reason", ""),
        "customer_tone": customer_tone,
        "answer_sections": sections,
        "base_reply_used": bool(base_reply and not sections),
        "plan_fact_types": [
            item.get("fact_type", "")
            for item in multi_intent_answer_plan or []
            if isinstance(item, dict)
        ],
    }
    return {"composed_reply": reply, "composition_trace": trace}


def _required_fact_types(query_understanding: dict[str, Any], grouping: dict[str, Any]) -> list[str]:
    coverage = grouping.get("coverage") or {}
    values = list(coverage.get("required_fact_types") or [])
    if not values:
        values = [
            query_understanding.get("query_fact_type", ""),
            *(query_understanding.get("secondary_fact_types") or []),
        ]
    rejected = str(query_understanding.get("llm_rejected_fact_type") or "").strip()
    out: list[str] = []
    for value in values:
        fact_type = str(value or "").strip()
        if fact_type and fact_type != rejected and fact_type not in out:
            out.append(fact_type)
    return out


def _fallback_required_fact_types(query_understanding: dict[str, Any], intent: str) -> list[str]:
    fact_type = str(query_understanding.get("query_fact_type") or "").strip()
    if fact_type:
        return [fact_type]
    if intent in {"complaint", "high_risk", "aftersales"}:
        return ["aftersales_policy"]
    return []


def _prepend_unique(values: list[str], prefix: list[str]) -> list[str]:
    out: list[str] = []
    for value in [*prefix, *values]:
        if value and value not in out:
            out.append(value)
    return out


def _append_unique(values: list[str], suffix: list[str]) -> list[str]:
    out = list(values)
    for value in suffix:
        if value and value not in out:
            out.append(value)
    return out


def _needs_aftersales_policy(message: str, intent: str) -> bool:
    text = message or ""
    if intent != "aftersales":
        return False
    return any(cue in text for cue in (
        "\u5c11\u4ef6",
        "\u5c11\u4e86",
        "\u7f3a\u4ef6",
        "\u7f3a\u914d\u4ef6",
        "\u6f0f\u53d1",
        "\u53d1\u9519",
        "\u9519\u53d1",
        "\u7834\u635f",
        "\u574f\u4e86",
        "\u5b89\u88c5\u4e0d\u4e86",
        "\u88c5\u4e0d\u4e86",
        "\u88c5\u4e0d\u4e0a",
    ))


def _mentions_installation(message: str) -> bool:
    return any(cue in (message or "") for cue in (
        "\u5b89\u88c5",
        "\u88c5\u4e0d\u4e86",
        "\u88c5\u4e0d\u4e0a",
        "\u7ec4\u88c5",
        "\u6559\u7a0b",
    ))


def _ordered_fact_types(values: list[str], message: str) -> list[str]:
    indexed = {fact_type: idx for idx, fact_type in enumerate(values)}

    def key(fact_type: str) -> tuple[int, int]:
        if fact_type in BUSINESS_PRIORITY:
            return (BUSINESS_PRIORITY[fact_type], indexed.get(fact_type, 999))
        pos = _message_position_for_fact_type(message, fact_type)
        if pos >= 0:
            return (100 + pos, indexed.get(fact_type, 999))
        return (10000, indexed.get(fact_type, 999))

    return sorted(values, key=key)


def _message_position_for_fact_type(message: str, fact_type: str) -> int:
    cues = {
        "material": ("\u6750\u8d28", "\u5b89\u5168", "\u5b9d\u5b9d", "\u9632\u6f6e", "\u9632\u6c34"),
        "stock_shipping": ("\u53d1\u8d27", "\u4eca\u5929", "\u73b0\u8d27", "\u5e93\u5b58"),
        "dimensions": ("\u5c3a\u5bf8", "\u591a\u5927", "\u957f\u5bbd\u9ad8"),
        "visual_asset": ("\u56fe", "\u56fe\u7247", "\u7167\u7247"),
        "aftersales_policy": ("\u5c11\u4ef6", "\u7f3a\u914d\u4ef6", "\u53d1\u9519", "\u7834\u635f", "\u552e\u540e"),
        "installation": ("\u5b89\u88c5", "\u88c5\u4e0d\u4e86", "\u88c5\u4e0d\u4e0a", "\u6559\u7a0b"),
        "age_range": ("\u4e00\u5c81", "\u5e74\u9f84", "\u9002\u9f84", "\u591a\u5927\u5b9d\u5b9d"),
        "odor": ("\u5473\u9053", "\u6c14\u5473", "\u5f02\u5473"),
    }.get(fact_type, (fact_type,))
    positions = [message.find(cue) for cue in cues if cue and cue in message]
    return min(positions) if positions else -1


def _section_source(fact_type: str, evidence_items: list[dict[str, Any]]) -> str:
    if fact_type == "visual_asset":
        return "evidence_answer" if _has_sendable_asset(evidence_items) else "handoff_guidance"
    if evidence_items:
        return "evidence_answer"
    if fact_type in FACT_EVIDENCE_REQUIRED_TYPES:
        return "handoff_guidance"
    return "service_guidance"


def _section_counts_as_answered(
    fact_type: str,
    section_source: str,
    section_text: str,
    evidence_items: list[dict[str, Any]],
) -> bool:
    if fact_type == "visual_asset":
        return _visual_asset_counts_as_answered(section_text, evidence_items)
    if section_source == "evidence_answer":
        return True
    return section_source == "service_guidance" and fact_type in SERVICE_GUIDANCE_FACT_TYPES


def _has_sendable_asset(items: list[dict[str, Any]]) -> bool:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        asset_type = str(item.get("asset_type") or item.get("type") or item.get("media_type") or "").lower()
        source_type = str(item.get("source_type") or "").lower()
        has_asset_id = bool(item.get("asset_id") or item.get("id"))
        has_url = bool(
            item.get("url")
            or item.get("asset_url")
            or item.get("oss_url")
            or item.get("signed_url")
            or item.get("media_url")
            or item.get("thumbnail_url")
        )
        if asset_type in {"image", "video", "picture", "photo"} and (has_asset_id or has_url):
            return True
        if source_type == "product_media" and has_asset_id and has_url:
            return True
        if has_asset_id and has_url and any(key in item for key in ("asset_title", "send_mode", "asset_type")):
            return True
    return False


def _visual_asset_counts_as_answered(section_text: str, evidence_items: list[dict[str, Any]]) -> bool:
    if not _has_sendable_asset(evidence_items):
        return False
    text = section_text or ""
    return any(cue in text for cue in ("发您参考", "一起发您", "看图参考", "给您参考", "发您看"))


def _has_resolved_product_identity(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    slots = state.get("slots") if isinstance(state.get("slots"), dict) else {}
    ctx = state.get("copilot_context") if isinstance(state.get("copilot_context"), dict) else {}
    identity = state.get("order_product_identity") if isinstance(state.get("order_product_identity"), dict) else {}
    product_identity = state.get("product_identity") if isinstance(state.get("product_identity"), dict) else {}
    resolved_product = state.get("resolved_product") if isinstance(state.get("resolved_product"), dict) else {}
    product_pack = state.get("product_context_pack") if isinstance(state.get("product_context_pack"), dict) else {}
    pack_identity = product_pack.get("identity") if isinstance(product_pack.get("identity"), dict) else {}

    direct_values = (
        state.get("sku_code"),
        state.get("i_id"),
        slots.get("sku_code"),
        slots.get("i_id"),
        ctx.get("sku_code"),
        ctx.get("i_id"),
        identity.get("sku_id"),
        identity.get("i_id"),
        product_identity.get("sku_code"),
        product_identity.get("i_id"),
        resolved_product.get("sku_code"),
        resolved_product.get("i_id"),
        pack_identity.get("sku_code"),
        pack_identity.get("i_id"),
    )
    if any(str(value or "").strip() for value in direct_values):
        return True
    if identity.get("status") == "resolved" or product_identity.get("status") == "resolved":
        return True
    if any(str(source.get("product_name") or source.get("matched_product_name") or "").strip() for source in (
        identity,
        product_identity,
        resolved_product,
        pack_identity,
    )):
        return True
    return _has_verified_product_candidate(state.get("product_candidates")) or _has_verified_product_candidate(ctx.get("product_candidates"))


def _has_verified_product_candidate(candidates: Any) -> bool:
    if not isinstance(candidates, list):
        return False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("verified") is True or candidate.get("is_verified") is True:
            return True
        status = str(candidate.get("status") or candidate.get("match_status") or "").lower()
        if status in {"verified", "resolved", "matched"}:
            return True
    return False


def _suppress_identity_prompt_when_product_resolved(
    reply: str,
    state: dict[str, Any] | None,
    *,
    intent: str = "",
    required_fact_types: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not reply or not _has_resolved_product_identity(state):
        return reply, {"suppressed": False, "reason": ""}
    if not _identity_prompt_suppression_applies(intent, required_fact_types or []):
        return reply, {"suppressed": False, "reason": ""}

    lines = reply.splitlines()
    kept: list[str] = []
    suppressed = False
    for line in lines:
        if _is_identity_prompt(line):
            suppressed = True
            continue
        kept.append(line)
    cleaned = _clean_reply("\n".join(kept))
    if not suppressed:
        return reply, {"suppressed": False, "reason": ""}
    if not cleaned:
        cleaned = "这款商品我已经帮您对到了，相关细节我会按已确认资料继续核实，避免说错。"
    elif not any(cue in cleaned for cue in ("已经帮您对到了", "按已确认资料", "当前商品", "这款")):
        cleaned = f"{cleaned}\n这款商品我已经帮您对到了，相关细节我会按已确认资料继续核实，避免说错。"
    return cleaned, {"suppressed": True, "reason": "resolved_product_identity"}


def _identity_prompt_suppression_applies(intent: str, required_fact_types: list[str]) -> bool:
    if str(intent or "") in {"logistics", "logistics_eta", "logistics_trace", "shipping", "delivery_not_received"}:
        return False
    if str(intent or "") == "aftersales":
        return False
    return bool(set(required_fact_types or []) & PRODUCT_IDENTITY_FACT_TYPES) or str(intent or "") in {
        "product_question",
        "product_consult",
        "material_safety",
        "child_safety",
        "odor_question",
    }


def _is_identity_prompt(text: str) -> bool:
    line = str(text or "")
    if not any(term in line for term in IDENTITY_PROMPT_TERMS):
        return False
    prompt_cues = ("麻烦", "请", "发", "提供", "补充", "把", "截图", "链接", "订单号", "标题")
    return any(cue in line for cue in prompt_cues)


def _evidence_for_fact_type(
    fact_type: str,
    group: dict[str, Any],
    selected_evidence: list[dict[str, Any]],
    selected_assets: list[dict[str, Any]],
    *,
    product_name: str = "",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in group.get("selected_evidence") or []:
        if isinstance(item, dict):
            items.append(item)
    for item in selected_evidence:
        if isinstance(item, dict) and _supports_fact_type(item, fact_type):
            items.append(item)
    if fact_type == "visual_asset":
        items.extend([item for item in selected_assets if isinstance(item, dict)])
    items = _filter_composable_evidence(items, fact_type)
    return _dedupe_evidence(_filter_unscoped_faq_items(items, product_name))


def _filter_composable_evidence(items: list[dict[str, Any]], fact_type: str) -> list[dict[str, Any]]:
    product_fact_types = {
        "material",
        "certification_report",
        "dimensions",
        "space_fit",
        "placement_scene",
        "age_range",
        "odor",
        "cleaning_care",
        "load_capacity",
    }
    if fact_type not in product_fact_types:
        return items
    allowed_sources = {"faq", "product_facts", "product_fact", "product_media", "installation_guide"}
    filtered: list[dict[str, Any]] = []
    for item in items:
        source_type = str(item.get("source_type") or "").lower()
        if source_type and source_type not in allowed_sources:
            continue
        title = str(item.get("title") or item.get("asset_title") or "")
        if "边界" in title or "政策" in title or "红线" in title:
            continue
        filtered.append(item)
    return filtered


def _filter_unscoped_faq_items(items: list[dict[str, Any]], product_name: str) -> list[dict[str, Any]]:
    if product_name:
        return items
    filtered: list[dict[str, Any]] = []
    for item in items:
        source_type = str(item.get("source_type") or "").lower()
        if source_type == "faq":
            continue
        filtered.append(item)
    return filtered


def _supports_fact_type(item: dict[str, Any], fact_type: str) -> bool:
    ev_type = item.get("evidence_fact_type") or item.get("fact_type") or item.get("query_fact_type") or ""
    if fact_type == "certification_report" and str(ev_type) != "certification_report":
        return False
    if ev_type and fact_type_matches(fact_type, str(ev_type)):
        return True
    inferred = infer_evidence_fact_type(item)
    return bool(inferred and fact_type_matches(fact_type, inferred))


def _section_for_fact_type(
    fact_type: str,
    evidence_items: list[dict[str, Any]],
    *,
    customer_message: str,
    product_name: str,
    customer_tone: str,
) -> str:
    evidence_text = _best_evidence_text(evidence_items)
    product = f"{product_name}" if product_name else "这款"

    if fact_type == "material":
        if evidence_text:
            return f"宝宝用的东西谨慎一点是对的，{_trim_sentence(evidence_text)}；建议按页面使用说明正常使用，收到后也可以先通风再给宝宝接触。"
        return "宝宝用的东西谨慎一点是对的，材质、安全和防潮表现需要以对应款式页面说明为准；收到后建议先通风，使用中尽量保持干燥。"
    if fact_type == "certification_report":
        if evidence_text:
            return f"\u8bc1\u4e66/\u68c0\u6d4b\u62a5\u544a\u8fd9\u5757\uff0c{_trim_sentence(evidence_text)}\uff1b\u5177\u4f53\u7ed3\u8bba\u8981\u4ee5\u62a5\u544a\u6807\u6ce8\u4e3a\u51c6\uff0c\u6211\u4e0d\u4f1a\u6269\u5c55\u6210\u7edd\u5bf9\u5b89\u5168\u62160\u7532\u919b\u7684\u627f\u8bfa\u3002"
        return "\u8bc1\u4e66/\u68c0\u6d4b\u62a5\u544a\u8fd9\u5757\u9700\u8981\u770b\u5bf9\u5e94\u5546\u54c1\u7684\u660e\u786e\u7d20\u6750\u6216\u9875\u9762\u8bf4\u660e\uff1b\u6ca1\u6709\u8bc1\u636e\u65f6\u4e0d\u76f4\u63a5\u4e0b\u5b89\u5168\u7ed3\u8bba\u3002"
    if fact_type == "stock_shipping":
        return "发货这块要看当前库存、下单时间和仓库截单情况；没有实时核实前，我不能承诺今天一定发出，我会按下单页和仓库状态帮您确认。"
    if fact_type == "dimensions":
        if evidence_text:
            return f"尺寸方面，{_trim_sentence(evidence_text)}。"
        return "尺寸需要看对应款式的长宽高和尺寸图来确认，避免只凭名称判断放置空间。"
    if fact_type == "visual_asset":
        if _has_sendable_asset(evidence_items):
            asset_name = _asset_title(evidence_items[0]) or "图片/尺寸图"
            return f"图片这边可以把当前商品的{asset_name}一起发您参考。"
        return "目前没有可直接发送的图片/视频素材，我先帮您核对对应商品，确认清楚后再回复您。"
    if fact_type == "space_fit":
        if evidence_text:
            return f"能不能放下主要看长宽高、占地和预留空间，{_trim_sentence(evidence_text)}；您也可以量一下预留位置，我按尺寸帮您对。"
        return "卧室空间比较小的话，重点看商品长宽高、占地和开合/取放预留空间；您可以量一下预留位置的长宽高，我按对应款式帮您判断。"
    if fact_type == "placement_scene":
        if evidence_text:
            return f"摆放场景上，{_trim_sentence(evidence_text)}；卧室使用建议放在平整、干燥、通风的位置。"
        return "卧室、客厅、书房这类场景一般要看地面是否平整、环境是否干燥通风，以及是否影响日常通行；如果是潮湿位置，建议先核对材质和页面提示。"
    if fact_type == "aftersales_policy":
        if _is_complaint(customer_message, customer_tone):
            return "给您添麻烦了，这个情况我先帮您按售后问题处理；我会先核对订单和实物情况，再给您安排对应处理方式。"
        return "少件、错发、破损这类情况可以先按售后流程处理；如果您想退货，可以先按平台售后路径提交，我这边同步帮您跟进。为了加快核对，麻烦把收到的商品和异常位置拍清楚发我。"
    if fact_type == "installation":
        if evidence_text:
            return f"安装这块，{_trim_sentence(evidence_text)}；如果配件不齐，先不要硬装，等售后核对后再继续安装。"
        return "安装不了时要先确认配件是否齐全；如果是少件导致装不上，先按售后核对，配件没确认前不建议硬装。"
    if fact_type == "age_range":
        if evidence_text:
            return f"适用年龄方面，{_trim_sentence(evidence_text)}；实际还要结合宝宝身高、活动能力和家长看护情况。"
        return "适合多大宝宝需要看对应款式的适龄说明和宝宝实际情况；没有明确证据时，我不会直接说一定适合某个年龄段。"
    if fact_type == "odor":
        if evidence_text:
            return f"气味方面，{_trim_sentence(evidence_text)}；刚拆封建议先通风，若有明显刺鼻或久散不掉的味道，先暂停使用并联系我们处理。"
        return "新商品刚拆封可能会有包装或材料本身的味道，建议先放在通风处散一散；如果味道明显刺鼻或通风后仍不散，先暂停使用并联系我们继续处理。"
    if fact_type == "cleaning_care":
        if evidence_text:
            return f"清洁保养方面，{_trim_sentence(evidence_text)}。"
        return "清洁方式要按对应材质和结构来确认；未核实前不建议整件机洗、长时间浸泡或使用强刺激清洁剂。"
    if fact_type == "load_capacity":
        if evidence_text:
            return f"承重方面，{_trim_sentence(evidence_text)}；建议日常均匀摆放，避免单点长期压重。"
        return "能放多少需要看对应款式的承重或容量说明；没有明确参数时，不建议直接按别的商品承重来判断。"
    return ""


def _join_sections(sections: list[dict[str, Any]], customer_tone: str) -> str:
    texts = [_clean_reply(str(section.get("text") or "")) for section in sections if section.get("text")]
    texts = [text for text in texts if text]
    if not texts:
        return ""
    intro = "亲亲，" if customer_tone != "complaint" else "亲，"
    if len(texts) == 1:
        return intro + texts[0]
    if len(texts) == 2:
        return intro + " ".join(texts)
    return intro + "您这边问到的点我分开帮您说明：\n" + "\n".join(
        f"{index}. {text}" for index, text in enumerate(texts, start=1)
    )


def _best_evidence_text(items: list[dict[str, Any]]) -> str:
    for item in items:
        text = (
            item.get("chunk_text")
            or item.get("fact")
            or item.get("content")
            or item.get("answer")
            or item.get("preview")
            or item.get("chunk_preview")
            or ""
        )
        text = _clean_reply(str(text))
        if text:
            return text
    return ""


def _trim_sentence(text: str, limit: int = 90) -> str:
    text = _clean_reply(text)
    if len(text) <= limit:
        return text.rstrip("。")
    return text[:limit].rstrip("，。；; ") + "..."


def _asset_title(item: dict[str, Any]) -> str:
    return str(item.get("asset_title") or item.get("title") or item.get("name") or "").strip()


def _customer_tone(message: str, risk_level: str, intent: str) -> str:
    text = message or ""
    if str(risk_level or "").lower() in {"high", "critical"} or intent in {"complaint", "high_risk"}:
        return "complaint"
    if any(word in text for word in ("投诉", "平台介入", "差评", "太差", "不处理")):
        return "complaint"
    if any(word in text for word in ("宝宝", "安全", "味道", "受潮")):
        return "reassuring"
    return "professional"


def _is_complaint(message: str, tone: str) -> bool:
    return tone == "complaint" or any(word in (message or "") for word in ("投诉", "平台介入", "差评", "太差"))


def _remove_forbidden_claims(reply: str) -> tuple[str, list[str]]:
    blocked: list[str] = []
    clean = reply
    replacements = {
        "绝对安全": "按页面说明正常使用",
        "100%安全": "按页面说明正常使用",
        "百分百安全": "按页面说明正常使用",
        "一定今天发": "需要以仓库实际处理为准",
        "今天一定发": "需要以仓库实际处理为准",
        "一定能发": "需要以仓库实际处理为准",
        "保证今天发": "需要以仓库实际处理为准",
        "保证能到": "以物流实际更新为准",
        "一定能到": "以物流实际更新为准",
        "肯定能到": "以物流实际更新为准",
        "保证无味": "建议先通风观察",
        "绝对无味": "建议先通风观察",
        "0甲醛": "以检测或页面说明为准",
        "零甲醛": "以检测或页面说明为准",
        "一定适合": "需要结合宝宝实际情况确认",
        "直接赔": "按售后流程处理",
        "一定赔": "按售后流程处理",
    }
    for claim, replacement in replacements.items():
        if claim in clean:
            blocked.append(claim)
            clean = clean.replace(claim, replacement)
    return clean, blocked


def _remove_internal_terms(reply: str) -> str:
    clean = reply
    for term in INTERNAL_TERMS:
        clean = clean.replace(term, "资料")
    clean = clean.replace("资料资料", "资料")
    return clean


def _clean_reply(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(" \n\t")


def _summarize_evidence(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "entry_id": item.get("entry_id", ""),
        "chunk_id": item.get("chunk_id", ""),
        "asset_id": item.get("asset_id") or item.get("id") or "",
        "asset_type": item.get("asset_type", ""),
        "asset_title": item.get("asset_title", ""),
        "asset_url": item.get("asset_url") or item.get("url") or "",
        "title": item.get("title") or item.get("asset_title") or "",
        "source_type": item.get("source_type", ""),
        "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or item.get("query_fact_type") or "",
        "evidence_origin": item.get("evidence_origin") or metadata.get("evidence_origin", ""),
        "preview": _trim_sentence(_best_evidence_text([item]), 60),
    }


def _evidence_origins(items: list[dict[str, Any]]) -> list[str]:
    origins: list[str] = []
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        origin = str(item.get("evidence_origin") or metadata.get("evidence_origin") or item.get("source_type") or "").strip()
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def _trace_items_by_origin(
    evidence_used_by_fact_type: dict[str, list[dict[str, Any]]],
    origin: str,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for fact_type, items in evidence_used_by_fact_type.items():
        matched = [item for item in items if item.get("evidence_origin") == origin]
        if matched:
            out[fact_type] = matched
    return out


def _trace_asset_items(evidence_used_by_fact_type: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for fact_type, items in evidence_used_by_fact_type.items():
        matched = [item for item in items if item.get("asset_id") or item.get("asset_url")]
        if matched:
            out[fact_type] = matched
    return out


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("entry_id") or ""),
            str(item.get("chunk_id") or ""),
            str(item.get("asset_id") or item.get("id") or item.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
