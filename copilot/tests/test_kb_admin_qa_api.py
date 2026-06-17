from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_client(monkeypatch, tmp_path):
    import app.db as db_module
    from app.api.kb_admin_routes import kb_admin_bp
    from app.models.kb_tables import KBQA  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'kb_admin_qa.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    app = Flask(__name__)
    app.register_blueprint(kb_admin_bp, url_prefix="/api/kb")
    return app.test_client(), session_factory


def _create_qa(session_factory, **overrides):
    from app.models.kb_tables import KBQA

    db = session_factory()
    try:
        qa = KBQA(
            question=overrides.pop("question", "客户一直骂人怎么办？"),
            answer=overrides.pop("answer", "先安抚客户情绪，再转人工处理。"),
            intent=overrides.pop("intent", "特殊场景"),
            risk_level=overrides.pop("risk_level", "low"),
            human_review=overrides.pop("human_review", False),
            auto_reply=overrides.pop("auto_reply", True),
            status=overrides.pop("status", "draft"),
            **overrides,
        )
        db.add(qa)
        db.commit()
        db.refresh(qa)
        return qa.id
    finally:
        db.close()


def test_update_qa_allows_medium_without_human_review(monkeypatch, tmp_path):
    client, session_factory = _make_client(monkeypatch, tmp_path)
    qa_id = _create_qa(session_factory)

    response = client.put(
        f"/api/kb/qa/{qa_id}",
        json={"risk_level": "medium", "human_review": False, "auto_reply": False},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["risk_level"] == "medium"
    assert body["human_review"] is False


def test_update_qa_persists_scenario_fields(monkeypatch, tmp_path):
    client, session_factory = _make_client(monkeypatch, tmp_path)
    qa_id = _create_qa(session_factory)

    response = client.put(
        f"/api/kb/qa/{qa_id}",
        json={
            "scenario_category": "特殊场景",
            "issue_type": "辱骂安抚",
            "risk_level": "medium",
            "human_review": True,
            "auto_reply": False,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["scenario_category"] == "特殊场景"
    assert body["issue_type"] == "辱骂安抚"

    get_response = client.get(f"/api/kb/qa/{qa_id}")
    assert get_response.status_code == 200
    get_body = get_response.get_json()
    assert get_body["scenario_category"] == "特殊场景"
    assert get_body["issue_type"] == "辱骂安抚"
