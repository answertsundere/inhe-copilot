from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def isolated_kb(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import (
        KBGenericServiceRule,
        KBMediaAsset,
        KBProduct,
        KBProductActivityRule,
        KBQA,
    )
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(
        bind=engine,
        tables=[
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


def test_cleaning_and_material_safety_remain_separate_when_product_specific_evidence_missing(isolated_kb):
    from app.main import create_app, get_reply_service
    from app.models.kb_tables import KBProduct
    from app.services.analysis_execution_service import execute_analysis

    sku = "TEST_CARE_001B01S01"
    display_name = "英禾测试收纳架"
    db = isolated_kb()
    try:
        db.add(KBProduct(
            i_id="TEST_CARE_001",
            product_name="测试收纳架",
            sku_list_json=json.dumps([{"sku_code": sku}], ensure_ascii=False),
            specs_json=json.dumps({"material": "PP"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    app = create_app()
    with app.app_context():
        common = {
            "reply_service": get_reply_service(),
            "conversation_id": f"test_cleaning_care_{uuid.uuid4().hex}",
            "product_name": display_name,
            "product_candidates": [{"type": "sku_code", "value": sku, "sku_code": sku}],
            "copilot_context": {"sku_code": sku, "display_product_name": display_name},
            "source": "pytest",
        }
        cleaning = execute_analysis(
            **common,
            customer_message="这个脏了怎么清洁？可以水洗吗？",
        )
        material = execute_analysis(
            **{
                **common,
                "conversation_id": f"test_material_safety_{uuid.uuid4().hex}",
            },
            customer_message="这个材质安全吗？会不会容易受潮？",
        )

    assert cleaning["intent"] == "cleaning_care"
    assert material["intent"] == "material_safety"
    assert cleaning["suggested_reply"] != material["suggested_reply"]
    assert cleaning["answer_mode"] == "no_evidence_controlled_reply"
    assert material["answer_mode"] == "no_evidence_controlled_reply"
    assert material["requires_human_review"] is True
    assert cleaning["requires_human_review"] is True

    cleaning_policy = (cleaning.get("evidence_debug") or {}).get("no_evidence_reply_policy") or {}
    material_policy = (material.get("evidence_debug") or {}).get("no_evidence_reply_policy") or {}
    assert cleaning_policy["reason"] == "no_evidence_for_fact_type"
    assert material_policy["reason"] == "material_safety_evidence_missing"
    assert "可以整体水洗" not in cleaning["suggested_reply"]
