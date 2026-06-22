import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _isolated_db(monkeypatch):
    import app.db as db_module
    import app.services.tool_call_ledger_service as ledger
    from app.models.tool_call_log import ToolCallLog  # noqa: F401

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


def test_record_tool_call_success_error_and_blocked(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    from app.models.tool_call_log import ToolCallLog
    from app.services.tool_call_ledger_service import record_tool_call

    for status, allowed, reason in [
        ("success", True, ""),
        ("error", True, ""),
        ("blocked", False, "intent_not_allowed"),
    ]:
        result = record_tool_call(
            tool_name="rag_search_tool",
            tool_risk_level="read_only_low_risk",
            intent="product_question",
            query_fact_type="material",
            allowed=allowed,
            blocked_reason=reason,
            status=status,
            error_type="ValueError" if status == "error" else "",
        )
        assert result["ledger_recorded"] is True

    db = session_factory()
    try:
        rows = db.query(ToolCallLog).order_by(ToolCallLog.id).all()
        assert [row.status for row in rows] == ["success", "error", "blocked"]
        assert rows[2].allowed is False
        assert rows[2].blocked_reason == "intent_not_allowed"
    finally:
        db.close()


def test_tool_call_ledger_sanitizes_sensitive_summaries(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    from app.models.tool_call_log import ToolCallLog
    from app.services.tool_call_ledger_service import record_tool_call

    result = record_tool_call(
        trace_id="trace-1",
        conversation_id="conv-1",
        request_id="req-1",
        tool_name="jst_lookup_order_tool",
        tool_risk_level="read_only_sensitive",
        intent="logistics_trace",
        query_fact_type="logistics",
        allowed=True,
        status="success",
        input_summary={
            "message": "客户完整原文不能入库",
            "order_id": "9876543210123456",
            "token": "secret-token",
            "image_url": "https://oss.example/private.png?signature=SECRET",
        },
        output_summary={
            "endpoint": "https://api.example/orders?token=SECRET",
            "tracking_no": "1234567890123",
            "safe": "ok",
        },
        entity_summary={"order_id": "9876543210123456", "phone": "13800000000"},
    )

    assert result["ledger_recorded"] is True
    db = session_factory()
    try:
        row = db.query(ToolCallLog).one()
        combined = "\n".join([
            row.input_summary_json,
            row.output_summary_json,
            row.entity_summary_json,
        ])
        assert "客户完整原文不能入库" not in combined
        assert "secret-token" not in combined
        assert "signature=SECRET" not in combined
        assert "9876543210123456" not in combined
        assert "***3456#" in combined
        assert "13800000000" not in combined
        assert "url_host:api.example" in combined
        assert json.loads(row.output_summary_json)["safe"] == "ok"
    finally:
        db.close()
