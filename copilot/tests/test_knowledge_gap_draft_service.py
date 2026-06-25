from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask, KnowledgeGapTaskSample
from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _seed_task(session_factory, *, risk_level="high"):
    db = session_factory()
    try:
        task = KnowledgeGapTask(
            task_uid="kgap_draft_1",
            gap_type="product_fact_gap",
            product_title="儿童收纳柜",
            query_fact_type="material",
            failure_type="rag_miss",
            suggested_fix_area="knowledge_rag",
            suggested_owner="knowledge_ops",
            missing_evidence_type="material_fact",
            risk_level=risk_level,
            sample_count=1,
            priority="high",
            status="open",
            summary="material gap",
        )
        db.add(task)
        sample = KnowledgeGapTaskSample(
            task_uid="kgap_draft_1",
            run_uid="run_1",
            case_uid="case_1",
            turn_uid="turn_1",
            buyer_message="这个材质安全吗，电话 13812345678",
            agent_reply="需要核对",
            reference_human_reply="参考回复",
            failure_type="rag_miss",
            query_fact_type="material",
        )
        db.add(sample)
        db.commit()
    finally:
        db.close()


def test_draft_generation_writes_only_pending_review_staging():
    session_factory = _session_factory()
    _seed_task(session_factory)
    db = session_factory()
    try:
        draft = KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")

        assert draft["review_status"] == "pending_review"
        assert draft["publish_target"] == "staging"
        assert draft["generated_by"] == "ai"
        content = draft["draft_content"]
        assert content["source_samples"]
        assert "13812345678" not in str(content)
        assert any("不代表已核验事实" in item for item in content["uncertain_items"])
        assert any("不得写 0 风险" in item for item in content["prohibited_claims"])
        assert db.query(KnowledgeGapDraft).count() == 1
    finally:
        db.close()


def test_draft_review_approve_and_reject_stay_in_staging():
    session_factory = _session_factory()
    _seed_task(session_factory, risk_level="medium")
    db = session_factory()
    try:
        KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")
        approved = KnowledgeGapDraftService().approve(db, "kgap_draft_1", reviewer="lead")

        assert approved["task"]["status"] == "approved"
        assert approved["drafts"][0]["review_status"] == "approved"
        assert approved["drafts"][0]["publish_target"] == "staging"

        rejected = KnowledgeGapDraftService().reject(db, "kgap_draft_1", reviewer="lead", reason="need source")
        assert rejected["task"]["status"] == "rejected"
    finally:
        db.close()
