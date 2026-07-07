from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _session_factory(tmp_path):
    from app.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'compare.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


class _FakeSQLiteRetriever:
    def retrieve(self, **kwargs):
        return [{"chunk_id": "1", "chunk_text": "安装说明", "source_type": "faq"}]


class _FakePgService:
    def check(self):
        return {"pgvector_available": True, "extension_available": True, "error": ""}

    def retrieve(self, **kwargs):
        return [{
            "chunk_id": "pgvector:1",
            "chunk_text": "安装说明",
            "source_type": "faq",
            "metadata": {"direct_answer_allowed": True},
        }]

    def fetch_rows_by_source_ids(self, source_chunk_ids):
        return {
            "1": {
                "source_chunk_id": "1",
                "query_fact_type": "installation",
                "source_type": "faq",
                "i_id": "IID-1",
                "sku_code": "SKU-1",
                "usable_for_agent": True,
            }
        }


class _UnavailablePgService:
    def check(self):
        return {"pgvector_available": False, "extension_available": False, "error": "missing_dsn"}


class _ExplodingSQLiteRetriever:
    def retrieve(self, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("sqlite retriever should not run when pgvector is unavailable")


def test_shadow_compare_does_not_mutate_eval_trace(tmp_path):
    from app.models.eval_tables import EvalRun, EvalTrace
    from scripts.compare_sqlite_pgvector_retrieval import compare_retrieval

    Session = _session_factory(tmp_path)
    db = Session()
    try:
        db.add(EvalRun(run_uid="run-shadow", source_type="real_conversation", status="completed", total_turns=1))
        trace = EvalTrace(
            run_uid="run-shadow",
            case_uid="case-1",
            turn_uid="turn-1",
            turn_index=1,
            buyer_message="有安装说明吗",
            query_fact_type="installation",
        )
        trace.set_raw_response({
            "copilot_context": {
                "sidecar_context": {
                    "product_title": "Storage shelf",
                    "sku_code": "SKU-1",
                    "i_id": "IID-1",
                }
            }
        })
        db.add(trace)
        db.commit()
    finally:
        db.close()

    report = compare_retrieval(
        run_uid="run-shadow",
        limit=10,
        sqlite_retriever=_FakeSQLiteRetriever(),
        pg_service=_FakePgService(),
        embedding_provider=lambda texts: [[0.01] * 1024 for _ in texts],
        db_factory=Session,
    )

    assert report["summary"]["compare_trace_count"] == 1
    assert report["summary"]["pgvector_available"] is True
    assert report["summary"]["pgvector_direct_answerable_count"] == 1
    assert report["summary"]["pgvector_faq_direct_count"] == 1
    assert report["summary"]["pgvector_service_action_count"] == 0
    assert report["summary"]["pgvector_media_reference_count"] == 0
    assert report["summary"]["missing_in_pgvector_count"] == 0
    assert report["summary"]["metadata_mismatch_count"] == 0
    assert report["rows"][0]["sqlite_candidate_count"] == 1
    assert report["rows"][0]["pgvector_candidate_count"] == 1
    assert report["rows"][0]["overlap_count"] == 1
    assert report["rows"][0]["pgvector_role_counts"]["faq_direct"] == 1
    assert report["rows"][0]["filter_ablation"]["strict"]["candidate_count"] == 1

    db = Session()
    try:
        stored = db.query(EvalTrace).filter(EvalTrace.run_uid == "run-shadow").one()
        assert stored.get_failure_labels() == []
    finally:
        db.close()


def test_shadow_compare_skips_cleanly_when_pgvector_unavailable(tmp_path):
    from app.models.eval_tables import EvalRun, EvalTrace
    from scripts.compare_sqlite_pgvector_retrieval import compare_retrieval

    Session = _session_factory(tmp_path)
    db = Session()
    try:
        db.add(EvalRun(run_uid="run-unavailable", source_type="real_conversation", status="completed", total_turns=1))
        trace = EvalTrace(
            run_uid="run-unavailable",
            case_uid="case-1",
            turn_uid="turn-1",
            turn_index=1,
            buyer_message="有安装说明吗",
            query_fact_type="installation",
        )
        trace.set_raw_response({"copilot_context": {"sidecar_context": {"product_title": "Shelf", "sku_code": "SKU-1"}}})
        db.add(trace)
        db.commit()
    finally:
        db.close()

    report = compare_retrieval(
        run_uid="run-unavailable",
        sqlite_retriever=_ExplodingSQLiteRetriever(),
        pg_service=_UnavailablePgService(),
        embedding_provider=lambda texts: (_ for _ in ()).throw(AssertionError("embedding should not run")),
        db_factory=Session,
    )

    assert report["summary"]["pgvector_available"] is False
    assert report["summary"]["skipped_reason"] == "pgvector_unavailable"
    assert report["rows"] == []
