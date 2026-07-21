"""Summarize the read-only formal-evidence funnel captured in a Tier D report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ALLOWED_BREAKPOINTS = frozenset({
    "context_missing",
    "product_identity_missing",
    "source_coverage_gap",
    "evidence_role_ineligible",
    "review_status_ineligible",
    "identity_mismatch",
    "fact_type_mismatch",
    "placeholder_value",
    "conflicting_evidence",
    "convergence_disabled",
    "graph_selection_gap",
    "selected_successfully",
})

ROLE_GAP_CATEGORIES = frozenset({
    "correctly_rejected_non_fact",
    "metadata_contract_missing",
    "source_review_missing",
    "identity_scope_missing",
    "fact_type_or_attribute_mismatch",
    "placeholder_or_conflict",
    "unsafe_promotion_candidate",
})

SOURCE_GAP_CATEGORIES = frozenset({
    "sidecar_context_missing",
    "product_identity_unresolved",
    "product_context_pack_empty",
    "formal_product_field_missing",
    "reviewed_faq_missing",
    "reviewed_manual_missing",
    "media_description_missing",
    "order_or_live_tool_required",
    "policy_source_missing",
    "unsupported_claim_requires_handoff",
    "evaluation_fixture_gap",
})

GAP_OWNERS = {
    "correctly_rejected_non_fact": "evidence_admission_contract",
    "metadata_contract_missing": "product_context_pack_compaction",
    "source_review_missing": "knowledge_review_workflow",
    "identity_scope_missing": "product_identity_resolution",
    "fact_type_or_attribute_mismatch": "fact_type_and_attribute_contract",
    "placeholder_or_conflict": "evidence_admission_contract",
    "unsafe_promotion_candidate": "supervisor_knowledge_governance",
    "sidecar_context_missing": "sidecar_context_owner",
    "product_identity_unresolved": "product_identity_resolution",
    "product_context_pack_empty": "product_context_pack",
    "formal_product_field_missing": "product_knowledge_governance",
    "reviewed_faq_missing": "faq_review_workflow",
    "reviewed_manual_missing": "manual_review_workflow",
    "media_description_missing": "approved_media_governance",
    "order_or_live_tool_required": "order_and_live_tool_integration",
    "policy_source_missing": "policy_knowledge_governance",
    "unsupported_claim_requires_handoff": "safety_and_handoff_contract",
    "evaluation_fixture_gap": "tier_d_dataset_owner",
}


def _normalize_breakpoint(funnel: dict[str, Any]) -> str:
    raw = str(funnel.get("earliest_breakpoint") or "")
    if raw in ALLOWED_BREAKPOINTS:
        return raw
    counts = funnel.get("counts") if isinstance(funnel.get("counts"), dict) else {}
    aliases = {
        "review_or_direct_evidence_missing": "review_status_ineligible",
        "identity_missing_or_mismatch": "identity_mismatch",
        "fact_type_missing_or_mismatch": "fact_type_mismatch",
        "selected_evidence_dropped": "graph_selection_gap",
    }
    if raw in aliases:
        return aliases[raw]
    if raw == "no_product_context":
        return (
            "source_coverage_gap"
            if int(counts.get("candidate_count") or 0) == 0
            else "evidence_role_ineligible"
        )
    if raw == "formal_admission_rejected":
        reasons = funnel.get("rejected_by_reason") if isinstance(funnel.get("rejected_by_reason"), dict) else {}
        if int(reasons.get("placeholder_fact") or 0):
            return "placeholder_value"
        if int(reasons.get("conflicting_evidence") or 0):
            return "conflicting_evidence"
        return "evidence_role_ineligible"
    if raw in {"none", ""} and int(counts.get("formal_selected_count") or 0) > 0:
        return "selected_successfully"
    raise ValueError(f"evidence_funnel_breakpoint_invalid:{raw or 'missing'}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("tier_d_report_not_object")
    return value


def _diagnostic_uid(result: dict[str, Any], trial: int, turn_number: int) -> str:
    seed = "|".join((str(result.get("scenario_uid") or ""), str(trial), str(turn_number)))
    return "gap-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _classify_role_gap(funnel: dict[str, Any]) -> tuple[str, str]:
    records = [item for item in funnel.get("records") or [] if isinstance(item, dict)]
    reasons = {str(item.get("rejection_reason") or "") for item in records}
    if reasons.intersection({"placeholder_fact", "placeholder_evidence", "conflicting_evidence"}):
        return "placeholder_or_conflict", "candidate_failed_placeholder_or_conflict_contract"
    if reasons.intersection({"fact_type_incompatible", "attribute_key_missing"}):
        return "fact_type_or_attribute_mismatch", "candidate_failed_fact_or_attribute_compatibility"
    if reasons.intersection({"review_status_missing", "review_status_not_allowed"}):
        return "source_review_missing", "candidate_lacked_allowed_review_state"
    if reasons.intersection({
        "resolved_product_identity_missing",
        "product_identity_missing",
        "product_identity_namespace_missing",
        "product_identity_mismatch",
    }):
        return "identity_scope_missing", "candidate_lacked_matching_identity_scope"

    protocol_compacted = any(
        str(item.get("rejection_reason") or "") == "evidence_role_not_direct"
        and "product_facts" in (item.get("source_types") or [])
        and any("product_structured_facts" in str(source) for source in item.get("source_containers") or [])
        for item in records
    )
    if protocol_compacted:
        return "metadata_contract_missing", "explicit_structured_protocol_metadata_was_not_preserved"

    high_risk_types = {
        "load_capacity", "material_safety", "non_toxic", "food_grade", "certification",
        "child_safety", "anti_tip", "wall_mounting",
    }
    if any(str(item.get("fact_type") or "") in high_risk_types for item in records):
        return "unsafe_promotion_candidate", "high_risk_candidate_was_not_directly_admissible"
    return "correctly_rejected_non_fact", "only_action_media_or_reference_candidates_observed"


def _classify_source_gap(result: dict[str, Any]) -> tuple[str, str]:
    domain = str(result.get("primary_domain") or "")
    if domain == "context_insufficient":
        return "sidecar_context_missing", "evaluation_contract_declares_missing_context"
    if domain in {"order_logistics_service_action", "aftersales_verification"}:
        return "order_or_live_tool_required", "domain_requires_order_or_live_state_verification"
    if domain == "known_fact_high_risk_remainder":
        return "unsupported_claim_requires_handoff", "high_risk_remainder_has_no_admitted_fact_source"
    if domain == "product_fact_direct":
        return "formal_product_field_missing", "direct_product_fact_domain_has_no_candidate"
    if domain == "installation_accessory":
        return "reviewed_manual_missing", "installation_domain_has_no_reviewed_source_candidate"
    return "evaluation_fixture_gap", "source_gap_cannot_be_attributed_more_narrowly"


def analyze_report(report: dict[str, Any]) -> dict[str, Any]:
    gap_counts: Counter[str] = Counter()
    breakpoint_counts: Counter[str] = Counter()
    funnel_turn_count = 0
    turn_count = 0
    selected_evidence_turn_count = 0
    turn_diagnostics: list[dict[str, Any]] = []
    detailed_gap_counts: Counter[str] = Counter()
    detailed_gap_representatives: dict[str, list[dict[str, Any]]] = {}
    for result in report.get("results") or []:
        if not isinstance(result, dict):
            continue
        for turn_index, turn in enumerate(result.get("turns") or [], start=1):
            if not isinstance(turn, dict):
                continue
            turn_count += 1
            observation = turn.get("observation") if isinstance(turn.get("observation"), dict) else {}
            if int(observation.get("selected_evidence_count") or 0) > 0:
                selected_evidence_turn_count += 1
            shadow = observation.get("evidence_action_shadow") if isinstance(observation.get("evidence_action_shadow"), dict) else {}
            funnel = shadow.get("evidence_funnel") if isinstance(shadow.get("evidence_funnel"), dict) else {}
            if not funnel:
                continue
            breakpoint = _normalize_breakpoint(funnel)
            gap = breakpoint
            counts = funnel.get("counts") if isinstance(funnel.get("counts"), dict) else {}
            funnel_turn_count += 1
            gap_counts[gap] += 1
            breakpoint_counts[breakpoint] += 1
            if breakpoint == "evidence_role_ineligible":
                detailed_gap, detailed_reason = _classify_role_gap(funnel)
                if detailed_gap not in ROLE_GAP_CATEGORIES:
                    raise ValueError(f"role_gap_category_invalid:{detailed_gap}")
            elif breakpoint == "source_coverage_gap":
                detailed_gap, detailed_reason = _classify_source_gap(result)
                if detailed_gap not in SOURCE_GAP_CATEGORIES:
                    raise ValueError(f"source_gap_category_invalid:{detailed_gap}")
            else:
                detailed_gap, detailed_reason = "", ""
            if detailed_gap:
                detailed_gap_counts[detailed_gap] += 1
                representatives = detailed_gap_representatives.setdefault(detailed_gap, [])
                if len(representatives) < 3:
                    representatives.append({
                        "diagnostic_uid": _diagnostic_uid(
                            result,
                            int(result.get("trial") or 0),
                            int(turn.get("turn_number") or turn_index),
                        ),
                        "reason": detailed_reason,
                        "owner": GAP_OWNERS[detailed_gap],
                    })
            turn_diagnostics.append({
                "diagnostic_uid": _diagnostic_uid(
                    result,
                    int(result.get("trial") or 0),
                    int(turn.get("turn_number") or turn_index),
                ),
                "trial": int(result.get("trial") or 0),
                "turn_number": int(turn.get("turn_number") or turn_index),
                "earliest_breakpoint": breakpoint,
                "detailed_gap_classification": detailed_gap,
                "detailed_gap_reason": detailed_reason,
                "owner": GAP_OWNERS.get(detailed_gap, ""),
                "counts": {
                    key: int(counts.get(key) or 0)
                    for key in (
                        "product_context_candidate_count",
                        "direct_fact_candidate_count",
                        "direct_reviewed_count",
                        "identity_matched_count",
                        "fact_type_compatible_count",
                        "non_placeholder_count",
                        "non_conflicting_count",
                        "formally_admissible_count",
                        "formal_selected_count",
                    )
                },
            })

    diagnostics_available = funnel_turn_count > 0
    return {
        "schema_version": "tier-d-formal-evidence-funnel-analysis-v3",
        "source_report_schema_version": str(report.get("schema_version") or ""),
        "turn_count": turn_count,
        "selected_evidence_turn_count": selected_evidence_turn_count,
        "evidence_funnel_turn_count": funnel_turn_count,
        "missing_funnel_turn_count": turn_count - funnel_turn_count,
        "evidence_funnel_status": "available" if diagnostics_available else "not_captured_in_source_report",
        "gap_classification_counts": dict(sorted(gap_counts.items())),
        "earliest_breakpoint_counts": dict(sorted(breakpoint_counts.items())),
        "detailed_gap_classification_counts": dict(sorted(detailed_gap_counts.items())),
        "detailed_gap_representatives": dict(sorted(detailed_gap_representatives.items())),
        "turn_diagnostics": turn_diagnostics,
        "interpretation": (
            "turn_level_funnel_available"
            if diagnostics_available
            else "selected_evidence_zero_cannot_distinguish_source_gap_from_disabled_or_dropped_convergence"
        ),
        "scoring_contract_changed": False,
        "formal_agent_changed": False,
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.json_output)
    try:
        raw = input_path.read_bytes()
        report = json.loads(raw.decode("utf-8"))
        if not isinstance(report, dict):
            raise ValueError("tier_d_report_not_object")
        result = analyze_report(report)
        result["source_report_sha256"] = hashlib.sha256(raw).hexdigest()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
