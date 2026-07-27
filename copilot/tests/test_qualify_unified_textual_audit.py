from scripts import qualify_unified_textual_audit as qualification
from scripts.qualify_unified_textual_audit import (
    qualification_cases,
    recompute_historical_report,
)


def test_unified_textual_audit_qualification_cases_are_bounded_and_generic():
    cases = qualification_cases()

    assert [item["case_id"] for item in cases] == [
        "supported_unresolved_valid",
        "history_conflict_candidate_valid",
        "unresolved_asserted_invalid",
        "evidence_expansion_invalid",
    ]
    assert [item["expected_pass"] for item in cases] == [
        True,
        True,
        False,
        False,
    ]
    assert cases[2]["expected_finding"] == "unresolved_claim_asserted"
    assert cases[3]["expected_finding"] == "unsupported_claim"
    for item in cases:
        response = item["response"]
        assert response["can_send"] is False
        assert response["requires_human_review"] is True
        assert response["sendable_reply"] == ""
        assert len(
            response["model_first_answer_composer"]["clauses"]
        ) == 2
        assert not {
            "sku_code",
            "i_id",
            "order_id",
            "scenario_uid",
        } & set(response)


def _historical_attempt(
    *,
    case_id,
    attempt,
    expected_pass,
    finding_codes,
):
    goal_finding_codes = list(finding_codes)
    return {
        "case_id": case_id,
        "attempt": attempt,
        "expected_pass": expected_pass,
        "unified_passed": expected_pass,
        "finding_codes": list(finding_codes),
        "goal_review_refs": [
            {
                "goal_ref": "goal-supported",
                "clause_ref": "clause-supported",
                "textual_status": (
                    "accepted"
                    if expected_pass
                    else "rejected"
                ),
                "finding_codes": goal_finding_codes,
            },
            {
                "goal_ref": "goal-unresolved",
                "clause_ref": "clause-unresolved",
                "textual_status": "accepted",
                "finding_codes": [],
            },
        ],
        "model_call_count": 1,
    }


def test_historical_recompute_preserves_verdict_and_canonical_root():
    attempts = []
    for case_id in (
        "supported_unresolved_valid",
        "history_conflict_candidate_valid",
    ):
        attempts.extend(
            _historical_attempt(
                case_id=case_id,
                attempt=index,
                expected_pass=True,
                finding_codes=[],
            )
            for index in range(1, 4)
        )
    attempts.extend(
        _historical_attempt(
            case_id="unresolved_asserted_invalid",
            attempt=index,
            expected_pass=False,
            finding_codes=["unresolved_claim_asserted"],
        )
        for index in range(1, 4)
    )
    attempts.extend([
        _historical_attempt(
            case_id="evidence_expansion_invalid",
            attempt=1,
            expected_pass=False,
            finding_codes=[
                "semantic_mismatch",
                "unsupported_claim",
            ],
        ),
        _historical_attempt(
            case_id="evidence_expansion_invalid",
            attempt=2,
            expected_pass=False,
            finding_codes=["unsupported_claim"],
        ),
    ])

    result = recompute_historical_report({"attempts": attempts})

    assert result["status"] == "recomputed"
    assert result["offline_model_call_count"] == 0
    assert result["historical_recorded_model_call_count"] == 11
    assert result["summary"]["attempt_count"] == 11
    assert result["summary"]["legal_pass_count"] == 6
    assert result["summary"]["illegal_reject_count"] == 5
    evidence_attempts = [
        item
        for item in result["attempts"]
        if item["case_id"] == "evidence_expansion_invalid"
    ]
    assert [
        item["goal_clause_attribution"][0][
            "primary_finding_code"
        ]
        for item in evidence_attempts
    ] == ["unsupported_claim", "unsupported_claim"]
    assert evidence_attempts[0]["goal_clause_attribution"][0][
        "secondary_finding_codes"
    ] == ["semantic_mismatch"]
    assert evidence_attempts[1]["goal_clause_attribution"][0][
        "secondary_finding_codes"
    ] == []
    assert result["blockers"] == []


def test_historical_recompute_reports_missing_attribution():
    result = recompute_historical_report({
        "attempts": [{
            "case_id": "missing",
            "attempt": 1,
            "expected_pass": False,
            "unified_passed": False,
            "finding_codes": ["unsupported_claim"],
            "goal_review_refs": [],
        }],
    })

    assert result["status"] == "invalid"
    assert result["offline_model_call_count"] == 0
    assert result["blockers"] == [
        "missing:historical_attribution_incomplete"
    ]


class _ConfiguredClient:
    api_key = "configured"
    model = "fake-model"


def test_qualification_uses_canonical_stability_not_secondary_variation(
    monkeypatch,
):
    calls = {"count": 0}

    def fake_semantic(response, **_kwargs):
        index = calls["count"]
        calls["count"] += 1
        case_index = index // 3
        finding_codes = []
        passed = case_index < 2
        if case_index == 2:
            finding_codes = ["unresolved_claim_asserted"]
        elif case_index == 3:
            finding_codes = [
                ["unsupported_claim"],
                ["unsupported_product_claim"],
                [
                    "unsupported_product_claim",
                    "semantic_mismatch",
                ],
            ][index % 3]
        canonical, issue = (
            qualification._canonicalize_finding_codes(
                finding_codes
            )
        )
        assert issue == ""
        return {
            "passed": passed,
            "issues": sorted(set(finding_codes)),
            "goal_reviews": [
                {
                    "goal_ref": "goal-supported",
                    "clause_ref": "clause-supported",
                    "textual_status": (
                        "accepted"
                        if passed
                        else "rejected"
                    ),
                    "finding_codes": finding_codes,
                },
                {
                    "goal_ref": "goal-unresolved",
                    "clause_ref": "clause-unresolved",
                    "textual_status": "accepted",
                    "finding_codes": [],
                },
            ],
            "canonical_goal_findings": [
                {
                    "goal_ref": "goal-supported",
                    "clause_ref": "clause-supported",
                    **canonical,
                },
                {
                    "goal_ref": "goal-unresolved",
                    "clause_ref": "clause-unresolved",
                    "blocking": False,
                    "primary_finding_family": "",
                    "primary_finding_code": "",
                    "secondary_finding_codes": [],
                    "raw_finding_codes": [],
                    "canonical_findings": [],
                    "normalization_status": "no_findings",
                },
            ],
            "canonical_global_findings": {
                "blocking": False,
                "primary_finding_family": "",
                "primary_finding_code": "",
                "secondary_finding_codes": [],
                "raw_finding_codes": [],
                "canonical_findings": [],
                "normalization_status": "no_findings",
            },
            "provider_diagnostics": {
                "model_call_count": 1,
                "retry_count": 0,
                "repair_count": 0,
                "finish_reason": "stop",
                "provider_latency_ms": 1,
            },
            "validation_diagnostics": {"category": "accepted"},
        }

    monkeypatch.setattr(
        qualification,
        "get_llm_client",
        lambda: _ConfiguredClient(),
    )
    monkeypatch.setattr(
        qualification,
        "audit_customer_reply_semantic_fit",
        fake_semantic,
    )

    report, exit_code = qualification.run_qualification(repeat=3)

    assert exit_code == 0
    assert report["status"] == "qualified"
    assert report["summary"]["attempt_count"] == 12
    assert report["summary"]["stability_comparison_count"] == 8
    assert report["summary"][
        "primary_code_stable_comparison_count"
    ] == 8
    assert report["summary"][
        "primary_family_stable_comparison_count"
    ] == 8
    assert report["summary"][
        "canonical_roots_stable_comparison_count"
    ] == 8
    evidence_attempts = report["attempts"][-3:]
    assert {
        item["canonical_goal_findings"][0][
            "primary_finding_code"
        ]
        for item in evidence_attempts
    } == {"unsupported_claim"}
    assert {
        tuple(
            item["canonical_goal_findings"][0][
                "primary_canonical_subtypes"
            ]
        )
        for item in evidence_attempts
    } == {
        ("generic",),
        ("product_claim",),
    }
