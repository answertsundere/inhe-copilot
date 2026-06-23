from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalFailure, EvalRun, EvalTrace
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions
from app.services.real_conversation_replay_service import classify_turn_failures


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
