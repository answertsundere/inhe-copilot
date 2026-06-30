from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.eval_sanitizer_service import hash_sensitive


@pytest.fixture()
def identity_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import AIProvisionalKnowledge, EvalTrace, KnowledgeGapTask, KnowledgeGapTaskSample
    from app.models.kb_tables import KBProduct, ProductIdentityMapping

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(
        bind=engine,
        tables=[
            AIProvisionalKnowledge.__table__,
            EvalTrace.__table__,
            KnowledgeGapTask.__table__,
            KnowledgeGapTaskSample.__table__,
            KBProduct.__table__,
            ProductIdentityMapping.__table__,
        ],
    )
    return session_factory


def _add_product(db, *, i_id: str = "YH80K01", sku_code: str = "YH80K01B01S01", name: str = "Storage rack"):
    from app.models.kb_tables import KBProduct

    product = KBProduct(
        i_id=i_id,
        product_name=name,
        status="published",
        sku_list_json=json.dumps([{"sku_code": sku_code}], ensure_ascii=False),
    )
    db.add(product)
    db.commit()
    return product


def _add_task(db, *, task_uid: str = "kgap_bind_1", turn_uid: str = "turn_bind_1"):
    from app.models.eval_tables import KnowledgeGapTask, KnowledgeGapTaskSample

    task = KnowledgeGapTask(
        task_uid=task_uid,
        gap_type="product_field_gap",
        product_title="Storage rack",
        query_fact_type="installation",
        failure_type="rag_miss",
        suggested_fix_area="knowledge_ops",
        suggested_owner="knowledge_ops",
        missing_evidence_type="installation",
        sample_count=1,
    )
    task.set_metadata({"source_run_uid": "run_bind"})
    task.set_related_turn_uids([turn_uid])
    db.add(task)
    db.add(KnowledgeGapTaskSample(
        task_uid=task_uid,
        run_uid="run_bind",
        case_uid=f"case_{turn_uid}",
        turn_uid=turn_uid,
        buyer_message="How to use the accessory?",
        reference_human_reply="Use it during assembly.",
        failure_type="rag_miss",
        query_fact_type="installation",
    ))
    db.commit()
    return task


def _add_trace(db, *, turn_uid: str, identity: dict):
    from app.models.eval_tables import EvalTrace

    trace = EvalTrace(
        run_uid="run_bind",
        case_uid=f"case_{turn_uid}",
        turn_uid=turn_uid,
        buyer_message="How to use it?",
        query_fact_type="installation",
        passed=False,
    )
    trace.set_product_identity(identity)
    trace.set_raw_response({"product_identity_resolution": identity})
    db.add(trace)
    db.commit()
    return trace


def test_resolved_identity_from_eval_trace(identity_db):
    from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService

    db = identity_db()
    try:
        product = _add_product(db)
        task = _add_task(db)
        _add_trace(db, turn_uid="turn_bind_1", identity={
            "status": "resolved",
            "i_id": product.i_id,
            "sku_code": "YH80K01B01S01",
            "identity_confidence": 0.98,
        })

        result = AIProvisionalIdentityBindingService().bind_for_task(db, task)

        assert result.identity_status == "resolved"
        assert result.i_id == product.i_id
        assert result.sku_code == "YH80K01B01S01"
        assert result.kb_product_id == product.id
    finally:
        db.close()


def test_resolved_identity_from_product_identity_mapping(identity_db):
    from app.models.kb_tables import ProductIdentityMapping
    from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService

    item_hash = hash_sensitive("123456789012")
    db = identity_db()
    try:
        product = _add_product(db)
        db.add(ProductIdentityMapping(
            mapping_uid="pim_bind_1",
            platform_item_id_hash=item_hash,
            kb_product_id=product.id,
            i_id=product.i_id,
            sku_code="YH80K01B01S01",
            status="active",
            confidence=1.0,
        ))
        task = _add_task(db)
        _add_trace(db, turn_uid="turn_bind_1", identity={"item_id_hash": item_hash})

        result = AIProvisionalIdentityBindingService().bind_for_task(db, task)

        assert result.identity_status == "resolved"
        assert result.i_id == product.i_id
        assert "product_identity_mappings" in result.identity_sources
    finally:
        db.close()


def test_title_only_identity_is_not_bound(identity_db):
    from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService

    db = identity_db()
    try:
        _add_product(db)
        task = _add_task(db)
        _add_trace(db, turn_uid="turn_bind_1", identity={"product_title": "Storage rack"})

        result = AIProvisionalIdentityBindingService().bind_for_task(db, task)

        assert result.identity_status in {"ambiguous", "unresolved"}
        assert result.i_id == ""
        assert result.skipped_reason in {"weak_or_ambiguous_identity_only", "no_identity_signal"}
    finally:
        db.close()


def test_conflicting_linked_turns_are_not_bound(identity_db):
    from app.models.eval_tables import KnowledgeGapTaskSample
    from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService

    db = identity_db()
    try:
        first = _add_product(db, i_id="YH80K01", sku_code="YH80K01B01S01", name="First rack")
        second = _add_product(db, i_id="YH80K02", sku_code="YH80K02B01S01", name="Second rack")
        task = _add_task(db)
        task.set_related_turn_uids(["turn_bind_1", "turn_bind_2"])
        db.add(task)
        db.add(KnowledgeGapTaskSample(
            task_uid=task.task_uid,
            run_uid="run_bind",
            case_uid="case_turn_bind_2",
            turn_uid="turn_bind_2",
            buyer_message="Another product question",
            reference_human_reply="Use it during assembly.",
            failure_type="rag_miss",
            query_fact_type="installation",
        ))
        _add_trace(db, turn_uid="turn_bind_1", identity={"status": "resolved", "i_id": first.i_id, "identity_confidence": 1.0})
        _add_trace(db, turn_uid="turn_bind_2", identity={"status": "resolved", "i_id": second.i_id, "identity_confidence": 1.0})
        db.commit()

        result = AIProvisionalIdentityBindingService().bind_for_task(db, task)

        assert result.identity_status == "conflict"
        assert result.skipped_reason == "identity_conflict"
        assert result.i_id == ""
    finally:
        db.close()


def test_generate_writes_resolved_identity_and_keeps_auto_send_disabled(identity_db):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService

    db = identity_db()
    try:
        product = _add_product(db)
        _add_task(db)
        _add_trace(db, turn_uid="turn_bind_1", identity={
            "status": "resolved",
            "i_id": product.i_id,
            "sku_code": "YH80K01B01S01",
            "identity_confidence": 0.99,
        })
    finally:
        db.close()

    result = AIProvisionalKnowledgeService().generate_for_run(
        run_uid="run_bind",
        apply=True,
        db_factory=identity_db,
    )

    assert result["generated_count"] == 1
    db = identity_db()
    try:
        row = db.query(AIProvisionalKnowledge).one()
        assert row.i_id == "YH80K01"
        assert row.sku_code == "YH80K01B01S01"
        assert row.kb_product_id is not None
        assert row.usable_for_eval is True
        assert row.usable_for_auto_send is False
        assert row.get_metadata()["identity_status"] == "resolved"
    finally:
        db.close()
