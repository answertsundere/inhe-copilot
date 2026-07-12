from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.kb_tables import KBMediaAsset, KBProduct, KBQA
from app.models.product_media_observation import ProductMediaObservationCandidate, ProductMediaObservationReviewEvent
from app.services import product_media_observation_review_service as service
from app.services.product_media_observation_review_service import (
    FormalKnowledgeWriteBlocked, ObservationReviewError, import_report, staging_write_guard, transition_candidate,
)


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    asset = KBMediaAsset(id=1, i_id="IID-1", sku_code="SKU-1", status="approved", usable_for_agent=1,
                         asset_type="size_image", asset_url="https://example.test/1.png", content_hash="legacy")
    session.add(asset)
    session.commit()
    monkeypatch.setattr(service, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    yield session
    session.close()


def _observation(uid="pmo-test"):
    return {
        "observation_uid": uid, "media_asset_id": 1, "i_id": "IID-1", "sku_code": "SKU-1",
        "observed_media_sha256": hashlib.sha256(b"image").hexdigest(), "asset_content_hash": "legacy",
        "hash_comparison_status": "asset_hash_not_comparable", "media_role": "size_image",
        "observation_type": "labelled_dimension", "attribute_key": "width", "raw_observation": "80cm",
        "normalized_value": "80", "normalized_unit": "cm", "normalized_domain": "length_metric",
        "ocr_text": "80cm", "region": {"x": 1}, "confidence": 0.9, "extraction_model": "local",
        "extraction_version": "v1", "provenance": {"schema_version": "product_media_observation_shadow_v2"},
        "risk_class": "low", "direct_answer_allowed": True, "can_change_can_send": True,
    }


def _report(*observations):
    return {"summary": {"schema_version": "product_media_observation_shadow_report_v2"},
            "results": [{"media_asset_id": 1, "observations": list(observations), "rejected_evidence": []}]}


def test_import_is_pending_only_idempotent_and_ignores_send_flags(db):
    dry = import_report(db, _report(_observation()), apply=False)
    assert dry["candidate_import_count"] == 1
    assert db.query(ProductMediaObservationCandidate).count() == 0
    applied = import_report(db, _report(_observation()), apply=True)
    assert applied["candidate_import_count"] == 1
    candidate = db.query(ProductMediaObservationCandidate).one()
    assert candidate.status == "pending_review"
    assert candidate.to_dict()["direct_answer_allowed"] is False
    assert candidate.to_dict()["can_change_can_send"] is False
    assert import_report(db, _report(_observation()), apply=True)["duplicate_skipped_count"] == 1


def test_formal_knowledge_dml_is_rejected_by_staging_guard(db):
    db.add(KBProduct(i_id="OTHER", product_name="seed"))
    with pytest.raises(FormalKnowledgeWriteBlocked):
        with staging_write_guard(db):
            db.commit()
    db.rollback()


def test_any_formal_knowledge_table_dml_is_rejected_by_staging_guard(db):
    db.add(KBQA(question="test", answer="test"))
    with pytest.raises(FormalKnowledgeWriteBlocked):
        with staging_write_guard(db):
            db.commit()
    db.rollback()


def test_approve_requires_hash_and_version_and_keeps_shadow_only(db):
    import_report(db, _report(_observation()), apply=True)
    candidate = db.query(ProductMediaObservationCandidate).one()
    approved = transition_candidate(db, candidate.id, action="approve", reviewer="supervisor", reason="核对图片", expected_version=1)
    assert approved.status == "approved_shadow"
    assert approved.version == 2
    assert db.query(ProductMediaObservationReviewEvent).one().reviewer == "supervisor"
    with pytest.raises(ObservationReviewError, match="invalid_status_transition"):
        transition_candidate(db, candidate.id, action="approve", reviewer="supervisor", reason="again", expected_version=2)


def test_media_hash_change_invalidates_without_override(db, monkeypatch):
    import_report(db, _report(_observation()), apply=True)
    candidate = db.query(ProductMediaObservationCandidate).one()
    monkeypatch.setattr(service, "resolve_product_media_image", lambda *_args, **_kwargs: (b"changed", ".png"))
    with pytest.raises(ObservationReviewError, match="media_changed_since_extraction"):
        transition_candidate(db, candidate.id, action="approve", reviewer="supervisor", reason="核对", expected_version=1)
    assert db.get(ProductMediaObservationCandidate, candidate.id).status == "invalidated"
