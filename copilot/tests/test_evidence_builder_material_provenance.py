from app.agent.nodes import evidence_builder as evidence_builder_module
from app.services.admitted_answer_context_service import collect_admitted_product_facts


def test_rag_product_fact_preserves_structured_claim_attribution_fields():
    result = evidence_builder_module.evidence_builder(
        {
            "intent": "product_question",
            "query_fact_type": "dimensions",
            "knowledge_evidence": [
                {
                    "entry_id": "entry-width",
                    "chunk_id": "chunk-width",
                    "evidence_uid": "evidence-width",
                    "source_type": "product_facts",
                    "chunk_text": "Width is 45 cm.",
                    "fact_type": "dimensions",
                    "evidence_fact_type": "dimensions",
                    "attribute_key": "width",
                    "subject_scope": "product",
                    "product_scope": ["IID-A"],
                    "entry_status": "published",
                    "fact_review_status": "reviewed",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                }
            ],
        }
    )

    fact = result["evidence"]["product_facts"][0]
    assert fact["attribute_key"] == "width"
    assert fact["evidence_uid"] == "evidence-width"
    assert fact["subject_scope"] == "product"
    assert fact["product_scope"] == ["IID-A"]


def test_preserved_rag_attribution_can_be_admitted_for_its_requested_field():
    result = evidence_builder_module.evidence_builder(
        {
            "intent": "product_question",
            "query_fact_type": "dimensions",
            "order_product_identity": {"i_id": "IID-A"},
            "knowledge_evidence": [
                {
                    "entry_id": "entry-width",
                    "chunk_id": "chunk-width",
                    "evidence_uid": "evidence-width",
                    "source_type": "product_facts",
                    "chunk_text": "Width is 45 cm.",
                    "evidence_fact_type": "dimensions",
                    "attribute_key": "width",
                    "subject_scope": "product",
                    "product_scope": ["IID-A"],
                    "entry_status": "published",
                    "fact_review_status": "reviewed",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                }
            ],
        }
    )

    admitted, rejected, _warnings = collect_admitted_product_facts(
        {"formal_evidence_candidates": result["evidence"]["product_facts"]},
        product_identity={"i_id": "IID-A"},
        requested_claim_types=["dimensions"],
    )

    assert rejected == []
    assert [(fact["attribute_key"], fact["evidence_uid"]) for fact in admitted] == [
        ("width", "evidence-width")
    ]


def test_published_product_material_placeholder_never_becomes_verified_fact(monkeypatch):
    profile = {
        "i_id": "ITEM-A",
        "status": "published",
        "specs": {
            "material": "PP",
            "_auto_backfill": {"batch": {"sources": {"material": "conservative_placeholder"}}},
        },
    }
    monkeypatch.setattr(evidence_builder_module, "_find_kb_product", lambda _state: profile)
    monkeypatch.setattr(evidence_builder_module, "_find_product_card", lambda _state: None)
    facts, verified, unknowns, sources = [], [], [], []

    evidence_builder_module._append_product_profile_evidence(
        {
            "query_fact_type": "material",
            "customer_message": "What is it made of?",
            "normalized_message": "What is it made of?",
            "order_product_identity": {"i_id": "ITEM-A"},
        },
        facts,
        verified,
        unknowns,
        sources,
    )

    assert facts == []
    assert verified == []
    assert unknowns[0]["material_admission_reason"] == "material_source_untrusted"


def test_published_rag_material_preserves_formal_chunk_provenance():
    result = evidence_builder_module.evidence_builder(
        {
            "intent": "product_question",
            "query_fact_type": "material",
            "knowledge_evidence": [
                {
                    "entry_id": 7083,
                    "chunk_id": 8150,
                    "title": "Basin material",
                    "source_type": "product_facts",
                    "chunk_text": "Material: PP, TPE.",
                    "evidence_fact_type": "material",
                    "evidence_allowed_for_direct_answer": True,
                    "evidence_allowed_for_exact_answer": True,
                    "entry_status": "published",
                    "fact_review_status": "published",
                    "material_provenance": "structured_product_profile",
                    "reference_only": False,
                }
            ],
        }
    )

    fact = result["evidence"]["product_facts"][0]
    assert fact["material_provenance"] == "structured_product_profile"
    assert fact["evidence_allowed_for_direct_answer"] is True


def test_exact_product_hub_fact_becomes_attributed_product_evidence():
    result = evidence_builder_module.evidence_builder(
        {
            "intent": "product_question",
            "query_fact_type": "dimensions",
            "order_product_identity": {"i_id": "YH57K02", "sku_code": "YH57K02B03S26"},
            "knowledge_evidence": [
                {
                    "entry_id": "product_data_hub:fact-width",
                    "chunk_id": "product_data_hub:fact-width",
                    "evidence_uid": "product_data_hub:fact-width",
                    "source_type": "product_facts",
                    "protocol_source_type": "product_data_hub",
                    "source_table": "product_data_hub",
                    "chunk_text": "36.5cm",
                    "evidence_fact_type": "dimensions",
                    "attribute_key": "width",
                    "subject_scope": "product",
                    "product_scope": ["YH57K02"],
                    "sku_scope": ["YH57K02B03S26"],
                    "entry_status": "published",
                    "fact_review_status": "verified",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                    "metadata": {
                        "product_evidence_protocol": True,
                        "trusted_product_hub_fact": True,
                        "verification_status": "verified",
                        "can_direct_answer": True,
                    },
                }
            ],
        }
    )

    fact = result["evidence"]["product_facts"][0]
    assert fact["source_table"] == "product_data_hub"
    assert fact["evidence_uid"] == "product_data_hub:fact-width"
    assert fact["attribute_key"] == "width"
    assert fact["evidence_allowed_for_direct_answer"] is True
