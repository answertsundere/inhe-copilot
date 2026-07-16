from __future__ import annotations

from copy import deepcopy

from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    is_placeholder_evidence_text,
)


def _fact(**overrides):
    value = {
        "evidence_uid": "fact-material",
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "fact_type": "material",
        "attribute_key": "material",
        "content": "主体材质为PP。",
        "sku_code": "SKU-A",
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
    }
    value.update(overrides)
    return value


def _understanding(*claim_types):
    return {
        "requested_claims": [
            {"claim_type": item, "question": item, "risk_level": "high" if "safety" in item else "medium"}
            for item in claim_types
        ]
    }


def test_placeholder_semantics_reject_verification_copy_without_rejecting_real_values():
    placeholders = (
        "\u672a\u660e\u786e\u5c3a\u5bf8",
        "\u672a\u5728\u73b0\u6709\u7ed3\u6784\u8d44\u6599\u4e2d\u660e\u786e\u5c3a\u5bf8",
        "\u5f53\u524d\u8d44\u6599\u4e2d\u6682\u672a\u660e\u786e\u662f\u5426\u53ef\u62c6",
        "\u9700\u8981\u4eba\u5de5\u6838\u5b9e",
        "\u4ee5\u8be6\u60c5\u9875\u4e3a\u51c6",
        "\u4ee5\u5b9e\u7269\u4e3a\u51c6",
        "\u5f85\u786e\u8ba4",
        "\u6682\u65e0\u660e\u786e\u6570\u636e",
    )
    real_values = ("\u4e3b\u4f53\u6750\u8d28 PP", "\u5bbd 38cm", "\u6bdb\u91cd 2.5kg", "\u53ef\u62c6\u5378", "\u4e0d\u53ef\u62c6\u5378")

    assert all(is_placeholder_evidence_text(value) for value in placeholders)
    assert not any(is_placeholder_evidence_text(value) for value in real_values)


def test_admits_reviewed_scoped_direct_product_fact():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    assert context["unresolved_claims"] == []
    assert context["read_only"] is True
    assert context["can_change_can_send"] is False


def test_rejects_reference_placeholder_identity_mismatch_and_unreviewed_faq():
    response = {
        "selected_evidence": [
            _fact(evidence_uid="reference", reference_only=True),
            _fact(evidence_uid="placeholder", content="材质未明确，需要人工确认。"),
            _fact(evidence_uid="wrong-product", sku_code="SKU-B"),
            _fact(
                evidence_uid="faq-unreviewed",
                evidence_role="faq_direct",
                source_type="faq",
                fact_review_status="pending_review",
            ),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    reasons = {item["evidence_uid"]: item["reason"] for item in context["rejected_evidence"]}
    assert reasons == {
        "reference": "reference_only",
        "placeholder": "placeholder_evidence",
        "wrong-product": "product_identity_mismatch",
        "faq-unreviewed": "review_status_missing",
    }


def test_rejects_placeholder_with_intervening_characters():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact(evidence_uid="placeholder-spread", content="未在现有结构资料中明确尺寸")]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    reasons = {item["evidence_uid"]: item["reason"] for item in context["rejected_evidence"]}
    assert reasons == {"placeholder-spread": "placeholder_evidence"}


def test_conflicting_product_fact_and_faq_are_both_blocked():
    response = {
        "selected_evidence": [
            _fact(evidence_uid="product", attribute_key="load_capacity", fact_type="load_capacity", value="10kg", content="承重10kg"),
            _fact(evidence_uid="faq", evidence_role="faq_direct", source_type="faq", attribute_key="load_capacity", fact_type="load_capacity", value="15kg", content="承重15kg"),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("load_capacity"),
    )

    assert context["direct_product_facts"] == []
    assert {item["evidence_uid"] for item in context["conflicts"]} == {"product", "faq"}
    assert {item["reason"] for item in context["conflicts"]} == {"conflicting_evidence"}


def test_conflicting_structured_material_values_are_both_blocked():
    response = {
        "selected_evidence": [
            _fact(evidence_uid="product-material", value="PP", content="主体材质为PP。"),
            _fact(
                evidence_uid="faq-material",
                evidence_role="faq_direct",
                source_type="faq",
                value="ABS",
                content="主体材质为ABS。",
            ),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    assert {item["evidence_uid"] for item in context["conflicts"]} == {
        "product-material", "faq-material",
    }


def test_compound_claims_do_not_promote_material_into_safety_or_moisture():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition", "material_safety", "moisture_resistance"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    assert {item["claim_type"] for item in context["unresolved_claims"]} == {
        "material_safety",
        "moisture_resistance",
    }
    resolutions = {item["claim_type"]: item for item in context["claim_resolutions"]}
    assert resolutions["material_composition"]["status"] == "supported"
    assert resolutions["material_composition"]["evidence_uids"] == ["fact-material"]
    assert resolutions["material_safety"]["status"] == "unresolved"
    assert resolutions["moisture_resistance"]["status"] == "unresolved"


def test_material_composition_cannot_admit_a_material_safety_claim():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_safety"),
    )

    assert context["direct_product_facts"] == []
    assert context["claim_resolutions"][0]["status"] == "unresolved"
    assert context["rejected_evidence"][0]["reason"] == "fact_type_incompatible"


def test_conflicting_claim_is_not_reported_as_supported():
    context = AdmittedAnswerContextService().build_for_response(
        {
            "selected_evidence": [
                _fact(evidence_uid="a", value="10kg", content="承重10kg", fact_type="load_capacity", attribute_key="load_capacity"),
                _fact(evidence_uid="b", value="15kg", content="承重15kg", fact_type="load_capacity", attribute_key="load_capacity"),
            ]
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("load_capacity"),
    )

    resolution = context["claim_resolutions"][0]
    assert resolution["claim_type"] == "load_capacity"
    assert resolution["status"] == "conflicting"
    assert resolution["evidence_uids"] == []
    assert resolution["conflicting_evidence_uids"] == ["a", "b"]
    assert resolution["requires_human_review"] is True
    assert resolution["reason"] == "conflicting_evidence"
    assert resolution["claim_uid"].startswith("claim-")


def test_roles_remain_separate():
    response = {
        "product_context_pack": {
            "generic_rules": [{
                "evidence_uid": "action",
                "source_type": "generic_rule",
                "evidence_role": "service_action",
                "content": "无法确认时转人工核对。",
            }],
            "media_assets": [{
                "evidence_uid": "media",
                "source_type": "media_asset",
                "evidence_role": "media_reference",
                "asset_type": "size_chart_image",
                "asset_url": "https://example.com/size.png",
            }],
        }
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
    )

    assert context["direct_product_facts"] == []
    assert [item["evidence_uid"] for item in context["handoff_action_guidance"]] == ["action"]
    assert [item["evidence_uid"] for item in context["media_candidates"]] == ["media"]


def test_service_does_not_mutate_input():
    response = {"selected_evidence": [_fact()]}
    before = deepcopy(response)
    AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )
    assert response == before


def test_read_only_shadow_retrieval_results_still_require_admission():
    response = {
        "evidence_debug": {
            "llm_decision_shadow_tool_results": {
                "rag_search_tool": {"chunks": [_fact(evidence_uid="shadow-material")]}
            }
        }
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["shadow-material"]
    assert context["direct_product_facts"][0]["source_container"].startswith(
        "llm_decision_shadow_tool_results"
    )


def test_uses_explicit_resolved_identity_from_evidence_pack():
    response = {
        "selected_evidence": [_fact()],
        "context_used": {
            "product_context_pack": {
                "evidence_pack": {"identity": {"sku": "SKU-A", "i_id": "IID-A"}}
            }
        },
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    assert context["product_identity"] == {"sku_code": "SKU-A", "i_id": "IID-A"}


def test_reviewed_structured_pack_fact_enters_shadow_context_with_explicit_scope():
    structured_fact = {
        "evidence_id": "kbproduct:42:material",
        "source_type": "product_facts",
        "fact_type": "material",
        "attribute_key": "material",
        "chunk_text": "Material: verified board and steel frame.",
        "sku_scope": ["SKU-A"],
        "product_scope": ["IID-A"],
        "metadata": {
            "product_evidence_protocol": True,
            "verification_status": "verified",
            "can_direct_answer": True,
        },
    }
    context = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [structured_fact]}},
        product_identity={"sku_code": "SKU-A", "i_id": "IID-A"},
        understanding=_understanding("material_composition"),
    )

    assert len(context["direct_product_facts"]) == 1
    assert context["direct_product_facts"][0]["origin_evidence_key"] == "product_facts:kbproduct:42:material"
    assert context["direct_product_facts"][0]["text"] == "Material: verified board and steel frame."
    trace = context["evidence_convergence"]
    record = trace["records"][0]
    assert record["context_pack_candidate"] is True
    assert record["formal_selected"] is False
    assert record["shadow_admission"] == "admitted"
    assert record["llm_context"] is True
    assert trace["summary"]["context_pack_not_formal_selected_count"] == 1


def test_structured_pack_fact_with_nonmatching_explicit_scope_stays_rejected():
    structured_fact = {
        "evidence_id": "kbproduct:42:material",
        "source_type": "product_facts",
        "fact_type": "material",
        "attribute_key": "material",
        "chunk_text": "Material: verified board and steel frame.",
        "sku_scope": ["SKU-B"],
        "product_scope": ["IID-B"],
        "metadata": {
            "product_evidence_protocol": True,
            "verification_status": "verified",
            "can_direct_answer": True,
        },
    }
    context = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [structured_fact]}},
        product_identity={"sku_code": "SKU-A", "i_id": "IID-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    assert context["rejected_evidence"][0]["reason"] == "product_identity_mismatch"
    assert context["evidence_convergence"]["records"][0]["llm_context"] is False
