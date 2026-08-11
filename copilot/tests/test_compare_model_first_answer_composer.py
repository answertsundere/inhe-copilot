from argparse import Namespace
import json

import pytest

from scripts import compare_model_first_answer_composer as comparison


def _scenario():
    return {
        "scenario_uid": "scenario-hmac",
        "business_domain": "商品事实",
        "risk_level": "medium",
        "must_handoff": False,
        "api_request_template": {
            "message": "这款是什么材质，耐摔吗？",
            "conversation_history": [{"role": "customer", "content": "我问的是这个款"}],
            "sku_code": "SKU-A",
        },
        "expected_claims": [
            {
                "expected_status": "supported",
                "required_answer_points": ["ABS"],
            },
            {
                "expected_status": "unresolved",
                "required_answer_points": ["不能保证耐摔"],
            },
        ],
        "forbidden_claims": ["保证摔不坏"],
        "gold_reply": "must not enter Agent payload",
        "required_actions": ["hidden evaluator action"],
    }


def _goal_ref_partial_response() -> dict:
    return {
        "suggested_reply": "这款是ABS材质，但不能保证耐摔。",
        "selected_evidence": [{"evidence_uid": "material"}],
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"passed": True, "issues": []},
        "reply_blocks": [{"type": "text"}],
        "turn_understanding": {
            "goal_understanding_status": "valid",
            "customer_goals": [
                {
                    "goal_ref": "goal-material",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "material",
                },
                {
                    "goal_ref": "goal-durability",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "semantic_key": "",
                },
            ],
        },
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
            "can_change_can_send": False,
            "can_send": False,
            "requires_human_review": True,
            "used_evidence_uids": ["material"],
            "unresolved_claim_types": [],
            "clauses": [
                {
                    "goal_ref": "claim-material",
                    "clause_kind": "supported_fact",
                    "evidence_uids": ["material"],
                },
                {
                    "goal_ref": "claim-durability",
                    "clause_kind": "unresolved",
                    "evidence_uids": [],
                },
            ],
        },
        "minimal_decision_context": {
            "admitted_evidence": [{"evidence_uid": "material"}],
            "claim_resolutions": [
                {
                    "goal_ref": "goal-material",
                    "claim_uid": "claim-material",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "material",
                    "status": "supported",
                    "evidence_uids": ["material"],
                },
                {
                    "goal_ref": "goal-durability",
                    "claim_uid": "claim-durability",
                    "goal_kind": "customer_goal",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "semantic_key": "",
                    "status": "unresolved",
                    "evidence_uids": [],
                },
            ],
        },
    }


def test_agent_payload_excludes_evaluation_fields():
    payload = comparison._agent_payload(_scenario())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "gold_reply" not in serialized
    assert "expected_claims" not in serialized
    assert "required_actions" not in serialized
    assert payload["message"] == "这款是什么材质，耐摔吗？"


def test_agent_payload_rejects_evaluation_field_nested_in_template():
    scenario = _scenario()
    scenario["api_request_template"]["copilot_context"] = {
        "rubric": {"hidden": True},
    }

    with pytest.raises(ValueError, match="evaluation_field_leakage:rubric"):
        comparison._agent_payload(scenario)


def test_response_scoring_separates_supported_and_unresolved_claims():
    response = _goal_ref_partial_response()
    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["supported_complete"] is True
    assert score["unresolved_complete"] is True
    assert score["structured_unresolved_complete"] is True
    assert score["partial_answer_success"] is True
    assert score["runtime_supported_claim_numerator"] == 1
    assert score["runtime_supported_claim_denominator"] == 1
    assert score["runtime_unresolved_handling_numerator"] == 1
    assert score["runtime_unresolved_handling_denominator"] == 1
    assert score["renderable_customer_goal_count"] == 2
    assert score["supporting_dependency_count"] == 0
    assert score["customer_goal_clause_coverage_numerator"] == 2
    assert score["customer_goal_clause_coverage_denominator"] == 2
    assert score["customer_goal_clause_coverage_rate"] == 1.0
    assert score["dependency_evidence_link_coverage_denominator"] == 0
    assert score["unknown_goal_kind_count"] == 0
    assert score["unsupported_high_risk_claim"] is False
    assert score["can_send"] is False


def test_response_scoring_keeps_unqualified_audit_advisory_for_supervisor_assist():
    response = _goal_ref_partial_response()
    response["final_semantic_fit_audit"] = {
        "passed": False,
        "issues": ["semantic_judge_schema_invalid"],
    }

    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )
    summary = comparison._summarize([score])

    assert score["partial_answer_success"] is True
    assert score["supervisor_assist_candidate_eligible"] is True
    assert score["unified_audit_advisory_failed"] is True
    assert score["autonomous_send_audit_gate_passed"] is False
    assert summary["supervisor_assist_candidate_eligible_count"] == 1
    assert summary["unified_audit_advisory_failure_count"] == 1
    assert summary["autonomous_send_audit_gate_pass_count"] == 0


def _bounded_policy_response():
    policy_ref = (
        "domain-policy:fixture_domain@1.0.0:"
        "intent:product_durability_practical_guidance"
    )
    return {
        "suggested_reply": "这款是ABS材质。日常轻微磕碰需注意，不能保证摔不坏。",
        "selected_evidence": [{"evidence_uid": "material"}],
        "can_send": False,
        "requires_human_review": True,
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"passed": True, "issues": []},
        "reply_blocks": [{"type": "text"}],
        "model_first_answer_composer": {
            "status": "accepted",
            "used_evidence_uids": ["material"],
            "unresolved_claim_types": [],
            "clauses": [{
                "goal_ref": "claim-durability",
                "clause_kind": "allowed_inference",
                "evidence_uids": ["material"],
                "premise_evidence_uids": ["material"],
                "inference_policy_refs": [policy_ref],
                "scope_qualifier": "ordinary_minor_accidental_impact",
                "inference_risk_level": "medium",
                "maximum_risk_level": "medium",
                "requested_claim_risk_level": "medium",
                "inference_review_only": True,
                "required_qualifiers": ["no_absolute_guarantee"],
                "prohibited_extensions": [
                    "certification_report",
                    "child_safety",
                    "warranty",
                ],
                "restricted_request_boundary": {},
            }],
        },
        "minimal_decision_context": {
            "admitted_evidence": [{
                "evidence_uid": "material",
                "fact_type": "material_composition",
            }],
            "bounded_inference_policies": [{
                "policy_ref": policy_ref,
                "policy_intent_ref": (
                    "product_durability_practical_guidance"
                ),
                "goal_family": "product_durability",
                "intent_kind": "practical_guidance",
                "premise_fact_families": ["material_composition"],
                "allowed_scope": "ordinary_minor_accidental_impact",
                "allowed_conclusion_family": (
                    "ordinary_minor_impact_tolerance"
                ),
                "allowed_variability_factor_families": [
                    "contact_surface",
                    "impact_angle",
                    "impact_height",
                ],
                "advice_mode": "none",
                "maximum_risk_level": "medium",
                "required_qualifiers": ["no_absolute_guarantee"],
                "prohibited_claim_families": [
                    "certification_report",
                    "child_safety",
                    "warranty",
                ],
                "review_only": True,
            }],
            "claim_resolutions": [{
                "claim_uid": "claim-durability",
                "goal_ref": "claim-durability",
                "claim_type": "unmapped_customer_goal",
                "status": "unresolved",
                "support_basis": "none",
                "policy_intent_ref": (
                    "product_durability_practical_guidance"
                ),
                "policy_goal_family": "product_durability",
                "policy_intent_kind": "practical_guidance",
                "bounded_inference_policy": "review_required",
                "evidence_uids": [],
                "premise_evidence_uids": [],
                "inference_policy_refs": [],
                "eligible_policy_options": [{
                    "policy_ref": policy_ref,
                    "trusted_domain_pack_ref": (
                        "domain-policy:fixture_domain@1.0.0"
                    ),
                    "applicable_goal_ref": "claim-durability",
                    "policy_intent_ref": (
                        "product_durability_practical_guidance"
                    ),
                    "goal_family": "product_durability",
                    "intent_kind": "practical_guidance",
                    "premise_evidence_refs": ["material"],
                    "premise_families": ["material_composition"],
                    "allowed_scope": (
                        "ordinary_minor_accidental_impact"
                    ),
                    "allowed_conclusion_family": (
                        "ordinary_minor_impact_tolerance"
                    ),
                    "allowed_variability_factor_families": [
                        "contact_surface",
                        "impact_angle",
                        "impact_height",
                    ],
                    "advice_mode": "none",
                    "forbidden_claim_families": [
                        "certification_report",
                        "child_safety",
                        "warranty",
                    ],
                "maximum_risk": "medium",
                "requested_risk": "medium",
                "requested_claim_risk": "medium",
                "answer_strategy_risk": "medium",
                "required_qualifiers": [
                        "no_absolute_guarantee"
                    ],
                    "review_only": True,
                    "option_provenance": {
                        "policy_owner": "domain_policy_pack",
                        "filter_owner": "claim_resolution",
                        "premise_owner": "admitted_answer_context",
                        "intent_narrowed": True,
                    },
                }],
            }],
        },
    }


def _restricted_bounded_policy_response():
    response = _bounded_policy_response()
    practical_policy = response["minimal_decision_context"][
        "bounded_inference_policies"
    ][0]
    absolute_intent_ref = "product_durability_absolute_guarantee"
    absolute_policy = {
        **practical_policy,
        "policy_ref": (
            "domain-policy:fixture_domain@1.0.0:"
            f"intent:{absolute_intent_ref}"
        ),
        "policy_intent_ref": absolute_intent_ref,
        "intent_kind": "absolute_guarantee",
    }
    response["minimal_decision_context"][
        "bounded_inference_policies"
    ].append(absolute_policy)
    resolution = response["minimal_decision_context"][
        "claim_resolutions"
    ][0]
    boundary = {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "absolute_guarantee_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": absolute_intent_ref,
        "policy_goal_family": "product_durability",
        "policy_intent_kind": "absolute_guarantee",
        "high_risk_claim_families": [],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    resolution.update({
        "policy_intent_ref": absolute_intent_ref,
        "policy_intent_kind": "absolute_guarantee",
        "requested_claim_risk": "high",
        "restricted_request_boundary": boundary,
    })
    option = resolution["eligible_policy_options"][0]
    option.update({
        "requested_risk": "high",
        "requested_claim_risk": "high",
        "answer_strategy_risk": "medium",
        "restricted_request_boundary": boundary,
    })
    option["option_provenance"].update({
        "intent_narrowed": False,
        "alternative_for_restricted_request": True,
    })
    clause = response["model_first_answer_composer"]["clauses"][0]
    clause.update({
        "requested_claim_risk_level": "high",
        "restricted_request_boundary": boundary,
    })
    return response


def test_response_scoring_reports_trusted_policy_and_bounded_attribution():
    score = comparison._score_response(
        _scenario(),
        _bounded_policy_response(),
        status_code=200,
        error_type="",
        latency_ms=25,
    )
    summary = comparison._summarize([score])

    assert score["policy_intent_refs"] == [
        "product_durability_practical_guidance"
    ]
    assert score["policy_intent_kinds"] == ["practical_guidance"]
    assert score["policy_intent_precision_numerator"] == 1
    assert score["policy_intent_precision_denominator"] == 1
    assert score["policy_intent_recall_numerator"] == 1
    assert score["policy_intent_recall_denominator"] == 1
    assert score["bounded_inference_attribution_numerator"] == 1
    assert score["bounded_inference_attribution_denominator"] == 1
    assert score["bounded_inference_premise_numerator"] == 1
    assert score["bounded_inference_scope_numerator"] == 1
    assert score["eligible_policy_options_numerator"] == 1
    assert score["eligible_policy_options_denominator"] == 1
    assert score["policy_selection_numerator"] == 1
    assert score["policy_selection_denominator"] == 1
    assert score["selected_policy_validity_numerator"] == 1
    assert score["selected_policy_premise_numerator"] == 1
    assert score["selected_policy_scope_numerator"] == 1
    assert score["inference_opportunity_missed_count"] == 0
    assert score["absolute_guarantee_supported_count"] == 0
    assert summary["eligible_policy_options_coverage"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert summary["policy_selection_coverage"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert summary["selected_policy_validity"]["rate"] == 1.0
    assert summary["selected_policy_premise_coverage"]["rate"] == 1.0
    assert summary["selected_policy_scope_validity"]["rate"] == 1.0


def test_response_scoring_counts_bound_policy_guidance_as_unresolved_handling():
    response = _bounded_policy_response()
    response["turn_understanding"] = {
        "goal_understanding_status": "valid",
        "customer_goals": [{
            "goal_ref": "claim-durability",
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "semantic_key": "ordinary_durability_guidance",
        }],
    }
    response["minimal_decision_context"]["claim_resolutions"][0].update({
        "goal_kind": "customer_goal",
        "claim_type_status": "unmapped",
        "semantic_key": "ordinary_durability_guidance",
    })
    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["wrong_clause_kind_count"] == 0
    assert score["runtime_unresolved_handling_numerator"] == 1
    assert score["runtime_unresolved_handling_denominator"] == 1


@pytest.mark.parametrize(
    "mutation",
    (
        lambda response: response["model_first_answer_composer"]["clauses"][0].update({
            "premise_evidence_uids": [],
        }),
        lambda response: response["model_first_answer_composer"]["clauses"][0].update({
            "scope_qualifier": "different_scope",
        }),
        lambda response: response["model_first_answer_composer"]["clauses"][0].update({
            "inference_risk_level": "high",
        }),
    ),
)
def test_response_scoring_rejects_malformed_bound_policy_guidance(mutation):
    response = _bounded_policy_response()
    response["turn_understanding"] = {
        "goal_understanding_status": "valid",
        "customer_goals": [{
            "goal_ref": "claim-durability",
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "semantic_key": "ordinary_durability_guidance",
        }],
    }
    response["minimal_decision_context"]["claim_resolutions"][0].update({
        "goal_kind": "customer_goal",
        "claim_type_status": "unmapped",
        "semantic_key": "ordinary_durability_guidance",
    })
    mutation(response)

    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["wrong_clause_kind_count"] == 1
    assert score["runtime_unresolved_handling_numerator"] == 0


def test_response_scoring_separates_restricted_request_and_answer_risk():
    score = comparison._score_response(
        _scenario(),
        _restricted_bounded_policy_response(),
        status_code=200,
        error_type="",
        latency_ms=25,
    )
    summary = comparison._summarize([score])

    assert score["policy_intent_kinds"] == ["absolute_guarantee"]
    assert score["restricted_boundary_preservation_numerator"] == 1
    assert score["restricted_boundary_preservation_denominator"] == 1
    assert score["answer_strategy_risk_separation_numerator"] == 1
    assert score["answer_strategy_risk_separation_denominator"] == 1
    assert score["absolute_guarantee_supported_count"] == 0
    assert summary["restricted_boundary_preservation"]["rate"] == 1.0
    assert summary["answer_strategy_risk_separation"]["rate"] == 1.0
    assert comparison._correctness_gate_blockers(
        {"requires_human_review_count": 1},
        summary,
        scenario_count=1,
    ) == []


def test_response_scoring_counts_restricted_bounded_clause_as_unresolved_boundary():
    response = _restricted_bounded_policy_response()
    response["turn_understanding"] = {
        "goal_understanding_status": "valid",
        "customer_goals": [{
            "goal_ref": "claim-durability",
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "semantic_key": "absolute_durability_guarantee",
        }],
    }
    response["minimal_decision_context"]["claim_resolutions"][0].update({
        "goal_kind": "customer_goal",
        "claim_type_status": "unmapped",
        "semantic_key": "absolute_durability_guarantee",
    })
    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["wrong_clause_kind_count"] == 0
    assert score["runtime_unresolved_handling_numerator"] == 1
    assert score["runtime_unresolved_handling_denominator"] == 1
    assert score["customer_goal_clause_coverage_numerator"] == 1
    assert score["customer_goal_clause_coverage_denominator"] == 1


def test_response_scoring_does_not_credit_unbound_allowed_inference_as_unresolved():
    response = _restricted_bounded_policy_response()
    response["turn_understanding"] = {
        "goal_understanding_status": "valid",
        "customer_goals": [{
            "goal_ref": "claim-durability",
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "semantic_key": "absolute_durability_guarantee",
        }],
    }
    response["minimal_decision_context"]["claim_resolutions"][0].update({
        "goal_kind": "customer_goal",
        "claim_type_status": "unmapped",
        "semantic_key": "absolute_durability_guarantee",
    })
    response["model_first_answer_composer"]["clauses"][0][
        "restricted_request_boundary"
    ] = {}

    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["wrong_clause_kind_count"] == 1
    assert score["runtime_unresolved_handling_numerator"] == 0


def test_response_scoring_rejects_restricted_boundary_and_risk_mutations():
    mutations = (
        (
            "missing_resolution_boundary",
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0].pop("restricted_request_boundary"),
            "restricted_boundary_not_preserved",
        ),
        (
            "missing_option_boundary",
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].pop(
                "restricted_request_boundary"
            ),
            "answer_strategy_risk_separation_invalid",
        ),
        (
            "strategy_risk_exceeds_policy",
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "answer_strategy_risk": "high"
            }),
            "answer_strategy_risk_separation_invalid",
        ),
        (
            "clause_loses_boundary",
            lambda response: response[
                "model_first_answer_composer"
            ]["clauses"][0].pop("restricted_request_boundary"),
            "selected_policy_scope_invalid",
        ),
    )
    for _, mutate, blocker in mutations:
        response = _restricted_bounded_policy_response()
        mutate(response)
        summary = comparison._summarize([
            comparison._score_response(
                _scenario(),
                response,
                status_code=200,
                error_type="",
                latency_ms=25,
            )
        ])
        assert blocker in comparison._correctness_gate_blockers(
            {"requires_human_review_count": 1},
            summary,
            scenario_count=1,
        )


def test_response_scoring_rejects_missing_bounded_inference_premise():
    response = _bounded_policy_response()
    response["model_first_answer_composer"]["clauses"][0][
        "premise_evidence_uids"
    ] = []

    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )
    summary = comparison._summarize([score])

    assert score["bounded_inference_attribution_numerator"] == 0
    assert score["bounded_inference_premise_numerator"] == 0
    assert summary["bounded_inference_attribution"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0.0,
    }
    assert "bounded_inference_attribution_incomplete" in (
        comparison._correctness_gate_blockers(
            {"requires_human_review_count": 1},
            summary,
            scenario_count=1,
        )
    )


def test_response_scoring_reports_composer_input_partition_metrics():
    response = _goal_ref_partial_response()
    response["model_first_answer_composer"]["input_eligibility"] = {
        "renderable_customer_goal_count": 2,
        "supporting_dependency_count": 1,
        "dependency_evidence_link_coverage": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0,
        },
        "unknown_goal_kind_count": 0,
    }

    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )
    summary = comparison._summarize([score])

    assert score["supporting_dependency_count"] == 1
    assert summary["customer_goal_clause_coverage"] == {
        "numerator": 2,
        "denominator": 2,
        "rate": 1.0,
    }
    assert summary["dependency_evidence_link_coverage"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert summary["non_customer_goal_clause_count"] == 0
    assert summary["unknown_goal_kind_count"] == 0


def test_correctness_gate_rejects_supported_absolute_guarantee():
    response = _bounded_policy_response()
    resolution = response["minimal_decision_context"]["claim_resolutions"][0]
    resolution["eligible_policy_options"][0][
        "intent_kind"
    ] = "absolute_guarantee"
    response["minimal_decision_context"]["bounded_inference_policies"][0][
        "intent_kind"
    ] = "absolute_guarantee"

    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )
    summary = comparison._summarize([score])

    assert score["absolute_guarantee_supported_count"] == 1
    assert "absolute_guarantee_supported" in (
        comparison._correctness_gate_blockers(
            {"requires_human_review_count": 1},
            summary,
            scenario_count=1,
        )
    )


def test_partial_answer_uses_structured_unresolved_contract_not_fixed_gold_phrase():
    response = _goal_ref_partial_response()
    response["suggested_reply"] = (
        "这款是ABS材质。耐摔程度暂时没有可确认的依据。"
    )
    score = comparison._score_response(
        _scenario(),
        response,
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["unresolved_complete"] is False
    assert score["dataset_unresolved_handling_numerator"] == 0
    assert score["structured_unresolved_complete"] is True
    assert score["partial_answer_success"] is True


def test_response_scoring_blocks_forbidden_and_media_claims():
    score = comparison._score_response(
        _scenario(),
        {
            "suggested_reply": "保证摔不坏，安装视频已经发给您了。",
            "selected_evidence": [],
            "can_send": True,
            "requires_human_review": False,
            "reply_blocks": [{"type": "text"}],
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["unsupported_high_risk_claim"] is True
    assert score["unsupported_media_promise"] is True
    assert score["can_send"] is True


@pytest.mark.parametrize(
    "reply",
    [
        "这款不能保证摔不坏。",
        "目前无法保证摔不坏。",
        "我们不会保证摔不坏。",
    ],
)
def test_response_scoring_does_not_treat_safe_negation_as_forbidden_claim(reply):
    score = comparison._score_response(
        _scenario(),
        {
            "suggested_reply": reply,
            "selected_evidence": [],
            "can_send": False,
            "requires_human_review": True,
            "reply_blocks": [{"type": "text"}],
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["forbidden_claim_hits"] == []
    assert score["unsupported_high_risk_claim"] is False


def test_response_scoring_handles_coordinated_uncertain_high_risk_claims():
    scenario = _scenario()
    scenario["forbidden_claims"] = ["无毒", "食品级"]

    score = comparison._score_response(
        scenario,
        {
            "suggested_reply": "至于宝宝啃咬是否无毒或食品级，目前无法从现有信息确认。",
            "selected_evidence": [],
            "can_send": False,
            "requires_human_review": True,
            "reply_blocks": [{"type": "text"}],
        },
        status_code=200,
        error_type="",
        latency_ms=25,
    )

    assert score["forbidden_claim_hits"] == []
    assert score["unsupported_high_risk_claim"] is False


def test_runtime_contract_requires_only_paired_feature_flag_difference():
    runtime = {
        "runtime_commit": "commit",
        "source_tree_sha256": "hash",
        "formal_model": "MiniMax-M3",
        "source_tree_drift": False,
        "formal_knowledge_query_only": True,
        "readiness": {"ready": True},
        "feature_flags": {
            "formal_evidence_convergence": True,
            "model_first_answer_composer": True,
        },
    }

    assert comparison._runtime_contract(
        runtime,
        mode="ON",
        expected_commit="commit",
        expected_source_hash="hash",
        expected_model="MiniMax-M3",
    ) == []


def test_correctness_gate_rejects_partial_audit_and_latency_failures():
    off = {"requires_human_review_count": 8}
    on = {
        "partial_answer_success": {"numerator": 0, "denominator": 4},
        "runtime_supported_claim_attribution": {"numerator": 3, "denominator": 6},
        "runtime_unresolved_claim_declaration": {"numerator": 10, "denominator": 12},
        "final_audit_pass_count": 6,
        "semantic_audit_pass_count": 4,
        "final_audit_model_call_count": 1,
        "unified_audit_model_call_count": 9,
        "unified_audit_retry_count": 1,
        "unified_audit_repair_count": 1,
        "fallback_count": 1,
        "requires_human_review_count": 8,
        "latency_ms": {"p95": 40_350},
    }

    assert comparison._correctness_gate_blockers(off, on, scenario_count=8) == [
        "partial_answer_incomplete",
        "supported_claim_attribution_incomplete",
        "unresolved_claim_declaration_incomplete",
        "final_audit_incomplete",
        "semantic_audit_incomplete",
        "final_audit_model_call_detected",
        "unified_audit_call_limit_exceeded",
        "unified_audit_retry_detected",
        "unified_audit_repair_detected",
        "model_first_fallback_detected",
        "latency_p95_exceeded",
    ]


def test_correctness_gate_requires_customer_goal_resolution_lineage():
    blockers = comparison._correctness_gate_blockers(
        {"requires_human_review_count": 1},
        {
            "partial_answer_success": {"numerator": 1, "denominator": 1},
            "runtime_supported_claim_attribution": {"numerator": 1, "denominator": 1},
            "runtime_unresolved_claim_declaration": {"numerator": 1, "denominator": 1},
            "goal_recall": {
                "customer_goal_resolution_coverage": {
                    "numerator": 1,
                    "denominator": 2,
                },
            },
            "final_audit_pass_count": 1,
            "semantic_audit_pass_count": 1,
            "requires_human_review_count": 1,
            "latency_ms": {"p95": 100},
        },
        scenario_count=1,
    )

    assert blockers == ["customer_goal_resolution_incomplete"]


def test_goal_truth_is_diagnostic_only_and_separates_dependency():
    fixture = (
        comparison.PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "model_first_goal_truth"
        / "v1.json"
    )

    truth = comparison._load_goal_truth(fixture)

    safety = truth["hq-7c578c7f63c4829a2b70"]
    assert [item["expected_goal_kind"] for item in safety] == [
        "customer_goal",
        "evidence_dependency",
    ]
    assert safety[0]["expected_claim_type"] == "bite_or_toxicity"
    assert safety[1]["expected_claim_type"] == "material_composition"
    assert len(safety[0]["expected_source_span_sha256"]) == 64


def test_goal_match_uses_verified_source_span_before_model_semantic_wording():
    source_hash = "a" * 64
    truth = {
        "diagnostic_goal_ref": "diagnostic-only-ref",
        "expected_claim_type": "",
        "expected_attribute_key": "durability",
        "expected_source_span_sha256": source_hash,
        "expected_source_span_start": 10,
        "expected_source_span_end": 18,
    }

    assert comparison._goal_matches({
        "goal_ref": "runtime-ref",
        "claim_type": "",
        "attribute_key": "",
        "semantic_key": "model-selected-wording-can-vary",
        "source_span_sha256": source_hash,
        "source_span_start": 10,
        "source_span_end": 18,
    }, truth) is True
    assert comparison._goal_matches({
        "goal_ref": "runtime-ref",
        "claim_type": "",
        "attribute_key": "durability",
        "semantic_key": "durability",
        "source_span_sha256": "b" * 64,
        "source_span_start": 0,
        "source_span_end": 5,
    }, truth) is False


def test_goal_match_does_not_use_optional_semantic_metadata_as_attribute():
    truth = {
        "diagnostic_goal_ref": "",
        "expected_claim_type": "",
        "expected_attribute_key": "durability",
        "expected_source_span_sha256": "",
        "expected_source_span_start": None,
        "expected_source_span_end": None,
    }

    assert comparison._goal_matches({
        "goal_ref": "",
        "claim_type": "",
        "attribute_key": "",
        "semantic_key": "durability",
    }, truth) is False


def test_goal_match_accepts_verified_source_span_granularity_but_not_other_clause():
    truth = {
        "diagnostic_goal_ref": "diagnostic-only-ref",
        "expected_claim_type": "moisture_resistance",
        "expected_attribute_key": "",
        "expected_source_span_sha256": "a" * 64,
        "expected_source_span_start": 15,
        "expected_source_span_end": 18,
    }

    assert comparison._goal_matches({
        "source_span_sha256": "b" * 64,
        "source_span_start": 8,
        "source_span_end": 18,
    }, truth) is True
    assert comparison._goal_matches({
        "source_span_sha256": "c" * 64,
        "source_span_start": 8,
        "source_span_end": 11,
    }, truth) is False


def test_goal_funnel_finds_earliest_understanding_and_requested_claim_breakpoints():
    scenario = {
        "api_request_template": {"message": "current question"},
        "current_buyer_message": "current question",
    }
    truth = [
        {
            "scenario_uid": "scenario-hmac",
            "source_turn_uid": "turn-hmac",
            "source_provenance": "dataset.current_buyer_message",
            "diagnostic_goal_ref": "goal-material",
            "expected_goal_kind": "customer_goal",
            "expected_claim_type": "material_composition",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
        },
        {
            "scenario_uid": "scenario-hmac",
            "source_turn_uid": "turn-hmac",
            "source_provenance": "dataset.current_buyer_message",
            "diagnostic_goal_ref": "goal-moisture",
            "expected_goal_kind": "customer_goal",
            "expected_claim_type": "moisture_resistance",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
        },
    ]
    response = {
        "turn_understanding": {
            "query_fact_type": "material",
            "secondary_fact_types": ["moisture_resistance"],
            "requested_claims": [{"claim_type": "material"}],
        },
        "final_answer_audit": {"passed": True},
        "final_semantic_fit_audit": {"passed": True},
    }

    rows = comparison._goal_funnel(scenario, response, truth)

    assert rows[0]["observed_in_turn_understanding"] is True
    assert rows[0]["observed_in_requested_claims"] is True
    assert rows[1]["observed_in_turn_understanding"] is True
    assert rows[1]["earliest_breakpoint"] == "requested_claim_missing"


def test_goal_funnel_does_not_count_evidence_dependency_as_customer_goal():
    rows = [
        {
            "scenario_uid": "scenario-hmac",
            "expected_goal_kind": "customer_goal",
            "expected_claim_type": "customer-fact",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
            "diagnostic_goal_ref": "goal-customer",
            "observed_in_turn_understanding": True,
            "earliest_breakpoint": None,
        },
        {
            "scenario_uid": "scenario-hmac",
            "expected_goal_kind": "evidence_dependency",
            "expected_claim_type": "supporting-fact",
            "expected_attribute_key": "",
            "diagnostic_label_uncertain": False,
            "diagnostic_goal_ref": "goal-dependency",
            "observed_in_turn_understanding": False,
            "earliest_breakpoint": "requested_claim_missing",
        },
    ]

    summary = comparison._goal_recall_summary(
        rows,
        [{
            "scenario_uid": "scenario-hmac",
            "customer_goals": [{"claim_type": "customer-fact"}],
        }],
    )

    assert summary["customer_goal_recall"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert summary["target_denominator"] == 0


def test_goal_recall_precision_counts_unexpected_runtime_goals():
    rows = [{
        "scenario_uid": "scenario-hmac",
        "expected_goal_kind": "customer_goal",
        "diagnostic_label_uncertain": False,
        "diagnostic_goal_ref": "goal-material",
        "expected_claim_type": "material_composition",
        "expected_attribute_key": "",
        "observed_in_turn_understanding": True,
        "earliest_breakpoint": None,
    }]

    summary = comparison._goal_recall_summary(
        rows,
        [{
            "scenario_uid": "scenario-hmac",
            "customer_goals": [
                {"claim_type": "material"},
                {"claim_type": "placement_scene"},
            ],
        }],
    )

    assert summary["customer_goal_precision"] == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
    }
    assert summary["unexpected_runtime_goals"] == [{
        "scenario_uid": "scenario-hmac",
        "claim_type": "placement_scene",
        "attribute_key": "",
    }]
