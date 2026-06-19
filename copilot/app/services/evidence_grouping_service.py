"""Evidence grouping and multi-intent answer planning.

This layer uses the evidence that the existing RAG/tool chain already selected.
It does not retrieve new data and does not relax evidence gates.
"""

from __future__ import annotations

from typing import Any

from app.services.fact_type_service import FACT_TYPE_LABELS, fact_type_matches, infer_evidence_fact_type


FACT_TYPE_TO_SUB_INTENT = {
    "material": "material_safety",
    "certification_report": "material_safety",
    "age_range": "age_range",
    "dimensions": "dimensions",
    "visual_asset": "visual_asset",
    "stock_shipping": "stock_query",
    "aftersales_policy": "aftersales",
    "installation": "installation",
    "cleaning_care": "cleaning_care",
    "odor": "odor_question",
}

HIGH_RISK_MISSING_FACT_TYPES = {
    "age_range",
    "certification_report",
    "pinch_safety",
    "safety_small_parts",
    "stability",
}

POLICY_SUPPORTED_FACT_TYPES = {
    "stock_shipping",
    "aftersales_policy",
    "installation",
}


def group_evidence_by_fact_type(evidence: dict[str, Any], query_understanding: dict[str, Any]) -> dict[str, Any]:
    required = _required_fact_types(query_understanding)
    selected_pool = _selected_pool(evidence)
    rejected_pool = _rejected_pool(evidence)
    product_pack = evidence.get("product_context_pack") or {}
    selected_assets = _selected_assets(evidence, product_pack)
    generic_rules = _generic_rules(product_pack)

    groups = []
    for fact_type in required:
        selected = [
            item for item in selected_pool
            if _evidence_supports_fact_type(item, fact_type)
        ]
        rejected = [
            item for item in rejected_pool
            if _evidence_supports_fact_type(item, fact_type)
            or item.get("query_fact_type") == fact_type
        ]
        matched_rules = [rule for rule in generic_rules if rule.get("fact_type") == fact_type]
        if fact_type == "visual_asset":
            selected.extend(selected_assets)

        status = _group_status(fact_type, selected, matched_rules)
        answer_policy = _answer_policy(fact_type, status, matched_rules)
        groups.append({
            "fact_type": fact_type,
            "fact_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
            "sub_intent": FACT_TYPE_TO_SUB_INTENT.get(fact_type, "product_question"),
            "status": status,
            "selected_evidence": _summarize_items(selected),
            "rejected_evidence": _summarize_items(rejected),
            "missing_fields": [] if status == "supported" else [FACT_TYPE_LABELS.get(fact_type, fact_type)],
            "risk_hints": _risk_hints(fact_type, status),
            "answer_policy": answer_policy,
        })

    covered = [g["fact_type"] for g in groups if g["status"] in {"supported", "needs_review"}]
    missing = [g["fact_type"] for g in groups if g["status"] == "missing"]
    return {
        "groups": groups,
        "coverage": {
            "required_fact_types": required,
            "covered_fact_types": covered,
            "missing_fact_types": missing,
        },
    }


def build_multi_intent_answer_plan(
    grouping: dict[str, Any],
    *,
    current_reply: str,
    customer_message: str = "",
) -> list[dict[str, Any]]:
    reply = current_reply or ""
    plan = []
    for group in grouping.get("groups") or []:
        fact_type = group.get("fact_type", "")
        reply_part = ""
        if not _reply_covers_fact_type(reply, fact_type):
            reply_part = _reply_part_for_group(group, customer_message)
        plan.append({
            "fact_type": fact_type,
            "sub_intent": group.get("sub_intent", ""),
            "answer_mode": group.get("answer_policy", ""),
            "covered_by_existing_reply": not bool(reply_part),
            "reply_part": reply_part,
        })
    return plan


def merge_multi_intent_reply(current_reply: str, plan: list[dict[str, Any]]) -> str:
    additions = [item.get("reply_part", "").strip() for item in plan if item.get("reply_part")]
    additions = [item for item in additions if item]
    if not additions:
        return current_reply
    base = (current_reply or "").strip()
    if not base:
        return "\n".join(additions)
    return base + "\n" + "\n".join(additions)


def _required_fact_types(query_understanding: dict[str, Any]) -> list[str]:
    rejected = str(query_understanding.get("llm_rejected_fact_type") or "").strip()
    values = [
        query_understanding.get("query_fact_type", ""),
        *(query_understanding.get("secondary_fact_types") or []),
    ]
    out = []
    for value in values:
        text = str(value or "").strip()
        if text and text != rejected and text not in out:
            out.append(text)
    return out


def _selected_pool(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    pool = []
    product_pack = evidence.get("product_context_pack") or {}
    for key in ("product_card_evidence", "media_evidence"):
        pool.extend([item for item in product_pack.get(key, []) or [] if isinstance(item, dict)])
    for key in ("knowledge_evidence", "filtered_evidence", "selected_evidence"):
        pool.extend([item for item in evidence.get(key, []) or [] if isinstance(item, dict)])
    raw_evidence = evidence.get("evidence") or {}
    for key in ("product_facts", "faq_evidence", "policy_facts", "sop_evidence", "template_evidence"):
        pool.extend([item for item in raw_evidence.get(key, []) or [] if isinstance(item, dict)])
    evidence_pack = product_pack.get("evidence_pack") or {}
    pool.extend([_expand_compact_fact(item) for item in evidence_pack.get("matched_facts", []) or [] if isinstance(item, dict)])
    return _dedupe_items(pool)


def _rejected_pool(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return _dedupe_items([item for item in evidence.get("rejected_evidence", []) or [] if isinstance(item, dict)])


def _selected_assets(evidence: dict[str, Any], product_pack: dict[str, Any]) -> list[dict[str, Any]]:
    assets = []
    assets.extend([item for item in evidence.get("selected_assets", []) or [] if isinstance(item, dict)])
    assets.extend([item for item in product_pack.get("selected_assets", []) or [] if isinstance(item, dict)])
    assets.extend([item for item in product_pack.get("recommended_assets", []) or [] if isinstance(item, dict)])
    assets.extend([
        item for item in product_pack.get("media_evidence", []) or []
        if isinstance(item, dict) and _evidence_supports_fact_type(item, "visual_asset")
    ])
    return _dedupe_items([
        {
            **item,
            "evidence_fact_type": "visual_asset",
            "fact_type": "visual_asset",
            "source_type": "product_media",
            "evidence_origin": item.get("evidence_origin") or "product_media",
        }
        for item in assets
    ])


def _generic_rules(product_pack: dict[str, Any]) -> list[dict[str, Any]]:
    rules = [item for item in product_pack.get("generic_rules", []) or [] if isinstance(item, dict)]
    evidence_pack = product_pack.get("evidence_pack") or {}
    rules.extend([item for item in evidence_pack.get("matched_generic_rules", []) or [] if isinstance(item, dict)])
    return _dedupe_items(rules)


def _evidence_supports_fact_type(item: dict[str, Any], fact_type: str) -> bool:
    ev_type = item.get("evidence_fact_type") or item.get("fact_type") or item.get("query_fact_type") or ""
    if fact_type == "certification_report" and str(ev_type) != "certification_report":
        return False
    if ev_type and fact_type_matches(fact_type, str(ev_type)):
        return True
    inferred = infer_evidence_fact_type(item)
    return bool(inferred and fact_type_matches(fact_type, inferred))


def _group_status(fact_type: str, selected: list[dict[str, Any]], rules: list[dict[str, Any]]) -> str:
    if selected:
        if any(item.get("requires_human_review") or item.get("needs_human_review") for item in selected):
            return "needs_review"
        return "supported"
    if fact_type in POLICY_SUPPORTED_FACT_TYPES:
        return "supported"
    if rules and str(rules[0].get("risk_level") or "low") == "low":
        return "supported"
    return "missing"


def _answer_policy(fact_type: str, status: str, rules: list[dict[str, Any]]) -> str:
    if status == "missing":
        return "handoff" if fact_type in HIGH_RISK_MISSING_FACT_TYPES else "generic_rule"
    if rules:
        return "generic_rule"
    if fact_type == "stock_shipping":
        return "policy_or_realtime"
    return "direct"


def _risk_hints(fact_type: str, status: str) -> list[str]:
    hints = []
    if fact_type in HIGH_RISK_MISSING_FACT_TYPES:
        hints.append("high_risk_fact_requires_evidence")
    if status == "missing":
        hints.append("missing_supporting_evidence")
    return hints


def _reply_covers_fact_type(reply: str, fact_type: str) -> bool:
    text = reply or ""
    cues = {
        "material": ("材质", "材料", "安全", "宝宝", "防潮", "防水", "检测"),
        "stock_shipping": ("发货", "库存", "现货", "仓库", "下单页", "今天"),
        "dimensions": ("尺寸", "长", "宽", "高", "尺寸图"),
        "visual_asset": ("图", "图片", "素材", "视频"),
        "aftersales_policy": ("售后", "补发", "少件", "缺配件", "退货", "退款"),
        "installation": ("安装", "组装", "教程", "说明"),
        "age_range": ("适合", "宝宝", "年龄", "月龄", "适龄"),
        "cleaning_care": ("清洁", "清洗", "湿布", "擦"),
    }.get(fact_type, (FACT_TYPE_LABELS.get(fact_type, fact_type),))
    return any(cue and cue in text for cue in cues)


def _reply_part_for_group(group: dict[str, Any], customer_message: str) -> str:
    fact_type = group.get("fact_type", "")
    status = group.get("status", "")
    if fact_type == "stock_shipping":
        return "发货这块需要以当前库存、下单页显示和仓库实际处理为准；没核实前我不会给出当天必发的确定承诺。"
    if fact_type == "material":
        return "宝宝使用和材质安全这块我会按商品材质/检测说明来核对；没有证据时不说绝对安全。"
    if fact_type == "dimensions":
        return "尺寸需要按对应款式的长宽高或尺寸图确认，我不会用承重或材质来代替尺寸回答。"
    if fact_type == "visual_asset":
        return "如果页面有对应图片/尺寸图/素材，我这边可以按当前商品素材发您参考。"
    if fact_type == "aftersales_policy":
        return "少件/缺配件属于售后核对范围，我会先按订单和实物情况确认能否补发或处理。"
    if fact_type == "installation":
        return "安装不了也需要结合缺少的配件一起判断；配件不齐时不建议只按安装教程硬装。"
    if fact_type == "age_range":
        return "适龄这块需要有明确适用年龄或使用场景证据；没有证据时我先保守核实，不直接下适合一岁宝宝的结论。"
    if status == "missing":
        return f"{group.get('fact_label') or fact_type}这块我先保守核实，避免没有依据直接下结论。"
    return ""


def _summarize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items[:8]:
        preview = (
            item.get("chunk_text")
            or item.get("fact")
            or item.get("content")
            or item.get("answer")
            or item.get("description")
            or ""
        )
        out.append({
            "chunk_id": item.get("chunk_id", ""),
            "entry_id": item.get("entry_id", ""),
            "asset_id": item.get("asset_id") or item.get("id") or "",
            "asset_type": item.get("asset_type", ""),
            "asset_title": item.get("asset_title", ""),
            "asset_url": item.get("asset_url") or item.get("url") or "",
            "url": item.get("url") or item.get("asset_url") or "",
            "sendable": item.get("sendable", False),
            "title": item.get("title") or item.get("asset_title") or "",
            "source_type": item.get("source_type", ""),
            "fact_type": item.get("evidence_fact_type") or item.get("fact_type") or item.get("query_fact_type") or "",
            "evidence_origin": item.get("evidence_origin") or (item.get("metadata") or {}).get("evidence_origin", ""),
            "metadata": item.get("metadata", {}),
            "preview": str(preview)[:120],
            "chunk_preview": str(preview)[:120],
            "gate_status": item.get("gate_status", ""),
            "gate_reasons": item.get("gate_reasons", []),
            "rejection_reasons": item.get("rejection_reasons") or item.get("reasons") or [],
        })
    return out


def _expand_compact_fact(item: dict[str, Any]) -> dict[str, Any]:
    preview = item.get("preview") or item.get("chunk_preview") or ""
    return {
        **item,
        "chunk_text": preview,
        "evidence_fact_type": item.get("fact_type", ""),
    }


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = (
            item.get("chunk_id"),
            item.get("entry_id"),
            item.get("asset_id") or item.get("id"),
            item.get("title") or item.get("asset_title"),
            item.get("fact_type") or item.get("evidence_fact_type"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
