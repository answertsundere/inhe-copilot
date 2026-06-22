import json

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _isolated_db(monkeypatch):
    import app.db as db_module
    import app.services.tool_call_ledger_service as ledger
    from app.models.tool_call_log import ToolCallLog  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(ledger, "_TABLE_READY", False)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


def _client(monkeypatch):
    _isolated_db(monkeypatch)
    from app.api.tool_ops_routes import tool_ops_bp

    app = Flask(__name__)
    app.register_blueprint(tool_ops_bp)
    return app.test_client()


def _seed_calls():
    from app.services.tool_call_ledger_service import record_tool_call

    record_tool_call(
        trace_id="trace-1",
        conversation_id="conv-1",
        request_id="req-1",
        node_name="tool_executor",
        tool_name="jst_lookup_order_tool",
        tool_risk_level="read_only_sensitive",
        intent="logistics_trace",
        query_fact_type="logistics",
        allowed=True,
        status="success",
        latency_ms=100,
        input_summary={
            "order_id": "9876543210123456",
            "phone": "13812345678",
            "image_url": "https://oss.example/a.png?signature=SECRET",
            "token": "SECRET",
        },
        output_summary={"endpoint": "https://api.example/orders?token=SECRET", "safe": "ok"},
    )
    record_tool_call(
        trace_id="trace-2",
        conversation_id="conv-2",
        request_id="req-2",
        node_name="tool_executor",
        tool_name="rag_search_tool",
        tool_risk_level="read_only_low_risk",
        intent="product_question",
        query_fact_type="material",
        allowed=False,
        blocked_reason="intent_not_allowed",
        status="blocked",
        latency_ms=300,
    )


def test_tool_ops_blocks_operator(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get("/api/tool-ops/calls", headers={"X-User-Role": "operator"})

    assert response.status_code == 403


def test_tool_ops_calls_are_sanitized_and_filterable(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get(
        "/api/tool-ops/calls?tool_name=jst_lookup_order_tool&allowed=true",
        headers={"X-User-Role": "supervisor"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["tool_name"] == "jst_lookup_order_tool"
    assert item["allowed"] is True
    rendered = json.dumps(data, ensure_ascii=False)
    assert "9876543210123456" not in rendered
    assert "13812345678" not in rendered
    assert "signature=SECRET" not in rendered
    assert "token" not in rendered.lower()
    assert item["output_summary"]["safe"] == "ok"


def test_tool_ops_summary_aggregates(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get("/api/tool-ops/summary", headers={"X-User-Role": "supervisor"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["total_calls"] == 2
    assert data["allowed_calls"] == 1
    assert data["blocked_calls"] == 1
    assert data["error_calls"] == 0
    assert data["high_risk_calls"] == 1
    assert data["by_tool"] == {"jst_lookup_order_tool": 1, "rag_search_tool": 1}
    assert data["by_status"] == {"success": 1, "blocked": 1}
    assert data["avg_latency_ms"] == 200
