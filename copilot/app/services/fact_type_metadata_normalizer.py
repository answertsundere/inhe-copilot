"""Normalize pgvector shadow fact-type metadata without changing user intent.

This module is for pgvector shadow storage metadata only. It does not expand
query aliases, relax final gates, or rewrite formal knowledge rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_text
from app.services.fact_type_alias_service import is_high_risk_fact_type


INSTALLATION_MEDIA_ROLES = {
    "install_video",
    "installation_video",
    "install_image",
    "installation_image",
    "installation_guide",
    "manual",
    "manual_image",
    "instruction_manual",
    "pack_guide_image",
    "packing_list_image",
}
DIMENSION_MEDIA_ROLES = {"size_chart", "size_chart_image", "size_image", "dimension_image"}
ACCESSORY_MEDIA_ROLES = {"accessory_photo", "accessory_image", "parts_image", "parts_list"}

ACCESSORY_AVAILABILITY_TERMS = (
    "单独", "单卖", "补配", "补买", "补购", "另购", "能买", "可以买", "有卖", "购买",
)
ACCESSORY_USAGE_TERMS = ("怎么用", "用途", "干嘛用", "干啥用", "用来", "作用")
STRUCTURE_FUNCTION_TERMS = (
    "孔位", "加装", "改装", "适配", "第四面", "补一面", "补第四面",
)
MATERIAL_SAFETY_TERMS = ("有毒", "无毒", "气味", "异味", "甲醛")
CERTIFICATION_TERMS = ("检测", "证书", "报告", "认证", "质检", "3C", "合格证")
RETURN_PICKUP_TERMS = ("上门取件", "取件", "揽收")
REFUND_TERMS = ("退款", "退钱", "打款", "赔付", "补偿")
REPLACEMENT_TERMS = ("补发", "换货", "少件", "缺件", "发错", "破损", "坏了")
GIFT_TERMS = ("赠品", "礼品", "送", "赠送")
PRICE_NEGOTIATION_TERMS = ("便宜", "少点", "多买", "最低", "议价")

CANONICAL_FACT_TYPES = {
    "after_sales": "aftersales",
    "aftersale": "aftersales",
    "shipping": "stock_shipping",
    "delivery": "stock_shipping",
    "logistics": "stock_shipping",
    "invoice": "invoice_policy",
    "receipt": "invoice_policy",
    "billing": "invoice_policy",
    "promotion": "promotion_policy",
    "coupon": "promotion_policy",
    "discount": "promotion_policy",
    "size": "dimensions",
    "cleaning": "cleaning_care",
    "maintenance": "cleaning_care",
    "parts": "accessories",
    "accessory": "accessories",
}

HIGH_RISK_NORMALIZATION_TARGETS = {
    "age_range",
    "child_suitability",
    "load_capacity",
    "certification_report",
    "food_grade",
    "non_toxic_claim",
    "safety_claim",
    "electrical_safety",
}


@dataclass(frozen=True)
class FactTypeNormalization:
    original_query_fact_type: str
    normalized_query_fact_type: str
    original_evidence_role: str
    normalized_evidence_role: str
    reason: str
    high_risk_blocked: bool = False

    @property
    def changed(self) -> bool:
        return (
            self.original_query_fact_type != self.normalized_query_fact_type
            or self.original_evidence_role != self.normalized_evidence_role
        )


def _text(*values: Any) -> str:
    return " ".join(sanitize_text(value) for value in values if sanitize_text(value))


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _media_fact_type(media_role: str) -> str:
    role = sanitize_text(media_role)
    if role in INSTALLATION_MEDIA_ROLES:
        return "installation"
    if role in DIMENSION_MEDIA_ROLES:
        return "dimensions"
    if role in ACCESSORY_MEDIA_ROLES:
        return "accessories"
    return ""


def _normalize_accessory_fact_type(text: str) -> tuple[str, str]:
    if _contains_any(text, ACCESSORY_AVAILABILITY_TERMS):
        return "accessory_availability", "accessory_availability_terms"
    if _contains_any(text, ACCESSORY_USAGE_TERMS):
        return "accessory_usage", "accessory_usage_terms"
    return "accessories", "accessory_list_terms"


def _normalize_installation_fact_type(text: str) -> tuple[str, str]:
    if _contains_any(text, STRUCTURE_FUNCTION_TERMS):
        return "structure_function", "structure_function_terms"
    if _contains_any(text, ACCESSORY_USAGE_TERMS):
        return "accessory_usage", "accessory_usage_terms"
    return "installation", "installation_terms"


def _normalize_material_fact_type(text: str) -> tuple[str, str]:
    if _contains_any(text, CERTIFICATION_TERMS):
        return "certification_report", "certification_terms"
    if _contains_any(text, MATERIAL_SAFETY_TERMS):
        return "material_safety", "material_safety_terms"
    return "material", "material_terms"


def _normalize_aftersales_fact_type(text: str) -> tuple[str, str]:
    if _contains_any(text, RETURN_PICKUP_TERMS):
        return "return_pickup", "return_pickup_terms"
    if _contains_any(text, REFUND_TERMS):
        return "refund_policy", "refund_terms"
    if _contains_any(text, REPLACEMENT_TERMS):
        return "replacement_policy", "replacement_terms"
    return "aftersales_policy", "aftersales_terms"


def _normalize_promotion_fact_type(text: str) -> tuple[str, str]:
    if _contains_any(text, GIFT_TERMS):
        return "gift_policy", "gift_terms"
    if _contains_any(text, PRICE_NEGOTIATION_TERMS):
        return "price_negotiation", "price_negotiation_terms"
    return "promotion_policy", "promotion_terms"


def normalize_pgvector_fact_type_metadata(row: dict[str, Any]) -> FactTypeNormalization:
    source_type = sanitize_text(row.get("source_type"))
    original = sanitize_text(row.get("query_fact_type") or row.get("fact_type"))
    evidence_role = sanitize_text(row.get("evidence_role"))
    media_role = sanitize_text(row.get("media_role"))
    haystack = _text(
        row.get("chunk_text"),
        row.get("product_title"),
        row.get("title"),
        media_role,
        source_type,
    )
    normalized = CANONICAL_FACT_TYPES.get(original, original)
    reason = "canonical"

    if source_type == "media_asset":
        media_normalized = _media_fact_type(media_role)
        if media_normalized:
            normalized = media_normalized
            reason = f"media_role:{media_role}"
        normalized_role = "media_reference"
    elif source_type in {"generic_rule", "generic_rules", "response_templates", "kbqa", "faq"}:
        normalized = CANONICAL_FACT_TYPES.get(original, original)
        normalized_role = evidence_role
        reason = "canonical"
    else:
        if normalized == "accessories":
            normalized, reason = _normalize_accessory_fact_type(haystack)
        elif normalized == "installation":
            normalized, reason = _normalize_installation_fact_type(haystack)
        elif normalized == "material":
            normalized, reason = _normalize_material_fact_type(haystack)
        elif normalized in {"aftersales", "aftersales_policy"}:
            normalized, reason = _normalize_aftersales_fact_type(haystack)
        elif normalized == "promotion_policy":
            normalized, reason = _normalize_promotion_fact_type(haystack)
        normalized_role = normalized or evidence_role

    high_risk_blocked = False
    if original and is_high_risk_fact_type(original) and normalized != original:
        normalized = original
        normalized_role = evidence_role or original
        reason = "high_risk_original_kept"
        high_risk_blocked = True
    if normalized in HIGH_RISK_NORMALIZATION_TARGETS and original not in {normalized, ""}:
        normalized = original
        normalized_role = evidence_role or original
        reason = "high_risk_target_blocked"
        high_risk_blocked = True

    return FactTypeNormalization(
        original_query_fact_type=original,
        normalized_query_fact_type=normalized,
        original_evidence_role=evidence_role,
        normalized_evidence_role=normalized_role,
        reason=reason,
        high_risk_blocked=high_risk_blocked,
    )
