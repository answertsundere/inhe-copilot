from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderService,
)


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "qualify_turn_understanding_strict_provider.py"
)


def _module():
    assert _SCRIPT_PATH.exists()
    spec = importlib.util.spec_from_file_location(
        "qualify_turn_understanding_strict_provider",
        _SCRIPT_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unconfigured_turn_understanding_qualification_is_read_only_and_blocked():
    module = _module()
    provider = StrictDecisionProviderService(
        config=StrictDecisionProviderConfig(
            provider_name="",
            api_base="",
            api_key="",
            model="",
            capability="unsupported",
            timeout_seconds=3,
            qualified=False,
            qualification_fingerprint_required=True,
            role_name="turn_understanding",
        )
    )

    report = module.qualify(repeats=2, provider=provider)

    assert report["qualification_status"] == "not_qualified"
    assert report["deployment_enablement_allowed"] is False
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
    assert report["free_text_fallback_count"] == 0
    assert report["json_repair_count"] == 0


def test_turn_understanding_qualification_report_has_no_provider_secret_or_origin():
    module = _module()

    class _ConfiguredProvider:
        last_latency_ms = None

        def metadata(self):
            return {
                "provider_name": "test-provider",
                "host_fingerprint": "c" * 12,
                "model_name": "test-model",
                "configured": True,
                "qualified": False,
                "qualification_status": "provider_not_qualified",
                "unsafe_origin": "https://hidden.example.invalid/beta",
                "unsafe_key": "not-for-report",
            }

        def qualification_fingerprint(self):
            return "d" * 64

        def request(self, **_kwargs):
            raise RuntimeError("unexpected provider failure")

    provider = _ConfiguredProvider()

    report = module.qualify(repeats=1, provider=provider)

    rendered = str(report)
    assert "hidden.example.invalid" not in rendered
    assert "not-for-report" not in rendered


def test_turn_understanding_qualification_uses_the_strict_route_without_legacy_client():
    module = _module()

    class _FakeProvider:
        last_latency_ms = 8.0

        def __init__(self):
            self.calls = []

        def metadata(self):
            return {
                "provider_name": "test-provider",
                "host_fingerprint": "a" * 12,
                "model_name": "test-model",
                "configured": True,
                "qualified": False,
                "qualification_status": "provider_not_qualified",
            }

        def qualification_fingerprint(self):
            return "b" * 64

        def request(self, **kwargs):
            self.calls.append(kwargs)
            return module.synthetic_provider_output(kwargs["payload"]["customer_message"])

    provider = _FakeProvider()
    report = module.qualify(repeats=2, provider=provider)

    assert report["qualification_status"] == "qualified"
    assert report["strict_transport_success_rate"]["rate"] == 1.0
    assert report["semantic_contract_success_rate"]["rate"] == 1.0
    assert report["repeat_structure_stability_rate"]["rate"] == 1.0
    assert report["deployment_enablement_allowed"] is False
    assert len(provider.calls) == len(module.FIXTURES) * 2
    assert all(call["allow_unqualified"] is True for call in provider.calls)


def test_qualification_does_not_require_non_authoritative_semantic_key_wording():
    module = _module()

    class _FakeProvider:
        last_latency_ms = 8.0

        def metadata(self):
            return {
                "provider_name": "test-provider",
                "host_fingerprint": "a" * 12,
                "model_name": "test-model",
                "configured": True,
                "qualified": False,
                "qualification_status": "provider_not_qualified",
            }

        def qualification_fingerprint(self):
            return "b" * 64

        def request(self, **kwargs):
            output = module.synthetic_provider_output(
                kwargs["payload"]["customer_message"]
            )
            for goal in output["goals"]:
                if goal["claim_type_status"] == "unmapped":
                    goal["semantic_key"] = "product_quality_review"
            return output

    report = module.qualify(repeats=1, provider=_FakeProvider())

    assert report["qualification_status"] == "qualified"
    assert report["semantic_contract_success_rate"]["rate"] == 1.0


def test_qualification_accepts_terminal_punctuation_on_an_exact_source_span():
    module = _module()

    class _FakeProvider:
        last_latency_ms = 8.0

        def metadata(self):
            return {
                "provider_name": "test-provider",
                "host_fingerprint": "a" * 12,
                "model_name": "test-model",
                "configured": True,
                "qualified": False,
                "qualification_status": "provider_not_qualified",
            }

        def qualification_fingerprint(self):
            return "b" * 64

        def request(self, **kwargs):
            message = kwargs["payload"]["customer_message"]
            output = module.synthetic_provider_output(message)
            for goal in output["goals"]:
                with_terminal_mark = f'{goal["source_text"]}？'
                if with_terminal_mark in message:
                    goal["source_text"] = with_terminal_mark
            return output

    report = module.qualify(repeats=1, provider=_FakeProvider())

    assert report["qualification_status"] == "qualified"
    assert report["semantic_contract_success_rate"]["rate"] == 1.0
