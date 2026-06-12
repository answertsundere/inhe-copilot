from app.services.evidence_fact_gate_service import evaluate_evidence_item


def test_gate_blocks_wrong_fact_type():
    item = {
        "source_type": "product_facts",
        "score": 0.9,
        "rerank_score": 0.9,
        "query_fact_type": "material",
        "evidence_fact_type": "dimensions",
        "entry_status": "published",
        "evidence_allowed_for_exact_answer": True,
    }

    result = evaluate_evidence_item(item, {})

    assert result["direct_answer_allowed"] is False
    assert result["evidence_allowed_for_direct_answer"] is False
    assert "wrong_fact_type" in result["gate_reasons"]
    assert result["gate_status"] == "blocked"


def test_gate_marks_product_mapping_reference_only():
    item = {
        "source_type": "product_mapping",
        "score": 0.95,
        "rerank_score": 0.95,
        "query_fact_type": "",
        "evidence_fact_type": "",
        "entry_status": "published",
        "evidence_allowed_for_exact_answer": True,
    }

    result = evaluate_evidence_item(item, {})

    assert result["direct_answer_allowed"] is False
    assert result["reference_only"] is True
    assert result["gate_status"] == "reference_only"
    assert "reference_only_source" in result["gate_reasons"]


def test_gate_requires_review_for_unverified_high_risk_fact():
    item = {
        "source_type": "product_facts",
        "score": 0.88,
        "rerank_score": 0.88,
        "query_fact_type": "certification_report",
        "evidence_fact_type": "certification_report",
        "entry_status": "draft",
        "fact_review_status": "pending",
        "evidence_allowed_for_exact_answer": True,
    }

    result = evaluate_evidence_item(item, {})

    assert result["direct_answer_allowed"] is False
    assert result["requires_human_review"] is True
    assert result["gate_status"] == "blocked"
    assert "unverified_high_risk_fact" in result["gate_reasons"]


def test_gate_allows_published_product_fact():
    item = {
        "source_type": "product_facts",
        "score": 0.82,
        "rerank_score": 0.82,
        "query_fact_type": "material",
        "evidence_fact_type": "material",
        "entry_status": "published",
        "evidence_allowed_for_exact_answer": True,
    }

    result = evaluate_evidence_item(item, {})

    assert result["direct_answer_allowed"] is True
    assert result["evidence_allowed_for_direct_answer"] is True
    assert result["gate_status"] == "allowed"
    assert result["gate_reasons"] == []


def test_gate_allows_installation_evidence_with_convenience_warning():
    item = {
        "source_type": "installation_guide",
        "score": 0.9,
        "rerank_score": 0.9,
        "query_fact_type": "installation",
        "evidence_fact_type": "installation",
        "entry_status": "published",
        "evidence_allowed_for_exact_answer": True,
        "chunk_text": "\u5b89\u88c5\u5f88\u65b9\u4fbf\uff0c\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177\u3002",
    }

    result = evaluate_evidence_item(item, {})

    assert result["direct_answer_allowed"] is True
    assert result["evidence_allowed_for_direct_answer"] is True
    assert result["reference_only"] is False
    assert result["gate_status"] == "allowed"
    assert "risky_convenience_claim" in result["gate_reasons"]


def test_gate_blocks_material_evidence_for_stability_question():
    item = {
        "source_type": "product_facts",
        "score": 0.9,
        "rerank_score": 0.9,
        "query_fact_type": "stability",
        "evidence_fact_type": "material",
        "entry_status": "published",
        "evidence_allowed_for_exact_answer": True,
        "chunk_text": "\u6750\u8d28\u662f\u51b7\u8f67\u94a2\u7ba1\u3001\u73af\u4fddPP\u3001\u65e0\u7eba\u5e03\u3002",
    }

    result = evaluate_evidence_item(item, {})

    assert result["direct_answer_allowed"] is False
    assert result["evidence_allowed_for_direct_answer"] is False
    assert result["gate_status"] == "reference_only"
    assert "wrong_fact_type" in result["gate_reasons"]


def test_gate_requires_review_for_absolute_stability_request():
    item = {
        "source_type": "faq",
        "score": 0.9,
        "rerank_score": 0.9,
        "query_fact_type": "stability",
        "evidence_fact_type": "stability",
        "entry_status": "published",
        "evidence_allowed_for_exact_answer": True,
        "chunk_text": "\u7ed3\u6784\u624e\u5b9e\u7a33\u56fa\uff0c\u5efa\u8bae\u91cd\u7269\u653e\u4e0b\u5c42\u3002",
    }
    state = {
        "customer_message": "\u8fd9\u4e2a\u7ed9\u5b9d\u5b9d\u7528\u7edd\u5bf9\u4e0d\u4f1a\u5012\u5427\uff1f",
        "query_fact_type": "stability",
    }

    result = evaluate_evidence_item(item, state)

    assert result["direct_answer_allowed"] is False
    assert result["requires_human_review"] is True
    assert result["gate_status"] == "blocked"
    assert "absolute_stability_request" in result["gate_reasons"]


def test_gate_blocks_llm_high_risk_stability_request():
    item = {
        "source_type": "faq",
        "score": 0.9,
        "rerank_score": 0.9,
        "query_fact_type": "stability",
        "evidence_fact_type": "stability",
        "entry_status": "published",
        "fact_review_status": "verified",
        "evidence_allowed_for_exact_answer": True,
        "chunk_text": "\u7ed3\u6784\u624e\u5b9e\u7a33\u56fa\uff0c\u653e\u4e66\u7c4d\u3001\u73a9\u5177\u7b49\u5b8c\u5168\u591f\u7528\u3002",
    }
    state = {
        "customer_message": "\u5b9d\u5b9d\u6276\u7740\u5b83\u4f1a\u4e0d\u4f1a\u7ffb\uff1f\u6211\u6709\u70b9\u62c5\u5fc3\u5b89\u5168",
        "query_fact_type": "stability",
        "query_fact_type_source": "llm",
        "query_fact_type_risk_hint": "high",
    }

    result = evaluate_evidence_item(item, state)

    assert result["direct_answer_allowed"] is False
    assert result["requires_human_review"] is True
    assert result["gate_status"] == "blocked"
    assert "semantic_high_risk_stability" in result["gate_reasons"]
