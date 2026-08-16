import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.llm.client import LLMClient
from app.services import semantic_fact_type_service as service


MESSAGE = "这款材质是什么，能不能保证摔不坏？"


def _goal(
    *,
    source_text: str,
    status: str = "canonical",
    claim_type: str = "material",
    semantic_key: str = "",
    **overrides,
) -> dict:
    result = {
        "goal_kind": "customer_goal",
        "claim_type_status": status,
        "claim_type": claim_type,
        "attribute_key": "material",
        "semantic_key": semantic_key,
        "policy_intent_ref": "",
        "source_text": source_text,
    }
    result.update(overrides)
    return result


def _valid_payload() -> dict:
    return {
        "goals": [
            _goal(source_text="这款材质是什么"),
            _goal(
                source_text="能不能保证摔不坏",
                status="unmapped",
                claim_type="",
                semantic_key="absolute_drop_durability",
                attribute_key="drop_durability",
            ),
        ],
    }


class _FakeHTTPError(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        super().__init__(detail)
        self.status_code = status_code


class _FakeMessage:
    def __init__(
        self,
        content=None,
        *,
        reasoning_content=None,
        reasoning_details=None,
    ):
        self.content = content
        self.reasoning_content = reasoning_content
        self.reasoning_details = reasoning_details


class _FakeChoice:
    def __init__(
        self,
        content=None,
        *,
        finish_reason="stop",
        include_message=True,
        reasoning_content=None,
    ):
        self.finish_reason = finish_reason
        if include_message:
            self.message = _FakeMessage(
                content,
                reasoning_content=reasoning_content,
            )


class _FakeResponse:
    def __init__(self, choices):
        self.choices = choices


class _FakeClient:
    api_key = "not-a-real-key"
    api_base = "https://provider.invalid/openai/v1?private=true"
    model = "test-model"
    provider_name = "test-provider"

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0
        self.kwargs = None

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _response_for_payload(payload: dict) -> _FakeResponse:
    return _FakeResponse([
        _FakeChoice(json.dumps(payload, ensure_ascii=False)),
    ])


def _run(monkeypatch, outcome, *, message=MESSAGE):
    client = _FakeClient(outcome)
    diagnostics = {"untrusted": "must be removed"}
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [],
    )
    result = service._classify_with_llm(
        {},
        message,
        "product_question",
        diagnostics_sink=diagnostics,
    )
    return result, diagnostics, client


def _reason_codes(diagnostics: dict) -> list[str]:
    return [
        item["reason_code"]
        for section in (
            "schema_validation",
            "provenance_validation",
        )
        for item in diagnostics[section]["violations"]
    ]


def test_minimal_provider_schema_keeps_server_owned_fields_out():
    schema = service.MINIMAL_PROVIDER_OUTPUT_SCHEMA
    goal_schema = schema["properties"]["goals"]["items"]

    assert set(schema["properties"]) == {"goals"}
    assert schema["required"] == ["goals"]
    assert schema["additionalProperties"] is False
    assert set(goal_schema["properties"]) == {
        "goal_kind",
        "claim_type_status",
        "claim_type",
        "attribute_key",
        "subject_scope",
        "semantic_key",
        "policy_intent_ref",
        "source_text",
        "continued_from",
    }
    assert set(goal_schema["required"]) == (
        set(goal_schema["properties"])
        - {"semantic_key", "continued_from", "subject_scope"}
    )
    assert goal_schema["additionalProperties"] is False
    for server_field in {
        "owner",
        "schema_version",
        "goal_ref",
        "conversation_ref",
        "source_turn_uid",
        "source_span_start",
        "source_span_end",
        "source_span_sha256",
        "source_text_sha256",
        "confidence",
        "status",
        "diagnostics",
    }:
        assert server_field not in goal_schema["properties"]


def test_minimal_prompt_does_not_request_server_owned_output_fields():
    prompt = service.SYSTEM_PROMPT

    assert '"goals"' in prompt
    assert '"source_text"' in prompt
    assert '"continued_from"' in prompt
    for forbidden_output in {
        '"owner"',
        '"schema_version"',
        '"goal_ref"',
        '"conversation_ref"',
        '"source_turn_uid"',
        '"source_span_start"',
        '"source_span_end"',
        '"source_span_sha256"',
        '"source_text_sha256"',
        '"confidence"',
        '"diagnostics"',
    }:
        assert forbidden_output not in prompt


def test_valid_canonical_and_unmapped_output_passes_with_one_call(monkeypatch):
    result, diagnostics, client = _run(
        monkeypatch,
        _response_for_payload(_valid_payload()),
    )

    assert result is not None
    assert diagnostics["status"] == "passed"
    assert diagnostics["stage"] == "understanding_built"
    assert diagnostics["reason_code"] == ""
    assert diagnostics["model_call_count"] == client.calls == 1
    assert diagnostics["retry_count"] == 0
    assert diagnostics["json_repair_count"] == 0
    assert diagnostics["response_envelope"] == "raw_json"
    assert diagnostics["envelope_unwrap_count"] == 0
    assert diagnostics["json_parse_success"] is True
    assert diagnostics["schema_success"] is True
    assert diagnostics["response_content_length"] == (
        diagnostics["completion"]["content_char_count"]
    )
    assert diagnostics["response_content_sha256"] == (
        diagnostics["completion"]["content_sha256"]
    )
    assert diagnostics["schema_validation"]["passed"] is True
    assert diagnostics["provenance_validation"]["passed"] is True
    assert client.kwargs["_single_attempt_no_repair"] is True
    assert "can_send" not in result
    assert diagnostics["can_change_can_send"] is False


def test_optional_semantic_metadata_counts_do_not_change_validity(monkeypatch):
    payload = _valid_payload()
    payload["goals"][0]["semantic_key"] = ""
    payload["goals"][1].pop("semantic_key")

    result, diagnostics, client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert result is not None
    assert diagnostics["status"] == "passed"
    assert diagnostics["optional_metadata"] == {
        "semantic_key_present_count": 0,
        "semantic_key_empty_count": 1,
        "semantic_key_missing_count": 1,
        "semantic_key_discarded_count": 0,
    }
    assert diagnostics["unmapped_metadata_contract_version"] == (
        service.UNMAPPED_METADATA_CONTRACT_VERSION
    )
    assert diagnostics["model_call_count"] == client.calls == 1
    assert diagnostics["retry_count"] == 0
    assert diagnostics["json_repair_count"] == 0


@pytest.mark.parametrize(
    ("error", "reason_code", "status_code"),
    [
        (_FakeHTTPError(401, "secret https://private.invalid"), "provider_auth_error", 401),
        (_FakeHTTPError(402, "secret https://private.invalid"), "provider_quota_error", 402),
        (_FakeHTTPError(429, "secret https://private.invalid"), "provider_rate_limited", 429),
        (_FakeHTTPError(500, "secret https://private.invalid"), "provider_http_error", 500),
        (TimeoutError("secret timeout"), "provider_timeout", None),
        (ConnectionError("secret connection"), "provider_connection_error", None),
    ],
)
def test_provider_failures_have_safe_stable_categories(
    monkeypatch,
    error,
    reason_code,
    status_code,
):
    result, diagnostics, client = _run(monkeypatch, error)

    assert result is None
    assert diagnostics["stage"] == "provider_request"
    assert diagnostics["reason_code"] == reason_code
    assert diagnostics["provider"]["provider_error_category"] == reason_code
    assert diagnostics["provider"]["http_status"] == status_code
    assert diagnostics["model_call_count"] == client.calls == 1
    serialized = json.dumps(diagnostics, ensure_ascii=False)
    assert "private.invalid" not in serialized
    assert "secret" not in serialized


@pytest.mark.parametrize(
    ("outcome", "reason_code"),
    [
        (None, "completion_missing"),
        (_FakeResponse([]), "choices_missing"),
        (_FakeResponse([_FakeChoice(include_message=False)]), "message_missing"),
        (_FakeResponse([_FakeChoice("")]), "content_empty"),
        (
            _FakeResponse([
                _FakeChoice(
                    "",
                    reasoning_content="private chain of thought",
                ),
            ]),
            "reasoning_only_response",
        ),
        (
            _FakeResponse([
                _FakeChoice(
                    json.dumps(_valid_payload(), ensure_ascii=False),
                    finish_reason="length",
                ),
            ]),
            "response_truncated",
        ),
    ],
)
def test_completion_failures_are_distinct(monkeypatch, outcome, reason_code):
    result, diagnostics, client = _run(monkeypatch, outcome)

    assert result is None
    assert diagnostics["stage"] == "completion"
    assert diagnostics["reason_code"] == reason_code
    assert diagnostics["model_call_count"] == client.calls == 1
    assert diagnostics["completion"]["content_sha256"] == (
        "" if reason_code in {
            "completion_missing",
            "choices_missing",
            "message_missing",
            "content_empty",
            "reasoning_only_response",
        } else diagnostics["completion"]["content_sha256"]
    )


@pytest.mark.parametrize(
    ("content", "reason_code", "root_type"),
    [
        ("这不是 JSON", "free_text_response", ""),
        ('{"query_fact_type":', "json_decode_error", ""),
        ("[]", "json_root_not_object", "array"),
    ],
)
def test_format_failures_are_not_repaired(
    monkeypatch,
    content,
    reason_code,
    root_type,
):
    result, diagnostics, client = _run(
        monkeypatch,
        _FakeResponse([_FakeChoice(content)]),
    )

    assert result is None
    assert diagnostics["stage"] == "json_parse"
    assert diagnostics["reason_code"] == reason_code
    assert diagnostics["json_parse"]["root_type"] == root_type
    assert diagnostics["model_call_count"] == client.calls == 1
    assert diagnostics["json_repair_count"] == 0


@pytest.mark.parametrize(
    "render",
    [
        lambda body: f"```json\n{body}\n```",
        lambda body: f"```\n{body}\n```",
        lambda body: f"\n\t```json\n{body}\n```\n ",
    ],
)
def test_single_complete_json_fence_is_unwrapped_without_repair(
    monkeypatch,
    render,
):
    body = json.dumps(_valid_payload(), ensure_ascii=False)
    raw = render(body)

    result, diagnostics, client = _run(
        monkeypatch,
        _FakeResponse([_FakeChoice(raw)]),
    )

    assert result is not None
    assert diagnostics["response_envelope"] == "single_json_fence"
    assert diagnostics["envelope_unwrap_count"] == 1
    assert diagnostics["json_parse_success"] is True
    assert diagnostics["schema_success"] is True
    assert diagnostics["response_content_length"] == len(raw)
    assert diagnostics["response_content_sha256"] == (
        hashlib.sha256(raw.encode("utf-8")).hexdigest()
    )
    assert diagnostics["json_repair_count"] == 0
    assert diagnostics["retry_count"] == 0
    assert diagnostics["model_call_count"] == client.calls == 1


@pytest.mark.parametrize(
    ("content", "reason_code", "envelope"),
    [
        (
            "说明如下：\n```json\n{}\n```",
            "json_envelope_invalid",
            "invalid",
        ),
        (
            "```json\n{}\n```\n以上是结果",
            "json_envelope_invalid",
            "invalid",
        ),
        (
            "```json\n{}\n```\n```json\n{}\n```",
            "json_envelope_invalid",
            "invalid",
        ),
        (
            "```json\nnot-json\n```",
            "json_decode_error",
            "single_json_fence",
        ),
        (
            "```json\n{}",
            "json_envelope_invalid",
            "invalid",
        ),
        (
            "- result: {\"query_fact_type\": \"material\"}",
            "free_text_response",
            "invalid",
        ),
        (
            "result {\"query_fact_type\": \"material\"}",
            "free_text_response",
            "invalid",
        ),
        (
            "{'query_fact_type': 'material'}",
            "json_decode_error",
            "raw_json",
        ),
        (
            '{"query_fact_type": "material",}',
            "json_decode_error",
            "raw_json",
        ),
        (
            '{"query_fact_type": /* comment */ "material"}',
            "json_decode_error",
            "raw_json",
        ),
    ],
)
def test_invalid_json_envelopes_and_json_repairs_fail_closed(
    monkeypatch,
    content,
    reason_code,
    envelope,
):
    result, diagnostics, client = _run(
        monkeypatch,
        _FakeResponse([_FakeChoice(content)]),
    )

    assert result is None
    assert diagnostics["reason_code"] == reason_code
    assert diagnostics["response_envelope"] == envelope
    assert diagnostics["json_repair_count"] == 0
    assert diagnostics["retry_count"] == 0
    assert diagnostics["model_call_count"] == client.calls == 1


def test_top_level_missing_and_extra_fields_are_exact(monkeypatch):
    payload = {"unknown_private_field": "must not appear"}
    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert result is None
    assert diagnostics["reason_code"] == "top_level_field_missing"
    violations = diagnostics["schema_validation"]["violations"]
    assert {item["reason_code"] for item in violations} >= {
        "top_level_field_missing",
        "top_level_extra_field",
    }
    extra = next(
        item
        for item in violations
        if item["reason_code"] == "top_level_extra_field"
    )
    assert extra["json_pointer"] == "$.<extra>"
    assert extra["field_name"] == "<extra>"
    assert extra["required"] is False
    assert extra["extra"] is True
    assert len(extra["field_name_hash"]) == 16
    assert "unknown_private_field" not in json.dumps(
        diagnostics,
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda payload: payload.update(goals={}), "top_level_field_type_invalid"),
        (lambda payload: payload["goals"][0].pop("source_text"), "goal_field_missing"),
        (
            lambda payload: payload["goals"][0].update(
                unknown_field="secret"
            ),
            "goal_extra_field",
        ),
    ],
)
def test_goal_schema_failures_are_distinct(
    monkeypatch,
    mutation,
    reason_code,
):
    payload = _valid_payload()
    mutation(payload)
    _result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert reason_code in _reason_codes(diagnostics)


def test_top_level_type_failure_has_sanitized_field_shape(monkeypatch):
    raw = json.dumps({"goals": None}, ensure_ascii=False)
    result, diagnostics, _client = _run(
        monkeypatch,
        _FakeResponse([_FakeChoice(raw)]),
    )

    assert result is None
    violation = diagnostics["schema_validation"]["violations"][0]
    assert diagnostics["error_category"] == (
        "top_level_field_type_invalid"
    )
    assert violation == {
        "stage": "top_level_schema",
        "error_category": "top_level_field_type_invalid",
        "json_pointer": "$.goals",
        "field_name": "goals",
        "reason_code": "top_level_field_type_invalid",
        "expected_type": "array",
        "actual_type": "null",
        "expected_count": None,
        "actual_count": None,
        "field_name_hash": "",
        "required": True,
        "missing": False,
        "extra": False,
        "value_present": True,
        "array_item_count": None,
        "root_key_count": 1,
    }
    assert diagnostics["response_envelope"] == "raw_json"
    assert diagnostics["completion"]["finish_reason"] == "stop"
    assert diagnostics["response_content_length"] == len(raw)
    assert diagnostics["response_content_sha256"] == hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize(
    ("payload", "reason_code", "path", "actual_type"),
    [
        ({"goals": "not-an-array"}, "top_level_field_type_invalid", "$.goals", "string"),
        ({"goals": [None]}, "goal_not_object", "$.goals[0]", "null"),
        ({"goals": []}, "goal_count_invalid", "$.goals", "array"),
        (
            {"goals": [_goal(source_text="这款材质是什么", goal_kind=True)]},
            "goal_field_type_invalid",
            "$.goals[0].goal_kind",
            "boolean",
        ),
        (
            {"goals": [_goal(source_text="这款材质是什么", attribute_key=1)]},
            "goal_field_type_invalid",
            "$.goals[0].attribute_key",
            "number",
        ),
        (
            {"goals": [_goal(source_text="这款材质是什么", semantic_key=[])]},
            "goal_field_type_invalid",
            "$.goals[0].semantic_key",
            "array",
        ),
    ],
)
def test_minimal_schema_type_matrix_is_fail_closed(
    monkeypatch,
    payload,
    reason_code,
    path,
    actual_type,
):
    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert result is None
    violation = next(
        item
        for item in diagnostics["schema_validation"]["violations"]
        if item["reason_code"] == reason_code
        and item["json_pointer"] == path
    )
    assert violation["actual_type"] == actual_type
    assert violation["root_key_count"] == 1
    assert violation["array_item_count"] == (
        len(payload["goals"])
        if isinstance(payload.get("goals"), list)
        else None
    )


def test_previous_wide_provider_schema_is_rejected(monkeypatch):
    payload = _valid_payload()
    payload.update({
        "query_fact_type": "material",
        "confidence": 0.9,
        "risk_hint": "medium",
    })

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert result is None
    assert diagnostics["reason_code"] == "top_level_extra_field"
    assert {
        item["reason_code"]
        for item in diagnostics["schema_validation"]["violations"]
    } == {"top_level_extra_field"}


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (
            lambda goal: goal.update(
                claim_type_status="canonical",
                claim_type="",
            ),
            "canonical_claim_type_missing",
        ),
        (
            lambda goal: goal.update(
                claim_type_status="canonical",
                semantic_key="material_diagnostic",
            ),
            "canonical_with_semantic_key",
        ),
        (
            lambda goal: goal.update(
                claim_type_status="unmapped",
                claim_type="material",
                semantic_key="drop_durability",
            ),
            "unmapped_claim_type_not_empty",
        ),
        (
            lambda goal: goal.update(
                claim_type_status="unmapped",
                claim_type="",
                semantic_key="not valid",
            ),
            None,
        ),
        (
            lambda goal: goal.pop("claim_type_status"),
            "claim_type_status_missing",
        ),
        (
            lambda goal: goal.update(
                claim_type_status="other",
            ),
            "claim_type_status_invalid",
        ),
    ],
)
def test_known_unmapped_failures_are_attributed(
    monkeypatch,
    mutation,
    reason_code,
):
    payload = _valid_payload()
    mutation(payload["goals"][0])
    _result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    if reason_code is None:
        assert diagnostics["status"] == "passed"
        assert diagnostics["optional_metadata"][
            "semantic_key_discarded_count"
        ] == 1
    else:
        assert reason_code in _reason_codes(diagnostics)
        assert diagnostics["status"] == "failed"


@pytest.mark.parametrize(
    ("message", "unknown_claim_type", "attribute_key"),
    [
        ("Which fulfillment option applies?", "provider_fulfillment_option", "service_option"),
        ("Is this suitable for the intended setup?", "provider_suitability", "suitability"),
    ],
)
def test_unknown_canonical_customer_goal_preserves_only_source_bound_goal(
    monkeypatch,
    message,
    unknown_claim_type,
    attribute_key,
):
    payload = {
        "goals": [
            _goal(
                source_text=message,
                claim_type=unknown_claim_type,
                attribute_key=attribute_key,
            )
        ]
    }

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
        message=message,
    )

    assert result is not None
    assert result["goal_understanding_status"] == "valid"
    assert result["query_fact_type"] == ""
    assert len(result["customer_goals"]) == 1
    goal = result["customer_goals"][0]
    assert goal["goal_kind"] == "customer_goal"
    assert goal["claim_type_status"] == "unmapped"
    assert goal["claim_type"] == ""
    assert goal["policy_intent_ref"] == ""
    assert goal["claim_type_reason_code"] == "canonical_claim_type_unknown"
    assert goal["goal_summary"] == message
    assert goal["source_span_start"] == 0
    assert goal["source_span_end"] == len(message)
    assert goal["source_span_sha256"] == hashlib.sha256(
        message.encode("utf-8")
    ).hexdigest()
    assert diagnostics["status"] == "failed"
    assert diagnostics["schema_success"] is False
    assert diagnostics["reason_code"] == "canonical_claim_type_not_allowed"
    assert diagnostics["runtime_goal_continuity"] == {
        "status": "preserved_unmapped",
        "downgraded_goal_count": 1,
        "recovered_goal_can_create_fact": False,
        "can_change_can_send": False,
    }


def test_unknown_canonical_service_action_remains_blocked(monkeypatch):
    message = "Please perform the external service operation."
    payload = {
        "goals": [
            _goal(
                source_text=message,
                goal_kind="service_action",
                claim_type="provider_service_operation",
                attribute_key="service_operation",
            )
        ]
    }

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
        message=message,
    )

    assert result is None
    assert diagnostics["status"] == "failed"
    assert diagnostics["reason_code"] == "canonical_claim_type_not_allowed"


def test_media_request_with_fact_type_is_preserved_without_fact_authority(
    monkeypatch,
):
    message = "Please provide the relevant setup diagram."
    payload = {
        "goals": [
            _goal(
                source_text=message,
                goal_kind="media_request",
                claim_type="installation",
                attribute_key="",
            )
        ]
    }

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
        message=message,
    )

    assert result is not None
    assert result["goal_understanding_status"] == "valid"
    assert result["query_fact_type"] == ""
    assert len(result["customer_goals"]) == 1
    goal = result["customer_goals"][0]
    assert goal["goal_kind"] == "media_request"
    assert goal["claim_type_status"] == "unmapped"
    assert goal["claim_type"] == ""
    assert goal["policy_intent_ref"] == ""
    assert goal["claim_type_reason_code"] == (
        "media_request_canonical_claim_forbidden"
    )
    assert diagnostics["schema_success"] is True
    assert diagnostics["provenance_validation"]["passed"] is True


def test_non_fact_media_normalization_keeps_independent_fact_goal(
    monkeypatch,
):
    message = "What material is it, and please provide the setup diagram."
    payload = {
        "goals": [
            _goal(
                source_text="What material is it",
                claim_type="material",
                attribute_key="material",
            ),
            _goal(
                source_text="please provide the setup diagram",
                goal_kind="media_request",
                claim_type="installation",
                attribute_key="",
            ),
        ]
    }

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
        message=message,
    )

    assert result is not None
    assert result["goal_understanding_status"] == "valid"
    assert result["query_fact_type"] == "material"
    assert {
        (goal["goal_kind"], goal["claim_type_status"], goal["claim_type"])
        for goal in result["customer_goals"]
    } == {
        ("customer_goal", "canonical", "material"),
        ("media_request", "unmapped", ""),
    }
    assert diagnostics["runtime_goal_continuity"] == {
        "status": "preserved_non_fact_media_request",
        "downgraded_goal_count": 1,
        "recovered_goal_can_create_fact": False,
        "can_change_can_send": False,
    }


def test_noncanonical_spelling_of_known_fact_type_cannot_use_goal_continuity(
    monkeypatch,
):
    message = "What material is it?"
    payload = {
        "goals": [
            _goal(
                source_text=message,
                claim_type="MATERIAL",
                attribute_key="material",
            )
        ]
    }

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
        message=message,
    )

    assert result is None
    assert diagnostics["status"] == "failed"
    assert diagnostics["runtime_goal_continuity"]["status"] == "not_applied"


def test_unknown_canonical_goal_cannot_mask_another_schema_failure(monkeypatch):
    message = "Which option applies?"
    goal = _goal(
        source_text=message,
        claim_type="provider_option",
        attribute_key="option",
    )
    goal["untrusted_extra"] = "must fail"

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload({"goals": [goal]}),
        message=message,
    )

    assert result is None
    assert diagnostics["status"] == "failed"
    assert {
        item["reason_code"]
        for item in diagnostics["schema_validation"]["violations"]
    } == {"canonical_claim_type_not_allowed", "goal_extra_field"}


def test_llm_first_keeps_recovered_goal_authoritative_without_fact_authority(
    monkeypatch,
):
    message = "Which service outcome applies?"
    payload = {
        "goals": [
            _goal(
                source_text=message,
                claim_type="provider_outcome",
                attribute_key="service_outcome",
            )
        ]
    }
    client = _FakeClient(_response_for_payload(payload))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [],
    )
    monkeypatch.setattr(
        service.config,
        "COPILOT_FACT_TYPE_LLM_ENABLED",
        True,
    )
    diagnostics = {}

    result = service.classify_query_fact_type_llm_first(
        {
            "normalized_message": message,
            "intent": "service_question",
        },
        diagnostics_sink=diagnostics,
    )

    assert result["source"] == "llm"
    assert result["goal_understanding_status"] == "valid"
    assert result["query_fact_type"] == ""
    assert result["customer_goals"][0]["claim_type_status"] == "unmapped"
    assert result["goal_understanding_diagnostics"] == [
        "canonical_claim_type_unknown",
        "canonical_claim_type_not_allowed",
    ]
    assert diagnostics["status"] == "failed"
    assert diagnostics["schema_success"] is False


def test_unknown_goal_downgrade_does_not_remove_independent_canonical_goal(
    monkeypatch,
):
    message = "What material is it, and which service outcome applies?"
    payload = {
        "goals": [
            _goal(
                source_text="What material is it",
                claim_type="material",
                attribute_key="material",
            ),
            _goal(
                source_text="which service outcome applies",
                claim_type="provider_outcome",
                attribute_key="service_outcome",
            ),
        ]
    }

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
        message=message,
    )

    assert result is not None
    assert result["goal_understanding_status"] == "valid"
    assert result["query_fact_type"] == "material"
    assert {
        (goal["claim_type_status"], goal["claim_type"])
        for goal in result["customer_goals"]
    } == {("canonical", "material"), ("unmapped", "")}
    assert diagnostics["runtime_goal_continuity"]["downgraded_goal_count"] == 1


def test_duplicate_goal_is_reported(monkeypatch):
    payload = _valid_payload()
    payload["goals"].append(
        copy.deepcopy(payload["goals"][0])
    )

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert result is None
    assert "duplicate_resolved_provenance" in _reason_codes(diagnostics)


def test_invalid_source_is_provenance_failure(monkeypatch):
    payload = _valid_payload()
    payload["goals"][0]["source_text"] = (
        "text from another message"
    )

    _result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert diagnostics["provenance_validation"]["passed"] is False
    assert "source_text_not_found" in _reason_codes(diagnostics)


def test_unique_text_is_resolved_without_provider_offsets(
    monkeypatch,
):
    payload = _valid_payload()

    result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert result is not None
    assert diagnostics["status"] == "passed"
    assert diagnostics["span_resolution"][
        "provider_offset_mismatch_count"
    ] == 0
    first = diagnostics["span_resolution"]["records"][0]
    assert first["reason_code"] == "source_text_resolved"
    assert first["exact_match_count"] == 1
    assert first["provider_offset_present"] is False
    assert first["provider_offset_match"] is None
    assert MESSAGE[
        first["resolved_span_start"]:first["resolved_span_end"]
    ] == payload["goals"][0]["source_text"]


def test_wrong_turn_source_text_has_sanitized_diagnostic(monkeypatch):
    payload = _valid_payload()
    payload["goals"] = [
        _goal(source_text="这款材质是什么")
    ]
    payload["goals"][0]["source_text"] = "上一轮安装问题"

    client = _FakeClient(_response_for_payload(payload))
    diagnostics = {}
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [],
    )
    result = service._classify_with_llm(
        {
            "copilot_context": {
                "conversation_history": [{
                    "role": "customer",
                    "content": "上一轮安装问题",
                }],
            },
        },
        MESSAGE,
        "product_question",
        diagnostics_sink=diagnostics,
    )

    assert result is None
    record = diagnostics["span_resolution"]["records"][0]
    assert record["reason_code"] == "source_text_from_wrong_turn"
    serialized = json.dumps(diagnostics, ensure_ascii=False)
    assert "上一轮安装问题" not in serialized


def test_turn_understanding_receives_bounded_role_preserving_recent_conversation(
    monkeypatch,
):
    message = "其他事项都没有了"
    payload = {
        "goals": [{
            "goal_kind": "contextual_constraint",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "",
            "subject_scope": "",
            "semantic_key": "no_additional_issue",
            "policy_intent_ref": "",
            "source_text": message,
            "continued_from": "",
        }],
    }
    client = _FakeClient(_response_for_payload(payload))
    diagnostics = {}
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(service, "_policy_intent_candidates", lambda _state: [])

    result = service._classify_with_llm(
        {
            "copilot_context": {
                "conversation_history": [
                    {
                        "role": "customer",
                        "content": "我还需要一份使用资料",
                        "turn_index": 2,
                    },
                    {
                        "role": "agent",
                        "content": "除此之外还有其他情况吗",
                        "turn_index": 3,
                    },
                ],
            },
        },
        message,
        "general",
        diagnostics_sink=diagnostics,
    )

    request_payload = json.loads(client.kwargs["messages"][1]["content"])
    assert request_payload["customer_message"] == message
    assert request_payload["recent_conversation"] == [
        {"role": "customer", "content": "我还需要一份使用资料"},
        {"role": "agent", "content": "除此之外还有其他情况吗"},
    ]
    assert result is not None
    assert result["customer_goals"][0]["goal_kind"] == "contextual_constraint"


def test_turn_understanding_recent_conversation_is_bounded(monkeypatch):
    message = "目前就这些"
    payload = {
        "goals": [{
            "goal_kind": "contextual_constraint",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "",
            "subject_scope": "",
            "semantic_key": "conversation_scope_confirmation",
            "policy_intent_ref": "",
            "source_text": message,
            "continued_from": "",
        }],
    }
    client = _FakeClient(_response_for_payload(payload))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(service, "_policy_intent_candidates", lambda _state: [])
    history = [
        {"role": "customer" if index % 2 == 0 else "agent", "content": f"turn-{index}"}
        for index in range(20)
    ]

    service._classify_with_llm(
        {"copilot_context": {"conversation_history": history}},
        message,
        "general",
    )

    request_payload = json.loads(client.kwargs["messages"][1]["content"])
    assert len(request_payload["recent_conversation"]) == 8
    assert request_payload["recent_conversation"][0]["content"] == "turn-12"
    assert request_payload["recent_conversation"][-1]["content"] == "turn-19"


def test_span_diagnostics_distinguish_schema_and_hash_mismatch():
    malformed = _valid_payload()["goals"][0]
    malformed["source_text"] = ""
    forged_hash = _valid_payload()["goals"][1]
    forged_hash["source_text_sha256"] = "0" * 64

    diagnostics = service._span_resolution_diagnostics(
        [malformed, forged_hash],
        span_reference_text=MESSAGE,
    )

    assert [
        record["reason_code"]
        for record in diagnostics["records"]
    ] == [
        "source_text_schema_invalid",
        "source_text_hash_mismatch",
    ]
    serialized = json.dumps(diagnostics, ensure_ascii=False)
    assert MESSAGE not in serialized
    assert forged_hash["source_text"] not in serialized


@pytest.mark.parametrize(
    ("provenance", "reason_code"),
    [
        (
            {
                "source_span_start": -1,
                "source_span_end": 3,
                "source_span_sha256": "0" * 64,
            },
            "source_span_out_of_range",
        ),
        (
            {
                "source_span_start": 0,
                "source_span_end": 7,
                "source_span_sha256": "0" * 64,
            },
            "source_span_digest_mismatch",
        ),
    ],
)
def test_server_provenance_failures_are_attributed(
    monkeypatch,
    provenance,
    reason_code,
):
    monkeypatch.setattr(
        service,
        "_resolve_source_span_provenance",
        lambda _source, _message, **_kwargs: (
            dict(provenance),
            "source_text_resolved",
        ),
    )
    payload = _valid_payload()
    payload["goals"] = payload["goals"][:1]

    _result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    assert reason_code in _reason_codes(diagnostics)


def test_forged_owner_is_hashed_and_rejected(monkeypatch):
    payload = _valid_payload()
    payload["goals"][0]["owner"] = "public_owner"
    payload["goals"][0]["provenance"] = {
        "source": "public"
    }

    _result, diagnostics, _client = _run(
        monkeypatch,
        _response_for_payload(payload),
    )

    serialized = json.dumps(diagnostics, ensure_ascii=False)
    assert "owner_invalid" in _reason_codes(diagnostics)
    assert "public_owner" not in serialized
    assert '"provenance"' not in serialized


def test_diagnostics_exclude_raw_content_and_credentials(monkeypatch):
    private_message = (
        "手机号13800138000，订单123456789012345678，"
        "地址北京市测试路88号"
    )
    raw_content = (
        "secret-key Authorization https://private.invalid "
        + private_message
    )
    client = _FakeClient(_FakeResponse([
        _FakeChoice(
            raw_content,
            reasoning_content="private reasoning",
        ),
    ]))
    diagnostics = {}
    monkeypatch.setattr(service, "get_llm_client", lambda: client)

    result = service._classify_with_llm(
        {},
        private_message,
        "product_question",
        diagnostics_sink=diagnostics,
    )

    assert result is None
    serialized = json.dumps(diagnostics, ensure_ascii=False)
    for forbidden in (
        private_message,
        "13800138000",
        "123456789012345678",
        "北京市测试路88号",
        "secret-key",
        "Authorization",
        "private.invalid",
        "private reasoning",
    ):
        assert forbidden not in serialized
    assert diagnostics["completion"]["content_char_count"] == len(
        raw_content
    )
    assert len(diagnostics["completion"]["content_sha256"]) == 64


def test_public_result_contract_is_unchanged_with_optional_sink(monkeypatch):
    client = _FakeClient(_response_for_payload(_valid_payload()))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [],
    )
    without_sink = service._classify_with_llm(
        {},
        MESSAGE,
        "product_question",
    )
    diagnostics = {}
    with_sink = service._classify_with_llm(
        {},
        MESSAGE,
        "product_question",
        diagnostics_sink=diagnostics,
    )

    assert without_sink == with_sink
    assert "diagnostics" not in with_sink
    assert "can_send" not in with_sink
    assert client.calls == 2


def test_input_order_does_not_change_primary_reason_code(monkeypatch):
    payload = {}
    payload["z_extra"] = True
    payload["a_extra"] = True
    reversed_payload = dict(reversed(list(payload.items())))

    _result_a, diagnostics_a, _client_a = _run(
        monkeypatch,
        _response_for_payload(payload),
    )
    _result_b, diagnostics_b, _client_b = _run(
        monkeypatch,
        _response_for_payload(reversed_payload),
    )

    assert diagnostics_a["reason_code"] == (
        diagnostics_b["reason_code"]
    ) == "top_level_field_missing"


def test_upper_fallback_does_not_overwrite_earliest_diagnostic(
    monkeypatch,
):
    payload = {}
    client = _FakeClient(_response_for_payload(payload))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service.config,
        "COPILOT_FACT_TYPE_LLM_ENABLED",
        True,
    )
    diagnostics = {}

    result = service.classify_query_fact_type_llm_first(
        {
            "normalized_message": MESSAGE,
            "intent": "product_question",
        },
        diagnostics_sink=diagnostics,
    )

    assert result["source"] == "rule_fallback"
    assert diagnostics["reason_code"] == "top_level_field_missing"
    assert diagnostics["stage"] == "top_level_schema"


def test_llm_client_single_attempt_mode_does_not_repair_or_retry():
    calls = []
    response = _FakeResponse([
        _FakeChoice("```json\n{\"ok\": true}\n```"),
    ])

    class _Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    client = LLMClient(
        api_key="test-key",
        api_base="https://provider.invalid/v1",
        model="test-model",
    )
    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions())
    )

    returned = client.create_chat_completion(
        model="test-model",
        messages=[{"role": "user", "content": "test"}],
        response_format={"type": "json_object"},
        _single_attempt_no_repair=True,
    )

    assert returned is response
    assert returned.choices[0].message.content.startswith("```")
    assert len(calls) == 1
    assert "_single_attempt_no_repair" not in calls[0]
