from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import EvalRun, EvalTrace


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _add_trace(db, *, buyer, sidecar_title="三层火箭书架", bucket="agent_error", labels=None, turn_uid="turn-1"):
    trace = EvalTrace(
        run_uid="run-1",
        case_uid="case-1",
        turn_uid=turn_uid,
        buyer_message=buyer,
        agent_reply="亲，我帮您核对一下。",
        query_fact_type="material",
        passed=False,
        requires_human_review=True,
    )
    trace.set_raw_response({
        "sidecar_context": {
            "product_title": sidecar_title,
            "sku_code": "SKU-1",
            "i_id": "IID-1",
            "sidecar_context_quality": "complete",
            "sidecar_context_sources": ["sidecar_product_title"],
        },
        "quality_bucket": {"quality_bucket": bucket},
        "sidecar_mode": "global",
        "sidecar_fixture_used": True,
        "eval_replay_options": {"eval_sidecar_mode": "global"},
    })
    trace.set_product_identity({"real_context_product_identity": {}})
    trace.set_failure_labels(labels or ["semantic_mismatch"])
    db.add(trace)
    return trace


def test_sidecar_mismatch_diagnosis_marks_eval_fixture_gap_for_cross_product_buyer_text():
    import scripts.diagnose_replay_sidecar_product_mismatch as script

    Session = _session_factory()
    db = Session()
    db.add(EvalRun(run_uid="run-1", source_type="real_conversation", status="completed"))
    _add_trace(db, buyer="这个餐椅的台面是什么材质啊")
    db.commit()
    db.close()

    result = script.diagnose_sidecar_product_mismatch(run_uid="run-1", db_factory=Session)

    assert result["summary"]["classification_counts"]["buyer_mentions_other_product"] == 1
    assert result["summary"]["agent_error_eval_fixture_gap_count"] == 1
    row = result["rows"][0]
    assert row["quality_bucket"] == "agent_error"
    assert row["adjusted_quality_bucket"] == "eval_fixture_gap"
    assert row["buyer_mentions_other_product"] is True


def test_sidecar_mismatch_diagnosis_keeps_matching_product_as_no_mismatch():
    import scripts.diagnose_replay_sidecar_product_mismatch as script

    Session = _session_factory()
    db = Session()
    db.add(EvalRun(run_uid="run-1", source_type="real_conversation", status="completed"))
    _add_trace(db, buyer="这个书架是什么材质啊", bucket="safe_handoff")
    db.commit()
    db.close()

    result = script.diagnose_sidecar_product_mismatch(run_uid="run-1", db_factory=Session)

    assert result["summary"]["classification_counts"]["no_mismatch"] == 1
    assert result["summary"]["agent_error_eval_fixture_gap_count"] == 0
    assert result["rows"][0]["adjusted_quality_bucket"] == "safe_handoff"


def test_sidecar_mismatch_diagnosis_marks_per_sample_missing_context():
    import scripts.diagnose_replay_sidecar_product_mismatch as script

    Session = _session_factory()
    db = Session()
    db.add(EvalRun(run_uid="run-1", source_type="real_conversation", status="completed"))
    trace = _add_trace(db, buyer="dimensions?", sidecar_title="", bucket="context_gap")
    trace.set_raw_response({
        "sidecar_context": {
            "sidecar_context_quality": "missing",
            "sidecar_context_sources": [],
        },
        "quality_bucket": {"quality_bucket": "context_gap"},
        "sidecar_mode": "per_sample",
        "sidecar_fixture_used": False,
        "eval_replay_options": {"eval_sidecar_mode": "per_sample"},
    })
    db.commit()
    db.close()

    result = script.diagnose_sidecar_product_mismatch(run_uid="run-1", db_factory=Session)

    assert result["summary"]["classification_counts"]["per_sample_missing_context"] == 1
    row = result["rows"][0]
    assert row["adjusted_quality_bucket"] == "context_gap"
    assert row["sidecar"]["mode"] == "per_sample"
