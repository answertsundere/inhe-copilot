"""Structured gate for deciding how a retrieved evidence item may be used."""

from __future__ import annotations

import re
from typing import Any

from app.services.fact_type_service import fact_type_matches, is_strict_fact_type
from app.services.product_structured_evidence_service import material_evidence_admission_reason


DIRECT_SOURCE_TYPES = {
    "product_facts",
    "faq",
    "shipping_policy",
    "aftersales_policy",
    "installation_guide",
    "high_risk_sop",
    "response_templates",
}

REFERENCE_ONLY_SOURCE_TYPES = {
    "product_mapping",
    "real_cases",
    "feedback_records",
}

HIGH_RISK_FACT_TYPES = {
    "material",
    "certification_report",
    "load_capacity",
    "stability",
    "dimensions",
    "age_range",
    "odor",
    "pinch_safety",
    "safety_small_parts",
}

REVIEWED_STATUSES = {"verified", "published", "high"}
UNREVIEWED_STATUSES = {
    "draft",
    "draft_unverified",
    "pending",
    "needs_update",
    "rejected",
}

# 安装/使用类证据里“免工具、几分钟装好”等可能误导买家的便利性表述。
# 这类表述不应让整条证据变成 reference_only，而是先清洗表述、再放行。
RISKY_CONVENIENCE_PHRASES = (
    "安装很方便",
    "安装非常方便",
    "安装很简单",
    "安装简单",
    "操作很简单",
    "操作简单",
    "很容易安装",
    "轻松安装",
    "不需要额外工具",
    "无需额外工具",
    "不需要额外准备工具",
    "无需额外准备工具",
    "免工具安装",
    "一般15-20分钟就能完成安装",
    "15-20分钟就能完成安装",
)


def sanitize_risky_convenience_claim(text: str) -> tuple[str, bool]:
    """移除安装便利性/免工具类表述，返回 (清洗后文本, 是否发生清洗)。"""
    sanitized = text or ""
    applied = False
    for phrase in RISKY_CONVENIENCE_PHRASES:
        if phrase in sanitized:
            sanitized = sanitized.replace(phrase, "")
            applied = True
    if applied:
        sanitized = re.sub(r"^[\s，,。\.；;！？!?:：、~～]+", "", sanitized)
        sanitized = re.sub(r"[，,。\.；;！？!?:：、~～]{2,}", "。", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized).strip(" ，,。.；;！？!?:：、~～")
    return sanitized, applied


def evaluate_evidence_item(item: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a normalized decision for one retrieved evidence item.

    This is deliberately conservative and backwards-compatible: existing
    ``published`` entries remain usable, while draft/pending high-risk facts
    are blocked from direct customer replies.
    """

    state = state or {}
    reasons: list[str] = []

    source_type = str(item.get("source_type") or "")
    query_fact_type = str(item.get("query_fact_type") or state.get("query_fact_type") or "")
    evidence_fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "")
    entry_status = str(item.get("entry_status") or "").lower()
    fact_review_status = str(item.get("fact_review_status") or "").lower()
    rerank_score = _to_float(item.get("rerank_score", item.get("score", 0)))
    exact_allowed = bool(item.get("evidence_allowed_for_exact_answer", rerank_score >= 0.3))
    reference_only = bool(item.get("reference_only", False))
    requires_human_review = bool(item.get("needs_human_review", False))

    if source_type in REFERENCE_ONLY_SOURCE_TYPES:
        reference_only = True
        reasons.append("reference_only_source")

    if source_type and source_type not in DIRECT_SOURCE_TYPES and source_type not in REFERENCE_ONLY_SOURCE_TYPES:
        reference_only = True
        reasons.append("source_type_not_direct")

    if item.get("metadata", {}).get("auto_reply_allowed") is False:
        reference_only = True
        reasons.append("auto_reply_disabled")

    mismatch_reason = item.get("mismatch_reason") or ""
    if mismatch_reason:
        reasons.append(str(mismatch_reason))

    if query_fact_type and not fact_type_matches(query_fact_type, evidence_fact_type):
        reasons.append("wrong_fact_type")
        exact_allowed = False
        if is_strict_fact_type(query_fact_type):
            reference_only = True

    if item.get("scope_match") is False:
        reasons.append("scope_mismatch")
        exact_allowed = False

    if rerank_score < 0.3:
        reasons.append("low_score")
        exact_allowed = False

    fact_type_for_risk = query_fact_type or evidence_fact_type
    if fact_type_for_risk in HIGH_RISK_FACT_TYPES and _is_unreviewed(entry_status, fact_review_status):
        reasons.append("unverified_high_risk_fact")
        requires_human_review = True
        exact_allowed = False

    if item.get("evidence_allowed_for_direct_answer") is False:
        reasons.append("preblocked_direct_answer")
        exact_allowed = False

    material_reason = material_evidence_admission_reason({
        **item,
        "requested_fact_type": query_fact_type or evidence_fact_type,
        "evidence_fact_type": evidence_fact_type,
    })
    if material_reason:
        reasons.append(material_reason)
        reference_only = True
        requires_human_review = True
        exact_allowed = False

    risky_convenience = _contains_risky_convenience_claim(item)
    if risky_convenience:
        # 便利性表述只作为 warning 记录；installation_guide 等结构化证据会被
        # evidence_builder 清洗后再用，这里不阻断。但 faq 可能被直接渲染给买家，
        # 若未经清洗则保守阻断，避免“免工具/几分钟装好”这类表述直接外露。
        reasons.append("risky_convenience_claim")
        if source_type == "faq":
            reference_only = True
            exact_allowed = False

    if _is_absolute_stability_request(state, query_fact_type):
        reasons.append("absolute_stability_request")
        reference_only = True
        requires_human_review = True
        exact_allowed = False

    if _is_semantic_high_risk_stability(state, query_fact_type):
        reasons.append("semantic_high_risk_stability")
        reference_only = True
        requires_human_review = True
        exact_allowed = False

    blocking_reasons = {
        "wrong_fact_type",
        "scope_mismatch",
        "sku_mismatch",
        "product_scope_mismatch",
        "compare_evidence_mismatch",
        "low_score",
        "unverified_high_risk_fact",
        "preblocked_direct_answer",
        "material_source_untrusted",
        "material_provenance_missing",
        "material_placeholder",
        "material_strong_claim_mixed",
    }
    has_blocking_reason = any(reason in blocking_reasons for reason in reasons)
    direct_answer_allowed = exact_allowed and not reference_only and not has_blocking_reason

    if direct_answer_allowed:
        gate_status = "allowed"
    elif reference_only and not requires_human_review:
        gate_status = "reference_only"
    else:
        gate_status = "blocked"

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "gate_status": gate_status,
        "gate_reasons": unique_reasons,
        "direct_answer_allowed": direct_answer_allowed,
        "evidence_allowed_for_direct_answer": direct_answer_allowed,
        "reference_only": reference_only,
        "requires_human_review": requires_human_review,
        "needs_human_review": requires_human_review,
        "evidence_allowed_for_exact_answer": bool(exact_allowed and direct_answer_allowed),
    }


def apply_evidence_gate(items: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Apply the structured gate to a list of evidence items."""

    gated = []
    for item in items:
        gated_item = dict(item)
        gated_item.update(evaluate_evidence_item(gated_item, state))
        gated.append(gated_item)
    return gated


def _is_unreviewed(entry_status: str, fact_review_status: str) -> bool:
    if fact_review_status in REVIEWED_STATUSES or entry_status in REVIEWED_STATUSES:
        return False
    if fact_review_status in UNREVIEWED_STATUSES or entry_status in UNREVIEWED_STATUSES:
        return True
    return False


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_semantic_high_risk_stability(state: dict[str, Any], query_fact_type: str) -> bool:
    if query_fact_type != "stability":
        return False
    risk_hint = str(state.get("query_fact_type_risk_hint") or "").lower()
    source = str(state.get("query_fact_type_source") or "")
    return source == "llm" and risk_hint == "high"


def _contains_risky_convenience_claim(item: dict[str, Any]) -> bool:
    """Detect convenience promises that should be rewritten before customers see them."""

    text = " ".join(str(value or "") for value in (
        item.get("chunk_text"),
        item.get("fact"),
        item.get("content"),
        (item.get("metadata") or {}).get("answer"),
    ))
    if not text:
        return False

    return any(phrase in text for phrase in RISKY_CONVENIENCE_PHRASES)


def _is_absolute_stability_request(state: dict[str, Any], query_fact_type: str) -> bool:
    if query_fact_type != "stability":
        return False
    msg = str(state.get("normalized_message") or state.get("customer_message") or "")
    if not msg:
        return False
    absolute_terms = (
        "\u7edd\u5bf9",
        "\u4fdd\u8bc1",
        "\u4e00\u5b9a",
        "\u80af\u5b9a",
        "\u5b8c\u5168\u4e0d\u4f1a",
        "\u4e0d\u53ef\u80fd",
    )
    stability_terms = (
        "\u4e0d\u4f1a\u5012",
        "\u9632\u503e\u5012",
        "\u503e\u5012",
        "\u5012\u584c",
        "\u7a33\u4e0d\u7a33",
        "\u7a33\u56fa",
        "\u7a33\u5b9a",
    )
    return any(term in msg for term in absolute_terms) and any(term in msg for term in stability_terms)
