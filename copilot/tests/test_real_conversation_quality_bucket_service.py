from app.services.real_conversation_quality_bucket_service import (
    AGENT_ERROR,
    AUTO_SENDABLE,
    KNOWLEDGE_GAP,
    SAFE_HANDOFF,
    UNSCORED_OR_NOISE,
    classify_quality_bucket,
)


def _bucket(**kwargs):
    defaults = {
        "passed": False,
        "requires_human_review": False,
        "failure_labels": [],
        "failures": [],
        "turn_understanding": {"should_score": True, "turn_actionability": "actionable_question"},
    }
    defaults.update(kwargs)
    return classify_quality_bucket(**defaults).to_dict()


def test_passed_turn_without_failures_is_auto_sendable():
    result = _bucket(passed=True)

    assert result["quality_bucket"] == AUTO_SENDABLE
    assert result["is_auto_sendable"] is True
    assert result["should_count_in_quality_rate"] is True


def test_needs_human_review_with_rag_miss_is_knowledge_gap_by_priority():
    result = _bucket(
        requires_human_review=True,
        failure_labels=["needs_human_review", "rag_miss"],
        failures=[
            {"failure_type": "needs_human_review", "suggested_fix_area": "human_policy_risk_boundary"},
            {"failure_type": "rag_miss", "suggested_fix_area": "knowledge_rag"},
        ],
    )

    assert result["quality_bucket"] == KNOWLEDGE_GAP
    assert result["is_knowledge_gap"] is True
    assert SAFE_HANDOFF in result["secondary_buckets"]


def test_agent_error_labels_win_over_safe_handoff_and_gap():
    for label in [
        "unrequested_product_fact",
        "query_fact_type_missing",
        "semantic_mismatch",
        "unsupported_media_claim",
        "intent_contract_mismatch",
        "wrong_topic_reply",
        "evidence_misuse",
    ]:
        result = _bucket(requires_human_review=True, failure_labels=["needs_human_review", label])
        assert result["quality_bucket"] == AGENT_ERROR
        assert result["is_agent_error"] is True


def test_context_update_with_unrequested_product_fact_is_agent_error():
    result = _bucket(
        failure_labels=["unrequested_product_fact"],
        turn_understanding={"should_score": True, "turn_actionability": "context_update"},
    )

    assert result["quality_bucket"] == AGENT_ERROR
    assert result["is_agent_error"] is True
    assert result["should_count_in_quality_rate"] is True


def test_acknowledgement_with_wrong_topic_reply_is_agent_error():
    result = _bucket(
        failure_labels=["wrong_topic_reply"],
        turn_understanding={"should_score": False, "turn_actionability": "acknowledgement"},
    )

    assert result["quality_bucket"] == AGENT_ERROR
    assert result["is_agent_error"] is True
    assert result["should_count_in_quality_rate"] is True


def test_clean_acknowledgement_remains_unscored():
    result = _bucket(
        failure_labels=[],
        turn_understanding={"should_score": False, "turn_actionability": "acknowledgement"},
    )

    assert result["quality_bucket"] == UNSCORED_OR_NOISE
    assert result["should_count_in_quality_rate"] is False


def test_context_update_without_failure_remains_unscored():
    result = _bucket(
        failure_labels=[],
        turn_understanding={"should_score": True, "turn_actionability": "context_update"},
    )

    assert result["quality_bucket"] == UNSCORED_OR_NOISE
    assert result["should_count_in_quality_rate"] is False


def test_should_score_false_without_agent_error_is_unscored_or_noise():
    result = _bucket(
        turn_understanding={"should_score": False, "turn_actionability": "noise"},
        failure_labels=["rag_miss"],
    )

    assert result["quality_bucket"] == UNSCORED_OR_NOISE
    assert result["should_count_in_quality_rate"] is False


def test_rag_miss_still_knowledge_gap():
    result = _bucket(
        failure_labels=["rag_miss"],
        failures=[{"failure_type": "rag_miss", "suggested_fix_area": "knowledge_rag"}],
    )

    assert result["quality_bucket"] == KNOWLEDGE_GAP
    assert result["is_knowledge_gap"] is True


def test_pure_needs_human_review_is_safe_handoff():
    result = _bucket(requires_human_review=True, failure_labels=["needs_human_review"])

    assert result["quality_bucket"] == SAFE_HANDOFF
    assert result["is_safe_handoff"] is True
