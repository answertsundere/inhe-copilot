"""素材卡片「适用款式 / 可回答问题 / 自动发送等级」单元测试。

不依赖真实商品/订单号，全部使用 TEST_* 临时数据。
"""

import json
from datetime import datetime, timedelta

import app.models.kb_tables  # noqa: F401
import pytest
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.services import media_asset_service as m
from app.services.media_asset_service import build_reply_blocks


def _create_asset(db, **kwargs) -> KBMediaAsset:
    defaults = {
        "i_id": "TEST_STYLE_SCOPE_001",
        "sku_code": "TEST_STYLE_SCOPE_001",
        "product_name": "测试款式范围商品",
        "source": "test",
        "source_doc_id": "test_doc",
        "source_raw_json": "{}",
        "match_confidence": 0.9,
        "content_hash": "",
        "scene_tags_json": "[]",
        "status": "approved",
        "usable_for_agent": 1,
        "refresh_status": "ok",
        "reviewed_by": "test",
        "url_expires_at": datetime.utcnow() + timedelta(days=1),
    }
    defaults.update(kwargs)
    # 有 content_hash 唯一约束时补一个唯一值
    if not defaults.get("content_hash"):
        defaults["content_hash"] = f"hash_{datetime.utcnow().timestamp()}"
    asset = KBMediaAsset(**defaults)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def _set_source_raw(db, asset, data):
    asset.set_source_raw(data)
    db.commit()
    db.refresh(asset)


@pytest.fixture
def db():
    db = SessionLocal()
    try:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id.like("TEST_STYLE_%")).delete(synchronize_session=False)
        db.commit()
        yield db
    finally:
        try:
            db.query(KBMediaAsset).filter(KBMediaAsset.i_id.like("TEST_STYLE_%")).delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass
        db.close()


def test_sku_size_image_preferred_over_generic_sku_image(db):
    """尺寸问题下，同 SKU 的尺寸图应排在 SKU 外观图之前。"""
    sku_img = _create_asset(db, asset_type="sku_image", asset_url="http://t/sku.png")
    size_img = _create_asset(db, asset_type="size_image", asset_url="http://t/size.png")

    reco = m.get_recommended_assets_for_message(
        customer_message="尺寸多大", i_id="TEST_STYLE_SCOPE_001", sku_code="TEST_STYLE_SCOPE_001", intent="size_query"
    )
    assert len(reco["recommended_assets"]) >= 1
    assert reco["recommended_assets"][0]["asset_type"] == "size_image"


def test_sku_exact_scope_excludes_wrong_sku(db):
    """标了适用 SKU=A 的图，不应在顾客问 SKU=B 时被推荐。"""
    asset = _create_asset(
        db,
        i_id="TEST_STYLE_SCOPE_001",
        sku_code="TEST_STYLE_SCOPE_001",
        asset_type="sku_image",
        asset_url="http://t/a.png",
    )
    _set_source_raw(db, asset, {"applicable_style": {"scope_type": "sku", "scope_values": ["TEST_STYLE_SCOPE_001A"], "scope_note": ""}})

    reco = m.get_recommended_assets_for_message(
        customer_message="看看图", i_id="TEST_STYLE_SCOPE_001", sku_code="TEST_STYLE_SCOPE_001B", intent="product_question"
    )
    assert reco["recommended_assets"] == []


def test_combo_scope_partial_match(db):
    """组合/颜色/尺寸等范围通过关键词命中。"""
    asset = _create_asset(db, asset_type="sku_image", asset_url="http://t/combo.png")
    _set_source_raw(db, asset, {"applicable_style": {"scope_type": "combo", "scope_values": ["大号款"], "scope_note": "大号款专用"}})

    reco = m.get_recommended_assets_for_message(
        customer_message="我要大号款的图片", i_id="TEST_STYLE_SCOPE_001", intent="product_question"
    )
    assert len(reco["recommended_assets"]) == 1
    assert reco["recommended_assets"][0]["asset_type"] == "sku_image"


def test_all_scope_fallback(db):
    """适用款式为全部时，任何查询都可作为兜底推荐。"""
    asset = _create_asset(db, asset_type="sku_image", asset_url="http://t/all.png")

    reco = m.get_recommended_assets_for_message(
        customer_message="发张图", i_id="TEST_STYLE_SCOPE_001", intent="product_question"
    )
    assert len(reco["recommended_assets"]) == 1
    assert reco["recommended_assets"][0]["asset_type"] == "sku_image"


def test_answer_scenario_boost_matching_asset(db):
    """可回答问题匹配的素材应排在未匹配素材之前。"""
    plain = _create_asset(db, asset_type="size_image", asset_url="http://t/plain.png")
    marked = _create_asset(db, asset_type="size_image", asset_url="http://t/marked.png")
    _set_source_raw(db, marked, {"answer_scenarios": ["dimensions"]})

    reco = m.get_recommended_assets_for_message(
        customer_message="尺寸是多少", i_id="TEST_STYLE_SCOPE_001", intent="size_query"
    )
    assert len(reco["recommended_assets"]) >= 1
    assert reco["recommended_assets"][0]["asset_id"] == marked.id


def test_certificate_material_default_review_not_auto_send(db):
    """证书/材质/售后图默认 review，不能进入自动发送 blocks。"""
    cert = _create_asset(db, asset_type="certificate_image", asset_url="http://t/cert.png")
    material = _create_asset(db, asset_type="material_image", asset_url="http://t/material.png")
    aftersales = _create_asset(db, asset_type="aftersales_image", asset_url="http://t/aftersales.png")

    for asset in (cert, material, aftersales):
        level = m.get_auto_send_level(asset)
        assert level == "review", f"{asset.asset_type} 应为 review，实际为 {level}"

    result = build_reply_blocks(
        "这是材质说明",
        [
            {
                "asset_id": material.id,
                "asset_type": "material_image",
                "asset_title": "材质图",
                "asset_url": "http://t/material.png",
                "auto_send_level": "review",
            }
        ],
        requires_human_review=False,
    )
    assert result["reply_delivery"]["auto_send_ready"] is False
    assert result["reply_delivery"]["reason"] == "media_requires_review"
    assert all(b["type"] != "image" for b in result["reply_blocks"])


def test_auto_send_level_can_be_overridden_to_disabled(db):
    """运营可将任何素材显式设为 disabled，此时不推荐。"""
    asset = _create_asset(db, asset_type="sku_image", asset_url="http://t/disabled.png")
    _set_source_raw(db, asset, {"auto_send_level": "disabled"})

    reco = m.get_recommended_assets_for_message(
        customer_message="发张图", i_id="TEST_STYLE_SCOPE_001", intent="product_question"
    )
    # 自动发送列表中不会出现 disabled 素材
    assert not any(a["asset_id"] == asset.id for a in reco["recommended_assets"])

    raw = m._asset_to_reco(asset)
    assert raw["auto_send_level"] == "disabled"
    selected = m.select_delivery_assets([raw])
    assert not any(a["asset_id"] == asset.id for a in selected)


def test_legacy_scene_tags_map_to_answer_scenarios(db):
    """旧数据只有 scene_tags 时，应自动映射为 answer_scenarios。"""
    asset = _create_asset(db, asset_type="size_image", asset_url="http://t/legacy.png")
    asset.set_scene_tags(["detachable", "dimensions"])
    db.commit()
    db.refresh(asset)

    scenarios = m.get_answer_scenarios(asset)
    assert "detachable" in scenarios
    assert "dimensions" in scenarios


def test_product_context_pack_respects_auto_send_level(db):
    """product_context_pack 的证据生成只使用 auto_send_level=auto 的素材。"""
    from app.services.product_context_pack_service import _media_facts_for_query

    auto_asset = {"asset_id": 1, "asset_type": "size_image", "asset_url": "http://t/size.png",
                      "asset_title": "尺寸图", "auto_send_level": "auto", "answer_scenarios": ["dimensions"],
                      "scene_tags": [], "applicable_style": {"scope_type": "all"}, "media_purpose": "size_image",
                      "i_id": "IID-A"}
    review_asset = dict(auto_asset)
    review_asset["auto_send_level"] = "review"

    facts = _media_facts_for_query({"product_name": "测试商品", "i_id": "IID-A"}, [auto_asset], query="尺寸", query_fact_type="dimensions")
    assert len(facts) == 1

    facts = _media_facts_for_query({"product_name": "测试商品"}, [review_asset], query="尺寸", query_fact_type="dimensions")
    assert facts == []

def test_product_name_match_does_not_send_wrong_variant_sku(db):
    wrong_variant = _create_asset(
        db,
        i_id="TEST_STYLE_VARIANT_001",
        sku_code="TEST_STYLE_VARIANT_001B01S01",
        product_name="Test Variant Product",
        asset_type="sku_image",
        asset_url="http://t/wrong-variant.png",
    )
    _set_source_raw(
        db,
        wrong_variant,
        {"applicable_style": {"scope_type": "all", "scope_values": [], "scope_note": ""}},
    )

    reco = m.get_recommended_assets_for_message(
        customer_message="show me a product photo",
        product_name="Test Variant Product",
        i_id="TEST_STYLE_VARIANT_001",
        sku_code="TEST_STYLE_VARIANT_001B05S01",
        intent="product_question",
    )

    assert reco["recommended_assets"] == []


def test_sku_variant_code_matches_combo_scope(db):
    combo5 = _create_asset(
        db,
        i_id="TEST_STYLE_COMBO_001",
        sku_code="TEST_STYLE_COMBO_001",
        product_name="Test Combo Product",
        asset_type="sku_image",
        asset_url="http://t/combo5.png",
    )
    _set_source_raw(
        db,
        combo5,
        {
            "applicable_style": {"scope_type": "combo", "scope_values": ["组合5"], "scope_note": "组合5"},
            "answer_scenarios": ["dimensions"],
        },
    )
    combo7 = _create_asset(
        db,
        i_id="TEST_STYLE_COMBO_001",
        sku_code="TEST_STYLE_COMBO_001",
        product_name="Test Combo Product",
        asset_type="sku_image",
        asset_url="http://t/combo7.png",
    )
    _set_source_raw(
        db,
        combo7,
        {
            "applicable_style": {"scope_type": "combo", "scope_values": ["组合7"], "scope_note": "组合7"},
            "answer_scenarios": ["dimensions"],
        },
    )

    reco = m.get_recommended_assets_for_message(
        customer_message="what size is it",
        product_name="Test Combo Product",
        i_id="TEST_STYLE_COMBO_001",
        sku_code="TEST_STYLE_COMBO_001B05S13",
        intent="size_query",
    )

    assert [item["asset_id"] for item in reco["recommended_assets"]] == [combo5.id]
