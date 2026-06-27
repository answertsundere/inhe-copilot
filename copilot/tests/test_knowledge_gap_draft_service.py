import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask, KnowledgeGapTaskSample
from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _seed_task(session_factory, *, gap_type="product_field_gap", risk_level="high"):
    db = session_factory()
    try:
        task = KnowledgeGapTask(
            task_uid="kgap_draft_1",
            gap_type=gap_type,
            product_title="儿童收纳柜",
            query_fact_type="material",
            failure_type="rag_miss",
            suggested_fix_area="knowledge_rag",
            suggested_owner="knowledge_ops",
            missing_evidence_type="product_material",
            risk_level=risk_level,
            sample_count=1,
            priority="high",
            status="open",
            summary="material gap",
        )
        task.set_metadata({
            "gap_category": gap_type,
            "required_evidence_type": "product_material",
            "target_system": "product_profile",
            "recommended_action": "fill_product_field",
            "missing_fields": ["material"],
        })
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


def test_product_field_draft_is_staging_and_publish_blocked_without_verified_evidence():
    session_factory = _session_factory()
    _seed_task(session_factory)
    db = session_factory()
    try:
        draft = KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")

        assert draft["review_status"] == "pending_review"
        assert draft["publish_target"] == "staging"
        assert draft["draft_type"] == "product_field_draft"
        content = draft["draft_content"]
        assert content["source_samples"]
        assert "13812345678" not in str(content)
        assert content["publish_blocked_reason"] == "product field drafts require verified evidence before publishing"
        assert content["evidence_requirements"]["required_evidence_type"] == "product_material"
        assert "material" in content["required_review_fields"]
        assert any("不得把原客服回复直接当作事实证据" in item for item in content["uncertain_items"])
        assert db.query(KnowledgeGapDraft).count() == 1
        task = db.query(KnowledgeGapTask).one()
        assert task.status == "draft_ready"
        assert task.get_metadata()["status_history"][-1]["status"] == "draft_ready"
    finally:
        db.close()


def test_media_gap_generates_media_asset_request_not_fake_url():
    session_factory = _session_factory()
    _seed_task(session_factory, gap_type="media_asset_gap", risk_level="medium")
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = "installation"
        task.missing_evidence_type = "installation_video"
        task.set_metadata({
            "gap_category": "media_asset_gap",
            "required_evidence_type": "installation_video",
            "target_system": "kb_media_asset",
            "recommended_action": "upload_approved_media",
            "missing_fields": ["installation_video"],
        })
        db.commit()

        draft = KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")
        content = draft["draft_content"]
        assert draft["draft_type"] == "media_asset_request"
        assert content["proposed_answer"] == ""
        assert "installation_video" in content["suggested_content"]
        assert "http" not in content["suggested_content"].lower()
        assert content["publish_blocked_reason"] == "media assets must be uploaded and approved before use"
    finally:
        db.close()


def test_aftersales_policy_gap_generates_aftersales_policy_draft_staging_only():
    session_factory = _session_factory()
    _seed_task(session_factory, gap_type="aftersales_policy_gap", risk_level="high")
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = "aftersales_policy"
        task.missing_evidence_type = "aftersales_rule"
        task.set_metadata({
            "gap_category": "aftersales_policy_gap",
            "required_evidence_type": "aftersales_rule",
            "target_system": "aftersales_policy",
            "recommended_action": "write_policy_rule",
            "missing_fields": ["aftersales_rule"],
        })
        db.commit()

        draft = KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")
        content = draft["draft_content"]
        assert draft["draft_type"] == "aftersales_policy_draft"
        assert draft["publish_target"] == "staging"
        assert content["proposed_rule"]
        assert "不得编造承诺" in content["proposed_rule"]
    finally:
        db.close()


def test_promotion_policy_gap_generates_promotion_policy_draft_staging_only():
    session_factory = _session_factory()
    _seed_task(session_factory, gap_type="promotion_policy_gap", risk_level="medium")
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = "promotion_policy"
        task.missing_evidence_type = "promotion_rule"
        task.set_metadata({
            "gap_category": "promotion_policy_gap",
            "required_evidence_type": "promotion_rule",
            "target_system": "promotion_policy",
            "recommended_action": "write_promotion_policy",
            "missing_fields": ["promotion_rule"],
        })
        db.commit()

        draft = KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")

        assert draft["draft_type"] == "promotion_policy_draft"
        assert draft["publish_target"] == "staging"
        assert draft["draft_content"]["proposed_rule"]
    finally:
        db.close()


def test_context_extraction_gap_generates_context_extraction_issue():
    session_factory = _session_factory()
    _seed_task(session_factory, gap_type="context_extraction_gap", risk_level="medium")
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = ""
        task.missing_evidence_type = "sku_context"
        task.set_metadata({
            "gap_category": "context_extraction_gap",
            "required_evidence_type": "sku_context",
            "target_system": "context_extractor",
            "recommended_action": "fix_context_extraction",
            "missing_fields": ["sku_code"],
        })
        db.commit()

        draft = KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")

        assert draft["draft_type"] == "context_extraction_issue"
        assert draft["publish_target"] == "staging"
    finally:
        db.close()


def test_ignore_false_positive_review_decision_does_not_generate_draft():
    session_factory = _session_factory()
    _seed_task(session_factory, risk_level="medium")
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).one()
        metadata = task.get_metadata()
        metadata["review_decision"] = "ignore_false_positive"
        task.set_metadata(metadata)
        db.commit()

        with pytest.raises(ValueError):
            KnowledgeGapDraftService().generate_draft(db, "kgap_draft_1")

        assert db.query(KnowledgeGapDraft).count() == 0
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
