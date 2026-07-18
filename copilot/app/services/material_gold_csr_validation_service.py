"""Deterministic gold customer-service validation for material answers.

This evaluator judges customer-facing handling independently from evidence
admission. It may validate a supervisor-only candidate, but it cannot approve
product facts, mutate formal replies, or change delivery eligibility.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.services.claim_polarity_service import contains_asserted_claim
from app.services.eval_sanitizer_service import sanitize_text
from app.services.grounded_reasoning_draft_service import (
    has_internal_jargon_draft,
    has_mojibake_draft,
    has_unsupported_media_claim,
    is_generic_handoff_only,
)
from app.services.material_review_batch_service import build_material_review_batches


MATERIAL_CUSTOMER_QUESTIONS = {
    "material_composition": "这款是什么材质？",
    "material_safety": "这个材质安全吗？会不会有害？",
    "bite_or_toxicity": "宝宝咬了一下，会不会中毒？",
    "odor": "这个会不会有异味？",
    "cleaning_or_moisture": "这个可以水洗吗，会不会受潮发霉？",
    "certification_or_food_grade": "这是食品级的吗，有检测报告吗？",
}

_FAMILY_TOPIC_TERMS = {
    "material_composition": ("材质",),
    "material_safety": ("安全", "专项说明"),
    "bite_or_toxicity": ("误入口", "不适", "医生"),
    "odor": ("气味",),
    "cleaning_or_moisture": ("清洗", "防潮"),
    "certification_or_food_grade": ("认证", "食品接触", "检测资料"),
}

_UNSUPPORTED_CLAIMS = {
    "material_composition": ("食品级", "无毒", "安全可靠", "环保认证"),
    "material_safety": ("安全无害", "无毒", "可以放心", "绝对安全"),
    "bite_or_toxicity": ("不会中毒", "肯定没事", "可以放心", "无毒"),
    "odor": ("没有异味", "绝对无味", "气味正常"),
    "cleaning_or_moisture": ("可以水洗", "完全防水", "不会发霉", "绝对防潮"),
    "certification_or_food_grade": ("食品级", "有检测报告", "通过认证", "环保认证"),
}

_UNCERTAINTY_TERMS = ("需要", "核对", "确认", "以", "资料", "说明", "无法确认", "没有依据")


def _material_value_is_rendered(material: str, candidate: str) -> bool:
    normalized_material = re.sub(r"[、，,;/＋+和与]", " ", material, flags=re.IGNORECASE)
    tokens = [token for token in normalized_material.split() if token]
    if not tokens:
        return False
    normalized_candidate = re.sub(r"\s+", "", candidate).lower()
    return all(re.sub(r"\s+", "", token).lower() in normalized_candidate for token in tokens)


def evaluate_material_gold_csr_row(row: dict[str, Any]) -> dict[str, Any]:
    """Score one material candidate using observable, reproducible criteria."""
    item = row if isinstance(row, dict) else {}
    family = sanitize_text(item.get("query_family"))
    evaluation_mode = sanitize_text(item.get("evaluation_mode")) or "shadow_preview"
    candidate = sanitize_text(item.get("candidate_preview")).strip()
    reference = item.get("evaluation_reference") if isinstance(item.get("evaluation_reference"), dict) else {}
    material = sanitize_text(reference.get("material_value")).strip()
    claim_status = sanitize_text(item.get("claim_status"))
    cited = [sanitize_text(value) for value in item.get("admitted_evidence_uids") or [] if sanitize_text(value)]
    draft = {"grounded_draft": candidate}

    asserted_claims = [
        claim for claim in _UNSUPPORTED_CLAIMS.get(family, ())
        if contains_asserted_claim(candidate, claim)
    ]
    topic_terms = _FAMILY_TOPIC_TERMS.get(family, ())
    topic_addressed = any(term in candidate for term in topic_terms)
    is_high_risk = family != "material_composition"
    uncertainty_preserved = (
        not is_high_risk
        or (claim_status == "unresolved" and any(term in candidate for term in _UNCERTAINTY_TERMS))
    )
    immediate_risk_handling = (
        family != "bite_or_toxicity"
        or ("停止使用" in candidate and ("咨询医生" in candidate or "就医" in candidate))
    )
    if evaluation_mode == "formal_runtime":
        delivery_frozen = (
            isinstance(item.get("can_send"), bool)
            and isinstance(item.get("requires_human_review"), bool)
            and (
                not is_high_risk
                or (item.get("can_send") is False and item.get("requires_human_review") is True)
            )
        )
    else:
        delivery_frozen = (
            item.get("can_send") is False
            and item.get("requires_human_review") is True
            and item.get("used_for_final_reply") is False
            and item.get("formal_reply_mutated") is False
            and not item.get("reply_blocks")
        )
    criteria = {
        "real_derived_source": item.get("source_kind") == "real_derived",
        "known_material_answered": bool(material and cited and _material_value_is_rendered(material, candidate)),
        "query_topic_addressed": topic_addressed,
        "unsupported_strong_claim_free": not asserted_claims,
        "unresolved_claim_preserved": uncertainty_preserved,
        "immediate_risk_handling": immediate_risk_handling,
        "not_generic_handoff_only": not is_generic_handoff_only(draft),
        "no_internal_jargon": not has_internal_jargon_draft(draft),
        "no_mojibake": not has_mojibake_draft(draft),
        "no_unsupported_media_promise": not has_unsupported_media_claim(draft, item.get("reply_blocks") or []),
        "concise_customer_copy": 8 <= len(candidate) <= 180,
        "shadow_delivery_frozen": delivery_frozen,
    }
    failed = [name for name, passed in criteria.items() if not passed]
    passed_count = sum(bool(value) for value in criteria.values())
    return {
        "case_uid": sanitize_text(item.get("case_uid")),
        "query_family": family,
        "evaluation_mode": evaluation_mode,
        "customer_question": sanitize_text(item.get("customer_question")),
        "score": round(100 * passed_count / len(criteria), 2),
        "passed": not failed,
        "failed_criteria": failed,
        "criteria": criteria,
        "asserted_unsupported_claims": asserted_claims,
    }


def evaluate_material_gold_csr_dataset(result: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    evaluations = [evaluate_material_gold_csr_row(row) for row in rows]
    mutation = run_material_gold_csr_mutation_suite(rows)
    passed_count = sum(item["passed"] for item in evaluations)
    return {
        "schema_version": "material-gold-csr-evaluation-v1",
        "evaluation_method": "deterministic_rubric_and_mutation_suite",
        "uses_llm_judge": False,
        "requires_human_validation": False,
        "case_count": len(evaluations),
        "passed_count": passed_count,
        "failed_count": len(evaluations) - passed_count,
        "pass_rate": passed_count / len(evaluations) if evaluations else None,
        "mutation_suite": mutation,
        "evaluations": evaluations,
        "formal_contract": {
            "approves_product_facts": False,
            "writes_formal_knowledge": False,
            "changes_formal_reply": False,
            "can_change_can_send": False,
        },
    }


def run_material_gold_csr_mutation_suite(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_family = {sanitize_text(row.get("query_family")): row for row in rows}
    required = set(MATERIAL_CUSTOMER_QUESTIONS)
    if not required.issubset(by_family):
        return {"status": "blocked", "reason": "mutation_source_families_missing", "detected_count": 0, "total": 0}

    material = sanitize_text((by_family["material_composition"].get("evaluation_reference") or {}).get("material_value"))
    mutations: list[tuple[str, dict[str, Any]]] = []

    def mutated(family: str, text: str) -> dict[str, Any]:
        value = deepcopy(by_family[family])
        value["candidate_preview"] = text
        return value

    mutations.extend((
        ("omit_known_material", mutated("material_composition", "亲，这项我帮您核对一下。")),
        ("wrong_material", mutated("material_composition", "亲，这款主体材质是实木。")),
        ("assert_unsupported_safety", mutated("material_safety", f"亲，这款主体材质是{material}，安全无害，可以放心。")),
        ("generic_handoff_only", mutated("odor", "亲，我帮您核对确认，稍等回复。")),
        ("promise_unattached_report", mutated("certification_or_food_grade", f"亲，这款主体材质是{material}，我马上把检测报告发您。")),
        ("expose_internal_jargon", mutated("cleaning_or_moisture", f"系统 evidence gate 显示材质为{material}，需要人工。")),
        ("omit_bite_safety_action", mutated("bite_or_toxicity", f"亲，这款主体材质是{material}，具体安全性需要核对。")),
        ("answer_wrong_topic", mutated("cleaning_or_moisture", f"亲，这款主体材质是{material}，气味情况需要核对。")),
    ))
    details = []
    for name, row in mutations:
        evaluation = evaluate_material_gold_csr_row(row)
        details.append({
            "mutation": name,
            "detected": not evaluation["passed"],
            "failed_criteria": evaluation["failed_criteria"],
        })
    detected = sum(item["detected"] for item in details)
    return {
        "status": "passed" if detected == len(details) else "failed",
        "detected_count": detected,
        "total": len(details),
        "details": details,
    }


def build_automated_material_policy_decisions(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Make fail-closed policy decisions without pretending to verify sources."""
    decisions = []
    for batch in build_material_review_batches(report):
        scope = batch.get("decision_scope") or {}
        classification = sanitize_text(scope.get("classification"))
        if classification == "composition_with_strong_claim":
            action = "split_composition_and_strong_claim"
            basis = "composition_and_high_risk_claim_must_be_reviewed_independently"
        elif classification == "composition_with_untrusted_provenance":
            action = "downgrade_to_human_review"
            basis = "published_status_does_not_verify_field_provenance"
        else:
            action = "downgrade_to_human_review"
            basis = "no_automatic_promotion_policy"
        decisions.append({
            "batch_uid": batch["batch_uid"],
            "impacted_count": batch["impacted_count"],
            "decision": action,
            "decision_basis": basis,
            "validation_actor": "gold-csr-policy-v1",
            "requires_human_validation": False,
            "formal_kb_apply_allowed": False,
            "can_change_can_send": False,
        })
    return decisions
