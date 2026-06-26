from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import EvalFailure, EvalRepairTask, EvalRun, EvalTrace, KnowledgeGapTask
from app.services.real_conversation_quality_task_service import RealConversationQualityTaskService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _add_trace(
    db,
    *,
    turn_uid: str,
    bucket_hint: str = "",
    query_fact_type: str = "",
    passed: bool = False,
    requires_human_review: bool = False,
    should_score: bool = True,
    actionability: str = "actionable_question",
    latency_ms: int = 10,
):
    trace = EvalTrace(
        run_uid="quality_task_run_1",
        case_uid=f"case_{turn_uid}",
        turn_uid=turn_uid,
        turn_index=latency_ms,
        buyer_message=f"buyer phone 13812345678 asks {turn_uid}",
        reference_human_reply="reference",
        agent_reply="agent reply https://demo.oss-cn/a.jpg?Signature=secret&Expires=999",
        query_fact_type=query_fact_type,
        requires_human_review=requires_human_review,
        latency_ms=latency_ms,
        passed=passed,
    )
    trace.set_turn_understanding({
        "should_score": should_score,
        "turn_actionability": actionability,
        "query_fact_type": query_fact_type,
    })
    trace.set_product_identity({"item_id": "ITEM-QA", "sku_code": "SKU-QA"})
    if bucket_hint:
        trace.set_raw_response({"quality_bucket": {"quality_bucket": bucket_hint}})
    db.add(trace)
    return trace


def _seed_run(session_factory):
    db = session_factory()
    try:
        db.add(EvalRun(run_uid="quality_task_run_1", source_type="real_conversation", status="completed"))
        _add_trace(db, turn_uid="kg_1", query_fact_type="material", latency_ms=20)
        _add_trace(db, turn_uid="kg_2", query_fact_type="material", latency_ms=30)
        _add_trace(db, turn_uid="kg_3", query_fact_type="material", latency_ms=40)
        _add_trace(db, turn_uid="kg_4", query_fact_type="material", latency_ms=50)
        _add_trace(db, turn_uid="agent_1", query_fact_type="dimensions", latency_ms=60)
        _add_trace(db, turn_uid="safe_1", query_fact_type="aftersales", requires_human_review=True, latency_ms=70)
        _add_trace(
            db,
            turn_uid="noise_1",
            should_score=False,
            actionability="acknowledgement",
            latency_ms=80,
        )
        _add_trace(db, turn_uid="auto_1", passed=True, query_fact_type="material", latency_ms=90)
        for turn_uid in ["kg_1", "kg_2", "kg_3", "kg_4"]:
            db.add(EvalFailure(
                run_uid="quality_task_run_1",
                case_uid=f"case_{turn_uid}",
                turn_uid=turn_uid,
                failure_type="rag_miss",
                severity="medium",
                suggested_fix_area="knowledge_rag",
                suggested_owner="knowledge_ops",
                message="missing knowledge 13812345678",
            ))
        db.add(EvalFailure(
            run_uid="quality_task_run_1",
            case_uid="case_agent_1",
            turn_uid="agent_1",
            failure_type="semantic_mismatch",
            severity="high",
            suggested_fix_area="final_audit_semantic_compiler",
            suggested_owner="agent_quality",
            message="agent mismatch",
        ))
        db.add(EvalFailure(
            run_uid="quality_task_run_1",
            case_uid="case_safe_1",
            turn_uid="safe_1",
            failure_type="needs_human_review",
            severity="medium",
            suggested_fix_area="human_policy_risk_boundary",
            suggested_owner="human_policy",
            message="safe handoff",
        ))
        db.commit()
    finally:
        db.close()


def test_quality_task_service_groups_buckets_and_limits_representative_samples():
    session_factory = _session_factory()
    _seed_run(session_factory)
    db = session_factory()
    try:
        result = RealConversationQualityTaskService().build_for_run(db, "quality_task_run_1")

        assert result["summary"]["knowledge_gap"] == 4
        assert result["summary"]["agent_error"] == 1
        assert result["summary"]["safe_handoff"] == 1
        assert result["summary"]["unscored_or_noise"] == 1
        assert result["summary"]["auto_sendable"] == 1
        assert result["task_group_count"] == 3

        kg_group = next(item for item in result["task_groups"] if item["quality_bucket"] == "knowledge_gap")
        assert kg_group["next_step"] == "generate_knowledge_gap_task"
        assert kg_group["suggested_owner"] == "knowledge_ops"
        assert kg_group["sample_count"] == 4
        assert len(kg_group["representative_samples"]) == 3

        agent_group = next(item for item in result["task_groups"] if item["quality_bucket"] == "agent_error")
        assert agent_group["next_step"] == "generate_repair_task"
        assert agent_group["suggested_owner"] == "agent_quality"

        safe_group = next(item for item in result["task_groups"] if item["quality_bucket"] == "safe_handoff")
        assert safe_group["next_step"] == "review_human_policy"

        raw = str(result)
        assert "13812345678" not in raw
        assert "Signature=secret" not in raw
    finally:
        db.close()


def test_quality_task_generation_uses_existing_repair_and_gap_services_without_duplicates():
    session_factory = _session_factory()
    _seed_run(session_factory)
    db = session_factory()
    try:
        first = RealConversationQualityTaskService().generate_for_run(db, "quality_task_run_1", created_by="lead")
        second = RealConversationQualityTaskService().generate_for_run(db, "quality_task_run_1", created_by="lead")

        assert first.generated == 2
        assert first.updated == 0
        assert second.generated == 0
        assert second.updated == 2
        assert second.skipped == 1
        assert db.query(EvalRepairTask).count() == 1
        assert db.query(KnowledgeGapTask).count() == 1
    finally:
        db.close()
