from __future__ import annotations

from scripts.sidecar.uia_sidebar_extractor import _extract_product_candidates
from scripts.sidecar.vision_extractor import VisionCandidateItem, VisionExtractResult


def test_uia_extracts_sku_code_candidate():
    result = _extract_product_candidates("SKU: YH88K01B09S26")

    assert any(
        c.value == "YH88K01B09S26"
        and c.type == "sku_id_candidate"
        and c.verified is True
        for c in result
    )


def test_uia_extracts_i_id_candidate():
    result = _extract_product_candidates("i_id: YH88K01")

    assert any(
        c.value == "YH88K01"
        and c.type == "i_id_candidate"
        and c.verified is True
        for c in result
    )


def test_uia_platform_product_id_is_not_verified_internal_code():
    result = _extract_product_candidates("ID: 1046558780232")

    assert any(
        c.value == "1046558780232"
        and c.type == "platform_product_id_candidate"
        and c.verified is False
        for c in result
    )


def test_uia_extracts_full_product_title_from_sidebar_card():
    text = (
        "咨询宝贝(1) ID 985017262291 "
        "英禾床围栏宝宝防摔婴儿床护栏儿童床边挡板一侧单面隔板便携式 "
        "￥16.9 库存911 销量2856 SKU 属性"
    )

    result = _extract_product_candidates(text)
    values = [c.value for c in result]

    assert "985017262291" in values
    assert "英禾床围栏宝宝防摔婴儿床护栏儿童床边挡板一侧单面隔板便携式" in values
    assert "(1)" not in values


def test_vision_candidate_type_is_preserved():
    result = VisionExtractResult(
        success=True,
        product_candidates=[
            VisionCandidateItem(
                value="YH88K01B09S26",
                source="vision",
                confidence=0.8,
                type="sku_id_candidate",
            )
        ],
    )

    assert result.to_dict()["product_candidates"][0]["type"] == "sku_id_candidate"
