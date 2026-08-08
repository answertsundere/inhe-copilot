from __future__ import annotations

from typing import Any

from scripts import qualify_unified_audit_role as qualification


def _provider_result(
    contract: list[dict[str, Any]],
    *,
    expected_passed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "unified-textual-audit-v3",
        "goal_reviews": [
            {
                "goal_ref": item["goal_ref"],
                "clause_ref": item["clause_ref"],
                "clause_kind": item["clause_kind"],
                "textual_status": "accepted",
                # The server derives semantic-budget findings from the vector;
                # they are intentionally not model-supplied finding codes.
                "finding_codes": [],
            }
            for item in contract
        ],
        "semantic_budget_checks": [
            {
                "goal_ref": item["goal_ref"],
                "clause_ref": item["clause_ref"],
                "advice_status": "absent",
                "variability_factor_status": "within_budget",
                "restricted_boundary_status": "not_applicable",
                "qualifier_status": (
                    "satisfied" if expected_passed else "violated"
                ),
                "conclusion_status": "within_budget",
            }
            for item in contract
            if item["semantic_budget_applicable"]
        ],
        "global_finding_codes": [],
    }


class _FakeProvider:
    def __init__(
        self,
        *,
        accept_unsafe: bool = False,
        configured: bool = True,
        provider_error: str = "",
    ):
        self.accept_unsafe = accept_unsafe
        self.configured = configured
        self.provider_error = provider_error
        self.calls: list[dict[str, Any]] = []
        self.last_latency_ms = 7.5

    def metadata(self) -> dict[str, Any]:
        return {
            "provider_name": "fake",
            "host_fingerprint": "0123456789ab",
            "model_name": "fake-model",
            "capability": "strict_json_schema",
            "configured": self.configured,
            "qualified": False,
            "disable_thinking": False,
        }

    def request(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.provider_error:
            raise qualification.StrictDecisionProviderError(self.provider_error)
        contract = kwargs["payload"]["unified_textual_contract"]
        unsafe = (
            "没有做过相关测试" in contract[0]["clause_text"]
        )
        return _provider_result(
            contract,
            expected_passed=False if unsafe and not self.accept_unsafe else True,
        )

    def qualification_fingerprint(self) -> str:
        return "f" * 64


def test_fixtures_are_synthetic_and_hold_the_same_qualifier_contract():
    fixtures = qualification.qualification_fixtures()

    assert [item["cohort"] for item in fixtures] == [
        "evidence_availability",
        "unsupported_test_status",
    ]
    assert all(len(item["contract"]) == 1 for item in fixtures)
    assert {
        tuple(item["contract"][0]["required_qualifiers"])
        for item in fixtures
    } == {("no_absolute_guarantee", "no_test_claim")}
    assert {
        item["contract"][0]["allowed_conclusion_family"]
        for item in fixtures
    } == {"ordinary_minor_impact_tolerance"}


def test_role_qualification_accepts_only_the_complete_five_plus_five_matrix():
    provider = _FakeProvider()

    report, exit_code = qualification.run_qualification(provider=provider)

    assert exit_code == 0
    assert report["status"] == "qualified"
    assert report["attempted"] == 10
    assert report["provider_call_count"] == 10
    assert report["qualification_fingerprint"] == "f" * 64
    assert report["retry_count"] == 0
    assert report["repair_count"] == 0
    assert report["formal_knowledge_read_count"] == 0
    assert report["formal_knowledge_dml"] == 0
    assert report["can_change_can_send"] is False
    assert len(provider.calls) == 10
    assert all(call["allow_unqualified"] is True for call in provider.calls)
    assert all(call["name"] == "unified_textual_audit_v3" for call in provider.calls)


def test_role_qualification_stops_at_the_first_unsafe_false_acceptance():
    provider = _FakeProvider(accept_unsafe=True)

    report, exit_code = qualification.run_qualification(provider=provider)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 6
    assert report["provider_call_count"] == 6
    assert report["hard_stop_reason"].startswith(
        "unsupported_test_status_attempt_1:"
    )
    assert len(provider.calls) == 6


def test_role_qualification_rejects_any_repeat_count_other_than_five():
    try:
        qualification.run_qualification(repeat=4, provider=_FakeProvider())
    except ValueError as exc:
        assert str(exc) == "repeat_must_equal_5"
    else:
        raise AssertionError("repeat gate must fail closed")


def test_role_qualification_does_not_call_an_unconfigured_provider():
    provider = _FakeProvider(configured=False)

    report, exit_code = qualification.run_qualification(provider=provider)

    assert exit_code == 2
    assert report["status"] == "invalid_run"
    assert report["reason"] == "provider_not_configured"
    assert provider.calls == []


def test_role_qualification_stops_on_the_first_provider_error():
    provider = _FakeProvider(provider_error="provider_request_failed")

    report, exit_code = qualification.run_qualification(provider=provider)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 1
    assert report["provider_call_count"] == 1
    assert report["hard_stop_reason"] == (
        "evidence_availability_attempt_1:provider_request_failed"
    )
    assert len(provider.calls) == 1
