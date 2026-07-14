import importlib.util
from pathlib import Path

from app.services.strict_decision_provider_service import StrictDecisionProviderConfig, StrictDecisionProviderService


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "qualify_strict_decision_provider.py"
_SPEC = importlib.util.spec_from_file_location("qualify_strict_decision_provider", _SCRIPT_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)


def test_local_qualification_checks_reject_mutated_contracts():
    checks = _MODULE._local_contract_checks()
    assert all(checks.values())


def test_unconfigured_qualification_is_read_only_and_not_qualified():
    provider = StrictDecisionProviderService(config=StrictDecisionProviderConfig(
        provider_name="", api_base="", api_key="", model="", capability="unsupported", timeout_seconds=3, qualified=False,
    ))
    report = _MODULE.qualify(repeats=2, provider=provider)
    assert report["qualification_status"] == "not_qualified"
    assert report["shadow_enablement_allowed"] is False
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
    assert report["parse_fallback_count"] == 0


def test_qualification_report_does_not_expose_provider_secret_or_base():
    provider = StrictDecisionProviderService(config=StrictDecisionProviderConfig(
        provider_name="test", api_base="https://hidden.example.invalid/v1", api_key="not-for-report", model="test-model",
        capability="unsupported", timeout_seconds=3, qualified=False,
    ))
    report = _MODULE.qualify(repeats=1, provider=provider)
    text = str(report)
    assert "hidden.example.invalid" not in text
    assert "not-for-report" not in text
