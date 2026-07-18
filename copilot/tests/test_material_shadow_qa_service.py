from app.services.material_shadow_qa_service import run_material_shadow_qa


def test_real_derived_material_shadow_qa_keeps_supported_composition_and_unresolved_risks():
    report = {
        "source": {"query_only": True, "source_database_mutated": False, "database_sha256": "a" * 64},
        "product_review_candidates": [
            {
                "product_uid": f"product_{index:020d}",
                "classification": "composition_ready",
                "material_value": "PP",
                "material_source_kind": "structured_product_record",
            }
            for index in range(5)
        ],
    }

    result = run_material_shadow_qa(report)

    assert result["case_count"] == 30
    assert result["metrics"]["composition_supported_rate"]["numerator"] == 5
    assert result["metrics"]["unresolved_claim_preservation_rate"]["numerator"] == 25
    assert result["safety"]["can_send_change_count"] == 0
    assert result["safety"]["formal_reply_mutation_count"] == 0
    assert all("expected" not in row for row in result["rows"])
    assert all("product_" in row["product_identity"]["i_id"] for row in result["rows"])
    bite = next(row for row in result["rows"] if row["query_family"] == "bite_or_toxicity")
    assert "咨询医生" in bite["candidate_preview"]
