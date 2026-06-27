import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.kb_tables  # noqa: F401 - register formal KB tables for negative write checks
from app.db import Base
from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapPublishQueue, KnowledgeGapTask
from app.models.kb_tables import KBMediaAsset
from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService
from app.services.knowledge_gap_publish_queue_service import KnowledgeGapPublishQueueService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _seed_task(db, *, task_uid="kgap_queue_1", gap_type="product_field_gap", metadata=None):
    task = KnowledgeGapTask(
        task_uid=task_uid,
        gap_type=gap_type,
        product_title="Storage cabinet",
        item_id="item-001",
        sku_code="sku-001",
        query_fact_type="dimensions",
        failure_type="rag_miss",
        suggested_fix_area="knowledge_rag",
        suggested_owner="knowledge_ops",
        missing_evidence_type="product_dimensions",
        risk_level="medium",
        sample_count=1,
        priority="medium",
        status="open",
        summary="missing product field",
    )
    task.set_metadata({
        "gap_category": gap_type,
        "required_evidence_type": "product_dimensions",
        "target_system": "product_profile",
        "missing_fields": ["dimensions"],
        "source_run_uid": "run_queue_1",
        **(metadata or {}),
    })
    db.add(task)
    db.commit()
    return task


def _draft(db, task_uid="kgap_queue_1", *, force_regenerate=False):
    return KnowledgeGapDraftService().generate_draft(db, task_uid, force_regenerate=force_regenerate)


def _review_payload(**overrides):
    payload = {
        "decision": "approve_for_queue",
        "reviewer": "lead",
        "review_note": "verified source before queue",
        "review_checklist": {
            "product_verified": True,
            "sku_scope_verified": True,
            "source_attached": True,
        },
    }
    payload.update(overrides)
    return payload


def test_approve_ready_for_review_draft_creates_queue_item():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(db, metadata={"evidence_status": "verified"})
        draft = _draft(db)

        result = KnowledgeGapPublishQueueService().review_draft(
            db,
            task_uid="kgap_queue_1",
            draft_uid=draft["draft_uid"],
            payload=_review_payload(),
            reviewer="lead",
        )

        assert result["queue_item"]["status"] == "queued"
        assert result["queue_item"]["export_status"] == "not_exported"
        assert result["queue_item"]["publish_target"] == "product_profile"
        assert result["draft"]["review_status"] == "approved_for_queue"
        assert result["task"]["status"] == "queued_for_publish"
        assert db.query(KnowledgeGapPublishQueue).count() == 1
    finally:
        db.close()


def test_product_field_needs_data_requires_verified_payload():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(db)
        draft = _draft(db)

        with pytest.raises(ValueError):
            KnowledgeGapPublishQueueService().review_draft(
                db,
                task_uid="kgap_queue_1",
                draft_uid=draft["draft_uid"],
                payload=_review_payload(),
                reviewer="lead",
            )

        payload = _review_payload(
            verified_payload={
                "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
                "fields": {"dimensions": "100x40x120cm"},
                "source_reference": "product manual page 3",
                "sku_scope": "sku-001 only",
                "reviewer_confirmation": True,
                "review_checklist": {"product_verified": True, "source_attached": True},
            },
        )
        result = KnowledgeGapPublishQueueService().review_draft(
            db,
            task_uid="kgap_queue_1",
            draft_uid=draft["draft_uid"],
            payload=payload,
            reviewer="lead",
        )

        assert result["queue_item"]["payload"]["fields"]["dimensions"] == "100x40x120cm"
        assert db.query(KnowledgeGapPublishQueue).count() == 1
    finally:
        db.close()


def test_product_field_rejects_customer_reply_as_only_source():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(db)
        draft = _draft(db)

        with pytest.raises(ValueError):
            KnowledgeGapPublishQueueService().review_draft(
                db,
                task_uid="kgap_queue_1",
                draft_uid=draft["draft_uid"],
                payload=_review_payload(
                    verified_payload={
                        "product_identity": {"sku_code": "sku-001"},
                        "fields": {"dimensions": "100x40x120cm"},
                        "source_reference": "customer said",
                        "sku_scope": "sku-001 only",
                        "reviewer_confirmation": True,
                        "review_checklist": {"product_verified": True},
                    },
                ),
                reviewer="lead",
            )
    finally:
        db.close()


def test_media_asset_request_queues_without_writing_formal_media_asset():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(
            db,
            gap_type="media_asset_gap",
            metadata={"required_evidence_type": "installation_video", "target_system": "kb_media_asset"},
        )
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = "installation"
        task.missing_evidence_type = "installation_video"
        db.commit()
        draft = _draft(db)

        result = KnowledgeGapPublishQueueService().review_draft(
            db,
            task_uid="kgap_queue_1",
            draft_uid=draft["draft_uid"],
            payload=_review_payload(
                verified_payload={
                    "asset_type": "video",
                    "media_purpose": "installation",
                    "answer_scenarios": ["installation steps"],
                    "bind_to_sku": "sku-001",
                    "asset_source_note": "uploaded to review drive",
                    "reviewer_confirms_upload_required": True,
                    "review_checklist": {"asset_scope_verified": True, "source_attached": True},
                },
            ),
            reviewer="lead",
        )

        assert result["queue_item"]["publish_target"] == "kb_media_asset"
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


def test_aftersales_unconditional_compensation_requires_verified_policy_source():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(
            db,
            gap_type="aftersales_policy_gap",
            metadata={"required_evidence_type": "aftersales_rule", "target_system": "aftersales_policy"},
        )
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = "aftersales_policy"
        task.missing_evidence_type = "aftersales_rule"
        db.commit()
        draft = _draft(db)

        with pytest.raises(ValueError):
            KnowledgeGapPublishQueueService().review_draft(
                db,
                task_uid="kgap_queue_1",
                draft_uid=draft["draft_uid"],
                payload=_review_payload(
                    verified_payload={
                        "scenario": "damaged item",
                        "policy_text": "always refund",
                        "required_customer_inputs": ["photo"],
                        "allowed_actions": ["unconditional refund"],
                        "escalation_boundary": "supervisor",
                        "reviewer_confirmation": True,
                        "review_checklist": {"policy_scope_verified": True},
                    },
                ),
                reviewer="lead",
            )
    finally:
        db.close()


def test_promotion_policy_requires_policy_source_reference():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(
            db,
            gap_type="promotion_policy_gap",
            metadata={"required_evidence_type": "promotion_rule", "target_system": "promotion_policy"},
        )
        task = db.query(KnowledgeGapTask).one()
        task.query_fact_type = "promotion_policy"
        task.missing_evidence_type = "promotion_rule"
        db.commit()
        draft = _draft(db)

        with pytest.raises(ValueError):
            KnowledgeGapPublishQueueService().review_draft(
                db,
                task_uid="kgap_queue_1",
                draft_uid=draft["draft_uid"],
                payload=_review_payload(
                    verified_payload={
                        "promotion_scope": "sku-001",
                        "platform": "marketplace",
                        "time_scope": "campaign period",
                        "rule_text": "follow platform rule",
                        "refund_after_participation_rule": "manual review",
                        "reviewer_confirmation": True,
                        "review_checklist": {"policy_scope_verified": True},
                    },
                ),
                reviewer="lead",
            )
    finally:
        db.close()


def test_context_extraction_issue_is_not_publishable():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(
            db,
            gap_type="context_extraction_gap",
            metadata={"required_evidence_type": "sku_context", "target_system": "context_extractor"},
        )
        draft = _draft(db)

        with pytest.raises(ValueError):
            KnowledgeGapPublishQueueService().review_draft(
                db,
                task_uid="kgap_queue_1",
                draft_uid=draft["draft_uid"],
                payload=_review_payload(verified_payload={"review_checklist": {"owner_confirmed": True}}),
                reviewer="lead",
            )
    finally:
        db.close()


def test_duplicate_approve_does_not_create_duplicate_queue_item():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(db, metadata={"evidence_status": "verified"})
        draft = _draft(db)
        service = KnowledgeGapPublishQueueService()

        first = service.review_draft(
            db,
            task_uid="kgap_queue_1",
            draft_uid=draft["draft_uid"],
            payload=_review_payload(),
            reviewer="lead",
        )
        second = service.review_draft(
            db,
            task_uid="kgap_queue_1",
            draft_uid=draft["draft_uid"],
            payload=_review_payload(),
            reviewer="lead",
        )

        assert second["queue_item"]["queue_uid"] == first["queue_item"]["queue_uid"]
        assert db.query(KnowledgeGapPublishQueue).count() == 1
    finally:
        db.close()


def test_export_preview_and_mark_exported_do_not_publish():
    session_factory = _session_factory()
    db = session_factory()
    try:
        _seed_task(db, metadata={"evidence_status": "verified"})
        draft = _draft(db)
        service = KnowledgeGapPublishQueueService()
        queued = service.review_draft(
            db,
            task_uid="kgap_queue_1",
            draft_uid=draft["draft_uid"],
            payload=_review_payload(),
            reviewer="lead",
        )

        preview = service.export_preview(db, queued["queue_item"]["queue_uid"])
        assert preview["dry_run"] is True
        assert preview["writes_formal_tables"] is False

        exported = service.update_queue_item(
            db,
            queued["queue_item"]["queue_uid"],
            {"status": "exported", "note": "exported to offline sheet"},
            operator="lead",
        )
        assert exported["status"] == "exported"
        assert exported["export_status"] == "exported"
        assert exported["exported_at"]

        with pytest.raises(ValueError):
            service.update_queue_item(db, queued["queue_item"]["queue_uid"], {"status": "published"}, operator="lead")
    finally:
        db.close()
