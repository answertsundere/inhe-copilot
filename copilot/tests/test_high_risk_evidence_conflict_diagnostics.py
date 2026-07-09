from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import EvalRun, EvalTrace


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def test_high_risk_conflict_diagnosis_detects_numeric_conflict():
    import scripts.diagnose_high_risk_evidence_conflicts as script

    Session = _session_factory()
    db = Session()
    db.add(EvalRun(run_uid="run-1", source_type="real_conversation", status="completed"))
    trace = EvalTrace(
        run_uid="run-1",
        case_uid="case-1",
        turn_uid="turn-1",
        buyer_message="能放多少斤",
        query_fact_type="load_capacity",
        requires_human_review=True,
    )
    trace.set_raw_response({"sidecar_context": {"product_title": "商品A", "sku_code": "SKU-1", "i_id": "IID-1"}})
    trace.set_selected_evidence([
        {"source_type": "product_facts", "evidence_fact_type": "load_capacity", "chunk_preview": "每层承重5-10kg左右"},
        {"source_type": "faq", "evidence_fact_type": "load_capacity", "chunk_preview": "每层承重15-25kg"},
    ])
    db.add(trace)
    db.commit()
    db.close()

    result = script.diagnose_high_risk_evidence_conflicts(run_uid="run-1", db_factory=Session)

    assert result["summary"]["by_conflict_category"]["numeric_conflict"] == 1
    row = result["rows"][0]
    assert row["must_block_or_handoff"] is True
    assert set(row["claims"]) == {"5-10kg", "15-25kg"}


def test_high_risk_conflict_diagnosis_allows_single_consistent_value():
    import scripts.diagnose_high_risk_evidence_conflicts as script

    Session = _session_factory()
    db = Session()
    db.add(EvalRun(run_uid="run-1", source_type="real_conversation", status="completed"))
    trace = EvalTrace(
        run_uid="run-1",
        case_uid="case-1",
        turn_uid="turn-1",
        buyer_message="毛重多少",
        query_fact_type="load_capacity",
    )
    trace.set_selected_evidence([
        {"source_type": "product_facts", "evidence_fact_type": "load_capacity", "chunk_preview": "每层承重5-10kg左右"},
        {"source_type": "product_facts", "evidence_fact_type": "load_capacity", "chunk_preview": "建议按5-10kg使用"},
    ])
    db.add(trace)
    db.commit()
    db.close()

    result = script.diagnose_high_risk_evidence_conflicts(run_uid="run-1", db_factory=Session)

    assert result["summary"]["by_conflict_category"]["no_conflict"] == 1
    assert result["rows"][0]["must_block_or_handoff"] is False
