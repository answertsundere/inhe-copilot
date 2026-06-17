from app.services.evidence_alignment_service import align_evidence_to_query


def test_primary_fact_type_can_directly_answer():
    result = align_evidence_to_query(
        query_fact_type="space_fit",
        evidence_fact_type="dimensions",
        semantic_query={"secondary_fact_types": ["load_capacity"]},
    )

    assert result["allowed"] is True
    assert result["direct_answer_allowed"] is True
    assert result["alignment"] == "primary_match"
    assert result["score_delta"] > 0


def test_secondary_fact_type_is_context_not_direct_answer():
    result = align_evidence_to_query(
        query_fact_type="space_fit",
        evidence_fact_type="load_capacity",
        semantic_query={"secondary_fact_types": ["load_capacity"]},
    )

    assert result["allowed"] is True
    assert result["direct_answer_allowed"] is False
    assert result["alignment"] == "secondary_match"


def test_strict_mismatch_is_dropped():
    result = align_evidence_to_query(
        query_fact_type="placement_scene",
        evidence_fact_type="material",
        semantic_query={"secondary_fact_types": []},
    )

    assert result["allowed"] is False
    assert result["direct_answer_allowed"] is False
    assert result["alignment"] == "strict_mismatch"


def test_no_query_fact_type_keeps_evidence_available():
    result = align_evidence_to_query(
        query_fact_type="",
        evidence_fact_type="load_capacity",
        semantic_query={},
    )

    assert result["allowed"] is True
    assert result["direct_answer_allowed"] is True
    assert result["alignment"] == "no_query_fact_type"
