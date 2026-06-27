from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import EvalFailure, EvalRun, EvalTrace, KnowledgeGapTask


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
        db.add(EvalRun(run_uid="kgap_route_run", source_type="real_conversation", status="completed"))
        trace = EvalTrace(
            run_uid="kgap_route_run",
            case_uid="case_route",
            turn_uid="turn_route",
            turn_index=1,
            buyer_message="手机号 13812345678，要安装视频",
            reference_human_reply="人工参考",
            agent_reply="Agent 回复 https://demo.oss-cn/a.jpg?Signature=secret&Expires=999",
            query_fact_type="installation",
            passed=False,
            requires_human_review=True,
        )
        trace.set_product_identity({"display_product_name": "收纳柜", "sku_code": "SKU-ROUTE"})
        trace.set_selected_evidence([])
        db.add(trace)
        db.add(EvalFailure(
            run_uid="kgap_route_run",
            case_uid="case_route",
            turn_uid="turn_route",
            failure_type="unsupported_media_claim",
            severity="high",
            suggested_fix_area="media_pipeline",
            suggested_owner="media_ops",
            message="video promise for 13812345678",
        ))
        db.commit()
    finally:
        db.close()


def test_knowledge_gap_routes_operator_read_and_supervisor_generate(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    assert client.get("/api/eval/knowledge-gaps", headers={"X-User-Role": "operator"}).status_code == 200
    forbidden = client.post(
        "/api/eval/knowledge-gaps/generate",
        json={"run_uid": "kgap_route_run"},
        headers={"X-User-Role": "operator"},
    )
    assert forbidden.status_code == 403

    generated = client.post(
        "/api/eval/knowledge-gaps/generate",
        json={"run_uid": "kgap_route_run"},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert generated.status_code == 201
    data = generated.get_json()
    task_uid = data["tasks"][0]["task_uid"]
    assert data["tasks"][0]["gap_type"] == "media_asset_gap"
    assert data["tasks"][0]["gap_category"] == "media_asset_gap"
    assert data["tasks"][0]["required_evidence_type"] == "installation_video"
    assert data["tasks"][0]["target_system"] == "kb_media_asset"

    filtered = client.get(
        "/api/eval/knowledge-gaps?gap_category=media_asset_gap&required_evidence_type=installation_video&target_system=kb_media_asset",
        headers={"X-User-Role": "operator"},
    )
    assert filtered.status_code == 200
    assert len(filtered.get_json()["items"]) == 1

    detail = client.get(f"/api/eval/knowledge-gaps/{task_uid}", headers={"X-User-Role": "operator"})
    assert detail.status_code == 200
    raw = detail.get_data(as_text=True)
    assert "13812345678" not in raw
    assert "Signature=secret" not in raw

    draft = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft",
        headers={"X-User-Role": "admin", "X-User-Name": "qa"},
    )
    assert draft.status_code == 201
    assert draft.get_json()["draft"]["review_status"] == "pending_review"
    assert draft.get_json()["draft"]["publish_target"] == "staging"


def test_knowledge_gap_routes_update_approve_reject_verify(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)
    generated = client.post(
        "/api/eval/knowledge-gaps/generate",
        json={"run_uid": "kgap_route_run"},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    task_uid = generated.get_json()["tasks"][0]["task_uid"]

    update = client.patch(
        f"/api/eval/knowledge-gaps/{task_uid}",
        json={"priority": "high", "suggested_owner": "media_lead"},
        headers={"X-User-Role": "supervisor"},
    )
    assert update.status_code == 200
    assert update.get_json()["task"]["suggested_owner"] == "media_lead"

    client.post(f"/api/eval/knowledge-gaps/{task_uid}/draft", headers={"X-User-Role": "supervisor"})
    approve = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/approve",
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert approve.status_code == 200
    assert approve.get_json()["task"]["status"] == "approved"

    verify = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/verify",
        headers={"X-User-Role": "admin", "X-User-Name": "lead"},
    )
    assert verify.status_code == 200
    verified_task = verify.get_json()["task"]
    assert verified_task["status"] == "verified"
    assert verified_task["metadata"]["verification"]["verification_mode"] == "manual_staging_check"

    db = session_factory()
    try:
        assert db.query(KnowledgeGapTask).one().status == "verified"
    finally:
        db.close()
