from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base
from app.models.eval_tables import AgentBenchmarkScenario
from app.services.agent_benchmark_runner_service import AgentBenchmarkRunnerService
from scripts.curate_agent_benchmark_seed_set import curate_seed_set, evaluate_seed_candidate


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    Base.metadata.create_all(bind=engine, tables=[AgentBenchmarkScenario.__table__])
    return session_factory


def _add_candidate(
    session_factory,
    *,
    scenario_uid: str = "seed_candidate_1",
    scenario_type: str = "installation",
    query_fact_type: str = "installation",
    with_sidecar: bool = True,
    status: str = "candidate",
    turns: list[dict] | None = None,
    metadata_extra: dict | None = None,
):
    db = session_factory()
    try:
        row = AgentBenchmarkScenario(
            scenario_uid=scenario_uid,
            source_type="real_conversation",
            source_uid=f"source_{scenario_uid}",
            status=status,
            title="Seed candidate",
            scenario_type=scenario_type,
            created_by="test",
        )
        row.set_sidecar_context({"product_title": "Test shelf", "sku_code": "SKU-SEED"} if with_sidecar else {})
        row.set_conversation_turns(
            turns
            if turns is not None
            else [{"speaker": "buyer", "text": "Do you have installation guidance for this product?"}]
        )
        row.set_expected_reply({
            "expected_reply": "",
            "key_points": [],
            "forbidden_claims": [],
            "needs_review": True,
            "auto_send_allowed": False,
            "must_handoff": True,
        })
        metadata = {
            "expected_reply_quality": "missing",
            "needs_expected_reply_review": True,
            "query_fact_type": query_fact_type,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        row.set_metadata(metadata)
        db.add(row)
        db.commit()
    finally:
        db.close()


def _scenario(session_factory, scenario_uid: str):
    db = session_factory()
    try:
        return db.query(AgentBenchmarkScenario).filter_by(scenario_uid=scenario_uid).one()
    finally:
        db.close()


def test_seed_curator_dry_run_does_not_write_db(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)

    result = curate_seed_set(limit=5, apply_reviewed=False, db_factory=session_factory)

    assert result["dry_run"] is True
    assert result["selected_count"] == 1
    assert result["would_review_count"] == 1
    row = _scenario(session_factory, "seed_candidate_1")
    assert row.status == "candidate"
    assert row.get_expected_reply()["needs_review"] is True
    assert row.get_expected_reply()["expected_reply"] == ""


def test_seed_curator_apply_reviewed_does_not_activate(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)

    result = curate_seed_set(limit=5, apply_reviewed=True, promote_active=False, db_factory=session_factory)

    assert result["reviewed_count"] == 1
    assert result["promoted_count"] == 0
    row = _scenario(session_factory, "seed_candidate_1")
    assert row.status == "candidate"
    assert row.get_expected_reply()["needs_review"] is False
    assert row.get_metadata()["expected_reply_quality"] == "valid"
    assert row.get_metadata()["expected_reply_reviewed_by"] == "codex_seed_curator"


def test_seed_curator_promote_active_uses_existing_gate(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)

    result = curate_seed_set(limit=5, apply_reviewed=True, promote_active=True, db_factory=session_factory)

    assert result["promoted_scenario_uids"] == ["seed_candidate_1"]
    row = _scenario(session_factory, "seed_candidate_1")
    assert row.status == "active"
    assert row.get_metadata()["status_history"][-1]["reviewer"] == "codex_seed_curator"


def test_seed_curator_skips_missing_sidecar_and_specific_fact_gaps(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory, scenario_uid="missing_sidecar", with_sidecar=False)
    _add_candidate(
        session_factory,
        scenario_uid="specific_fact",
        scenario_type="presales",
        query_fact_type="dimensions",
    )

    result = curate_seed_set(limit=5, apply_reviewed=False, db_factory=session_factory)

    assert result["selected_count"] == 0
    assert result["skip_reason_counts"]["missing_sidecar_context"] == 1
    assert result["skip_reason_counts"]["specific_product_fact_requires_verified_evidence"] == 1


def test_seed_curator_does_not_generate_concrete_numeric_facts(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)

    result = curate_seed_set(limit=5, apply_reviewed=False, db_factory=session_factory)

    expected = result["items"][0]["expected"]["expected_reply"]
    assert expected
    assert not any(char.isdigit() for char in expected)


def test_seed_curator_installation_seed_allows_verified_install_material_send(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(
        session_factory,
        metadata_extra={
            "recommended_assets": [
                {
                    "asset_type": "manual",
                    "review_status": "approved",
                    "usable": True,
                    "auto_send_level": "auto",
                    "asset_url": "https://example.test/manual.jpg",
                }
            ]
        },
    )

    result = curate_seed_set(limit=5, apply_reviewed=False, db_factory=session_factory)

    expected = result["items"][0]["expected"]
    assert expected["auto_send_allowed"] is True
    assert expected["must_handoff"] is False
    assert "\u5b89\u88c5\u56fe\u6216\u8bf4\u660e\u4e66" in expected["key_points"]


def test_seed_curator_installation_seed_without_install_asset_requires_handoff(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)

    result = curate_seed_set(limit=5, apply_reviewed=False, db_factory=session_factory)

    expected = result["items"][0]["expected"]
    assert expected["auto_send_allowed"] is False
    assert expected["must_handoff"] is True
    assert "\u8f6c\u4eba\u5de5" in expected["key_points"]
    assert "\u4e0d\u76f4\u63a5\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891" in expected["key_points"]


def test_seed_curator_installation_seed_rejects_plain_product_photo_as_sendable(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(
        session_factory,
        metadata_extra={
            "recommended_assets": [
                {
                    "asset_type": "sku_image",
                    "media_role": "product_photo",
                    "review_status": "approved",
                    "usable": True,
                    "auto_send_level": "auto",
                    "asset_url": "https://example.test/product.jpg",
                }
            ]
        },
    )

    result = curate_seed_set(limit=5, apply_reviewed=False, db_factory=session_factory)

    expected = result["items"][0]["expected"]
    assert expected["auto_send_allowed"] is False
    assert expected["must_handoff"] is True


def test_seed_curator_evaluate_rejects_unclear_candidate():
    item = {
        "scenario_uid": "unclear",
        "scenario_type": "presales",
        "sidecar_context": {"product_title": "Test product"},
        "conversation_turns": [{"speaker": "buyer", "text": "ok"}],
        "metadata": {"query_fact_type": "space_fit"},
    }

    result = evaluate_seed_candidate(item)

    assert result["selected"] is False
    assert result["reason"] == "unclear_or_too_short_context"


def test_seed_curator_rejects_order_backend_status_question():
    item = {
        "scenario_uid": "backend_status",
        "scenario_type": "aftersales",
        "sidecar_context": {"product_title": "Test product", "order_id": "ORDER-SEED"},
        "conversation_turns": [{"speaker": "buyer", "text": "Has my refund arrived yet?"}],
        "metadata": {"query_fact_type": "aftersales"},
    }

    result = evaluate_seed_candidate(item)

    assert result["selected"] is True

    chinese_status_item = {
        **item,
        "scenario_uid": "backend_status_cn",
        "conversation_turns": [{"speaker": "buyer", "text": "\u9000\u6b3e\u5230\u8d26\u4e86\u5417"}],
    }

    result = evaluate_seed_candidate(chinese_status_item)

    assert result["selected"] is False
    assert result["reason"] == "order_backend_state_required"


def test_active_seed_benchmark_can_run(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _add_candidate(session_factory)
    curate_seed_set(limit=5, apply_reviewed=True, promote_active=True, db_factory=session_factory)

    result = AgentBenchmarkRunnerService(agent_callable=lambda _payload: {
        "can_send": False,
        "requires_human_review": True,
        "draft_reply": "I will check the current product, not directly promise an installation video, and transfer to a human agent.",
        "answer_trace": {"query_fact_type": "installation"},
    }).run_scenarios(db_factory=session_factory)

    assert result["total_scenarios"] == 1
    assert result["per_scenario_result"][0]["scenario_uid"] == "seed_candidate_1"
