from __future__ import annotations

from scripts.diagnose_reply_ownership import _record, _request_from_scenario


def test_diagnostic_request_uses_api_template_only():
    scenario = {
        "scenario_uid": "diagnostic-only",
        "gold_reply": "must never enter the Agent request",
        "expected_claims": [{"text": "hidden"}],
        "api_request_template": {
            "message": "这个多宽",
            "conversation_history": [{"role": "customer", "content": "我问当前款"}],
            "copilot_context": {},
            "sku_code": "SKU-LOCAL",
        },
    }

    request = _request_from_scenario(scenario, object())

    assert request.customer_message == "这个多宽"
    assert request.copilot_context["conversation_history"][0]["content"] == "我问当前款"
    assert "gold_reply" not in request.copilot_context
    assert "expected_claims" not in request.copilot_context


def test_stage_record_reports_change_without_claiming_fact_correctness(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "scripts.diagnose_reply_ownership._ACTIVE_STAGES",
        captured,
    )

    _record("customer_reply_polisher", "宽度80厘米", "我帮您核对后回复")

    assert captured[0]["changed"] is True
    assert captured[0]["fact_change_assessment"] == "requires_claim_attribution_review"
    assert captured[0]["system_tone_terms_added"] == ["帮您核对"]
