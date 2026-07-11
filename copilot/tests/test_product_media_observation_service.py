from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services import product_media_observation_service as observation_module
from app.services.product_media_observation_service import (
    ProductMediaObservationExtractor,
    ProductMediaObservationProviderError,
    ProductMediaObservationSchemaError,
    _model_prompt,
    _normalize_complete_json_object,
    probe_product_media_vlm,
    media_asset_eligibility,
)


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


def test_model_prompt_declares_exact_attribute_keys_and_region_contract():
    prompt = _model_prompt(_asset(), max_observations=5)

    assert "labelled_dimension/width|height|depth|length" in prompt
    assert "visible_text/visible_text" in prompt
    assert "Region must be null" in prompt
    assert "prose location string" in prompt
    assert "maximum 5" in prompt


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
    assert observation["observed_media_sha256"]
    assert observation["hash_comparison_status"] == "asset_hash_not_comparable"


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
            "attribute_key": "visible_text",
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


def test_compartment_count_and_ordinary_ocr_text_remain_low_risk(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    response = _response(
        {
            "observation_type": "compartment_count",
            "attribute_key": "compartment_count",
            "raw_observation": "4 compartments",
            "normalized_value": "4",
            "unit": "count",
            "domain": "count",
            "ocr_text": "4 compartments",
            "region": {"x": 1},
            "confidence": 0.9,
        },
        {
            "observation_type": "visible_text",
            "attribute_key": "visible_text",
            "raw_observation": "Width 80cm",
            "normalized_value": "",
            "unit": "",
            "domain": "",
            "ocr_text": "Width 80cm",
            "region": {"x": 2},
            "confidence": 0.9,
        },
    )
    result = ProductMediaObservationExtractor(lambda *_args: response).extract_asset(_asset(asset_type="pack_guide_image"))

    assert {item["observation_type"] for item in result["observations"]} == {"compartment_count", "visible_text"}
    assert next(item for item in result["observations"] if item["observation_type"] == "visible_text")["ocr_text"] == "Width 80cm"


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


def test_model_schema_error_is_classified_without_leaking_provider_details(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    extractor = ProductMediaObservationExtractor(
        lambda *_args: (_ for _ in ()).throw(ProductMediaObservationSchemaError("vlm_empty_response"))
    )

    result = extractor.extract_asset(_asset())

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "schema_error"
    assert "https://" not in " ".join(result["warnings"])


@pytest.mark.parametrize(
    "raw_observation",
    [
        "age_range: 3-6 years",
        "\u9002\u7528\u5e74\u9f843-6\u5c81",
        "pinch_protection design",
        "\u9632\u5939\u624b\u8bbe\u8ba1",
        "installation_method: wall_fixing required",
        "\u9700\u8981\u56fa\u5b9a\u5230\u5899\u9762",
        "load_capacity 20kg",
        "\u65e0\u6bd2\u98df\u54c1\u7ea7\u8ba4\u8bc1",
    ],
)
def test_high_risk_content_cannot_hide_as_visible_text(monkeypatch, raw_observation):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    observation = {
        "observation_type": "visible_text",
        "attribute_key": "visible_text",
        "raw_observation": raw_observation,
        "normalized_value": "",
        "unit": "",
        "domain": "",
        "ocr_text": raw_observation,
        "region": None,
        "confidence": 0.9,
    }
    result = ProductMediaObservationExtractor(lambda *_args: _response(observation)).extract_asset(_asset())

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "out_of_scope_high_risk"


@pytest.mark.parametrize(
    "raw_observation",
    ["3\u5c81\u4ee5\u4e0a", "3-6\u5c81", "\u65e0\u7532\u919b", "\u65e0\u919b", "formaldehyde-free"],
)
def test_age_and_formaldehyde_claim_fragments_cannot_hide_as_visible_text(monkeypatch, raw_observation):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    observation = {
        "observation_type": "visible_text",
        "attribute_key": "visible_text",
        "raw_observation": raw_observation,
        "normalized_value": "",
        "unit": "",
        "domain": "",
        "ocr_text": raw_observation,
        "region": None,
        "confidence": 0.9,
    }

    result = ProductMediaObservationExtractor(lambda *_args: _response(observation)).extract_asset(_asset())

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "out_of_scope_high_risk"


def test_multiple_dimension_values_without_variant_scope_are_rejected(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    response = _response(
        _dimension("width", "80cm", "80", "cm"),
        _dimension("width", "120cm", "120", "cm"),
        _dimension("height", "60cm", "60", "cm"),
    )

    result = ProductMediaObservationExtractor(lambda *_args: response).extract_asset(_asset())

    assert [(item["attribute_key"], item["normalized_value"]) for item in result["observations"]] == [("height", "60")]
    rejected = [item for item in result["rejected_evidence"] if item["reason"] == "ambiguous_variant_dimension_scope"]
    assert len(rejected) == 2
    assert {item["attribute_key"] for item in rejected} == {"width"}


def test_unknown_attribute_is_rejected_even_for_low_risk_observation(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    observation = _dimension("unrecognized_dimension")
    result = ProductMediaObservationExtractor(lambda *_args: _response(observation)).extract_asset(_asset())

    assert result["observations"] == []
    assert result["rejected_evidence"][0]["reason"] == "attribute_not_allowed"


def test_visible_structure_accepts_only_allowlisted_attribute(monkeypatch):
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    observation = {
        "observation_type": "visible_structure",
        "attribute_key": "shelf_layout",
        "raw_observation": "three shelves are visible",
        "normalized_value": "",
        "unit": "",
        "domain": "",
        "ocr_text": "",
        "region": None,
        "confidence": 0.9,
    }
    result = ProductMediaObservationExtractor(lambda *_args: _response(observation)).extract_asset(_asset(asset_type="sku_image"))

    assert result["rejected_evidence"] == []
    assert result["observations"][0]["attribute_key"] == "shelf_layout"


def test_actual_media_sha256_controls_uid_and_db_hash_mismatch_fails_closed(monkeypatch):
    state = {"image": b"first-image"}
    monkeypatch.setattr(
        observation_module,
        "resolve_product_media_image",
        lambda *_args, **_kwargs: (state["image"], ".png"),
    )
    runner = lambda *_args: _response(_dimension())
    extractor = ProductMediaObservationExtractor(runner)
    matching_hash = __import__("hashlib").sha256(state["image"]).hexdigest()

    first = extractor.extract_asset(_asset(content_hash=matching_hash))
    state["image"] = b"second-image"
    second = extractor.extract_asset(_asset(content_hash="legacy-import-hash"))
    mismatch = extractor.extract_asset(_asset(content_hash=matching_hash))

    assert first["hash_comparison_status"] == "verified_match"
    assert first["observations"][0]["observation_uid"] != second["observations"][0]["observation_uid"]
    assert second["hash_comparison_status"] == "asset_hash_not_comparable"
    assert mismatch["observations"] == []
    assert mismatch["rejected_evidence"][0]["reason"] == "media_content_hash_mismatch"


def test_placeholder_vlm_values_are_not_treated_as_configured(monkeypatch):
    monkeypatch.setattr(observation_module.config, "COPILOT_VLM_ENABLED", True)
    monkeypatch.setattr(observation_module.config, "COPILOT_VLM_API_BASE", "<placeholder>")
    monkeypatch.setattr(observation_module.config, "COPILOT_VLM_API_KEY", "your-api-key")
    monkeypatch.setattr(observation_module.config, "COPILOT_VLM_MODEL", "")

    status = observation_module.vlm_configuration_status()

    assert status["enabled"] is True
    assert status["api_base_configured"] is False
    assert status["api_key_configured"] is False
    assert status["model_configured"] is False
    assert observation_module.vlm_configured() is False


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


def _vlm_response(content, *, finish_reason="stop", reasoning_content="", refusal=""):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, reasoning_content=reasoning_content, refusal=refusal),
        )],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
    )


def _fake_openai(monkeypatch, outcomes):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(observation_module, "OpenAI", lambda **_kwargs: SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    return calls


def test_response_format_retry_only_occurs_for_explicit_unsupported_parameter(monkeypatch):
    calls = _fake_openai(monkeypatch, [RuntimeError("unsupported"), _vlm_response('{"model_version":"v","observations":[]}')])
    monkeypatch.setattr(observation_module, "_classify_vlm_exception", lambda _exc: "unsupported_parameter")

    response = observation_module.call_product_media_vlm(_asset(), b"image", ".png")

    assert response["observations"] == []
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


@pytest.mark.parametrize("category", ["authentication_error", "rate_limit_error", "timeout_error", "provider_error"])
def test_provider_failures_do_not_trigger_a_compatibility_retry(monkeypatch, category):
    calls = _fake_openai(monkeypatch, [RuntimeError(category)])
    monkeypatch.setattr(observation_module, "_classify_vlm_exception", lambda _exc: category)

    with pytest.raises(ProductMediaObservationProviderError) as exc_info:
        observation_module.call_product_media_vlm(_asset(), b"image", ".png")

    assert exc_info.value.category == category
    assert len(calls) == 1


def test_outer_fenced_json_is_normalized_but_truncated_json_is_not_repaired():
    metadata = {"finish_reason": "stop"}
    parsed = _normalize_complete_json_object("```json\n{\"model_version\":\"v\",\"observations\":[]}\n```", metadata)

    assert parsed["observations"] == []
    assert metadata["json_parse_success"] is True
    with pytest.raises(ProductMediaObservationSchemaError) as exc_info:
        _normalize_complete_json_object('{"model_version":"v","observations":[', {"finish_reason": "stop"})
    assert exc_info.value.category == "non_json_response"


def test_length_finish_reason_and_reasoning_content_cannot_supply_an_observation(monkeypatch):
    calls = _fake_openai(monkeypatch, [
        _vlm_response('{"model_version":"v","observations":[]}', finish_reason="length"),
        _vlm_response("", reasoning_content='{"model_version":"v","observations":[]}'),
    ])

    with pytest.raises(ProductMediaObservationSchemaError) as truncated:
        observation_module.call_product_media_vlm(_asset(), b"image", ".png")
    assert truncated.value.category == "truncated_response"
    probe = probe_product_media_vlm(_asset(), b"image", ".png")
    assert probe["error_category"] == "empty_response"
    assert probe["reasoning_content_present"] is True
    assert probe["content_present"] is False
    assert len(calls) == 2


def test_plain_json_transport_does_not_send_response_format_or_retry(monkeypatch):
    calls = _fake_openai(monkeypatch, [RuntimeError("unsupported")])
    monkeypatch.setattr(observation_module, "_classify_vlm_exception", lambda _exc: "unsupported_parameter")

    parsed, metadata = observation_module.run_product_media_vlm_transport(
        _asset(),
        b"image",
        ".png",
        request_variant="plain_json_prompt",
    )

    assert parsed is None
    assert metadata["retry_count"] == 0
    assert len(calls) == 1
    assert "response_format" not in calls[0]


def test_explicit_qualification_connection_can_use_a_bounded_local_budget(monkeypatch):
    calls = _fake_openai(monkeypatch, [_vlm_response('{"model_version":"v","observations":[]}')])
    connection = observation_module.ProductMediaVlmConnection(
        api_base="http://127.0.0.1:8001/v1",
        api_key="local-development",
        model="local-model",
    )

    parsed, _metadata = observation_module.run_product_media_vlm_transport(
        _asset(), b"image", ".png", connection=connection, timeout_seconds=45, max_tokens=256, max_observations=5
    )

    assert parsed is not None
    assert calls[0]["timeout"] == 45
    assert calls[0]["max_tokens"] == 256
    assert "maximum 5" in calls[0]["messages"][1]["content"][0]["text"]


def test_extractor_passes_shadow_budget_to_default_vlm_runner(monkeypatch):
    captured = {}
    monkeypatch.setattr(observation_module, "resolve_product_media_image", lambda *_args, **_kwargs: (b"image", ".png"))
    monkeypatch.setattr(observation_module, "vlm_configured", lambda: True)
    monkeypatch.setattr(
        observation_module,
        "call_product_media_vlm",
        lambda *_args, **kwargs: captured.update(kwargs) or _response(_dimension()),
    )

    ProductMediaObservationExtractor(max_tokens=1024, max_observations=5).extract_asset(_asset())

    assert captured["max_tokens"] == 1024
    assert captured["max_observations"] == 5
