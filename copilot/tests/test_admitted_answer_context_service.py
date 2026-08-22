from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_minimal_decision_context,
    is_placeholder_evidence_text,
    project_response_strategy_actions,
)


def _fact(**overrides):
    value = {
        "evidence_uid": "fact-material",
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "fact_type": "material",
        "attribute_key": "material",
        "content": "主体材质为PP。",
        "material_provenance": "structured_product_record",
        "sku_code": "SKU-A",
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
    }
    value.update(overrides)
    return value


def _understanding(*claim_types):
    return {
        "requested_claims": [
            {"claim_type": item, "question": item, "risk_level": "high" if "safety" in item else "medium"}
            for item in claim_types
        ]
    }


def test_placeholder_semantics_reject_verification_copy_without_rejecting_real_values():
    placeholders = (
        "\u672a\u660e\u786e\u5c3a\u5bf8",
        "\u672a\u5728\u73b0\u6709\u7ed3\u6784\u8d44\u6599\u4e2d\u660e\u786e\u5c3a\u5bf8",
        "\u5f53\u524d\u8d44\u6599\u4e2d\u6682\u672a\u660e\u786e\u662f\u5426\u53ef\u62c6",
        "\u9700\u8981\u4eba\u5de5\u6838\u5b9e",
        "\u4ee5\u8be6\u60c5\u9875\u4e3a\u51c6",
        "\u4ee5\u5b9e\u7269\u4e3a\u51c6",
        "\u5df2\u6536\u5f55\u5c3a\u5bf8\u56fe\uff0c\u5177\u4f53\u5c3a\u5bf8\u4ee5\u5c3a\u5bf8\u56fe\u6216\u5546\u54c1\u8be6\u60c5\u9875\u6807\u6ce8\u4e3a\u51c6",
        "\u5df2\u6536\u5f55\u5b89\u88c5\u89c6\u9891\uff0c\u5efa\u8bae\u6309\u5b89\u88c5\u89c6\u9891\u6216\u8bf4\u660e\u4e66\u6b65\u9aa4\u7ec4\u88c5",
        "\u5177\u4f53\u914d\u4ef6\u6e05\u5355\u4ee5\u6253\u5305\u6307\u5357\u6216\u5b9e\u7269\u5305\u88c5\u4e3a\u51c6",
        "\u5f85\u786e\u8ba4",
        "\u6682\u65e0\u660e\u786e\u6570\u636e",
    )
    real_values = ("\u4e3b\u4f53\u6750\u8d28 PP", "\u5bbd 38cm", "\u6bdb\u91cd 2.5kg", "\u53ef\u62c6\u5378", "\u4e0d\u53ef\u62c6\u5378")

    assert all(is_placeholder_evidence_text(value) for value in placeholders)
    assert not any(is_placeholder_evidence_text(value) for value in real_values)


def test_admits_reviewed_scoped_direct_product_fact():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    assert context["unresolved_claims"] == []
    assert context["read_only"] is True
    assert context["can_change_can_send"] is False


def _operational_fact(**overrides):
    value = {
        "evidence_uid": "live-logistics-fact",
        "source_type": "erp_live_logistics",
        "evidence_role": "operational_fact_direct",
        "fact_type": "stock_shipping",
        "claim_types_supported": ["stock_shipping"],
        "fact": "承运商已接收包裹，当前状态为已发出。",
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
        "operational_scope": "logistics",
        "tool_execution_status": "completed",
        "read_only": True,
    }
    value.update(overrides)
    return value


def test_admits_completed_read_only_operational_fact_separately_from_product_facts():
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [_operational_fact()]},
        product_identity={},
        understanding=_understanding("stock_shipping"),
    )

    assert context["direct_product_facts"] == []
    assert [item["evidence_uid"] for item in context["direct_operational_facts"]] == [
        "live-logistics-fact"
    ]
    assert context["claim_resolutions"][0]["status"] == "supported"
    assert context["unresolved_claims"] == []


def test_projects_completed_jst_no_record_outcome_as_non_fact_service_action():
    response = {
        "tool_results": {
            "jst_lookup_outbound_tool": {
                "found": False,
                "lookup_complete": True,
                "safe_fallback_reason": "not_found",
                "query_type": "platform_trade_id",
            }
        }
    }

    admitted = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={},
        understanding=_understanding("stock_shipping"),
    )
    actions = admitted["handoff_action_guidance"]
    assert len(actions) == 1
    assert actions[0]["action_type"] == "inform_lookup_completed_no_record"
    assert actions[0]["completed"] is True
    assert actions[0]["non_fact"] is True
    assert actions[0]["can_change_can_send"] is False
    assert "订单号" not in actions[0]["text"]

    minimal = build_minimal_decision_context(
        admitted,
        customer_message="现在快递到哪里了",
    )
    assert minimal["service_actions"][0]["action_type"] == (
        "inform_lookup_completed_no_record"
    )
    assert minimal["service_actions"][0]["completed"] is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"tool_execution_status": "planned"}, "operational_tool_not_completed"),
        ({"read_only": False}, "operational_fact_not_read_only"),
        ({"operational_scope": ""}, "operational_scope_missing"),
    ],
)
def test_operational_fact_fails_closed_without_completed_read_contract(overrides, reason):
    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [_operational_fact(**overrides)]},
        product_identity={},
        understanding=_understanding("stock_shipping"),
    )

    assert context["direct_operational_facts"] == []
    assert context["claim_resolutions"][0]["status"] == "unresolved"
    assert any(item["reason"] == reason for item in context["rejected_evidence"])


def test_same_origin_transport_copies_do_not_make_dimension_claim_ambiguous():
    first = _fact(
        evidence_uid="pack-dimensions",
        origin_evidence_key="kb_product:2:dimensions:size",
        fact_type="dimensions",
        attribute_key="",
        content="高度约63cm。",
        value="63cm",
    )
    duplicate = _fact(
        evidence_uid="profile-dimensions",
        origin_evidence_key="kb_product:2:dimensions:size",
        fact_type="dimensions",
        attribute_key="dimensions",
        content="尺寸：高度约63cm。",
        value="63cm",
    )

    context = AdmittedAnswerContextService().build_for_response(
        {"formal_evidence_candidates": [duplicate, first]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
    )

    assert len(context["direct_product_facts"]) == 1
    assert context["claim_resolutions"][0]["status"] == "supported"
    assert any(item["reason"] == "duplicate_evidence" for item in context["rejected_evidence"])


def test_preserves_dimension_subject_scope_without_cross_scope_conflict():
    response = {
        "selected_evidence": [
            _fact(
                evidence_uid="component-width",
                fact_type="dimensions",
                attribute_key="width",
                subject_scope="component",
                content="Component width is 31 cm.",
                value="31cm",
            ),
            _fact(
                evidence_uid="product-width",
                fact_type="dimensions",
                attribute_key="width",
                subject_scope="product",
                content="Overall product width is 45 cm.",
                value="45cm",
            ),
        ],
    }
    understanding = {
        "requested_claims": [
            {
                "claim_type": "dimensions",
                "attribute_key": "overall_width",
                "question": "overall width",
                "risk_level": "low",
            },
        ],
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
    )

    assert {
        item["evidence_uid"]: item["subject_scope"]
        for item in context["direct_product_facts"]
    } == {
        "component-width": "component",
        "product-width": "product",
    }
    resolution = context["claim_resolutions"][0]
    assert resolution["status"] == "supported"
    assert resolution["evidence_uids"] == ["product-width"]
    assert not any(
        item["reason"] == "conflicting_evidence"
        for item in context["rejected_evidence"]
    )


def test_requested_dimension_scope_survives_admission_to_resolution():
    response = {
        "selected_evidence": [
            _fact(
                evidence_uid="product-width",
                fact_type="dimensions",
                attribute_key="width",
                subject_scope="product",
                content="Product width is 45 cm.",
                value="45cm",
            ),
            _fact(
                evidence_uid="packaging-width",
                fact_type="dimensions",
                attribute_key="width",
                subject_scope="packaging",
                content="Packaging width is 51 cm.",
                value="51cm",
            ),
        ],
    }
    understanding = {
        "requested_claims": [
            {
                "claim_type": "dimensions",
                "attribute_key": "width",
                "subject_scope": "packaging",
                "question": "packaging width",
                "risk_level": "low",
            },
        ],
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
    )

    resolution = context["claim_resolutions"][0]
    assert context["requested_claims"][0]["subject_scope"] == "packaging"
    assert resolution["subject_scope"] == "packaging"
    assert resolution["evidence_uids"] == ["packaging-width"]


def test_rejects_reference_placeholder_identity_mismatch_and_unreviewed_faq():
    response = {
        "selected_evidence": [
            _fact(evidence_uid="reference", reference_only=True),
            _fact(evidence_uid="placeholder", content="材质未明确，需要人工确认。"),
            _fact(evidence_uid="wrong-product", sku_code="SKU-B"),
            _fact(
                evidence_uid="faq-unreviewed",
                evidence_role="faq_direct",
                source_type="faq",
                fact_review_status="pending_review",
            ),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    reasons = {item["evidence_uid"]: item["reason"] for item in context["rejected_evidence"]}
    assert reasons == {
        "reference": "reference_only",
        "placeholder": "placeholder_evidence",
        "wrong-product": "product_identity_mismatch",
        "faq-unreviewed": "review_status_missing",
    }


def test_rejects_placeholder_with_intervening_characters():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact(evidence_uid="placeholder-spread", content="未在现有结构资料中明确尺寸")]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    reasons = {item["evidence_uid"]: item["reason"] for item in context["rejected_evidence"]}
    assert reasons == {"placeholder-spread": "placeholder_evidence"}


def test_conflicting_product_fact_and_faq_are_both_blocked():
    response = {
        "selected_evidence": [
            _fact(evidence_uid="product", attribute_key="load_capacity", fact_type="load_capacity", value="10kg", content="承重10kg"),
            _fact(evidence_uid="faq", evidence_role="faq_direct", source_type="faq", attribute_key="load_capacity", fact_type="load_capacity", value="15kg", content="承重15kg"),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("load_capacity"),
    )

    assert context["direct_product_facts"] == []
    assert {item["evidence_uid"] for item in context["conflicts"]} == {"product", "faq"}
    assert {item["reason"] for item in context["conflicts"]} == {"conflicting_evidence"}


def test_conflicting_structured_material_values_are_both_blocked():
    response = {
        "selected_evidence": [
            _fact(evidence_uid="product-material", value="PP", content="主体材质为PP。"),
            _fact(
                evidence_uid="faq-material",
                evidence_role="faq_direct",
                source_type="faq",
                value="ABS",
                content="主体材质为ABS。",
            ),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    assert {item["evidence_uid"] for item in context["conflicts"]} == {
        "product-material", "faq-material",
    }
    assert {item["reason"] for item in context["rejected_evidence"]} == {"material_conflicting_evidence"}


def test_material_alias_conflicts_share_one_slot_without_changing_provenance():
    response = {
        "selected_evidence": [
            _fact(
                evidence_uid="material-pp",
                origin_evidence_key="kb:material-pp",
                fact_type="material",
                attribute_key="material",
                value="PP",
                content="主体材质为PP。",
            ),
            _fact(
                evidence_uid="material-abs",
                origin_evidence_key="kb:material-abs",
                evidence_role="faq_direct",
                source_type="faq",
                fact_type="material_composition",
                attribute_key="material_composition",
                value="ABS",
                content="主体材质为ABS。",
            ),
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material"),
    )

    assert context["direct_product_facts"] == []
    conflicts = {
        item["evidence_uid"]: item
        for item in context["conflicts"]
    }
    assert set(conflicts) == {"material-pp", "material-abs"}
    assert conflicts["material-pp"]["origin_evidence_key"] == "kb:material-pp"
    assert conflicts["material-abs"]["origin_evidence_key"] == "kb:material-abs"
    assert {
        item["canonical_attribute_key"]
        for item in conflicts.values()
    } == {"material_composition"}


def test_material_alias_admission_preserves_uid_identity_and_raw_attribute():
    context = AdmittedAnswerContextService().build_for_response(
        {
            "selected_evidence": [
                _fact(
                    evidence_uid="material-profile",
                    origin_evidence_key="kb:material-profile",
                    fact_type="material_composition",
                    attribute_key="material_composition",
                    value="PP",
                    content="主体材质为PP。",
                )
            ]
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material"),
    )

    fact = context["direct_product_facts"][0]
    assert fact["evidence_uid"] == "material-profile"
    assert fact["origin_evidence_key"] == "kb:material-profile"
    assert fact["product_identity_scope"] == [
        {"namespace": "sku_code", "value": "SKU-A"}
    ]
    assert fact["attribute_key"] == "material_composition"
    assert fact["canonical_attribute_key"] == "material_composition"
    assert fact["original_fact_type"] == "material_composition"
    assert fact["original_evidence_attribute_key"] == "material_composition"
    assert context["claim_resolutions"][0]["status"] == "supported"


def test_material_display_attribute_and_empty_evidence_slot_preserve_provenance():
    understanding = {
        "requested_claims": [{
            "claim_type": "material",
            "attribute_key": "材质",
            "question": "材质",
            "risk_level": "medium",
        }]
    }
    context = AdmittedAnswerContextService().build_for_response(
        {
            "selected_evidence": [
                _fact(
                    evidence_uid="material-empty-slot",
                    origin_evidence_key="kb:material-empty-slot",
                    attribute_key="",
                )
            ]
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
    )

    fact = context["direct_product_facts"][0]
    resolution = context["claim_resolutions"][0]
    assert fact["attribute_key"] == ""
    assert fact["canonical_attribute_key"] == "material_composition"
    assert fact["original_fact_type"] == "material"
    assert fact["original_evidence_attribute_key"] == ""
    assert fact["evidence_uid"] == "material-empty-slot"
    assert fact["origin_evidence_key"] == "kb:material-empty-slot"
    assert fact["product_identity_scope"] == [
        {"namespace": "sku_code", "value": "SKU-A"}
    ]
    assert resolution["status"] == "supported"
    assert resolution["evidence_uids"] == ["material-empty-slot"]
    assert resolution["original_claim_type"] == "material"
    assert resolution["original_attribute_key"] == "材质"
    assert resolution["canonical_attribute_key"] == "material_composition"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"sku_code": "SKU-B"}, "product_identity_mismatch"),
        ({"fact_review_status": "pending_review"}, "review_status_missing"),
        ({"gate_status": "blocked"}, "gate_not_allowed"),
        ({"direct_answer_allowed": False}, "not_direct_answerable"),
    ],
)
def test_material_alias_does_not_bypass_admission_boundaries(overrides, reason):
    context = AdmittedAnswerContextService().build_for_response(
        {
            "selected_evidence": [
                _fact(
                    fact_type="material_composition",
                    attribute_key="material_composition",
                    **overrides,
                )
            ]
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material"),
    )

    assert context["direct_product_facts"] == []
    assert context["rejected_evidence"][0]["reason"] == reason


def test_compound_claims_do_not_promote_material_into_safety_or_moisture():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition", "material_safety", "moisture_resistance"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    assert {item["claim_type"] for item in context["unresolved_claims"]} == {
        "material_safety",
        "moisture_resistance",
    }
    resolutions = {item["claim_type"]: item for item in context["claim_resolutions"]}
    assert resolutions["material_composition"]["status"] == "supported"
    assert resolutions["material_composition"]["evidence_uids"] == ["fact-material"]
    assert resolutions["material_safety"]["status"] == "unresolved"
    assert resolutions["moisture_resistance"]["status"] == "unresolved"


def test_unmapped_customer_goal_is_preserved_as_unresolved():
    understanding = {
        "requested_claims": [
            {
                "goal_ref": "goal-material",
                "goal_kind": "customer_goal",
                "claim_type": "material",
                "semantic_key": "",
                "goal_summary": "确认商品材质",
                "question": "这款是什么材质，能保证摔不坏吗？",
                "risk_level": "medium",
            },
            {
                "goal_ref": "goal-durability",
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "semantic_key": "",
                "goal_summary": "确认是否能保证摔不坏",
                "question": "这款是什么材质，能保证摔不坏吗？",
                "risk_level": "medium",
            },
        ]
    }

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
    )

    requested = {
        item["goal_ref"]: item
        for item in context["requested_claims"]
        if item.get("goal_kind") == "customer_goal"
    }
    resolutions = {
        item["goal_ref"]: item
        for item in context["claim_resolutions"]
        if item.get("goal_kind") == "customer_goal"
    }
    assert requested["goal-durability"]["claim_type"] == ""
    assert requested["goal-durability"]["semantic_key"] == ""
    assert resolutions["goal-durability"]["status"] == "unresolved"
    assert resolutions["goal-durability"]["reason"] == (
        "unmapped_claim_type"
    )
    assert resolutions["goal-durability"]["evidence_uids"] == []
    assert resolutions["goal-durability"]["semantic_key"] == ""
    assert resolutions["goal-durability"]["goal_summary"] == (
        "确认是否能保证摔不坏"
    )
    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is False


def test_semantic_key_variation_cannot_change_admission_or_send_contract():
    from app.agent.nodes.query_fact_type_classifier import (
        _requested_claims_from_customer_goals,
    )
    from app.services import semantic_fact_type_service

    message = "material request and durability request"
    base_goals = [
        {
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "material",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "material request",
        },
        {
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "drop_durability",
            "semantic_key": "first_durability_wording",
            "policy_intent_ref": "",
            "source_text": "durability request",
        },
    ]
    alternate_goals = deepcopy(base_goals)
    alternate_goals[1]["semantic_key"] = "second_durability_wording"

    contexts = []
    responses = []
    for raw_goals in (base_goals, alternate_goals):
        goals, status, diagnostics = (
            semantic_fact_type_service._sanitize_customer_goals(
                raw_goals,
                message=message,
            )
        )
        assert status == "valid"
        assert diagnostics == []
        requested = _requested_claims_from_customer_goals(
            goals,
            question=message,
            risk_hint="medium",
        )
        response = {
            "selected_evidence": [_fact()],
            "can_send": False,
            "requires_human_review": True,
        }
        original = deepcopy(response)
        contexts.append(
            AdmittedAnswerContextService().build_for_response(
                response,
                product_identity={"sku_code": "SKU-A"},
                understanding={"requested_claims": requested},
            )
        )
        responses.append((response, original))

    assert [
        item["evidence_uid"]
        for item in contexts[0]["direct_product_facts"]
    ] == [
        item["evidence_uid"]
        for item in contexts[1]["direct_product_facts"]
    ] == ["fact-material"]
    assert [
        (item["goal_ref"], item["status"])
        for item in contexts[0]["claim_resolutions"]
    ] == [
        (item["goal_ref"], item["status"])
        for item in contexts[1]["claim_resolutions"]
    ]
    assert all(item["can_change_can_send"] is False for item in contexts)
    assert all(response == original for response, original in responses)


def test_rebuilds_customer_requested_claims_from_canonical_goals_on_goal_ref_mismatch():
    from app.agent.nodes.query_fact_type_classifier import (
        _requested_claims_from_customer_goals,
    )
    from app.services import semantic_fact_type_service

    message = "material request and durability request"
    goals, status, diagnostics = semantic_fact_type_service._sanitize_customer_goals(
        [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "material",
                "attribute_key": "material",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "material request",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "drop_durability",
                "semantic_key": "durability_wording",
                "policy_intent_ref": "",
                "source_text": "durability request",
            },
        ],
        message=message,
    )
    assert status == "valid"
    assert diagnostics == []
    requested = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    corrupted = deepcopy(requested)
    corrupted[0]["goal_ref"] = "a" * 40

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding={
            "customer_goals": goals,
            "requested_claims": corrupted,
        },
    )

    expected_goal_refs = {item["goal_ref"] for item in goals}
    requested_goal_refs = {
        item["goal_ref"]
        for item in context["requested_claims"]
        if item.get("goal_kind") == "customer_goal"
    }
    resolution_goal_refs = {
        item["goal_ref"]
        for item in context["claim_resolutions"]
        if item.get("goal_kind") == "customer_goal"
    }
    assert requested_goal_refs == expected_goal_refs
    assert resolution_goal_refs == expected_goal_refs
    assert "a" * 40 not in requested_goal_refs


def test_rebuilding_customer_claims_discards_untyped_stale_goal_projection():
    goals = [
        {
            "goal_ref": "goal-material",
            "goal_kind": "customer_goal",
            "claim_type": "material_safety",
        },
        {
            "goal_ref": "goal-dimension",
            "goal_kind": "customer_goal",
            "claim_type": "dimensions",
        },
    ]
    requested = [
        {
            "goal_ref": "goal-material",
            "goal_kind": "customer_goal",
            "claim_type": "material_safety",
        },
        {
            "goal_ref": "goal-dimension",
            "goal_kind": "customer_goal",
            "claim_type": "dimensions",
        },
        {
            "goal_ref": "c" * 40,
            "claim_type": "dimensions",
        },
    ]

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding={
            "customer_goals": goals,
            "requested_claims": requested,
        },
    )

    expected_goal_refs = {item["goal_ref"] for item in goals}
    assert {
        item["goal_ref"]
        for item in context["requested_claims"]
        if item.get("goal_kind") == "customer_goal"
    } == expected_goal_refs
    assert {
        item["goal_ref"]
        for item in context["claim_resolutions"]
        if item.get("goal_kind") == "customer_goal"
    } == expected_goal_refs
    assert "c" * 40 not in {
        item.get("goal_ref") for item in context["claim_resolutions"]
    }


def test_rebuilt_customer_claim_defaults_to_high_risk_when_derived_goal_ref_is_stale():
    from app.agent.nodes.query_fact_type_classifier import (
        _requested_claims_from_customer_goals,
    )
    from app.services import semantic_fact_type_service

    message = "material request"
    goals, status, _diagnostics = semantic_fact_type_service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "material",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": message,
        }],
        message=message,
    )
    assert status == "valid"
    requested = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="low",
    )
    requested[0]["goal_ref"] = "b" * 40

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding={
            "customer_goals": goals,
            "requested_claims": requested,
        },
    )

    rebuilt = context["requested_claims"][0]
    assert rebuilt["goal_ref"] == goals[0]["goal_ref"]
    assert rebuilt["risk_level"] == "high"


def test_rebuilt_customer_claim_projects_only_derived_claim_fields():
    from app.agent.nodes.query_fact_type_classifier import (
        _requested_claims_from_customer_goals,
    )
    from app.services import semantic_fact_type_service

    message = "material request"
    goals, status, _diagnostics = semantic_fact_type_service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "material",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": message,
        }],
        message=message,
    )
    assert status == "valid"
    requested = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding={
            "customer_goals": goals,
            "requested_claims": requested,
        },
    )

    assert context["requested_claims"][0]["unexpected_fields"] == []


def test_rebuilding_customer_claims_preserves_non_customer_requested_items():
    from app.agent.nodes.query_fact_type_classifier import (
        _requested_claims_from_customer_goals,
    )
    from app.services import semantic_fact_type_service

    message = "material request"
    goals, status, _diagnostics = semantic_fact_type_service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "material",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": message,
        }],
        message=message,
    )
    assert status == "valid"
    requested = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    requested.append({
        "goal_kind": "service_action",
        "claim_type": "after_sales",
        "question": "service request",
        "risk_level": "high",
    })

    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding={
            "customer_goals": goals,
            "requested_claims": requested,
        },
    )

    assert any(
        item.get("goal_kind") == "service_action"
        and item.get("claim_type") == "after_sales"
        for item in context["requested_claims"]
    )


def test_material_composition_cannot_admit_a_material_safety_claim():
    context = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_safety"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    resolutions = {item["claim_type"]: item for item in context["claim_resolutions"]}
    assert resolutions["material_composition"]["status"] == "supported"
    assert resolutions["material_safety"]["status"] == "unresolved"


def test_conflicting_claim_is_not_reported_as_supported():
    context = AdmittedAnswerContextService().build_for_response(
        {
            "selected_evidence": [
                _fact(evidence_uid="a", value="10kg", content="承重10kg", fact_type="load_capacity", attribute_key="load_capacity"),
                _fact(evidence_uid="b", value="15kg", content="承重15kg", fact_type="load_capacity", attribute_key="load_capacity"),
            ]
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("load_capacity"),
    )

    resolution = context["claim_resolutions"][0]
    assert resolution["claim_type"] == "load_capacity"
    assert resolution["status"] == "conflicting"
    assert resolution["evidence_uids"] == []
    assert resolution["conflicting_evidence_uids"] == ["a", "b"]
    assert resolution["requires_human_review"] is True
    assert resolution["reason"] == "conflicting_evidence"
    assert resolution["claim_uid"].startswith("claim-")


def test_roles_remain_separate():
    response = {
        "product_context_pack": {
            "generic_rules": [{
                "evidence_uid": "action",
                "source_type": "generic_rule",
                "evidence_role": "service_action",
                "content": "无法确认时转人工核对。",
            }],
            "media_assets": [{
                "evidence_uid": "media",
                "source_type": "media_asset",
                "evidence_role": "media_reference",
                "asset_type": "size_chart_image",
                "asset_url": "https://example.com/size.png",
            }],
        }
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("dimensions"),
    )

    assert context["direct_product_facts"] == []
    assert [item["evidence_uid"] for item in context["handoff_action_guidance"]] == ["action"]
    assert [item["evidence_uid"] for item in context["media_candidates"]] == ["media"]


def test_service_does_not_mutate_input():
    response = {"selected_evidence": [_fact()]}
    before = deepcopy(response)
    AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )
    assert response == before


def test_minimal_decision_context_keeps_recent_canonical_turns_and_excludes_raw_stores():
    admitted = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )
    context = build_minimal_decision_context(
        admitted,
        customer_message="上次说的材质是什么？",
        conversation_turns=[
            {"role": "customer", "content": "先问一下材质", "turn_uid": "turn-a", "turn_index": 1},
            {"role": "agent", "content": "我先核对", "turn_uid": "turn-b", "turn_index": 2},
        ],
    )

    assert [turn["content"] for turn in context["recent_conversation_turns"]] == ["先问一下材质", "我先核对"]
    assert all("turn_uid" not in turn for turn in context["recent_conversation_turns"])
    assert context["context_stats"]["recent_turn_count"] == 2
    assert {"full_trace", "raw_candidate_store", "answer_memory_history"}.issubset(
        context["context_stats"]["excluded_context_categories"]
    )
    assert [item["evidence_uid"] for item in context["admitted_evidence"]] == ["fact-material"]


def test_minimal_decision_context_projects_private_conversation_text_for_external_model():
    admitted = AdmittedAnswerContextService().build_for_response(
        {"selected_evidence": [_fact()]},
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )
    context = build_minimal_decision_context(
        admitted,
        customer_message="订单号 A-12345，手机号 13812345678，请改到上海市浦东新区测试路88号",
        conversation_turns=[{
            "role": "customer",
            "content": "订单号 A-12345，手机号 13812345678",
            "turn_index": 1,
        }],
    )
    rendered = str(context)

    assert "A-12345" not in rendered
    assert "13812345678" not in rendered


def test_read_only_shadow_retrieval_results_still_require_admission():
    response = {
        "evidence_debug": {
            "llm_decision_shadow_tool_results": {
                "rag_search_tool": {"chunks": [_fact(evidence_uid="shadow-material")]}
            }
        }
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["shadow-material"]
    assert context["direct_product_facts"][0]["source_container"].startswith(
        "llm_decision_shadow_tool_results"
    )


def test_uses_explicit_resolved_identity_from_evidence_pack():
    response = {
        "selected_evidence": [_fact()],
        "context_used": {
            "product_context_pack": {
                "evidence_pack": {"identity": {"sku": "SKU-A", "i_id": "IID-A"}}
            }
        },
    }

    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={},
        understanding=_understanding("material_composition"),
    )

    assert [item["evidence_uid"] for item in context["direct_product_facts"]] == ["fact-material"]
    assert context["product_identity"] == {"sku_code": "SKU-A", "i_id": "IID-A"}


def test_reviewed_structured_pack_fact_enters_shadow_context_with_explicit_scope():
    structured_fact = {
        "evidence_id": "kbproduct:42:material",
        "source_type": "product_facts",
        "fact_type": "material",
        "attribute_key": "material",
        "chunk_text": "Material: verified board and steel frame.",
        "sku_scope": ["SKU-A"],
        "product_scope": ["IID-A"],
        "metadata": {
                "product_evidence_protocol": True,
                "verification_status": "verified",
                "can_direct_answer": True,
                "material_provenance": "structured_product_record",
        },
    }
    context = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [structured_fact]}},
        product_identity={"sku_code": "SKU-A", "i_id": "IID-A"},
        understanding=_understanding("material_composition"),
    )

    assert len(context["direct_product_facts"]) == 1
    assert context["direct_product_facts"][0]["origin_evidence_key"] == "product_facts:kbproduct:42:material"
    assert context["direct_product_facts"][0]["text"] == "Material: verified board and steel frame."
    trace = context["evidence_convergence"]
    record = trace["records"][0]
    assert record["context_pack_candidate"] is True
    assert record["formal_selected"] is False
    assert record["shadow_admission"] == "admitted"
    assert record["llm_context"] is True
    assert trace["summary"]["context_pack_not_formal_selected_count"] == 1


def test_structured_pack_fact_with_nonmatching_explicit_scope_stays_rejected():
    structured_fact = {
        "evidence_id": "kbproduct:42:material",
        "source_type": "product_facts",
        "fact_type": "material",
        "attribute_key": "material",
        "chunk_text": "Material: verified board and steel frame.",
        "sku_scope": ["SKU-B"],
        "product_scope": ["IID-B"],
        "metadata": {
                "product_evidence_protocol": True,
                "verification_status": "verified",
                "can_direct_answer": True,
                "material_provenance": "structured_product_record",
        },
    }
    context = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [structured_fact]}},
        product_identity={"sku_code": "SKU-A", "i_id": "IID-A"},
        understanding=_understanding("material_composition"),
    )

    assert context["direct_product_facts"] == []
    assert context["rejected_evidence"][0]["reason"] == "product_identity_mismatch"
    assert context["evidence_convergence"]["records"][0]["llm_context"] is False


def _bounded_inference_pack() -> dict:
    return {
        "schema_version": "domain-policy-pack/v1",
        "domain_id": "fixture_domain",
        "version": "1.0.0",
        "status": "loaded",
        "reason_codes": [],
        "claim_policies": {
            "material_composition": {
                "risk_level": "low",
                "direct_fact_fast_path_allowed": True,
                "bounded_inference_policy": "none",
                "freshness_requirement": "static",
            },
        },
        "bounded_inference_policies": [{
            "policy_intent_ref": "product_durability_practical_guidance",
            "goal_family": "product_durability",
            "intent_kind": "practical_guidance",
            "premise_fact_families": ["material_composition"],
            "required_context_capabilities": ["product_category"],
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
    }


def _bounded_inference_understanding() -> dict:
    return {
        "requested_claims": [
            {
                "goal_ref": "goal-material",
                "goal_kind": "customer_goal",
                "claim_type": "material_composition",
                "attribute_key": "material",
                "semantic_key": "product_material",
                "goal_summary": "了解商品材质",
                "risk_level": "low",
            },
            {
                "goal_ref": "goal-durability",
                "goal_kind": "customer_goal",
                "claim_type": "unmapped_customer_goal",
                "attribute_key": "drop_durability",
                "semantic_key": "product_drop_durability",
                "policy_intent_ref": (
                    "product_durability_practical_guidance"
                ),
                "policy_goal_family": "product_durability",
                "policy_intent_kind": "practical_guidance",
                "goal_summary": "了解日常意外跌落的耐用边界",
                "risk_level": "medium",
            },
        ],
    }


def test_admitted_context_builds_policy_bounded_inference_from_trusted_context():
    response = {
        "selected_evidence": [
            _fact(fact_type="material_composition", attribute_key="material")
        ],
        "product_context_pack": {
            "structured_profile": {
                "source": "kb_product",
                "category": {"l1": "fixture category", "l2": "", "l3": ""},
            },
        },
    }
    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_bounded_inference_understanding(),
        answer_eligibility_inputs={
            "domain_policy_pack": _bounded_inference_pack(),
        },
    )

    by_goal = {
        item["goal_ref"]: item for item in context["claim_resolutions"]
    }
    assert by_goal["goal-material"]["support_basis"] == "direct_evidence"
    assert by_goal["goal-durability"]["support_basis"] == "none"
    assert by_goal["goal-durability"]["premise_evidence_uids"] == []
    assert by_goal["goal-durability"]["inference_policy_refs"] == []
    options = by_goal["goal-durability"]["eligible_policy_options"]
    assert len(options) == 1
    assert options[0]["allowed_conclusion_family"] == (
        "ordinary_minor_impact_tolerance"
    )
    assert options[0]["allowed_variability_factor_families"] == [
        "contact_surface",
        "impact_angle",
        "impact_height",
    ]
    assert options[0]["advice_mode"] == "none"
    assert options[0]["premise_evidence_refs"] == [
        "fact-material"
    ]
    assert options[0]["policy_ref"] == (
        "domain-policy:fixture_domain@1.0.0:"
        "intent:product_durability_practical_guidance"
    )
    assert options[0]["review_only"] is True
    assert context["product_context_capabilities"] == {
        "product_category": {
            "available": True,
            "source": "product_context_pack.structured_profile.category",
        }
    }
    minimal = build_minimal_decision_context(
        context,
        customer_message="材质和日常耐用边界怎么样",
    )
    assert minimal["product_context_capabilities"] == (
        context["product_context_capabilities"]
    )
    assert minimal["bounded_inference_policies"][0]["policy_ref"] == (
        "domain-policy:fixture_domain@1.0.0:"
        "intent:product_durability_practical_guidance"
    )


def test_admitted_context_keeps_oral_safety_handling_out_of_evidence():
    pack = _bounded_inference_pack()
    pack["bounded_inference_policies"] = [{
        "policy_intent_ref": "oral_exposure_safety_handling",
        "goal_family": "bite_or_toxicity",
        "intent_kind": "practical_guidance",
        "premise_fact_families": [],
        "required_context_capabilities": ["product_category"],
        "allowed_scope": "interrupt_exposure_inspect_and_escalate_if_needed",
        "allowed_conclusion_family": "general_oral_exposure_risk_mitigation",
        "allowed_variability_factor_families": [],
        "advice_mode": "safety_handoff_required",
        "maximum_risk_level": "medium",
        "required_qualifiers": [
            "stop_further_oral_contact",
            "inspect_for_damage_or_missing_fragments",
            "seek_medical_help_if_ingested_or_symptomatic",
            "no_toxicity_or_ingestion_safety_conclusion",
        ],
        "prohibited_claim_families": [
            "bite_or_toxicity",
            "child_safety",
            "material_safety",
            "non_toxic_claim",
        ],
        "review_only": True,
    }]
    understanding = {
        "requested_claims": [{
            "goal_ref": "goal-oral-safety",
            "goal_kind": "customer_goal",
            "claim_type": "bite_or_toxicity",
            "claim_type_status": "mapped",
            "attribute_key": "bite_or_toxicity",
            "semantic_key": "bite_or_toxicity",
            "policy_intent_ref": "",
            "policy_goal_family": "bite_or_toxicity",
            "policy_intent_kind": "practical_guidance",
            "goal_summary": "understand oral exposure safety handling",
            "risk_level": "high",
        }],
    }
    context = AdmittedAnswerContextService().build_for_response(
        {
            "selected_evidence": [],
            "product_context_pack": {
                "structured_profile": {
                    "source": "kb_product",
                    "category": {
                        "l1": "fixture category",
                        "l2": "",
                        "l3": "",
                    },
                },
            },
        },
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding,
        answer_eligibility_inputs={"domain_policy_pack": pack},
    )

    resolution = context["claim_resolutions"][0]
    assert resolution["status"] == "unresolved"
    assert resolution["evidence_uids"] == []
    assert resolution["premise_evidence_uids"] == []
    assert resolution["restricted_request_boundary"][
        "must_remain_unresolved"
    ] is True
    option = resolution["eligible_policy_options"][0]
    assert option["premise_evidence_refs"] == []
    assert option["advice_mode"] == "safety_handoff_required"
    assert option["option_provenance"]["premise_owner"] == (
        "authoritative_customer_goal"
    )
    assert context["direct_product_facts"] == []
    minimal = build_minimal_decision_context(
        context,
        customer_message="oral exposure question",
    )
    assert minimal["admitted_evidence"] == []
    assert minimal["claim_resolutions"][0][
        "eligible_policy_options"
    ][0]["premise_evidence_refs"] == []


@pytest.mark.parametrize(
    ("evidence_overrides", "include_category", "include_pack"),
    [
        ({"sku_code": "SKU-B"}, True, True),
        ({"fact_review_status": "pending_review"}, True, True),
        ({"reference_only": True}, True, True),
        ({}, False, True),
        ({}, True, False),
    ],
)
def test_admitted_context_blocks_bounded_inference_without_all_trusted_inputs(
    evidence_overrides,
    include_category,
    include_pack,
):
    response = {
        "selected_evidence": [
            _fact(
                fact_type="material_composition",
                attribute_key="material",
                **evidence_overrides,
            )
        ],
        "product_context_pack": {
            "structured_profile": {
                "source": "kb_product",
                "category": (
                    {"l1": "fixture category", "l2": "", "l3": ""}
                    if include_category
                    else {}
                ),
            },
        },
    }
    eligibility = (
        {"domain_policy_pack": _bounded_inference_pack()}
        if include_pack
        else {}
    )
    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=_bounded_inference_understanding(),
        answer_eligibility_inputs=eligibility,
    )

    durability = next(
        item
        for item in context["claim_resolutions"]
        if item["goal_ref"] == "goal-durability"
    )
    assert durability["status"] == "unresolved"
    assert durability["support_basis"] == "none"
    assert durability["evidence_uids"] == []


def test_response_strategy_customer_input_is_projected_as_non_fact_action():
    original = {
        "customer_goal": "Check the current shipment status.",
        "service_actions": [{
            "evidence_uid": "existing-action",
            "text": "Existing non-fact action",
            "non_fact": True,
        }],
    }

    projected = project_response_strategy_actions(
        original,
        {
            "should_ask_slot": True,
            "missing_slots": ["order_id", "tracking_no"],
            "missing_slot_mode": "any_of",
        },
    )

    assert projected is not original
    assert original["service_actions"] == [{
        "evidence_uid": "existing-action",
        "text": "Existing non-fact action",
        "non_fact": True,
    }]
    assert projected["service_actions"][-1] == {
        "action_type": "request_customer_input",
        "accepted_input_slots": ["order_id", "tracking_no"],
        "input_selection_mode": "any_of",
        "source_owner": "response_strategy_planner",
        "non_fact": True,
        "completed": False,
        "can_change_can_send": False,
    }


@pytest.mark.parametrize(
    "plan",
    [
        {
            "should_ask_slot": True,
            "missing_slots": ["unknown_private_field"],
            "missing_slot_mode": "all_of",
        },
        {
            "should_ask_slot": True,
            "missing_slots": ["order_id", "tracking_no"],
            "missing_slot_mode": "unknown_mode",
        },
    ],
)
def test_response_strategy_customer_input_projection_fails_closed(plan):
    projected = project_response_strategy_actions(
        {"service_actions": []},
        plan,
    )

    assert projected["service_actions"] == []
