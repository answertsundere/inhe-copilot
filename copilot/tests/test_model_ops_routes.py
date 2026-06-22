import json

from flask import Flask
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


def _client(monkeypatch):
    _isolated_db(monkeypatch)
    from app.api.model_ops_routes import model_ops_bp

    app = Flask(__name__)
    app.register_blueprint(model_ops_bp)
    return app.test_client()


def _seed_calls():
    from app.services.model_call_ledger_service import record_model_call

    record_model_call(
        trace_id="trace-1",
        conversation_id="conv-1",
        request_id="req-1",
        node_name="node_a",
        alias="fast_model",
        provider="test_provider",
        model="cheap-test",
        api_base="https://api.example/v1?token=secret",
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        latency_ms=100,
        status="success",
        metadata={
            "safe": "ok",
            "prompt": "full prompt should not be returned",
            "messages": [{"role": "user", "content": "private"}],
            "image_url": "https://oss.example/private.png?signature=secret",
            "base64": "SECRET",
            "api_key": "secret-key",
        },
    )
    record_model_call(
        trace_id="trace-2",
        conversation_id="conv-2",
        request_id="req-2",
        node_name="node_b",
        alias="judge_model",
        provider="unknown_provider",
        model="unknown-model",
        api_base="https://judge.example/v1",
        total_tokens=7,
        latency_ms=300,
        status="error",
        error_type="RuntimeError",
        metadata={"safe": "err"},
    )


def test_calls_api_returns_safe_metadata_and_filters(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    resp = client.get(
        "/api/model-ops/calls?alias=fast_model&status=success&node_name=node_a",
        headers={"X-User-Role": "supervisor"},
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["limit"] == 50
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["alias"] == "fast_model"
    assert item["api_base_host"] == "api.example"
    assert "api_base" not in item
    metadata = item["metadata_json"]
    assert item["metadata"] == metadata
    assert metadata["safe"] == "ok"
    assert "prompt" not in metadata
    assert "messages" not in metadata
    assert "image_url" not in metadata
    assert "base64" not in metadata
    assert "api_key" not in metadata
    assert "secret" not in json.dumps(data, ensure_ascii=False)


def test_summary_api_aggregates(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    resp = client.get("/api/model-ops/summary", headers={"X-User-Role": "supervisor"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["total_calls"] == 2
    assert data["success_calls"] == 1
    assert data["error_calls"] == 1
    assert data["total_tokens"] == 1507
    assert data["total_estimated_cost"] == 0.002
    assert data["by_alias"] == {"fast_model": 1, "judge_model": 1}
    assert data["by_node"] == {"node_a": 1, "node_b": 1}
    assert data["by_status"] == {"success": 1, "error": 1}
    assert data["avg_latency_ms"] == 200
    assert data["cost_unknown_count"] == 1


def test_limit_is_capped_and_status_filter_works(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    resp = client.get("/api/model-ops/calls?limit=999&status=error", headers={"X-User-Role": "supervisor"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["limit"] == 200
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "error"


def test_trace_and_conversation_filters_work(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    resp = client.get(
        "/api/model-ops/calls?trace_id=trace-2&conversation_id=conv-2",
        headers={"X-User-Role": "supervisor"},
    )
    assert resp.status_code == 200
    data = resp.get_json()

    assert len(data["items"]) == 1
    assert data["items"][0]["trace_id"] == "trace-2"
    assert data["items"][0]["conversation_id"] == "conv-2"
