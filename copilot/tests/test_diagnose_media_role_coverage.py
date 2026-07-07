from __future__ import annotations

from app.models.kb_tables import KBMediaAsset


def test_suggest_media_role_uses_explicit_installation_video_terms():
    from scripts.diagnose_media_role_coverage import suggest_media_role

    asset = KBMediaAsset(asset_type="other", asset_title="\u5b89\u88c5\u89c6\u9891-\u4e66\u67b6\u7ec4\u88c5\u6559\u7a0b")

    suggestion = suggest_media_role(asset)

    assert suggestion["confidence"] == "high"
    assert suggestion["suggested_role"] == "installation_video"


def test_suggest_media_role_keeps_plain_product_photo_unknown():
    from scripts.diagnose_media_role_coverage import suggest_media_role

    asset = KBMediaAsset(asset_type="sku_image", asset_title="\u5546\u54c1\u4e3b\u56fe")

    suggestion = suggest_media_role(asset)

    assert suggestion["confidence"] == "low"
    assert suggestion["suggested_role"] == "unknown"


def test_suggest_media_role_ignores_noisy_dimension_file_metadata():
    from scripts.diagnose_media_role_coverage import suggest_media_role

    asset = KBMediaAsset(asset_type="sku_image", asset_title="\u5546\u54c1\u4e3b\u56fe")
    asset.set_source_raw({"file_name": "dimension_001.jpg", "description": "dimension"})

    suggestion = suggest_media_role(asset)

    assert suggestion["confidence"] == "low"
    assert suggestion["suggested_role"] == "unknown"


def test_suggest_media_role_does_not_treat_answer_scenario_as_media_role():
    from scripts.diagnose_media_role_coverage import suggest_media_role

    asset = KBMediaAsset(asset_type="sku_image", asset_title="\u5546\u54c1\u4e3b\u56fe")
    asset.set_source_raw({"media_purpose": "appearance_image", "answer_scenarios": ["dimensions"]})
    asset.set_scene_tags(["dimensions"])

    suggestion = suggest_media_role(asset)

    assert suggestion["confidence"] == "low"
    assert suggestion["suggested_role"] == "unknown"
