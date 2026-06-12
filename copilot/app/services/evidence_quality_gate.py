"""
Knowledge Evidence Quality Gate — 高风险商品事实审核门

规则:
1. source_type=product_facts 或 faq 且回答涉及高风险商品事实:
   - fact_review_status 必须为 verified 才允许直接回答。
2. fact_review_status 为空/pending/needs_update/rejected:
   - answer_mode 改为 evidence_needs_review 或 no_evidence_clarification。
   - 回复改为核实型话术。
3. evidence 来自 real_cases / feedback_records，默认不能作为强事实依据。
4. evidence_debug 显示 fact_review_status, fact_confidence, high_risk_fact_fields,
   evidence_allowed_for_direct_answer。
"""

import logging

logger = logging.getLogger(__name__)

HIGH_RISK_FACT_FIELDS = (
    "材质", "填充物", "承重", "适用年龄", "洗涤方式", "是否食品级",
    "是否3C", "是否无毒无味", "是否实木", "是否绝对安全", "是否可机洗",
    "填充", "防水", "机洗", "实木", "食品级", "无毒", "重量", "尺寸",
    "材质说明",
)

# 不允许作为强事实依据的 source_type
WEAK_SOURCE_TYPES = {"real_cases", "feedback_records", "customer_service_case"}

VERIFIED_STATUSES = {"verified"}

UNVERIFIED_STATUSES = {"pending", "needs_update", "rejected", "draft_unverified", "draft"}

CLARIFICATION_REPLY = (
    "这类参数需要结合具体商品/SKU确认，"
    "麻烦发一下商品链接、订单截图或具体款式，我帮您核实准确参数～"
)


def check_evidence_quality(evidence: dict, knowledge_evidence: list = None) -> dict:
    """
    检查证据质量，返回质量门结果。

    Returns:
        {
            "all_verified": bool,
            "blocked_items": list,
            "high_risk_fact_fields": list,
            "weak_source_items": list,
            "evidence_allowed_for_direct_answer": bool,
        }
    """
    knowledge_evidence = knowledge_evidence or []

    blocked_items = []
    weak_source_items = []
    high_risk_fact_fields = []
    all_verified = True

    product_facts = evidence.get("product_facts", [])
    faq_evidence_list = evidence.get("faq_evidence", [])

    for item in product_facts + faq_evidence_list:
        source_type = item.get("source_type", "")
        text = item.get("fact", "") or item.get("chunk_text", "")
        fact_review_status = item.get("fact_review_status", "")
        entry_status = item.get("entry_status", "unknown")

        if source_type in WEAK_SOURCE_TYPES:
            weak_source_items.append({
                "entry_id": item.get("entry_id"),
                "title": item.get("title", ""),
                "source_type": source_type,
                "fact_review_status": fact_review_status,
            })
            item["evidence_allowed_for_direct_answer"] = False
            continue

        if source_type not in ("product_facts", "faq"):
            continue

        risk_fields = _detect_high_risk_fields(text)
        if not risk_fields:
            continue

        for f in risk_fields:
            if f not in high_risk_fact_fields:
                high_risk_fact_fields.append(f)

        is_unverified = (
            entry_status == "draft"
            or (entry_status != "published" and fact_review_status in UNVERIFIED_STATUSES)
            or (not fact_review_status and entry_status != "published")
        )

        if is_unverified:
            all_verified = False
            blocked_items.append({
                "matched_entry_id": item.get("entry_id"),
                "matched_title": item.get("title", ""),
                "source_type": source_type,
                "fact_review_status": fact_review_status,
                "fact_confidence": item.get("confidence", "low"),
                "fact_source": item.get("fact_source", "unknown"),
                "high_risk_fact_fields": risk_fields,
                "evidence_allowed_for_direct_answer": False,
            })
            item["evidence_allowed_for_direct_answer"] = False
            item["unverified_fact"] = True
        else:
            item["evidence_allowed_for_direct_answer"] = True

    evidence_allowed = all_verified and not blocked_items

    return {
        "all_verified": all_verified,
        "blocked_items": blocked_items,
        "high_risk_fact_fields": high_risk_fact_fields,
        "weak_source_items": weak_source_items,
        "evidence_allowed_for_direct_answer": evidence_allowed,
    }


def enforce_evidence_quality_gate(state: dict) -> dict:
    """
    在 factual_guard 之后、build_response 之前执行。
    如果高风险商品事实未审核，强制修改 answer_mode 和 suggested_reply。

    Returns:
        dict with keys to merge into state.
    """
    evidence = state.get("evidence", {})
    knowledge_evidence = state.get("knowledge_evidence", [])
    answer_mode = state.get("answer_mode", "")
    guard_warnings = list(state.get("guard_warnings", []))
    suggested_reply = state.get("suggested_reply", "")
    intent = state.get("intent", "")

    quality_result = check_evidence_quality(evidence, knowledge_evidence)

    blocked = quality_result["blocked_items"]
    weak_sources = quality_result["weak_source_items"]
    allowed = quality_result["evidence_allowed_for_direct_answer"]

    if not blocked and not weak_sources:
        return {
            "evidence": evidence,
            "guard_warnings": guard_warnings,
            "evidence_quality": quality_result,
        }

    warnings = []

    if blocked:
        for b in blocked:
            warnings.append(
                f"evidence_quality_gate: blocked unverified high-risk fact "
                f"(entry={b.get('matched_entry_id')}, fields={b.get('high_risk_fact_fields')}, "
                f"status={b.get('fact_review_status')})"
            )

        if answer_mode in ("exact_faq_answer", "product_fact_answer", "product_answer"):
            answer_mode = "evidence_needs_review"
            warnings.append("evidence_quality_gate: changed answer_mode to evidence_needs_review")
        else:
            answer_mode = "no_evidence_clarification"
            warnings.append("evidence_quality_gate: changed answer_mode to no_evidence_clarification")

        suggested_reply = CLARIFICATION_REPLY
        logger.info(
            "evidence_quality_gate blocked %d unverified items, forced conservative reply",
            len(blocked),
        )

    if weak_sources:
        for w in weak_sources:
            warnings.append(
                f"evidence_quality_gate: weak source type '{w.get('source_type')}' "
                f"used as strong fact (entry={w.get('entry_id')})"
            )

    guard_warnings.extend(warnings)

    return {
        "answer_mode": answer_mode,
        "suggested_reply": suggested_reply,
        "evidence": evidence,
        "guard_warnings": guard_warnings,
        "evidence_quality": quality_result,
    }


def _detect_high_risk_fields(text: str) -> list:
    found = []
    for field in HIGH_RISK_FACT_FIELDS:
        if field in text:
            found.append(field)
    return found
