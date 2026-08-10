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


def test_odor_query_records_generic_rule_but_requires_direct_evidence_for_customer_reply(isolated_kb):
    from app.main import create_app, get_reply_service
    from app.models.kb_tables import KBProduct
    from app.services.analysis_execution_service import execute_analysis

    sku = "TEST_ODOR_001B01S01"
    display_name = "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6"

    db = isolated_kb()
    try:
        db.add(KBProduct(
            i_id="TEST_ODOR_001",
            product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": sku}], ensure_ascii=False),
            specs_json=json.dumps(
                {
                    "load_capacity": "\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg",
                    "material": "PET/PP",
                },
                ensure_ascii=False,
            ),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    app = create_app()
    with app.app_context():
        result = execute_analysis(
            reply_service=get_reply_service(),
            customer_message="\u6709\u6ca1\u6709\u5473\u9053",
            conversation_id=f"test_odor_generic_{uuid.uuid4().hex}",
            product_name=display_name,
            product_candidates=[{"type": "sku_code", "value": sku, "sku_code": sku}],
            copilot_context={"sku_code": sku, "display_product_name": display_name},
            source="pytest",
        )

    debug = result.get("evidence_debug") or {}
    reply = result.get("suggested_reply") or ""

    assert debug.get("query_fact_type") == "odor"
    # A generic care rule supplies a safe boundary, not product-specific odor
    # evidence. It remains review-only and must not be rendered as a fact.
    assert result.get("requires_human_review") is True
    assert (result.get("generic_service_rule_used") or {}).get("rule_key") == "odor_new_product_ventilation_v1"
    assert (debug.get("generic_service_rule_used") or {}).get("rule_key") == "odor_new_product_ventilation_v1"
    assert result.get("answer_mode") == "no_evidence_controlled_reply"
    assert "\u627f\u91cd" not in reply
    assert "15-30kg" not in reply


def test_space_fit_query_does_not_substitute_load_capacity_for_dimensions(isolated_kb):
    from app.main import create_app, get_reply_service
    from app.models.kb_tables import KBProduct
    from app.services.analysis_execution_service import execute_analysis

    sku = "TEST_SPACE_001B01S01"
    display_name = "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6\u6574\u7406\u5ba2\u5385\u96f6\u98df\u684c\u9762\u513f\u7ae5\u73a9\u5177\u5367\u5ba4\u53ef\u62fc\u642d\u50a8\u7269\u62bd\u5c49"

    db = isolated_kb()
    try:
        db.add(KBProduct(
            i_id="TEST_SPACE_001",
            product_name="\u4e5d\u53f7\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67dc",
            sku_list_json=json.dumps([{"sku_code": sku}], ensure_ascii=False),
            specs_json=json.dumps(
                {
                    "load_capacity": "\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg",
                    "material": "\u51b7\u8f67\u94a2\u7ba1/\u73af\u4fddPP/\u65e0\u7eba\u5e03",
                },
                ensure_ascii=False,
            ),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    app = create_app()
    with app.app_context():
        result = execute_analysis(
            reply_service=get_reply_service(),
            customer_message="5\u5e73\u65b9\u7684\u7a7a\u95f4\u591f\u4e0d\u591f\u653e\u7684\u4e0b\u53bb",
            conversation_id=f"test_space_fit_generic_{uuid.uuid4().hex}",
            product_name=display_name,
            product_candidates=[{"type": "sku_code", "value": sku, "sku_code": sku}],
            copilot_context={"sku_code": sku, "display_product_name": display_name},
            source="pytest",
        )

    debug = result.get("evidence_debug") or {}
    reply = result.get("suggested_reply") or ""

    assert debug.get("query_fact_type") == "space_fit"
    # There is no product-specific dimensions evidence, so the response stays
    # review-only rather than treating load capacity as a space-fit answer.
    assert result.get("requires_human_review") is True
    assert result.get("answer_mode") == "no_evidence_controlled_reply"
    assert "\u627f\u91cd" not in reply
    assert "15-30kg" not in reply
