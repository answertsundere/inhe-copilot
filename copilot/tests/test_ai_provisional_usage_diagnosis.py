from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def usage_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import AIProvisionalKnowledge, EvalRun, EvalTrace

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
        ],
    )
    return session_factory


def _add_run(db, run_uid: str):
    from app.models.eval_tables import EvalRun

    db.add(EvalRun(
        run_uid=run_uid,
        source_type="real_conversation",
        status="completed",
        total_turns=1,
        passed_turns=0,
        failed_turns=1,
    ))
    db.commit()


def _provisional_pack(*, with_item_identity: bool = False):
    resolved_identity = {
        "product_id": 17,
        "i_id": "YH90K01",
        "sku": "YH90K01B01S01",
        "identity_sources": ["sku_exact"],
    }
    items = []
    for uid in ("aipk_one", "aipk_two"):
        item = {
            "evidence_id": uid,
            "source_table": "ai_provisional_knowledge",
            "protocol_source_type": "ai_prefill",
            "provisional_knowledge_used": True,
            "provisional_draft_uid": uid,
            "fact_type": "promotion",
            "usable_for_eval": True,
            "usable_for_auto_send": False,
            "needs_human_review": True,
        }
        if with_item_identity:
            item.update({
                "i_id": "YH90K01",
                "sku_code": "YH90K01B01S01",
                "kb_product_id": 17,
                "identity_status": "resolved",
                "identity_sources": ["ai_provisional_identity_binding"],
            })
        items.append(item)
    return {
        "resolved_product_identity": resolved_identity,
        "ai_provisional_knowledge": items,
        "matched_facts": items,
        "product_scoped_chunks": items,
    }


def _add_trace(db, *, run_uid: str, turn_uid: str = "turn_one", fact_type: str = "promotion_policy", pack=None):
    from app.models.eval_tables import EvalTrace

    trace = EvalTrace(
        run_uid=run_uid,
        case_uid=f"case_{turn_uid}",
        turn_uid=turn_uid,
        turn_index=1,
        buyer_message="Can you confirm the promotion?",
        agent_reply="Please confirm with support.",
        query_fact_type=fact_type,
        passed=False,
        requires_human_review=True,
    )
    if pack is not None:
        trace.set_raw_response({
            "can_send": False,
            "sendable_reply": "",
            "requires_human_review": True,
            "reply_delivery": {"auto_send_ready": False},
            "quality_bucket": {"quality_bucket": "knowledge_gap"},
            "evidence_debug": {
                "product_context_pack_summary": {
                    "evidence_pack": pack,
                }
            },
        })
    db.add(trace)
    db.commit()
    return trace


def _add_draft(
    db,
    *,
    draft_uid: str = "aipk_one",
    fact_type: str = "promotion",
    i_id: str = "YH90K01",
    sku_code: str = "YH90K01B01S01",
    kb_product_id: int | None = 17,
):
    from app.models.eval_tables import AIProvisionalKnowledge

    draft = AIProvisionalKnowledge(
        draft_uid=draft_uid,
        source_run_uid="source_run",
        case_uid="case_turn_one",
        turn_uid="turn_one",
        task_uid=f"task_{draft_uid}",
        i_id=i_id,
        sku_code=sku_code if i_id else "",
        kb_product_id=kb_product_id if i_id else None,
        query_fact_type=fact_type,
        field_name=fact_type,
        provisional_answer="Please confirm the promotion with support.",
        confidence="medium",
        verification_status="pending_review",
        usable_for_eval=True,
        usable_for_auto_send=False,
    )
    db.add(draft)
    db.commit()
    return draft


def test_compare_report_lists_all_provisional_evidence_with_identity_fallback(usage_db, monkeypatch):
    import scripts.compare_replay_knowledge_modes as compare

    monkeypatch.setattr(compare, "SessionLocal", usage_db)
    db = usage_db()
    try:
        _add_run(db, "run_a")
        _add_run(db, "run_b")
        _add_trace(db, run_uid="run_a", pack=None)
        _add_trace(db, run_uid="run_b", pack=_provisional_pack(with_item_identity=False))
        _add_draft(db, draft_uid="aipk_one")
        _add_draft(db, draft_uid="aipk_two")
    finally:
        db.close()

    result = compare.compare_modes("run_a", sample_limit=10, provisional_run_uid="run_b")

    summary = result["summary"]
    assert summary["same_case_sequence"] is True
    assert summary["provisional_used_turn_count"] == 1
    assert summary["provisional_used_evidence_count"] == 2
    turn = result["provisional_used_turns"][0]
    assert len(turn["provisional_evidence"]) == 2
    assert turn["provisional_evidence"][0]["i_id"] == "YH90K01"
    assert turn["provisional_evidence"][0]["sku_code"] == "YH90K01B01S01"
    assert turn["provisional_evidence"][0]["identity_status"] == "resolved"
    assert turn["can_send"] is False
    assert turn["requires_human_review"] is True


def test_diagnose_usage_reports_used_and_fact_type_alias(usage_db, monkeypatch):
    import scripts.diagnose_ai_provisional_usage as diagnose

    monkeypatch.setattr(diagnose, "SessionLocal", usage_db)
    db = usage_db()
    try:
        _add_run(db, "run_b")
        _add_trace(db, run_uid="run_b", pack=_provisional_pack(with_item_identity=True))
        _add_draft(db, draft_uid="aipk_one", fact_type="promotion")
        _add_draft(db, draft_uid="aipk_two", fact_type="promotion")
    finally:
        db.close()

    result = diagnose.diagnose_usage("run_b")

    assert result["miss_reason_counts"]["used"] == 2
    rows = {item["draft_uid"]: item for item in result["drafts"]}
    assert rows["aipk_one"]["appears_alias_query_fact_type_in_replay"] is True
    assert rows["aipk_one"]["appears_same_identity_in_replay"] is True
    assert rows["aipk_one"]["used"] is True


def test_diagnose_usage_reports_no_replay_turn_for_identity(usage_db, monkeypatch):
    import scripts.diagnose_ai_provisional_usage as diagnose

    monkeypatch.setattr(diagnose, "SessionLocal", usage_db)
    db = usage_db()
    try:
        _add_run(db, "run_b")
        _add_trace(db, run_uid="run_b", pack=_provisional_pack(with_item_identity=True))
        _add_draft(
            db,
            draft_uid="aipk_missing",
            fact_type="promotion",
            i_id="YH91K01",
            sku_code="YH91K01B01S01",
            kb_product_id=18,
        )
    finally:
        db.close()

    result = diagnose.diagnose_usage("run_b")

    rows = {item["draft_uid"]: item for item in result["drafts"]}
    assert rows["aipk_missing"]["miss_reason"] == "no_replay_turn_for_identity"
