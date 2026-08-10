from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalRepairTask, EvalRun, EvalTrace
from app.services.real_conversation_repair_verification_service import RealConversationRepairVerificationService
from app.services.real_conversation_replay_service import RealConversationReplayService


def _make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_task(session_factory, related_turns=None):
    related_turns = related_turns or ["turn_buyer_1", "turn_buyer_2"]
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_verify_1", source_type="real_conversation", status="active")
        case.message = "first question"
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
                case_uid="case_verify_1",
                conversation_uid="conv_verify_1",
                turn_uid="turn_buyer_1",
                turn_index=0,
                speaker="buyer",
                sanitized_text="材质安全吗 phone 13812345678",
                reference_human_reply="first reference",
            ),
            EvalConversationTurn(
                case_uid="case_verify_1",
                conversation_uid="conv_verify_1",
                turn_uid="turn_service_1",
                turn_index=1,
                speaker="service",
                sanitized_text="first service",
            ),
            EvalConversationTurn(
                case_uid="case_verify_1",
                conversation_uid="conv_verify_1",
                turn_uid="turn_buyer_2",
                turn_index=2,
                speaker="buyer",
                sanitized_text="材质会不会受潮 order 123456789012345",
                reference_human_reply="second reference",
            ),
            EvalConversationTurn(
                case_uid="case_verify_1",
                conversation_uid="conv_verify_1",
                turn_uid="turn_buyer_unrelated",
                turn_index=3,
                speaker="buyer",
                sanitized_text="unrelated question",
            ),
        ])
        task = EvalRepairTask(
            task_uid="repair_verify_1",
            run_uid="original_run_1",
            case_uid="case_verify_1",
            turn_uid=related_turns[0],
            failure_type="rag_miss",
            suggested_fix_area="knowledge_rag",
            suggested_owner="knowledge_ops",
            status="resolved",
            priority="medium",
            sample_count=len(related_turns),
        )
        task.set_related_case_uids(["case_verify_1"])
        task.set_related_turn_uids(related_turns)
        db.add(task)
        db.commit()
    finally:
        db.close()


def _passing_agent(self, payload):
    return {
        "suggested_reply": "answer from current agent",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{"fact_type": "material", "content": "safe evidence"}],
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
        "suggested_reply": "needs review",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
        "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
        "final_answer_audit": {"passed": False},
    }


def test_repair_verification_dry_run_does_not_write(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)

    result = RealConversationRepairVerificationService().preview_task("repair_verify_1")

    assert result["dry_run"] is True
    assert result["checked_turn_uids"] == ["turn_buyer_1", "turn_buyer_2"]
    db = session_factory()
    try:
        task = db.query(EvalRepairTask).one()
        assert task.verification_status == "not_verified"
        assert db.query(EvalRun).count() == 0
        assert db.query(EvalTrace).count() == 0
    finally:
        db.close()


def test_repair_verification_passed_updates_task(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _passing_agent)

    result = RealConversationRepairVerificationService().verify_task("repair_verify_1", verified_by="lead")

    assert result["ok"] is True
    assert result["task"]["verification_status"] == "verified_passed"
    assert result["verification"]["passed_turns"] == 2
    db = session_factory()
    try:
        task = db.query(EvalRepairTask).one()
        assert task.status == "resolved"
        assert task.verification_status == "verified_passed"
        assert task.verification_run_uid.startswith("verify_")
        assert task.verified_by == "lead"
    finally:
        db.close()


def test_repair_verification_retest_failed_moves_task_to_in_progress(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _failing_agent)

    result = RealConversationRepairVerificationService().verify_task("repair_verify_1", verified_by="lead")

    assert result["task"]["verification_status"] == "retest_failed"
    assert "rag_miss" in result["verification"]["remaining_failure_types"]
    assert "needs_human_review" in result["verification"]["remaining_failure_types"]
    db = session_factory()
    try:
        task = db.query(EvalRepairTask).one()
        assert task.status == "in_progress"
        assert task.verification_status == "retest_failed"
    finally:
        db.close()


def test_repair_verification_error_records_sanitized_message(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)

    def boom(self, options=None):
        raise RuntimeError("failed for phone 13812345678 and order 123456789012345")

    monkeypatch.setattr(RealConversationReplayService, "replay_cases", boom)

    result = RealConversationRepairVerificationService().verify_task("repair_verify_1", verified_by="lead")

    assert result["ok"] is False
    raw = str(result)
    assert "13812345678" not in raw
    assert "123456789012345" not in raw
    db = session_factory()
    try:
        task = db.query(EvalRepairTask).one()
        assert task.verification_status == "error"
        assert "PHONE_REDACTED" in task.get_verification_summary()["error_message"]
    finally:
        db.close()


def test_repair_verification_only_replays_related_turns(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory, related_turns=["turn_buyer_2"])
    called_turns = []

    def recording_agent(self, payload):
        called_turns.append(payload["copilot_context"]["eval_turn_uid"])
        return _passing_agent(self, payload)

    monkeypatch.setattr(RealConversationReplayService, "_call_agent", recording_agent)

    RealConversationRepairVerificationService().verify_task("repair_verify_1", verified_by="lead")

    assert called_turns == ["turn_buyer_2"]


def test_repair_verification_api_permissions_dry_run_and_sanitized_output(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)

    set_admin_test_principal("operator")
    assert client.post(
        "/api/eval/repair-tasks/repair_verify_1/verify",
        json={"dry_run": True},
        headers={"X-User-Role": "supervisor"},
    ).status_code == 403

    set_admin_test_principal("supervisor")
    response = client.post(
        "/api/eval/repair-tasks/repair_verify_1/verify",
        json={"dry_run": True},
        headers={"X-User-Role": "operator"},
    )

    assert response.status_code == 200
    raw = response.get_data(as_text=True)
    assert "13812345678" not in raw
    assert response.get_json()["checked_turn_uids"] == ["turn_buyer_1", "turn_buyer_2"]


def test_repair_task_patch_resolved_can_trigger_verification(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_task(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _passing_agent)

    response = client.patch(
        "/api/eval/repair-tasks/repair_verify_1",
        json={"status": "resolved", "verify_after_resolve": True},
        headers={"X-User-Role": "admin", "X-User-Name": "lead"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["task"]["verification_status"] == "verified_passed"
    assert data["verification"]["passed_turns"] == 2
