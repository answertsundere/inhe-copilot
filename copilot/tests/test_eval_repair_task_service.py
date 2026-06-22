import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _isolated_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import EvalFailure, EvalRepairTask  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


def test_repair_task_merges_same_failure_type_and_fix_area(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    from app.models.eval_tables import EvalFailure
    from app.services.eval_repair_task_service import generate_repair_tasks

    db = session_factory()
    try:
        for idx in range(2):
            db.add(EvalFailure(
                run_uid="run1",
                case_uid=f"case{idx}",
                failure_type="wrong_tool_called",
                severity="high",
                suggested_fix_area="tool_policy",
                failed_contract="must_not_call_tools",
                expected_json="{}",
                actual_json=json.dumps({"suggested_files": ["app/agent/tools/tool_policy_gate.py"]}),
            ))
        db.commit()
    finally:
        db.close()

    tasks = generate_repair_tasks("run1")

    assert len(tasks) == 1
    assert tasks[0]["failure_count"] == 2
    assert tasks[0]["suggested_owner"] == "agent"
    assert "tool_policy_gate.py" in tasks[0]["suggested_files"][0]
