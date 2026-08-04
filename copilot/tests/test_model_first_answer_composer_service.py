from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.model_first_answer_composer_service import (
    COMPOSER_CLAUSE_FIELD_OWNERSHIP,
    COMPOSER_RESPONSE_SCHEMA,
    COMPOSER_RESPONSE_SCHEMA_VERSION,
    ModelFirstAnswerComposerService,
)

_DOMAIN_PACK_HASH = hashlib.sha256(
    b"fixture-domain-policy-pack"
).hexdigest()


def _resolution(
    claim_uid: str,
    claim_type: str,
    status: str,
    *,
    attribute_key: str = "",
    evidence_uids: list[str] | None = None,
    support_basis: str = "",
    premise_evidence_uids: list[str] | None = None,
    inference_policy_refs: list[str] | None = None,
    scope_qualifier: str = "",
    inference_risk_level: str = "",
    maximum_risk_level: str = "",
    inference_review_only: bool = False,
    required_qualifiers: list[str] | None = None,
    prohibited_extensions: list[str] | None = None,
    eligible_policy_options: list[dict] | None = None,
    goal_ref: str = "",
    goal_kind: str = "customer_goal",
    claim_type_status: str = "mapped",
    supporting_only: bool = False,
    supporting_for_goal_ref: str = "",
) -> dict:
    resolved_goal_ref = goal_ref or claim_uid.replace("claim-", "goal-", 1)
    return {
        "claim_uid": claim_uid,
        "goal_ref": resolved_goal_ref,
        "goal_kind": goal_kind,
        "claim_type": claim_type,
        "claim_type_status": claim_type_status,
        "attribute_key": attribute_key,
        "status": status,
        "evidence_uids": list(evidence_uids or []),
        "support_basis": support_basis,
        "premise_evidence_uids": list(premise_evidence_uids or []),
        "inference_policy_refs": list(inference_policy_refs or []),
        "scope_qualifier": scope_qualifier,
        "inference_risk_level": inference_risk_level,
        "maximum_risk_level": maximum_risk_level,
        "inference_review_only": inference_review_only,
        "required_qualifiers": list(required_qualifiers or []),
        "prohibited_extensions": list(prohibited_extensions or []),
        "eligible_policy_options": deepcopy(
            eligible_policy_options or []
        ),
        "supporting_only": supporting_only,
        "supporting_for_goal_ref": supporting_for_goal_ref,
    }


def _goal(
    goal_ref: str,
    claim_type: str,
    *,
    goal_kind: str = "customer_goal",
    attribute_key: str = "",
    supporting_only: bool = False,
    supporting_for_goal_ref: str = "",
    claim_type_status: str = "mapped",
    semantic_key: str = "",
    goal_summary: str = "",
    customer_goal_eligible: bool = True,
    source_span_start: int = 0,
    source_span_end: int = 8,
    source_turn_uid: str = "turn-current",
) -> dict:
    digest = hashlib.sha256(goal_ref.encode("utf-8")).hexdigest()
    return {
        "schema_version": "turn-understanding-goal-identity/v2",
        "goal_ref": goal_ref,
        "goal_kind": goal_kind,
        "claim_type_status": claim_type_status,
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "semantic_key": semantic_key,
        "goal_summary": goal_summary,
        "source": "current_customer_message",
        "source_span_start": source_span_start,
        "source_span_end": source_span_end,
        "source_span_sha256": digest,
        "source_text_sha256": digest,
        "source_turn_uid": source_turn_uid,
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "supporting_only": supporting_only,
        "supporting_for_goal_ref": supporting_for_goal_ref,
        "customer_goal_eligible": customer_goal_eligible,
    }


def _response() -> dict:
    return {
        "suggested_reply": "旧回复",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "旧回复"}],
        "minimal_decision_context": {
            "customer_goal": "尺寸和安全怎么样",
            "recent_conversation_turns": [
                {"role": "customer", "content": "我问的是宽度", "turn_index": 1},
            ],
            "product_identity": {"sku_code": "private-sku"},
            "requested_claims": [
                _goal(
                    "goal-width",
                    "dimensions",
                    attribute_key="width",
                ),
                _goal("goal-safety", "child_safety"),
            ],
            "admitted_evidence": [{
                "evidence_uid": "ev-width",
                "fact_type": "dimensions",
                "attribute_key": "width",
                "content": "商品宽度为80厘米",
            }],
            "claim_resolutions": [
                _resolution(
                    "claim-width",
                    "dimensions",
                    "supported",
                    attribute_key="width",
                    evidence_uids=["ev-width"],
                ),
                _resolution("claim-safety", "child_safety", "unresolved"),
            ],
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 40},
        },
    }


def _valid_payload() -> dict:
    return {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "text": "儿童安全方面目前无法确认。",
                "selected_option_refs": [],
            },
            {
                "goal_ref": "goal_02",
                "text": "商品宽度为80厘米。",
                "selected_option_refs": [],
            },
        ],
    }


def _with_policy_selection_fields(payload: dict) -> dict:
    normalized = deepcopy(payload)
    for clause in normalized.get("clauses") or []:
        if not isinstance(clause, dict):
            continue
        selected_policy_ref = str(
            clause.pop("selected_policy_ref", "") or ""
        ).strip()
        clause.pop("clause_kind", None)
        clause.pop("evidence_refs", None)
        clause.pop("premise_evidence_refs", None)
        clause.pop("inference_scope", None)
        clause.setdefault(
            "selected_option_refs",
            [selected_policy_ref] if selected_policy_ref else [],
        )
    return normalized


class _Client:
    api_key = "configured"
    model = "MiniMax-M3"

    def __init__(
        self,
        payload: dict | str | None,
        *,
        finish_reason: str = "stop",
    ):
        self.payload = payload
        self.finish_reason = finish_reason
        self.messages = []
        self.kwargs = {}
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        self.kwargs = kwargs
        self.messages = kwargs["messages"]
        content = (
            self.payload
            if isinstance(self.payload, str)
            else (
                ""
                if self.payload is None
                else json.dumps(self.payload, ensure_ascii=False)
            )
        )
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=self.finish_reason,
            message=SimpleNamespace(content=content),
        )])


class _RaisingClient(_Client):
    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise RuntimeError("minimax_response_truncated")


class _TimeoutClient(_Client):
    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise TimeoutError("provider timeout")


def _compose(
    payload: dict | str,
    response: dict | None = None,
    *,
    normalize_policy_fields: bool = True,
):
    client_payload = (
        _with_policy_selection_fields(payload)
        if normalize_policy_fields and isinstance(payload, dict)
        else payload
    )
    client = _Client(client_payload)
    updated, result = ModelFirstAnswerComposerService().compose(
        response or _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )
    return updated, result, client


def test_composer_renders_one_clause_for_each_customer_goal():
    updated, result, client = _compose(_valid_payload())

    assert result["status"] == "accepted"
    assert result["covered_goal_refs"] == ["claim-safety", "claim-width"]
    assert result["used_evidence_uids"] == ["ev-width"]
    assert result["unresolved_claim_types"] == ["child_safety"]
    assert updated["suggested_reply"] == (
        "儿童安全方面目前无法确认。商品宽度为80厘米。"
    )
    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    assert updated["requires_human_review"] is True
    assert client.call_count == 1
    prompt = json.loads(client.messages[1]["content"])
    assert prompt["product_scope"] == {
        "resolved": True,
        "variant_context_present": False,
    }
    assert "private-sku" not in client.messages[1]["content"]


def test_composer_prompt_projects_canonical_clause_contract():
    _, result, client = _compose(_valid_payload())

    assert result["status"] == "accepted"
    prompt = json.loads(client.messages[1]["content"])
    goals = {
        item["claim_type"]: item
        for item in prompt["renderable_customer_goals"]
    }
    assert goals["child_safety"]["required_clause_kind"] == "unresolved"
    assert goals["child_safety"]["required_evidence_refs"] == []
    assert goals["dimensions"]["required_clause_kind"] == "supported_fact"
    assert goals["dimensions"]["required_evidence_refs"] == ["E1"]
    assert (
        "不补充原因、概率、性能、适用或使用建议"
        in client.messages[0]["content"]
    )


def _presentation_response() -> dict:
    response = _response()
    context = response["minimal_decision_context"]
    context["customer_goal"] = "先问第一项，再问第二项"
    context["requested_claims"] = [
        _goal(
            "goal-z-first",
            "dimensions",
            attribute_key="first",
            source_span_start=0,
            source_span_end=5,
        ),
        _goal(
            "goal-a-second",
            "material_composition",
            attribute_key="second",
            source_span_start=6,
            source_span_end=11,
        ),
    ]
    context["admitted_evidence"] = [
        {
            "evidence_uid": "ev-first",
            "fact_type": "dimensions",
            "attribute_key": "first",
            "content": "第一项事实",
        },
        {
            "evidence_uid": "ev-second",
            "fact_type": "material_composition",
            "attribute_key": "second",
            "content": "第二项事实",
        },
    ]
    context["claim_resolutions"] = [
        _resolution(
            "claim-z-first",
            "dimensions",
            "supported",
            attribute_key="first",
            evidence_uids=["ev-first"],
            goal_ref="goal-z-first",
        ),
        _resolution(
            "claim-a-second",
            "material_composition",
            "supported",
            attribute_key="second",
            evidence_uids=["ev-second"],
            goal_ref="goal-a-second",
        ),
    ]
    return response


def _presentation_payload() -> dict:
    return {
        "clauses": [
            {
                "goal_ref": "goal_02",
                "clause_kind": "supported_fact",
                "text": "第一项事实。",
                "evidence_refs": ["E1"],
            },
            {
                "goal_ref": "goal_01",
                "clause_kind": "supported_fact",
                "text": "第二项事实。",
                "evidence_refs": ["E2"],
            },
        ],
    }


def test_composer_uses_source_span_presentation_without_changing_aliases():
    response = _presentation_response()

    updated, result, client = _compose(
        _presentation_payload(),
        response,
    )

    assert result["status"] == "accepted"
    prompt = json.loads(client.messages[1]["content"])
    assert prompt["presentation_order"] == ["goal_02", "goal_01"]
    goals = {
        item["claim_type"]: item["goal_ref"]
        for item in prompt["renderable_customer_goals"]
    }
    assert goals == {
        "material_composition": "goal_01",
        "dimensions": "goal_02",
    }
    assert result["covered_goal_refs"] == [
        "claim-z-first",
        "claim-a-second",
    ]
    assert updated["suggested_reply"] == "第一项事实。第二项事实。"
    assert client.call_count == 1


def test_composer_rejects_provider_clause_order_mismatch():
    payload = _presentation_payload()
    payload["clauses"].reverse()

    updated, result, client = _compose(
        payload,
        _presentation_response(),
    )

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_clause_presentation_order_invalid"
    )
    assert result["validation_diagnostics"]["category"] == (
        "clause_presentation_order_invalid"
    )
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


def test_presentation_projection_is_input_permutation_stable():
    first = _presentation_response()
    second = deepcopy(first)
    minimal = second["minimal_decision_context"]
    minimal["requested_claims"].reverse()
    minimal["claim_resolutions"].reverse()
    minimal["admitted_evidence"].reverse()

    first_material, first_error = (
        ModelFirstAnswerComposerService
        .build_composer_decision_input(
            first,
            customer_message="先问第一项，再问第二项",
        )
    )
    second_material, second_error = (
        ModelFirstAnswerComposerService
        .build_composer_decision_input(
            second,
            customer_message="先问第一项，再问第二项",
        )
    )
    assert first_error == second_error == ""
    first_provider, first_provider_error = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(first_material)
    )
    second_provider, second_provider_error = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(second_material)
    )

    assert first_provider_error == second_provider_error == ""
    assert first_provider["customer_goals"] == second_provider[
        "customer_goals"
    ]
    assert first_provider["offered_option_bindings"] == second_provider[
        "offered_option_bindings"
    ]
    assert first_provider["partitions"]["presentation_order"] == [
        "goal_02",
        "goal_01",
    ]
    assert first_provider["partitions"]["presentation_order"] == (
        second_provider["partitions"]["presentation_order"]
    )


def test_presentation_projection_uses_goal_ref_only_as_span_tie_breaker():
    response = _presentation_response()
    for claim in response["minimal_decision_context"]["requested_claims"]:
        claim["source_span_start"] = 3
        claim["source_span_end"] = 7

    decision_input, decision_error = (
        ModelFirstAnswerComposerService.build_composer_decision_input(
            response,
            customer_message="两个并列问题",
        )
    )
    material, material_error = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert decision_error == material_error == ""
    assert material["partitions"]["presentation_order"] == [
        "goal_01",
        "goal_02",
    ]


def test_composer_rejects_cross_turn_customer_goal_provenance():
    response = _presentation_response()
    response["minimal_decision_context"]["requested_claims"][1][
        "source_turn_uid"
    ] = "turn-other"
    client = _Client(_with_policy_selection_fields(_presentation_payload()))

    updated, result = ModelFirstAnswerComposerService().compose(
        response,
        customer_message="先问第一项，再问第二项",
        client=client,
    )

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_customer_goal_source_turn_mismatch"
    )
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 0


def test_high_risk_and_unowned_emergency_marker_do_not_reorder_goals():
    response = _presentation_response()
    context = response["minimal_decision_context"]
    context["claim_resolutions"][1]["requested_claim_risk"] = "high"
    context["requested_claims"][1]["requires_immediate_action"] = True

    decision_input, decision_error = (
        ModelFirstAnswerComposerService.build_composer_decision_input(
            response,
            customer_message="先问第一项，再问第二项",
        )
    )
    material, material_error = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert decision_error == material_error == ""
    assert "requires_immediate_action" not in json.dumps(
        decision_input,
        ensure_ascii=False,
    )
    assert material["partitions"]["presentation_order"] == [
        "goal_02",
        "goal_01",
    ]


@pytest.mark.parametrize(
    ("mutate", "expected_reason"),
    (
        (
            lambda goal: goal.pop("source_span_start"),
            "composer_goal_provenance_invalid",
        ),
        (
            lambda goal: goal.__setitem__("source_span_start", True),
            "composer_goal_provenance_invalid",
        ),
        (
            lambda goal: goal.__setitem__("source_span_start", -1),
            "composer_goal_provenance_invalid",
        ),
        (
            lambda goal: goal.__setitem__("source_span_end", -1),
            "composer_goal_provenance_invalid",
        ),
    ),
)
def test_composer_rejects_invalid_presentation_span(
    mutate,
    expected_reason,
):
    response = _presentation_response()
    mutate(response["minimal_decision_context"]["requested_claims"][0])
    client = _Client(_with_policy_selection_fields(_presentation_payload()))

    updated, result = ModelFirstAnswerComposerService().compose(
        response,
        customer_message="依次确认三个并列事项",
        client=client,
    )

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == expected_reason
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 0


def test_presentation_projection_supports_three_customer_goals():
    response = _presentation_response()
    context = response["minimal_decision_context"]
    context["requested_claims"].append(
        _goal(
            "goal-m-middle",
            "generic_fact",
            attribute_key="middle",
            source_span_start=3,
            source_span_end=5,
        )
    )
    context["admitted_evidence"].append({
        "evidence_uid": "ev-middle",
        "fact_type": "generic_fact",
        "attribute_key": "middle",
        "content": "中间事项",
    })
    context["claim_resolutions"].append(
        _resolution(
            "claim-m-middle",
            "generic_fact",
            "supported",
            attribute_key="middle",
            evidence_uids=["ev-middle"],
            goal_ref="goal-m-middle",
        )
    )

    decision_input, decision_error = (
        ModelFirstAnswerComposerService.build_composer_decision_input(
            response,
            customer_message="依次确认三个并列事项",
        )
    )
    material, material_error = (
        ModelFirstAnswerComposerService
        .build_provider_material_from_decision_input(decision_input)
    )

    assert decision_error == material_error == ""
    assert [
        item["goal_ref"] for item in material["customer_goals"]
    ] == ["goal_01", "goal_02", "goal_03"]
    assert material["partitions"]["presentation_order"] == [
        "goal_03",
        "goal_02",
        "goal_01",
    ]


def test_composer_preserves_unmapped_goal_as_unresolved_clause():
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"] = [
        _goal("goal-material", "material"),
        _goal(
            "goal-durability",
            "",
            claim_type_status="unmapped",
            goal_summary="确认是否能保证摔不坏",
        ),
    ]
    context["admitted_evidence"] = [{
        "evidence_uid": "ev-material",
        "fact_type": "material",
        "attribute_key": "",
        "content": "商品材质为ABS塑料加硅胶。",
    }]
    context["claim_resolutions"] = [
        {
            **_resolution(
                "claim-material",
                "material",
                "supported",
                evidence_uids=["ev-material"],
            ),
        },
        {
            **_resolution(
                "claim-durability",
                "",
                "unresolved",
            ),
            "claim_type_status": "unmapped",
            "semantic_key": "",
            "goal_summary": "确认是否能保证摔不坏",
        },
    ]
    payload = {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "unresolved",
                "text": "是否能保证摔不坏目前无法确认。",
                "evidence_refs": [],
            },
            {
                "goal_ref": "goal_02",
                "clause_kind": "supported_fact",
                "text": "这款材质是ABS塑料加硅胶。",
                "evidence_refs": ["E1"],
            },
        ],
    }

    updated, result, client = _compose(payload, response)

    assert result["status"] == "accepted"
    assert result["unresolved_claim_types"] == []
    assert "无法确认" in updated["suggested_reply"]
    prompt = json.loads(client.messages[1]["content"])
    unresolved_goal = next(
        item
        for item in prompt["renderable_customer_goals"]
        if item["required_clause_kind"] == "unresolved"
    )
    assert unresolved_goal["claim_type"] == ""
    assert unresolved_goal["claim_type_status"] == "unmapped"
    assert unresolved_goal["required_clause_kind"] == (
        "unresolved"
    )
    assert unresolved_goal["semantic_key"] == ""
    assert unresolved_goal["goal_summary"] == (
        "确认是否能保证摔不坏"
    )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda value: value["clauses"].pop(0),
            "composer_goal_clause_omitted",
        ),
        (
            lambda value: value["clauses"][0].update(text=""),
            "composer_goal_clause_text_missing",
        ),
        (
            lambda value: value["clauses"].append(deepcopy(value["clauses"][0])),
            "composer_duplicate_goal_clause",
        ),
        (
            lambda value: value["clauses"][0].update(goal_ref="goal_09"),
            "composer_unknown_goal_reference",
        ),
        (
            lambda value: value["clauses"][0].update(extra="not-allowed"),
            "composer_clause_schema_invalid",
        ),
    ],
)
def test_composer_rejects_goal_clause_contract_mutations(mutate, reason):
    payload = _valid_payload()
    mutate(payload)

    updated, result, client = _compose(payload)

    assert result["rejection_reason"] == reason
    assert updated["suggested_reply"] == "旧回复"
    assert updated["can_send"] is True
    assert client.call_count == 1


def test_composer_restores_supported_evidence_without_model_echo():
    payload = _valid_payload()

    _, result, _ = _compose(payload)

    assert result["status"] == "accepted"
    assert result["clauses"][1]["evidence_uids"] == ["ev-width"]


def test_composer_rejects_model_owned_evidence_field():
    payload = _valid_payload()
    payload["clauses"][0]["evidence_refs"] = ["E1"]

    _, result, _ = _compose(payload, normalize_policy_fields=False)

    assert result["rejection_reason"] == "composer_clause_schema_invalid"


def test_composer_rejects_media_promise_without_actual_block():
    payload = _valid_payload()
    payload["clauses"][0]["text"] = "儿童安全无法确认，安装视频已经发给您了。"

    _, result, _ = _compose(payload)

    assert result["rejection_reason"] == "composer_unsupported_media_promise"


def test_composer_rejects_process_copy_instead_of_direct_answer():
    payload = _valid_payload()
    payload["clauses"][1]["text"] = "我先核对宽度，确认后回复。"

    _, result, _ = _compose(payload)

    assert result["rejection_reason"] == "composer_process_language"


@pytest.mark.parametrize(
    ("text", "trigger_category"),
    [
        ("这个结论不能承诺。", "reply_policy_meta_language"),
        ("当前缺少证据支持。", "evidence_process_language"),
        ("这项需要人工审核。", "review_process_language"),
        ("当前知识库没有记录。", "internal_knowledge_language"),
        ("Final Gate 尚未通过。", "internal_system_language"),
        ("需要查看 rAg 结果。", "internal_system_language"),
        ("这项不直接说结论。", "reply_policy_meta_language"),
    ],
)
def test_composer_attributes_customer_visible_internal_language(
    text,
    trigger_category,
):
    payload = _valid_payload()
    payload["clauses"][0]["text"] = text

    _, result, client = _compose(payload)

    assert result["rejection_reason"] == "composer_internal_language"
    match = result["validation_diagnostics"]["language_match"]
    assert match["detector_family"] == (
        "customer_facing_internal_redline"
    )
    assert match["reason_code"] == (
        "customer_visible_internal_language_detected"
    )
    assert match["trigger_category"] == trigger_category
    assert match["clause_index"] == 0
    assert match["goal_ref"] == "goal_01"
    assert match["json_path"] == "$.clauses[0].text"
    assert len(match["text_sha256"]) == 64
    assert len(match["rule_sha256"]) == 64
    assert client.call_count == 1


@pytest.mark.parametrize(
    ("text", "trigger_category"),
    [
        ("我先核对，之后答复。", "deferred_process_language"),
        ("请稍等\n我马上处理。", "deferred_process_language"),
        ("这个问题需要转人工。", "handoff_process_language"),
        ("资料显示该项可用。", "source_process_language"),
        ("系统显示该项可用。", "source_process_language"),
        ("公司资料写了这一点。", "source_process_language"),
    ],
)
def test_composer_attributes_customer_visible_process_language(
    text,
    trigger_category,
):
    payload = _valid_payload()
    payload["clauses"][0]["text"] = text

    _, result, client = _compose(payload)

    assert result["rejection_reason"] == "composer_process_language"
    match = result["validation_diagnostics"]["language_match"]
    assert match["detector_family"] == "composer_process_language"
    assert match["reason_code"] == (
        "customer_visible_process_language_detected"
    )
    assert match["trigger_category"] == trigger_category
    assert match["clause_index"] == 0
    assert client.call_count == 1


def test_composer_does_not_scan_internal_schema_metadata_as_reply_text():
    response = _response()
    goal = response["minimal_decision_context"]["requested_claims"][0]
    goal["goal_summary"] = (
        "evidence policy claim audit system prompt model"
    )
    goal["semantic_key"] = "allowed_inference_supported_fact"

    _, result, client = _compose(_valid_payload(), response)

    assert result["status"] == "accepted"
    assert result["rejection_reason"] == ""
    assert client.call_count == 1


def test_composer_does_not_scan_internal_controlled_references_as_text():
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"][0]["goal_ref"] = (
        "goal-z-RAG-policy-audit"
    )
    context["claim_resolutions"][0]["goal_ref"] = (
        "goal-z-RAG-policy-audit"
    )

    _, result, client = _compose(_valid_payload(), response)

    assert result["status"] == "accepted"
    assert result["rejection_reason"] == ""
    assert client.call_count == 1


def test_composer_allows_normal_business_terms_in_customer_text():
    payload = _valid_payload()
    payload["clauses"][1]["text"] = (
        "材料和规格以当前商品说明为依据。"
    )

    _, result, client = _compose(payload)

    assert result["status"] == "accepted"
    assert result["rejection_reason"] == ""
    assert client.call_count == 1


def test_composer_internal_language_rule_spanning_clause_boundary_is_preserved():
    payload = _valid_payload()
    payload["clauses"][0]["text"] = "当前知"
    payload["clauses"][1]["text"] = "识库没有记录。"

    _, result, client = _compose(payload)

    assert result["rejection_reason"] == "composer_internal_language"
    match = result["validation_diagnostics"]["language_match"]
    assert match["trigger_category"] == "internal_knowledge_language"
    assert match["clause_index"] == 0
    assert client.call_count == 1


def test_composer_prompt_requires_customer_visible_expression_stability():
    _, result, client = _compose(_valid_payload())

    assert result["status"] == "accepted"
    prompt = client.messages[0]["content"]
    for required in (
        "按客户提问顺序先回答已支持事实",
        "自然、礼貌、简洁",
        "避免重复主语、边界、法务声明",
        "客户可见文字只放在 text",
    ):
        assert required in prompt
    for prohibited in (
        "ABS",
        "硅胶",
        "聚合物",
        "跌落",
        "摔不坏",
        "GSC",
    ):
        assert prohibited not in prompt
    assert client.call_count == 1


def test_composer_prompt_prioritizes_required_option_over_unresolved_kind():
    _, result, client = _compose(_valid_payload())

    assert result["status"] == "accepted"
    prompt = client.messages[0]["content"]
    structural_priority = (
        "每个 goal 先按 option_selection_mode 决定 option 选择"
    )
    required_rule = (
        "该规则优先于 required_clause_kind"
    )
    customer_style = (
        "多目标 clause 各自只回答对应 goal"
    )
    for required in (
        structural_priority,
        required_rule,
        "即使 required_clause_kind=unresolved 也相同",
        "required clause 的 text 同时表达所选 allowed_scope",
        "required_qualifiers 中每一项都是必须显式表达的语义义务",
        "以 do_not_ 开头的 qualifier 必须直接说明暂不采取对应动作",
        "must_remain_unresolved 只约束客户原始受限主张",
        "模型不得输出 evidence_refs",
        "required_clause_kind=unresolved 时结合 goal_summary",
    ):
        assert required in prompt
    assert prompt.index(structural_priority) < prompt.index(required_rule)
    assert prompt.index(required_rule) < prompt.index(customer_style)
    assert client.call_count == 1


def test_composer_prompt_uses_only_actual_blocks_as_media_delivery_authority():
    prompt = ModelFirstAnswerComposerService._system_prompt()

    assert "Only media_context.actual_attached_media_types authorizes wording" in prompt
    assert "candidate_count and media_context.request_refs are context only" in prompt
    assert "do not state or imply present delivery" in prompt


def test_composer_response_schema_is_the_prompt_and_validator_field_owner():
    service = ModelFirstAnswerComposerService
    schema = COMPOSER_RESPONSE_SCHEMA
    clause_schema = schema["properties"]["clauses"]["items"]
    contract = service._schema_prompt_contract()
    projection = service._output_contract_projection()
    prompt = service._system_prompt()

    assert schema["title"] == COMPOSER_RESPONSE_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert clause_schema["additionalProperties"] is False
    assert set(contract["top_level_fields"]) == set(
        schema["properties"]
    )
    assert set(contract["top_level_required"]) == set(
        schema["required"]
    )
    assert set(contract["clause_fields"]) == set(
        clause_schema["properties"]
    )
    assert set(contract["clause_required"]) == set(
        clause_schema["required"]
    )
    assert set(contract["clause_fields"]) == {
        "goal_ref",
        "text",
        "selected_option_refs",
    }
    assert "clause_kind" not in clause_schema["properties"]
    assert projection["response_schema_sha256"] == contract[
        "schema_sha256"
    ]
    assert projection["prompt_schema_summary_sha256"] == contract[
        "summary_sha256"
    ]
    assert contract["summary"] in prompt
    assert prompt.count("clauses[*]字段=[") == 1
    assert (
        "每个 clause 只能包含 goal_ref、clause_kind"
        not in prompt
    )


def test_composer_field_ownership_is_complete_and_non_overlapping():
    ownership = COMPOSER_CLAUSE_FIELD_OWNERSHIP
    model_owned = set(ownership["model_owned"])
    server_owned = set(ownership["server_owned"])

    assert ownership["mixed_or_not_proven"] == ()
    assert not model_owned.intersection(server_owned)
    assert {
        "goal_ref",
        "text",
        "selected_option_refs",
        "presentation_order",
    } == model_owned
    assert {
        "clause_kind",
        "evidence_refs",
        "selected_policy_ref",
        "premise_evidence_refs",
        "inference_scope",
        "requested_claim_risk",
        "answer_strategy_risk",
        "maximum_risk_level",
        "allowed_conclusion_family",
        "allowed_variability_factor_families",
        "advice_mode",
        "required_qualifiers",
        "prohibited_claim_families",
        "trusted_domain_pack_ref",
        "pack_content_sha256",
        "restricted_request_boundary",
    } == server_owned


def test_minimal_output_reconstructs_legacy_supported_unresolved_contract():
    response = _response()
    service = ModelFirstAnswerComposerService()
    decision_input, decision_error = service.build_composer_decision_input(
        response,
        customer_message="尺寸和安全怎么样",
    )
    assert decision_error == ""
    material, material_error = (
        service.build_provider_material_from_decision_input(decision_input)
    )
    assert material_error == ""
    goals = material["customer_goals"]
    bindings = material["offered_option_bindings"]
    payload = _valid_payload()

    canonical, reason, diagnostics = (
        ModelFirstAnswerComposerService
        ._reconstruct_canonical_output_with_diagnostics(
            payload,
            known_refs={"E1"},
            customer_goals=goals,
            offered_option_bindings=bindings,
        )
    )

    assert reason == ""
    assert diagnostics["category"] == "canonical_reconstruction_accepted"
    assert canonical == {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "unresolved",
                "text": "儿童安全方面目前无法确认。",
                "evidence_refs": [],
                "selected_policy_ref": "",
                "premise_evidence_refs": [],
                "inference_scope": "",
            },
            {
                "goal_ref": "goal_02",
                "clause_kind": "supported_fact",
                "text": "商品宽度为80厘米。",
                "evidence_refs": ["E1"],
                "selected_policy_ref": "",
                "premise_evidence_refs": [],
                "inference_scope": "",
            },
        ],
    }


def test_minimal_output_matches_legacy_allowed_inference_oracle():
    response = _bounded_inference_response()
    goals, bindings = _offered_projection(response)
    legacy = _bounded_inference_payload(response)
    legacy["clauses"][1].update({
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    })
    minimal = _with_policy_selection_fields(legacy)

    canonical, reason, _ = (
        ModelFirstAnswerComposerService
        ._reconstruct_canonical_output_with_diagnostics(
            minimal,
            known_refs={"E1"},
            customer_goals=goals,
            offered_option_bindings=bindings,
        )
    )

    assert reason == ""
    assert canonical == legacy


def test_minimal_output_matches_legacy_canonical_oracle_matrix():
    partial_response = _response()
    service = ModelFirstAnswerComposerService()
    partial_input, partial_input_error = (
        service.build_composer_decision_input(
            partial_response,
            customer_message="尺寸和安全怎么样",
        )
    )
    assert partial_input_error == ""
    partial_material, partial_material_error = (
        service.build_provider_material_from_decision_input(
            partial_input
        )
    )
    assert partial_material_error == ""
    partial_goals = partial_material["customer_goals"]
    partial_bindings = partial_material["offered_option_bindings"]
    partial_legacy = {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "unresolved",
                "text": "儿童安全方面目前无法确认。",
                "evidence_refs": [],
                "selected_policy_ref": "",
                "premise_evidence_refs": [],
                "inference_scope": "",
            },
            {
                "goal_ref": "goal_02",
                "clause_kind": "supported_fact",
                "text": "商品宽度为80厘米。",
                "evidence_refs": ["E1"],
                "selected_policy_ref": "",
                "premise_evidence_refs": [],
                "inference_scope": "",
            },
        ],
    }

    required_response = _bounded_inference_response()
    required_goals, required_bindings = _offered_projection(
        required_response
    )
    required_legacy = _bounded_inference_payload(required_response)
    required_legacy["clauses"][1].update({
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    })

    optional_response = _bounded_inference_response()
    _add_alternate_safe_option(
        optional_response,
        resolution_index=1,
    )
    optional_goals, optional_bindings = _offered_projection(
        optional_response
    )
    optional_legacy = _bounded_inference_payload(optional_response)
    optional_legacy["clauses"][1].update({
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    })

    cases = [
        (
            partial_legacy,
            partial_goals,
            partial_bindings,
            {"E1"},
        ),
        (
            required_legacy,
            required_goals,
            required_bindings,
            {"E1"},
        ),
        (
            optional_legacy,
            optional_goals,
            optional_bindings,
            {"E1"},
        ),
    ]
    for legacy, goals, bindings, known_refs in cases:
        canonical, reason, _ = (
            ModelFirstAnswerComposerService
            ._reconstruct_canonical_output_with_diagnostics(
                _with_policy_selection_fields(legacy),
                known_refs=known_refs,
                customer_goals=goals,
                offered_option_bindings=bindings,
            )
        )

        assert reason == ""
        assert canonical == legacy


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_reason"),
    [
        ("goal_ref", ["goal_01"], "composer_clause_schema_invalid"),
        ("text", ["文本"], "composer_goal_clause_text_missing"),
        (
            "selected_option_refs",
            "option_000000000000",
            "composer_inference_policy_schema_invalid",
        ),
    ],
)
def test_minimal_output_rejects_scalar_array_shape_mutations(
    field_name,
    invalid_value,
    expected_reason,
):
    payload = _valid_payload()
    payload["clauses"][0][field_name] = invalid_value

    _, result, _ = _compose(payload)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == expected_reason


def test_schema_change_changes_derived_prompt_summary_hash():
    original = ModelFirstAnswerComposerService._schema_prompt_contract()
    mutated = deepcopy(COMPOSER_RESPONSE_SCHEMA)
    clause_schema = mutated["properties"]["clauses"]["items"]
    clause_schema["properties"]["new_diagnostic"] = {
        "type": "string",
    }
    clause_schema["required"].append("new_diagnostic")

    changed = ModelFirstAnswerComposerService._schema_prompt_contract(
        mutated
    )

    assert changed["schema_sha256"] != original["schema_sha256"]
    assert changed["summary_sha256"] != original["summary_sha256"]
    assert "new_diagnostic:string" in changed["summary"]


def test_composer_accepts_legal_minimal_response_schema_object():
    reason, diagnostics = (
        ModelFirstAnswerComposerService
        ._validate_output_with_diagnostics(
            {"clauses": []},
            known_refs=set(),
            customer_goals=[],
            presentation_order=[],
            response=_response(),
        )
    )

    assert reason == ""
    assert diagnostics["category"] == "accepted"


@pytest.mark.parametrize(
    ("target", "field_name", "field_value"),
    [
        ("top", "reasoning", "hidden"),
        ("top", "explanation", "hidden"),
        ("top", "diagnostics", {}),
        ("top", "text", "misplaced"),
        ("clause", "extra_scalar", "value"),
        ("clause", "extra_object", {"value": "hidden"}),
        ("clause", "extra_array", ["hidden"]),
        ("clause", "reasoning", "hidden"),
        ("clause", "explanation", "hidden"),
        ("clause", "diagnostics", {}),
        ("clause", "context_stats", {}),
        ("clause", "selection_mode", "required"),
        ("clause", "policy_metadata", {"risk": "low"}),
        ("clause", "clauses", []),
    ],
)
def test_composer_rejects_schema_metadata_echo_mutations(
    target,
    field_name,
    field_value,
):
    payload = _valid_payload()
    mutation_target = (
        payload
        if target == "top"
        else payload["clauses"][0]
    )
    mutation_target[field_name] = field_value

    updated, result, client = _compose(payload)

    assert result["status"] == "provider_blocked"
    assert result["validation_diagnostics"]["category"] == (
        "extra_field"
    )
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert result["provider_diagnostics"]["json_repair_count"] == 0
    assert client.call_count == 1
    assert updated["suggested_reply"] == "旧回复"


def test_composer_excludes_supporting_only_dependency_from_customer_goals():
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"] = [
        _goal("goal-moisture", "moisture_resistance"),
        _goal(
            "goal-dependency",
            "material_composition",
            goal_kind="evidence_dependency",
            attribute_key="material",
            supporting_only=True,
            supporting_for_goal_ref="goal-moisture",
        ),
    ]
    context["admitted_evidence"] = []
    context["claim_resolutions"] = [
        _resolution(
            "claim-dependency",
            "material_composition",
            "unresolved",
            attribute_key="material",
            goal_kind="evidence_dependency",
            supporting_only=True,
            supporting_for_goal_ref="goal-moisture",
        ),
        _resolution(
            "claim-moisture",
            "moisture_resistance",
            "unresolved",
        ),
    ]
    payload = {
        "clauses": [{
            "goal_ref": "goal_01",
            "clause_kind": "unresolved",
            "text": "防潮表现目前无法确认。",
            "evidence_refs": [],
        }],
    }

    updated, result, client = _compose(payload, response)

    assert result["status"] == "accepted"
    assert result["covered_goal_refs"] == ["claim-moisture"]
    prompt = json.loads(client.messages[1]["content"])
    assert [
        item["claim_type"]
        for item in prompt["renderable_customer_goals"]
    ] == [
        "moisture_resistance",
    ]
    assert prompt["supporting_dependencies"] == [{
        "dependency_ref": "dependency_01",
        "supporting_for_goal_ref": "goal_01",
        "admitted_evidence_refs": [],
        "resolution_status": "unresolved",
        "provenance_status": "valid",
    }]
    assert prompt["presentation_order"] == ["goal_01"]
    assert updated["suggested_reply"] == "防潮表现目前无法确认。"


def _dependency_response() -> dict:
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"] = [
        _goal(
            "goal-primary",
            "generic_fact",
            attribute_key="generic_attribute",
        ),
        _goal(
            "goal-support",
            "supporting_fact",
            goal_kind="evidence_dependency",
            attribute_key="supporting_attribute",
            supporting_only=True,
            supporting_for_goal_ref="goal-primary",
        ),
    ]
    context["admitted_evidence"] = [{
        "evidence_uid": "ev-support",
        "fact_type": "supporting_fact",
        "attribute_key": "supporting_attribute",
        "content": "已审核支持事实",
    }]
    context["claim_resolutions"] = [
        _resolution(
            "claim-primary",
            "generic_fact",
            "supported",
            attribute_key="generic_attribute",
            evidence_uids=["ev-support"],
        ),
        _resolution(
            "claim-support",
            "supporting_fact",
            "supported",
            attribute_key="supporting_attribute",
            evidence_uids=["ev-support"],
            goal_kind="evidence_dependency",
            supporting_only=True,
            supporting_for_goal_ref="goal-primary",
        ),
    ]
    return response


def test_composer_dependency_evidence_is_bound_without_rendered_clause():
    response = _dependency_response()
    payload = {
        "clauses": [{
            "goal_ref": "goal_01",
            "clause_kind": "supported_fact",
            "text": "已确认该项信息。",
            "evidence_refs": ["E1"],
        }],
    }

    updated, result, client = _compose(payload, response)

    assert result["status"] == "accepted"
    assert updated["can_send"] is False
    assert result["input_eligibility"][
        "renderable_customer_goal_count"
    ] == 1
    assert result["input_eligibility"][
        "supporting_dependency_count"
    ] == 1
    assert result["input_eligibility"][
        "dependency_evidence_link_coverage"
    ] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    prompt = json.loads(client.messages[1]["content"])
    assert len(prompt["renderable_customer_goals"]) == 1
    assert prompt["supporting_dependencies"] == [{
        "dependency_ref": "dependency_01",
        "supporting_for_goal_ref": "goal_01",
        "admitted_evidence_refs": ["E1"],
        "resolution_status": "supported",
        "provenance_status": "valid",
    }]
    assert prompt["presentation_order"] == ["goal_01"]


def test_composer_input_partition_is_deterministic_for_mixed_goal_kinds():
    response = _dependency_response()
    context = response["minimal_decision_context"]
    context["requested_claims"].extend([
        _goal("goal-action", "", goal_kind="service_action"),
        _goal("goal-media", "", goal_kind="media_request"),
        _goal(
            "goal-constraint",
            "",
            goal_kind="contextual_constraint",
        ),
    ])
    context["claim_resolutions"].extend([
        _resolution(
            "claim-action",
            "",
            "unresolved",
            goal_kind="service_action",
        ),
        _resolution(
            "claim-media",
            "",
            "unresolved",
            goal_kind="media_request",
        ),
        _resolution(
            "claim-constraint",
            "",
            "unresolved",
            goal_kind="contextual_constraint",
        ),
    ])
    evidence, uid_by_ref = (
        ModelFirstAnswerComposerService._project_evidence(context)
    )
    assert evidence
    policies, policy_by_ref, policy_error = (
        ModelFirstAnswerComposerService._project_bounded_inference_policies(
            context
        )
    )
    assert policies == []
    assert policy_error == ""
    first, first_mapping, first_error = (
        ModelFirstAnswerComposerService._partition_composer_inputs(
            context,
            uid_by_ref,
            policy_by_ref,
            actual_media_types=[],
        )
    )
    reversed_context = deepcopy(context)
    reversed_context["requested_claims"].reverse()
    reversed_context["claim_resolutions"].reverse()
    second, second_mapping, second_error = (
        ModelFirstAnswerComposerService._partition_composer_inputs(
            reversed_context,
            uid_by_ref,
            policy_by_ref,
            actual_media_types=[],
        )
    )

    assert first_error == second_error == ""
    assert first_mapping == second_mapping
    assert (
        first["renderable_customer_goals"]
        == second["renderable_customer_goals"]
    )
    assert first["supporting_dependencies"] == second[
        "supporting_dependencies"
    ]
    assert first["eligibility_metrics"] == {
        "renderable_customer_goal_count": 1,
        "supporting_dependency_count": 1,
        "excluded_compatibility_dependency_count": 0,
        "non_customer_goal_clause_count": 0,
        "customer_goal_clause_coverage": {
            "numerator": 0,
            "denominator": 1,
            "rate": None,
        },
        "dependency_evidence_link_coverage": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0,
        },
        "unknown_goal_kind_count": 0,
    }


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda response: response["minimal_decision_context"][
                "requested_claims"
            ][1].update(supporting_for_goal_ref=""),
            "composer_dependency_binding_missing",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "requested_claims"
            ][1].update(supporting_for_goal_ref="goal-unknown"),
            "composer_dependency_target_unknown",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "requested_claims"
            ][0].update(goal_kind=""),
            "composer_goal_kind_missing",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "requested_claims"
            ][0].update(goal_kind="unknown_kind"),
            "composer_unknown_goal_kind",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "requested_claims"
            ][1].update(goal_ref="goal-primary"),
            "composer_goal_ref_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "requested_claims"
            ][0].update(owner="compatibility_owner"),
            "composer_goal_provenance_invalid",
        ),
    ],
)
def test_composer_fails_closed_on_goal_eligibility_mutations(
    mutate,
    reason,
):
    response = _dependency_response()
    mutate(response)
    client = _Client({"clauses": []})

    updated, result = ModelFirstAnswerComposerService().compose(
        response,
        customer_message="匿名通用问题",
        client=client,
    )

    assert result["rejection_reason"] == reason
    assert client.call_count == 0
    assert updated["suggested_reply"] == "旧回复"
    assert updated["can_send"] is True


def test_composer_rejects_dependency_ref_rendered_as_clause():
    response = _dependency_response()
    payload = {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "supported_fact",
                "text": "已确认该项信息。",
                "evidence_refs": ["E1"],
            },
            {
                "goal_ref": "dependency_01",
                "clause_kind": "supported_fact",
                "text": "支持信息也作为商品事实。",
                "evidence_refs": ["E1"],
            },
        ],
    }

    _, result, client = _compose(payload, response)

    assert result["rejection_reason"] == (
        "composer_non_renderable_goal_reference"
    )
    assert result["validation_diagnostics"]["category"] == (
        "non_renderable_goal_ref"
    )
    assert client.call_count == 1


@pytest.mark.parametrize(
    "goal_kind",
    ["service_action", "media_request", "contextual_constraint"],
)
def test_composer_rejects_non_customer_goal_ref_rendered_as_fact(
    goal_kind,
):
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"] = [
        _goal("goal-primary", "generic_fact"),
        _goal("goal-secondary", "", goal_kind=goal_kind),
    ]
    context["admitted_evidence"] = [{
        "evidence_uid": "ev-primary",
        "fact_type": "generic_fact",
        "attribute_key": "",
        "content": "已审核事实",
    }]
    context["claim_resolutions"] = [
        _resolution(
            "claim-primary",
            "generic_fact",
            "supported",
            evidence_uids=["ev-primary"],
        ),
        _resolution(
            "claim-secondary",
            "",
            "unresolved",
            goal_kind=goal_kind,
        ),
    ]
    payload = {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "supported_fact",
                "text": "已确认该项信息。",
                "evidence_refs": ["E1"],
            },
            {
                "goal_ref": "non_renderable_01",
                "clause_kind": "supported_fact",
                "text": "非客户目标被写成事实。",
                "evidence_refs": [],
            },
        ],
    }

    _, result, _ = _compose(payload, response)

    assert result["rejection_reason"] == (
        "composer_non_renderable_goal_reference"
    )


def test_composer_degraded_compatibility_claim_is_accepted_noop():
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"] = [{
        "goal_kind": "compatibility_claim",
        "claim_type": "generic_fact",
        "customer_goal_eligible": False,
    }]
    context["claim_resolutions"] = [{
        "claim_uid": "claim-compatibility",
        "goal_kind": "compatibility_claim",
        "claim_type": "generic_fact",
        "status": "supported",
        "evidence_uids": ["ev-width"],
    }]
    context["answer_eligibility_context"][
        "goal_understanding_status"
    ]["status"] = "degraded"

    updated, result, client = _compose({"clauses": []}, response)

    assert result["status"] == "accepted"
    assert result["composition_applicable"] is False
    assert result["clauses"] == []
    assert result["input_eligibility"][
        "renderable_customer_goal_count"
    ] == 0
    assert result["input_eligibility"][
        "non_customer_goal_clause_count"
    ] == 0
    assert result["used_for_final_reply"] is False
    assert result["provider_diagnostics"]["model_call_count"] == 0
    assert result["provider_diagnostics"][
        "decision_input_used_for_final_reply"
    ] is False
    assert updated["suggested_reply"] == "旧回复"
    assert updated["can_send"] is True
    assert client.call_count == 0


def test_composer_input_partition_does_not_modify_existing_audit_contracts():
    response = _response()
    response["final_answer_audit"] = {
        "passed": False,
        "issues": ["existing-final-issue"],
    }
    response["final_semantic_fit_audit"] = {
        "passed": False,
        "issues": ["existing-semantic-issue"],
    }
    before_final = deepcopy(response["final_answer_audit"])
    before_semantic = deepcopy(response["final_semantic_fit_audit"])

    updated, result, _ = _compose(_valid_payload(), response)

    assert result["status"] == "accepted"
    assert updated["final_answer_audit"] == before_final
    assert updated["final_semantic_fit_audit"] == before_semantic


def test_composer_excludes_legacy_unbound_supporting_only_compatibility_claim():
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"].append({
        "goal_kind": "",
        "goal_ref": "",
        "claim_type": "supporting_fact",
        "supporting_only": True,
    })
    context["claim_resolutions"].append({
        "claim_uid": "claim-legacy-support",
        "goal_kind": "",
        "goal_ref": "",
        "claim_type": "supporting_fact",
        "status": "unresolved",
        "supporting_only": True,
        "evidence_uids": [],
    })

    _, result, client = _compose(_valid_payload(), response)

    assert result["status"] == "accepted"
    assert result["input_eligibility"][
        "excluded_compatibility_dependency_count"
    ] == 1
    prompt = json.loads(client.messages[1]["content"])
    assert prompt["supporting_dependencies"] == []


@pytest.mark.parametrize(
    ("statuses", "expected_supported", "expected_unresolved"),
    [
        (
            [("material", "supported"), ("safety", "unresolved")],
            1,
            1,
        ),
        (
            [("width", "supported"), ("space_fit", "unresolved")],
            1,
            1,
        ),
        (
            [("gross_weight", "supported"), ("load_capacity", "unresolved")],
            1,
            1,
        ),
        (
            [
                ("width", "supported"),
                ("height", "supported"),
                ("space_fit", "unresolved"),
            ],
            2,
            1,
        ),
        (
            [
                ("material", "supported"),
                ("safety", "unresolved"),
                ("moisture", "unresolved"),
            ],
            1,
            2,
        ),
    ],
)
def test_composer_covers_generic_supported_and_unresolved_goal_mixes(
    statuses,
    expected_supported,
    expected_unresolved,
):
    response = _response()
    context = response["minimal_decision_context"]
    context["requested_claims"] = []
    context["admitted_evidence"] = []
    context["claim_resolutions"] = []
    payload = {"clauses": []}
    for index, (claim_type, status) in enumerate(statuses, start=1):
        claim_uid = f"claim-{index}"
        context["requested_claims"].append(_goal(
            f"goal-{index}",
            claim_type,
            attribute_key=claim_type,
        ))
        evidence_uids = []
        if status == "supported":
            evidence_uid = f"ev-{index}"
            evidence_uids = [evidence_uid]
            context["admitted_evidence"].append({
                "evidence_uid": evidence_uid,
                "fact_type": claim_type,
                "attribute_key": claim_type,
                "content": f"{claim_type}的已审核事实",
            })
        context["claim_resolutions"].append(_resolution(
            claim_uid,
            claim_type,
            status,
            attribute_key=claim_type,
            evidence_uids=evidence_uids,
        ))

    evidence_ref_by_uid = {
        item["evidence_uid"]: f"E{index}"
        for index, item in enumerate(
            sorted(
                context["admitted_evidence"],
                key=lambda item: item["evidence_uid"],
            ),
            start=1,
        )
    }
    for index, resolution in enumerate(
        sorted(context["claim_resolutions"], key=lambda item: item["claim_uid"]),
        start=1,
    ):
        supported = resolution["status"] == "supported"
        payload["clauses"].append({
            "goal_ref": f"goal_{index:02d}",
            "clause_kind": "supported_fact" if supported else "unresolved",
            "text": (
                f"{resolution['claim_type']}为已确认信息。"
                if supported
                else f"{resolution['claim_type']}目前无法确认。"
            ),
            "evidence_refs": [
                evidence_ref_by_uid[uid]
                for uid in resolution["evidence_uids"]
            ],
        })

    _, result, _ = _compose(payload, response)

    assert result["status"] == "accepted"
    assert len(result["clauses"]) == len(statuses)
    assert sum(
        item["clause_kind"] == "supported_fact" for item in result["clauses"]
    ) == expected_supported
    assert sum(
        item["clause_kind"] == "unresolved" for item in result["clauses"]
    ) == expected_unresolved


def test_composer_is_stable_when_context_input_order_changes():
    first = _response()
    second = deepcopy(first)
    second["minimal_decision_context"]["requested_claims"].reverse()
    second["minimal_decision_context"]["claim_resolutions"].reverse()
    second["minimal_decision_context"]["admitted_evidence"].reverse()

    first_updated, first_result, first_client = _compose(
        _valid_payload(),
        first,
    )
    second_updated, second_result, second_client = _compose(
        _valid_payload(),
        second,
    )

    assert first_result["status"] == second_result["status"] == "accepted"
    assert first_result["covered_goal_refs"] == second_result["covered_goal_refs"]
    assert first_result["clauses"] == second_result["clauses"]
    assert first_updated["suggested_reply"] == second_updated["suggested_reply"]
    assert (
        json.loads(first_client.messages[1]["content"])[
            "renderable_customer_goals"
        ]
        == json.loads(second_client.messages[1]["content"])[
            "renderable_customer_goals"
        ]
    )


def test_composer_rejects_service_action_or_media_as_extra_goal():
    response = _response()
    context = response["minimal_decision_context"]
    context["service_actions"] = [{"action": "check_order"}]
    context["available_media_candidates"] = [{"type": "video"}]
    payload = _valid_payload()
    payload["clauses"].append({
        "goal_ref": "goal_03",
        "clause_kind": "service_action",
        "text": "为您查询订单。",
        "evidence_refs": [],
    })

    _, result, _ = _compose(payload, response)

    assert result["rejection_reason"] == "composer_unknown_goal_reference"


def test_composer_requires_minimal_context():
    original = {"suggested_reply": "旧回复", "can_send": False}

    updated, result = ModelFirstAnswerComposerService().compose(
        original,
        customer_message="这个多宽",
        client=_Client({}),
    )

    assert updated == original
    assert result["rejection_reason"] == "minimal_decision_context_missing"


@pytest.mark.parametrize("payload", ["not-json", {"reply": "legacy"}])
def test_composer_fails_closed_on_provider_or_schema_error(payload):
    updated, result, client = _compose(payload)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] in {
        "composer_fenced_or_free_text",
        "composer_schema_invalid",
    }
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1


def test_composer_fails_closed_on_provider_truncation_without_retry():
    client = _RaisingClient({})

    updated, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == "formal_llm_error:RuntimeError"
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1


@pytest.mark.parametrize(
    ("payload", "finish_reason", "reason", "category", "envelope"),
    [
        (
            None,
            "stop",
            "composer_completion_empty",
            "completion_empty",
            "empty",
        ),
        (
            '{"clauses": [',
            "length",
            "composer_truncated_response",
            "truncated_response",
            "json_fragment",
        ),
        (
            "not-json",
            "stop",
            "composer_fenced_or_free_text",
            "free_text_response",
            "invalid",
        ),
        (
            '{"clauses":',
            "stop",
            "composer_json_parse_error",
            "json_parse_error",
            "raw_json",
        ),
    ],
)
def test_composer_reports_sanitized_provider_completion_diagnostics(
    payload,
    finish_reason,
    reason,
    category,
    envelope,
):
    client = _Client(payload, finish_reason=finish_reason)

    updated, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert updated["suggested_reply"] == "旧回复"
    assert result["rejection_reason"] == reason
    assert result["validation_diagnostics"]["category"] == category
    assert result["provider_diagnostics"]["response_envelope"] == envelope
    assert result["provider_diagnostics"]["response_length"] == len(payload or "")
    assert result["provider_diagnostics"]["response_sha256"]
    assert result["provider_diagnostics"]["finish_reason"] == finish_reason
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert result["provider_diagnostics"]["json_repair_count"] == 0
    assert result["provider_diagnostics"]["provider_latency_ms"] >= 0
    assert client.kwargs["_single_attempt_no_repair"] is True
    rendered = json.dumps(result, ensure_ascii=False)
    if payload:
        assert str(payload) not in rendered


@pytest.mark.parametrize(
    ("wrap", "expected_envelope", "expected_unwrap_count"),
    [
        (lambda value: value, "raw_json", 0),
        (lambda value: f"```json\n{value}\n```", "single_json_fence", 1),
        (lambda value: f"```\n{value}\n```", "single_json_fence", 1),
        (lambda value: f" \n```json\n{value}\n```\n ", "single_json_fence", 1),
    ],
)
def test_composer_accepts_only_bounded_json_envelopes(
    wrap,
    expected_envelope,
    expected_unwrap_count,
):
    raw = json.dumps(
        _with_policy_selection_fields(_valid_payload()),
        ensure_ascii=False,
    )

    updated, result, client = _compose(wrap(raw))

    assert result["status"] == "accepted"
    assert result["provider_diagnostics"]["response_envelope"] == expected_envelope
    assert (
        result["provider_diagnostics"]["envelope_unwrap_count"]
        == expected_unwrap_count
    )
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert result["provider_diagnostics"]["json_repair_count"] == 0
    assert updated["can_send"] is False
    assert updated["requires_human_review"] is True
    assert updated["sendable_reply"] == ""
    assert client.call_count == 1


def test_composer_raw_and_fenced_json_have_identical_canonical_clauses():
    raw = json.dumps(
        _with_policy_selection_fields(_valid_payload()),
        ensure_ascii=False,
    )

    raw_updated, raw_result, _ = _compose(raw)
    fenced_updated, fenced_result, _ = _compose(f"```json\n{raw}\n```")

    assert raw_result["status"] == fenced_result["status"] == "accepted"
    assert raw_result["clauses"] == fenced_result["clauses"]
    assert raw_result["used_evidence_uids"] == fenced_result["used_evidence_uids"]
    assert raw_updated["suggested_reply"] == fenced_updated["suggested_reply"]


@pytest.mark.parametrize(
    "payload",
    [
        "说明如下：\n```json\n{}\n```",
        "```json\n{}\n```\n以上是结果。",
        "```json\n{}\n```\n```json\n{}\n```",
        "```json\n[]\n```",
        "```json\nnot-json\n```",
        "```json\n{}\n",
        '{"clauses": [',
        '结果是 {"clauses": []}',
        "reasoning only",
        "- clauses: []",
        "{'clauses': []}",
        '{"clauses": [],}',
        '{"clauses": [/* comment */]}',
        '{"clauses": []} {"clauses": []}',
    ],
)
def test_composer_rejects_unbounded_or_repaired_json_envelopes(payload):
    updated, result, client = _compose(payload)

    assert result["status"] == "provider_blocked"
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert result["provider_diagnostics"]["json_repair_count"] == 0
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("clauses"),
        lambda value: value.update(extra="not-allowed"),
        lambda value: value["clauses"][0].pop("text"),
        lambda value: value["clauses"][0].update(extra="not-allowed"),
        lambda value: value["clauses"][0].update(
            clause_kind="not_a_clause_kind"
        ),
        lambda value: value["clauses"][0].update(goal_ref="goal_unknown"),
        lambda value: value["clauses"].append(deepcopy(value["clauses"][0])),
    ],
)
def test_composer_fenced_json_still_requires_strict_clause_schema(mutate):
    payload = _with_policy_selection_fields(_valid_payload())
    mutate(payload)
    fenced = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"

    updated, result, client = _compose(fenced)

    assert result["status"] == "provider_blocked"
    assert result["provider_diagnostics"]["response_envelope"] == (
        "single_json_fence"
    )
    assert result["provider_diagnostics"]["envelope_unwrap_count"] == 1
    assert result["provider_diagnostics"]["json_repair_count"] == 0
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1


@pytest.mark.parametrize(
    ("mutate", "reason", "category", "path"),
    [
        (
            lambda value: value.update(extra="not-allowed"),
            "composer_schema_invalid",
            "extra_field",
            "$",
        ),
        (
            lambda value: value.pop("clauses"),
            "composer_schema_invalid",
            "top_level_schema_invalid",
            "$",
        ),
        (
            lambda value: value["clauses"][0].update(extra="not-allowed"),
            "composer_clause_schema_invalid",
            "extra_field",
            "$.clauses[0]",
        ),
        (
            lambda value: value["clauses"][0].pop("text"),
            "composer_clause_schema_invalid",
            "clause_schema_invalid",
            "$.clauses[0]",
        ),
        (
            lambda value: value["clauses"].pop(0),
            "composer_goal_clause_omitted",
            "missing_goal_clause",
            "$.clauses",
        ),
        (
            lambda value: value["clauses"].append(
                deepcopy(value["clauses"][0])
            ),
            "composer_duplicate_goal_clause",
            "duplicate_goal_clause",
            "$.clauses[2].goal_ref",
        ),
        (
            lambda value: value["clauses"][0].update(goal_ref="goal_99"),
            "composer_unknown_goal_reference",
            "unknown_goal_ref",
            "$.clauses[0].goal_ref",
        ),
    ],
)
def test_composer_reports_field_level_schema_diagnostics(
    mutate,
    reason,
    category,
    path,
):
    payload = _valid_payload()
    mutate(payload)

    _, result, client = _compose(payload)

    diagnostics = result["validation_diagnostics"]
    assert result["rejection_reason"] == reason
    assert diagnostics["category"] == category
    assert diagnostics["json_path"] == path
    assert diagnostics["clause_count"] >= 0
    assert diagnostics["goal_ref_count"] >= 0
    assert diagnostics["evidence_ref_count"] >= 0
    assert "actual_value" not in diagnostics
    assert "field_value" not in diagnostics
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert client.kwargs["_single_attempt_no_repair"] is True


@pytest.mark.parametrize(
    "clause_kind",
    ["supported_fact", "unresolved", "allowed_inference",
     "empathy_or_transition", "service_action"],
)
def test_composer_rejects_server_owned_clause_kind_in_model_output(
    clause_kind,
):
    payload = _valid_payload()
    payload["clauses"][1].update({
        "clause_kind": clause_kind,
        "text": "商品宽度为80厘米，相关动作已经完成。",
    })

    _, result, _ = _compose(
        payload,
        normalize_policy_fields=False,
    )

    assert result["rejection_reason"] == "composer_clause_schema_invalid"
    assert result["validation_diagnostics"]["category"] == "extra_field"


def test_composer_timeout_is_provider_error_without_retry_or_repair():
    client = _TimeoutClient({})

    updated, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert updated["suggested_reply"] == "旧回复"
    assert result["rejection_reason"] == "formal_llm_error:TimeoutError"
    assert result["validation_diagnostics"]["category"] == "provider_error"
    assert result["provider_diagnostics"]["provider_error_type"] == "TimeoutError"
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert client.call_count == 1


def _media_goal_response() -> dict:
    response = _response()
    context = response["minimal_decision_context"]
    context["customer_goal"] = "查看当前商品的尺寸标注资料"
    context["requested_claims"] = [_goal(
        "goal-size-diagram",
        "dimensions",
        goal_kind="media_request",
        attribute_key="size_diagram",
    )]
    context["admitted_evidence"] = []
    context["claim_resolutions"] = [{
        **_resolution(
            "claim-size-diagram",
            "dimensions",
            "unresolved",
            attribute_key="size_diagram",
            goal_kind="media_request",
        ),
    }]
    context["media_candidates"] = [{
        "evidence_uid": "media-candidate",
        "asset_type": "size_image",
        "media_role": "dimension_reference",
        "non_fact": True,
    }]
    response["query_fact_type"] = "dimensions"
    response["sku_code"] = "private-sku"
    return response


def _media_goal_payload(text: str) -> dict:
    return {
        "clauses": [{
            "goal_ref": "non_renderable_01",
            "clause_kind": "unresolved",
            "text": text,
            "evidence_refs": [],
        }],
    }


def test_composer_rejects_media_delivery_without_explicit_media_goal():
    response = _response()
    response["query_fact_type"] = "dimensions"
    response["sku_code"] = "private-sku"
    response["reply_blocks"].append({
        "type": "image",
        "url": "https://static.invalid/size.png",
        "asset_type": "size_image",
        "status": "approved",
        "usable_for_agent": True,
        "sku_code": "private-sku",
    })
    payload = _valid_payload()
    payload["clauses"][0]["text"] = "儿童安全无法确认，尺寸图已发，请查看。"

    _, result, _ = _compose(payload, response)

    assert result["rejection_reason"] == "composer_unsupported_media_promise"
    assert result["media_claim_diagnostics"]["goal_is_media_request"] is False


def test_composer_skips_provider_for_media_only_request_without_block():
    response = _media_goal_response()

    updated, result, client = _compose(
        _media_goal_payload("尺寸图已发，请查看。"),
        response,
    )

    assert result["status"] == "accepted"
    assert result["composition_applicable"] is False
    assert result["used_for_final_reply"] is False
    assert result["clauses"] == []
    assert result["provider_diagnostics"]["model_call_count"] == 0
    assert client.call_count == 0
    assert updated["suggested_reply"] == response["suggested_reply"]


def test_composer_skips_provider_for_media_only_request_with_wrong_identity():
    response = _media_goal_response()
    response["reply_blocks"].append({
        "type": "image",
        "url": "https://static.invalid/size.png",
        "asset_type": "size_image",
        "status": "approved",
        "usable_for_agent": True,
        "sku_code": "different-sku",
    })

    updated, result, client = _compose(
        _media_goal_payload("尺寸图已发，请查看。"),
        response,
    )

    assert result["status"] == "accepted"
    assert result["composition_applicable"] is False
    assert result["used_for_final_reply"] is False
    assert result["provider_diagnostics"]["model_call_count"] == 0
    assert client.call_count == 0
    assert updated["suggested_reply"] == response["suggested_reply"]


def test_composer_skips_provider_for_media_only_request_with_eligible_block():
    response = _media_goal_response()
    response["reply_blocks"].append({
        "type": "image",
        "url": "https://static.invalid/size.png",
        "asset_type": "size_image",
        "status": "approved",
        "usable_for_agent": True,
        "sku_code": "private-sku",
    })

    updated, result, client = _compose(
        _media_goal_payload("尺寸图已发，请查看。"),
        response,
    )

    assert result["status"] == "accepted"
    assert result["composition_applicable"] is False
    assert result["used_for_final_reply"] is False
    assert result["clauses"] == []
    assert updated["can_send"] is True
    assert result["provider_diagnostics"]["model_call_count"] == 0
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert client.call_count == 0


def _bounded_inference_response() -> dict:
    policy_ref = (
        "domain-policy:fixture_domain@1.0.0:"
        "intent:product_durability_practical_guidance"
    )
    return {
        "suggested_reply": "旧回复",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "旧回复"}],
        "minimal_decision_context": {
            "customer_goal": "材质和日常耐用边界怎么样",
            "product_identity": {"sku_code": "private-sku"},
            "requested_claims": [
                _goal(
                    "goal-material",
                    "material_composition",
                    attribute_key="material",
                ),
                _goal(
                    "goal-durability",
                    "",
                    attribute_key="drop_durability",
                    claim_type_status="unmapped",
                ),
            ],
            "admitted_evidence": [{
                "evidence_uid": "ev-material",
                "fact_type": "material_composition",
                "attribute_key": "material",
                "content": "主体为通用聚合物材料",
            }],
            "claim_resolutions": [
                _resolution(
                    "claim-durability",
                    "",
                    "unresolved",
                    attribute_key="drop_durability",
                    claim_type_status="unmapped",
                    eligible_policy_options=[{
                        "policy_ref": policy_ref,
                        "trusted_domain_pack_ref": (
                            "domain-policy:fixture_domain@1.0.0"
                        ),
                        "pack_content_sha256": _DOMAIN_PACK_HASH,
                        "applicable_goal_ref": "goal-durability",
                        "policy_intent_ref": (
                            "product_durability_practical_guidance"
                        ),
                        "goal_family": "product_durability",
                        "intent_kind": "practical_guidance",
                        "premise_evidence_refs": ["ev-material"],
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
                        "required_qualifiers": [
                            "no_absolute_guarantee"
                        ],
                        "review_only": True,
                        "used_for_evidence": False,
                        "used_for_fact_support": False,
                        "can_change_can_send": False,
                        "option_provenance": {
                            "policy_owner": "domain_policy_pack",
                            "filter_owner": "claim_resolution",
                            "premise_owner": (
                                "admitted_answer_context"
                            ),
                            "intent_narrowed": True,
                        },
                    }],
                ),
                _resolution(
                    "claim-material",
                    "material_composition",
                    "supported",
                    attribute_key="material",
                    evidence_uids=["ev-material"],
                    support_basis="direct_evidence",
                ),
            ],
            "bounded_inference_policies": [{
                "policy_ref": policy_ref,
                "pack_content_sha256": _DOMAIN_PACK_HASH,
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
                "used_for_evidence": False,
                "used_for_fact_support": False,
                "can_change_can_send": False,
            }],
            "trusted_domain_policy_context": {
                "schema_version": "trusted-domain-policy-context/v1",
                "status": "selected",
                "trusted_owner": "analysis_pipeline",
                "selection_source": "evaluation_fixture",
                "pack_ref": "domain-policy:fixture_domain@1.0.0",
                "pack_schema_version": "domain-policy-pack/v1",
                "pack_content_sha256": _DOMAIN_PACK_HASH,
                "domain_ref": "domain-fixture",
                "binding_summary": {
                    "tenant": False,
                    "store": False,
                    "catalog": True,
                },
                "provenance": {
                    "boundary": "analysis_pipeline_internal",
                    "selector_owner": "file_policy_repository",
                },
                "selected_at_stage": "canonical_input",
                "validation_reasons": [],
                "used_for_evidence": False,
                "used_for_fact_support": False,
                "can_change_can_send": False,
            },
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 50},
        },
    }


def _oral_safety_response() -> dict:
    response = _bounded_inference_response()
    minimal = response["minimal_decision_context"]
    goal = minimal["requested_claims"][1]
    goal.update({
        "claim_type": "bite_or_toxicity",
        "claim_type_status": "mapped",
        "attribute_key": "bite_or_toxicity",
        "semantic_key": "bite_or_toxicity",
        "goal_summary": "handle possible oral exposure without claiming safety",
        "risk_level": "high",
        "policy_intent_ref": "",
        "policy_goal_family": "bite_or_toxicity",
        "policy_intent_kind": "practical_guidance",
    })
    minimal["requested_claims"] = [goal]
    minimal["admitted_evidence"] = []

    resolution = minimal["claim_resolutions"][0]
    boundary = {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "high_risk_factual_claim_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": "",
        "policy_goal_family": "bite_or_toxicity",
        "policy_intent_kind": "practical_guidance",
        "high_risk_claim_families": ["bite_or_toxicity"],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    policy_ref = (
        "domain-policy:fixture_domain@1.0.0:"
        "intent:oral_exposure_safety_handling"
    )
    option = resolution["eligible_policy_options"][0]
    option.update({
        "policy_ref": policy_ref,
        "applicable_goal_ref": goal["goal_ref"],
        "policy_intent_ref": "oral_exposure_safety_handling",
        "goal_family": "bite_or_toxicity",
        "premise_evidence_refs": [],
        "premise_families": [],
        "allowed_scope": "interrupt_exposure_inspect_and_escalate_if_needed",
        "allowed_conclusion_family": "general_oral_exposure_risk_mitigation",
        "allowed_variability_factor_families": [],
        "advice_mode": "safety_handoff_required",
        "forbidden_claim_families": [
            "bite_or_toxicity",
            "child_safety",
            "material_safety",
            "non_toxic_claim",
        ],
        "requested_risk": "high",
        "requested_claim_risk": "high",
        "answer_strategy_risk": "medium",
        "required_qualifiers": [
            "stop_further_oral_contact",
            "inspect_for_damage_or_missing_fragments",
            "seek_medical_help_if_ingested_or_symptomatic",
            "no_toxicity_or_ingestion_safety_conclusion",
        ],
        "restricted_request_boundary": boundary,
        "option_provenance": {
            "policy_owner": "domain_policy_pack",
            "filter_owner": "claim_resolution",
            "premise_owner": "authoritative_customer_goal",
            "intent_narrowed": False,
            "alternative_for_restricted_request": True,
        },
    })
    resolution.update({
        "goal_ref": goal["goal_ref"],
        "claim_type": "bite_or_toxicity",
        "claim_type_status": "mapped",
        "attribute_key": "bite_or_toxicity",
        "status": "unresolved",
        "reason": "high_risk_factual_claim_prohibited",
        "requested_claim_risk": "high",
        "evidence_uids": [],
        "premise_evidence_uids": [],
        "restricted_request_boundary": boundary,
        "eligible_policy_options": [option],
    })
    minimal["claim_resolutions"] = [resolution]
    policy = minimal["bounded_inference_policies"][0]
    policy.update({
        "policy_ref": policy_ref,
        "policy_intent_ref": "oral_exposure_safety_handling",
        "goal_family": "bite_or_toxicity",
        "premise_fact_families": [],
        "allowed_scope": "interrupt_exposure_inspect_and_escalate_if_needed",
        "allowed_conclusion_family": "general_oral_exposure_risk_mitigation",
        "allowed_variability_factor_families": [],
        "advice_mode": "safety_handoff_required",
        "required_qualifiers": list(option["required_qualifiers"]),
        "prohibited_claim_families": list(
            option["forbidden_claim_families"]
        ),
    })
    minimal["bounded_inference_policies"] = [policy]
    return response


def _offered_projection(
    response: dict,
) -> tuple[list[dict], dict[str, dict]]:
    service = ModelFirstAnswerComposerService()
    minimal = service._minimal_context(response)
    _, uid_by_ref = service._project_evidence(minimal)
    policies, policy_by_ref, policy_error = (
        service._project_bounded_inference_policies(minimal)
    )
    assert policy_error == ""
    assert policies
    partitions, _, partition_error = (
        service._partition_composer_inputs(
            minimal,
            uid_by_ref,
            policy_by_ref,
            actual_media_types=[],
        )
    )
    assert partition_error == ""
    goals, bindings, offered_error = (
        service._build_goal_scoped_offered_projection(
            partitions["renderable_customer_goals"]
        )
    )
    assert offered_error == ""
    return goals, bindings


def _option_alias(
    response: dict,
    *,
    goal_ref: str,
    allowed_scope: str,
) -> str:
    goals, _ = _offered_projection(response)
    goal = next(item for item in goals if item["goal_ref"] == goal_ref)
    option = next(
        item
        for item in goal["eligible_policy_options"]
        if item["allowed_scope"] == allowed_scope
    )
    return str(option["option_ref"])


def _validate_with_offered_projection(
    response: dict,
    payload: dict,
) -> tuple[str, dict]:
    goals, bindings = _offered_projection(response)
    known_refs = {
        str(ref)
        for goal in goals
        for ref in (
            list(goal.get("required_evidence_refs") or [])
            + [
                premise_ref
                for option in goal.get("eligible_policy_options") or []
                for premise_ref in (
                    option.get("premise_evidence_refs") or []
                )
            ]
        )
        if str(ref)
    }
    return ModelFirstAnswerComposerService._validate_output_with_diagnostics(
        _with_policy_selection_fields(payload),
        known_refs=known_refs,
        customer_goals=goals,
        response=response,
        offered_option_bindings=bindings,
    )


def _bounded_inference_payload(
    response: dict | None = None,
) -> dict:
    source = response or _bounded_inference_response()
    return {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "allowed_inference",
                "text": "日常轻微意外一般不用过度担心，但不能保证耐摔。",
                "evidence_refs": ["E1"],
                "selected_policy_ref": _option_alias(
                    source,
                    goal_ref="goal_01",
                    allowed_scope=(
                        "ordinary_minor_accidental_impact"
                    ),
                ),
                "premise_evidence_refs": ["E1"],
                "inference_scope": "ordinary_minor_accidental_impact",
            },
            {
                "goal_ref": "goal_02",
                "clause_kind": "supported_fact",
                "text": "主体为通用聚合物材料。",
                "evidence_refs": ["E1"],
            },
        ],
    }


def _with_restricted_request_strategy(response: dict) -> dict:
    boundary = {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "absolute_guarantee_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": (
            "product_durability_absolute_guarantee"
        ),
        "policy_goal_family": "product_durability",
        "policy_intent_kind": "absolute_guarantee",
        "high_risk_claim_families": [],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    resolution = response["minimal_decision_context"][
        "claim_resolutions"
    ][0]
    resolution["requested_claim_risk"] = "high"
    resolution["restricted_request_boundary"] = boundary
    option = resolution["eligible_policy_options"][0]
    option["requested_risk"] = "high"
    option["requested_claim_risk"] = "high"
    option["answer_strategy_risk"] = "medium"
    option["restricted_request_boundary"] = boundary
    option["option_provenance"][
        "alternative_for_restricted_request"
    ] = True
    option["option_provenance"]["intent_narrowed"] = False
    return response


def _add_alternate_safe_option(
    response: dict,
    *,
    resolution_index: int = 0,
) -> str:
    policy_ref = (
        "domain-policy:fixture_domain@1.0.0:"
        "intent:material_daily_use_practical_guidance"
    )
    minimal = response["minimal_decision_context"]
    resolution = minimal["claim_resolutions"][resolution_index]
    option = deepcopy(
        minimal["claim_resolutions"][0]["eligible_policy_options"][0]
    )
    option.update({
        "policy_ref": policy_ref,
        "applicable_goal_ref": resolution["goal_ref"],
        "policy_intent_ref": "material_daily_use_practical_guidance",
        "goal_family": "material_daily_use",
        "allowed_scope": "ordinary_daily_material_handling",
    })
    resolution.setdefault("eligible_policy_options", []).append(option)
    policy = deepcopy(minimal["bounded_inference_policies"][0])
    policy.update({
        "policy_ref": policy_ref,
        "policy_intent_ref": "material_daily_use_practical_guidance",
        "goal_family": "material_daily_use",
        "allowed_scope": "ordinary_daily_material_handling",
    })
    minimal["bounded_inference_policies"].append(policy)
    return policy_ref


def test_composer_accepts_policy_bounded_inference_with_canonical_attribution():
    updated, result, client = _compose(
        _bounded_inference_payload(),
        _bounded_inference_response(),
    )

    assert result["status"] == "accepted"
    assert result["can_send"] is False
    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    bounded = next(
        item for item in result["clauses"]
        if item["clause_kind"] == "allowed_inference"
    )
    assert bounded["evidence_uids"] == ["ev-material"]
    assert bounded["inference_policy_refs"] == [
        "domain-policy:fixture_domain@1.0.0:"
        "intent:product_durability_practical_guidance"
    ]
    assert bounded["scope_qualifier"] == "ordinary_minor_accidental_impact"
    assert bounded["inference_risk_level"] == "medium"
    assert bounded["maximum_risk_level"] == "medium"
    assert bounded["allowed_conclusion_family"] == (
        "ordinary_minor_impact_tolerance"
    )
    assert bounded["allowed_variability_factor_families"] == [
        "contact_surface",
        "impact_angle",
        "impact_height",
    ]
    assert bounded["advice_mode"] == "none"
    assert bounded["inference_review_only"] is True
    assert bounded["prohibited_extensions"] == [
        "certification_report",
        "child_safety",
        "warranty",
    ]
    prompt = json.loads(client.messages[1]["content"])
    inferred_goal = next(
        item for item in prompt["renderable_customer_goals"]
        if item["eligible_policy_options"]
    )
    assert inferred_goal["option_selection_mode"] == "required"
    assert {
        item["option_selection_mode"]
        for item in prompt["renderable_customer_goals"]
        if not item["eligible_policy_options"]
    } == {"forbidden"}
    assert [
        item["option_ref"]
        for item in inferred_goal["eligible_policy_options"]
    ] == sorted(
        item["option_ref"]
        for item in inferred_goal["eligible_policy_options"]
    )
    assert "bounded_inference_policies" not in prompt
    assert "allowed_low_risk_reasoning" not in prompt
    assert "domain-policy:" not in client.messages[1]["content"]
    option = inferred_goal["eligible_policy_options"][0]
    assert option["requested_claim_risk"] == "medium"
    assert option["maximum_risk_level"] == "medium"
    assert option["allowed_conclusion_family"] == (
        "ordinary_minor_impact_tolerance"
    )
    assert option["allowed_variability_factor_families"] == [
        "contact_surface",
        "impact_angle",
        "impact_height",
    ]
    assert option["advice_mode"] == "none"
    assert option["review_only"] is True
    diagnostics = result["provider_diagnostics"]
    for field in (
        "system_prompt_sha256",
        "prompt_payload_sha256",
        "provider_input_sha256",
        "offered_projection_sha256",
        "output_contract_sha256",
        "response_schema_sha256",
        "prompt_schema_summary_sha256",
    ):
        assert len(diagnostics[field]) == 64
    assert diagnostics["offered_goal_refs"] == ["goal_01", "goal_02"]
    assert diagnostics["offered_option_refs"] == [
        option["option_ref"]
    ]
    assert diagnostics["model_call_count"] == 1
    assert diagnostics["retry_count"] == 0
    assert diagnostics["repair_count"] == 0


def test_composer_accepts_goal_owned_oral_safety_handling_without_evidence():
    response = _oral_safety_response()
    option_ref = _option_alias(
        response,
        goal_ref="goal_01",
        allowed_scope="interrupt_exposure_inspect_and_escalate_if_needed",
    )
    updated, result, client = _compose(
        {
            "clauses": [{
                "goal_ref": "goal_01",
                "text": (
                    "先别让孩子继续咬，看看有没有破损或缺口；如果有误吞或不舒服，及时就医。"
                    "单凭现有信息不能判断它入口是否安全。"
                ),
                "selected_option_refs": [option_ref],
            }],
        },
        response,
    )

    assert result["status"] == "accepted"
    assert client.call_count == 1
    clause = result["clauses"][0]
    assert clause["clause_kind"] == "allowed_inference"
    assert clause["evidence_uids"] == []
    assert clause["premise_evidence_uids"] == []
    assert clause["advice_mode"] == "safety_handoff_required"
    assert clause["requested_claim_risk_level"] == "high"
    assert clause["restricted_request_boundary"][
        "must_remain_unresolved"
    ] is True
    assert clause["inference_policy_refs"] == [
        "domain-policy:fixture_domain@1.0.0:"
        "intent:oral_exposure_safety_handling"
    ]
    assert updated["can_send"] is False
    prompt = json.loads(client.messages[1]["content"])
    goal = prompt["renderable_customer_goals"][0]
    assert goal["option_selection_mode"] == "required"
    assert goal["eligible_policy_options"][0][
        "premise_evidence_refs"
    ] == []


def test_composer_accepts_bounded_strategy_without_erasing_request_boundary():
    response = _with_restricted_request_strategy(
        _bounded_inference_response()
    )
    updated, result, client = _compose(
        _bounded_inference_payload(response),
        response,
    )

    assert result["status"] == "accepted"
    bounded = next(
        item
        for item in result["clauses"]
        if item["clause_kind"] == "allowed_inference"
    )
    assert bounded["requested_claim_risk_level"] == "high"
    assert bounded["inference_risk_level"] == "medium"
    assert bounded["maximum_risk_level"] == "medium"
    assert bounded["restricted_request_boundary"][
        "must_remain_unresolved"
    ] is True
    prompt = json.loads(client.messages[1]["content"])
    goal = next(
        item
        for item in prompt["renderable_customer_goals"]
        if item["restricted_request_boundary"]
    )
    assert goal["resolution_status"] == "unresolved"
    assert goal["requested_claim_risk"] == "high"
    assert goal["eligible_policy_options"][0][
        "answer_strategy_risk"
    ] == "medium"
    assert updated["can_send"] is False
    assert updated["requires_human_review"] is True


def test_composer_preserves_explicit_prohibition_without_strategy_option():
    response = _with_restricted_request_strategy(
        _bounded_inference_response()
    )
    resolution = response["minimal_decision_context"][
        "claim_resolutions"
    ][0]
    boundary = resolution["restricted_request_boundary"]
    boundary.update({
        "reason_code": "direct_handling_prohibited",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "allows_bounded_alternative": False,
    })
    resolution.update({
        "status": "prohibited",
        "reason": "direct_handling_prohibited",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "eligible_policy_options": [],
    })
    payload = _bounded_inference_payload()
    payload["clauses"][0] = {
        "goal_ref": "goal_01",
        "clause_kind": "unresolved",
        "text": "该项不能作肯定承诺。",
        "evidence_refs": [],
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    }

    updated, result, _ = _compose(payload, response)

    assert result["status"] == "accepted"
    assert result["clauses"][0]["clause_kind"] == "unresolved"
    assert result["clauses"][0]["restricted_request_boundary"] == {}
    assert updated["can_send"] is False
    assert updated["requires_human_review"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda resolution, option: resolution.update({
            "restricted_request_boundary": {},
        }),
        lambda resolution, option: option.update({
            "restricted_request_boundary": {},
        }),
        lambda resolution, option: option.update({
            "answer_strategy_risk": "high",
        }),
        lambda resolution, option: option.update({
            "requested_claim_risk": "medium",
        }),
        lambda resolution, option: option[
            "option_provenance"
        ].update({
            "alternative_for_restricted_request": False,
        }),
    ],
)
def test_composer_rejects_restricted_request_contract_mutation(mutation):
    response = _with_restricted_request_strategy(
        _bounded_inference_response()
    )
    resolution = response["minimal_decision_context"][
        "claim_resolutions"
    ][0]
    mutation(resolution, resolution["eligible_policy_options"][0])
    original_reply = response["suggested_reply"]

    updated, result, _ = _compose(
        _bounded_inference_payload(),
        response,
    )

    assert result["status"] == "provider_blocked"
    assert updated["suggested_reply"] == original_reply


def test_composer_rejects_required_goal_without_policy_selection():
    payload = _bounded_inference_payload()
    payload["clauses"][0].update({
        "clause_kind": "unresolved",
        "text": "日常耐用边界目前无法确认。",
        "evidence_refs": [],
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    })

    updated, result, client = _compose(
        payload,
        _bounded_inference_response(),
    )

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_required_option_not_selected"
    )
    assert result["validation_diagnostics"]["category"] == (
        "required_option_not_selected"
    )
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


def test_composer_allows_unresolved_goal_to_decline_unnarrowed_options():
    response = _bounded_inference_response()
    option = response["minimal_decision_context"][
        "claim_resolutions"
    ][0]["eligible_policy_options"][0]
    option["option_provenance"]["intent_narrowed"] = False
    payload = _bounded_inference_payload(response)
    payload["clauses"][0].update({
        "clause_kind": "unresolved",
        "text": "日常耐用表现目前无法确认。",
        "evidence_refs": [],
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    })

    _, result, client = _compose(payload, response)

    assert result["status"] == "accepted"
    prompt = json.loads(client.messages[1]["content"])
    inferred_goal = next(
        item
        for item in prompt["renderable_customer_goals"]
        if item["eligible_policy_options"]
    )
    assert inferred_goal["option_selection_mode"] == "optional"
    assert client.call_count == 1


def test_composer_allows_optional_goal_to_select_zero_or_one_option():
    response = _bounded_inference_response()
    selected_policy_ref = _add_alternate_safe_option(
        response,
        resolution_index=1,
    )
    zero_selection_payload = _bounded_inference_payload(response)

    _, zero_result, zero_client = _compose(
        zero_selection_payload,
        response,
    )

    assert zero_result["status"] == "accepted"
    zero_prompt = json.loads(zero_client.messages[1]["content"])
    optional_goal = next(
        item
        for item in zero_prompt["renderable_customer_goals"]
        if item["option_selection_mode"] == "optional"
    )
    assert optional_goal["goal_ref"] == "goal_02"
    assert len(optional_goal["eligible_policy_options"]) == 1

    one_selection_payload = _bounded_inference_payload(response)
    one_selection_payload["clauses"][1].update({
        "clause_kind": "allowed_inference",
        "text": "主体材质已确认，日常使用仍需避免反复冲击。",
        "evidence_refs": ["E1"],
        "selected_policy_ref": _option_alias(
            response,
            goal_ref="goal_02",
            allowed_scope="ordinary_daily_material_handling",
        ),
        "premise_evidence_refs": ["E1"],
        "inference_scope": "ordinary_daily_material_handling",
    })

    _, one_result, one_client = _compose(
        one_selection_payload,
        response,
    )

    assert one_result["status"] == "accepted"
    assert {
        tuple(item["inference_policy_refs"])
        for item in one_result["clauses"]
        if item["clause_kind"] == "allowed_inference"
    } == {
        (
            "domain-policy:fixture_domain@1.0.0:"
            "intent:product_durability_practical_guidance",
        ),
        (selected_policy_ref,),
    }
    assert one_client.call_count == 1


def test_composer_accepts_forbidden_mode_with_zero_selection():
    updated, result, client = _compose(_valid_payload(), _response())

    assert result["status"] == "accepted"
    prompt = json.loads(client.messages[1]["content"])
    assert {
        item["option_selection_mode"]
        for item in prompt["renderable_customer_goals"]
    } == {"forbidden"}
    assert all(
        not item["eligible_policy_options"]
        for item in prompt["renderable_customer_goals"]
    )
    assert updated["can_send"] is False


def test_composer_forbids_option_selection_when_goal_has_no_offered_option():
    payload = _valid_payload()
    payload["clauses"][0].update({
        "text": "该项可以作有界说明。",
        "evidence_refs": [],
        "selected_option_refs": ["option_000000000000"],
    })

    updated, result, client = _compose(payload, _response())

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == "composer_forbidden_option_selected"
    assert result["validation_diagnostics"]["category"] == (
        "forbidden_option_selected"
    )
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


def test_composer_rejects_multiple_selections_for_one_required_goal():
    response = _bounded_inference_response()
    _add_alternate_safe_option(response)
    payload = _bounded_inference_payload(response)
    payload["clauses"].insert(1, deepcopy(payload["clauses"][0]))

    updated, result, client = _compose(payload, response)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == "composer_duplicate_goal_clause"
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


def test_composer_rejects_two_option_refs_in_one_required_clause():
    response = _bounded_inference_response()
    _add_alternate_safe_option(response)
    first_ref = _option_alias(
        response,
        goal_ref="goal_01",
        allowed_scope="ordinary_minor_accidental_impact",
    )
    second_ref = _option_alias(
        response,
        goal_ref="goal_01",
        allowed_scope="ordinary_daily_material_handling",
    )
    payload = _with_policy_selection_fields(
        _bounded_inference_payload(response)
    )
    payload["clauses"][0]["selected_option_refs"] = [
        first_ref,
        second_ref,
    ]

    updated, result, client = _compose(payload, response)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_option_selection_count_invalid"
    )
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


def test_composer_rejects_multiple_selections_for_one_optional_goal():
    response = _bounded_inference_response()
    _add_alternate_safe_option(response, resolution_index=1)
    payload = _bounded_inference_payload(response)
    optional_clause = {
        "goal_ref": "goal_02",
        "clause_kind": "allowed_inference",
        "text": "日常使用仍需避免反复冲击。",
        "evidence_refs": ["E1"],
        "selected_policy_ref": _option_alias(
            response,
            goal_ref="goal_02",
            allowed_scope="ordinary_daily_material_handling",
        ),
        "premise_evidence_refs": ["E1"],
        "inference_scope": "ordinary_daily_material_handling",
    }
    payload["clauses"][1] = deepcopy(optional_clause)
    payload["clauses"].append(deepcopy(optional_clause))

    updated, result, client = _compose(payload, response)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == "composer_duplicate_goal_clause"
    assert updated["suggested_reply"] == "旧回复"
    assert client.call_count == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


def test_validator_rejects_mutated_option_selection_mode_without_provider():
    response = _bounded_inference_response()
    goals, bindings = _offered_projection(response)
    goals[0]["option_selection_mode"] = "optional"
    payload = _with_policy_selection_fields(
        _bounded_inference_payload(response)
    )
    known_refs = {
        str(ref)
        for goal in goals
        for ref in (
            list(goal.get("required_evidence_refs") or [])
            + [
                premise_ref
                for option in goal.get("eligible_policy_options") or []
                for premise_ref in (
                    option.get("premise_evidence_refs") or []
                )
            ]
        )
        if str(ref)
    }

    reason, diagnostics = (
        ModelFirstAnswerComposerService._validate_output_with_diagnostics(
            payload,
            known_refs=known_refs,
            customer_goals=goals,
            response=response,
            offered_option_bindings=bindings,
        )
    )

    assert reason == "composer_offered_projection_invalid"
    assert diagnostics["category"] == "offered_projection_invalid"


def test_composer_selects_one_of_multiple_goal_scoped_safe_options():
    response = _bounded_inference_response()
    selected_policy_ref = _add_alternate_safe_option(response)
    selected_ref = _option_alias(
        response,
        goal_ref="goal_01",
        allowed_scope="ordinary_daily_material_handling",
    )
    payload = _bounded_inference_payload()
    payload["clauses"][0].update({
        "selected_policy_ref": selected_ref,
        "inference_scope": "ordinary_daily_material_handling",
    })

    _, result, client = _compose(payload, response)

    assert result["status"] == "accepted"
    selected = next(
        clause
        for clause in result["clauses"]
        if clause["clause_kind"] == "allowed_inference"
    )
    assert selected["inference_policy_refs"] == [
        selected_policy_ref
    ]
    prompt = json.loads(client.messages[1]["content"])
    goal = next(
        item
        for item in prompt["renderable_customer_goals"]
        if len(item["eligible_policy_options"]) == 2
    )
    assert [
        item["option_ref"] for item in goal["eligible_policy_options"]
    ] == sorted(
        item["option_ref"] for item in goal["eligible_policy_options"]
    )


def test_composer_rejects_policy_offered_only_to_another_goal():
    response = _bounded_inference_response()
    _add_alternate_safe_option(
        response,
        resolution_index=1,
    )
    other_goal_option = _option_alias(
        response,
        goal_ref="goal_02",
        allowed_scope="ordinary_daily_material_handling",
    )
    payload = _bounded_inference_payload()
    payload["clauses"][0].update({
        "selected_policy_ref": other_goal_option,
        "inference_scope": "ordinary_daily_material_handling",
    })

    _, result, _ = _compose(payload, response)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_wrong_goal_inference_policy_reference"
    )


def test_composer_rejects_duplicate_offered_policy_reference():
    response = _bounded_inference_response()
    options = response["minimal_decision_context"][
        "claim_resolutions"
    ][0]["eligible_policy_options"]
    options.append(deepcopy(options[0]))

    _, result, _ = _compose(_bounded_inference_payload(), response)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_duplicate_offered_option"
    )


def test_goal_scoped_option_projection_is_order_stable_and_private():
    first = _bounded_inference_response()
    _add_alternate_safe_option(first)
    second = deepcopy(first)
    minimal = second["minimal_decision_context"]
    minimal["requested_claims"].reverse()
    minimal["claim_resolutions"].reverse()
    minimal["admitted_evidence"].reverse()
    minimal["bounded_inference_policies"].reverse()

    first_goals, first_bindings = _offered_projection(first)
    second_goals, second_bindings = _offered_projection(second)

    assert first_goals == second_goals
    assert first_bindings == second_bindings
    assert all(
        ref.startswith("option_") and len(ref) == len("option_") + 12
        for ref in first_bindings
    )
    serialized_goals = json.dumps(first_goals, ensure_ascii=False)
    assert "domain-policy:" not in serialized_goals
    assert _DOMAIN_PACK_HASH not in serialized_goals


def test_same_policy_with_different_goal_premise_has_distinct_aliases():
    response = _bounded_inference_response()
    minimal = response["minimal_decision_context"]
    minimal["admitted_evidence"].append({
        "evidence_uid": "ev-material-two",
        "fact_type": "material_composition",
        "attribute_key": "material",
        "content": "second admitted premise",
    })
    minimal["requested_claims"].append(
        _goal(
            "goal-durability-two",
            "",
            attribute_key="drop_durability_secondary",
            claim_type_status="unmapped",
        )
    )
    option = deepcopy(
        minimal["claim_resolutions"][0]["eligible_policy_options"][0]
    )
    option["applicable_goal_ref"] = "goal-durability-two"
    option["premise_evidence_refs"] = ["ev-material-two"]
    minimal["claim_resolutions"].append(
        _resolution(
            "claim-durability-two",
            "",
            "unresolved",
            attribute_key="drop_durability_secondary",
            claim_type_status="unmapped",
            eligible_policy_options=[option],
        )
    )

    _, bindings = _offered_projection(response)
    same_policy = [
        binding
        for binding in bindings.values()
        if binding["policy_ref"].endswith(
            "intent:product_durability_practical_guidance"
        )
    ]

    assert len(same_policy) == 2
    assert len({
        binding["option_ref"] for binding in same_policy
    }) == 2
    assert {
        tuple(binding["premise_evidence_uids"])
        for binding in same_policy
    } == {("ev-material",), ("ev-material-two",)}


@pytest.mark.parametrize(
    ("selected_ref_factory", "expected_reason"),
    [
        (
            lambda response, bindings: next(
                iter(bindings.values())
            )["policy_ref"],
            "composer_canonical_policy_reference_forbidden",
        ),
        (
            lambda response, bindings: "option_000000000000",
            "composer_unknown_inference_policy_reference",
        ),
    ],
)
def test_validator_rejects_non_offered_option_references_without_provider(
    selected_ref_factory,
    expected_reason,
):
    response = _bounded_inference_response()
    _, bindings = _offered_projection(response)
    payload = _bounded_inference_payload(response)
    payload["clauses"][0]["selected_policy_ref"] = selected_ref_factory(
        response,
        bindings,
    )

    reason, diagnostics = _validate_with_offered_projection(
        response,
        payload,
    )

    assert reason == expected_reason
    assert diagnostics["invalid_reference_sha256"]
    assert "domain-policy:" not in json.dumps(
        diagnostics,
        ensure_ascii=False,
    )


def test_validator_rejects_stale_option_alias_without_provider():
    original = _bounded_inference_response()
    stale_alias = _option_alias(
        original,
        goal_ref="goal_01",
        allowed_scope="ordinary_minor_accidental_impact",
    )
    updated = deepcopy(original)
    minimal = updated["minimal_decision_context"]
    option = minimal["claim_resolutions"][0][
        "eligible_policy_options"
    ][0]
    policy = minimal["bounded_inference_policies"][0]
    option["allowed_scope"] = "ordinary_minor_storage_handling"
    policy["allowed_scope"] = "ordinary_minor_storage_handling"
    payload = _bounded_inference_payload(original)
    payload["clauses"][0]["selected_policy_ref"] = stale_alias

    reason, _ = _validate_with_offered_projection(updated, payload)

    assert reason == "composer_unknown_inference_policy_reference"


def test_composer_requires_policy_selection_schema_fields():
    payload = _with_policy_selection_fields(_valid_payload())
    payload["clauses"][0].pop("selected_option_refs")

    _, result, _ = _compose(
        payload,
        normalize_policy_fields=False,
    )

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == "composer_clause_schema_invalid"


@pytest.mark.parametrize(
    ("mutate_response", "mutate_payload", "expected_reason"),
    [
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "policy_ref": "domain-policy:unknown@1.0.0:intent:x",
            }),
            lambda payload: None,
            "composer_unknown_inference_policy_reference",
        ),
        (
            lambda response: None,
            lambda payload: payload["clauses"][0].update({
                "selected_option_refs": [],
            }),
            "composer_required_option_not_selected",
        ),
        (
            lambda response: response["minimal_decision_context"].update({
                "bounded_inference_policies": [],
            }),
            lambda payload: None,
            "composer_unknown_inference_policy_reference",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "review_only": False,
            }),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "requested_risk": "high",
            }),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "bounded_inference_policies"
            ][0].update({"maximum_risk_level": "low"}),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "allowed_conclusion_family": "unoffered_conclusion",
            }),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "allowed_variability_factor_families": [
                    "unoffered_factor"
                ],
            }),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "advice_mode": "concise_care_only",
            }),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "bounded_inference_policies"
            ][0].pop("allowed_conclusion_family"),
            lambda payload: None,
            "composer_inference_policy_schema_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "trusted_domain_policy_context"
            ].update({"pack_content_sha256": "0" * 64}),
            lambda payload: None,
            "composer_inference_policy_schema_invalid",
        ),
        (
            lambda response: response["minimal_decision_context"][
                "claim_resolutions"
            ][0]["eligible_policy_options"][0].update({
                "pack_content_sha256": "0" * 64,
            }),
            lambda payload: None,
            "composer_bounded_inference_contract_invalid",
        ),
    ],
)
def test_composer_fails_closed_on_bounded_inference_contract_mutation(
    mutate_response,
    mutate_payload,
    expected_reason,
):
    response = _bounded_inference_response()
    payload = _bounded_inference_payload()
    mutate_response(response)
    mutate_payload(payload)

    updated, result, _ = _compose(payload, response)

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == expected_reason
    assert updated["suggested_reply"] == "旧回复"
    assert updated["can_send"] is True
