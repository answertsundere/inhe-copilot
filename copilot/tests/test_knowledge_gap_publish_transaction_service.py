from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import KnowledgeGapPublishQueue
from app.services.knowledge_gap_publish_queue_service import payload_fingerprint
from app.services.knowledge_gap_publish_transaction_service import KnowledgeGapPublishTransactionService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _queue(db, *, target="product_profile", payload=None):
    clean_payload = payload or {
        "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
        "fields": {"dimensions": "100x40x120cm"},
    }
    fingerprint = payload_fingerprint(target, clean_payload)
    item = KnowledgeGapPublishQueue(
        queue_uid=f"kgpub_tx_{target}",
        task_uid=f"kgap_tx_{target}",
        draft_uid=f"kgdraft_tx_{target}",
        publish_target=target,
        payload_fingerprint=fingerprint,
        locked_payload_fingerprint=fingerprint,
        reviewer="lead",
        risk_level="medium",
        status="queued",
        export_status="not_exported",
    )
    item.set_payload(clean_payload)
    db.add(item)
    db.commit()
    return item


def _assert_standard_plan(plan):
    assert plan["plan_version"] == "v1"
    assert plan["mode"] == "simulation"
    assert plan["writes_formal_tables"] is False
    assert plan["publish_enabled"] is False
    assert plan["requires_transaction"] is True
    assert plan["requires_pre_publish_gate"] is True
    assert plan["requires_post_publish_retest"] is True
    assert plan["rollback_supported"] is False
    assert plan["adapter_capability"]["supports_formal_publish"] is False
    assert plan["adapter_capability"]["supports_rollback"] is False
    for step in plan["steps"]:
        assert step["step_id"]
        assert step["operation"]
        assert "rollback" in step
        assert step["rollback"]["strategy"]


def test_product_profile_builds_validate_and_upsert_steps():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db)

        plan = KnowledgeGapPublishTransactionService().build_plan(item)

        _assert_standard_plan(plan)
        assert [step["step_id"] for step in plan["steps"]] == ["validate_product_identity", "upsert_product_profile"]
        assert plan["steps"][1]["target_table"] == "kb_product"
        assert "dimensions" in plan["steps"][1]["fields"]
        assert plan["block_reasons"] == []
    finally:
        db.close()


def test_kb_product_builds_fact_upsert_plan():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="kb_product", payload={
            "product_identity": {"item_id": "item-001"},
            "fact_type": "material",
            "evidence_text": "engineered wood",
            "source_reference": "manual",
        })

        plan = KnowledgeGapPublishTransactionService().build_plan(item)

        _assert_standard_plan(plan)
        assert [step["step_id"] for step in plan["steps"]] == ["validate_fact_payload", "upsert_product_fact"]
        assert plan["steps"][1]["target_table"] == "kb_product_facts"
        assert plan["steps"][1]["match_key"] == "product_identity + fact_type"
    finally:
        db.close()


def test_media_asset_without_asset_builds_upload_request_and_blocks_formal_publish():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="kb_media_asset", payload={
            "asset_type": "video",
            "media_purpose": "installation",
            "bind_to_sku": "sku-001",
        })

        plan = KnowledgeGapPublishTransactionService().build_plan(item)

        _assert_standard_plan(plan)
        assert [step["step_id"] for step in plan["steps"]] == ["validate_media_asset_request", "create_media_upload_request"]
        assert "media asset missing uploaded_asset_id or asset_url" in plan["block_reasons"]
        assert plan["adapter_capability"]["supports_formal_publish"] is False
    finally:
        db.close()


def test_context_extractor_is_engineering_task_plan_only():
    session_factory = _session_factory()
    db = session_factory()
    try:
        item = _queue(db, target="context_extractor", payload={"context_field": "product_identity"})

        plan = KnowledgeGapPublishTransactionService().build_plan(item)

        _assert_standard_plan(plan)
        assert plan["steps"][0]["step_id"] == "engineering_task_plan"
        assert "engineering task cannot publish to knowledge store" in plan["block_reasons"]
    finally:
        db.close()


def test_validate_plan_rejects_illegal_publish_plan():
    service = KnowledgeGapPublishTransactionService()

    result = service.validate_plan({
        "plan_version": "v1",
        "mode": "simulation",
        "writes_formal_tables": True,
        "publish_enabled": False,
        "adapter_capability": {"supports_formal_publish": False},
        "steps": [{"operation": "upsert", "rollback": {}}],
    })

    assert result["ok"] is False
    assert "writes_formal_tables must be false" in result["errors"]
    assert "step 0 missing step_id" in result["errors"]
    assert "step 0 missing rollback strategy" in result["errors"]


def test_capabilities_return_all_targets_disabled():
    result = KnowledgeGapPublishTransactionService().capabilities()

    assert result["publish_enabled"] is False
    assert result["writes_formal_tables"] is False
    for target in [
        "product_profile",
        "kb_product",
        "kb_media_asset",
        "activity_rules",
        "aftersales_policy",
        "context_extractor",
    ]:
        assert target in result["targets"]
        assert result["targets"][target]["supports_formal_publish"] is False
