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


def test_eval_case_creation_sanitizes_private_fields(monkeypatch):
    _isolated_db(monkeypatch)
    from app.services.eval_replay_service import EvalReplayService

    item = EvalReplayService().create_case({
        "case_uid": "case_private",
        "customer_message": "订单9876543210123456，电话13812345678，尺寸多大？",
        "category": "agent_phase",
        "expected_behavior": {"must_have_fact_type": "dimensions"},
    })

    assert item["case_uid"] == "case_private"
    assert "9876543210123456" not in item["customer_message_sanitized"]
    assert "13812345678" not in item["customer_message_sanitized"]


def test_replay_with_fake_runner_generates_run_trace_and_no_failure_for_pass(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    from app.models.eval_tables import EvalFailure, EvalTrace
    from app.services.eval_replay_service import EvalReplayService

    service = EvalReplayService(response_runner=lambda case: {
        "suggested_reply": "可以参考",
        "intent": "product_question",
        "query_fact_type": "dimensions",
        "evidence_debug": {
            "query_fact_type": "dimensions",
            "tool_policy_trace": {"allowed_tools": ["rag_search_tool"], "evaluated_tools": []},
            "selected_evidence": [{"evidence_fact_type": "dimensions"}],
        },
    })
    service.create_case({
        "case_uid": "case_pass",
        "customer_message": "尺寸多大",
        "expected_behavior": {
            "must_have_intent": "product_question",
            "must_have_fact_type": "dimensions",
            "must_have_evidence_type": ["rag"],
        },
    })
    result = service.run_replay(limit=10, run_type="manual")

    assert result["run"]["passed_cases"] == 1
    assert result["run"]["failed_cases"] == 0
    db = session_factory()
    try:
        assert db.query(EvalTrace).count() == 1
        assert db.query(EvalFailure).count() == 0
    finally:
        db.close()


def test_replay_fail_case_generates_failure(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    from app.models.eval_tables import EvalFailure
    from app.services.eval_replay_service import EvalReplayService

    service = EvalReplayService(response_runner=lambda case: {
        "suggested_reply": "系统 RAG fact_type 已命中",
        "intent": "product_question",
        "query_fact_type": "material",
        "evidence_debug": {"tool_policy_trace": {"allowed_tools": ["jst_lookup_order_tool"], "evaluated_tools": []}},
    })
    service.create_case({
        "case_uid": "case_fail",
        "customer_message": "尺寸多大",
        "expected_behavior": {
            "must_have_fact_type": "dimensions",
            "must_not_contain": ["系统", "RAG", "fact_type"],
            "must_not_call_tools": ["jst_lookup_order_tool"],
        },
    })
    result = service.run_replay(limit=10, run_type="manual")

    assert result["run"]["failed_cases"] == 1
    db = session_factory()
    try:
        failure_types = {row.failure_type for row in db.query(EvalFailure).all()}
        assert "fact_type_mismatch" in failure_types
        assert "internal_term_leak" in failure_types
        assert "wrong_tool_called" in failure_types
    finally:
        db.close()
