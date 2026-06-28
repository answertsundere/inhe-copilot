import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.kb_tables  # noqa: F401 - register formal KB tables for negative write checks
from app.db import Base
from app.models.eval_tables import KnowledgeGapPublishAudit, KnowledgeGapPublishQueue
from app.models.kb_tables import KBMediaAsset, KBProduct
from app.services.knowledge_gap_publish_gate_service import KnowledgeGapPublishGateService
from app.services.knowledge_gap_publish_queue_service import payload_fingerprint


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _payload(target="product_profile"):
    if target == "kb_media_asset":
        return {
            "asset_type": "video",
            "media_purpose": "installation",
            "bind_to_sku": "sku-001",
            "uploaded_asset_id": "asset-001",
        }
    if target == "kb_product":
        return {
            "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
            "fact_type": "dimensions",
            "evidence_text": "100x40x120cm",
            "source_reference": "manual page 3",
        }
    return {
        "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
        "fields": {"dimensions": "100x40x120cm"},
        "source_reference": "manual page 3",
    }


def _queue(db, *, target="product_profile", payload=None, **overrides):
    clean_payload = payload or _payload(target)
    fingerprint = payload_fingerprint(target, clean_payload)
    item = KnowledgeGapPublishQueue(
        queue_uid=f"kgpub_gate_{target}_{len(clean_payload)}",
        task_uid=f"kgap_gate_{target}",
        draft_uid=f"kgdraft_gate_{target}",
        publish_target=target,
        payload_fingerprint=fingerprint,
        reviewer="lead",
        risk_level="medium",
        status="queued",
        export_status="not_exported",
        publish_dry_run_status="passed",
        ready_for_publish=True,
        pre_publish_retest_status="passed",
        approved_to_publish=True,
        approval_status="approved_to_publish",
        locked_payload_fingerprint=fingerprint,
    )
    for key, value in overrides.items():
        setattr(item, key, value)
    item.set_payload(clean_payload)
    db.add(item)
    db.commit()
    return item


def test_product_profile_gate_creates_transaction_plan_without_formal_writes():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db)

        result = KnowledgeGapPublishGateService().simulate_publish(db, item.queue_uid, operator="admin")

        assert result["ok"] is True
        assert result["status"] == "passed"
        assert result["writes_formal_tables"] is False
        assert result["transaction_plan"]["mode"] == "simulation"
        assert result["transaction_plan"]["operations"][0]["operation"] == "upsert"
        assert result["transaction_plan"]["operations"][0]["target_table"] == "kb_product"
        assert "dimensions" in result["transaction_plan"]["operations"][0]["fields"]
        assert db.query(KnowledgeGapPublishAudit).count() == 1
        assert db.query(KBProduct).count() == 0
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"publish_dry_run_status": "failed"}, "publish dry-run must pass"),
        ({"ready_for_publish": False}, "not ready_for_publish"),
        ({"pre_publish_retest_status": "failed"}, "pre-publish retest must pass"),
        ({"approved_to_publish": False}, "not approved_to_publish"),
        ({"approval_status": "retest_required"}, "approval_status must be approved_to_publish"),
        ({"locked_payload_fingerprint": ""}, "locked_payload_fingerprint is required"),
        ({"locked_payload_fingerprint": "different"}, "payload changed after approval"),
        ({"status": "superseded"}, "superseded queue items cannot be simulated"),
        ({"status": "rejected"}, "rejected queue items cannot be simulated"),
        ({"status": "cancelled"}, "cancelled queue items cannot be simulated"),
    ],
)
def test_gate_blocks_when_required_publish_contract_is_not_met(overrides, reason):
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, **overrides)

        result = KnowledgeGapPublishGateService().simulate_publish(db, item.queue_uid, operator="admin")

        assert result["ok"] is False
        assert result["status"] == "blocked"
        assert any(reason in block for block in result["block_reasons"])
        audit = db.query(KnowledgeGapPublishAudit).one()
        assert audit.status == "blocked"
        assert audit.writes_formal_tables is False
    finally:
        db.close()


def test_context_extractor_is_blocked_and_audited():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(
            db,
            target="context_extractor",
            payload={"context_field": "product_identity"},
        )

        result = KnowledgeGapPublishGateService().simulate_publish(db, item.queue_uid, operator="admin")

        assert result["ok"] is False
        assert any("engineering task" in reason for reason in result["block_reasons"])
        assert db.query(KnowledgeGapPublishAudit).count() == 1
    finally:
        db.close()


def test_media_asset_without_uploaded_asset_or_url_is_blocked():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(
            db,
            target="kb_media_asset",
            payload={
                "asset_type": "video",
                "media_purpose": "installation",
                "bind_to_sku": "sku-001",
            },
        )

        result = KnowledgeGapPublishGateService().simulate_publish(db, item.queue_uid, operator="admin")

        assert result["ok"] is False
        assert any("uploaded_asset_id or asset_url" in reason for reason in result["block_reasons"])
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


def test_audit_validation_uses_summary_not_full_payload():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db)

        result = KnowledgeGapPublishGateService().simulate_publish(db, item.queue_uid, operator="admin")
        audit = db.query(KnowledgeGapPublishAudit).filter(KnowledgeGapPublishAudit.audit_uid == result["audit_uid"]).one()

        validation = audit.get_validation_result()
        assert "payload_summary" in validation
        assert "payload" not in validation
        assert validation["payload_summary"]["field_names"] == ["dimensions"]
    finally:
        db.close()
