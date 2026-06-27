import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalFailure, EvalRepairTask, EvalRun, EvalTrace
from app.services.real_conversation_daily_replay_service import (
    DailyReplayOptions,
    run_daily_real_conversation_replay,
)
from app.services.real_conversation_replay_service import RealConversationReplayService


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    return session_factory


def _write_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    payload = {
        "conversation_id": "daily-conv-1",
        "messages": [
            {
                "speaker": "buyer",
                "text": "install question https://item.taobao.com/item.htm?id=123456789 SKU:SKU-TEST phone 13812345678",
            },
            {"speaker": "service", "text": "reference install reply"},
            {
                "speaker": "buyer",
                "text": "material question https://item.taobao.com/item.htm?id=123456789 order 123456789012345",
            },
            {"speaker": "service", "text": "reference material reply"},
            {
                "speaker": "buyer",
                "text": "video question https://item.taobao.com/item.htm?id=123456789 SKU:SKU-TEST",
            },
            {"speaker": "service", "text": "reference video reply"},
        ],
    }
    (source / "chat-2026-06-23.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return source


def test_daily_replay_dry_run_does_not_write_db(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = _write_source(tmp_path)

    report = run_daily_real_conversation_replay(DailyReplayOptions(
        source_dir=str(source),
        sample_limit=50,
        run_date="2026-06-23",
        apply=False,
    ))

    assert report["dry_run"] is True
    assert report["import"]["sample_count"] == 1
    assert report["replay"]["skipped"] is True
    raw = json.dumps(report, ensure_ascii=False)
    assert "13812345678" not in raw
    assert "123456789012345" not in raw
    db = session_factory()
    try:
        assert db.query(EvalCase).count() == 0
        assert db.query(EvalRun).count() == 0
    finally:
        db.close()


def test_daily_replay_apply_creates_run_traces_failures_and_schedule(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = _write_source(tmp_path)

    def fake_call_agent(self, payload):
        return {
            "suggested_reply": "needs human review",
            "requires_human_review": True,
            "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
            "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
            "final_answer_audit": {"passed": False},
        }

    monkeypatch.setattr(RealConversationReplayService, "_call_agent", fake_call_agent)

    report = run_daily_real_conversation_replay(DailyReplayOptions(
        source_dir=str(source),
        sample_limit=50,
        run_date="2026-06-23",
        apply=True,
    ))

    assert report["status"] == "completed"
    db = session_factory()
    try:
        run = db.query(EvalRun).one()
        assert run.run_uid == report["run_uid"]
        assert run.total_turns == 3
        assert run.failed_turns == 3
        assert db.query(EvalTrace).count() == 3
        assert db.query(EvalFailure).count() >= 3
        schedule = run.get_metadata()["daily_schedule"]
        assert schedule["schedule_uid"] == report["schedule_uid"]
        assert schedule["status"] == "completed"
        assert schedule["pass_rate"] == 0
    finally:
        db.close()


def test_daily_replay_only_replays_current_imported_cases(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = _write_source(tmp_path)
    db = session_factory()
    try:
        stale_case = EvalCase(case_uid="case_stale", source_type="real_conversation", status="active")
        stale_case.message = "stale report summary"
        stale_turn = EvalConversationTurn(
            turn_uid="turn_stale",
            case_uid="case_stale",
            conversation_uid="stale",
            turn_index=0,
            speaker="buyer",
            sanitized_text="unknown 客服:英禾旗舰店:宇航 时间:2026-05-19 08:08:00+08:00 → 5 个会话",
        )
        db.add(stale_case)
        db.add(stale_turn)
        db.commit()
    finally:
        db.close()

    seen_messages = []

    def fake_call_agent(self, payload):
        seen_messages.append(payload.get("message", ""))
        return {"suggested_reply": "ok", "evidence_debug": {"selected_evidence": [{"fact_type": "material"}]}}

    monkeypatch.setattr(RealConversationReplayService, "_call_agent", fake_call_agent)

    report = run_daily_real_conversation_replay(DailyReplayOptions(
        source_dir=str(source),
        sample_limit=50,
        run_date="2026-06-23",
        apply=True,
    ))

    assert report["replay"]["turns"] == 3
    assert len(seen_messages) == 3
    assert all("个会话" not in item for item in seen_messages)


def test_daily_replay_apply_can_generate_repair_tasks(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = _write_source(tmp_path)

    def fake_call_agent(self, payload):
        return {
            "suggested_reply": "needs human review",
            "requires_human_review": True,
            "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
            "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
        }

    monkeypatch.setattr(RealConversationReplayService, "_call_agent", fake_call_agent)

    report = run_daily_real_conversation_replay(DailyReplayOptions(
        source_dir=str(source),
        sample_limit=50,
        run_date="2026-06-23",
        apply=True,
        generate_repair_tasks=True,
    ))

    assert report["repair_tasks"]["generated"] >= 1
    db = session_factory()
    try:
        assert db.query(EvalRepairTask).count() >= 1
    finally:
        db.close()
