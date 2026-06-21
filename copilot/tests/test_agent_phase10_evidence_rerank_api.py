from __future__ import annotations

import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PHASE10_SKU = "PHASE10_RERANK_SKU"
PHASE10_I_ID = "PHASE10_RERANK_PRODUCT"
PHASE10_PRODUCT_NAME = "Phase10 测试收纳架"


@pytest.fixture()
def phase10_api(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA  # noqa: F401
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    saved_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    os.environ["COPILOT_LLM_API_KEY"] = ""
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "phase10_feedback.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "phase10_review.jsonl")

    _seed_phase10_product(session_factory)

    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    try:
        yield app.test_client()
    finally:
        os.environ["COPILOT_LLM_API_KEY"] = saved_key


def _seed_phase10_product(session_factory) -> None:
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct

    db = session_factory()
    try:
        product = KBProduct(
            i_id=PHASE10_I_ID,
            product_name=PHASE10_PRODUCT_NAME,
            sku_list_json=json.dumps([{"sku_code": PHASE10_SKU}], ensure_ascii=False),
            specs_json=json.dumps({
                "material": "环保PP/冷轧钢管",
                "load_capacity": "承重/容量: 8.58",
                "size": "长宽高 120*40*80cm",
                "usage_scene": "卧室、客厅建议预留取放空间",
                "installation": "先核对配件，再按说明书安装",
                "certification_report": "",
            }, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add(KBMediaAsset(
            product_id=product.id,
            i_id=PHASE10_I_ID,
            sku_code=PHASE10_SKU,
            product_name=PHASE10_PRODUCT_NAME,
            asset_type="install_video",
            asset_title="安装视频",
            asset_url="https://example.test/install.mp4",
            status="approved",
            usable_for_agent=1,
            match_confidence=0.95,
            scene_tags_json=json.dumps(["installation"], ensure_ascii=False),
        ))
        db.add(KBMediaAsset(
            product_id=product.id,
            i_id=PHASE10_I_ID,
            sku_code=PHASE10_SKU,
            product_name=PHASE10_PRODUCT_NAME,
            asset_type="size_image",
            asset_title="尺寸图",
            asset_url="https://example.test/size.jpg",
            status="approved",
            usable_for_agent=1,
            match_confidence=0.9,
            scene_tags_json=json.dumps(["dimensions"], ensure_ascii=False),
        ))
        db.add(KBGenericServiceRule(
            rule_key="detachable_generic",
            title="通用拆卸规则",
            intent="product_question",
            fact_type="detachable",
            content="多数收纳类商品可以拆卸，以实际商品为准。",
            status="active",
            priority=1,
        ))
        db.commit()
    finally:
        db.close()


def _analyze(client, message: str) -> dict:
    resp = client.post("/api/analyze", json={
        "message": message,
        "sku_code": PHASE10_SKU,
        "conversation_id": "phase10_rerank_" + str(abs(hash(message))),
    })
    assert resp.status_code == 200
    assert resp.is_json
    return resp.get_json()


@pytest.mark.parametrize("message,expected_fact_type", [
    ("这个尺寸多大？", "dimensions"),
    ("卧室空间小能放吗？", "space_fit"),
    ("有检测报告吗？", "certification_report"),
    ("有没有安装视频？", "installation"),
    ("放玩具稳不稳？", "stability"),
])
def test_phase10_api_rerank_trace_and_boundaries(phase10_api, message, expected_fact_type):
    data = _analyze(phase10_api, message)
    reply = data.get("suggested_reply") or ""
    trace = data.get("answer_trace") or {}

    assert data.get("query_fact_type") == expected_fact_type
    assert trace.get("query_fact_type") == expected_fact_type
    assert isinstance(trace.get("rerank_trace"), list)
    assert trace.get("selected_evidence_count", 0) >= 0
    if trace.get("selected_evidence_count", 0) or trace.get("rejected_evidence_count", 0):
        assert trace.get("rerank_trace")
        assert all("rank_reason" in item for item in trace.get("rerank_trace", []))
    assert "承重/容量:" not in reply
    assert "fact_type" not in reply
    assert "query_fact_type" not in reply
    assert "RAG" not in reply
    assert trace.get("final_quality_pass") is True or data.get("requires_human_review") is True

    if expected_fact_type == "dimensions":
        selected_types = {
            item.get("evidence_fact_type")
            for item in trace.get("selected_evidence", [])
        }
        assert "load_capacity" not in selected_types
        assert "承重" not in reply or "尺寸" in reply
    if expected_fact_type == "space_fit":
        assert "空间" in reply or "尺寸" in reply or "预留" in reply
    if expected_fact_type == "certification_report":
        selected_types = {
            item.get("evidence_fact_type")
            for item in trace.get("selected_evidence", [])
        }
        assert "material" not in selected_types
        assert "有检测报告" not in reply
    if expected_fact_type == "installation":
        selected_assets = trace.get("selected_assets") or data.get("selected_assets") or []
        assert any(item.get("asset_type") == "install_video" for item in selected_assets)
    if expected_fact_type == "stability":
        roles = {
            item.get("evidence_fact_type"): item.get("role")
            for item in trace.get("selected_evidence", [])
        }
        if "load_capacity" in roles:
            assert roles["load_capacity"] == "supporting_evidence"
