from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.model_first_answer_composer_service import (
    COMPOSER_DECISION_INPUT_OWNER,
    COMPOSER_DECISION_INPUT_SCHEMA,
    ModelFirstAnswerComposerService,
)


_HELPERS_PATH = Path(__file__).with_name(
    "test_model_first_answer_composer_service.py"
)
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "_composer_test_helpers",
    _HELPERS_PATH,
)
assert _HELPERS_SPEC is not None
assert _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_response = _HELPERS._response
_bounded_inference_response = _HELPERS._bounded_inference_response
_dependency_response = _HELPERS._dependency_response
_compose = _HELPERS._compose
_valid_payload = _HELPERS._valid_payload
_DOMAIN_PACK_HASH = _HELPERS._DOMAIN_PACK_HASH


def _decision_input(
    response: dict | None = None,
) -> dict:
    source = deepcopy(response or _response())
    value, reason = (
        ModelFirstAnswerComposerService.build_composer_decision_input(
            source,
            customer_message=str(
                source["minimal_decision_context"].get(
                    "customer_goal"
                )
                or ""
            ),
        )
    )
    assert reason == ""
    assert value["schema_version"] == COMPOSER_DECISION_INPUT_SCHEMA
    assert value["owner"] == COMPOSER_DECISION_INPUT_OWNER
    return value


@pytest.mark.parametrize(
    ("injected_field", "injected_value"),
    [
        ("full_response", {"can_send": True}),
        ("copilot_context", {"retrieved_chunks": ["private"]}),
        ("trace", {"nodes": ["private"]}),
    ],
)
def test_decision_input_excludes_full_parent_containers(
    injected_field,
    injected_value,
):
    response = _response()
    response[injected_field] = injected_value

    decision_input = _decision_input(response)
    serialized = json.dumps(decision_input, ensure_ascii=False)

    assert injected_field not in decision_input
    assert "retrieved_chunks" not in serialized
    assert '"nodes"' not in serialized


def test_decision_input_excludes_raw_product_order_and_customer_identity():
    response = _response()
    context = response["minimal_decision_context"]
    context["product_identity"].update({
        "sku_code": "SKU-RAW-123",
        "i_id": "IID-RAW-456",
        "product_id": "PRODUCT-RAW-789",
    })
    context["order_identity"] = {"order_id": "ORDER-RAW-123"}
    context["customer_identity"] = {"phone": "13800138000"}

    serialized = json.dumps(_decision_input(response), ensure_ascii=False)

    for forbidden in (
        "SKU-RAW-123",
        "IID-RAW-456",
        "PRODUCT-RAW-789",
        "ORDER-RAW-123",
        "13800138000",
        "order_identity",
        "customer_identity",
    ):
        assert forbidden not in serialized


def test_conversation_fact_cannot_gain_evidence_authority():
    response = _response()
    response["minimal_decision_context"][
        "recent_conversation_turns"
    ].append({
        "role": "assistant",
        "content": "Historical unsupported product statement.",
        "turn_index": 2,
        "facts": [{
            "evidence_uid": "history-fact",
            "content": "not admitted",
        }],
    })

    decision_input = _decision_input(response)
    serialized = json.dumps(decision_input, ensure_ascii=False)

    assert "Historical unsupported product statement." in serialized
    assert "history-fact" not in serialized
    assert "not admitted" not in serialized
    assert [
        row["evidence_uid"]
        for row in decision_input["admitted_evidence"]
    ] == ["ev-width"]


@pytest.mark.parametrize(
    "missing_field",
    ["owner", "source", "source_span_sha256", "source_text_sha256"],
)
def test_decision_input_rejects_goal_without_authoritative_provenance(
    missing_field,
):
    decision_input = _decision_input()
    decision_input["requested_claims"][0].pop(missing_field)

    reason = (
        ModelFirstAnswerComposerService
        .validate_composer_decision_input(decision_input)
    )

    assert reason in {
        "composer_decision_input_schema_invalid",
        "composer_goal_provenance_invalid",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["requested_claims"].append(
            deepcopy(value["requested_claims"][0])
        ),
        lambda value: value["claim_resolutions"][0].update({
            "goal_ref": "goal-unknown",
        }),
    ],
)
def test_decision_input_rejects_duplicate_or_unknown_goal_reference(
    mutation,
):
    decision_input = _decision_input()
    mutation(decision_input)

    _, reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert reason


def test_decision_input_rejects_stale_cross_goal_option():
    decision_input = _decision_input(_bounded_inference_response())
    option = decision_input["claim_resolutions"][0][
        "eligible_policy_options"
    ][0]
    option["applicable_goal_ref"] = "goal-material"

    _, reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert reason


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["admitted_evidence"][0].update({
            "admission_owner": "conversation_history",
        }),
        lambda value: value["admitted_evidence"][0].update({
            "identity_scope_refs": [{
                "namespace": "sku_code",
                "scope_ref": "raw-sku-value",
            }],
        }),
        lambda value: value["admitted_evidence"][0].update({
            "provenance": {"source_container": "pack"},
        }),
    ],
)
def test_decision_input_rejects_evidence_provenance_or_scope_mutation(
    mutation,
):
    decision_input = _decision_input()
    mutation(decision_input)

    reason = (
        ModelFirstAnswerComposerService
        .validate_composer_decision_input(decision_input)
    )

    assert reason == "composer_evidence_provenance_invalid"


def test_decision_input_rejects_pack_hash_mutation():
    decision_input = _decision_input(_bounded_inference_response())
    decision_input["trusted_domain_policy_context"][
        "pack_content_sha256"
    ] = "0" * 64

    _, reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert reason


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("option", "policy_ref", "domain-policy:unknown@1.0.0:intent:x"),
        ("option", "premise_evidence_refs", ["ev-unknown"]),
        ("option", "allowed_scope", "untrusted_scope"),
        ("option", "requested_risk", "high"),
        ("policy", "maximum_risk_level", "low"),
    ],
)
def test_decision_input_rejects_policy_premise_scope_or_risk_mutation(
    target,
    field,
    value,
):
    decision_input = _decision_input(_bounded_inference_response())
    if target == "option":
        row = decision_input["claim_resolutions"][0][
            "eligible_policy_options"
        ][0]
    else:
        row = decision_input["bounded_inference_policies"][0]
    row[field] = value

    _, reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert reason


def test_decision_input_keeps_dependency_out_of_renderable_clauses():
    material, reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(
            _decision_input(_dependency_response())
        )
    )

    assert reason == ""
    prompt = material["prompt_payload"]
    assert len(prompt["renderable_customer_goals"]) == 1
    assert len(prompt["supporting_dependencies"]) == 1
    assert prompt["supporting_dependencies"][0][
        "dependency_ref"
    ].startswith("dependency_")


def test_decision_input_keeps_service_media_and_context_out_of_facts():
    response = _dependency_response()
    context = response["minimal_decision_context"]
    context["service_actions"] = [{
        "action_uid": "action-1",
        "action_type": "check_order",
        "status": "proposed",
    }]
    context["media_candidates"] = [{
        "media_uid": "media-1",
        "media_type": "image",
        "status": "candidate",
    }]
    decision_input = _decision_input(response)

    assert {
        item["evidence_uid"]
        for item in decision_input["admitted_evidence"]
    } == {"ev-support"}
    assert decision_input["service_actions"]
    assert decision_input["media_candidates"]
    assert all(
        row.get("admission_owner") == "admitted_answer_context"
        for row in decision_input["admitted_evidence"]
    )


def test_decision_input_preserves_unmapped_goal_and_source_span():
    response = _response()
    goal = response["minimal_decision_context"]["requested_claims"][0]
    goal.update({
        "claim_type": "",
        "claim_type_status": "unmapped",
        "source_span_start": 17,
        "source_span_end": 29,
    })
    response["minimal_decision_context"]["claim_resolutions"][0].update({
        "claim_type": "",
        "claim_type_status": "unmapped",
    })

    decision_input = _decision_input(response)
    projected_goal = decision_input["requested_claims"][0]

    assert projected_goal["claim_type_status"] == "unmapped"
    assert projected_goal["source_span_start"] == 17
    assert projected_goal["source_span_end"] == 29


def test_decision_input_privacy_projection_is_idempotent():
    decision_input = _decision_input()

    projected = (
        ModelFirstAnswerComposerService
        ._privacy_project_decision_value(decision_input)
    )

    assert projected == decision_input
    assert (
        ModelFirstAnswerComposerService
        ._privacy_project_decision_value(projected)
    ) == decision_input


def test_decision_input_preserves_controlled_refs_and_hashes():
    decision_input = _decision_input(_bounded_inference_response())
    option = decision_input["claim_resolutions"][0][
        "eligible_policy_options"
    ][0]

    assert option["policy_ref"].startswith("domain-policy:")
    assert "@" in option["policy_ref"]
    assert option["pack_content_sha256"] == _DOMAIN_PACK_HASH
    assert decision_input["trusted_domain_policy_context"][
        "pack_content_sha256"
    ] == _DOMAIN_PACK_HASH


def test_decision_input_projects_free_text_pii_without_damaging_facts():
    response = _response()
    context = response["minimal_decision_context"]
    context["customer_goal"] = (
        "Material PP for bedroom storage; call 13800138000, "
        "email buyer@example.com, order 33116082254651279, "
        "see https://example.com/item?token=secret."
    )
    context["admitted_evidence"][0]["content"] = (
        "Material is PP and width is 80 cm."
    )

    serialized = json.dumps(_decision_input(response), ensure_ascii=False)

    for raw_value in (
        "13800138000",
        "buyer@example.com",
        "33116082254651279",
        "token=secret",
    ):
        assert raw_value not in serialized
    assert "Material is PP and width is 80 cm." in serialized
    assert "bedroom storage" in serialized
    assert "_REDACTED" in serialized


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown_field": True}),
        lambda value: value["requested_claims"][0].update({
            "unknown_field": True,
        }),
        lambda value: value["admitted_evidence"][0].update({
            "unknown_field": True,
        }),
    ],
)
def test_decision_input_unknown_fields_fail_closed(mutation):
    decision_input = _decision_input()
    mutation(decision_input)

    reason = (
        ModelFirstAnswerComposerService
        .validate_composer_decision_input(decision_input)
    )

    assert reason == "composer_decision_input_schema_invalid"


def test_decision_input_cannot_change_can_send():
    decision_input = _decision_input()
    decision_input["can_change_can_send"] = True

    reason = (
        ModelFirstAnswerComposerService
        .validate_composer_decision_input(decision_input)
    )

    assert reason == "composer_decision_input_authority_invalid"


def test_decision_input_preserves_existing_ordering_under_input_reversal():
    first = _bounded_inference_response()
    second = deepcopy(first)
    context = second["minimal_decision_context"]
    context["requested_claims"].reverse()
    context["claim_resolutions"].reverse()
    context["admitted_evidence"].reverse()
    context["bounded_inference_policies"].reverse()

    first_material, first_reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(
            _decision_input(first)
        )
    )
    second_material, second_reason = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(
            _decision_input(second)
        )
    )

    assert first_reason == second_reason == ""
    assert first_material["messages"] == second_material["messages"]
    assert first_material["customer_goals"] == second_material[
        "customer_goals"
    ]
    assert first_material["offered_option_bindings"] == second_material[
        "offered_option_bindings"
    ]


def test_decision_input_path_keeps_fake_provider_to_one_call():
    _, result, client = _compose(_valid_payload())

    assert result["status"] == "accepted"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["model_call_count"] == 1
