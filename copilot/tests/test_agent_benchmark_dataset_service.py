from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db as db_module
from app.db import Base
from app.models.eval_tables import AgentBenchmarkScenario, EvalCase, EvalConversationTurn, EvalRun, EvalTrace
from app.services.agent_benchmark_dataset_service import AgentBenchmarkDatasetService, is_low_quality_reference_reply


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            AgentBenchmarkScenario.__table__,
            EvalRun.__table__,
            EvalCase.__table__,
            EvalTrace.__table__,
            EvalConversationTurn.__table__,
        ],
    )
    return session_factory


def _seed_replay(session_factory, *, with_sidecar: bool = True, reference_reply: str = "可以按这款商品资料核对。"):
    db = session_factory()
    try:
        db.add(EvalRun(run_uid="bench_run_1", source_type="real_conversation", status="completed"))
        db.add(EvalCase(case_uid="bench_case_1", source_type="real_conversation", status="active", message="材质安全吗"))
        db.add_all([
            EvalConversationTurn(
                case_uid="bench_case_1",
                conversation_uid="bench_conv_1",
                turn_uid="bench_turn_1",
                turn_index=0,
                speaker="buyer",
                sanitized_text="这个材质安全吗？",
                reference_human_reply=reference_reply,
            ),
            EvalConversationTurn(
                case_uid="bench_case_1",
                conversation_uid="bench_conv_1",
                turn_uid="bench_turn_2",
                turn_index=1,
                speaker="service",
                sanitized_text=reference_reply,
            ),
            EvalConversationTurn(
                case_uid="bench_case_1",
                conversation_uid="bench_conv_1",
                turn_uid="bench_turn_3",
                turn_index=2,
                speaker="buyer",
                sanitized_text="还有安装视频吗？",
            ),
        ])
        trace = EvalTrace(
            run_uid="bench_run_1",
            case_uid="bench_case_1",
            turn_uid="bench_turn_1",
            turn_index=0,
            buyer_message="这个材质安全吗？",
            reference_human_reply=reference_reply,
            agent_reply="需要按资料核对。",
            query_fact_type="material",
            passed=False,
        )
        if with_sidecar:
            trace.set_answer_trace({
                "sidecar_context": {
                    "product_title": "儿童收纳柜",
                    "sku_code": "SKU-BENCH",
                    "i_id": "YH-BENCH",
                    "sidecar_context_quality": "complete",
                }
            })
        db.add(trace)
        db.commit()
    finally:
        db.close()


def test_create_candidate_from_replay_keeps_sidecar_and_long_turns(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_replay(session_factory)

    result = AgentBenchmarkDatasetService().create_candidate_from_real_replay(
        run_uid="bench_run_1",
        apply=True,
        db_factory=session_factory,
    )

    assert result["created"] == 1
    candidate = result["candidates"][0]
    assert candidate["status"] == "candidate"
    assert candidate["sidecar_context"]["product_title"] == "儿童收纳柜"
    assert len(candidate["conversation_turns"]) == 3
    assert candidate["expected_reply"]["needs_review"] is True
    assert candidate["metadata"]["missing_sidecar"] is False
    assert candidate["metadata"]["expected_reply_quality"] == "valid"


def test_missing_sidecar_candidate_cannot_promote_active(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_replay(session_factory, with_sidecar=False)
    result = AgentBenchmarkDatasetService().create_candidate_from_real_replay(
        run_uid="bench_run_1",
        apply=True,
        db_factory=session_factory,
    )

    scenario_uid = result["candidates"][0]["scenario_uid"]
    try:
        AgentBenchmarkDatasetService().promote_to_active(scenario_uid, reviewer="lead", db_factory=session_factory)
    except ValueError as exc:
        assert str(exc) == "sidecar_context_required"
    else:
        raise AssertionError("missing sidecar scenario should not become active")


def test_empty_expected_reply_cannot_promote_active(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        row = AgentBenchmarkScenario(
            scenario_uid="bench_empty_expected",
            source_type="manual",
            source_uid="manual_empty_expected",
            status="candidate",
            title="empty expected",
            scenario_type="presales",
        )
        row.set_sidecar_context({"product_title": "儿童收纳柜"})
        row.set_expected_reply({"expected_reply": "", "needs_review": False})
        row.set_conversation_turns([{"speaker": "buyer", "text": "材质安全吗"}])
        row.set_metadata({"expected_reply_quality": "valid"})
        db.add(row)
        db.commit()
    finally:
        db.close()

    try:
        AgentBenchmarkDatasetService().promote_to_active("bench_empty_expected", reviewer="lead", db_factory=session_factory)
    except ValueError as exc:
        assert str(exc) == "expected_reply_required"
    else:
        raise AssertionError("empty expected reply should not become active")


def test_needs_review_candidate_cannot_promote_active(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_replay(session_factory)
    result = AgentBenchmarkDatasetService().create_candidate_from_real_replay(
        run_uid="bench_run_1",
        apply=True,
        db_factory=session_factory,
    )
    scenario_uid = result["candidates"][0]["scenario_uid"]

    try:
        AgentBenchmarkDatasetService().promote_to_active(scenario_uid, reviewer="lead", db_factory=session_factory)
    except ValueError as exc:
        assert str(exc) == "expected_reply_review_required"
    else:
        raise AssertionError("needs_review candidate should not become active")


def test_mark_expected_reply_reviewed_then_promote_active(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_replay(session_factory)
    result = AgentBenchmarkDatasetService().create_candidate_from_real_replay(
        run_uid="bench_run_1",
        apply=True,
        db_factory=session_factory,
    )
    scenario_uid = result["candidates"][0]["scenario_uid"]

    reviewed = AgentBenchmarkDatasetService().mark_expected_reply_reviewed(
        scenario_uid,
        reviewer="lead",
        expected_reply="这款材质需要按商品检测资料核对，不能承诺绝对安全。",
        key_points=["检测资料核对"],
        forbidden_claims=["绝对安全"],
        auto_send_allowed=False,
        must_handoff=True,
        db_factory=session_factory,
    )
    assert reviewed["expected_reply"]["needs_review"] is False
    assert reviewed["metadata"]["expected_reply_quality"] == "valid"

    promoted = AgentBenchmarkDatasetService().promote_to_active(scenario_uid, reviewer="lead", db_factory=session_factory)

    assert promoted["status"] == "active"
    assert promoted["metadata"]["status_history"][-1]["reviewer"] == "lead"


def test_low_quality_reference_reply_clears_expected_reply(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_replay(session_factory, reference_reply="您好~欢迎光临本小店，您看中哪些宝贝？我可以帮您介绍一下哦~")

    result = AgentBenchmarkDatasetService().create_candidate_from_real_replay(
        run_uid="bench_run_1",
        apply=True,
        db_factory=session_factory,
    )

    candidate = result["candidates"][0]
    assert candidate["expected_reply"]["expected_reply"] == ""
    assert candidate["expected_reply"]["draft_source"] == "low_quality_reference_reply"
    assert candidate["metadata"]["expected_reply_quality"] == "low_quality"
    assert candidate["metadata"]["expected_reply_block_reason"] == "welcome_reference_reply"
    assert candidate["metadata"]["needs_expected_reply_review"] is True


def test_common_low_quality_reference_reply_terms_are_detected():
    for text in ("稍等亲", "好的", "可以的", "亲亲在的", "https://example.com/a.jpg"):
        assert is_low_quality_reference_reply(text) is True


def test_business_reference_reply_is_valid():
    assert is_low_quality_reference_reply("这个配件是备用螺丝，不需要安装到柜体上。") is False


def test_low_quality_candidate_cannot_promote_active(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_replay(session_factory, reference_reply="稍等")
    result = AgentBenchmarkDatasetService().create_candidate_from_real_replay(
        run_uid="bench_run_1",
        apply=True,
        db_factory=session_factory,
    )

    try:
        AgentBenchmarkDatasetService().promote_to_active(result["candidates"][0]["scenario_uid"], reviewer="lead", db_factory=session_factory)
    except ValueError as exc:
        assert str(exc) == "expected_reply_required"
    else:
        raise AssertionError("low quality expected reply should not become active")


def test_empty_conversation_turns_cannot_promote_active(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        row = AgentBenchmarkScenario(
            scenario_uid="bench_empty_turns",
            source_type="manual",
            source_uid="manual_empty_turns",
            status="candidate",
            title="empty turns",
            scenario_type="presales",
        )
        row.set_sidecar_context({"product_title": "儿童收纳柜"})
        row.set_expected_reply({"expected_reply": "材质按商品资料核对。", "needs_review": False})
        row.set_conversation_turns([])
        row.set_metadata({"expected_reply_quality": "valid"})
        db.add(row)
        db.commit()
    finally:
        db.close()

    try:
        AgentBenchmarkDatasetService().promote_to_active("bench_empty_turns", reviewer="lead", db_factory=session_factory)
    except ValueError as exc:
        assert str(exc) == "conversation_turns_required"
    else:
        raise AssertionError("empty conversation turns should not become active")
