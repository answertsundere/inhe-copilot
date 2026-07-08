from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def source_coverage_db():
    from app.db import Base
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBQA

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            KBProduct.__table__,
            KBGenericServiceRule.__table__,
            KBQA.__table__,
            KBMediaAsset.__table__,
        ],
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    db = factory()
    try:
        product = KBProduct(i_id="IID-1", product_name="测试商品", status="published")
        product.set_specs({"dimensions": "10x20x30"})
        db.add(product)
        db.flush()
        db.add(KBGenericServiceRule(
            rule_key="logistics_rule",
            title="物流核对",
            fact_type="stock_shipping",
            status="active",
            auto_reply_allowed=True,
            allowed_when_product_fact_missing=True,
        ))
        db.add(KBQA(
            question="怎么开发票",
            answer="按平台开票流程处理",
            intent="invoice",
            source_type="faq",
            status="published",
            auto_reply=True,
        ))
        db.add(KBMediaAsset(
            asset_title="安装说明书",
            asset_type="manual",
            asset_url="https://example.invalid/manual.png",
            status="approved",
            usable_for_agent=1,
        ))
        db.commit()
    finally:
        db.close()
    return factory


def _analysis_payload():
    return {
        "run_uid": "run-1",
        "strict_empty_product_only_hit_count": 3,
        "groups": [
            {
                "requested_fact_type": "stock_shipping",
                "recommendation": "add_source_coverage",
                "candidate_count": 2,
                "direct_answerable_candidate_count": 0,
                "samples": [{"buyer_message_preview": "物流到哪了"}],
            },
            {
                "requested_fact_type": "invoice_policy",
                "recommendation": "add_source_coverage",
                "candidate_count": 1,
                "direct_answerable_candidate_count": 0,
                "samples": [{"buyer_message_preview": "发票怎么开"}],
            },
            {
                "requested_fact_type": "load_capacity",
                "recommendation": "keep_strict",
                "candidate_count": 1,
                "direct_answerable_candidate_count": 1,
                "samples": [{"buyer_message_preview": "能承重多少"}],
            },
        ],
    }


def test_diagnose_source_coverage_recommends_existing_service_sources(source_coverage_db):
    from scripts.diagnose_pgvector_source_coverage_gaps import diagnose

    db = source_coverage_db()
    try:
        report = diagnose(_analysis_payload(), db=db)
    finally:
        db.close()

    shipping = next(item for item in report["items"] if item["requested_fact_type"] == "stock_shipping")
    invoice = next(item for item in report["items"] if item["requested_fact_type"] == "invoice_policy")
    load_capacity = next(item for item in report["items"] if item["requested_fact_type"] == "load_capacity")

    assert shipping["existing_generic_rule_count"] == 1
    assert shipping["recommended_source_type"] == "generic_rule"
    assert shipping["safe_to_auto_generate_rule"] is False
    assert invoice["existing_kbqa_count"] == 1
    assert invoice["recommended_source_type"] == "kbqa"
    assert load_capacity["recommended_source_type"] == "keep_strict"
    assert report["by_recommended_source_type"]["generic_rule"] == 1


def test_diagnose_source_coverage_script_writes_json(tmp_path, source_coverage_db):
    from scripts.diagnose_pgvector_source_coverage_gaps import run

    input_path = tmp_path / "analysis.json"
    output_path = tmp_path / "coverage.json"
    input_path.write_text(json.dumps(_analysis_payload(), ensure_ascii=False), encoding="utf-8")

    report = run(
        analysis_json=str(input_path),
        json_output=str(output_path),
        db_factory=source_coverage_db,
    )

    assert report["source_coverage_group_count"] == 3
    assert output_path.exists()
    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["notes"]
