from app.agent.nodes import evidence_builder as evidence_builder_module


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
