from __future__ import annotations

import importlib.util
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.model_first_answer_composer_service import (
    COMPOSER_PRIVACY_DIAGNOSTICS_MAX_DIFFS,
    COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA,
    ModelFirstAnswerComposerService,
    _structured_privacy_diff,
)


_HELPERS_PATH = Path(__file__).with_name(
    "test_model_first_answer_composer_service.py"
)
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "_composer_privacy_diagnostic_helpers",
    _HELPERS_PATH,
)
assert _HELPERS_SPEC is not None
assert _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_Client = _HELPERS._Client
_response = _HELPERS._response
_valid_payload = _HELPERS._valid_payload
_with_policy_selection_fields = _HELPERS._with_policy_selection_fields


@pytest.fixture(autouse=True)
def diagnostic_hmac_key(monkeypatch):
    monkeypatch.setenv(
        "COPILOT_FORMAL_KB_AUDIT_HMAC_KEY",
        "diagnostics-test-key",
    )


def _compose(*, sink=None, response=None, payload=None, client=None):
    active_client = client or _Client(
        _with_policy_selection_fields(payload or _valid_payload())
    )
    updated, result = ModelFirstAnswerComposerService().compose(
        deepcopy(response or _response()),
        customer_message="current question",
        client=active_client,
        privacy_diagnostics_sink=sink,
    )
    return updated, result, active_client


def _single_diff(first, second, *, validated=True):
    total, retained, categories = _structured_privacy_diff(
        first,
        second,
        provenance_validated=validated,
    )
    assert total >= 1
    assert retained
    return retained[0], categories


def test_diagnostics_are_default_disabled_and_not_returned():
    updated, result, client = _compose()

    serialized = json.dumps(
        {"updated": updated, "result": result, "messages": client.messages},
        ensure_ascii=False,
    )
    assert COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA not in serialized


def test_d1_equals_d2_records_one_safe_invocation():
    sink = {}

    _, result, client = _compose(sink=sink)

    assert result["status"] == "accepted"
    assert sink["schema_version"] == COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA
    assert sink["decision_input_build_attempted"] is True
    assert sink["decision_input_build_completed"] is True
    assert sink["d1_generated"] is True
    assert sink["d2_generated"] is True
    assert sink["privacy_projection_equal"] is True
    assert sink["diff_total_count"] == 0
    assert sink["provider_material_completed"] is True
    assert sink["transport_forwarded"] is True
    assert sink["stage_reached"] == "completed"
    assert client.call_count == 1


def test_scalar_difference_is_structured_and_hashed():
    diff, categories = _single_diff({"flag": 1}, {"flag": 2})

    assert categories == {"scalar_changed": 1}
    assert diff["json_path"].startswith("$.key_")
    assert "flag" not in diff["json_path"]
    assert diff["field_role"] == "integer"
    assert diff["d1_value_sha256"] != diff["d2_value_sha256"]
    assert "d1_value" not in diff
    assert "d2_value" not in diff


@pytest.mark.parametrize(
    ("first", "second", "category"),
    [
        ({}, {"status": "valid"}, "object_key_changed"),
        ({"status": "valid"}, {}, "object_key_changed"),
        ({"status": "valid"}, {"status": ["valid"]}, "type_changed"),
        ({"items": [1]}, {"items": [1, 2]}, "array_length_changed"),
        ({"items": [1, 2]}, {"items": [2, 1]}, "array_order_changed"),
        (
            {"provenance": {"owner": "one"}},
            {"provenance": {"owner": "one", "source_stage": "two"}},
            "object_key_changed",
        ),
    ],
)
def test_structural_mutations_have_distinct_categories(
    first,
    second,
    category,
):
    total, retained, categories = _structured_privacy_diff(
        first,
        second,
        provenance_validated=True,
    )

    assert total >= 1
    assert retained
    assert categories.get(category, 0) >= 1


def test_object_order_only_is_distinguished_from_value_change():
    first = {"alpha": 1, "beta": 2}
    second = {"beta": 2, "alpha": 1}

    diff, categories = _single_diff(first, second)

    assert categories == {"canonical_order_only": 1}
    assert diff["projection_action_category"] == "canonical_order_only"


def test_unicode_difference_records_length_and_hash_only():
    raw_value = "sensitive-unicode-value"
    diff, _ = _single_diff(
        {"customer_goal": raw_value},
        {"customer_goal": "projected-value"},
    )

    serialized = json.dumps(diff, ensure_ascii=False)
    assert diff["field_role"] == "free_text"
    assert diff["d1_length_or_count"] == len(raw_value)
    assert raw_value not in serialized


def test_first_projection_removes_pii_and_second_projection_is_stable():
    response = _response()
    context = response["minimal_decision_context"]
    raw_values = (
        "13800138000",
        "buyer@example.com",
        "33116082254651279",
        "https://example.com/private",
    )
    context["customer_goal"] = " ".join(raw_values)
    sink = {}

    decision_input, reason = (
        ModelFirstAnswerComposerService.build_composer_decision_input(
            response,
            customer_message=context["customer_goal"],
            privacy_diagnostics_sink=sink,
        )
    )

    assert reason == ""
    assert sink["privacy_projection_equal"] is True
    serialized_input = json.dumps(decision_input, ensure_ascii=False)
    serialized_sink = json.dumps(sink, ensure_ascii=False)
    for raw_value in raw_values:
        assert raw_value not in serialized_input
        assert raw_value not in serialized_sink


def test_already_projected_text_remains_idempotent():
    response = _response()
    response["minimal_decision_context"]["customer_goal"] = (
        "[PHONE_REDACTED] [EMAIL_REDACTED]"
    )
    sink = {}

    _, reason = ModelFirstAnswerComposerService.build_composer_decision_input(
        response,
        customer_message="projected",
        privacy_diagnostics_sink=sink,
    )

    assert reason == ""
    assert sink["privacy_projection_equal"] is True


@pytest.mark.parametrize(
    ("field_name", "first", "expected_role", "expected_trust"),
    [
        ("goal_ref", "goal-width", "controlled_goal_ref", "controlled_goal_ref"),
        ("claim_uid", "claim-width", "controlled_claim_ref", "controlled_claim_ref"),
        ("evidence_uid", "ev-width", "controlled_evidence_ref", "controlled_evidence_ref"),
        (
            "policy_ref",
            "domain-policy:handling@v1",
            "controlled_policy_ref",
            "controlled_policy_ref",
        ),
        ("pack_ref", "pack-safe-v1", "controlled_pack_ref", "controlled_pack_ref"),
    ],
)
def test_valid_controlled_reference_roles_are_generic(
    field_name,
    first,
    expected_role,
    expected_trust,
):
    diff, _ = _single_diff(
        {field_name: first},
        {field_name: f"changed-{first}"},
    )

    assert diff["field_role"] == expected_role
    assert diff["trusted_reference_class"] == expected_trust


@pytest.mark.parametrize(
    "forged_ref",
    [
        "[FORGED_REFERENCE]",
        "buyer@example.com",
        "33116082254651279",
    ],
)
def test_forged_controlled_references_are_not_marked_trusted(forged_ref):
    diff, _ = _single_diff(
        {"goal_ref": forged_ref},
        {"goal_ref": "changed"},
    )

    assert diff["field_role"] == "controlled_goal_ref"
    assert diff["trusted_reference_class"] == "untrusted_reference"


@pytest.mark.parametrize(
    ("field_name", "expected_role"),
    [
        ("source_text_sha256", "source_text_hash"),
        ("pack_content_sha256", "canonical_hash"),
    ],
)
def test_structured_hash_roles_require_valid_sha256(field_name, expected_role):
    first = "a" * 64
    second = "b" * 64

    diff, _ = _single_diff(
        {field_name: first},
        {field_name: second},
    )

    assert diff["field_role"] == expected_role
    assert diff["trusted_reference_class"] == expected_role


def test_evidence_and_goal_provenance_roles_are_observable_without_values():
    first = {
        "requested_claims": [{
            "owner": "turn_understanding_owner",
            "source_stage": "query_fact_type_classifier",
        }],
        "admitted_evidence": [{
            "admission_owner": "admitted_answer_context",
        }],
    }
    second = deepcopy(first)
    second["requested_claims"][0]["owner"] = "changed-owner"
    second["admitted_evidence"][0]["admission_owner"] = "changed-owner"

    total, retained, _ = _structured_privacy_diff(
        first,
        second,
        provenance_validated=True,
    )

    assert total == 2
    assert {item["field_role"] for item in retained} == {
        "owner_provenance"
    }
    assert all(
        item["owner_provenance_validation_status"]
        == "validated_before_privacy_idempotence"
        for item in retained
    )


def test_unknown_field_role_hashes_hostile_path_and_never_retains_value():
    hostile_key = "buyer@example.com"
    hostile_value = "raw-private-value"

    diff, _ = _single_diff(
        {hostile_key: hostile_value},
        {hostile_key: "changed-private-value"},
    )

    serialized = json.dumps(diff, ensure_ascii=False)
    assert diff["field_role"] == "unknown"
    assert hostile_key not in serialized
    assert hostile_value not in serialized
    assert diff["json_path"].startswith("$.key_")


def test_diagnostics_diff_retention_is_bounded():
    first = {f"field_{index}": index for index in range(80)}
    second = {f"field_{index}": index + 1 for index in range(80)}

    total, retained, _ = _structured_privacy_diff(
        first,
        second,
        provenance_validated=False,
    )

    assert total == 80
    assert len(retained) == COMPOSER_PRIVACY_DIAGNOSTICS_MAX_DIFFS


class _HostileSink(dict):
    def clear(self):
        raise RuntimeError("sink failure must remain isolated")


def test_sink_failure_does_not_change_composer_result_or_calls():
    baseline_updated, baseline_result, baseline_client = _compose()
    updated, result, client = _compose(sink=_HostileSink())

    assert updated == baseline_updated
    assert result == baseline_result
    assert client.messages == baseline_client.messages
    assert client.call_count == baseline_client.call_count == 1


def test_concurrent_requests_keep_diagnostics_isolated():
    def run(index):
        response = _response()
        response["minimal_decision_context"]["customer_goal"] = (
            f"concurrent-question-{index}"
        )
        sink = {}
        _, result, client = _compose(sink=sink, response=response)
        return sink, result["status"], client.call_count

    with ThreadPoolExecutor(max_workers=6) as executor:
        rows = list(executor.map(run, range(12)))

    aliases = {row[0]["request_alias"] for row in rows}
    assert len(aliases) == 12
    assert all(row[1] == "accepted" for row in rows)
    assert all(row[2] == 1 for row in rows)
    assert all(row[0]["diff_total_count"] == 0 for row in rows)


def test_pre_provider_privacy_failure_records_path_without_transport(
    monkeypatch,
):
    from app.services import canonical_conversation_turn_service as projector

    original = projector.project_value_for_external_model

    def non_idempotent(value, *, field_name=""):
        if value == "diagnostic-trigger":
            return "diagnostic-trigger-projected"
        if value == "diagnostic-trigger-projected":
            return "diagnostic-trigger-projected-again"
        return original(value, field_name=field_name)

    monkeypatch.setattr(
        projector,
        "project_value_for_external_model",
        non_idempotent,
    )
    response = _response()
    response["minimal_decision_context"]["customer_goal"] = (
        "diagnostic-trigger"
    )
    sink = {}

    _, result, client = _compose(sink=sink, response=response)

    assert result["rejection_reason"] == (
        "composer_decision_input_privacy_invalid"
    )
    assert client.call_count == 0
    assert sink["privacy_projection_equal"] is False
    assert sink["first_diff_path"] == "$.customer_goal"
    assert sink["diffs"][0]["field_role"] == "free_text"
    assert sink["provider_material_attempted"] is False
    assert sink["transport_forwarded"] is False
    serialized = json.dumps(sink, ensure_ascii=False)
    assert "diagnostic-trigger" not in serialized


class _InterceptClient(_Client):
    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise RuntimeError("transport intercepted")


def test_provider_boundary_intercept_does_not_retry_or_repair():
    sink = {}
    client = _InterceptClient(_valid_payload())

    _, result, active_client = _compose(sink=sink, client=client)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == "formal_llm_error:RuntimeError"
    assert active_client.call_count == 1
    assert sink["transport_attempted"] is True
    assert sink["transport_forwarded"] is False


@pytest.mark.parametrize(
    "response_mutation",
    [
        lambda response: None,
        lambda response: response["minimal_decision_context"][
            "requested_claims"
        ][0].update({"owner": "invalid-owner"}),
    ],
)
def test_diagnostics_off_on_behavior_is_exactly_equivalent(
    response_mutation,
):
    first_response = _response()
    response_mutation(first_response)
    second_response = deepcopy(first_response)
    first_client = _Client(_with_policy_selection_fields(_valid_payload()))
    second_client = _Client(_with_policy_selection_fields(_valid_payload()))

    baseline_updated, baseline_result, _ = _compose(
        response=first_response,
        client=first_client,
    )
    sink = {}
    observed_updated, observed_result, _ = _compose(
        sink=sink,
        response=second_response,
        client=second_client,
    )

    assert observed_updated == baseline_updated
    assert observed_result == baseline_result
    assert second_client.kwargs == first_client.kwargs
    assert second_client.messages == first_client.messages
    assert second_client.call_count == first_client.call_count
    assert sink["can_change_can_send"] is False
    assert sink["can_change_model_call_count"] is False


def test_sink_none_performs_zero_diagnostic_work(monkeypatch):
    import app.services.model_first_answer_composer_service as composer_module

    def unexpected(*_args, **_kwargs):
        raise AssertionError("diagnostics_must_not_run_without_sink")

    for name in (
        "_privacy_diagnostic_base",
        "_privacy_diagnostic_initialize",
        "_privacy_diagnostic_update",
        "_privacy_diagnostic_finish",
        "_privacy_diagnostic_alias",
        "_diagnostic_value_sha256",
        "_structured_privacy_diff",
    ):
        monkeypatch.setattr(composer_module, name, unexpected)
    monkeypatch.setattr(
        ModelFirstAnswerComposerService,
        "_record_decision_input_privacy_diagnostics",
        unexpected,
    )

    updated, result, client = _compose()

    assert result["status"] == "accepted"
    assert updated["can_send"] is False
    assert client.call_count == 1


@pytest.mark.parametrize(
    "raw_value",
    [
        "1380013",
        "ORD-7281",
        "CUST-91",
        "728190",
        "A7B91C",
        "客户甲",
        "goal-1",
        "evidence-1",
        "policy-1",
        "run-1",
        "turn-1",
    ],
)
def test_short_identifiers_use_existing_keyed_alias_owner(raw_value):
    from app.services.model_first_answer_composer_service import (
        _privacy_diagnostic_alias,
    )

    alias = _privacy_diagnostic_alias("diagnostic", raw_value)

    assert alias.startswith("diagnostic_")
    assert raw_value not in alias
    assert alias == _privacy_diagnostic_alias("diagnostic", raw_value)


def test_keyed_alias_changes_with_key_and_does_not_collide(monkeypatch):
    from app.services.model_first_answer_composer_service import (
        _privacy_diagnostic_alias,
    )

    first = _privacy_diagnostic_alias("diagnostic", "CUST-A")
    second = _privacy_diagnostic_alias("diagnostic", "CUST-B")
    monkeypatch.setenv(
        "COPILOT_FORMAL_KB_AUDIT_HMAC_KEY",
        "diagnostics-test-key-rotated",
    )
    rotated = _privacy_diagnostic_alias("diagnostic", "CUST-A")

    assert first != second
    assert first != rotated


def test_missing_or_untrusted_hmac_key_fails_closed(monkeypatch):
    from app.services.model_first_answer_composer_service import (
        _privacy_diagnostic_alias,
    )

    monkeypatch.delenv(
        "COPILOT_FORMAL_KB_AUDIT_HMAC_KEY",
        raising=False,
    )
    monkeypatch.delenv("COPILOT_GOLD_SET_HMAC_KEY", raising=False)
    monkeypatch.setenv("COPILOT_LLM_API_KEY", "not-an-alias-key")

    with pytest.raises(ValueError, match="diagnostic_alias_key_required"):
        _privacy_diagnostic_alias("diagnostic", "CUST-A")


def test_unkeyed_sha_identity_is_realiased():
    from app.services.model_first_answer_composer_service import (
        _privacy_diagnostic_alias,
    )

    raw_sha = hashlib.sha256(b"customer-identity").hexdigest()
    alias = _privacy_diagnostic_alias("customer", raw_sha)

    assert alias.startswith("customer_")
    assert raw_sha not in alias


def test_unknown_string_and_wrong_path_sha_are_not_persisted():
    raw_value = "short-private-id"
    wrong_path_sha = "a" * 64
    first = {
        "unknown_customer_field": raw_value,
        "customer_id": wrong_path_sha,
    }
    second = {
        "unknown_customer_field": "changed-private-id",
        "customer_id": "b" * 64,
    }

    _total, retained, _categories = _structured_privacy_diff(
        first,
        second,
        provenance_validated=False,
    )
    serialized = json.dumps(retained, ensure_ascii=False)

    assert raw_value not in serialized
    assert wrong_path_sha not in serialized
    assert "unknown_customer_field" not in serialized
    assert "customer_id" not in serialized


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"customer_id": ""}, {"customer_id": None}),
        ({"status": "accepted"}, {"status": "not-an-allowed-status"}),
    ],
)
def test_empty_null_and_enum_mutations_do_not_persist_raw_values(
    first,
    second,
):
    _total, retained, _categories = _structured_privacy_diff(
        first,
        second,
        provenance_validated=False,
    )
    serialized = json.dumps(retained, ensure_ascii=False)

    assert "not-an-allowed-status" not in serialized
    assert "customer_id" not in serialized


def test_structured_sha_requires_validated_provenance_to_be_trusted():
    first = "a" * 64
    second = "b" * 64

    diff, _ = _single_diff(
        {"source_text_sha256": first},
        {"source_text_sha256": second},
        validated=False,
    )
    serialized = json.dumps(diff, ensure_ascii=False)

    assert diff["field_role"] == "source_text_hash"
    assert diff["trusted_reference_class"] == "untrusted_reference"
    assert first not in serialized
    assert second not in serialized


def test_missing_hmac_key_diagnostics_do_not_change_composer(monkeypatch):
    baseline_updated, baseline_result, baseline_client = _compose()
    monkeypatch.delenv(
        "COPILOT_FORMAL_KB_AUDIT_HMAC_KEY",
        raising=False,
    )
    monkeypatch.delenv("COPILOT_GOLD_SET_HMAC_KEY", raising=False)
    sink: dict = {}

    updated, result, client = _compose(sink=sink)

    assert updated == baseline_updated
    assert result == baseline_result
    assert client.messages == baseline_client.messages
    assert client.call_count == baseline_client.call_count == 1
    assert sink["request_alias"] == ""
    assert sink["turn_alias"] == ""
    assert sink["diagnostic_error"] in {
        "diagnostic_alias_unavailable",
        "privacy_diff_generation_failed",
    }
