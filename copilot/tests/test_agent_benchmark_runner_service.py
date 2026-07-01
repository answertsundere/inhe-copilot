from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base
from app.models.eval_tables import AgentBenchmarkScenario
from app.services.agent_benchmark_runner_service import AgentBenchmarkRunnerService
from scripts.run_agent_benchmark import run_benchmark_report


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
    status: str = "active",
):
    expected = expected or {
        "expected_reply": "The material is reinforced board.",
        "key_points": ["reinforced board"],
        "forbidden_claims": ["zero formaldehyde"],
        "must_handoff": False,
        "auto_send_allowed": True,
    }
    db = session_factory()
    try:
        row = AgentBenchmarkScenario(
            scenario_uid=scenario_uid,
            source_type="manual",
            source_uid=scenario_uid,
            status=status,
            title="Material question",
            scenario_type=scenario_type,
        )
        row.set_sidecar_context({
            "product_title": "Kids storage cabinet",
            "sku_code": "SKU-BENCH",
            "i_id": "IID-BENCH",
            "order_id": "ORDER-BENCH",
        })
        row.set_conversation_turns([
            {"turn_uid": f"{scenario_uid}_turn_1", "speaker": "buyer", "text": "Is this material safe?"}
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
            "sendable_reply": "The material is reinforced board. Please confirm against the product page.",
            "answer_trace": {"query_fact_type": "material"},
        }

    result = AgentBenchmarkRunnerService(agent_callable=fake_agent).run_scenarios(db_factory=session_factory)

    assert result["passed"] == 1
    assert result["total_scenarios"] == 1
    assert result["passed_count"] == 1
    assert result["by_scenario_type"]["presales"]["passed"] == 1
    assert result["by_query_fact_type"]["material"]["passed"] == 1
    assert result["by_reply_status"]["can_send"] == 1
    item = result["per_scenario_result"][0]
    assert item["title"] == "Material question"
    assert item["conversation_turns"]
    assert item["expected_reply"]["expected_reply"]
    assert item["can_send"] is True
    assert item["reply_status"] == "can_send"
    assert payloads[0]["product_name"] == "Kids storage cabinet"
    assert payloads[0]["sku_code"] == "SKU-BENCH"
    assert payloads[0]["copilot_context"]["sidecar_context"]["i_id"] == "IID-BENCH"


def test_runner_empty_when_no_active_scenarios(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory, status="candidate")

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {}).run_scenarios(db_factory=session_factory)

    assert result["total_scenarios"] == 0
    assert result["passed_count"] == 0
    assert result["failed_count"] == 0
    assert result["pass_rate"] == 0
    assert result["per_scenario_result"] == []


def test_missing_key_points_fail(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory)

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "Please confirm against the product page.",
        "answer_trace": {"query_fact_type": "material"},
    }).run_scenarios(db_factory=session_factory)

    assert result["failed"] == 1
    item = result["per_scenario_result"][0]
    assert item["failure_reasons"] == ["missing_key_point"]
    assert item["missing_key_points"] == ["reinforced board"]


def test_forbidden_claims_fail(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory)

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "The material is reinforced board and has zero formaldehyde.",
        "answer_trace": {"query_fact_type": "material"},
    }).run_scenarios(db_factory=session_factory)

    item = result["per_scenario_result"][0]
    assert result["failed"] == 1
    assert "forbidden_claim_present" in item["failure_reasons"]
    assert item["forbidden_claims_hit"] == ["zero formaldehyde"]


def test_must_handoff_and_auto_send_allowed_contracts(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(
        session_factory,
        expected={
            "expected_reply": "Please ask a human agent to confirm the discount.",
            "key_points": ["human agent"],
            "forbidden_claims": [],
            "must_handoff": True,
            "auto_send_allowed": False,
        },
        scenario_type="promotion",
    )

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "Please ask a human agent to confirm the discount.",
        "answer_trace": {"query_fact_type": "promotion_policy"},
    }).run_scenarios(db_factory=session_factory)

    reasons = set(result["per_scenario_result"][0]["failure_reasons"])
    assert result["failed"] == 1
    assert "auto_send_not_allowed" in reasons
    assert "handoff_mismatch" in reasons


def test_fact_type_mismatch_fails(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory, scenario_type="installation")

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": True,
        "requires_human_review": False,
        "sendable_reply": "The material is reinforced board.",
        "answer_trace": {"query_fact_type": "material"},
    }).run_scenarios(db_factory=session_factory)

    assert result["failed"] == 1
    assert "fact_type_mismatch" in result["per_scenario_result"][0]["failure_reasons"]


def test_run_benchmark_report_writes_json_and_excel(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_scenario(session_factory)
    json_output = tmp_path / "benchmark.json"
    excel_output = tmp_path / "benchmark.xlsx"

    result, exit_code = run_benchmark_report(
        json_output=str(json_output),
        excel_output=str(excel_output),
        fail_on_failure=True,
        db_factory=session_factory,
        agent_callable=lambda _payload: {
            "can_send": True,
            "requires_human_review": False,
            "sendable_reply": "Please confirm against the product page.",
            "answer_trace": {"query_fact_type": "material"},
        },
    )

    assert exit_code == 1
    assert result["failed_count"] == 1
    assert json_output.exists()
    workbook = load_workbook(excel_output)
    assert set(workbook.sheetnames) == {"汇总", "按场景", "按问题类型", "失败原因", "逐条结果"}
    assert [cell.value for cell in workbook["逐条结果"][1]][:5] == ["场景 UID", "标题", "场景类型", "问题类型", "是否通过"]
