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
}

COMPOSABLE_INTENTS = {
    "complaint",
    "high_risk",
    "aftersales",
}

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
    customer_tone = _customer_tone(customer_message, risk_level, intent)

    if not required:
        required = _fallback_required_fact_types(query_understanding, intent)

    sections: list[dict[str, Any]] = []
    evidence_used_by_fact_type: dict[str, list[dict[str, Any]]] = {}
    fallback_used_by_fact_type: dict[str, bool] = {}

    for fact_type in required:
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
        evidence_used_by_fact_type[fact_type] = [_summarize_evidence(item) for item in evidence_items[:3]]
        fallback_used_by_fact_type[fact_type] = not bool(evidence_items)
        sections.append({
            "fact_type": fact_type,
            "fact_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
            "source": "evidence" if evidence_items else "fallback",
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

    covered = [section["fact_type"] for section in sections if section.get("fact_type") != "base_reply"]
    missing = [fact_type for fact_type in required if fact_type not in covered]
    trace = {
        "mode": "multi_intent" if len(required) >= 2 else "single_intent",
        "covered_fact_types": covered,
        "missing_fact_types": missing,
        "evidence_used_by_fact_type": evidence_used_by_fact_type,
        "fallback_used_by_fact_type": fallback_used_by_fact_type,
        "blocked_claims": blocked_claims,
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
    if fact_type == "stock_shipping":
        return "发货这块要看当前库存、下单时间和仓库截单情况；没有实时核实前，我不能承诺今天一定发出，我会按下单页和仓库状态帮您确认。"
    if fact_type == "dimensions":
        if evidence_text:
            return f"尺寸方面，{_trim_sentence(evidence_text)}。"
        return "尺寸需要看对应款式的长宽高和尺寸图来确认，避免只凭名称判断放置空间。"
    if fact_type == "visual_asset":
        if evidence_items:
            asset_name = _asset_title(evidence_items[0]) or "图片/尺寸图"
            return f"图片资料这块，可以参考当前商品的{asset_name}，我这边只把它作为辅助确认，不用图片替代参数结论。"
        return "如果您需要看图，我可以优先按当前商品的图片或尺寸图给您参考；没有对应素材时，不会用别的款式图片代替。"
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
    return {
        "entry_id": item.get("entry_id", ""),
        "chunk_id": item.get("chunk_id", ""),
        "asset_id": item.get("asset_id") or item.get("id") or "",
        "title": item.get("title") or item.get("asset_title") or "",
        "source_type": item.get("source_type", ""),
        "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or item.get("query_fact_type") or "",
        "preview": _trim_sentence(_best_evidence_text([item]), 60),
    }


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
