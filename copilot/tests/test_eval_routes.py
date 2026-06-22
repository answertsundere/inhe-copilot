from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _isolated_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import EvalCase, EvalFailure, EvalRepairTask, EvalRun, EvalTrace  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


def _client(monkeypatch):
    _isolated_db(monkeypatch)
    from app.api.eval_routes import eval_bp

    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client()


def test_eval_case_api_sanitizes_response(monkeypatch):
    client = _client(monkeypatch)

    response = client.post("/api/eval/cases", json={
        "case_uid": "api_case",
        "customer_message": "订单9876543210123456，电话13812345678，有没有图？",
        "expected_behavior": {"must_have_fact_type": "visual_asset"},
    }, headers={"X-User-Role": "supervisor"})

    assert response.status_code == 201
    body = response.get_json()
    text = str(body)
    assert "9876543210123456" not in text
    assert "13812345678" not in text
    assert body["item"]["case_uid"] == "api_case"

    listed = client.get("/api/eval/cases", headers={"X-User-Role": "supervisor"}).get_json()
    assert listed["items"][0]["case_uid"] == "api_case"
    assert "9876543210123456" not in str(listed)


def test_eval_runs_api_dry_run_does_not_require_real_agent(monkeypatch):
    client = _client(monkeypatch)
    client.post("/api/eval/cases", json={
        "case_uid": "api_case_dry",
        "customer_message": "尺寸多大？",
        "category": "agent_phase",
    }, headers={"X-User-Role": "supervisor"})

    response = client.post(
        "/api/eval/runs",
        json={"limit": 5, "category": "agent_phase", "apply": False},
        headers={"X-User-Role": "supervisor"},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "dry_run"
    assert body["total_cases"] == 1
