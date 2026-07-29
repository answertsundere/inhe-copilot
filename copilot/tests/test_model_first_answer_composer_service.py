from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.model_first_answer_composer_service import (
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
        "source_span_start": 0,
        "source_span_end": 8,
        "source_span_sha256": digest,
        "source_text_sha256": digest,
        "source_turn_uid": "turn-current",
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
                "clause_kind": "unresolved",
                "text": "儿童安全方面目前无法确认。",
                "evidence_refs": [],
            },
            {
                "goal_ref": "goal_02",
                "clause_kind": "supported_fact",
                "text": "商品宽度为80厘米。",
                "evidence_refs": ["E1"],
            },
        ],
    }


def _with_policy_selection_fields(payload: dict) -> dict:
    normalized = deepcopy(payload)
    for clause in normalized.get("clauses") or []:
        if not isinstance(clause, dict):
            continue
        clause.setdefault("selected_policy_ref", "")
        clause.setdefault("premise_evidence_refs", [])
        clause.setdefault("inference_scope", "")
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
        "儿童安全方面目前无法确认。\n商品宽度为80厘米。"
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
    assert "不得补充原因、影响条件、发生概率" in client.messages[0]["content"]


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
            lambda value: value["clauses"][0].update(
                clause_kind="supported_fact",
            ),
            "composer_unresolved_goal_asserted",
        ),
        (
            lambda value: value["clauses"][1].update(evidence_refs=["E9"]),
            "composer_unknown_evidence_reference",
        ),
        (
            lambda value: value["clauses"][1].update(
                clause_kind="empathy_or_transition",
            ),
            "composer_supported_goal_clause_invalid",
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
            lambda value: value["clauses"][1].update(
                evidence_refs=["E1", "E1"],
            ),
            "composer_duplicate_evidence_reference",
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


def test_composer_rejects_supported_fact_omission():
    payload = _valid_payload()
    payload["clauses"][1]["evidence_refs"] = []

    _, result, _ = _compose(payload)

    assert result["rejection_reason"] == "composer_supported_claim_omitted"


def test_composer_rejects_evidence_on_unresolved_goal():
    payload = _valid_payload()
    payload["clauses"][0]["evidence_refs"] = ["E1"]

    _, result, _ = _compose(payload)

    assert result["rejection_reason"] == "composer_unresolved_goal_evidence_invalid"


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
    assert updated["suggested_reply"] == "旧回复"
    assert updated["can_send"] is True
    assert client.call_count == 1


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
        (
            lambda value: value["clauses"][0].update(
                clause_kind="supported_fact"
            ),
            "composer_unresolved_goal_asserted",
            "wrong_clause_kind",
            "$.clauses[0].clause_kind",
        ),
        (
            lambda value: value["clauses"][0].update(
                clause_kind="not_a_clause_kind"
            ),
            "composer_clause_kind_invalid",
            "wrong_clause_kind",
            "$.clauses[0].clause_kind",
        ),
        (
            lambda value: value["clauses"][1].update(evidence_refs=["E9"]),
            "composer_unknown_evidence_reference",
            "unknown_evidence_ref",
            "$.clauses[1].evidence_refs",
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
    ["empathy_or_transition", "service_action"],
)
def test_composer_rejects_non_factual_clause_kinds_hiding_supported_fact(
    clause_kind,
):
    payload = _valid_payload()
    payload["clauses"][1].update({
        "clause_kind": clause_kind,
        "text": "商品宽度为80厘米，相关动作已经完成。",
    })

    _, result, _ = _compose(payload)

    assert result["rejection_reason"] == "composer_supported_goal_clause_invalid"
    assert result["validation_diagnostics"]["category"] == "wrong_clause_kind"


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


def test_composer_rejects_media_request_clause_without_attached_block():
    response = _media_goal_response()

    _, result, _ = _compose(
        _media_goal_payload("尺寸图已发，请查看。"),
        response,
    )

    assert result["rejection_reason"] == (
        "composer_non_renderable_goal_reference"
    )
    assert result["validation_diagnostics"]["category"] == (
        "non_renderable_goal_ref"
    )


def test_composer_rejects_identity_mismatched_attached_media():
    response = _media_goal_response()
    response["reply_blocks"].append({
        "type": "image",
        "url": "https://static.invalid/size.png",
        "asset_type": "size_image",
        "status": "approved",
        "usable_for_agent": True,
        "sku_code": "different-sku",
    })

    _, result, _ = _compose(
        _media_goal_payload("尺寸图已发，请查看。"),
        response,
    )

    assert result["rejection_reason"] == (
        "composer_non_renderable_goal_reference"
    )


def test_composer_does_not_render_media_request_as_fact_with_eligible_block():
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

    assert result["status"] == "provider_blocked"
    assert result["rejection_reason"] == (
        "composer_non_renderable_goal_reference"
    )
    assert updated["can_send"] is True
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0
    prompt = json.loads(client.messages[1]["content"])
    assert prompt["renderable_customer_goals"] == []
    assert prompt["media_context"]["request_refs"] == [{
        "goal_ref": "non_renderable_01",
        "goal_kind": "media_request",
        "status": "unresolved",
        "renderable": False,
    }]
    assert prompt["media_context"]["actual_attached_media_types"] == ["image"]


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


def _bounded_inference_payload() -> dict:
    return {
        "clauses": [
            {
                "goal_ref": "goal_01",
                "clause_kind": "allowed_inference",
                "text": "日常轻微意外一般不用过度担心，但不能保证耐摔。",
                "evidence_refs": ["E1"],
                "selected_policy_ref": (
                    "domain-policy:fixture_domain@1.0.0:"
                    "intent:product_durability_practical_guidance"
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
    assert [
        item["policy_ref"]
        for item in inferred_goal["eligible_policy_options"]
    ] == [
        "domain-policy:fixture_domain@1.0.0:"
        "intent:product_durability_practical_guidance"
    ]
    assert prompt["allowed_low_risk_reasoning"] == [
        "ordinary_minor_accidental_impact"
    ]
    option = inferred_goal["eligible_policy_options"][0]
    assert option["requested_risk"] == "medium"
    assert option["maximum_risk_level"] == "medium"
    assert option["review_only"] is True


def test_composer_can_decline_an_eligible_policy_without_asserting_inference():
    payload = _bounded_inference_payload()
    payload["clauses"][0].update({
        "clause_kind": "unresolved",
        "text": "日常耐用边界目前无法确认。",
        "evidence_refs": [],
        "selected_policy_ref": "",
        "premise_evidence_refs": [],
        "inference_scope": "",
    })

    updated, result, _ = _compose(
        payload,
        _bounded_inference_response(),
    )

    assert result["status"] == "accepted"
    assert all(
        clause["inference_policy_refs"] == []
        for clause in result["clauses"]
    )
    assert "无法确认" in updated["suggested_reply"]
    assert updated["can_send"] is False


def test_composer_selects_one_of_multiple_goal_scoped_safe_options():
    response = _bounded_inference_response()
    selected_ref = _add_alternate_safe_option(response)
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
    assert selected["inference_policy_refs"] == [selected_ref]
    prompt = json.loads(client.messages[1]["content"])
    goal = next(
        item
        for item in prompt["renderable_customer_goals"]
        if len(item["eligible_policy_options"]) == 2
    )
    assert [
        item["policy_ref"] for item in goal["eligible_policy_options"]
    ] == sorted(
        item["policy_ref"] for item in goal["eligible_policy_options"]
    )


def test_composer_rejects_policy_offered_only_to_another_goal():
    response = _bounded_inference_response()
    other_goal_policy = _add_alternate_safe_option(
        response,
        resolution_index=1,
    )
    payload = _bounded_inference_payload()
    payload["clauses"][0].update({
        "selected_policy_ref": other_goal_policy,
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
        "composer_unknown_inference_policy_reference"
    )


def test_composer_requires_policy_selection_schema_fields():
    payload = _with_policy_selection_fields(_valid_payload())
    payload["clauses"][0].pop("selected_policy_ref")

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
                "clause_kind": "supported_fact",
            }),
            "composer_unselected_policy_metadata_invalid",
        ),
        (
            lambda response: None,
            lambda payload: payload["clauses"][0].update({
                "evidence_refs": [],
            }),
            "composer_bounded_inference_premise_omitted",
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
