from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base
from app.models.eval_tables import AgentBenchmarkScenario
from app.services.agent_benchmark_runner_service import AgentBenchmarkRunnerService


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    Base.metadata.create_all(bind=engine, tables=[AgentBenchmarkScenario.__table__])
    return session_factory


def _add_scenario(
    session_factory,
    *,
    scenario_uid: str = "bench_runner_1",
    expected: dict | None = None,
    scenario_type: str = "presales",
):
    expected = expected or {
        "expected_reply": "这款材质是加厚板材。",
        "key_points": ["加厚板材"],
        "forbidden_claims": ["0甲醛"],
        "must_handoff": False,
        "auto_send_allowed": True,
    }
    db = session_factory()
    try:
        row = AgentBenchmarkScenario(
            scenario_uid=scenario_uid,
            source_type="manual",
            source_uid=scenario_uid,
            status="active",
            title="材质问题",
            scenario_type=scenario_type,
        )
        row.set_sidecar_context({
            "product_title": "儿童收纳柜",
            "sku_code": "SKU-BENCH",
            "i_id": "YH-BENCH",
            "order_id": "ORDER-BENCH",
        })
        row.set_conversation_turns([
            {"turn_uid": f"{scenario_uid}_turn_1", "speaker": "buyer", "text": "这款材质安全吗？"}
        ])
        row.set_expected_reply(expected)
        row.set_rubric({"fact_correctness": True})
        db.add(row)
        db.commit()
    finally:
        db.close()


def test_runner_injects_sidecar_context_into_agent_payload(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory)
    payloads = []

    def fake_agent(payload):
        payloads.append(payload)
        return {
            "can_send": True,
            "requires_human_review": False,
            "sendable_reply": "这款材质是加厚板材，可以按页面资料核对。",
            "answer_trace": {"query_fact_type": "material"},
        }

    result = AgentBenchmarkRunnerService(agent_callable=fake_agent).run_scenarios(db_factory=session_factory)

    assert result["passed"] == 1
    assert payloads[0]["product_name"] == "儿童收纳柜"
    assert payloads[0]["sku_code"] == "SKU-BENCH"
    assert payloads[0]["copilot_context"]["sidecar_context"]["i_id"] == "YH-BENCH"


def test_missing_key_points_fail(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory)

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "可以按页面资料核对。",
        "answer_trace": {"query_fact_type": "material"},
    }).run_scenarios(db_factory=session_factory)

    assert result["failed"] == 1
    assert result["per_scenario_result"][0]["failure_reasons"] == ["missing_key_point"]


def test_forbidden_claims_fail(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory)

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "这款材质是加厚板材，0甲醛。",
        "answer_trace": {"query_fact_type": "material"},
    }).run_scenarios(db_factory=session_factory)

    assert result["failed"] == 1
    assert "forbidden_claim_present" in result["per_scenario_result"][0]["failure_reasons"]


def test_must_handoff_and_auto_send_allowed_contracts(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(
        session_factory,
        expected={
            "expected_reply": "需要人工核对优惠。",
            "key_points": ["人工核对"],
            "forbidden_claims": [],
            "must_handoff": True,
            "auto_send_allowed": False,
        },
        scenario_type="promotion",
    )

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "需要人工核对优惠。",
        "answer_trace": {"query_fact_type": "promotion_policy"},
    }).run_scenarios(db_factory=session_factory)

    assert result["failed"] == 1
    reasons = set(result["per_scenario_result"][0]["failure_reasons"])
    assert "auto_send_allowed_mismatch" in reasons
    assert "must_handoff_mismatch" in reasons
