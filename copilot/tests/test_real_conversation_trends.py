import json
from datetime import datetime, timedelta

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import EvalFailure, EvalRepairTask, EvalRun


def _make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_trends(session_factory):
    db = session_factory()
    try:
        now = datetime.utcnow()
        run_a = EvalRun(run_uid="trend_run_a", source_type="real_conversation", status="completed")
        run_a.total_turns = 10
        run_a.passed_turns = 7
        run_a.failed_turns = 3
        run_a.created_at = now - timedelta(days=1)
        run_a.set_metadata({
            "daily_schedule": {
                "schedule_uid": "daily_a",
                "status": "completed",
                "total_turns": 10,
                "failed_turns": 3,
                "pass_rate": 0.7,
                "error_message": "phone 13812345678 should be redacted",
            }
        })
        run_b = EvalRun(run_uid="trend_run_b", source_type="real_conversation", status="completed")
        run_b.total_turns = 4
        run_b.passed_turns = 4
        run_b.failed_turns = 0
        run_b.created_at = now
        run_b.set_metadata({"daily_schedule": {"schedule_uid": "daily_b", "status": "completed"}})
        db.add_all([run_a, run_b])
        db.add_all([
            EvalFailure(
                run_uid="trend_run_a",
                case_uid="case_a",
                turn_uid="turn_a",
                failure_type="rag_miss",
                severity="medium",
                suggested_fix_area="knowledge_rag",
                suggested_owner="knowledge_ops",
                message="missing phone 13812345678 order 123456789012345",
            ),
            EvalFailure(
                run_uid="trend_run_a",
                case_uid="case_b",
                turn_uid="turn_b",
                failure_type="semantic_mismatch",
                severity="high",
                suggested_fix_area="final_audit_semantic_compiler",
                suggested_owner="agent_quality",
                message="signed url https://demo/a.jpg?Signature=secret",
            ),
        ])
        task = EvalRepairTask(
            task_uid="repair_trend_a",
            run_uid="trend_run_a",
            case_uid="case_a",
            turn_uid="turn_a",
            failure_type="rag_miss",
            suggested_fix_area="knowledge_rag",
            suggested_owner="knowledge_ops",
            status="open",
            priority="medium",
            sample_count=1,
        )
        task.set_related_case_uids(["case_a"])
        task.set_related_turn_uids(["turn_a"])
        db.add(task)
        db.commit()
    finally:
        db.close()


def test_trends_api_returns_aggregates_without_private_text(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_trends(session_factory)

    response = client.get("/api/eval/trends?days=7", headers={"X-User-Role": "supervisor"})

    assert response.status_code == 200
    raw = response.get_data(as_text=True)
    assert "13812345678" not in raw
    assert "123456789012345" not in raw
    assert "Signature=secret" not in raw
    data = response.get_json()
    assert data["failure_type_counts"]["rag_miss"] == 1
    assert data["failure_type_counts"]["semantic_mismatch"] == 1
    assert data["suggested_fix_area_counts"]["knowledge_rag"] == 1
    assert data["suggested_owner_counts"]["knowledge_ops"] == 1
    assert data["repair_task_status_counts"]["open"] == 1
    assert data["top_failure_types"][0]["count"] == 1
    assert len(data["daily"]) == 7
    assert data["latest_daily_replay"]["schedule_uid"] == "daily_b"


def test_trends_api_filters_and_rejects_operator(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_trends(session_factory)

    assert client.get("/api/eval/trends", headers={"X-User-Role": "operator"}).status_code == 403
    response = client.get(
        "/api/eval/trends?days=7&suggested_fix_area=knowledge_rag",
        headers={"X-User-Role": "admin"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["failure_type_counts"] == {"rag_miss": 1}
    assert json.dumps(data, ensure_ascii=False).count("semantic_mismatch") == 0
