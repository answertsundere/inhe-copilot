from app.services.real_conversation_turn_understanding_service import (
    RealConversationTurnUnderstandingService,
    detect_reply_topics,
)


def _understand(message, **kwargs):
    return RealConversationTurnUnderstandingService().understand(message, **kwargs)


def test_receipt_and_installation_status_is_context_update_not_product_question():
    first = _understand("柜子我昨天收到已经装好了")
    variant = _understand("昨天收到了，已经装完了")

    for result in (first, variant):
        assert result["turn_actionability"] == "context_update"
        assert result["needs_rag"] is False
        assert result["should_score"] is True
        assert "dimensions" in result["forbidden_reply_topics"]
        assert "material" in result["forbidden_reply_topics"]


def test_acknowledgement_and_noise_are_not_scored_agent_turns():
    ack = _understand("好的")
    short = _understand("嗯")

    for result in (ack, short):
        assert result["turn_actionability"] == "acknowledgement"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is False
        assert result["reply_strategy"] == "skip"


def test_deictic_followup_without_context_is_context_insufficient():
    result = _understand("这一块")

    assert result["turn_actionability"] == "deictic_followup"
    assert result["needs_agent_reply"] is False
    assert result["should_score"] is True
    assert result["skip_reason"] == "context_insufficient"


def test_installation_video_and_dimension_questions_are_actionable():
    video = _understand("请发安装视频")
    size = _understand("最窄是什么尺寸")

    assert video["turn_actionability"] == "actionable_question"
    assert video["needs_rag"] is True
    assert video["query_fact_type"] == "installation"
    assert size["turn_actionability"] == "actionable_question"
    assert size["query_fact_type"] == "dimensions"


def test_reply_topic_detection_is_fact_type_based():
    topics = detect_reply_topics("您可以量一下宽深高，再对照尺寸图。承重以页面说明为准。")

    assert "dimensions" in topics
    assert "load_capacity" in topics


def test_replay_service_does_not_contain_mojibake_risk_terms():
    from pathlib import Path

    raw = Path("app/services/real_conversation_replay_service.py").read_text(encoding="utf-8")

    assert "锛" not in raw
    assert "鐭" not in raw
    assert "璧" not in raw
