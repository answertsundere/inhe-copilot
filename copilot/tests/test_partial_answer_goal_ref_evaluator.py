from copy import deepcopy

import pytest

from scripts import compare_model_first_answer_composer as comparison


def _response() -> dict:
    return {
        "suggested_reply": "已回答一个目标，并保留另一个未解决目标。",
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
        "turn_understanding": {
            "goal_understanding_status": "valid",
            "customer_goals": [
                {
                    "goal_ref": "goal-supported",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "material",
                },
                {
                    "goal_ref": "goal-unresolved",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "semantic_key": "",
                },
            ],
        },
        "minimal_decision_context": {
            "admitted_evidence": [
                {"evidence_uid": "evidence-material"},
            ],
            "claim_resolutions": [
                {
                    "goal_ref": "goal-supported",
                    "claim_uid": "claim-supported",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "material",
                    "status": "supported",
                    "evidence_uids": ["evidence-material"],
                },
                {
                    "goal_ref": "goal-unresolved",
                    "claim_uid": "claim-unresolved",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "semantic_key": "",
                    "status": "unresolved",
                    "evidence_uids": [],
                },
            ],
        },
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
            "can_change_can_send": False,
            "can_send": False,
            "requires_human_review": True,
            "used_evidence_uids": ["evidence-material"],
            "unresolved_claim_types": [],
            "clauses": [
                {
                    "goal_ref": "claim-supported",
                    "clause_kind": "supported_fact",
                    "evidence_uids": ["evidence-material"],
                },
                {
                    "goal_ref": "claim-unresolved",
                    "clause_kind": "unresolved",
                    "evidence_uids": [],
                },
            ],
        },
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"passed": True, "issues": []},
    }


def _diagnostics(response: dict) -> dict:
    return comparison._goal_ref_partial_answer_diagnostics(response)


@pytest.mark.parametrize("semantic_value", ["durability_hint", "", ...])
def test_unmapped_optional_semantic_metadata_does_not_change_coverage(
    semantic_value,
):
    response = _response()
    goal = response["turn_understanding"]["customer_goals"][1]
    resolution = response["minimal_decision_context"]["claim_resolutions"][1]
    if semantic_value is ...:
        goal.pop("semantic_key")
        resolution.pop("semantic_key")
    else:
        goal["semantic_key"] = semantic_value
        resolution["semantic_key"] = semantic_value

    result = _diagnostics(response)

    assert result["partial_answer_contract_pass"] is True
    assert result["unresolved_goal_coverage_rate"] == 1.0


def test_missing_unresolved_clause_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"].pop()

    result = _diagnostics(response)

    assert result["unresolved_goal_coverage_numerator"] == 0
    assert result["partial_answer_contract_pass"] is False


def test_wrong_unresolved_goal_ref_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"][1][
        "goal_ref"
    ] = "claim-unknown"

    result = _diagnostics(response)

    assert result["unknown_goal_ref_count"] == 1
    assert result["unresolved_goal_coverage_numerator"] == 0
    assert result["partial_answer_contract_pass"] is False


def test_duplicate_unresolved_clause_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"].append(
        deepcopy(response["model_first_answer_composer"]["clauses"][1])
    )

    result = _diagnostics(response)

    assert result["duplicate_goal_ref_clause_count"] == 1
    assert result["unresolved_goal_coverage_numerator"] == 0
    assert result["partial_answer_contract_pass"] is False


def test_unresolved_goal_rendered_as_supported_fact_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"][1][
        "clause_kind"
    ] = "supported_fact"

    result = _diagnostics(response)

    assert result["wrong_clause_kind_count"] == 1
    assert result["partial_answer_contract_pass"] is False


def test_supported_goal_without_clause_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"].pop(0)

    result = _diagnostics(response)

    assert result["supported_goal_coverage_numerator"] == 0
    assert result["partial_answer_contract_pass"] is False


def test_supported_clause_with_wrong_admitted_evidence_fails():
    response = _response()
    response["minimal_decision_context"]["admitted_evidence"].append(
        {"evidence_uid": "evidence-other"}
    )
    response["model_first_answer_composer"]["used_evidence_uids"].append(
        "evidence-other"
    )
    response["model_first_answer_composer"]["clauses"][0][
        "evidence_uids"
    ] = ["evidence-other"]

    result = _diagnostics(response)

    assert result["unsupported_evidence_ref_count"] == 1
    assert result["unknown_evidence_ref_count"] == 0
    assert result["partial_answer_contract_pass"] is False


def test_supported_clause_with_unknown_evidence_fails():
    response = _response()
    response["model_first_answer_composer"]["used_evidence_uids"].append(
        "evidence-unknown"
    )
    response["model_first_answer_composer"]["clauses"][0][
        "evidence_uids"
    ] = ["evidence-unknown"]

    result = _diagnostics(response)

    assert result["unknown_evidence_ref_count"] == 1
    assert result["partial_answer_contract_pass"] is False


def _append_non_customer_resolution(
    response: dict,
    *,
    goal_kind: str,
    with_clause: bool,
) -> None:
    response["minimal_decision_context"]["claim_resolutions"].append(
        {
            "goal_ref": f"goal-{goal_kind}",
            "claim_uid": f"claim-{goal_kind}",
            "goal_kind": goal_kind,
            "status": "unresolved",
            "evidence_uids": [],
        }
    )
    if with_clause:
        response["model_first_answer_composer"]["clauses"].append(
            {
                "goal_ref": f"claim-{goal_kind}",
                "clause_kind": "unresolved",
                "evidence_uids": [],
            }
        )


def test_dependency_rendered_as_customer_unresolved_fails():
    response = _response()
    _append_non_customer_resolution(
        response,
        goal_kind="evidence_dependency",
        with_clause=True,
    )

    result = _diagnostics(response)

    assert result["non_customer_goal_clause_count"] == 1
    assert result["unresolved_goal_count"] == 1
    assert result["partial_answer_contract_pass"] is False


def test_dependency_without_factual_clause_is_excluded():
    response = _response()
    _append_non_customer_resolution(
        response,
        goal_kind="evidence_dependency",
        with_clause=False,
    )

    result = _diagnostics(response)

    assert result["non_customer_goal_clause_count"] == 0
    assert result["unresolved_goal_count"] == 1
    assert result["partial_answer_contract_pass"] is True


@pytest.mark.parametrize(
    ("goal_kind", "metric"),
    [
        ("service_action", "service_action_fact_clause_count"),
        ("media_request", "media_request_fact_clause_count"),
    ],
)
def test_non_factual_goal_rendered_as_fact_fails(goal_kind, metric):
    response = _response()
    _append_non_customer_resolution(
        response,
        goal_kind=goal_kind,
        with_clause=True,
    )

    result = _diagnostics(response)

    assert result[metric] == 1
    assert result["partial_answer_contract_pass"] is False


def test_unknown_extra_goal_clause_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"].append(
        {
            "goal_ref": "claim-extra",
            "clause_kind": "supported_fact",
            "evidence_uids": ["evidence-material"],
        }
    )

    result = _diagnostics(response)

    assert result["unknown_goal_ref_count"] == 1
    assert result["partial_answer_contract_pass"] is False


def test_one_clause_cannot_cover_multiple_goals():
    response = _response()
    response["model_first_answer_composer"]["clauses"][0]["goal_ref"] = [
        "claim-supported",
        "claim-unresolved",
    ]

    result = _diagnostics(response)

    assert result["multiple_goal_ref_clause_count"] == 1
    assert result["supported_goal_coverage_numerator"] == 0
    assert result["partial_answer_contract_pass"] is False


def test_same_claim_type_with_distinct_goal_refs_is_not_merged():
    response = _response()
    response["turn_understanding"]["customer_goals"].append(
        {
            "goal_ref": "goal-supported-second",
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
        }
    )
    response["minimal_decision_context"]["admitted_evidence"].append(
        {"evidence_uid": "evidence-material-second"}
    )
    response["minimal_decision_context"]["claim_resolutions"].append(
        {
            "goal_ref": "goal-supported-second",
            "claim_uid": "claim-supported-second",
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "status": "supported",
            "evidence_uids": ["evidence-material-second"],
        }
    )
    response["model_first_answer_composer"]["used_evidence_uids"].append(
        "evidence-material-second"
    )
    response["model_first_answer_composer"]["clauses"].append(
        {
            "goal_ref": "claim-supported-second",
            "clause_kind": "supported_fact",
            "evidence_uids": ["evidence-material-second"],
        }
    )

    result = _diagnostics(response)

    assert result["supported_goal_count"] == 2
    assert result["supported_goal_coverage_numerator"] == 2
    assert result["partial_answer_contract_pass"] is True


def test_empty_claim_type_is_attributed_by_goal_ref():
    result = _diagnostics(_response())

    assert result["unresolved_goal_count"] == 1
    assert result["unresolved_goal_coverage_numerator"] == 1
    assert result["partial_answer_contract_pass"] is True


def test_deleting_confirmed_clause_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"] = [
        response["model_first_answer_composer"]["clauses"][1]
    ]

    assert _diagnostics(response)["partial_answer_contract_pass"] is False


def test_deleting_unresolved_clause_fails():
    response = _response()
    response["model_first_answer_composer"]["clauses"] = [
        response["model_first_answer_composer"]["clauses"][0]
    ]

    assert _diagnostics(response)["partial_answer_contract_pass"] is False


def test_absolute_unresolved_wording_is_rejected_by_both_audits():
    response = _response()
    response["suggested_reply"] = "一个绝对事实声明。"
    response["final_answer_audit"]["passed"] = False
    response["final_semantic_fit_audit"]["passed"] = False

    result = _diagnostics(response)

    assert "final_audit_failed" in result["partial_answer_contract_reasons"]
    assert "semantic_audit_failed" in result[
        "partial_answer_contract_reasons"
    ]
    assert result["partial_answer_contract_pass"] is False


def test_can_send_true_fails():
    response = _response()
    response["can_send"] = True

    result = _diagnostics(response)

    assert "can_send_pollution" in result["partial_answer_contract_reasons"]
    assert result["partial_answer_contract_pass"] is False


def test_shadow_candidate_cannot_be_used_for_final_reply():
    response = _response()
    response["supervisor_candidate_preview"] = {
        "used_for_final_reply": True,
    }

    result = _diagnostics(response)

    assert result["shadow_candidate_formal_use_count"] == 1
    assert result["partial_answer_contract_pass"] is False


def test_empty_denominator_does_not_produce_fake_full_coverage():
    response = _response()
    response["turn_understanding"]["customer_goals"] = []
    response["minimal_decision_context"]["claim_resolutions"] = []
    response["model_first_answer_composer"]["clauses"] = []

    result = _diagnostics(response)

    assert result["supported_goal_coverage_rate"] is None
    assert result["unresolved_goal_coverage_rate"] is None
    assert result["partial_answer_contract_pass"] is None
    assert "partial_answer_denominator_empty" in result[
        "partial_answer_contract_reasons"
    ]


def test_input_order_does_not_change_goal_ref_evaluation():
    forward = _response()
    reverse = deepcopy(forward)
    reverse["turn_understanding"]["customer_goals"].reverse()
    reverse["minimal_decision_context"]["claim_resolutions"].reverse()
    reverse["minimal_decision_context"]["admitted_evidence"].reverse()
    reverse["model_first_answer_composer"]["clauses"].reverse()
    reverse["model_first_answer_composer"]["used_evidence_uids"].reverse()

    assert _diagnostics(forward) == _diagnostics(reverse)


def test_reply_phrasing_does_not_change_structured_goal_coverage():
    first = _response()
    second = deepcopy(first)
    first["suggested_reply"] = "表达甲。"
    second["suggested_reply"] = "完全不同的表达乙。"

    assert _diagnostics(first) == _diagnostics(second)


def test_duplicate_authoritative_goal_ref_fails_closed():
    response = _response()
    response["turn_understanding"]["customer_goals"].append(
        deepcopy(response["turn_understanding"]["customer_goals"][0])
    )

    result = _diagnostics(response)

    assert result["duplicate_goal_ref_count"] == 1
    assert result["partial_answer_contract_pass"] is False


def test_sendable_reply_pollution_fails():
    response = _response()
    response["sendable_reply"] = "must stay empty"

    result = _diagnostics(response)

    assert "sendable_reply_pollution" in result[
        "partial_answer_contract_reasons"
    ]
    assert result["partial_answer_contract_pass"] is False
