from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalRun, EvalTrace, KnowledgeGapTask, KnowledgeGapTaskSample
from app.services.knowledge_gap_retest_service import KnowledgeGapRetestService
from app.services.real_conversation_replay_service import RealConversationReplayService


def _make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_task(session_factory, *, related_turns=None):
    related_turns = related_turns or ["turn_gap_1", "turn_gap_2"]
    db = session_factory()
    try:
        db.add(EvalRun(run_uid="source_run_1", source_type="real_conversation", status="completed"))
        case = EvalCase(case_uid="case_gap_1", source_type="real_conversation", status="active")
        case.message = "material question"
        case.set_metadata({
            "real_context": {
                "conversation_type": "presales",
                "source_page": "product_detail",
                "product": {
                    "product_title": "children storage cabinet",
                    "sku_code": "SKU-TEST",
                },
                "order": {},
                "media": {"image_urls": [], "video_urls": []},
                "raw_context_sources": ["product_title", "sku_code"],
            }
        })
        db.add(case)
        db.add_all([
            EvalConversationTurn(
                case_uid="case_gap_1",
                conversation_uid="conv_gap_1",
                turn_uid="turn_gap_1",
                turn_index=0,
                speaker="buyer",
                sanitized_text="这个材质安全吗？",
                reference_human_reply="reference one",
            ),
            EvalConversationTurn(
                case_uid="case_gap_1",
                conversation_uid="conv_gap_1",
                turn_uid="turn_service_1",
                turn_index=1,
                speaker="service",
                sanitized_text="service reply",
            ),
            EvalConversationTurn(
                case_uid="case_gap_1",
                conversation_uid="conv_gap_1",
                turn_uid="turn_gap_2",
                turn_index=2,
                speaker="buyer",
                sanitized_text="材质会不会受潮？",
                reference_human_reply="reference two",
            ),
            EvalConversationTurn(
                case_uid="case_gap_1",
                conversation_uid="conv_gap_1",
                turn_uid="turn_unrelated",
                turn_index=3,
                speaker="buyer",
                sanitized_text="unrelated",
            ),
        ])
        task = KnowledgeGapTask(
            task_uid="kgap_retest_1",
            gap_type="product_field_gap",
            query_fact_type="material",
            failure_type="rag_miss",
            suggested_fix_area="knowledge_rag",
            suggested_owner="knowledge_ops",
            missing_evidence_type="product_material",
            status="resolved_pending_retest",
            priority="medium",
            sample_count=len(related_turns),
        )
        task.set_related_case_uids(["case_gap_1"])
        task.set_related_turn_uids(related_turns)
        task.set_metadata({
            "source_run_uid": "source_run_1",
            "gap_category": "product_field_gap",
            "required_evidence_type": "product_material",
        })
        db.add(task)
        for turn_uid in related_turns:
            db.add(KnowledgeGapTaskSample(
                task_uid="kgap_retest_1",
                run_uid="source_run_1",
                case_uid="case_gap_1",
                turn_uid=turn_uid,
                buyer_message="buyer",
                agent_reply="agent",
                failure_type="rag_miss",
                query_fact_type="material",
            ))
        db.commit()
    finally:
        db.close()


def _seed_task_without_samples(session_factory):
    db = session_factory()
    try:
        db.add(KnowledgeGapTask(
            task_uid="kgap_empty",
            gap_type="product_field_gap",
            query_fact_type="material",
            failure_type="rag_miss",
            missing_evidence_type="product_material",
            status="resolved_pending_retest",
            sample_count=0,
        ))
        db.commit()
    finally:
        db.close()


def _passing_agent(self, payload):
    return {
        "suggested_reply": "current agent answer with evidence",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{"fact_type": "material", "content": "verified material evidence"}],
        },
        "answer_trace": {
            "query_fact_type": "material",
            "required_fact_types": ["material"],
            "evidence_answered_fact_types": ["material"],
        },
        "final_answer_audit": {"passed": True},
    }


def _failing_agent(self, payload):
    return {
        "suggested_reply": "generic fallback",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
        "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
        "final_answer_audit": {"passed": False},
    }


def _handoff_agent(self, payload):
    return {
        "suggested_reply": "please wait for manual review",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{"fact_type": "material", "content": "evidence exists but needs review"}],
        },
        "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
        "final_answer_audit": {"passed": True},
    }


def test_knowledge_gap_retest_preview_does_not_write(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)

    result = KnowledgeGapRetestService().preview_task("kgap_retest_1")

    assert result["dry_run"] is True
    assert result["sample_count"] == 2
    assert result["checked_turn_uids"] == ["turn_gap_1", "turn_gap_2"]
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        assert task.get_metadata().get("verification_status") is None
        assert db.query(EvalRun).count() == 1
        assert db.query(EvalTrace).count() == 0
    finally:
        db.close()


def test_knowledge_gap_retest_without_related_samples_records_error(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task_without_samples(session_factory)

    result = KnowledgeGapRetestService().retest_task("kgap_empty", verified_by="lead")

    assert result["ok"] is False
    assert result["task"]["verification_status"] == "error"
    assert result["verification"]["remaining_failure_types"] == ["context_missing"]
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        assert task.status == "resolved_pending_retest"
        assert task.get_metadata()["verification_history"][-1]["verification_status"] == "error"
    finally:
        db.close()


def test_knowledge_gap_retest_passed_marks_task_verified(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _passing_agent)

    result = KnowledgeGapRetestService().retest_task("kgap_retest_1", verified_by="lead")

    assert result["task"]["status"] == "verified"
    assert result["task"]["verification_status"] == "verified_passed"
    assert result["verification"]["summary"]["passed_turns"] == 2
    assert result["verification"]["summary"]["agent_error_count"] == 0
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == "kgap_retest_1").one()
        assert task.status == "verified"
        assert task.get_metadata()["verification_run_uid"].startswith("kgap_retest_")
        assert task.get_metadata()["verification_history"][-1]["verification_status"] == "verified_passed"
    finally:
        db.close()


def test_knowledge_gap_retest_failed_does_not_verify_task(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _failing_agent)

    result = KnowledgeGapRetestService().retest_task("kgap_retest_1", verified_by="lead")

    assert result["task"]["verification_status"] == "retest_failed"
    assert result["task"]["status"] == "waiting_data"
    assert "semantic_mismatch" in result["verification"]["summary"]["remaining_failure_types"]
    assert result["verification"]["summary"]["agent_error_count"] >= 1
    db = session_factory()
    try:
        assert db.query(KnowledgeGapTask).one().status != "verified"
    finally:
        db.close()


def test_knowledge_gap_retest_safe_handoff_is_not_fully_verified_by_default(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _handoff_agent)

    result = KnowledgeGapRetestService().retest_task("kgap_retest_1", verified_by="lead")

    assert result["task"]["verification_status"] == "retest_failed"
    assert result["task"]["status"] == "waiting_data"
    assert result["verification"]["summary"]["safe_handoff_count"] >= 1


def test_knowledge_gap_retest_only_replays_related_turns(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory, related_turns=["turn_gap_2"])
    called_turns = []

    def recording_agent(self, payload):
        called_turns.append(payload["copilot_context"]["eval_turn_uid"])
        return _passing_agent(self, payload)

    monkeypatch.setattr(RealConversationReplayService, "_call_agent", recording_agent)

    KnowledgeGapRetestService().retest_task("kgap_retest_1", verified_by="lead")

    assert called_turns == ["turn_gap_2"]


def test_knowledge_gap_retest_api_permissions_preview_and_apply(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _passing_agent)

    assert client.post(
        "/api/eval/knowledge-gaps/kgap_retest_1/retest",
        json={"apply": True},
        headers={"X-User-Role": "operator"},
    ).status_code == 403

    preview = client.post(
        "/api/eval/knowledge-gaps/kgap_retest_1/retest-preview",
        headers={"X-User-Role": "supervisor"},
    )
    assert preview.status_code == 200
    assert preview.get_json()["sample_count"] == 2
    db = session_factory()
    try:
        assert db.query(EvalRun).count() == 1
    finally:
        db.close()

    retest = client.post(
        "/api/eval/knowledge-gaps/kgap_retest_1/retest",
        json={"apply": True},
        headers={"X-User-Role": "admin", "X-User-Name": "lead"},
    )
    assert retest.status_code == 200
    data = retest.get_json()
    assert data["task"]["verification_status"] == "verified_passed"
    assert data["verification"]["verification_run_uid"]


def test_knowledge_gap_status_verified_cannot_be_set_directly(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)

    response = client.patch(
        "/api/eval/knowledge-gaps/kgap_retest_1/status",
        json={"status": "verified"},
        headers={"X-User-Role": "supervisor"},
    )

    assert response.status_code == 400
    assert "retest" in response.get_json()["error"]
