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


def _executor_with_handlers():
    from app.agent.tools.base import ToolSpec
    from app.agent.tools.registry import ToolRegistry
    from app.agent.tools.executor import ToolExecutor

    registry = ToolRegistry()
    calls = []

    def handler(inputs, state):
        calls.append(inputs.get("tool_marker", "called"))
        return {"found": True, "count": 1}

    for name in [
        "jst_lookup_order_tool",
        "rag_search_tool",
        "media_asset_recommend_tool",
        "product_resolver_tool",
    ]:
        registry.register(ToolSpec(name=name, description=name, handler=handler))
    return ToolExecutor(registry), calls


def test_product_question_blocks_order_tool_and_allows_rag(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    executor, calls = _executor_with_handlers()

    result = executor.execute_plan(
        [
            {"tool_name": "jst_lookup_order_tool", "inputs": {"tool_marker": "jst"}},
            {"tool_name": "rag_search_tool", "inputs": {"tool_marker": "rag", "query": "材质"}},
        ],
        {
            "intent": "product_question",
            "query_fact_type": "material",
            "product_entities": [{"sku_code": "SKU-1"}],
            "slots": {"order_id": "9876543210123456"},
        },
    )

    assert calls == ["rag"]
    assert result["tool_results"]["jst_lookup_order_tool"]["blocked"] is True
    trace = result["tool_policy_trace"]
    assert "rag_search_tool" in trace["allowed_tools"]
    assert trace["blocked_tools"][0]["tool_name"] == "jst_lookup_order_tool"

    from app.models.tool_call_log import ToolCallLog

    db = session_factory()
    try:
        rows = db.query(ToolCallLog).order_by(ToolCallLog.id).all()
        assert [row.status for row in rows] == ["blocked", "success"]
    finally:
        db.close()


def test_logistics_question_allows_order_tool_and_blocks_media_without_fact_type(monkeypatch):
    _isolated_db(monkeypatch)
    executor, calls = _executor_with_handlers()

    result = executor.execute_plan(
        [
            {"tool_name": "jst_lookup_order_tool", "inputs": {"tool_marker": "jst"}},
            {"tool_name": "media_asset_recommend_tool", "inputs": {"tool_marker": "media"}},
        ],
        {
            "intent": "logistics_trace",
            "query_fact_type": "logistics",
            "slots": {"order_id": "9876543210123456"},
        },
    )

    assert calls == ["jst"]
    trace = result["tool_policy_trace"]
    assert "jst_lookup_order_tool" in trace["allowed_tools"]
    assert trace["blocked_tools"][0]["tool_name"] == "media_asset_recommend_tool"


def test_image_question_allows_media_not_order(monkeypatch):
    _isolated_db(monkeypatch)
    executor, calls = _executor_with_handlers()

    result = executor.execute_plan(
        [
            {"tool_name": "media_asset_recommend_tool", "inputs": {"tool_marker": "media"}},
            {"tool_name": "jst_lookup_order_tool", "inputs": {"tool_marker": "jst"}},
        ],
        {
            "intent": "product_question",
            "query_fact_type": "visual_asset",
            "product_entities": [{"sku_code": "SKU-1"}],
            "slots": {"order_id": "9876543210123456"},
        },
    )

    assert calls == ["media"]
    assert "media_asset_recommend_tool" in result["tool_policy_trace"]["allowed_tools"]
    assert result["tool_policy_trace"]["blocked_tools"][0]["tool_name"] == "jst_lookup_order_tool"


def test_api_helper_attaches_empty_tool_policy_trace():
    from app.api.analyze_routes import _attach_tool_policy_trace

    response = {"suggested_reply": "ok"}
    _attach_tool_policy_trace(response)

    trace = response["evidence_debug"]["tool_policy_trace"]
    assert trace["evaluated_tools"] == []
    assert trace["tool_call_count"] == 0
    assert trace["high_risk_tool_called"] is False
