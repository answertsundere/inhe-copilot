from __future__ import annotations

import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PRODUCT_I_ID = "PHASE6_MEDIA_PRODUCT"
SKU = "PHASE6_MEDIA_PRODUCT_B01"
PRODUCT_NAME = "Phase6 Media Positive Path Product"


@pytest.fixture()
def phase6_api(monkeypatch):
    import app.db as db_module

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
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "phase6_feedback.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "phase6_review.jsonl")
    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    try:
        yield app.test_client(), session_factory
    finally:
        os.environ["COPILOT_LLM_API_KEY"] = saved_key


def _seed_media(session_factory, *, asset_type: str, scenarios: list[str], title: str):
    from app.models.kb_tables import KBMediaAsset, KBProduct

    db = session_factory()
    try:
        product = db.query(KBProduct).filter(KBProduct.i_id == PRODUCT_I_ID).first()
        if not product:
            product = KBProduct(
                i_id=PRODUCT_I_ID,
                product_name=PRODUCT_NAME,
                sku_list_json=json.dumps([{"sku_code": SKU}], ensure_ascii=False),
                specs_json=json.dumps({"size": "60*30*90cm", "material": "PP"}, ensure_ascii=False),
                status="published",
            )
            db.add(product)
            db.flush()
        asset = KBMediaAsset(
            product_id=product.id,
            i_id=PRODUCT_I_ID,
            sku_code=SKU,
            product_name=PRODUCT_NAME,
            asset_type=asset_type,
            asset_title=title,
            asset_url=f"https://example.com/phase6/{asset_type}.jpg",
            status="approved",
            audit_status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.97,
        )
        asset.set_source_raw({"auto_send_level": "auto", "answer_scenarios": scenarios})
        db.add(asset)
        db.commit()
        return asset.id
    finally:
        db.close()


def _post(client, message: str) -> dict:
    resp = client.post("/ask/api/analyze", json={
        "message": message,
        "conversation_id": f"phase6_{abs(hash(message)) & 0xFFFFFFFF}",
        "product_name": PRODUCT_NAME,
        "i_id": PRODUCT_I_ID,
        "sku_code": SKU,
        "product_candidates": [
            {"type": "i_id", "value": PRODUCT_I_ID, "i_id": PRODUCT_I_ID, "product_name": PRODUCT_NAME},
            {"type": "sku_code", "value": SKU, "sku_code": SKU, "product_name": PRODUCT_NAME},
        ],
        "copilot_context": {
            "product_name": PRODUCT_NAME,
            "i_id": PRODUCT_I_ID,
            "sku_code": SKU,
            "product_candidates": [
                {"type": "sku_code", "value": SKU, "sku_code": SKU, "product_name": PRODUCT_NAME},
            ],
        },
    })
    assert resp.status_code == 200, resp.data[:500]
    return resp.get_json()


def _trace(data: dict) -> dict:
    return (data.get("evidence_debug") or {}).get("answer_trace") or data.get("answer_trace") or {}


def test_size_image_positive_path_enters_assets_blocks_and_trace(phase6_api):
    client, session_factory = phase6_api
    _seed_media(session_factory, asset_type="size_image", scenarios=["dimensions", "ask_photo"], title="尺寸图")

    data = _post(client, "尺寸多大，有没有图？")
    trace = _trace(data)

    assert data["recommended_assets"]
    assert data["selected_assets"]
    assert data["recommended_assets"][0]["asset_type"] == "size_image"
    assert any(block.get("asset_type") == "size_image" for block in data["reply_blocks"])
    assert trace["selected_assets"][0]["asset_type"] == "size_image"
    assert trace["media_evidence_used"].get("dimensions")
    assert trace["asset_evidence_used"]
    assert "visual_asset" not in trace["fallback_fact_types"]
    assert "尺寸图" in data["suggested_reply"] or "图" in data["suggested_reply"]
    assert "https://example.com" not in data["suggested_reply"]


def test_install_video_positive_path_enters_assets_blocks_and_trace(phase6_api):
    client, session_factory = phase6_api
    _seed_media(session_factory, asset_type="install_video", scenarios=["installation"], title="安装视频")

    data = _post(client, "怎么安装，有视频吗？")
    trace = _trace(data)

    assert data["selected_assets"][0]["asset_type"] == "install_video"
    assert any(block.get("asset_type") == "install_video" for block in data["reply_blocks"])
    assert trace["media_evidence_used"].get("installation")
    asset_trace = trace["asset_evidence_used"].get("visual_asset") or trace["asset_evidence_used"].get("installation")
    assert asset_trace
    assert asset_trace[0]["asset_id"]
    assert asset_trace[0]["asset_url"]
    assert "视频" in data["suggested_reply"]
    assert (data.get("final_answer_audit") or {}).get("passed") is True


def test_sku_image_positive_path_does_not_use_no_asset_fallback(phase6_api):
    client, session_factory = phase6_api
    _seed_media(session_factory, asset_type="sku_image", scenarios=["ask_photo"], title="实物图")

    data = _post(client, "有没有实物图？")
    trace = _trace(data)

    assert data["selected_assets"][0]["asset_type"] == "sku_image"
    assert trace["selected_assets"][0]["asset_type"] == "sku_image"
    assert "目前没有可直接发送" not in data["suggested_reply"]
    assert "visual_asset" not in trace["fallback_fact_types"]


def test_certificate_image_positive_path_does_not_become_absolute_safety_claim(phase6_api):
    client, session_factory = phase6_api
    _seed_media(session_factory, asset_type="certificate_image", scenarios=["certification_report"], title="检测报告")

    data = _post(client, "有没有检测报告，安全吗？")
    trace = _trace(data)

    assert data["selected_assets"][0]["asset_type"] == "certificate_image"
    assert trace["media_evidence_used"].get("certification_report")
    assert "certification_report" in trace["evidence_answered_fact_types"]
    assert trace["media_evidence_used"]["certification_report"][0]["asset_type"] == "certificate_image"
    for forbidden in ("绝对安全", "0甲醛", "完全无害"):
        assert forbidden not in data["suggested_reply"]


def test_no_asset_path_still_has_safe_trace_and_no_fake_send_claim(phase6_api):
    client, _session_factory = phase6_api

    data = _post(client, "有没有实物图？")
    trace = _trace(data)

    assert data.get("selected_assets", []) == []
    assert data.get("recommended_assets", []) == []
    assert "visual_asset" in trace["fallback_fact_types"] or "visual_asset" in trace["needs_followup_fact_types"]
    assert "下面发" not in data["suggested_reply"]
    assert "发您参考" not in data["suggested_reply"]
