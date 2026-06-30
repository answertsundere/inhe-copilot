from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def compare_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import AIProvisionalKnowledge, EvalRun, EvalTrace

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(
        bind=engine,
        tables=[
            AIProvisionalKnowledge.__table__,
            EvalRun.__table__,
            EvalTrace.__table__,
        ],
    )
    return session_factory


def _add_run_and_trace(db, run_uid: str, case_uid: str):
    from app.models.eval_tables import EvalRun, EvalTrace

    db.add(EvalRun(
        run_uid=run_uid,
        source_type="real_conversation",
        status="completed",
        total_cases=20,
        total_turns=99,
    ))
    trace = EvalTrace(
        run_uid=run_uid,
        case_uid=case_uid,
        turn_uid=f"turn_{run_uid}",
        turn_index=1,
        buyer_message="问安装方式",
        agent_reply="需要人工核对。",
        query_fact_type="installation",
        passed=False,
    )
    trace.set_raw_response({"quality_bucket": {"quality_bucket": "knowledge_gap"}})
    db.add(trace)
    db.commit()


def test_compare_report_separates_compared_sample_from_raw_replay_totals(compare_db, monkeypatch, tmp_path):
    import scripts.compare_replay_knowledge_modes as compare

    monkeypatch.setattr(compare, "SessionLocal", compare_db)
    db = compare_db()
    try:
        _add_run_and_trace(db, "run_verified", "same_case")
        _add_run_and_trace(db, "run_prefill", "same_case")
    finally:
        db.close()

    verified_json = tmp_path / "verified.json"
    prefill_json = tmp_path / "prefill.json"
    verified_json.write_text(json.dumps({"replay": {"run_uid": "run_verified", "turns": 135, "total_cases": 50}}), encoding="utf-8")
    prefill_json.write_text(json.dumps({"replay": {"run_uid": "run_prefill", "turns": 137, "total_cases": 50}}), encoding="utf-8")

    result = compare.compare_modes(
        sample_limit=50,
        verified_only_json=str(verified_json),
        verified_plus_ai_prefill_json=str(prefill_json),
    )

    summary = result["summary"]
    assert summary["compared_trace_count"] == 1
    assert summary["compared_turn_count"] == 1
    assert summary["compared_case_count"] == 1
    assert summary["raw_replay_total_turns_verified_only"] == 135
    assert summary["raw_replay_total_turns_verified_plus_ai_prefill"] == 137
    assert summary["raw_replay_total_cases_verified_only"] == 50
    assert summary["raw_replay_total_cases_verified_plus_ai_prefill"] == 50
    assert summary["total_turns_deprecated"] == 1
    assert "Deprecated" in summary["total_turns_deprecated_note"]
