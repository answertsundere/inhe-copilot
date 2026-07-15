from __future__ import annotations

from app.agent.nodes.evidence_builder import _formal_evidence_convergence
from app.agent.nodes.generate_reply import _real_product_facts
from app.agent.nodes.build_response import build_response
from app.models.reply import ReplySuggestion
from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_minimal_decision_context,
    canonical_selected_evidence,
)


def _candidate(**overrides):
    item = {
        "evidence_uid": "material-a",
        "source_type": "product_facts",
        "fact_type": "material",
        "attribute_key": "material",
        "chunk_text": "Material is PP.",
        "sku_code": "SKU-A",
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
    }
    item.update(overrides)
    return item


def _understanding(*claim_types):
    return {
        "requested_claims": [
            {"claim_type": claim_type, "question": claim_type, "risk_level": "medium"}
            for claim_type in claim_types
        ]
    }


def test_formal_candidate_reuses_admission_and_becomes_canonical_selection():
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [_candidate()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    selected = canonical_selected_evidence(context)

    assert [item["evidence_uid"] for item in selected] == ["material-a"]
    assert selected[0]["evidence_role"] == "product_fact_direct"
    assert selected[0]["content"] == "Material is PP."


def test_reviewed_product_context_pack_fact_enters_formal_selection():
    context = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [{
            "evidence_uid": "pack-material",
            "fact_type": "material",
            "attribute_key": "material",
            "chunk_text": "Material is PP.",
            "sku_scope": ["SKU-A"],
            "metadata": {
                "product_evidence_protocol": True,
                "verification_status": "verified",
                "can_direct_answer": True,
            },
        }]}},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in canonical_selected_evidence(context)] == ["pack-material"]


def test_protocolised_pack_fact_wins_over_same_uid_raw_pack_duplicate():
    shared_uid = "pack-material"
    context = AdmittedAnswerContextService().build_for_response(
        {
            "formal_evidence_candidates": [{
                "evidence_uid": shared_uid,
                "source_type": "product_facts",
                "fact_type": "material",
                "chunk_text": "Material is PP.",
                "sku_code": "SKU-A",
            }],
            "product_context_pack": {"facts": [{
                "evidence_uid": shared_uid,
                "fact_type": "material",
                "attribute_key": "material",
                "chunk_text": "Material is PP.",
                "sku_scope": ["SKU-A"],
                "metadata": {
                    "product_evidence_protocol": True,
                    "verification_status": "verified",
                    "can_direct_answer": True,
                },
            }]},
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in canonical_selected_evidence(context)] == [shared_uid]


def test_formal_candidate_preserves_matched_scope_as_identity_provenance():
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [
            _candidate(sku_code="", sku_scope=["SKU-A", "SKU-B"]),
        ]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    selected = canonical_selected_evidence(context)
    assert selected[0]["product_identity_scope"] == [{"namespace": "sku_code", "value": "SKU-A"}]


def test_formal_convergence_rejects_non_facts_and_identity_or_gate_failures():
    candidates = [
        _candidate(evidence_uid="blocked", gate_status="blocked"),
        _candidate(evidence_uid="reference", reference_only=True),
        _candidate(evidence_uid="wrong-sku", sku_code="SKU-B"),
        _candidate(evidence_uid="missing-identity", sku_code=""),
        _candidate(evidence_uid="service", source_type="service_action", evidence_role="service_action"),
        _candidate(evidence_uid="media", source_type="media_reference", evidence_role="media_reference"),
        _candidate(evidence_uid="memory", source_type="answer_memory", evidence_role="answer_memory"),
    ]
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": candidates},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    reasons = {item["evidence_uid"]: item["reason"] for item in context["rejected_evidence"]}
    assert reasons["blocked"] == "gate_not_allowed"
    assert reasons["reference"] == "reference_only"
    assert reasons["wrong-sku"] == "product_identity_mismatch"
    assert reasons["missing-identity"] == "product_identity_missing"
    assert {"service", "media", "memory"}.isdisjoint(reasons)


def test_convergence_deduplicates_and_is_order_independent():
    first = _candidate(evidence_uid="same-fact", chunk_text="Width is 80cm.", fact_type="dimensions", attribute_key="width")
    duplicate = _candidate(
        evidence_uid="same-fact",
        source_type="faq",
        chunk_text="Width is 80cm.",
        fact_type="dimensions",
        attribute_key="width",
    )
    response = {"formal_evidence_candidates": [first, duplicate]}
    reversed_response = {"formal_evidence_candidates": [duplicate, first]}

    def selected(source):
        context = AdmittedAnswerContextService().build_for_response(
            source,
            product_identity={"sku_code": "SKU-A"},
            understanding=_understanding("dimensions"),
        )
        return canonical_selected_evidence(context)

    assert selected(response) == selected(reversed_response)
    assert len(selected(response)) == 1


def test_convergence_deduplicates_rag_and_pack_copies_with_one_origin_key():
    rag_copy = _candidate(
        evidence_uid="rag-copy",
        origin_evidence_key="product-fact:width-80",
        chunk_text="Width is 80cm.",
        fact_type="dimensions",
        attribute_key="width",
    )
    pack_copy = _candidate(
        evidence_uid="pack-copy",
        origin_evidence_key="product-fact:width-80",
        chunk_text="Width is 80cm.",
        fact_type="dimensions",
        attribute_key="width",
    )
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [rag_copy, pack_copy]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
    )

    assert len(canonical_selected_evidence(context)) == 1


def test_conflicting_candidates_are_excluded_with_provenance():
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [
            _candidate(evidence_uid="width-80", chunk_text="Width is 80cm.", value="80cm", fact_type="dimensions", attribute_key="width"),
            _candidate(evidence_uid="width-120", chunk_text="Width is 120cm.", value="120cm", fact_type="dimensions", attribute_key="width"),
        ]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
    )

    assert canonical_selected_evidence(context) == []
    assert {item["evidence_uid"] for item in context["conflicts"]} == {"width-80", "width-120"}


def test_minimal_context_keeps_partial_claim_resolution_and_omits_unbounded_inputs():
    admitted = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [_candidate()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition", "moisture_resistance"),
    )

    context = build_minimal_decision_context(
        admitted,
        customer_message="What is the material and is it moisture resistant?",
        conversation_summary={"summary": "customer asks two facts", "history": "must not be present"},
        allowed_read_only_tools=["rag_search_tool"],
    )

    assert context["claim_resolutions"][0]["status"] == "supported"
    assert context["claim_resolutions"][1]["status"] == "unresolved"
    assert context["admitted_evidence"][0]["evidence_uid"] == "material-a"
    assert "history" not in context["conversation_summary"]
    assert "rejected_evidence" not in context
    assert context["can_change_can_send"] is False


def test_feature_flag_keeps_formal_state_unchanged_when_disabled(monkeypatch):
    monkeypatch.delenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", raising=False)
    assert _formal_evidence_convergence(
        {"customer_message": "material", "slots": {"sku_code": "SKU-A"}},
        product_facts=[_candidate()],
        policy_facts=[],
        faq_evidence=[],
    ) == {}


def test_feature_flag_produces_supervisor_only_preview(monkeypatch):
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    result = _formal_evidence_convergence(
        {
            "customer_message": "material",
            "query_fact_type": "material_composition",
            "slots": {"sku_code": "SKU-A"},
        },
        product_facts=[_candidate()],
        policy_facts=[],
        faq_evidence=[],
    )

    assert [item["evidence_uid"] for item in result["selected_evidence"]] == ["material-a"]
    assert result["supervisor_candidate_preview"]["can_send"] is False
    assert result["supervisor_candidate_preview"]["used_for_final_reply"] is False
    assert result["supervisor_candidate_preview"]["render_mode"] == "deterministic"
    assert "Material is PP." in result["supervisor_candidate_preview"]["candidate_text"]


def test_formal_selection_is_the_only_product_fact_input_when_present():
    selected = _candidate(evidence_uid="selected", chunk_text="Material is PP.")
    raw_only = _candidate(evidence_uid="raw", chunk_text="Material is ABS.")
    facts = _real_product_facts({
        "query_fact_type": "material",
        "selected_evidence": [{
            **selected,
            "evidence_role": "product_fact_direct",
            "content": selected["chunk_text"],
        }],
        "knowledge_evidence": [raw_only],
    })

    assert [item["evidence_uid"] for item in facts] == ["selected"]


def test_build_response_persists_the_same_formal_selection_as_debug_context():
    selection = [{
        "evidence_uid": "selected",
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "content": "Material is PP.",
    }]
    response = build_response({
        "suggested_reply": "Draft reply.",
        "selected_evidence": selection,
        "minimal_decision_context": {"schema_version": "minimal-decision-context-v1"},
        "supervisor_candidate_preview": {"can_send": False},
        "formal_evidence_convergence": {"summary": {"formal_selected_count": 1}},
        "evidence": {},
    })

    assert response["selected_evidence"] == selection
    assert response["evidence_debug"]["selected_evidence"] == selection
    assert response["minimal_decision_context"]["schema_version"] == "minimal-decision-context-v1"


def test_reply_suggestion_keeps_opt_in_formal_evidence_fields():
    suggestion = ReplySuggestion.from_dict({
        "suggested_reply": "Draft reply.",
        "selected_evidence": [{"evidence_uid": "selected"}],
        "minimal_decision_context": {"schema_version": "minimal-decision-context-v1"},
        "supervisor_candidate_preview": {"can_send": False},
    })

    payload = suggestion.to_dict()

    assert payload["selected_evidence"] == [{"evidence_uid": "selected"}]
    assert payload["minimal_decision_context"]["schema_version"] == "minimal-decision-context-v1"
    assert payload["supervisor_candidate_preview"]["can_send"] is False
