import copy
import json

import pytest

from app.agent.nodes.query_fact_type_classifier import (
    _requested_claims_from_customer_goals,
)
from app.services import semantic_fact_type_service as service
from app.services.claim_resolution_service import build_claim_resolutions
from app.services.fact_type_alias_service import (
    canonical_material_composition_claim_type,
)


def _raw_goal(
    *,
    source_text: str,
    source_span_start: int = 0,
    source_span_end: int | None = None,
    claim_type_status: str = "canonical",
    claim_type: str = "material",
    semantic_key: str = "",
    goal_kind: str = "customer_goal",
    **overrides,
) -> dict:
    goal = {
        "goal_kind": goal_kind,
        "claim_type_status": claim_type_status,
        "claim_type": claim_type,
        "attribute_key": "material",
        "semantic_key": semantic_key,
        "policy_intent_ref": "",
        "source_text": source_text,
    }
    goal.update(overrides)
    return goal


def _llm_result(customer_goals: list[dict], **overrides) -> dict:
    result = {"goals": customer_goals}
    result.update(overrides)
    return result


def test_canonical_material_and_material_composition_share_existing_family():
    message = "material request"
    material, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(source_text=message, claim_type="material")],
        message=message,
    )
    composition, composition_status, composition_diagnostics = (
        service._sanitize_customer_goals(
            [_raw_goal(
                source_text=message,
                claim_type="material_composition",
            )],
            message=message,
        )
    )

    assert status == composition_status == "valid"
    assert diagnostics == composition_diagnostics == []
    assert material[0]["claim_type_status"] == "canonical"
    assert composition[0]["claim_type_status"] == "canonical"
    assert canonical_material_composition_claim_type(
        material[0]["claim_type"]
    ) == canonical_material_composition_claim_type(
        composition[0]["claim_type"]
    ) == "material_composition"
    assert material[0]["goal_ref"] == composition[0]["goal_ref"]


def test_known_dimension_display_attribute_reaches_only_matching_direct_fact():
    message = "dimension request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type="dimensions",
            attribute_key="\u5bbd\u5ea6",
        )],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    claims = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    resolution = build_claim_resolutions(
        claims,
        direct_product_facts=[{
            "evidence_uid": "width-evidence",
            "claim_types_supported": ["dimensions"],
            "attribute_key": "width",
            "subject_scope": "product",
            "text": "verified width",
        }],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert claims[0]["attribute_key"] == "width"
    assert resolution["status"] == "supported"
    assert resolution["evidence_uids"] == ["width-evidence"]


def test_dimension_subject_scope_reaches_only_matching_direct_fact():
    message = "dimension request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type="dimensions",
            attribute_key="width",
            subject_scope="packaging",
        )],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    claims = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    resolution = build_claim_resolutions(
        claims,
        direct_product_facts=[
            {
                "evidence_uid": "product-width",
                "claim_types_supported": ["dimensions"],
                "attribute_key": "width",
                "subject_scope": "product",
                "text": "verified product width",
            },
            {
                "evidence_uid": "packaging-width",
                "claim_types_supported": ["dimensions"],
                "attribute_key": "width",
                "subject_scope": "packaging",
                "text": "verified packaging width",
            },
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert goals[0]["subject_scope"] == "packaging"
    assert claims[0]["subject_scope"] == "packaging"
    assert resolution["status"] == "supported"
    assert resolution["evidence_uids"] == ["packaging-width"]


def test_product_overall_dimensions_do_not_become_a_specific_axis():
    result = build_claim_resolutions(
        [{
            "goal_ref": "goal-product-width",
            "goal_kind": "customer_goal",
            "claim_type": "dimensions",
            "attribute_key": "width",
            "subject_scope": "product",
        }],
        direct_product_facts=[{
            "evidence_uid": "product-overall-dimensions",
            "claim_types_supported": ["dimensions"],
            "attribute_key": "overall_dimensions",
            "subject_scope": "product",
            "text": "verified overall dimensions",
        }],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "unresolved"
    assert result["evidence_uids"] == []


def test_product_overall_dimensions_require_same_scope_and_attribute():
    result = build_claim_resolutions(
        [{
            "goal_ref": "goal-product-overall-dimensions",
            "goal_kind": "customer_goal",
            "claim_type": "dimensions",
            "attribute_key": "overall_dimensions",
            "subject_scope": "product",
        }],
        direct_product_facts=[
            {
                "evidence_uid": "packaging-overall-dimensions",
                "claim_types_supported": ["dimensions"],
                "attribute_key": "overall_dimensions",
                "subject_scope": "packaging",
                "text": "verified packaging dimensions",
            },
            {
                "evidence_uid": "product-overall-dimensions",
                "claim_types_supported": ["dimensions"],
                "attribute_key": "overall_dimensions",
                "subject_scope": "product",
                "text": "verified product dimensions",
            },
        ],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert result["status"] == "supported"
    assert result["evidence_uids"] == ["product-overall-dimensions"]


def test_non_dimension_scope_cannot_promote_a_customer_goal():
    message = "material request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type="material",
            attribute_key="material",
            subject_scope="packaging",
        )],
        message=message,
    )

    assert status == "degraded"
    assert "dimension_subject_scope_not_applicable" in diagnostics
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["subject_scope"] == ""


def test_unknown_dimension_attribute_is_not_guessed_into_direct_evidence():
    message = "dimension request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type="dimensions",
            attribute_key="unregistered_dimension_property",
        )],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    claims = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    resolution = build_claim_resolutions(
        claims,
        direct_product_facts=[{
            "evidence_uid": "width-evidence",
            "claim_types_supported": ["dimensions"],
            "attribute_key": "width",
            "subject_scope": "product",
            "text": "verified width",
        }],
        direct_policy_facts=[],
        conflicts=[],
    )[0]

    assert claims[0]["attribute_key"] == "unregistered_dimension_property"
    assert resolution["status"] == "unresolved"
    assert resolution["evidence_uids"] == []


def test_unmapped_goal_is_preserved_without_authorizing_a_fact_type():
    message = "durability request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type_status="unmapped",
            claim_type="",
            semantic_key="product_drop_durability",
            attribute_key="drop_durability",
        )],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["claim_type"] == ""
    assert goals[0]["semantic_key"] == "product_drop_durability"
    claims = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    assert claims[0]["claim_type"] == ""
    assert claims[0]["semantic_key"] == "product_drop_durability"
    assert claims[0]["schema_version"] == (
        service.GOAL_IDENTITY_SCHEMA_VERSION
    )
    assert claims[0]["source_turn_uid"] == goals[0]["source_turn_uid"]
    assert claims[0]["source_text_sha256"] == (
        goals[0]["source_text_sha256"]
    )


@pytest.mark.parametrize(
    ("mutations", "reason_code"),
    [
        ({"claim_type_status": "canonical", "claim_type": ""},
         "canonical_claim_type_missing"),
        ({"claim_type_status": "canonical", "claim_type": "unknown_type"},
         "canonical_claim_type_unknown"),
        ({"claim_type_status": "unmapped", "claim_type": "material",
          "semantic_key": "product_drop_durability"},
         "unmapped_claim_type_present"),
        ({"claim_type_status": "unsupported_status"},
         "claim_type_status_invalid"),
        ({"claim_type_status": None},
         "claim_type_status_missing"),
    ],
)
def test_invalid_type_choice_is_preserved_as_unmapped_and_fail_closed(
    mutations,
    reason_code,
):
    message = "property request"
    raw = _raw_goal(source_text=message)
    if mutations.get("claim_type_status") is None:
        raw.pop("claim_type_status")
    else:
        raw.update(mutations)

    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )

    assert status == "degraded"
    assert reason_code in diagnostics
    assert len(goals) == 1
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["claim_type"] == ""
    assert goals[0]["claim_type_reason_code"] == reason_code
    assert goals[0]["goal_summary"]
    assert goals[0]["source_span_sha256"]


@pytest.mark.parametrize("semantic_key", [pytest.param(None, id="missing"), ""])
def test_unmapped_goal_preserves_optional_semantic_metadata(
    semantic_key,
):
    message = "durability request"
    raw = _raw_goal(
        source_text=message,
        claim_type_status="unmapped",
        claim_type="",
        semantic_key="temporary_hint",
    )
    if semantic_key is None:
        raw.pop("semantic_key")
    else:
        raw["semantic_key"] = semantic_key

    schema, provenance = service._validate_raw_llm_result(
        _llm_result([raw]),
        message=message,
    )
    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )

    assert schema == []
    assert provenance == []
    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 1
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["claim_type"] == ""
    assert goals[0]["semantic_key"] == ""
    assert goals[0]["goal_summary"] == message


@pytest.mark.parametrize(
    "semantic_key",
    [None, 3, True, {}, []],
)
def test_non_string_semantic_metadata_remains_schema_invalid(
    semantic_key,
):
    message = "durability request"
    raw = _raw_goal(
        source_text=message,
        claim_type_status="unmapped",
        claim_type="",
        semantic_key=semantic_key,
    )

    schema, _provenance = service._validate_raw_llm_result(
        _llm_result([raw]),
        message=message,
    )

    assert {
        (
            item["json_pointer"],
            item["reason_code"],
        )
        for item in schema
    } >= {
        (
            "$.goals[0].semantic_key",
            "goal_field_type_invalid",
        )
    }


@pytest.mark.parametrize(
    "semantic_key",
    [
        "visible damage",
        "refund or replacement",
        "\u53ef\u89c1\u7834\u635f",
    ],
)
def test_invalid_optional_semantic_hint_is_discarded_without_losing_unmapped_goal(
    semantic_key,
):
    message = "first request, second request, third request"
    raw_goals = [
        _raw_goal(
            source_text="first request",
            claim_type_status="unmapped",
            claim_type="",
            attribute_key="visible_condition",
            semantic_key=semantic_key,
        ),
        _raw_goal(
            source_text="second request",
            claim_type_status="unmapped",
            claim_type="",
            attribute_key="resolution_choice",
            semantic_key="resolution_choice",
        ),
        _raw_goal(
            source_text="third request",
            claim_type_status="canonical",
            claim_type="aftersales_policy",
            semantic_key="",
        ),
    ]

    schema, provenance = service._validate_raw_llm_result(
        _llm_result(raw_goals),
        message=message,
    )
    result = service._sanitize_llm_result(
        _llm_result(raw_goals),
        message=message,
    )

    assert schema == []
    assert provenance == []
    assert result is not None
    assert result["goal_understanding_status"] == "valid"
    assert len(result["customer_goals"]) == 3
    first = next(
        goal
        for goal in result["customer_goals"]
        if goal["attribute_key"] == "visible_condition"
    )
    assert first["claim_type_status"] == "unmapped"
    assert first["claim_type"] == ""
    assert first["semantic_key"] == ""


def test_invalid_optional_semantic_hint_cannot_promote_or_merge_goals():
    message = "property one and property two"
    raw_goals = [
        _raw_goal(
            source_text="property one",
            claim_type_status="unmapped",
            claim_type="",
            attribute_key="first_property",
            semantic_key="material composition",
        ),
        _raw_goal(
            source_text="property two",
            claim_type_status="unmapped",
            claim_type="",
            attribute_key="second_property",
            semantic_key="material composition",
        ),
    ]

    goals, status, diagnostics = service._sanitize_customer_goals(
        raw_goals,
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 2
    assert len({goal["goal_ref"] for goal in goals}) == 2
    assert all(goal["claim_type_status"] == "unmapped" for goal in goals)
    assert all(goal["claim_type"] == "" for goal in goals)
    assert all(goal["semantic_key"] == "" for goal in goals)


def test_semantic_metadata_presence_and_value_do_not_change_goal_identity():
    message = "durability request"
    base = _raw_goal(
        source_text=message,
        claim_type_status="unmapped",
        claim_type="",
        semantic_key="first_hint",
    )
    missing = dict(base)
    missing.pop("semantic_key")
    empty = {**base, "semantic_key": ""}
    changed = {**base, "semantic_key": "second_hint"}

    goal_refs = {
        service._sanitize_customer_goals(
            [raw],
            message=message,
        )[0][0]["goal_ref"]
        for raw in (base, missing, empty, changed)
    }

    assert len(goal_refs) == 1


@pytest.mark.parametrize(
    ("message", "attribute_key"),
    [
        ("confirm product durability boundary", "durability"),
        ("confirm installation limitation", "installation_constraint"),
        ("confirm aftersales handling boundary", "aftersales_handling"),
    ],
)
def test_optional_semantic_metadata_contract_is_domain_independent(
    message,
    attribute_key,
):
    raw = _raw_goal(
        source_text=message,
        claim_type_status="unmapped",
        claim_type="",
        semantic_key="temporary_hint",
        attribute_key=attribute_key,
    )
    raw.pop("semantic_key")

    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )
    claims = _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    )
    resolutions = build_claim_resolutions(
        claims,
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=[],
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == len(claims) == len(resolutions) == 1
    assert goals[0]["semantic_key"] == ""
    assert resolutions[0]["status"] == "unresolved"
    assert resolutions[0]["reason"] == "unmapped_claim_type"


def test_missing_semantic_metadata_does_not_clear_another_valid_goal():
    message = "material request and durability request"
    unmapped = _raw_goal(
        source_text="durability request",
        claim_type_status="unmapped",
        claim_type="",
        attribute_key="durability",
        semantic_key="temporary_hint",
    )
    unmapped.pop("semantic_key")

    result = service._sanitize_llm_result(
        _llm_result([
            _raw_goal(
                source_text="material request",
                claim_type="material",
            ),
            unmapped,
        ]),
        message=message,
    )

    assert result is not None
    assert result["goal_understanding_status"] == "valid"
    assert len(result["customer_goals"]) == 2
    assert {
        (goal["claim_type_status"], goal["claim_type"])
        for goal in result["customer_goals"]
    } == {
        ("canonical", "material"),
        ("unmapped", ""),
    }


def test_extra_goal_fields_and_public_owner_injection_fail_closed():
    message = "property request"
    raw = _raw_goal(
        source_text=message,
        canonical_fact_type_allowlist=["material"],
        owner="public_request",
        provenance={"source": "public_request"},
    )

    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )

    assert status == "degraded"
    assert diagnostics == ["customer_goal_fields_invalid"]
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["claim_type_reason_code"] == "customer_goal_fields_invalid"
    assert goals[0]["owner"] == "turn_understanding_owner"
    assert goals[0]["source_stage"] == "semantic_fact_type_service"


@pytest.mark.parametrize("field", ["goal_ref", "turn_uid"])
def test_public_goal_identity_fields_are_not_accepted_from_model_output(
    field,
    monkeypatch,
):
    message = "property request"
    raw = _raw_goal(source_text=message)
    raw[field] = "public-forged-identity"
    payload = _llm_result([raw])
    schema, _provenance = service._validate_raw_llm_result(
        payload,
        message=message,
    )

    assert "goal_extra_field" in {
        item["reason_code"] for item in schema
    }
    client = _FakeClient(payload)
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [],
    )
    diagnostics = {}

    result = service._classify_with_llm(
        {},
        message,
        "product_question",
        diagnostics_sink=diagnostics,
    )

    assert result is None
    assert diagnostics["schema_success"] is False
    assert diagnostics["model_call_count"] == 1


def test_invalid_service_action_cannot_become_a_product_fact_type():
    message = "service request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            goal_kind="service_action",
            claim_type_status="canonical",
            claim_type="material",
        )],
        message=message,
    )

    assert status == "degraded"
    assert "service_action_canonical_claim_forbidden" in diagnostics
    assert goals[0]["goal_kind"] == "service_action"
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["claim_type"] == ""
    assert _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    ) == []


def test_evidence_dependency_is_not_rewritten_as_customer_goal():
    message = "supporting property"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            goal_kind="evidence_dependency",
            claim_type_status="canonical",
            claim_type="material",
        )],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["goal_kind"] == "evidence_dependency"
    assert _requested_claims_from_customer_goals(
        goals,
        question=message,
        risk_hint="medium",
    ) == []


def test_semantic_key_variation_cannot_promote_unmapped_goal():
    message = "durability request"
    variants = (
        "material",
        "material_composition",
        "product_material_composition",
    )

    results = []
    for semantic_key in variants:
        goals, status, diagnostics = service._sanitize_customer_goals(
            [_raw_goal(
                source_text=message,
                claim_type_status="unmapped",
                claim_type="",
                semantic_key=semantic_key,
            )],
            message=message,
        )
        assert status == "valid"
        assert diagnostics == []
        results.append(goals[0])

    assert all(item["claim_type"] == "" for item in results)
    assert all(
        item["claim_type_status"] == "unmapped"
        for item in results
    )
    assert len({item["goal_ref"] for item in results}) == 1


def test_goal_summary_is_derived_from_resolved_source_text():
    message = "durability request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type_status="unmapped",
            claim_type="",
            semantic_key="drop_durability",
        )],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["goal_summary"] == message


def test_same_semantic_key_with_different_source_span_has_distinct_identity():
    message = "first durability request and second durability request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                source_text="first durability request",
                source_span_start=message.index(
                    "first durability request"
                ),
                claim_type_status="unmapped",
                claim_type="",
                semantic_key="drop_durability",
            ),
            _raw_goal(
                source_text="second durability request",
                source_span_start=message.index(
                    "second durability request"
                ),
                claim_type_status="unmapped",
                claim_type="",
                semantic_key="drop_durability",
            ),
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len({item["goal_ref"] for item in goals}) == 2


def test_source_turn_uid_is_server_bound_and_changes_goal_identity():
    message = "durability request"
    first_uid = "turn-" + ("1" * 20)
    second_uid = "turn-" + ("2" * 20)
    raw = _raw_goal(
        source_text=message,
        claim_type_status="unmapped",
        claim_type="",
        semantic_key="drop_durability",
    )
    first, _, _ = service._sanitize_customer_goals(
        [raw],
        message=message,
        source_turn_uid=first_uid,
    )
    second, _, _ = service._sanitize_customer_goals(
        [raw],
        message=message,
        source_turn_uid=second_uid,
    )

    assert first[0]["goal_ref"] != second[0]["goal_ref"]
    valid, reasons = service._validate_canonical_customer_goals(
        first,
        message=message,
        source_turn_uid=second_uid,
    )
    assert valid is False
    assert "customer_goal_source_turn_uid_invalid" in reasons


def test_changed_goal_ref_cannot_inherit_prior_claim_resolution():
    message = "material request"
    raw = _raw_goal(source_text=message)
    first_goals, _, _ = service._sanitize_customer_goals(
        [raw],
        message=message,
        source_turn_uid="turn-" + ("1" * 20),
    )
    second_goals, _, _ = service._sanitize_customer_goals(
        [raw],
        message=message,
        source_turn_uid="turn-" + ("2" * 20),
    )
    first_claims = _requested_claims_from_customer_goals(
        first_goals,
        question=message,
        risk_hint="medium",
    )
    second_claims = _requested_claims_from_customer_goals(
        second_goals,
        question=message,
        risk_hint="medium",
    )
    first_resolutions = build_claim_resolutions(
        first_claims,
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=[],
    )
    second_resolutions = build_claim_resolutions(
        second_claims,
        direct_product_facts=[],
        direct_policy_facts=[],
        conflicts=[],
    )

    assert first_resolutions[0]["goal_ref"] != (
        second_resolutions[0]["goal_ref"]
    )
    assert first_resolutions[0]["goal_ref"] not in {
        item["goal_ref"] for item in second_resolutions
    }


def test_source_text_digest_change_cannot_reuse_old_goal_ref():
    message = "material request"
    goals, _, _ = service._sanitize_customer_goals(
        [_raw_goal(source_text=message)],
        message=message,
    )
    old_goal_ref = goals[0]["goal_ref"]
    goals[0]["source_text_sha256"] = "1" * 64

    valid, reasons = service._validate_canonical_customer_goals(
        goals,
        message=message,
    )

    assert service._goal_ref(goals[0]) != old_goal_ref
    assert valid is False
    assert "customer_goal_source_text_digest_invalid" in reasons
    assert "customer_goal_identity_mismatch" in reasons


def test_semantic_classification_and_goal_kind_are_not_goal_identity():
    message = "property request"
    canonical, _, _ = service._sanitize_customer_goals(
        [_raw_goal(source_text=message)],
        message=message,
    )
    unmapped, _, _ = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            claim_type_status="unmapped",
            claim_type="",
            semantic_key="property_request",
        )],
        message=message,
    )
    dependency, _, _ = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            goal_kind="evidence_dependency",
        )],
        message=message,
    )
    service_action, _, _ = service._sanitize_customer_goals(
        [_raw_goal(
            source_text=message,
            goal_kind="service_action",
            claim_type_status="unmapped",
            claim_type="",
            semantic_key="property_request",
        )],
        message=message,
    )

    assert len({
        canonical[0]["goal_ref"],
        unmapped[0]["goal_ref"],
        dependency[0]["goal_ref"],
        service_action[0]["goal_ref"],
    }) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {
            "claim_type_status": "canonical",
            "claim_type": "material_composition",
            "attribute_key": "material_composition",
            "semantic_key": "",
        },
        {
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "drop_durability",
            "semantic_key": "drop_durability",
        },
        {
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "different_material_slot",
            "semantic_key": "",
        },
    ],
)
def test_classification_fields_change_without_changing_goal_ref(mutation):
    message = "property request"
    baseline, _, _ = service._sanitize_customer_goals(
        [_raw_goal(source_text=message)],
        message=message,
    )
    changed, _, _ = service._sanitize_customer_goals(
        [_raw_goal(source_text=message, **mutation)],
        message=message,
    )

    assert changed[0]["goal_ref"] == baseline[0]["goal_ref"]
    assert (
        changed[0]["claim_type_status"],
        changed[0]["claim_type"],
        changed[0]["attribute_key"],
    ) != (
        baseline[0]["claim_type_status"],
        baseline[0]["claim_type"],
        baseline[0]["attribute_key"],
    )


def test_one_invalid_goal_does_not_overwrite_valid_goal_and_order_is_stable():
    message = "material request and durability request"
    valid = _raw_goal(
        source_text="material request",
        claim_type="material",
    )
    invalid = _raw_goal(
        source_text="durability request",
        source_span_start=message.index("durability request"),
        claim_type_status="canonical",
        claim_type="unknown_type",
        semantic_key="product_drop_durability",
    )

    forward = service._sanitize_customer_goals(
        [valid, invalid],
        message=message,
    )
    reverse = service._sanitize_customer_goals(
        [invalid, valid],
        message=message,
    )

    assert forward == reverse
    goals, status, diagnostics = forward
    assert status == "degraded"
    assert diagnostics == ["canonical_claim_type_unknown"]
    assert len(goals) == 2
    assert {
        (item["claim_type_status"], item["claim_type"])
        for item in goals
    } == {("canonical", "material"), ("unmapped", "")}


def test_top_level_schema_is_exact_and_does_not_accept_reasoning():
    message = "material request"
    valid = _llm_result([_raw_goal(source_text=message)])
    assert service._sanitize_llm_result(
        valid,
        message=message,
    ) is not None

    for mutation in (
        {"reasoning": "hidden reasoning"},
        {"canonical_fact_type_allowlist": ["material"]},
        {"owner": "public_request"},
    ):
        invalid = {**valid, **mutation}
        assert service._sanitize_llm_result(
            invalid,
            message=message,
        ) is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda goals: goals[0].pop("goal_ref"),
         "customer_goal_ref_missing"),
        (lambda goals: goals.append(copy.deepcopy(goals[0])),
         "duplicate_resolved_provenance"),
        (lambda goals: goals[0].update(source_span_end=10_000),
         "customer_goal_source_span_invalid"),
        (lambda goals: goals[0].update(source_span_sha256="0" * 64),
         "customer_goal_source_digest_invalid"),
        (lambda goals: goals[0].pop("owner"),
         "canonical_customer_goal_schema_invalid"),
        (lambda goals: goals[0].pop("source_span_start"),
         "canonical_customer_goal_schema_invalid"),
        (lambda goals: goals[0].pop("source_text_sha256"),
         "canonical_customer_goal_schema_invalid"),
        (lambda goals: goals[0].update(schema_version="forged"),
         "customer_goal_identity_schema_invalid"),
        (lambda goals: goals[0].update(source_turn_uid="turn-" + "f" * 20),
         "customer_goal_source_turn_uid_invalid"),
        (lambda goals: goals[0].update(source_text_sha256="0" * 64),
         "customer_goal_source_text_digest_invalid"),
    ],
)
def test_canonical_goal_provenance_is_revalidated(mutation, reason):
    message = "material request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_raw_goal(source_text=message)],
        message=message,
    )
    assert status == "valid"
    assert diagnostics == []
    mutation(goals)

    valid, reasons = service._validate_canonical_customer_goals(
        goals,
        message=message,
    )

    assert valid is False
    assert reason in reasons


def test_digest_from_another_message_is_rejected():
    message = "material request"
    goals, _, _ = service._sanitize_customer_goals(
        [_raw_goal(source_text=message)],
        message=message,
    )
    other_goals, _, _ = service._sanitize_customer_goals(
        [_raw_goal(source_text="different request")],
        message="different request",
    )
    goals[0]["source_span_sha256"] = other_goals[0][
        "source_span_sha256"
    ]

    valid, reasons = service._validate_canonical_customer_goals(
        goals,
        message=message,
    )

    assert valid is False
    assert reasons == ["customer_goal_source_digest_invalid"]


def test_duplicate_raw_goal_is_diagnostic_not_silent_success():
    message = "material request"
    goal = _raw_goal(source_text=message)

    goals, status, diagnostics = service._sanitize_customer_goals(
        [goal, copy.deepcopy(goal)],
        message=message,
    )

    assert status == "invalid"
    assert diagnostics == ["duplicate_resolved_provenance"]
    assert goals == []


def test_same_provenance_with_different_classification_fails_closed():
    message = "property request"
    canonical = _raw_goal(source_text=message)
    unmapped = _raw_goal(
        source_text=message,
        claim_type_status="unmapped",
        claim_type="",
        semantic_key="different_interpretation",
        attribute_key="different_attribute",
    )

    goals, status, diagnostics = service._sanitize_customer_goals(
        [canonical, unmapped],
        message=message,
    )

    assert goals == []
    assert status == "invalid"
    assert diagnostics == ["duplicate_resolved_provenance"]


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, payload):
        self.choices = [
            _FakeChoice(json.dumps(payload, ensure_ascii=False))
        ]


class _FakeClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None

    def create_chat_completion(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResponse(self.payload)


def test_turn_understanding_payload_uses_server_candidates_without_product_data(
    monkeypatch,
):
    message = "material request"
    client = _FakeClient(
        _llm_result([_raw_goal(source_text=message)])
    )
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [],
    )

    result = service._classify_with_llm(
        {
            "resolved_product": {"sku_id": "private-product"},
            "product_name": "private product name",
            "product_candidates": [{"sku_id": "private-product"}],
            "order_id": "private-order",
            "canonical_fact_type_allowlist": ["forged_type"],
            "turn_understanding_owner": "public_request",
        },
        message,
        "product_question",
    )

    payload = json.loads(client.kwargs["messages"][1]["content"])
    assert result is not None
    assert "canonical_fact_type_candidates" in payload
    assert {
        item["fact_type_id"]
        for item in payload["canonical_fact_type_candidates"]
    } == {
        canonical_material_composition_claim_type(fact_type)
        for fact_type in service.FACT_TYPE_LABELS
    }
    assert "resolved_product" not in payload
    assert "product_name" not in payload
    assert "product_candidates" not in payload
    assert "has_order_identifier" not in payload
    assert "canonical_fact_type_allowlist" not in payload
    assert "turn_understanding_owner" not in payload
