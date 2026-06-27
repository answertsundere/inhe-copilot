from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.kb_tables  # noqa: F401 - register formal KB tables for negative write checks
from app.db import Base
from app.models.eval_tables import KnowledgeGapPublishQueue
from app.models.kb_tables import KBMediaAsset, KBProduct
from app.services.knowledge_gap_publish_adapter_service import PublishAdapterDryRunService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _queue(db, *, target="product_profile", payload=None, status="queued"):
    item = KnowledgeGapPublishQueue(
        queue_uid=f"kgpub_{target}_1",
        task_uid=f"kgap_{target}_1",
        draft_uid=f"kgdraft_{target}_1",
        publish_target=target,
        reviewer="lead",
        risk_level="medium",
        status=status,
        export_status="not_exported",
    )
    item.set_payload(payload or {})
    db.add(item)
    db.commit()
    return item


def test_product_profile_missing_product_identity_is_blocked():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, payload={"fields": {"dimensions": "100x40x120cm"}})

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["ok"] is False
        assert result["dry_run"]["schema_valid"] is False
        assert result["queue_item"]["publish_dry_run_status"] == "failed"
        assert "product_identity is required" in result["queue_item"]["publish_block_reasons"]
    finally:
        db.close()


def test_product_profile_identity_and_fields_pass_without_writing_formal_tables():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, payload={
            "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
            "fields": {"dimensions": "100x40x120cm"},
        })

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["ok"] is True
        assert result["dry_run"]["ready_for_publish"] is True
        assert result["dry_run"]["writes_formal_tables"] is False
        assert result["dry_run"]["diff_preview"]["would_create"] is True
        assert result["queue_item"]["ready_for_publish"] is True
        assert db.query(KBProduct).count() == 0
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


def test_kb_media_asset_without_uploaded_asset_is_not_ready():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="kb_media_asset", payload={
            "asset_type": "video",
            "media_purpose": "installation",
            "bind_to_sku": "sku-001",
            "asset_source_note": "review folder pending upload",
        })

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["ready_for_publish"] is False
        assert result["queue_item"]["publish_dry_run_status"] == "failed"
        assert any("needs_media_upload" in reason for reason in result["queue_item"]["publish_block_reasons"])
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


def test_kb_media_asset_conversation_reference_is_not_approved_media():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="kb_media_asset", payload={
            "asset_type": "image",
            "media_purpose": "accessory",
            "bind_to_sku": "sku-001",
            "asset_source_note": "copied from conversation",
            "conversation_media_reference": "chat image placeholder",
        })

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["ready_for_publish"] is False
        assert "conversation_media_reference cannot be treated as approved usable media" in result["dry_run"]["block_reasons"]
    finally:
        db.close()


def test_aftersales_policy_missing_escalation_boundary_is_blocked():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="aftersales_policy", payload={
            "scenario": "damaged item",
            "policy_text": "collect evidence and escalate before action",
            "required_customer_inputs": ["photo"],
            "allowed_actions": ["replacement"],
            "human_policy_confirmation": True,
        })

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["schema_valid"] is False
        assert "escalation_boundary is required" in result["dry_run"]["block_reasons"]
    finally:
        db.close()


def test_activity_rules_missing_time_scope_is_blocked():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="activity_rules", payload={
            "platform": "marketplace",
            "rule_text": "campaign-specific discount rule",
            "promotion_scope": "selected sku",
        })

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["schema_valid"] is False
        assert "time_scope is required" in result["dry_run"]["block_reasons"]
    finally:
        db.close()


def test_context_extractor_is_never_ready_for_publish():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="context_extractor", payload={"context_field": "product_identity"})

        result = PublishAdapterDryRunService().dry_run(db, item.queue_uid, operator="lead")

        assert result["dry_run"]["ok"] is False
        assert result["dry_run"]["schema_valid"] is True
        assert result["dry_run"]["ready_for_publish"] is False
        assert result["dry_run"]["writes_formal_tables"] is False
        assert "engineering work" in result["dry_run"]["block_reasons"][0]
    finally:
        db.close()
