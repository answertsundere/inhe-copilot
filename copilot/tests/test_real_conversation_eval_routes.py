from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import EvalFailure, EvalReview, EvalRun, EvalTrace


def _make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_run(session_factory):
    db = session_factory()
    try:
        run = EvalRun(run_uid="real_run_api", source_type="real_conversation", status="completed")
        run.total_cases = 1
        run.total_turns = 1
        db.add(run)
        trace = EvalTrace(
            run_uid="real_run_api",
            case_uid="case_api",
            turn_uid="turn_api",
            turn_index=0,
            buyer_message="手机号[PHONE_REDACTED]，这个怎么安装？",
            reference_human_reply="看说明书",
            agent_reply="按说明书安装",
            query_fact_type="installation",
            latency_ms=12,
        )
        trace.set_selected_evidence([{"content": "安装说明", "url": "https://demo.oss-cn/a.jpg/[SIGNED_URL_REDACTED:abc]"}])
        trace.set_rejected_evidence([])
        trace.set_answer_trace({"query_fact_type": "installation"})
        trace.set_turn_understanding({
            "turn_actionability": "actionable_question",
            "needs_rag": True,
            "should_score": True,
            "reply_strategy": "normal_agent",
        })
        trace.set_final_audit({"passed": True})
        trace.set_semantic_compiler({"blocks": 1})
        db.add(trace)
        failure = EvalFailure(
            run_uid="real_run_api",
            case_uid="case_api",
            turn_uid="turn_api",
            failure_type="needs_human_review",
            severity="medium",
            suggested_fix_area="human_policy_risk_boundary",
            suggested_owner="customer_service_lead",
            explanation="agent requested human review",
            message="needs review",
        )
        db.add(failure)
        review = EvalReview(
            run_uid="real_run_api",
            case_uid="case_api",
            turn_uid="turn_api",
            decision="needs_knowledge",
            suggested_fix_area="knowledge_rag",
            reason="need a sanitized knowledge note",
            reviewer="qa",
        )
        db.add(review)
        db.commit()
    finally:
        db.close()


def test_real_conversation_eval_routes_require_supervisor(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    assert client.get("/api/eval/real-conversation/runs").status_code == 403
    assert client.get("/api/eval/real-conversation/runs", headers={"X-User-Role": "operator"}).status_code == 403
    assert client.get("/api/eval/real-conversation/runs", headers={"X-User-Role": "supervisor"}).status_code == 200
    assert client.get("/api/eval/real-conversation/runs", headers={"X-User-Role": "admin"}).status_code == 200


def test_real_conversation_eval_run_detail_is_sanitized(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    response = client.get(
        "/api/eval/real-conversation/runs/real_run_api",
        headers={"X-User-Role": "supervisor"},
    )

    assert response.status_code == 200
    raw = response.get_data(as_text=True)
    assert "13812345678" not in raw
    assert "Signature=" not in raw
    data = response.get_json()
    assert data["run"]["run_uid"] == "real_run_api"
    assert data["turns"][0]["query_fact_type"] == "installation"
    assert data["turns"][0]["quality_bucket"] == "safe_handoff"
    assert data["turns"][0]["is_safe_handoff"] is True
    assert data["turns"][0]["turn_understanding"]["turn_actionability"] == "actionable_question"
    assert data["turns"][0]["turn_understanding"]["needs_rag"] is True
    assert data["failures"][0]["failure_type"] == "needs_human_review"
    assert data["failures"][0]["suggested_fix_area"] == "human_policy_risk_boundary"
    assert data["failures"][0]["suggested_owner"] == "customer_service_lead"
    assert data["failures"][0]["explanation"]
    assert data["summary"]["failure_counts_by_type"]["needs_human_review"] == 1
    assert data["summary"]["review_counts_by_decision"]["needs_knowledge"] == 1
    assert data["summary"]["avg_latency_ms"] == 12
    assert data["summary"]["requires_review_count"] == 0
    assert data["summary"]["pass_rate"] == 1
    assert data["summary"]["safe_handoff_turns"] == 1
    assert data["summary"]["quality_denominator"] == 1
    assert data["summary"]["agent_error_turns"] == 0


def test_real_conversation_review_writes_only_review(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    response = client.post(
        "/api/eval/real-conversation/reviews",
        json={
            "run_uid": "real_run_api",
            "case_uid": "case_api",
            "turn_uid": "turn_api",
            "decision": "needs_knowledge",
            "reason": "手机号13812345678不应出现",
        },
        headers={"X-User-Role": "admin", "X-User-Name": "qa"},
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["review"]["decision"] == "needs_knowledge"
    assert data["review"]["suggested_fix_area"] == "knowledge_rag"
    assert "13812345678" not in data["review"]["reason"]


def test_real_conversation_review_operator_forbidden(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    response = client.post(
        "/api/eval/real-conversation/reviews",
        json={
            "run_uid": "real_run_api",
            "case_uid": "case_api",
            "turn_uid": "turn_api",
            "decision": "correct",
        },
        headers={"X-User-Role": "operator"},
    )

    assert response.status_code == 403


def test_real_conversation_review_rejects_legacy_needs_review(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    response = client.post(
        "/api/eval/real-conversation/reviews",
        json={
            "run_uid": "real_run_api",
            "case_uid": "case_api",
            "turn_uid": "turn_api",
            "decision": "needs_review",
        },
        headers={"X-User-Role": "supervisor"},
    )

    assert response.status_code == 400
