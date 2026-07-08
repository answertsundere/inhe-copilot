"""Diagnose source coverage gaps behind pgvector strict-empty groups.

Read-only diagnostic for shadow pgvector work. It inspects strict-empty analysis
JSON and local SQLite service/FAQ/media/product sources, then recommends the
source type that should cover the gap. It does not sync pgvector, generate
embeddings, or write formal knowledge.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBQA  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402
from app.services.fact_type_service import infer_evidence_fact_type  # noqa: E402


SERVICE_FACT_TYPES = {
    "stock_shipping",
    "logistics",
    "shipping",
    "invoice_policy",
    "receipt",
    "billing",
    "promotion",
    "promotion_policy",
    "gift_policy",
    "price_negotiation",
    "aftersales",
    "aftersales_policy",
    "return_pickup",
    "refund_policy",
    "replacement_policy",
    "order_assistance",
    "sku_selection",
    "purchase_link",
}

MEDIA_FACT_TYPES = {
    "installation",
    "dimensions",
    "space_fit",
    "accessories",
    "accessory_usage",
    "accessory_availability",
}

PRODUCT_FIELD_FACT_TYPES = {
    "dimensions",
    "material",
    "load_capacity",
    "gross_weight",
    "accessories",
    "accessory_availability",
    "installation",
    "structure_function",
    "stability",
    "variant_compare",
    "space_fit",
}

GENERIC_FACT_ALIASES = {
    "logistics": {"stock_shipping"},
    "shipping": {"stock_shipping"},
    "receipt": {"invoice_policy"},
    "billing": {"invoice_policy"},
    "promotion": {"promotion_policy", "gift_policy", "price_negotiation"},
    "aftersales": {"aftersales_policy", "return_pickup", "refund_policy", "replacement_policy"},
    "replacement_policy": {"aftersales_policy"},
    "refund_policy": {"aftersales_policy"},
}

MEDIA_ROLE_FACT_TYPES = {
    "installation": {
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
    },
    "dimensions": {"size_chart", "size_chart_image", "size_image", "dimension_image"},
    "space_fit": {"size_chart", "size_chart_image", "size_image", "dimension_image"},
    "accessories": {"accessory_photo", "accessory_image", "parts_image", "parts_list"},
    "accessory_usage": {"accessory_photo", "accessory_image", "parts_image", "parts_list"},
    "accessory_availability": {"accessory_photo", "accessory_image", "parts_image", "parts_list"},
}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fact_aliases(fact_type: str) -> set[str]:
    clean = sanitize_text(fact_type)
    return {clean, *GENERIC_FACT_ALIASES.get(clean, set())}


def _count_generic_rules(db, fact_type: str) -> int:
    aliases = _fact_aliases(fact_type)
    return int(
        db.query(KBGenericServiceRule)
        .filter(KBGenericServiceRule.status == "active")
        .filter(KBGenericServiceRule.fact_type.in_(aliases))
        .count()
        or 0
    )


def _qa_fact_type(qa: KBQA) -> str:
    return infer_evidence_fact_type({
        "title": qa.question,
        "chunk_text": qa.answer,
        "source_type": qa.source_type or "faq",
        "category": qa.category_l2 or qa.category_l1 or "",
        "category_l3": qa.category_l3 or "",
        "issue_type": qa.issue_type or "",
    })


def _count_kbqa(db, fact_type: str) -> int:
    aliases = _fact_aliases(fact_type)
    rows = (
        db.query(KBQA)
        .filter(KBQA.status == "published", KBQA.auto_reply == True)  # noqa: E712
        .all()
    )
    return sum(1 for row in rows if _qa_fact_type(row) in aliases)


def _count_media(db, fact_type: str) -> int:
    roles = MEDIA_ROLE_FACT_TYPES.get(sanitize_text(fact_type), set())
    if not roles:
        return 0
    return int(
        db.query(KBMediaAsset)
        .filter(KBMediaAsset.status == "approved", KBMediaAsset.usable_for_agent == 1)
        .filter(KBMediaAsset.asset_type.in_(roles))
        .count()
        or 0
    )


def _count_product_fields(db, fact_type: str) -> int:
    fact = sanitize_text(fact_type)
    if fact not in PRODUCT_FIELD_FACT_TYPES:
        return 0
    rows = db.query(KBProduct).all()
    count = 0
    for product in rows:
        data = product.to_dict() if hasattr(product, "to_dict") else {}
        text = json.dumps(sanitize_obj(data), ensure_ascii=False)
        if fact in text:
            count += 1
    return count


def _recommended_source_type(
    *,
    fact_type: str,
    recommendation: str,
    existing_generic_rule_count: int,
    existing_kbqa_count: int,
    existing_media_count: int,
    existing_product_field_count: int,
) -> tuple[str, bool, str]:
    if recommendation == "keep_strict":
        return "keep_strict", False, "product_only_candidates_are_not_safe_for_requested_fact_type"
    if recommendation == "split_fact_type":
        return "manual_policy", False, "fact_type_boundary_needs_contract_review"
    if fact_type in SERVICE_FACT_TYPES:
        if existing_generic_rule_count:
            return "generic_rule", False, "existing_generic_service_rule_should_cover_shadow_service_action"
        if existing_kbqa_count:
            return "kbqa", False, "existing_kbqa_matches_service_fact_type"
        return "generic_rule", True, "low_risk_service_action_gap_can_use_generic_rule_draft"
    if fact_type in MEDIA_FACT_TYPES and existing_media_count:
        return "media_asset", False, "approved_role_matched_media_exists"
    if fact_type in PRODUCT_FIELD_FACT_TYPES:
        if existing_product_field_count:
            return "product_field", False, "product_field_coverage_exists_but_shadow_fact_type_filter_missed"
        return "product_field", False, "product_identity_matches_but_product_field_or_fact_is_missing"
    if existing_kbqa_count:
        return "kbqa", False, "existing_kbqa_matches_fact_type"
    return "manual_policy", False, "no_safe_source_coverage_found"


def _samples(group: dict[str, Any]) -> list[dict[str, Any]]:
    samples = group.get("samples") if isinstance(group.get("samples"), list) else []
    return [
        {
            "buyer_message_preview": sanitize_text(item.get("buyer_message_preview"))[:160],
            "requested_fact_type": sanitize_text(item.get("requested_fact_type")),
            "candidate_fact_type": sanitize_text(item.get("candidate_fact_type")),
            "candidate_source_type": sanitize_text(item.get("candidate_source_type")),
            "candidate_evidence_role": sanitize_text(item.get("candidate_evidence_role")),
            "candidate_text_preview": sanitize_text(item.get("candidate_text_preview"))[:180],
            "why_strict_excluded_it": sanitize_text(item.get("why_strict_excluded_it")),
        }
        for item in samples[:5]
        if isinstance(item, dict)
    ]


def diagnose(analysis: dict[str, Any], *, db) -> dict[str, Any]:
    groups = analysis.get("groups") if isinstance(analysis.get("groups"), list) else []
    results: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        fact_type = sanitize_text(group.get("requested_fact_type"))
        recommendation = sanitize_text(group.get("recommendation"))
        existing_generic = _count_generic_rules(db, fact_type)
        existing_kbqa = _count_kbqa(db, fact_type)
        existing_media = _count_media(db, fact_type)
        existing_product = _count_product_fields(db, fact_type)
        source_type, safe_to_generate, reason = _recommended_source_type(
            fact_type=fact_type,
            recommendation=recommendation,
            existing_generic_rule_count=existing_generic,
            existing_kbqa_count=existing_kbqa,
            existing_media_count=existing_media,
            existing_product_field_count=existing_product,
        )
        results.append({
            "requested_fact_type": fact_type,
            "strict_empty_group_recommendation": recommendation,
            "gap_count": int(len(group.get("samples") or [])),
            "candidate_count": int(group.get("candidate_count") or 0),
            "direct_answerable_candidate_count": int(group.get("direct_answerable_candidate_count") or 0),
            "existing_generic_rule_count": existing_generic,
            "existing_kbqa_count": existing_kbqa,
            "existing_media_count": existing_media,
            "existing_product_field_count": existing_product,
            "recommended_source_type": source_type,
            "safe_to_auto_generate_rule": bool(safe_to_generate),
            "reason": reason,
            "representative_samples": _samples(group),
        })
    by_source: dict[str, int] = {}
    by_fact_type: dict[str, int] = {}
    safe_generate_count = 0
    for item in results:
        by_source[item["recommended_source_type"]] = by_source.get(item["recommended_source_type"], 0) + 1
        by_fact_type[item["requested_fact_type"]] = by_fact_type.get(item["requested_fact_type"], 0) + 1
        if item["safe_to_auto_generate_rule"]:
            safe_generate_count += 1
    return sanitize_obj({
        "run_uid": sanitize_text(analysis.get("run_uid")),
        "strict_empty_product_only_hit_count": int(analysis.get("strict_empty_product_only_hit_count") or 0),
        "source_coverage_group_count": len(results),
        "safe_to_auto_generate_rule_count": safe_generate_count,
        "by_recommended_source_type": by_source,
        "by_requested_fact_type": by_fact_type,
        "items": results,
        "notes": [
            "Read-only diagnostic. It does not sync pgvector, generate embeddings, or write formal knowledge.",
            "generic_rule rows are service_action/fallback coverage only, not product facts.",
            "media_asset rows still require media role and delivery contract checks before any sendable reply.",
        ],
    })


def run(*, analysis_json: str, json_output: str = "", db_factory=SessionLocal) -> dict[str, Any]:
    db = db_factory()
    try:
        result = diagnose(_load_json(analysis_json), db=db)
    finally:
        db.close()
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose pgvector source coverage gaps from strict-empty analysis.")
    parser.add_argument("--analysis-json", "--input", dest="analysis_json", required=True)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(analysis_json=args.analysis_json, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
