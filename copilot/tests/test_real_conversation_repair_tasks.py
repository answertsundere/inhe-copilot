from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import EvalFailure, EvalRepairTask, EvalReview, EvalRun, EvalTrace
from app.services.real_conversation_repair_task_service import RealConversationRepairTaskService


def _make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_repair_task_run(session_factory):
    db = session_factory()
    try:
        run = EvalRun(run_uid="repair_run_1", source_type="real_conversation", status="completed")
        run.total_cases = 3
        run.total_turns = 4
        db.add(run)
        for index, turn_uid in enumerate(["turn_a", "turn_b", "turn_agent", "turn_correct"]):
            trace = EvalTrace(
                run_uid="repair_run_1",
                case_uid=f"case_{index}",
                turn_uid=turn_uid,
                turn_index=index,
                buyer_message=f"phone 13812345678 asks turn {index}",
                reference_human_reply="reference reply",
                agent_reply="agent reply",
                query_fact_type="material",
                latency_ms=10 + index,
                passed=False,
            )
            trace.set_selected_evidence([{
                "content": "material evidence",
                "url": "https://demo.oss-cn/a.jpg?Signature=secret&Expires=999",
            }])
            trace.set_answer_trace({"query_fact_type": "material"})
            db.add(trace)

        db.add_all([
            EvalFailure(
                run_uid="repair_run_1",
                case_uid="case_0",
                turn_uid="turn_a",
                failure_type="rag_miss",
                severity="medium",
                suggested_fix_area="knowledge_rag",
                suggested_owner="knowledge_ops",
                message="missing knowledge for 13812345678",
            ),
            EvalFailure(
                run_uid="repair_run_1",
                case_uid="case_1",
                turn_uid="turn_b",
                failure_type="rag_miss",
                severity="high",
                suggested_fix_area="knowledge_rag",
                suggested_owner="knowledge_ops",
                message="second missing knowledge",
            ),
            EvalFailure(
                run_uid="repair_run_1",
                case_uid="case_2",
                turn_uid="turn_agent",
                failure_type="semantic_mismatch",
                severity="high",
                suggested_fix_area="final_audit_semantic_compiler",
                suggested_owner="agent_quality",
                message="agent answer mismatched buyer intent",
            ),
            EvalFailure(
                run_uid="repair_run_1",
                case_uid="case_3",
                turn_uid="turn_correct",
                failure_type="semantic_mismatch",
                severity="high",
                suggested_fix_area="final_audit_semantic_compiler",
                suggested_owner="agent_quality",
                message="review marked correct",
            ),
        ])
        db.add_all([
            EvalReview(
                run_uid="repair_run_1",
                case_uid="case_0",
                turn_uid="turn_a",
                decision="needs_knowledge",
                suggested_fix_area="knowledge_rag",
                reviewer="qa",
            ),
            EvalReview(
                run_uid="repair_run_1",
                case_uid="case_3",
                turn_uid="turn_correct",
                decision="correct",
                suggested_fix_area="",
                reviewer="qa",
            ),
        ])
        db.commit()
    finally:
        db.close()


def test_repair_task_generation_groups_failures_and_skips_correct_review(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_repair_task_run(session_factory)
    db = session_factory()
    try:
        result = RealConversationRepairTaskService().generate_for_run(db, "repair_run_1", created_by="lead")
        assert result.generated == 1
        assert result.updated == 0
        assert result.skipped_correct == 1

        task = db.query(EvalRepairTask).one()
        assert task.failure_type == "semantic_mismatch"
        assert task.suggested_fix_area == "final_audit_semantic_compiler"
        assert task.suggested_owner == "agent_quality"
        assert task.sample_count == 1
        assert task.priority == "high"
        assert sorted(task.get_related_turn_uids()) == ["turn_agent"]
        assert "turn_a" not in task.get_related_turn_uids()
        assert "turn_b" not in task.get_related_turn_uids()
        assert "turn_correct" not in task.get_related_turn_uids()
    finally:
        db.close()


def test_repair_task_generation_updates_existing_task_instead_of_duplicating(monkeypatch):
    _, session_factory = _make_client(monkeypatch)
    _seed_repair_task_run(session_factory)
    db = session_factory()
    try:
        first = RealConversationRepairTaskService().generate_for_run(db, "repair_run_1", created_by="lead")
        second = RealConversationRepairTaskService().generate_for_run(db, "repair_run_1", created_by="lead")
        assert first.generated == 1
        assert second.generated == 0
        assert second.updated == 1
        assert db.query(EvalRepairTask).count() == 1
        assert db.query(EvalRepairTask).one().sample_count == 1
    finally:
        db.close()


def test_repair_task_routes_list_detail_generate_update_and_sanitize(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_repair_task_run(session_factory)

    generate_response = client.post(
        "/api/eval/repair-tasks/generate",
        json={"run_uid": "repair_run_1"},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert generate_response.status_code == 201
    generated = generate_response.get_json()
    task_uid = generated["tasks"][0]["task_uid"]

    list_response = client.get(
        "/api/eval/repair-tasks?suggested_fix_area=final_audit_semantic_compiler&status=open",
        headers={"X-User-Role": "supervisor"},
    )
    assert list_response.status_code == 200
    assert list_response.get_json()["items"][0]["sample_count"] == 1

    detail_response = client.get(
        f"/api/eval/repair-tasks/{task_uid}",
        headers={"X-User-Role": "admin"},
    )
    assert detail_response.status_code == 200
    raw_detail = detail_response.get_data(as_text=True)
    assert "13812345678" not in raw_detail
    assert "Signature=secret" not in raw_detail
    detail = detail_response.get_json()
    assert detail["task"]["task_uid"] == task_uid
    assert len(detail["traces"]) == 1
    assert len(detail["failures"]) == 1

    update_response = client.patch(
        f"/api/eval/repair-tasks/{task_uid}",
        json={
            "status": "in_progress",
            "priority": "high",
            "assigned_to": "knowledge_lead",
            "resolution_note": "call 13812345678 after fixing",
        },
        headers={"X-User-Role": "supervisor"},
    )
    assert update_response.status_code == 200
    update_raw = update_response.get_data(as_text=True)
    assert "13812345678" not in update_raw
    updated = update_response.get_json()["task"]
    assert updated["status"] == "in_progress"
    assert updated["assigned_to"] == "knowledge_lead"


def test_repair_task_routes_reject_operator(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    _seed_repair_task_run(session_factory)

    set_admin_test_principal("operator")
    assert client.get("/api/eval/repair-tasks", headers={"X-User-Role": "operator"}).status_code == 403
    assert client.post(
        "/api/eval/repair-tasks/generate",
        json={"run_uid": "repair_run_1"},
        headers={"X-User-Role": "operator"},
    ).status_code == 403
