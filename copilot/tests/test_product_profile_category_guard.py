from app.agent.nodes.evidence_builder import _append_product_profile_evidence


def test_book_context_does_not_answer_from_unrelated_faucet_product():
    product_facts = []
    verified_facts = []
    unknowns = []
    sources = []

    state = {
        "customer_message": "可以放多少本绘本",
        "normalized_message": "可以放多少本绘本",
        "query_fact_type": "load_capacity",
        "matched_product_name": "1号快乐鲸鱼水龙头延长器",
    }

    _append_product_profile_evidence(state, product_facts, verified_facts, unknowns, sources)

    assert product_facts == []
    assert verified_facts == []
    assert unknowns
    assert unknowns[0]["product_category_mismatch"] is True
    assert unknowns[0]["reference_only"] is True
