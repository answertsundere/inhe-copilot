from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def identity_eval_db(monkeypatch):
    import app.db as db_module
    from app.models.eval_tables import EvalRun, EvalTrace
    from app.models.kb_tables import KBProduct, ProductIdentityMapping

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(
        bind=engine,
        tables=[EvalRun.__table__, EvalTrace.__table__, KBProduct.__table__, ProductIdentityMapping.__table__],
    )
    return session_factory


def _run(db, run_uid="run_identity"):
    from app.models.eval_tables import EvalRun

    db.add(EvalRun(run_uid=run_uid, source_type="real_conversation", status="completed"))
    db.commit()


def _trace(db, *, run_uid="run_identity", turn_uid="turn-1", item_hash="", item_id="", url="", title="", i_id="", sku=""):
    from app.models.eval_tables import EvalTrace

    identity = {
        "item_id": item_id,
        "item_id_hash": item_hash,
        "product_url": url,
        "product_title": title,
        "i_id": i_id,
        "sku_code": sku,
    }
    trace = EvalTrace(
        run_uid=run_uid,
        case_uid=f"case-{turn_uid}",
        turn_uid=turn_uid,
        turn_index=1,
        buyer_message="sanitized buyer message",
        passed=False,
    )
    trace.set_product_identity({"real_context_product_identity": identity})
    trace.set_raw_response({"real_context_product_identity": identity})
    db.add(trace)
    db.commit()
    return trace


def test_diagnose_counts_mapped_and_unmapped_platform_identity(identity_eval_db):
    from app.models.kb_tables import KBProduct, ProductIdentityMapping
    from scripts.diagnose_product_identity_mapping_coverage import collect_coverage

    db = identity_eval_db()
    try:
        _run(db)
        product = KBProduct(i_id="YH88K01", product_name="trusted product", status="published")
        db.add(product)
        db.commit()
        db.add(ProductIdentityMapping(
            mapping_uid="pim-existing",
            platform_item_id_hash="hash-mapped",
            kb_product_id=product.id,
            i_id=product.i_id,
            status="active",
        ))
        _trace(db, turn_uid="mapped", item_hash="hash-mapped", url="https://item.example.com/item.htm?id=1")
        _trace(db, turn_uid="unmapped", item_hash="hash-unmapped", url="https://item.example.com/item.htm?id=2")
        db.commit()
    finally:
        db.close()

    result = collect_coverage("run_identity", db_factory=identity_eval_db)

    assert result["replay_turn_count"] == 2
    assert result["turns_with_platform_identity"] == 2
    assert result["turns_already_mapped"] == 1
    assert result["turns_unmapped"] == 1
    assert result["candidate_match_count_by_method"]["exact_item_hash"] == 1
    assert result["candidate_match_count_by_method"]["not_found"] == 1


def test_diagnose_title_only_is_not_auto_match(identity_eval_db):
    from scripts.diagnose_product_identity_mapping_coverage import collect_coverage

    db = identity_eval_db()
    try:
        _run(db)
        _trace(db, turn_uid="title-only", title="Only a platform title")
    finally:
        db.close()

    result = collect_coverage("run_identity", db_factory=identity_eval_db)

    assert result["turns_with_platform_identity"] == 0
    assert result["turns_with_product_title_only"] == 1
    assert result["candidate_match_count_by_method"]["title_only_not_used"] == 1
