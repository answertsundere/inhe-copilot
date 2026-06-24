from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalFailure, EvalRun, EvalTrace
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions
from app.services.real_conversation_replay_service import classify_turn_failures
from app.services.real_conversation_replay_service import evaluate_replay_turn_result


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    return session_factory


def _seed_case(session_factory):
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_real_1", source_type="real_conversation", message="材质安全吗")
        db.add(case)
        db.add_all([
            EvalConversationTurn(
                case_uid="case_real_1",
                conversation_uid="conv_real_1",
                turn_uid="turn_buyer_1",
                turn_index=0,
                speaker="buyer",
                sanitized_text="这个材质安全吗？",
                reference_human_reply="材质以页面资料为准。",
            ),
            EvalConversationTurn(
                case_uid="case_real_1",
                conversation_uid="conv_real_1",
                turn_uid="turn_service_1",
                turn_index=1,
                speaker="service",
                sanitized_text="材质以页面资料为准。",
            ),
            EvalConversationTurn(
                case_uid="case_real_1",
                conversation_uid="conv_real_1",
                turn_uid="turn_buyer_2",
                turn_index=2,
                speaker="buyer",
                sanitized_text="会不会容易受潮？",
                reference_human_reply="建议保持干燥。",
            ),
        ])
        db.commit()
    finally:
        db.close()


def test_replay_keeps_history_out_of_current_message_and_stores_trace(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_case(session_factory)
    payloads = []

    class FakeReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            payloads.append(payload)
            return {
                "suggested_reply": "材质按资料说明，不建议长期受潮。",
                "requires_human_review": False,
                "evidence_debug": {
                    "query_fact_type": "material",
                    "selected_evidence": [{"fact_type": "material", "content": "板材说明"}],
                    "rejected_evidence": [],
                },
                "answer_trace": {
                    "query_fact_type": "material",
                    "required_fact_types": ["material"],
                    "evidence_answered_fact_types": ["material"],
                },
                "final_answer_audit": {"passed": True},
            }

    result = FakeReplayService().replay_cases(ReplayOptions(run_uid="run_test_1"))

    assert result["status"] == "completed"
    assert len(payloads) == 2
    assert payloads[1]["message"] == "会不会容易受潮？"
    assert "这个材质安全吗" not in payloads[1]["message"]
    assert payloads[1]["copilot_context"]["conversation_history"]

    db = session_factory()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == "run_test_1").one()
        traces = db.query(EvalTrace).order_by(EvalTrace.turn_index).all()
        assert run.total_turns == 2
        assert len(traces) == 2
        assert traces[0].query_fact_type == "material"
        assert traces[0].get_selected_evidence()[0]["fact_type"] == "material"
        assert traces[0].get_answer_trace()["required_fact_types"] == ["material"]
        assert db.query(EvalFailure).count() == 0
    finally:
        db.close()


def test_replay_records_failure_when_agent_requires_review(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_case(session_factory)

    class ReviewReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            return {
                "suggested_reply": "这个需要人工确认。",
                "requires_human_review": True,
                "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
                "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
            }

    result = ReviewReplayService().replay_cases(ReplayOptions(run_uid="run_review_1"))

    assert result["failed"] == 2
    db = session_factory()
    try:
        failures = db.query(EvalFailure).order_by(EvalFailure.id).all()
        labels = [row.failure_type for row in failures]
        assert "needs_human_review" in labels
        assert "rag_miss" in labels
        by_type = {row.failure_type: row for row in failures}
        assert by_type["needs_human_review"].suggested_fix_area == "human_policy_risk_boundary"
        assert by_type["rag_miss"].suggested_fix_area == "knowledge_rag"
        assert by_type["rag_miss"].suggested_owner == "knowledge_ops"
        assert by_type["rag_miss"].explanation
    finally:
        db.close()


def test_failure_classifier_covers_audit_policy_and_product_identity():
    failures = classify_turn_failures({
        "suggested_reply": "我先核实后回复。",
        "query_fact_type": "dimensions",
        "tool_policy_blocked": True,
        "product_identified": False,
        "final_answer_audit": {"passed": False},
        "evidence_debug": {"selected_evidence": []},
    })

    labels = {item["failure_type"] for item in failures}
    assert "semantic_mismatch" in labels
    assert "tool_policy_blocked" in labels
    assert "no_product_identified" in labels
    by_type = {item["failure_type"]: item for item in failures}
    assert by_type["semantic_mismatch"]["suggested_fix_area"] == "final_audit_semantic_compiler"
    assert by_type["tool_policy_blocked"]["suggested_owner"] == "agent_engineering"
    assert by_type["no_product_identified"]["explanation"]


def test_context_update_with_product_fact_reply_is_failed(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_status_1", source_type="real_conversation", message="status")
        db.add(case)
        db.add(EvalConversationTurn(
            case_uid="case_status_1",
            conversation_uid="conv_status_1",
            turn_uid="turn_status_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="柜子我昨天收到已经装好了",
        ))
        db.commit()
    finally:
        db.close()

    payloads = []

    class WrongTopicReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            payloads.append(payload)
            return {
                "suggested_reply": "亲可以先量一下宽深高，再对照尺寸图确认摆放空间。",
                "requires_human_review": False,
                "query_fact_type": "",
                "evidence_debug": {
                    "query_fact_type": "",
                    "selected_evidence": [{"fact_type": "dimensions", "content": "尺寸图"}],
                },
                "answer_trace": {"query_fact_type": "", "required_fact_types": []},
                "final_answer_audit": {"passed": True, "expected_topics": []},
            }

    result = WrongTopicReplayService().replay_cases(ReplayOptions(run_uid="run_status_wrong_topic"))

    assert len(payloads) == 1
    assert payloads[0]["copilot_context"]["turn_understanding"]["turn_actionability"] == "context_update"
    assert result["failed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        assert trace.passed is False
        assert trace.get_turn_understanding()["needs_rag"] is False
        labels = set(trace.get_failure_labels())
        assert "wrong_topic_reply" in labels
        assert "query_fact_type_missing" in labels
        assert "unrequested_product_fact" in labels
        assert "unnecessary_rag_call" in labels
    finally:
        db.close()


def test_acknowledgement_is_traced_but_not_scored_or_sent_to_agent(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        db.add(EvalCase(case_uid="case_ack_1", source_type="real_conversation", message="ack"))
        db.add(EvalConversationTurn(
            case_uid="case_ack_1",
            conversation_uid="conv_ack_1",
            turn_uid="turn_ack_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="好的",
        ))
        db.commit()
    finally:
        db.close()

    class AckReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            raise AssertionError("acknowledgement turn should not call agent")

    result = AckReplayService().replay_cases(ReplayOptions(run_uid="run_ack_skip"))

    assert result["turns"] == 0
    assert result["passed"] == 0
    assert result["failed"] == 0
    db = session_factory()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == "run_ack_skip").one()
        trace = db.query(EvalTrace).one()
        assert run.total_turns == 0
        assert trace.get_turn_understanding()["turn_actionability"] == "acknowledgement"
        assert trace.get_turn_understanding()["should_score"] is False
        assert trace.get_failure_labels() == []
    finally:
        db.close()


def test_replay_result_fails_empty_query_fact_type_with_product_reply():
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "context_update",
            "needs_rag": False,
            "should_score": True,
            "forbidden_reply_topics": ["dimensions", "material", "load_capacity"],
        },
        {
            "suggested_reply": "这款尺寸是宽80厘米，材质为PP。",
            "query_fact_type": "",
            "final_answer_audit": {"passed": True, "expected_topics": []},
        },
        [],
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is False
    assert "wrong_topic_reply" in labels
    assert "query_fact_type_missing" in labels
    assert "unrequested_product_fact" in labels
