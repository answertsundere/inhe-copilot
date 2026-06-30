from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def provisional_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import AIProvisionalKnowledge, EvalRun, EvalTrace, KnowledgeGapTask, KnowledgeGapTaskSample
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

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
            EvalRun.__table__,
            EvalTrace.__table__,
            KnowledgeGapTask.__table__,
            KnowledgeGapTaskSample.__table__,
            KBProduct.__table__,
            KBQA.__table__,
            KBMediaAsset.__table__,
            KBProductActivityRule.__table__,
            KnowledgeEntry.__table__,
            KnowledgeChunk.__table__,
            KBGenericServiceRule.__table__,
        ],
    )
    return session_factory


def _add_product(db):
    from app.models.kb_tables import KBProduct

    product = KBProduct(
        i_id="YH77K01",
        product_name="Storage cabinet",
        status="published",
        sku_list_json=json.dumps([{"sku_code": "YH77K01B01S01"}], ensure_ascii=False),
    )
    db.add(product)
    db.commit()
    return product


def _add_gap_task(db, *, fact_type: str = "installation", reference_reply: str = "The small tool is used during assembly."):
    from app.models.eval_tables import KnowledgeGapTask, KnowledgeGapTaskSample

    task = KnowledgeGapTask(
        task_uid=f"kgap_ai_{fact_type}",
        gap_type="product_field_gap",
        product_title="Storage cabinet",
        item_id="YH77K01",
        sku_code="YH77K01B01S01",
        query_fact_type=fact_type,
        failure_type="rag_miss",
        suggested_fix_area="knowledge_ops",
        suggested_owner="knowledge_ops",
        missing_evidence_type=fact_type,
        status="open",
        sample_count=1,
    )
    task.set_metadata({"source_run_uid": "run_ai_prefill"})
    task.set_related_turn_uids(["turn_ai_1"])
    db.add(task)
    db.add(KnowledgeGapTaskSample(
        task_uid=task.task_uid,
        run_uid="run_ai_prefill",
        case_uid="case_ai_1",
        turn_uid="turn_ai_1",
        buyer_message="How to use this part?",
        reference_human_reply=reference_reply,
        failure_type="rag_miss",
        query_fact_type=fact_type,
    ))
    db.commit()
    return task


def test_generate_ai_prefill_draft_never_writes_verified(provisional_db):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService

    db = provisional_db()
    try:
        _add_product(db)
        _add_gap_task(db)
    finally:
        db.close()

    result = AIProvisionalKnowledgeService().generate_for_run(
        run_uid="run_ai_prefill",
        apply=True,
        db_factory=provisional_db,
    )

    assert result["generated_count"] == 1
    db = provisional_db()
    try:
        row = db.query(AIProvisionalKnowledge).one()
        assert row.source == "ai_prefill"
        assert row.verification_status != "verified"
        assert row.usable_for_eval is True
        assert row.usable_for_auto_send is False
    finally:
        db.close()


def test_high_risk_ai_prefill_is_low_confidence_pending_review(provisional_db):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService

    db = provisional_db()
    try:
        _add_product(db)
        _add_gap_task(db, fact_type="certification_report", reference_reply="Please check the report with support.")
    finally:
        db.close()

    AIProvisionalKnowledgeService().generate_for_run(
        run_uid="run_ai_prefill",
        apply=True,
        db_factory=provisional_db,
    )

    db = provisional_db()
    try:
        row = db.query(AIProvisionalKnowledge).one()
        assert row.confidence == "low"
        assert row.verification_status == "pending_review"
        assert row.usable_for_auto_send is False
    finally:
        db.close()


def test_short_acknowledgement_is_not_used_as_high_risk_prefill(provisional_db):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService

    db = provisional_db()
    try:
        _add_gap_task(db, fact_type="load_capacity", reference_reply="好的亲")
    finally:
        db.close()

    AIProvisionalKnowledgeService().generate_for_run(
        run_uid="run_ai_prefill",
        apply=True,
        db_factory=provisional_db,
    )

    db = provisional_db()
    try:
        row = db.query(AIProvisionalKnowledge).one()
        assert row.provisional_answer == ""
        assert row.provisional_value == ""
        assert row.usable_for_eval is False
        assert row.usable_for_auto_send is False
    finally:
        db.close()


def test_default_verified_only_does_not_use_ai_prefill(provisional_db, monkeypatch):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.product_context_pack_service import build_product_context_pack

    db = provisional_db()
    try:
        _add_product(db)
        row = AIProvisionalKnowledge(
            draft_uid="aipk_default_off",
            i_id="YH77K01",
            sku_code="YH77K01B01S01",
            query_fact_type="installation",
            field_name="installation",
            provisional_answer="Use the small tool during assembly.",
            verification_status="pending_review",
            usable_for_eval=True,
            usable_for_auto_send=False,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()
    monkeypatch.delenv("COPILOT_EVAL_KNOWLEDGE_MODE", raising=False)

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH77K01B01S01"}},
        query="How to install?",
        allowed_source_types=["product_facts"],
        query_fact_type="installation",
    )

    evidence_pack = pack["product_first_evidence_pack"]
    assert evidence_pack["knowledge_mode"] == "verified_only"
    assert evidence_pack["ai_provisional_knowledge"] == []
    assert evidence_pack["provisional_knowledge_used"] is False


def test_eval_mode_uses_ai_prefill_but_not_auto_send(provisional_db, monkeypatch):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.product_context_pack_service import build_product_context_pack

    db = provisional_db()
    try:
        _add_product(db)
        row = AIProvisionalKnowledge(
            draft_uid="aipk_eval_on",
            i_id="YH77K01",
            sku_code="YH77K01B01S01",
            query_fact_type="installation",
            field_name="installation",
            provisional_answer="Use the small tool during assembly.",
            confidence="medium",
            verification_status="pending_review",
            usable_for_eval=True,
            usable_for_auto_send=False,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()
    monkeypatch.setenv("COPILOT_EVAL_KNOWLEDGE_MODE", "verified_plus_ai_prefill")

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH77K01B01S01"}},
        query="How to install?",
        allowed_source_types=["product_facts"],
        query_fact_type="installation",
    )

    evidence_pack = pack["product_first_evidence_pack"]
    assert evidence_pack["knowledge_mode"] == "verified_plus_ai_prefill"
    assert evidence_pack["provisional_knowledge_used"] is True
    assert evidence_pack["answerability"] == "provisional_answerable"
    provisional = evidence_pack["ai_provisional_knowledge"][0]
    assert provisional["provisional_draft_uid"] == "aipk_eval_on"
    assert provisional["usable_for_eval"] is True
    assert provisional["usable_for_auto_send"] is False


def test_eval_mode_matches_promotion_fact_type_alias(provisional_db, monkeypatch):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.product_context_pack_service import build_product_context_pack

    db = provisional_db()
    try:
        _add_product(db)
        db.add(AIProvisionalKnowledge(
            draft_uid="aipk_eval_promotion_alias",
            i_id="YH77K01",
            sku_code="YH77K01B01S01",
            query_fact_type="promotion",
            field_name="promotion",
            provisional_answer="Please confirm the current promotion with support.",
            confidence="medium",
            verification_status="pending_review",
            usable_for_eval=True,
            usable_for_auto_send=False,
        ))
        db.commit()
    finally:
        db.close()
    monkeypatch.setenv("COPILOT_EVAL_KNOWLEDGE_MODE", "verified_plus_ai_prefill")

    pack = build_product_context_pack(
        {"slots": {"sku_code": "YH77K01B01S01"}},
        query="Any discount?",
        allowed_source_types=["product_facts"],
        query_fact_type="promotion_policy",
    )

    evidence_pack = pack["product_first_evidence_pack"]
    assert evidence_pack["provisional_knowledge_used"] is True
    assert evidence_pack["ai_provisional_knowledge"][0]["provisional_draft_uid"] == "aipk_eval_promotion_alias"


def test_generate_reply_requires_review_when_using_ai_prefill():
    from app.agent.nodes.generate_reply import generate_reply

    pack = {
        "resolved_product_identity": {"product_name": "Storage cabinet", "sku": "YH77K01B01S01"},
        "identity_confidence": 0.95,
        "requested_fact_type": "installation",
        "query_fact_type": "installation",
        "answerability": "provisional_answerable",
        "product_structured_facts": [],
        "product_media_assets": [],
        "product_scoped_chunks": [{
            "evidence_id": "aipk_eval_on",
            "source_table": "ai_provisional_knowledge",
            "protocol_source_type": "ai_prefill",
            "fact_type": "installation",
            "preview": "Use the small tool during assembly.",
            "provisional_knowledge_used": True,
            "provisional_draft_uid": "aipk_eval_on",
            "usable_for_eval": True,
            "usable_for_auto_send": False,
            "direct_answer_allowed": True,
            "can_direct_answer": True,
        }],
        "generic_fallback_rules": [],
        "missing_required_evidence": [],
        "evidence_pack_trace": {"product_identity_locked": True},
    }
    result = generate_reply({
        "intent": "product_question",
        "customer_message": "How to install?",
        "normalized_message": "How to install?",
        "query_fact_type": "installation",
        "matched_product_name": "Storage cabinet",
        "product_first_evidence_pack": pack,
        "product_context_pack": {"product_first_evidence_pack": pack, "evidence_pack": pack},
        "trace_steps": [],
    })

    assert "small tool" in result["suggested_reply"]
    assert result["requires_human_review"] is True
    assert result["review_reason"] == "ai_provisional_knowledge_requires_review"
    trace = result["trace_steps"][-1]
    assert trace["provisional_knowledge_used"] is True
    assert trace["usable_for_auto_send"] is False
    assert trace["can_send"] is False


def test_import_rejects_verified_status(provisional_db):
    from app.models.eval_tables import AIProvisionalKnowledge
    from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService

    result = AIProvisionalKnowledgeService().import_rows(
        [{
            "draft_uid": "aipk_verified_blocked",
            "i_id": "YH77K01",
            "sku_code": "YH77K01B01S01",
            "query_fact_type": "installation",
            "provisional_answer": "Use it during assembly.",
            "verification_status": "verified",
        }],
        apply=True,
        db_factory=provisional_db,
    )

    assert result["matched_count"] == 0
    assert result["skipped_reasons"][0]["reason"] == "verified_status_not_allowed"
    db = provisional_db()
    try:
        assert db.query(AIProvisionalKnowledge).count() == 0
    finally:
        db.close()
