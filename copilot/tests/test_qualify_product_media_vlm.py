from __future__ import annotations


def _record(*, success=True, category="", schema=True, latency=10.0):
    return {
        "transport_success": success,
        "error_category": category,
        "schema_parse_success": schema,
        "latency_ms": latency,
        "content_present": success,
        "finish_reason": "stop" if success else "",
        "high_risk_admitted_count": 0,
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }


def test_qualification_requires_every_run_to_complete_valid_json_without_timeouts():
    from scripts.qualify_product_media_vlm import build_qualification_summary

    passed = build_qualification_summary(
        provider_alias="candidate-a",
        model="candidate-model",
        official_vision_support="yes",
        json_mode_support="yes",
        records=[_record(), _record(), _record()],
    )
    failed = build_qualification_summary(
        provider_alias="candidate-a",
        model="candidate-model",
        official_vision_support="yes",
        json_mode_support="yes",
        records=[_record(), _record(success=False, category="timeout_error", schema=False), _record()],
    )

    assert passed["qualified"] is True
    assert passed["stable_json_rate"] == {"numerator": 3, "denominator": 3, "rate": 1.0}
    assert failed["qualified"] is False
    assert failed["timeout_count"] == 1
    assert failed["finish_reason_distribution"] == {"missing": 1, "stop": 2}


def test_qualification_rejects_truncation_schema_failure_and_high_risk_admission():
    from scripts.qualify_product_media_vlm import build_qualification_summary

    summary = build_qualification_summary(
        provider_alias="candidate-a",
        model="candidate-model",
        official_vision_support="unknown",
        json_mode_support="unknown",
        records=[
            _record(success=False, category="truncated_response", schema=False),
            {**_record(), "high_risk_admitted_count": 1},
        ],
    )

    assert summary["qualified"] is False
    assert summary["truncated_count"] == 1
    assert summary["high_risk_admitted_count"] == 1
    assert summary["reasoning_content_consumed_count"] == 0
    assert summary["authentication_error_count"] == 0


def test_qualification_summary_has_no_connection_values_or_response_text():
    from scripts.qualify_product_media_vlm import build_qualification_summary

    summary = build_qualification_summary(
        provider_alias="candidate-a",
        model="candidate-model",
        official_vision_support="yes",
        json_mode_support="yes",
        records=[_record()],
    )
    serialized = str(summary)

    assert "api_key" not in serialized
    assert "api_base" not in serialized
    assert "raw_response" not in serialized
