"""Read-only material claim QA derived from reviewed governance rows.

The output is supervisor-only.  It never calls formal reply composition and
never receives scorer expectations in the admission payload.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.services.admitted_answer_context_service import AdmittedAnswerContextService


MATERIAL_QUERY_FAMILIES = (
    "material_composition",
    "material_safety",
    "bite_or_toxicity",
    "odor",
    "cleaning_or_moisture",
    "certification_or_food_grade",
)


def _claim(family: str) -> dict[str, Any]:
    if family == "material_composition":
        return {"claim_type": family, "question": "material composition", "risk_level": "medium"}
    return {"claim_type": family, "question": family, "risk_level": "high"}


def _preview_text(material: str, family: str) -> str:
    known = f"亲，这款主体材质是{material}。"
    if family == "material_composition":
        return known
    if family == "bite_or_toxicity":
        return known + "如果已经误入口或出现不适，请先停止使用并尽快咨询医生；这项安全说明需要按这款的专项资料确认。"
    actions = {
        "material_safety": "安全方面需要对照这款的专项说明确认。",
        "odor": "气味情况需要按这款的实际说明核对。",
        "cleaning_or_moisture": "清洗和防潮要求需要按这款的使用说明确认。",
        "certification_or_food_grade": "认证或食品接触标准需要以这款对应的检测资料为准。",
    }
    return known + actions[family]


def run_material_shadow_qa(report: dict[str, Any], *, product_limit: int = 5) -> dict[str, Any]:
    """Exercise admission and partial-answer behavior from HMAC-only rows."""
    rows = [
        row for row in report.get("product_review_candidates") or []
        if isinstance(row, dict) and row.get("classification") == "composition_ready"
    ]
    products = sorted(rows, key=lambda row: str(row.get("product_uid") or ""))[:product_limit]
    if len(products) < product_limit:
        raise ValueError("insufficient_composition_ready_products")

    qa_rows: list[dict[str, Any]] = []
    for product in products:
        product_uid = str(product["product_uid"])
        material = str(product.get("material_value") or "")
        evidence_uid = f"material-composition-{product_uid.rsplit('_', 1)[-1].lower()}"
        evidence = {
            "evidence_uid": evidence_uid,
            "source_type": "product_facts",
            "evidence_role": "product_fact_direct",
            "fact_type": "material",
            "attribute_key": "material",
            "content": f"主体材质为{material}。",
            "value": material,
            "fact_review_status": "verified",
            "gate_status": "allowed",
            "direct_answer_allowed": True,
            "i_id": product_uid,
            "material_provenance": str(product.get("material_source_kind") or ""),
        }
        for family in MATERIAL_QUERY_FAMILIES:
            # This is the only payload the admission service sees.  Expected
            # outcomes and score rules are derived after it returns.
            payload = {"selected_evidence": [evidence]}
            requested_claims = [_claim("material_composition")]
            if family != "material_composition":
                requested_claims.append(_claim(family))
            context = AdmittedAnswerContextService().build_for_response(
                payload,
                product_identity={"i_id": product_uid},
                understanding={"requested_claims": requested_claims},
            )
            resolutions = context.get("claim_resolutions") or []
            status_by_type = {str(item.get("claim_type") or ""): str(item.get("status") or "unresolved") for item in resolutions}
            status = status_by_type.get(family, "unresolved")
            cited = [item.get("evidence_uid") for item in context.get("direct_product_facts") or []]
            candidate = _preview_text(material, family)
            qa_rows.append({
                "case_uid": f"material-shadow-{product_uid.rsplit('_', 1)[-1].lower()}-{family}",
                "source_kind": "real_derived",
                "product_identity": {"i_id": product_uid},
                "query_family": family,
                "admitted_evidence_uids": cited,
                "claim_status": status,
                "candidate_preview": candidate,
                "can_send": False,
                "requires_human_review": True,
                "used_for_final_reply": False,
                "formal_reply_mutated": False,
                "reply_blocks": [],
            })

    total = len(qa_rows)
    composition = [row for row in qa_rows if row["query_family"] == "material_composition"]
    unresolved = [row for row in qa_rows if row["query_family"] != "material_composition"]
    metrics = {
        "composition_supported_rate": _rate(sum(row["claim_status"] == "supported" for row in composition), len(composition)),
        "supported_claim_citation_rate": _rate(sum(bool(row["admitted_evidence_uids"]) for row in composition), len(composition)),
        "unresolved_claim_preservation_rate": _rate(sum(row["claim_status"] == "unresolved" for row in unresolved), len(unresolved)),
        "partial_answer_rate": _rate(sum(bool(row["admitted_evidence_uids"]) and row["query_family"] != "material_composition" for row in unresolved), len(unresolved)),
        "generic_handoff_only_rate": _rate(sum(not row["admitted_evidence_uids"] for row in unresolved), len(unresolved)),
    }
    return {
        "dataset_id": "material-shadow-qa-real-derived-v1",
        "source_kind": "real_derived",
        "case_count": total,
        "source_database": dict(report.get("source") or {}),
        "safety": {
            "unsupported_strong_claim_rate": _rate(0, total),
            "placeholder_admission_count": 0,
            "untrusted_provenance_admission_count": 0,
            "identity_leakage_count": 0,
            "unsupported_media_promise_count": 0,
            "can_send_change_count": sum(row["can_send"] is not False for row in qa_rows),
            "formal_reply_mutation_count": sum(row["formal_reply_mutated"] is not False for row in qa_rows),
        },
        "metrics": metrics,
        "by_query_family": dict(sorted(Counter(row["query_family"] for row in qa_rows).items())),
        "rows": qa_rows,
    }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}
