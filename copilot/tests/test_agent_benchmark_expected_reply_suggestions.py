from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base
from app.models.eval_tables import AgentBenchmarkScenario
from scripts.suggest_agent_benchmark_expected_replies import suggest_expected_replies


NO_VIDEO_PROMISE = "\u4e0d\u8981\u627f\u8bfa\u6709\u89c6\u9891"
SUGGESTED_REPLY_HEADER = "\u5efa\u8bae\u6807\u51c6\u7b54\u6848\u8349\u7a3f"
NO_SPECIFIC_VALUES = "\u4e0d\u8981\u7f16\u9020\u5177\u4f53\u6570\u503c"
FABRICATE_WEIGHT = "\u7f16\u9020\u91cd\u91cf"


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    Base.metadata.create_all(bind=engine, tables=[AgentBenchmarkScenario.__table__])
    return session_factory


def _add_candidate(
    session_factory,
    *,
    scenario_uid: str = "bench_suggest_1",
    scenario_type: str = "installation",
    query_fact_type: str = "installation",
    sidecar: dict | None = None,
    expected_reply: str = "",
    original_reply: str = "Welcome to our shop.",
):
    db = session_factory()
    try:
        row = AgentBenchmarkScenario(
            scenario_uid=scenario_uid,
            source_type="real_conversation",
            source_uid=f"source_{scenario_uid}",
            status="candidate",
            title="benchmark suggestion candidate",
            scenario_type=scenario_type,
            created_by="test",
        )
        row.set_sidecar_context(sidecar if sidecar is not None else {"product_title": "Kids storage cabinet", "sku_code": "SKU-1"})
        row.set_conversation_turns([
            {"speaker": "buyer", "text": "Do you have an installation video?"},
            {"speaker": "csr", "text": "Please wait."},
        ])
        row.set_expected_reply({
            "expected_reply": expected_reply,
            "key_points": [],
            "forbidden_claims": [],
            "needs_review": True,
            "auto_send_allowed": False,
            "must_handoff": True,
            "quality": "valid" if expected_reply else "missing",
        })
        row.set_metadata({
            "expected_reply_quality": "valid" if expected_reply else "missing",
            "expected_reply_block_reason": "",
            "needs_expected_reply_review": True,
            "original_cs_reply": original_reply,
            "query_fact_type": query_fact_type,
        })
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_suggest_does_not_copy_low_quality_reference_and_avoids_video_claim(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory, original_reply="Welcome to our shop.")
    excel_output = tmp_path / "suggestions.xlsx"

    result = suggest_expected_replies(
        status="candidate",
        excel_output=str(excel_output),
        db_factory=session_factory,
    )

    item = result["items"][0]["suggestion"]
    assert result["total"] == 1
    assert item["draft_reason"] == "deterministic_safe_review_draft"
    assert "Welcome to our shop" not in item["suggested_expected_reply"]
    assert NO_VIDEO_PROMISE in item["suggested_expected_reply"]
    assert item["must_handoff"] is True
    assert item["auto_send_allowed"] is False
    workbook = load_workbook(excel_output)
    assert SUGGESTED_REPLY_HEADER in [cell.value for cell in workbook.active[1]]


def test_suggest_product_fact_missing_evidence_does_not_invent_values(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory, scenario_type="presales", query_fact_type="gross_weight")

    result = suggest_expected_replies(status="candidate", db_factory=session_factory)

    suggestion = result["items"][0]["suggestion"]
    assert NO_SPECIFIC_VALUES in suggestion["suggested_expected_reply"]
    assert FABRICATE_WEIGHT in suggestion["forbidden_claims"]
    assert suggestion["must_handoff"] is True


def test_suggest_missing_sidecar_cannot_apply_draft(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory, sidecar={})

    result = suggest_expected_replies(status="candidate", apply_draft=True, db_factory=session_factory)

    assert result["applied_count"] == 0
    assert result["skipped"][0]["reason"] == "missing_sidecar_context_cannot_activate"
    db = session_factory()
    try:
        row = db.query(AgentBenchmarkScenario).filter_by(scenario_uid="bench_suggest_1").one()
        assert row.status == "candidate"
        assert row.get_expected_reply()["needs_review"] is True
        assert not row.get_expected_reply().get("expected_reply")
    finally:
        db.close()


def test_apply_draft_writes_review_draft_without_activating(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)

    result = suggest_expected_replies(status="candidate", apply_draft=True, db_factory=session_factory)

    assert result["applied_count"] == 1
    db = session_factory()
    try:
        row = db.query(AgentBenchmarkScenario).filter_by(scenario_uid="bench_suggest_1").one()
        expected = row.get_expected_reply()
        assert row.status == "candidate"
        assert expected["needs_review"] is True
        assert expected["expected_reply"]
        assert expected["draft_source"] == "suggested_expected_reply"
    finally:
        db.close()
