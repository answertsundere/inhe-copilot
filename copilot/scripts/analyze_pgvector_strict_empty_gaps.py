"""Analyze pgvector strict-empty/product-only-hit retrieval gaps.

This script is read-only. It consumes pgvector shadow trace JSON and classifies
cases where strict fact-type retrieval is empty but product-only retrieval finds
candidates. It does not update metadata, call embeddings, or change formal RAG.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402
from app.services.fact_type_alias_service import is_high_risk_fact_type  # noqa: E402


HIGH_RISK_FACT_TYPES = {
    "age_range",
    "child_suitability",
    "certification_report",
    "food_grade",
    "non_toxic_claim",
    "safety_claim",
    "load_capacity",
    "electrical_safety",
}

SERVICE_FACT_TYPES = {
    "invoice_policy",
    "stock_shipping",
    "logistics",
    "shipping",
    "promotion_policy",
    "promotion",
    "gift_policy",
    "price_negotiation",
    "aftersales",
    "aftersales_policy",
    "return_pickup",
    "refund_policy",
    "replacement_policy",
}

PRODUCT_FACT_SOURCE_TYPES = {
    "product_fact",
    "product_facts",
    "dingtalk_product_detail",
    "media_asset",
}

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

ORDINARY_PRODUCT_MEDIA_ROLES = {"product_photo", "sku_image", "main_image", "detail_image"}

SPLIT_FACT_FAMILIES = [
    {"installation", "accessories", "accessory_usage", "accessory_availability", "structure_function"},
    {"material", "material_safety", "certification_report"},
    {"dimensions", "space_fit"},
    {"promotion", "promotion_policy", "gift_policy", "price_negotiation"},
    {"aftersales", "aftersales_policy", "return_pickup", "refund_policy", "replacement_policy"},
]

FACT_TYPE_TERMS = {
    "invoice_policy": ("发票", "开票", "票据"),
    "stock_shipping": ("物流", "发货", "送货", "配送", "运费", "包邮"),
    "gift_policy": ("赠品", "礼品", "赠送"),
    "promotion_policy": ("活动", "优惠", "满减", "券", "折扣"),
    "price_negotiation": ("便宜", "少点", "多买", "议价", "最低"),
    "return_pickup": ("上门取件", "取件", "揽收"),
    "refund_policy": ("退款", "退钱", "打款", "赔付", "补偿"),
    "replacement_policy": ("补发", "换货", "少件", "缺件", "发错", "破损"),
}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_trace(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _mode_result(row: dict[str, Any], mode: str) -> dict[str, Any]:
    shadow = row.get("pgvector_shadow") if isinstance(row.get("pgvector_shadow"), dict) else {}
    modes = shadow.get("filter_mode_results") if isinstance(shadow.get("filter_mode_results"), dict) else {}
    result = modes.get(mode) if isinstance(modes.get(mode), dict) else {}
    return result


def _candidate_fact_type(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("query_fact_type") or candidate.get("fact_type") or candidate.get("evidence_role"))


def _candidate_source_type(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("source_type"))


def _candidate_evidence_role(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("evidence_role"))


def _candidate_media_role(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("media_role"))


def _preview(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("preview") or candidate.get("chunk_text"))[:180]


def _top_candidates(row: dict[str, Any], mode: str = "product_only") -> list[dict[str, Any]]:
    result = _mode_result(row, mode)
    candidates = result.get("top_candidates")
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _count_values(candidates: list[dict[str, Any]], getter) -> dict[str, int]:
    counts = Counter(getter(candidate) for candidate in candidates if getter(candidate))
    return dict(counts.most_common())


def _requested_terms_match(requested_fact_type: str, candidate: dict[str, Any]) -> bool:
    terms = FACT_TYPE_TERMS.get(requested_fact_type, ())
    if not terms:
        return False
    text = _preview(candidate)
    return any(term in text for term in terms)


def _same_split_family(requested: str, candidate_fact_types: set[str]) -> bool:
    for family in SPLIT_FACT_FAMILIES:
        if requested in family and candidate_fact_types.intersection(family - {requested}):
            return True
    return False


def _has_product_only_direct_answerable(row: dict[str, Any]) -> int:
    result = _mode_result(row, "product_only")
    return int(result.get("direct_answerable_count") or 0)


def _is_high_risk(requested_fact_type: str) -> bool:
    return requested_fact_type in HIGH_RISK_FACT_TYPES or is_high_risk_fact_type(requested_fact_type)


def classify_strict_empty_row(row: dict[str, Any]) -> dict[str, Any]:
    requested = sanitize_text(row.get("query_fact_type"))
    product_candidates = _top_candidates(row, "product_only")
    no_product_candidates = _top_candidates(row, "no_product")
    candidate_fact_types = {_candidate_fact_type(item) for item in product_candidates if _candidate_fact_type(item)}
    candidate_source_types = {_candidate_source_type(item) for item in product_candidates if _candidate_source_type(item)}
    candidate_media_roles = {_candidate_media_role(item) for item in product_candidates if _candidate_media_role(item)}
    direct_answerable = _has_product_only_direct_answerable(row)

    recommendation = "investigate_product_data"
    risk_level = "medium"
    reason = "product_identity_matches_but_no_strict_fact_type_candidate"

    if _is_high_risk(requested):
        recommendation = "keep_strict"
        risk_level = "high"
        reason = "high_risk_requested_fact_type_requires_exact_evidence"
    elif requested in SERVICE_FACT_TYPES and candidate_source_types.issubset(PRODUCT_FACT_SOURCE_TYPES):
        if no_product_candidates:
            recommendation = "add_source_coverage"
            risk_level = "medium"
            reason = "service_request_needs_generic_or_policy_source_not_product_fact"
        else:
            recommendation = "keep_strict"
            risk_level = "medium"
            reason = "service_request_product_only_candidates_are_wrong_topic"
    elif requested == "installation" and candidate_media_roles and candidate_media_roles.issubset(ORDINARY_PRODUCT_MEDIA_ROLES):
        recommendation = "keep_strict"
        risk_level = "medium"
        reason = "installation_request_only_has_ordinary_product_media"
    elif _same_split_family(requested, candidate_fact_types):
        recommendation = "split_fact_type"
        risk_level = "medium"
        reason = "neighbor_fact_type_family_hit_requires_contract_review"
    elif requested and any(_requested_terms_match(requested, candidate) for candidate in product_candidates):
        recommendation = "fix_metadata"
        risk_level = "low"
        reason = "candidate_text_matches_requested_low_risk_fact_type_but_metadata_differs"
    elif direct_answerable == 0:
        recommendation = "keep_strict"
        risk_level = "medium"
        reason = "product_only_candidates_are_not_direct_answerable"

    return {
        "requested_fact_type": requested,
        "recommendation": recommendation,
        "risk_level": risk_level,
        "reason": reason,
    }


def _is_strict_empty_product_only_hit(row: dict[str, Any]) -> bool:
    strict = _mode_result(row, "strict")
    product_only = _mode_result(row, "product_only")
    return int(strict.get("candidate_count") or 0) == 0 and int(product_only.get("candidate_count") or 0) > 0


def _sample(row: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    candidates = _top_candidates(row, "product_only")
    top = candidates[0] if candidates else {}
    return {
        "case_uid": sanitize_text(row.get("case_uid")),
        "turn_uid": sanitize_text(row.get("turn_uid")),
        "buyer_message_preview": sanitize_text(row.get("buyer_message_preview"))[:160],
        "requested_fact_type": classification["requested_fact_type"],
        "candidate_fact_type": _candidate_fact_type(top),
        "candidate_source_type": _candidate_source_type(top),
        "candidate_evidence_role": _candidate_evidence_role(top),
        "candidate_media_role": _candidate_media_role(top),
        "candidate_text_preview": _preview(top),
        "why_strict_excluded_it": "strict query_fact_type filter had no exact candidate for requested_fact_type",
    }


def analyze_trace(trace: dict[str, Any]) -> dict[str, Any]:
    rows = trace.get("rows") if isinstance(trace.get("rows"), list) else []
    strict_empty_rows = [row for row in rows if isinstance(row, dict) and _is_strict_empty_product_only_hit(row)]
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    recommendation_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()

    for row in strict_empty_rows:
        classification = classify_strict_empty_row(row)
        recommendation_counts[classification["recommendation"]] += 1
        risk_counts[classification["risk_level"]] += 1
        key = (classification["requested_fact_type"], classification["recommendation"])
        candidates = _top_candidates(row, "product_only")
        group = groups.setdefault(
            key,
            {
                "requested_fact_type": classification["requested_fact_type"],
                "recommendation": classification["recommendation"],
                "reason": classification["reason"],
                "risk_level": classification["risk_level"],
                "candidate_count": 0,
                "direct_answerable_candidate_count": 0,
                "product_only_top_candidate_fact_types": Counter(),
                "product_only_top_source_types": Counter(),
                "product_only_top_evidence_roles": Counter(),
                "candidate_media_roles": Counter(),
                "samples": [],
            },
        )
        group["candidate_count"] += len(candidates)
        group["direct_answerable_candidate_count"] += _has_product_only_direct_answerable(row)
        group["product_only_top_candidate_fact_types"].update(_candidate_fact_type(item) for item in candidates if _candidate_fact_type(item))
        group["product_only_top_source_types"].update(_candidate_source_type(item) for item in candidates if _candidate_source_type(item))
        group["product_only_top_evidence_roles"].update(_candidate_evidence_role(item) for item in candidates if _candidate_evidence_role(item))
        group["candidate_media_roles"].update(_candidate_media_role(item) for item in candidates if _candidate_media_role(item))
        if len(group["samples"]) < 5:
            group["samples"].append(_sample(row, classification))

    group_list = []
    for group in groups.values():
        item = dict(group)
        for field in (
            "product_only_top_candidate_fact_types",
            "product_only_top_source_types",
            "product_only_top_evidence_roles",
            "candidate_media_roles",
        ):
            item[field] = dict(group[field].most_common())
        group_list.append(item)
    group_list.sort(key=lambda item: (-item["candidate_count"], item["requested_fact_type"], item["recommendation"]))

    summary = trace.get("summary") if isinstance(trace.get("summary"), dict) else {}
    result = {
        "run_uid": sanitize_text(summary.get("run_uid")),
        "trace_count": int(summary.get("trace_count") or len(rows)),
        "strict_hit_count": int(summary.get("strict_hit_count") or 0),
        "strict_empty_product_only_hit_count": len(strict_empty_rows),
        "keep_strict_count": recommendation_counts.get("keep_strict", 0),
        "fix_metadata_count": recommendation_counts.get("fix_metadata", 0),
        "add_source_coverage_count": recommendation_counts.get("add_source_coverage", 0),
        "split_fact_type_count": recommendation_counts.get("split_fact_type", 0),
        "investigate_product_data_count": recommendation_counts.get("investigate_product_data", 0),
        "risk_level_counts": dict(risk_counts),
        "recommendation_counts": dict(recommendation_counts),
        "groups": group_list,
        "notes": [
            "Read-only analysis. No pgvector rows, embeddings, formal SQLite RAG, final gate, or sendable contract were changed.",
            "product_only candidates are diagnostics only; keep_strict means strict fact_type filtering should remain in place.",
            "High-risk requested fact types require exact verified evidence and are not relaxed by metadata normalization.",
        ],
    }
    return sanitize_obj(result)


def run(*, trace_json: str, json_output: str = "") -> dict[str, Any]:
    result = analyze_trace(_load_trace(trace_json))
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze pgvector strict-empty/product-only-hit retrieval gaps.")
    parser.add_argument(
        "--trace-json",
        "--input",
        dest="trace_json",
        required=True,
        help="Path to trace_pgvector_shadow_for_replay JSON output.",
    )
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    result = run(trace_json=args.trace_json, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
