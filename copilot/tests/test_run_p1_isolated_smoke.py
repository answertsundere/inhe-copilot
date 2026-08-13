from __future__ import annotations

import pytest

from scripts.run_p1_isolated_smoke import (
    SCENARIOS,
    SmokeContractError,
    _loopback_base_url,
    _loopback_provider_url,
    project_case_result,
)


def _response(**overrides):
    value = {
        "error": None,
        "intent": "general",
        "reply_status": "needs_human_review",
        "suggested_reply": "A review-only draft.",
        "draft_reply": "",
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
    }
    value.update(overrides)
    return value


def test_loopback_base_url_rejects_non_loopback_or_non_http_urls():
    assert _loopback_base_url("http://127.0.0.1:5012") == "http://127.0.0.1:5012"
    with pytest.raises(Exception, match="base_url_must_be_http_loopback"):
        _loopback_base_url("https://example.com")
    with pytest.raises(Exception, match="base_url_must_not_include_path_or_query"):
        _loopback_base_url("http://127.0.0.1:5012/api/analyze")


def test_loopback_provider_url_allows_local_api_prefix_but_not_remote_hosts():
    assert _loopback_provider_url("http://127.0.0.1:8001/v1") == "http://127.0.0.1:8001/v1"
    with pytest.raises(Exception, match="llm_api_base_must_be_http_loopback"):
        _loopback_provider_url("https://provider.example/v1")


def test_case_projection_does_not_retain_reply_content():
    result = project_case_result(SCENARIOS[0], _response())

    assert result["review_draft_present"] is True
    assert result["review_draft_length"] == len("A review-only draft.")
    assert "suggested_reply" not in result
    assert "A review-only draft." not in str(result)


@pytest.mark.parametrize(
    "response,reason",
    [
        (_response(can_send=True), "unsafe_auto_send"),
        (_response(requires_human_review=False), "human_review_missing"),
        (_response(suggested_reply=""), "review_draft_missing"),
    ],
)
def test_low_risk_case_rejects_delivery_boundary_failures(response, reason):
    with pytest.raises(SmokeContractError, match=reason):
        project_case_result(SCENARIOS[0], response)


def test_high_risk_case_allows_empty_draft_but_never_auto_send():
    result = project_case_result(SCENARIOS[1], _response(suggested_reply=""))

    assert result["review_draft_present"] is False
    assert result["can_send"] is False
    assert result["requires_human_review"] is True
