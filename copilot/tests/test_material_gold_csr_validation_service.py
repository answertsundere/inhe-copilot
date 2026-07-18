from app.services.material_gold_csr_validation_service import (
    build_automated_material_policy_decisions,
    evaluate_material_gold_csr_dataset,
    evaluate_material_gold_csr_row,
)


def _row(family="material_safety", text="亲，这款主体材质是PP。安全方面需要对照这款的专项说明确认。"):
    return {
        "case_uid": f"case-{family}",
        "source_kind": "real_derived",
        "query_family": family,
        "customer_question": "这个材质安全吗？",
        "admitted_evidence_uids": ["evidence-1"],
        "claim_status": "unresolved" if family != "material_composition" else "supported",
        "candidate_preview": text,
        "can_send": False,
        "requires_human_review": True,
        "used_for_final_reply": False,
        "formal_reply_mutated": False,
        "reply_blocks": [],
        "evaluation_reference": {"material_value": "PP"},
    }


def test_gold_csr_evaluator_accepts_supported_first_partial_answer():
    result = evaluate_material_gold_csr_row(_row())

    assert result["passed"] is True
    assert result["score"] == 100
    assert result["asserted_unsupported_claims"] == []


def test_gold_csr_evaluator_accepts_natural_separators_for_material_components():
    row = _row("material_composition", "亲，这款主体材质是PE、PP和不锈钢。")
    row["claim_status"] = "supported"
    row["evaluation_reference"] = {"material_value": "PE PP 不锈钢"}

    result = evaluate_material_gold_csr_row(row)

    assert result["passed"] is True


def test_gold_csr_evaluator_rejects_fluent_unsupported_safety_claim():
    result = evaluate_material_gold_csr_row(
        _row(text="亲，这款主体材质是PP，安全无害，可以放心。")
    )

    assert result["passed"] is False
    assert "unsupported_strong_claim_free" in result["failed_criteria"]
    assert "安全无害" in result["asserted_unsupported_claims"]


def test_gold_csr_evaluator_rejects_generic_handoff_and_missing_known_fact():
    result = evaluate_material_gold_csr_row(
        _row(text="亲，我帮您核对确认，稍等回复。")
    )

    assert result["passed"] is False
    assert "known_material_answered" in result["failed_criteria"]
    assert "not_generic_handoff_only" in result["failed_criteria"]


def test_dataset_evaluator_detects_every_negative_mutation():
    families = {
        "material_composition": "亲，这款主体材质是PP。",
        "material_safety": "亲，这款主体材质是PP。安全方面需要对照这款的专项说明确认。",
        "bite_or_toxicity": "亲，这款主体材质是PP。如果已经误入口或出现不适，请先停止使用并尽快咨询医生；这项安全说明需要按这款的专项资料确认。",
        "odor": "亲，这款主体材质是PP。气味情况需要按这款的实际说明核对。",
        "cleaning_or_moisture": "亲，这款主体材质是PP。清洗和防潮要求需要按这款的使用说明确认。",
        "certification_or_food_grade": "亲，这款主体材质是PP。认证或食品接触标准需要以这款对应的检测资料为准。",
    }
    rows = [_row(family, text) for family, text in families.items()]

    result = evaluate_material_gold_csr_dataset({"rows": rows})

    assert result["passed_count"] == 6
    assert result["mutation_suite"]["status"] == "passed"
    assert result["mutation_suite"]["detected_count"] == result["mutation_suite"]["total"] == 8
    assert result["formal_contract"]["approves_product_facts"] is False


def test_automated_policy_decisions_are_fail_closed_and_do_not_apply_formal_kb():
    report = {
        "summary": {
            "direct_entry_review_candidates": [
                {
                    "entry_uid": "entry-a",
                    "classification": "composition_with_untrusted_provenance",
                    "source_type": "product_facts",
                    "provenance_kind": "knowledge_entry",
                    "fact_type": "material_composition",
                    "review_status": "published",
                    "direct_answer_state": "direct_allowed",
                    "strong_claim_mixed": "",
                    "identity_scope_quality": "scoped",
                },
                {
                    "entry_uid": "entry-b",
                    "classification": "composition_with_strong_claim",
                    "source_type": "product_facts",
                    "provenance_kind": "knowledge_entry",
                    "fact_type": "material_composition",
                    "review_status": "published",
                    "direct_answer_state": "direct_allowed",
                    "strong_claim_mixed": True,
                    "identity_scope_quality": "scoped",
                },
            ]
        }
    }

    decisions = build_automated_material_policy_decisions(report)

    assert {item["decision"] for item in decisions} == {
        "downgrade_to_human_review",
        "split_composition_and_strong_claim",
    }
    assert all(item["requires_human_validation"] is False for item in decisions)
    assert all(item["formal_kb_apply_allowed"] is False for item in decisions)
    assert all(item["can_change_can_send"] is False for item in decisions)
