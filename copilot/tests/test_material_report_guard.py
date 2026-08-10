"""Material-safety API regressions with isolated published knowledge."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


SKU = "TEST_MATERIAL_GUARD_001"
PRODUCT_NAME = "Material Guard Test Storage Unit"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Expose only composition evidence, never an implicit safety conclusion."""
    import app.config as config_module
    import app.db as db_module
    import app.main as main_module
    from app.models.kb_tables import KBProduct, KBQA
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    db_path = tmp_path / "material_report_guard.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(config_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(main_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    for service_name in (
        "_order_repo",
        "_product_repo",
        "_knowledge_repo",
        "_policy_repo",
        "_product_knowledge_repo",
        "_risk_service",
        "_context_builder",
        "_output_guard",
        "_reply_service",
        "_feedback_service",
        "_review_queue_service",
        "_reply_template_repo",
        "_sop_repo",
        "_data_quality_service",
        "_quality_check_service",
    ):
        monkeypatch.setattr(main_module, service_name, None)
    db_module.Base.metadata.create_all(bind=engine)

    db = session_factory()
    try:
        product = KBProduct(
            i_id="MATERIAL_GUARD_001",
            product_name=PRODUCT_NAME,
            sku_list_json=json.dumps([{"sku_code": SKU}]),
            specs_json=json.dumps({"material": "PP"}),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add(KBQA(
            question="How is this installed?",
            answer="Follow the product instructions for installation.",
            product_id=product.id,
            intent="installation",
            status="published",
            auto_reply=True,
        ))
        entry = KnowledgeEntry(
            source_type="faq",
            title="Material composition",
            content="The product material is PP.",
            intent="product_question",
            product_scope_json=json.dumps([PRODUCT_NAME]),
            risk_level="low",
            status="published",
            index_status="ready",
            fact_type="material",
            fact_review_status="verified",
        )
        db.add(entry)
        db.flush()
        db.add(KnowledgeChunk(
            entry_id=entry.id,
            chunk_text=entry.content,
            source_type="faq",
            intent="product_question",
            product_scope_json=json.dumps([PRODUCT_NAME]),
            metadata_json=json.dumps({"fact_type": "material"}),
            fact_review_status="verified",
            fact_source_type="faq",
        ))
        db.commit()
    finally:
        db.close()

    app = main_module.create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _post(client, message: str) -> dict:
    response = client.post("/ask/api/analyze", json={
        "message": message,
        "conversation_id": f"test_material_report_guard_{uuid.uuid4().hex}",
        "sku_code": SKU,
        "product_candidates": [{"value": SKU, "type": "sku_id_candidate", "verified": True}],
        "copilot_context": {
            "product_candidates": [{"value": SKU, "type": "sku_id_candidate", "verified": True}],
        },
    })
    assert response.status_code == 200
    result = response.get_json()
    assert "intent" in result, result.get("block_reasons")
    return result


def test_material_composition_does_not_answer_safety_or_moisture_questions(client):
    result = _post(client, "\u8fd9\u4e2a\u6750\u8d28\u5b89\u5168\u5417\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u53d7\u6f6e\uff1f")

    assert result["intent"] == "material_safety"
    assert result["requires_human_review"] is True
    policy = (result.get("evidence_debug") or {}).get("no_evidence_reply_policy") or {}
    assert policy["reason"] == "material_safety_evidence_missing"
    assert (result.get("evidence_debug") or {}).get("evidence_sufficient") is False


def test_formaldehyde_report_query_does_not_use_unrelated_material_composition(client):
    result = _post(client, "\u6ca1\u6709\u7532\u919b\u7684\u68c0\u67e5\u62a5\u544a\u5417\uff1f")

    assert result["intent"] == "material_safety"
    assert result["requires_human_review"] is True
    policy = (result.get("evidence_debug") or {}).get("no_evidence_reply_policy") or {}
    assert policy["reason"] == "material_safety_evidence_missing"
    assert (result.get("evidence_debug") or {}).get("evidence_sufficient") is False
