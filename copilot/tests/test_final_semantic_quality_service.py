import json

import pytest

from app import config
from app.services import final_semantic_quality_service as semantic_service
from app.services.final_semantic_quality_service import (
    _atomic_semantic_contract,
    _atomic_semantic_json_schema,
    _atomic_semantic_system_prompt,
    _canonicalize_finding_codes,
    _is_model_first_candidate,
    _semantic_budget_finding_codes,
    _validated_semantic_budget_checks,
    apply_semantic_fit_result,
    audit_customer_reply_semantic_fit,
    finding_ownership_matrix,
)


def test_model_first_detection_requires_candidate_reply_ownership():
    assert _is_model_first_candidate({
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
        },
    }) is True
    assert _is_model_first_candidate({
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": False,
            "composition_applicable": False,
        },
    }) is False


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, *, finish_reason="stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content, *, finish_reason="stop"):
        self.choices = [_FakeChoice(content, finish_reason=finish_reason)]


class _CountingClient:
    api_key = "test"
    model = "fake"

    def __init__(self, *, content=None, error=None, finish_reason="stop"):
        self.content = content
        self.error = error
        self.finish_reason = finish_reason
        self.call_count = 0
        self.last_kwargs = None

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _FakeResponse(
            self.content,
            finish_reason=self.finish_reason,
        )


class _FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return _FakeResponse(self.content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, content):
        self.client = type("Client", (), {"chat": _FakeChat(content)})()

    def create_chat_completion(self, **kwargs):
        return self.client.chat.completions.create(**kwargs)


def _model_first_atomic_response(*, inference: bool = False):
    second_status = "supported" if inference else "unresolved"
    second_basis = "bounded_inference" if inference else "none"
    second_kind = "allowed_inference" if inference else "unresolved"
    second_evidence = ["material-direct"] if inference else []
    return {
        "suggested_reply": (
            "这款主体材质为ABS塑料加硅胶。\n"
            + (
                "日常轻微滑落一般不用过度担心，但高处或反复跌落不能保证。"
                if inference
                else "目前无法确认能否保证摔不坏。"
            )
        ),
        "requires_human_review": True,
        "can_send": False,
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
            "clauses": [
                {
                    "clause_ref": "C1",
                    "goal_ref": "goal-material",
                    "clause_kind": "supported_fact",
                    "text": "这款主体材质为ABS塑料加硅胶。",
                    "evidence_uids": ["material-direct"],
                },
                {
                    "clause_ref": "C2",
                    "goal_ref": "goal-durability",
                    "clause_kind": second_kind,
                    "text": (
                        "日常轻微滑落一般不用过度担心，但高处或反复跌落不能保证。"
                        if inference
                        else "目前无法确认能否保证摔不坏。"
                    ),
                    "evidence_uids": second_evidence,
                    "inference_policy_refs": (
                        ["domain-policy:household@v1:minor-drop-guidance"]
                        if inference
                        else []
                    ),
                    "scope_qualifier": (
                        "ordinary_minor_accidental_drop"
                        if inference
                        else ""
                    ),
                    "inference_risk_level": "medium" if inference else "",
                    "maximum_risk_level": "medium" if inference else "",
                    "inference_review_only": inference,
                    "allowed_conclusion_family": (
                        "ordinary_minor_impact_tolerance"
                        if inference
                        else ""
                    ),
                    "allowed_variability_factor_families": (
                        [
                            "contact_surface",
                            "impact_angle",
                            "impact_height",
                        ]
                        if inference
                        else []
                    ),
                    "advice_mode": "none" if inference else "",
                    "required_qualifiers": (
                        ["no_absolute_guarantee"] if inference else []
                    ),
                    "prohibited_extensions": (
                        ["child_safety"] if inference else []
                    ),
                },
            ],
        },
        "minimal_decision_context": {
            "product_identity": {"resolved": True},
            "admitted_evidence": [{
                "evidence_uid": "material-direct",
                "fact_type": "material",
                "content": "主体材质为ABS塑料加硅胶。",
            }],
            "claim_resolutions": [
                {
                    "claim_uid": "goal-material",
                    "goal_kind": "customer_goal",
                    "claim_type": "material",
                    "status": "supported",
                    "support_basis": "direct_evidence",
                    "evidence_uids": ["material-direct"],
                },
                {
                    "claim_uid": "goal-durability",
                    "goal_kind": "customer_goal",
                    "claim_type": "durability",
                    "status": second_status,
                    "support_basis": second_basis,
                    "evidence_uids": second_evidence,
                    "inference_policy_refs": (
                        ["domain-policy:household@v1:minor-drop-guidance"]
                        if inference
                        else []
                    ),
                    "scope_qualifier": (
                        "ordinary_minor_accidental_drop"
                        if inference
                        else ""
                    ),
                    "inference_risk_level": "medium" if inference else "",
                    "maximum_risk_level": "medium" if inference else "",
                    "inference_review_only": inference,
                    "required_qualifiers": (
                        ["no_absolute_guarantee"] if inference else []
                    ),
                    "prohibited_extensions": (
                        ["child_safety"] if inference else []
                    ),
                    "eligible_policy_options": (
                        [{
                            "policy_ref": (
                                "domain-policy:household@v1:"
                                "minor-drop-guidance"
                            ),
                            "trusted_domain_pack_ref": (
                                "domain-policy:household@v1"
                            ),
                            "pack_content_sha256": "a" * 64,
                        }]
                        if inference
                        else []
                    ),
                },
            ],
            "bounded_inference_policies": (
                [{
                    "policy_ref": (
                        "domain-policy:household@v1:minor-drop-guidance"
                    ),
                    "maximum_risk_level": "medium",
                }]
                if inference
                else []
            ),
        },
        "evidence_debug": {
            "query_fact_type": "material",
            "admitted_answer_context": {
                "direct_product_facts": [{
                    "evidence_uid": "material-direct",
                    "source_type": "product_facts",
                    "evidence_role": "product_fact_direct",
                    "claim_types_supported": ["material"],
                    "text": "主体材质为ABS塑料加硅胶。",
                }],
                "direct_policy_facts": [],
                "unresolved_claims": (
                    []
                    if inference
                    else [{
                        "claim_uid": "goal-durability",
                        "claim_type": "durability",
                        "status": "unresolved",
                    }]
                ),
            },
        },
    }


def _atomic_judge_payload_for_response(response):
    contract = _atomic_semantic_contract(response)
    return {
        "schema_version": "unified-textual-audit-v3",
        "goal_reviews": [
            {
                "goal_ref": item["goal_ref"],
                "clause_ref": item["clause_ref"],
                "clause_kind": item["clause_kind"],
                "textual_status": "accepted",
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
                "restricted_boundary_status": (
                    "preserved"
                    if item["restricted_request_boundary"]
                    else "not_applicable"
                ),
                "qualifier_status": "satisfied",
                "conclusion_status": "within_budget",
            }
            for item in contract
            if item["semantic_budget_applicable"]
        ],
        "global_finding_codes": [],
    }


def _atomic_judge_payload(*, inference: bool = False):
    return _atomic_judge_payload_for_response(
        _model_first_atomic_response(inference=inference)
    )


def test_atomic_contract_exposes_restricted_request_boundary():
    response = _model_first_atomic_response(inference=True)
    boundary = {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "absolute_guarantee_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": "durability_absolute_guarantee",
        "policy_goal_family": "product_durability",
        "policy_intent_kind": "absolute_guarantee",
        "high_risk_claim_families": [],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    resolution = response["minimal_decision_context"][
        "claim_resolutions"
    ][1]
    resolution.update({
        "status": "unresolved",
        "support_basis": "none",
        "requested_claim_risk": "high",
        "restricted_request_boundary": boundary,
    })
    clause = response["model_first_answer_composer"]["clauses"][1]
    clause.update({
        "requested_claim_risk_level": "high",
        "restricted_request_boundary": boundary,
    })

    contract = _atomic_semantic_contract(response)
    bounded = next(
        item
        for item in contract
        if item["clause_kind"] == "allowed_inference"
    )

    assert bounded["requested_claim_risk_level"] == "high"
    assert bounded["inference_risk_level"] == "medium"
    assert bounded["restricted_request_boundary"][
        "must_remain_unresolved"
    ] is True
    assert bounded["restricted_boundary_applicable"] is True


def test_atomic_contract_exposes_canonical_semantic_budget():
    contract = _atomic_semantic_contract(
        _model_first_atomic_response(inference=True)
    )
    bounded = next(
        item
        for item in contract
        if item["clause_kind"] == "allowed_inference"
    )

    assert bounded["allowed_conclusion_family"] == (
        "ordinary_minor_impact_tolerance"
    )
    assert bounded["allowed_variability_factor_families"] == [
        "contact_surface",
        "impact_angle",
        "impact_height",
    ]
    assert bounded["required_qualifiers"] == [
        "no_absolute_guarantee",
    ]
    assert bounded["advice_mode"] == "none"
    assert bounded["trusted_domain_pack_ref"] == (
        "domain-policy:household@v1"
    )
    assert bounded["pack_content_sha256"] == "a" * 64


def test_atomic_prompt_requires_independent_cumulative_budget_checks():
    prompt = _atomic_semantic_system_prompt()

    assert "semantic_budget_checks row in the same order" in prompt
    assert "Natural paraphrases count by meaning" in prompt
    assert "Determine each dimension independently" in prompt
    assert "advice_mode=none forbids customer-directed advice" in prompt
    assert "concise_care_only authorizes at most one brief care instruction" in prompt
    assert "Topical relevance alone never authorizes an action" in prompt
    assert (
        "safety_handoff_required authorizes only risk-mitigation"
        in prompt
    )
    assert "checking damage or possible ingestion" in prompt
    assert "server derives all semantic-budget findings" in prompt
    assert "trusted_domain_pack_ref" in prompt
    assert "pack_content_sha256" in prompt
    assert "material property, causal explanation" in prompt
    assert "does not authorize presenting that factor" in prompt
    assert "authoritative restricted_boundary_applicable boolean" in prompt
    assert "return not_applicable regardless of caveats" in prompt
    assert "Do not infer boundary applicability from wording alone" in prompt
    assert "qualifier_status is satisfied only when" in prompt
    assert "Judge the whole qualifier set cumulatively" in prompt
    assert "fail-closed last resort for genuinely ambiguous language" in prompt
    assert "not an alternative to performing a supplied comparison" in prompt
    assert "semantically within prohibited_extensions is outside_budget" in prompt
    assert "no_test_claim or no_test_claim_without_direct_evidence" in prompt
    assert "does not permit asserting that the product was never tested" in prompt
    assert "It does not classify the meaning of customer-facing delivery wording" in prompt
    assert "completion_evidence.attached_media_blocks" in prompt
    assert "Candidate or catalog media is never delivery evidence" in prompt
    assert "regardless of the wording or synonym used" in prompt
    assert "always mechanically not_applicable" in prompt


@pytest.mark.parametrize(
    "mutation",
    [
        lambda option: option.update({
            "trusted_domain_pack_ref": "",
        }),
        lambda option: option.update({
            "pack_content_sha256": "not-a-sha256",
        }),
        lambda option: option.update({
            "policy_ref": "different-policy",
        }),
    ],
)
def test_atomic_contract_fails_closed_on_invalid_pack_identity(mutation):
    response = _model_first_atomic_response(inference=True)
    option = response["minimal_decision_context"][
        "claim_resolutions"
    ][1]["eligible_policy_options"][0]
    mutation(option)

    assert _atomic_semantic_contract(response) == []


def test_atomic_contract_rejects_conflicting_duplicate_pack_identity():
    response = _model_first_atomic_response(inference=True)
    option = response["minimal_decision_context"][
        "claim_resolutions"
    ][1]["eligible_policy_options"][0]
    response["minimal_decision_context"]["claim_resolutions"][0][
        "eligible_policy_options"
    ] = [{
        **option,
        "pack_content_sha256": "b" * 64,
    }]

    assert _atomic_semantic_contract(response) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda clause: clause.update({
            "allowed_conclusion_family": "",
        }),
        lambda clause: clause.update({
            "allowed_variability_factor_families": [
                "impact_height",
                "impact_height",
            ],
        }),
        lambda clause: clause.update({
            "advice_mode": "free_form_advice",
        }),
        lambda clause: clause.update({
            "required_qualifiers": [],
        }),
    ],
)
def test_atomic_contract_fails_closed_on_invalid_semantic_budget(
    mutation,
):
    response = _model_first_atomic_response(inference=True)
    clause = response["model_first_answer_composer"]["clauses"][1]
    mutation(clause)

    assert _atomic_semantic_contract(response) == []


def _semantic_budget_target(
    goal_ref,
    clause_ref,
    *,
    advice_mode="none",
    restricted_boundary=False,
):
    return {
        "goal_ref": goal_ref,
        "clause_ref": clause_ref,
        "semantic_budget_applicable": True,
        "advice_mode": advice_mode,
        "restricted_boundary_applicable": restricted_boundary,
        "restricted_request_boundary": (
            {"must_remain_unresolved": True}
            if restricted_boundary
            else {}
        ),
    }


def _semantic_budget_check(
    goal_ref,
    clause_ref,
    *,
    advice_status="absent",
    variability_factor_status="within_budget",
    restricted_boundary_status="not_applicable",
    qualifier_status="satisfied",
    conclusion_status="within_budget",
):
    return {
        "goal_ref": goal_ref,
        "clause_ref": clause_ref,
        "advice_status": advice_status,
        "variability_factor_status": variability_factor_status,
        "restricted_boundary_status": restricted_boundary_status,
        "qualifier_status": qualifier_status,
        "conclusion_status": conclusion_status,
    }


def test_semantic_budget_validator_accepts_zero_targets():
    checks, findings, diagnostics = _validated_semantic_budget_checks(
        [],
        atomic_contract=[],
    )

    assert checks == []
    assert findings == {}
    assert diagnostics["category"] == "accepted"


def test_semantic_budget_validator_accepts_multiple_targets_in_exact_order():
    contract = [
        _semantic_budget_target("goal-1", "clause-1"),
        _semantic_budget_target(
            "goal-2",
            "clause-2",
            advice_mode="concise_care_only",
            restricted_boundary=True,
        ),
    ]
    raw_checks = [
        _semantic_budget_check("goal-1", "clause-1"),
        _semantic_budget_check(
            "goal-2",
            "clause-2",
            advice_status="authorized",
            restricted_boundary_status="preserved",
        ),
    ]

    checks, findings, diagnostics = _validated_semantic_budget_checks(
        raw_checks,
        atomic_contract=contract,
    )

    assert checks == raw_checks
    assert findings == {
        ("goal-1", "clause-1"): [],
        ("goal-2", "clause-2"): [],
    }
    assert diagnostics["category"] == "accepted"


@pytest.mark.parametrize(
    "raw_checks",
    [
        [
            _semantic_budget_check("goal-2", "clause-2"),
            _semantic_budget_check("goal-1", "clause-1"),
        ],
        [
            _semantic_budget_check("goal-1", "clause-1"),
            _semantic_budget_check("goal-1", "clause-1"),
        ],
        [
            _semantic_budget_check("goal-1", "clause-1"),
            _semantic_budget_check("goal-1", "clause-2"),
        ],
    ],
)
def test_semantic_budget_validator_rejects_order_duplicate_and_cross_goal(
    raw_checks,
):
    checks, findings, diagnostics = _validated_semantic_budget_checks(
        raw_checks,
        atomic_contract=[
            _semantic_budget_target("goal-1", "clause-1"),
            _semantic_budget_target("goal-2", "clause-2"),
        ],
    )

    assert checks is None
    assert findings == {}
    assert diagnostics["category"] == (
        "semantic_budget_check_order_or_reference_invalid"
    )


@pytest.mark.parametrize(
    ("check", "expected_findings"),
    [
        (
            _semantic_budget_check(
                "goal",
                "clause",
                advice_status="unauthorized",
            ),
            ["advice_scope_exceeded"],
        ),
        (
            _semantic_budget_check(
                "goal",
                "clause",
                variability_factor_status="outside_budget",
            ),
            ["variability_factor_scope_exceeded"],
        ),
        (
            _semantic_budget_check(
                "goal",
                "clause",
                variability_factor_status="asserted_as_fact",
            ),
            ["variability_factor_asserted_as_fact"],
        ),
        (
            _semantic_budget_check(
                "goal",
                "clause",
                restricted_boundary_status="violated",
            ),
            ["restricted_boundary_violation"],
        ),
        (
            _semantic_budget_check(
                "goal",
                "clause",
                qualifier_status="violated",
            ),
            ["inference_scope_exceeded"],
        ),
        (
            _semantic_budget_check(
                "goal",
                "clause",
                conclusion_status="outside_budget",
            ),
            ["inference_scope_exceeded"],
        ),
    ],
)
def test_semantic_budget_status_mapping_is_deterministic(
    check,
    expected_findings,
):
    assert _semantic_budget_finding_codes(check) == expected_findings


def test_semantic_budget_qualifier_and_conclusion_violation_deduplicate():
    check = _semantic_budget_check(
        "goal",
        "clause",
        qualifier_status="violated",
        conclusion_status="outside_budget",
    )

    assert _semantic_budget_finding_codes(check) == [
        "inference_scope_exceeded"
    ]


@pytest.mark.parametrize(
    ("qualifier_status", "expected_category"),
    [
        ("unknown", "semantic_budget_status_invalid"),
        ("indeterminate", "semantic_budget_indeterminate"),
    ],
)
def test_semantic_budget_validator_rejects_invalid_qualifier_status(
    qualifier_status,
    expected_category,
):
    checks, findings, diagnostics = _validated_semantic_budget_checks(
        [
            _semantic_budget_check(
                "goal",
                "clause",
                qualifier_status=qualifier_status,
            )
        ],
        atomic_contract=[_semantic_budget_target("goal", "clause")],
    )

    assert checks is None
    assert findings == {}
    assert diagnostics["category"] == expected_category


def _mutated_atomic_payload(mutation):
    budget_mutation = mutation.startswith("budget_")
    payload = _atomic_judge_payload(inference=budget_mutation)
    checks = payload["goal_reviews"]
    first = checks[0]
    budget_checks = payload["semantic_budget_checks"]
    budget_first = budget_checks[0] if budget_checks else None
    if mutation == "top_level_extra":
        payload["extra"] = True
    elif mutation == "top_level_missing":
        payload.pop("global_finding_codes")
    elif mutation == "schema_version":
        payload["schema_version"] = "unknown"
    elif mutation == "goal_reviews_type":
        payload["goal_reviews"] = {}
    elif mutation == "global_finding_codes_type":
        payload["global_finding_codes"] = {}
    elif mutation == "global_issue_duplicate":
        payload["global_finding_codes"] = ["semantic_mismatch", "semantic_mismatch"]
    elif mutation == "global_issue_invalid":
        payload["global_finding_codes"] = ["unknown_issue"]
    elif mutation == "budget_checks_type":
        payload["semantic_budget_checks"] = {}
    elif mutation == "budget_missing_check":
        budget_checks.pop()
    elif mutation == "budget_extra_check":
        budget_checks.append(dict(budget_first))
    elif mutation == "budget_check_type":
        budget_checks[0] = "invalid"
    elif mutation == "budget_extra_field":
        budget_first["extra"] = True
    elif mutation == "budget_missing_field":
        budget_first.pop("conclusion_status")
    elif mutation == "budget_unknown_goal":
        budget_first["goal_ref"] = "unknown-goal"
    elif mutation == "budget_unknown_clause":
        budget_first["clause_ref"] = "unknown-clause"
    elif mutation == "budget_status_type":
        budget_first["advice_status"] = True
    elif mutation == "budget_status_enum":
        budget_first["advice_status"] = "sometimes"
    elif mutation == "budget_indeterminate":
        budget_first["conclusion_status"] = "indeterminate"
    elif mutation == "budget_boundary_applicability":
        budget_first["restricted_boundary_status"] = "preserved"
    elif mutation == "budget_advice_authorization":
        budget_first["advice_status"] = "authorized"
    elif mutation == "budget_finding_in_goal_review":
        checks[1].update({
            "textual_status": "rejected",
            "finding_codes": ["advice_scope_exceeded"],
        })
    elif mutation == "budget_finding_in_global":
        payload["global_finding_codes"] = ["advice_scope_exceeded"]
    elif mutation == "segment_type":
        checks[0] = "invalid"
    elif mutation == "segment_extra_field":
        first["extra"] = True
    elif mutation == "segment_missing_field":
        first.pop("textual_status")
    elif mutation == "duplicate_reference":
        checks[1] = dict(first)
    elif mutation == "unknown_goal":
        first["goal_ref"] = "unknown-goal"
    elif mutation == "unknown_clause":
        first["clause_ref"] = "unknown-clause"
    elif mutation == "clause_kind":
        first["clause_kind"] = "unknown"
    elif mutation == "textual_status":
        first["textual_status"] = True
    elif mutation == "issue_codes_type":
        first["finding_codes"] = {}
    elif mutation == "issue_code_duplicate":
        first.update({
            "textual_status": "rejected",
            "finding_codes": ["unsupported_claim", "unsupported_claim"],
        })
    elif mutation == "issue_code_invalid":
        first["finding_codes"] = ["unknown_issue"]
    elif mutation == "status_finding_mismatch":
        first.update({
            "textual_status": "rejected",
            "finding_codes": [],
        })
    elif mutation == "missing_segment":
        checks.pop()
    elif mutation == "duplicate_segment":
        checks.append(dict(first))
    elif mutation == "array_root":
        return []
    else:
        raise AssertionError(f"Unknown mutation: {mutation}")
    return payload


def test_final_semantic_fit_uses_llm_judge_to_block_wrong_answer(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["answered_space_fit_as_load_capacity"], "reason": "Customer asks fit/space but reply answers load capacity."}'
        ),
    )
    response = {
        "suggested_reply": "亲～这款单层均匀承重约15-30kg，放书和玩具都够用。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "space_fit"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "space_fit",
                    "matched_facts": [
                        {
                            "fact_type": "space_fit",
                            "preview": "尺寸图可参考预留宽度、进深和高度。",
                "direct_answer_allowed": True,
                "material_provenance": "structured_product_record",
                        }
                    ],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is False
    assert result["mode"] == "llm_semantic_fit"
    assert "answered_space_fit_as_load_capacity" in result["issues"]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not-json",
        json.dumps({"passed": True, "issues": []}),
        json.dumps({
            "passed": True,
            "issues": [],
            "reason": "ok",
            "extra": "not allowed",
        }),
        json.dumps({
            "passed": False,
            "issues": ["unknown_issue"],
            "reason": "blocked",
        }),
        json.dumps({
            "passed": True,
            "issues": ["semantic_mismatch"],
            "reason": "contradictory",
        }),
    ],
)
def test_model_first_semantic_fit_fails_closed_on_invalid_schema(
    monkeypatch,
    content,
):
    client = _CountingClient(content=content)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]


@pytest.mark.parametrize(
    ("mutation", "expected_category"),
    [
        ("top_level_extra", "top_level_fields_invalid"),
        ("top_level_missing", "top_level_fields_invalid"),
        ("schema_version", "schema_version_invalid"),
        ("goal_reviews_type", "goal_reviews_type_invalid"),
        ("global_finding_codes_type", "global_finding_codes_type_invalid"),
        ("global_issue_invalid", "global_issue_code_invalid"),
        ("budget_checks_type", "semantic_budget_checks_type_invalid"),
        ("budget_missing_check", "semantic_budget_check_count_invalid"),
        ("budget_extra_check", "semantic_budget_check_count_invalid"),
        ("budget_check_type", "semantic_budget_check_type_invalid"),
        ("budget_extra_field", "semantic_budget_check_fields_invalid"),
        ("budget_missing_field", "semantic_budget_check_fields_invalid"),
        (
            "budget_unknown_goal",
            "semantic_budget_check_order_or_reference_invalid",
        ),
        (
            "budget_unknown_clause",
            "semantic_budget_check_order_or_reference_invalid",
        ),
        ("budget_status_type", "semantic_budget_status_invalid"),
        ("budget_status_enum", "semantic_budget_status_invalid"),
        ("budget_indeterminate", "semantic_budget_indeterminate"),
        (
            "budget_boundary_applicability",
            "semantic_budget_boundary_applicability_invalid",
        ),
        (
            "budget_advice_authorization",
            "semantic_budget_advice_authorization_invalid",
        ),
        ("budget_finding_in_goal_review", "issue_code_invalid"),
        ("budget_finding_in_global", "global_issue_code_invalid"),
        ("segment_type", "segment_type_invalid"),
        ("segment_extra_field", "segment_fields_invalid"),
        ("segment_missing_field", "segment_fields_invalid"),
        ("duplicate_reference", "duplicate_segment_reference"),
        ("unknown_goal", "unknown_segment_reference"),
        ("unknown_clause", "unknown_segment_reference"),
        ("clause_kind", "clause_kind_mismatch"),
        ("textual_status", "textual_status_invalid"),
        ("issue_codes_type", "finding_codes_type_invalid"),
        ("issue_code_invalid", "issue_code_invalid"),
        ("status_finding_mismatch", "textual_status_finding_mismatch"),
        ("missing_segment", "segment_reference_set_incomplete"),
        ("duplicate_segment", "duplicate_segment_reference"),
        ("array_root", "free_text_response"),
    ],
)
def test_atomic_semantic_audit_mutations_fail_closed_with_exact_diagnostics(
    monkeypatch,
    mutation,
    expected_category,
):
    client = _CountingClient(
        content=json.dumps(_mutated_atomic_payload(mutation))
    )
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(
            inference=mutation.startswith("budget_")
        ),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]
    assert result["validation_diagnostics"]["category"] == expected_category
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    if mutation in {
        "budget_missing_check",
        "budget_extra_check",
        "budget_indeterminate",
    }:
        assert "raw_semantic_budget_checks" in result
    if mutation == "budget_indeterminate":
        assert result["raw_semantic_budget_checks"][0][
            "conclusion_status"
        ] == "indeterminate"
    if mutation in {
        "budget_extra_field",
        "budget_missing_field",
        "budget_status_enum",
    }:
        assert "raw_semantic_budget_checks" not in result


@pytest.mark.parametrize(
    "mutation",
    ["global_issue_duplicate", "issue_code_duplicate"],
)
def test_atomic_semantic_audit_canonicalizes_duplicate_findings(
    monkeypatch,
    mutation,
):
    client = _CountingClient(
        content=json.dumps(_mutated_atomic_payload(mutation))
    )
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["normalization_status"] == "canonicalized"
    if mutation == "issue_code_duplicate":
        finding = result["canonical_goal_findings"][0]
    else:
        finding = result["canonical_global_findings"]
    assert finding["primary_finding_code"] in {
        "semantic_mismatch",
        "unsupported_claim",
    }
    assert finding["raw_finding_codes"] == (
        ["unsupported_claim", "unsupported_claim"]
        if mutation == "issue_code_duplicate"
        else ["semantic_mismatch", "semantic_mismatch"]
    )


def test_finding_ownership_matrix_covers_all_allowed_codes():
    matrix = finding_ownership_matrix()

    codes = [item["raw_finding_code"] for item in matrix]
    assert len(codes) == len(set(codes)) == 25
    assert {
        "factual_fidelity",
        "unresolved_boundary",
        "goal_coverage",
        "conversation_continuity",
        "unsupported_completion",
        "relevance",
        "communication_quality",
        "policy_semantic_budget",
    } == {item["canonical_family"] for item in matrix}
    assert all(item["blocking"] is True for item in matrix)
    by_code = {
        item["raw_finding_code"]: item
        for item in matrix
    }
    assert by_code["unsupported_claim"]["canonical_root_code"] == (
        "unsupported_claim"
    )
    assert by_code["unsupported_claim"]["canonical_subtype"] == (
        "generic"
    )
    assert by_code["unsupported_product_claim"][
        "canonical_root_code"
    ] == "unsupported_claim"
    assert by_code["unsupported_product_claim"][
        "canonical_subtype"
    ] == "product_claim"


@pytest.mark.parametrize(
    "raw_codes",
    [
        ["unsupported_claim", "semantic_mismatch"],
        ["semantic_mismatch", "unsupported_claim"],
        [
            "unsupported_claim",
            "semantic_mismatch",
            "unsupported_claim",
        ],
    ],
)
def test_finding_canonicalizer_stabilizes_supported_root_with_secondary(
    raw_codes,
):
    before = list(raw_codes)

    normalized, issue = _canonicalize_finding_codes(raw_codes)

    assert issue == ""
    assert raw_codes == before
    assert normalized["blocking"] is True
    assert normalized["primary_finding_family"] == "factual_fidelity"
    assert normalized["primary_finding_code"] == "unsupported_claim"
    assert normalized["secondary_finding_codes"] == [
        "semantic_mismatch"
    ]
    assert normalized["raw_finding_codes"] == before
    assert normalized["canonical_findings"] == [{
        "finding_family": "factual_fidelity",
        "finding_code": "unsupported_claim",
        "canonical_root_code": "unsupported_claim",
        "raw_finding_codes": ["unsupported_claim"],
        "canonical_subtypes": ["generic"],
        "blocking": True,
        "secondary_finding_codes": ["semantic_mismatch"],
    }]


@pytest.mark.parametrize(
    ("raw_codes", "expected_subtypes"),
    [
        (["unsupported_claim"], ["generic"]),
        (["unsupported_product_claim"], ["product_claim"]),
        (
            [
                "unsupported_claim",
                "unsupported_product_claim",
            ],
            ["generic", "product_claim"],
        ),
        (
            [
                "unsupported_product_claim",
                "unsupported_claim",
                "unsupported_product_claim",
            ],
            ["generic", "product_claim"],
        ),
    ],
)
def test_unsupported_claim_aliases_share_only_the_approved_root(
    raw_codes,
    expected_subtypes,
):
    normalized, issue = _canonicalize_finding_codes(raw_codes)

    assert issue == ""
    assert normalized["blocking"] is True
    assert normalized["primary_finding_family"] == "factual_fidelity"
    assert normalized["primary_finding_code"] == "unsupported_claim"
    assert normalized["primary_canonical_root_code"] == (
        "unsupported_claim"
    )
    assert normalized["primary_canonical_subtypes"] == expected_subtypes
    assert normalized["raw_finding_codes"] == raw_codes
    assert {
        item["raw_finding_code"]
        for item in normalized["raw_finding_details"]
    } == set(raw_codes)
    assert len(normalized["canonical_findings"]) == 1


def test_product_claim_alias_with_semantic_secondary_keeps_root():
    normalized, issue = _canonicalize_finding_codes([
        "semantic_mismatch",
        "unsupported_product_claim",
    ])

    assert issue == ""
    assert normalized["primary_finding_code"] == "unsupported_claim"
    assert normalized["primary_canonical_subtypes"] == ["product_claim"]
    assert normalized["secondary_finding_codes"] == [
        "semantic_mismatch"
    ]


def test_finding_canonicalizer_does_not_invent_unsupported_root():
    normalized, issue = _canonicalize_finding_codes(
        ["semantic_mismatch"]
    )

    assert issue == ""
    assert normalized["primary_finding_family"] == "relevance"
    assert normalized["primary_finding_code"] == "semantic_mismatch"
    assert normalized["secondary_finding_codes"] == []


def test_finding_canonicalizer_preserves_independent_roots():
    normalized, issue = _canonicalize_finding_codes([
        "unsupported_claim",
        "unresolved_claim_asserted",
        "semantic_mismatch",
    ])

    assert issue == ""
    assert {
        item["finding_code"]
        for item in normalized["canonical_findings"]
    } == {"unsupported_claim", "unresolved_claim_asserted"}
    assert normalized["primary_finding_code"] == (
        "unresolved_claim_asserted"
    )


@pytest.mark.parametrize(
    ("raw_codes", "expected_issue"),
    [
        (["unknown_issue"], "finding_code_unknown"),
        (
            [
                "missing_evidence_without_human_review",
                "unnecessary_handoff",
            ],
            "finding_code_conflict",
        ),
    ],
)
def test_finding_canonicalizer_rejects_unknown_or_conflicting_codes(
    raw_codes,
    expected_issue,
):
    normalized, issue = _canonicalize_finding_codes(raw_codes)

    assert normalized is None
    assert issue == expected_issue


def test_atomic_semantic_audit_keeps_findings_on_separate_goals(
    monkeypatch,
):
    payload = _atomic_judge_payload()
    payload["goal_reviews"][0].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_claim"],
    })
    payload["goal_reviews"][1].update({
        "textual_status": "rejected",
        "finding_codes": ["semantic_mismatch"],
    })
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    assert [
        item["primary_finding_code"]
        for item in result["canonical_goal_findings"]
    ] == ["unsupported_claim", "semantic_mismatch"]


def test_unsupported_aliases_on_different_goals_remain_separate(
    monkeypatch,
):
    payload = _atomic_judge_payload()
    payload["goal_reviews"][0].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_claim"],
    })
    payload["goal_reviews"][1].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_product_claim"],
    })
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    findings = result["canonical_goal_findings"]
    assert len(findings) == 2
    assert [item["goal_ref"] for item in findings] == [
        "goal_01",
        "goal_02",
    ]
    assert [item["primary_finding_code"] for item in findings] == [
        "unsupported_claim",
        "unsupported_claim",
    ]
    assert [item["primary_canonical_subtypes"] for item in findings] == [
        ["generic"],
        ["product_claim"],
    ]


def test_atomic_semantic_audit_prefers_goal_attribution_over_global_duplicate(
    monkeypatch,
):
    payload = _atomic_judge_payload()
    payload["goal_reviews"][0].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_claim"],
    })
    payload["global_finding_codes"] = ["unsupported_claim"]
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    assert result["canonical_goal_findings"][0][
        "primary_finding_code"
    ] == "unsupported_claim"
    assert result["canonical_global_findings"]["canonical_findings"] == []
    assert result["canonical_global_findings"][
        "secondary_finding_codes"
    ] == ["unsupported_claim"]
    assert result["canonical_global_findings"][
        "raw_finding_codes"
    ] == ["unsupported_claim"]


def test_finding_canonicalization_is_hash_stable_and_input_immutable():
    first_input = [
        "semantic_mismatch",
        "unsupported_claim",
        "unsupported_claim",
    ]
    second_input = list(reversed(first_input))
    first_before = json.dumps(first_input)
    second_before = json.dumps(second_input)

    first, first_issue = _canonicalize_finding_codes(first_input)
    second, second_issue = _canonicalize_finding_codes(second_input)

    assert first_issue == second_issue == ""
    assert json.dumps(first_input) == first_before
    assert json.dumps(second_input) == second_before
    stable_fields = (
        "blocking",
        "primary_finding_family",
        "primary_finding_code",
        "secondary_finding_codes",
        "canonical_findings",
    )
    first_stable = {
        key: first[key]
        for key in stable_fields
    }
    second_stable = {
        key: second[key]
        for key in stable_fields
    }
    assert first_stable == second_stable
    assert json.dumps(
        first_stable,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        second_stable,
        sort_keys=True,
        separators=(",", ":"),
    )


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```"])
def test_atomic_semantic_audit_accepts_one_complete_json_fence(
    monkeypatch,
    fence,
):
    payload = json.dumps(_atomic_judge_payload())
    content = fence.format(payload)
    client = _CountingClient(content=content)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is True
    assert result["provider_diagnostics"]["response_envelope"] == (
        "single_json_fence"
    )
    assert result["provider_diagnostics"]["envelope_unwrap_count"] == 1
    assert result["provider_diagnostics"]["json_repair_count"] == 0


@pytest.mark.parametrize(
    ("content", "expected_category"),
    [
        ("analysis\n" + json.dumps(_atomic_judge_payload()), "free_text_response"),
        (
            "```json\n"
            + json.dumps(_atomic_judge_payload())
            + "\n```\n```json\n{}\n```",
            "json_envelope_invalid",
        ),
        ("```json\n{\"schema_version\":", "json_envelope_invalid"),
    ],
)
def test_atomic_semantic_audit_rejects_unbounded_or_incomplete_envelopes(
    monkeypatch,
    content,
    expected_category,
):
    client = _CountingClient(content=content)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]
    assert result["validation_diagnostics"]["category"] == expected_category
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert result["provider_diagnostics"]["retry_count"] == 0


def test_atomic_semantic_prompt_counts_direct_unresolved_declaration_as_answer(
    monkeypatch,
):
    client = _CountingClient(content=json.dumps(_atomic_judge_payload()))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    system_prompt = client.last_kwargs["messages"][0]["content"]
    assert result["passed"] is True
    assert "cannot be confirmed or guaranteed answers" in system_prompt
    assert "without asserting the fact" in system_prompt


@pytest.mark.parametrize("error", [TimeoutError("late"), RuntimeError("provider")])
def test_model_first_semantic_fit_fails_closed_when_judge_unavailable(
    monkeypatch,
    error,
):
    client = _CountingClient(error=error)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_unavailable"]
    assert result["validation_diagnostics"]["category"] == "provider_error"
    assert result["provider_diagnostics"]["provider_latency_ms"] is None


def test_atomic_semantic_audit_accepts_supported_and_unresolved_segments(
    monkeypatch,
):
    client = _CountingClient(content=json.dumps(_atomic_judge_payload()))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is True
    assert result["issues"] == []
    assert result["schema_version"] == "unified-textual-audit-v3"
    assert len(result["goal_reviews"]) == 2
    assert all(
        item["textual_status"] == "accepted"
        for item in result["goal_reviews"]
    )


def test_atomic_semantic_audit_accepts_policy_bounded_inference(monkeypatch):
    client = _CountingClient(
        content=json.dumps(_atomic_judge_payload(inference=True))
    )
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(inference=True),
        customer_message="这款是什么材质，日常不小心滑落容易坏吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is True
    assert result["issues"] == []
    assert any(
        item["clause_kind"] == "allowed_inference"
        for item in result["goal_reviews"]
    )


@pytest.mark.parametrize(
    (
        "status_field",
        "status_value",
        "finding_code",
        "boundary_required",
    ),
    [
        ("advice_status", "unauthorized", "advice_scope_exceeded", False),
        (
            "restricted_boundary_status",
            "violated",
            "restricted_boundary_violation",
            True,
        ),
        (
            "variability_factor_status",
            "asserted_as_fact",
            "variability_factor_asserted_as_fact",
            False,
        ),
        (
            "variability_factor_status",
            "outside_budget",
            "variability_factor_scope_exceeded",
            False,
        ),
        (
            "conclusion_status",
            "outside_budget",
            "inference_scope_exceeded",
            False,
        ),
        (
            "qualifier_status",
            "violated",
            "inference_scope_exceeded",
            False,
        ),
    ],
)
def test_atomic_semantic_audit_preserves_budget_finding_attribution(
    monkeypatch,
    status_field,
    status_value,
    finding_code,
    boundary_required,
):
    response = _model_first_atomic_response(inference=True)
    if boundary_required:
        boundary = {
            "schema_version": "restricted-request-boundary/v1",
            "status": "prohibited",
            "reason_code": "absolute_guarantee_prohibited",
            "requested_claim_risk": "high",
            "policy_intent_ref": "durability_absolute_guarantee",
            "policy_goal_family": "product_durability",
            "policy_intent_kind": "absolute_guarantee",
            "high_risk_claim_families": [],
            "must_remain_unresolved": True,
            "allows_bounded_alternative": True,
        }
        response["minimal_decision_context"]["claim_resolutions"][1].update({
            "status": "unresolved",
            "support_basis": "none",
            "requested_claim_risk": "high",
            "restricted_request_boundary": boundary,
        })
        response["model_first_answer_composer"]["clauses"][1].update({
            "requested_claim_risk_level": "high",
            "restricted_request_boundary": boundary,
        })
    payload = _atomic_judge_payload_for_response(response)
    payload["semantic_budget_checks"][0][status_field] = status_value
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: client,
    )

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="当前商品的日常耐用边界是什么？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == [finding_code]
    finding = next(
        item
        for item in result["canonical_goal_findings"]
        if item["primary_finding_code"]
    )
    assert finding["primary_finding_code"] == finding_code
    assert result["semantic_budget_derivations"][0][
        "canonical_finding_codes"
    ] == [finding_code]
    budget_check = result["semantic_budget_checks"][0]
    budget_ref = (
        budget_check["goal_ref"],
        budget_check["clause_ref"],
    )
    raw_review = next(
        item
        for item in result["raw_goal_reviews"]
        if (item["goal_ref"], item["clause_ref"]) == budget_ref
    )
    normalized_review = next(
        item
        for item in result["goal_reviews"]
        if (item["goal_ref"], item["clause_ref"]) == budget_ref
    )
    assert raw_review["textual_status"] == "accepted"
    assert normalized_review["textual_status"] == "rejected"


def test_atomic_semantic_audit_preserves_independent_budget_findings(
    monkeypatch,
):
    payload = _atomic_judge_payload(inference=True)
    payload["semantic_budget_checks"][0].update({
        "advice_status": "unauthorized",
        "variability_factor_status": "outside_budget",
    })
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: client,
    )

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(inference=True),
        customer_message="当前商品的日常耐用边界是什么？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == [
        "advice_scope_exceeded",
        "variability_factor_scope_exceeded",
    ]
    finding = next(
        item
        for item in result["canonical_goal_findings"]
        if item["raw_finding_codes"]
    )
    assert finding["goal_ref"]
    assert finding["clause_ref"]
    assert finding["raw_finding_codes"] == [
        "advice_scope_exceeded",
        "variability_factor_scope_exceeded",
    ]


@pytest.mark.parametrize(
    ("finding_codes", "expected_passed"),
    [
        ([], True),
        (
            [
                "advice_scope_exceeded",
                "variability_factor_scope_exceeded",
            ],
            False,
        ),
    ],
)
def test_atomic_semantic_budget_contract_is_reusable_across_domain_packs(
    monkeypatch,
    finding_codes,
    expected_passed,
):
    response = _model_first_atomic_response(inference=True)
    policy_ref = "domain-policy:travel_goods@v2:ordinary-use-boundary"
    pack_ref = "domain-policy:travel_goods@v2"
    clause = response["model_first_answer_composer"]["clauses"][1]
    clause["inference_policy_refs"] = [policy_ref]
    option = response["minimal_decision_context"][
        "claim_resolutions"
    ][1]["eligible_policy_options"][0]
    option.update({
        "policy_ref": policy_ref,
        "trusted_domain_pack_ref": pack_ref,
        "pack_content_sha256": "c" * 64,
    })
    contract = _atomic_semantic_contract(response)
    payload = {
        "schema_version": "unified-textual-audit-v3",
        "goal_reviews": [
            {
                "goal_ref": item["goal_ref"],
                "clause_ref": item["clause_ref"],
                "clause_kind": item["clause_kind"],
                "textual_status": "accepted",
                "finding_codes": [],
            }
            for item in contract
        ],
        "semantic_budget_checks": [
            {
                "goal_ref": item["goal_ref"],
                "clause_ref": item["clause_ref"],
                "advice_status": (
                    "unauthorized"
                    if "advice_scope_exceeded" in finding_codes
                    else "absent"
                ),
                "variability_factor_status": (
                    "outside_budget"
                    if "variability_factor_scope_exceeded"
                    in finding_codes
                    else "within_budget"
                ),
                "restricted_boundary_status": "not_applicable",
                "qualifier_status": "satisfied",
                "conclusion_status": "within_budget",
            }
            for item in contract
            if item["semantic_budget_applicable"]
        ],
        "global_finding_codes": [],
    }
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: client,
    )

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="请说明当前商品的一般使用边界。",
    )

    assert client.call_count == 1
    assert result["passed"] is expected_passed
    assert result["issues"] == sorted(finding_codes)


@pytest.mark.parametrize(
    ("mutate", "expected_issue"),
    [
        (
            lambda payload: payload["goal_reviews"][0].update({
                "textual_status": "rejected",
                "finding_codes": ["unsupported_claim"],
            }),
            "unsupported_claim",
        ),
        (
            lambda payload: payload["goal_reviews"][1].update({
                "textual_status": "rejected",
                "finding_codes": ["unresolved_claim_asserted"],
            }),
            "unresolved_claim_asserted",
        ),
        (
            lambda payload: payload["goal_reviews"][1].update({
                "textual_status": "rejected",
                "finding_codes": ["unsupported_product_claim"],
            }),
            "unsupported_product_claim",
        ),
        (
            lambda payload: payload["goal_reviews"][1].update({
                "textual_status": "rejected",
                "finding_codes": ["query_reply_mismatch"],
            }),
            "query_reply_mismatch",
        ),
    ],
)
def test_atomic_semantic_audit_derives_failure_from_atomic_fields(
    monkeypatch,
    mutate,
    expected_issue,
):
    payload = _atomic_judge_payload()
    mutate(payload)
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert expected_issue in result["issues"]


@pytest.mark.parametrize(
    "finding_code",
    [
        "historical_agent_fact_used",
        "known_context_re_requested",
        "unsupported_service_action_completion",
        "unsupported_media_claim",
        "omitted_customer_goal",
        "repeated_generic_reply",
        "internal_language_exposure",
    ],
)
def test_atomic_semantic_audit_derives_global_findings_locally(
    monkeypatch,
    finding_code,
):
    payload = _atomic_judge_payload()
    payload["global_finding_codes"] = [finding_code]
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == [finding_code]
    assert result["goal_reviews"] == payload["goal_reviews"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["goal_reviews"].pop(),
        lambda payload: payload["goal_reviews"].append(
            dict(payload["goal_reviews"][0])
        ),
        lambda payload: payload["goal_reviews"][0].update({
            "goal_ref": "unknown-goal",
        }),
        lambda payload: payload["goal_reviews"][0].update({
            "clause_ref": "unknown-clause",
        }),
        lambda payload: payload["goal_reviews"][0].update({
            "finding_codes": ["unknown_issue"],
        }),
        lambda payload: payload.update({
            "passed": True,
            "reason": "Pass.",
        }),
    ],
)
def test_atomic_semantic_audit_rejects_invalid_references_and_schema(
    monkeypatch,
    mutate,
):
    payload = _atomic_judge_payload()
    mutate(payload)
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]


def test_atomic_semantic_audit_is_stable_when_output_order_changes(monkeypatch):
    forward = _atomic_judge_payload()
    reverse = _atomic_judge_payload()
    reverse["goal_reviews"].reverse()
    clients = iter([
        _CountingClient(content=json.dumps(forward)),
        _CountingClient(content=json.dumps(reverse)),
    ])
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: next(clients),
    )
    response = _model_first_atomic_response()

    first = audit_customer_reply_semantic_fit(
        response,
        customer_message="这款是什么材质，耐摔吗？",
    )
    second = audit_customer_reply_semantic_fit(
        response,
        customer_message="这款是什么材质，耐摔吗？",
    )

    first_semantic = {
        key: value
        for key, value in first.items()
        if key != "provider_diagnostics"
    }
    second_semantic = {
        key: value
        for key, value in second.items()
        if key != "provider_diagnostics"
    }
    assert first_semantic == second_semantic
    assert (
        first["provider_diagnostics"]["response_sha256"]
        != second["provider_diagnostics"]["response_sha256"]
    )


def test_legacy_semantic_fit_remains_fail_soft_when_judge_unavailable(monkeypatch):
    client = _CountingClient(error=TimeoutError("late"))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        {
            "suggested_reply": "这款是ABS材质。",
            "requires_human_review": True,
        },
        customer_message="这款是什么材质？",
    )

    assert client.call_count == 1
    assert result["passed"] is True
    assert result["mode"] == "deterministic"


def test_model_first_semantic_failure_keeps_delivery_fail_closed():
    response = {
        "suggested_reply": "这款是ABS材质，目前无法确认耐摔程度。",
        "sendable_reply": "stale",
        "can_send": True,
        "requires_human_review": False,
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
        },
    }
    result = {
        "checked": True,
        "passed": False,
        "issues": ["semantic_judge_unavailable"],
        "reason": "Semantic judge is unavailable.",
        "mode": "llm_semantic_fit",
    }

    updated = apply_semantic_fit_result(response, result)

    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    assert updated["requires_human_review"] is True


def test_final_semantic_fit_blocks_missing_evidence_without_human_review(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲～这款可以拆卸，日常移动很方便。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "detachable"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "detachable",
                    "missing_fields": ["detachable"],
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个可以拆卸吗？",
    )

    assert result["passed"] is False
    assert "missing_evidence_without_human_review" in result["issues"]


def test_final_semantic_fit_blocks_gross_weight_answered_with_capacity(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5355\u5c42\u627f\u91cd\u7ea620kg\uff0c\u653e\u4e66\u548c\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "gross_weight"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u8fd9\u4e2a\u591a\u91cd\uff1f",
    )

    assert result["passed"] is False
    assert "gross_weight_answered_with_load_capacity" in result["issues"]


def test_final_semantic_fit_blocks_gross_weight_answered_with_dimensions(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5bbd80cm\u3001\u6df140cm\u3001\u9ad890cm\uff0c\u60a8\u53ef\u4ee5\u5148\u91cf\u4e00\u4e0b\u9884\u7559\u4f4d\u7f6e\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "gross_weight"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u5546\u54c1\u6bdb\u91cd\u591a\u5c11\uff1f",
    )

    assert result["passed"] is False
    assert "gross_weight_answered_with_dimensions_or_capacity" in result["issues"]


def test_final_semantic_fit_blocks_accessory_availability_answered_with_installation(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u4e2a\u914d\u4ef6\u6309\u8bf4\u660e\u4e66\u7684\u5b89\u88c5\u6b65\u9aa4\u5148\u5361\u4e0a\u4fa7\u677f\u5c31\u53ef\u4ee5\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "accessory_availability"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417\uff1f",
    )

    assert result["passed"] is False
    assert "accessory_availability_answered_with_installation" in result["issues"]


def test_final_semantic_fit_blocks_installation_answered_with_product_facts(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5bbd80cm\uff0c\u6750\u8d28\u662fPP\uff0c\u5355\u5c42\u627f\u91cd\u7ea610kg\uff0c\u9002\u5408\u65e5\u5e38\u6536\u7eb3\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "installation"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417\uff1f",
    )

    assert result["passed"] is False
    assert "installation_answered_with_unrelated_product_fact" in result["issues"]


def test_final_semantic_fit_does_not_accept_recommended_asset_without_reply_block(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u4e0b\u9762\u56fe\u7247/\u89c6\u9891\u53ef\u53c2\u8003\uff0c\u6211\u518d\u53d1\u60a8\u5bf9\u5e94\u7684\u5b89\u88c5\u56fe\u6216\u89c6\u9891\u3002",
        "requires_human_review": False,
        "recommended_assets": [{
            "asset_type": "pack_guide_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }],
        "reply_blocks": [],
        "evidence_debug": {
            "query_fact_type": "installation",
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "installation",
                    "missing_fields": ["installation"],
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528",
    )

    assert result["passed"] is False
    assert "unsupported_media_claim" in result["issues"]


def test_final_semantic_fit_rejects_combined_media_claim_when_only_image_is_attached(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，下面图片/视频可参考。",
        "requires_human_review": True,
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "pack_guide_image",
        }],
        "evidence_debug": {
            "query_fact_type": "installation",
            "answer_mode": "no_evidence_controlled_reply",
            "no_evidence_reply_policy": {"reply_strategy": "verify_installation_asset_before_send"},
        },
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {"reply_strategy": "verify_installation_asset_before_send"},
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="有安装资料吗",
    )

    assert result["passed"] is False


def test_final_semantic_fit_allows_installation_handoff_about_materials(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u6211\u5148\u6309\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1\u7684\u5b89\u88c5\u8d44\u6599\u6838\u5bf9\u3002"
            "\u5982\u679c\u6ca1\u6709\u660e\u786e\u5b89\u88c5\u89c6\u9891\uff0c\u4e0d\u4f1a\u76f4\u63a5\u627f\u8bfa\u89c6\u9891\uff1b"
            "\u60a8\u53ef\u4ee5\u628a\u5361\u4f4f\u7684\u4f4d\u7f6e\u62cd\u7167\u53d1\u6765\uff0c\u6211\u8fd9\u8fb9\u8f6c\u4eba\u5de5\u5e2e\u60a8\u786e\u8ba4\u3002"
        ),
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "installation"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417\uff1f",
    )

    assert result["passed"] is True


def test_final_semantic_fit_accepts_controlled_no_evidence_installation_handoff(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u5b89\u88c5\u8d44\u6599\u6211\u5e2e\u60a8\u6309\u8fd9\u6b3e\u6838\u5bf9\u4e00\u4e0b\u3002"
            "\u60a8\u5982\u679c\u5361\u5728\u54ea\u4e00\u6b65\uff0c\u4e5f\u53ef\u4ee5\u628a\u5f53\u524d\u4f4d\u7f6e\u62cd\u7ed9\u6211\uff0c\u6211\u4e00\u8d77\u770b\uff1b"
            "\u6211\u786e\u8ba4\u540e\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        ),
        "requires_human_review": True,
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {
                "reply_strategy": "verify_installation_asset_before_send",
                "requires_human_review": True,
            },
        },
        "evidence_debug": {
            "answer_mode": "no_evidence_controlled_reply",
            "query_fact_type": "installation",
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528\uff1f",
    )

    assert result["passed"] is True
    assert result["reason"] == "Controlled no-evidence handoff reply accepted deterministically."


def test_material_semantic_fallback_does_not_present_keyword_hits_as_product_facts():
    from app.services.final_semantic_quality_service import apply_semantic_fit_result

    response = {
        "suggested_reply": "亲，这款防潮还可以。",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "material",
            "filtered_evidence_summary": [
                {
                    "evidence_fact_type": "material",
                    "chunk_preview": "这款产品主要采用冷轧钢管/环保PP/无纺布等材质，金属部分经过防锈喷涂处理，具有一定的防潮能力。",
                }
            ],
        },
    }

    updated = apply_semantic_fit_result(
        response,
        {
            "checked": True,
            "passed": False,
            "issues": ["material_safety_incomplete"],
            "reason": "material safety was not fully answered",
        },
    )

    reply = updated["suggested_reply"]
    assert updated["requires_human_review"] is True
    assert "材质、安全和防潮说明" in reply
    assert "里面有材质和防潮相关说明" not in reply
    assert "转人工" not in reply
    assert "口径" not in reply
    assert "复核" not in reply
    assert "英禾防夹滑门收纳架" not in reply


def test_final_semantic_fit_blocks_structure_function_answered_with_scene(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，这款可以放卧室、客厅，建议旁边留出走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="侧板可以翻下来吗？",
    )

    assert result["passed"] is False
    assert "structure_function_answered_with_scene_or_space" in result["issues"]


def test_final_semantic_fit_blocks_structure_compatibility_answered_with_space(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，这款能不能放下主要看您家预留位置的宽度、进深和高度，旁边也要留走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="三面围栏，想补第四面，这款能用吗",
    )

    assert result["passed"] is False
    assert "structure_function_answered_with_scene_or_space" in result["issues"]


def test_final_semantic_fit_allows_damaged_aftersales_handoff(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，收到。麻烦您拍一下断裂/破损位置、配件整体和外包装，我这边核实后给您处理补发、换件或售后方案。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个断了",
    )

    assert result["passed"] is True


def test_apply_semantic_fit_result_replaces_bad_reply():
    response = {
        "suggested_reply": "bad answer",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": False,
    }
    result = {
        "checked": True,
        "passed": False,
        "issues": ["semantic_mismatch"],
        "reason": "bad",
        "mode": "llm_semantic_fit",
    }

    updated = apply_semantic_fit_result(response, result)

    assert updated["requires_human_review"] is True
    assert updated["generation_mode"] == "final_semantic_fit_fallback"
    assert "bad answer" != updated["suggested_reply"]
    assert updated["final_semantic_fit_audit"]["fallback_used"] is True


def test_final_semantic_fit_allows_direct_evidence_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲～这款尺寸可以参考下面的尺寸图，建议对照家里预留位置的宽度、进深和高度。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "space_fit"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "space_fit",
                    "matched_facts": [
                        {
                            "fact_type": "space_fit",
                            "preview": "尺寸图可参考预留宽度、进深和高度。",
                            "direct_answer_allowed": True,
                        }
                    ],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is True


def test_semantic_payload_contains_only_admitted_direct_facts():
    from app.services.final_semantic_quality_service import _semantic_payload

    response = {
        "suggested_reply": "主体材质为PP。",
        "selected_evidence": [{
            "evidence_uid": "direct",
            "source_type": "product_facts",
            "evidence_role": "product_fact_direct",
            "fact_type": "material",
            "attribute_key": "material",
            "content": "主体材质为PP。",
            "sku_code": "SKU-A",
            "fact_review_status": "verified",
                "gate_status": "allowed",
                "direct_answer_allowed": True,
                "material_provenance": "structured_product_record",
            }],
        "context_used": {
            "product_context_pack": {
                "matched_facts": [{
                    "evidence_uid": "reference",
                    "source_type": "faq",
                    "evidence_role": "faq_direct",
                    "fact_type": "material",
                    "preview": "待核实材质",
                    "reference_only": True,
                    "direct_answer_allowed": False,
                }],
                "generic_rules": [{
                    "evidence_uid": "generic",
                    "source_type": "generic_rule",
                    "evidence_role": "service_action",
                    "content": "转人工核对。",
                }],
            }
        },
        "answer_memory_guidance": {"answer_text": "历史客服说安全。"},
        "grounded_reasoning_draft": {"used_facts": [{"evidence_uid": "shadow"}]},
        "evidence_debug": {"query_fact_type": "material"},
    }

    payload = _semantic_payload(response, "什么材质？", {"sku_code": "SKU-A"})

    assert [item["evidence_uid"] for item in payload["admitted_direct_facts"]] == ["direct"]
    serialized = str(payload)
    assert "reference" not in serialized
    assert "generic" not in serialized
    assert "历史客服说安全" not in serialized
    assert "shadow" not in serialized


def test_semantic_payload_preserves_model_first_review_and_reasoning_contract():
    from app.services.final_semantic_quality_service import _semantic_payload

    response = _model_first_atomic_response(inference=True)
    response["final_answer_audit"] = {
        "passed": True,
        "issues": [],
        "model_call_count": 0,
    }

    payload = _semantic_payload(
        response,
        "这款是什么材质，耐摔吗？",
        {"sku_code": "SKU-A"},
    )

    assert payload["schema_version"] == "unified-textual-audit-input-v1"
    assert payload["deterministic_final_contract"] == {
        "passed": True,
        "issues": [],
        "model_call_count": 0,
    }
    assert len(payload["canonical_truth"]["candidate_clauses"]) == 2
    assert payload["canonical_truth"]["evidence"][0]["evidence_ref"] == "E1"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "material-direct" not in serialized
    assert "model_first_candidate_contract" not in payload


def _configure_strict_unified_audit(monkeypatch, *, qualified=True):
    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_STRICT_ENABLED",
        True,
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_PROVIDER",
        "strict-audit-test",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_API_BASE",
        "https://audit.example.invalid/v1",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_API_KEY",
        "audit-secret",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_MODEL",
        "audit-model",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_CAPABILITY",
        "strict_json_schema",
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_TIMEOUT_SECONDS",
        9,
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_QUALIFIED",
        qualified,
    )
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_DISABLE_THINKING",
        False,
    )


class _StrictAuditProvider:
    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = []
        self.last_latency_ms = 12.7

    def metadata(self):
        return {
            "provider_name": "strict-audit-test",
            "host_fingerprint": "123456789abc",
            "model_name": "audit-model",
            "capability": "strict_json_schema",
            "configured": True,
            "qualified": True,
        }

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.parsed


def test_atomic_semantic_json_schema_has_exact_contract_cardinality():
    contract = _atomic_semantic_contract(
        _model_first_atomic_response(inference=True)
    )

    schema = _atomic_semantic_json_schema(contract)

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version",
        "goal_reviews",
        "semantic_budget_checks",
        "global_finding_codes",
    }
    assert schema["properties"]["goal_reviews"]["minItems"] == 2
    assert schema["properties"]["goal_reviews"]["maxItems"] == 2
    assert schema["properties"]["semantic_budget_checks"][
        "minItems"
    ] == 1
    assert schema["properties"]["semantic_budget_checks"][
        "maxItems"
    ] == 1
    assert schema["properties"]["goal_reviews"]["items"][
        "additionalProperties"
    ] is False
    assert schema["properties"]["semantic_budget_checks"]["items"][
        "additionalProperties"
    ] is False
    budget_properties = schema["properties"]["semantic_budget_checks"][
        "items"
    ]["properties"]
    assert budget_properties["qualifier_status"]["enum"] == [
        "indeterminate",
        "satisfied",
        "violated",
    ]


def test_strict_unified_audit_uses_independent_provider_once(monkeypatch):
    _configure_strict_unified_audit(monkeypatch)
    provider = _StrictAuditProvider(
        _atomic_judge_payload(inference=True)
    )
    monkeypatch.setattr(
        semantic_service,
        "StrictDecisionProviderService",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("formal LLM role must not be used")
        ),
    )
    raw_customer_value = "buyer-private@example.com"

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(inference=True),
        customer_message=(
            "杩欐鏄粈涔堟潗璐紝鏃ュ父磕碰鎬庝箞鏍凤紵 "
            + raw_customer_value
        ),
    )

    assert result["passed"] is True
    assert len(provider.calls) == 1
    request = provider.calls[0]
    assert request["name"] == "unified_textual_audit_v3"
    assert request["allow_unqualified"] is False
    assert request["schema"]["additionalProperties"] is False
    assert raw_customer_value not in json.dumps(
        request["payload"],
        ensure_ascii=False,
    )
    diagnostics = result["provider_diagnostics"]
    assert diagnostics["provider_role"] == "unified_textual_audit"
    assert diagnostics["model_call_count"] == 1
    assert diagnostics["retry_count"] == 0
    assert diagnostics["repair_count"] == 0
    assert "audit-secret" not in str(diagnostics)
    assert "audit.example.invalid" not in str(diagnostics)


def test_strict_unified_audit_unqualified_fails_without_formal_fallback(
    monkeypatch,
):
    _configure_strict_unified_audit(monkeypatch, qualified=False)
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("formal LLM role must not be used")
        ),
    )

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="杩欐鏄粈涔堟潗璐紵",
    )

    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_unavailable"]
    assert result["provider_diagnostics"]["model_call_count"] == 0
    assert result["provider_diagnostics"][
        "provider_error_type"
    ] == "provider_not_qualified"
    assert result["validation_diagnostics"][
        "category"
    ] == "strict_provider_error"


def test_strict_unified_audit_keeps_local_validator_authoritative(
    monkeypatch,
):
    _configure_strict_unified_audit(monkeypatch)
    parsed = _atomic_judge_payload()
    parsed["goal_reviews"][0]["goal_ref"] = "goal-durability"
    provider = _StrictAuditProvider(parsed)
    monkeypatch.setattr(
        semantic_service,
        "StrictDecisionProviderService",
        lambda config: provider,
    )

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="杩欐鏄粈涔堟潗璐紵",
    )

    assert len(provider.calls) == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]
    assert result["validation_diagnostics"]["category"] in {
        "duplicate_segment_reference",
        "unknown_segment_reference",
    }


def test_default_model_first_audit_keeps_legacy_transport(monkeypatch):
    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        config,
        "COPILOT_UNIFIED_AUDIT_STRICT_ENABLED",
        False,
    )
    client = _CountingClient(content=json.dumps(_atomic_judge_payload()))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)
    monkeypatch.setattr(
        semantic_service,
        "StrictDecisionProviderService",
        lambda config: (_ for _ in ()).throw(
            AssertionError("strict Audit role must remain disabled")
        ),
    )

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="杩欐鏄粈涔堟潗璐紵",
    )

    assert result["passed"] is True
    assert client.call_count == 1
    assert client.last_kwargs["response_format"] == {
        "type": "json_object"
    }
