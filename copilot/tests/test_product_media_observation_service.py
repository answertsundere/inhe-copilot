from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import product_media_observation_service as observation_module
from app.services.product_media_observation_service import ProductMediaObservationExtractor, media_asset_eligibility


def _asset(**overrides):
    asset = {
        "id": 41,
        "product_id": 9,
        "i_id": "TEST-IID-9",
        "sku_code": "TEST-IID-9-SKU",
        "asset_type": "size_image",
        "asset_url": "https://example.test/image.png?Signature=secret",
        "content_hash": "media-content-9",
        "status": "approved",
        "usable_for_agent": 1,
        "source": "test",
    }
    asset.update(overrides)
    return asset


def _response(*observations):
    return {"model_version": "test-vlm", "observations": list(observations)}


def _dimension(attribute_key="width", raw="宽80cm", value="80", unit="cm"):
    return {
        "observation_type": "labelled_dimension",
        "attribute_key": attribute_key,
        "raw_observation": raw,
        "normalized_value": value,
        "unit": unit,
        "domain": "length",
        "ocr_text": raw,
        "region": {"x": 1, "y": 2, "width": 30, "height": 10},
        "confidence": 0.92,
    }


@pytest.fixture()
def extractor(monkeypatch):
    monkeypatch.setattr(
        observation_module,
        "resolve_product_media_image",
        lambda *_args, **_kwargs: (b"image", ".png"),
    )
    return ProductMediaObservationExtractor(
        lambda _asset, _data, _extension, _timeout: _response(_dimension())
    )


def test_approved_identity_scoped_dimension_extracts_pending_observation(extractor):
    result = extractor.extract_asset(_asset())

    assert result["rejected_evidence"] == []
    observation = result["observations"][0]
    assert observation["observation_type"] == "labelled_dimension"
    assert observation["attribute_key"] == "width"
    assert observation["normalized_value"] == "80"
    assert observation["normalized_unit"] == "cm"
    assert observation["review_status"] == "pending_review"
    assert observation["direct_answer_allowed"] is False
    assert observation["used_for_generation"] is False
    assert observation["can_change_can_send"] is False
    assert observation["provenance"]["identity_scope"]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"i_id": ""}, "product_identity_incomplete"),
        ({"status": "pending_review"}, "media_not_approved"),
        ({"usable_for_agent": 0}, "media_not_usable"),
        ({"content_hash": ""}, "media_content_hash_missing"),
    ],
)
def test_asset_without_eligible_identity_scope_fails_closed(extractor, changes, reason):
    result = extractor.extract_asset(_asset(**changes))

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == reason


def test_expected_product_identity_requires_a_matching_namespace(extractor):
    matched = extractor.extract_asset(_asset(), expected_product_identity={"i_id": "TEST-IID-9"})
    mismatch = extractor.extract_asset(_asset(), expected_product_identity={"i_id": "OTHER-IID"})
    cross_namespace = extractor.extract_asset(
        _asset(product_id=None, sku_code=""),
        expected_product_identity={"sku_code": "SKU-X"},
    )

    assert matched["observations"]
    assert mismatch["rejected_evidence"][0]["reason"] == "product_identity_mismatch"
    assert cross_namespace["rejected_evidence"][0]["reason"] == "product_identity_namespace_missing"


def test_layer_count_is_not_upgraded_to_load_capacity(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    response = _response(
        {
            "observation_type": "layer_count",
            "attribute_key": "layer_count",
            "raw_observation": "三层",
            "normalized_value": "3",
            "unit": "count",
            "domain": "count",
            "ocr_text": "三层",
            "region": None,
            "confidence": 0.9,
        },
        {
            "observation_type": "visible_text",
            "attribute_key": "load_capacity",
            "raw_observation": "承重 20kg",
            "normalized_value": "",
            "unit": "",
            "domain": "",
            "ocr_text": "承重 20kg",
            "region": None,
            "confidence": 0.9,
        },
    )
    extractor = ProductMediaObservationExtractor(lambda *_args: response)

    result = extractor.extract_asset(_asset(asset_type="sku_image"))

    assert [item["observation_type"] for item in result["observations"]] == ["layer_count"]
    assert result["rejected_evidence"][0]["reason"] == "out_of_scope_high_risk"
    assert result["observations"][0]["warning_reasons"] == ["region_missing"]


def test_dimension_normalizes_and_keeps_width_height_depth_separate(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    response = _response(
        _dimension("width", "宽800mm", "800", "mm"),
        _dimension("height", "高120cm", "120", "cm"),
        _dimension("depth", "深1m", "1", "m"),
    )
    extractor = ProductMediaObservationExtractor(lambda *_args: response)

    result = extractor.extract_asset(_asset())
    observed = {(row["attribute_key"], row["normalized_value"], row["normalized_unit"]) for row in result["observations"]}

    assert observed == {("width", "80", "cm"), ("height", "120", "cm"), ("depth", "100", "cm")}


def test_sku_image_cannot_be_promoted_to_dimension_from_role_or_scenario(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    extractor = ProductMediaObservationExtractor(lambda *_args: _response(_dimension()))

    result = extractor.extract_asset(_asset(asset_type="sku_image"))

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "media_role_not_dimension_source"


@pytest.mark.parametrize(
    "response",
    [
        {"observations": "not-a-list"},
        {"observations": [], "unexpected": True},
        _response({"observation_type": "visible_text"}),
    ],
)
def test_malformed_model_response_fails_closed(monkeypatch, response):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    extractor = ProductMediaObservationExtractor(lambda *_args: response)

    result = extractor.extract_asset(_asset())

    assert result["observations"] == []
    assert result["rejected_evidence"]


def test_low_confidence_is_rejected_and_missing_region_is_explicit(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    low = _dimension()
    low["confidence"] = 0.2
    extractor = ProductMediaObservationExtractor(lambda *_args: _response(low))

    result = extractor.extract_asset(_asset())

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "low_confidence"


def test_observation_uids_and_normalization_are_stable_when_model_order_changes(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    values = [_dimension("width", "宽80cm", "80", "cm"), _dimension("height", "高120cm", "120", "cm")]
    forward = ProductMediaObservationExtractor(lambda *_args: _response(*values)).extract_asset(_asset())
    backward = ProductMediaObservationExtractor(lambda *_args: _response(*reversed(deepcopy(values)))).extract_asset(_asset())

    assert forward["observations"] == backward["observations"]


def test_observation_contract_is_not_formal_evidence_or_send_permission(extractor):
    result = extractor.extract_asset(_asset())
    assert media_asset_eligibility(_asset()) == []
    observation = result["observations"][0]

    assert observation["review_status"] == "pending_review"
    assert observation["direct_answer_allowed"] is False
    assert observation["used_for_generation"] is False
    assert observation["can_change_can_send"] is False


def test_grounded_reasoning_ignores_pending_media_observations():
    from app.services.grounded_reasoning_draft_service import build_grounded_reasoning_draft

    draft = build_grounded_reasoning_draft(
        customer_message="尺寸是多少",
        query_fact_type="dimensions",
        product_identity={"i_id": "TEST-IID-9"},
        product_context_pack={
            "product_media_observations": [{
                "observation_uid": "pmo_pending",
                "i_id": "TEST-IID-9",
                "observation_type": "labelled_dimension",
                "attribute_key": "width",
                "raw_observation": "宽80cm",
                "review_status": "pending_review",
                "direct_answer_allowed": False,
            }]
        },
    )

    assert draft["used_facts"] == []
    assert "pmo_pending" not in str(draft["fact_coverage_plan"])
