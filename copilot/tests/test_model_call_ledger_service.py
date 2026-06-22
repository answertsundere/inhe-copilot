import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _isolated_db(monkeypatch):
    import app.db as db_module
    import app.services.model_call_ledger_service as ledger
    from app.models.model_call_log import ModelCallLog  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(ledger, "_TABLE_READY", False)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


def test_record_model_call_sanitizes_key_and_url(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    from app.models.model_call_log import ModelCallLog
    from app.services.model_call_ledger_service import record_model_call

    result = record_model_call(
        trace_id="t1",
        conversation_id="c1",
        request_id="r1",
        node_name="judge",
        alias="judge_model",
        provider="test_provider",
        model="judge-test",
        api_base="https://api.example/v1?token=secret",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=123,
        status="success",
        metadata={"api_key": "secret-key", "safe": "ok"},
    )

    assert result["ledger_recorded"] is True
    db = session_factory()
    try:
        row = db.query(ModelCallLog).one()
        assert row.alias == "judge_model"
        assert row.api_base_host == "api.example"
        assert row.prompt_tokens == 10
        assert row.completion_tokens == 5
        assert row.total_tokens == 15
        metadata = json.loads(row.metadata_json)
        assert metadata["safe"] == "ok"
        assert "api_key" not in metadata
        assert "secret-key" not in row.metadata_json
    finally:
        db.close()


def test_unknown_cost_does_not_fail(monkeypatch):
    _isolated_db(monkeypatch)
    from app.services.model_call_ledger_service import estimate_cost, record_model_call

    estimate = estimate_cost("unknown_provider", "unknown_model", 1, 2)
    assert estimate["estimated_cost"] == 0.0
    assert estimate["cost_unknown"] is True

    result = record_model_call(alias="fast_model", provider="unknown", model="m", status="success")
    assert result["ledger_recorded"] is True
    assert result["cost_unknown"] is True
