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
