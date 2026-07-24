from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.model_first_answer_composer_service import (
    ModelFirstAnswerComposerService,
)


def _resolution(
    claim_uid: str,
    claim_type: str,
    status: str,
    *,
    attribute_key: str = "",
    evidence_uids: list[str] | None = None,
) -> dict:
    return {
        "claim_uid": claim_uid,
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "status": status,
        "evidence_uids": list(evidence_uids or []),
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
                {"claim_type": "dimensions", "attribute_key": "width"},
                {"claim_type": "child_safety", "attribute_key": ""},
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


class _Client:
    api_key = "configured"
    model = "MiniMax-M3"

    def __init__(self, payload: dict | str):
        self.payload = payload
        self.messages = []
        self.call_count = 0

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        self.messages = kwargs["messages"]
        content = (
            self.payload
            if isinstance(self.payload, str)
            else json.dumps(self.payload, ensure_ascii=False)
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=content,
        ))])


class _RaisingClient(_Client):
    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise RuntimeError("minimax_response_truncated")


def _compose(payload: dict | str, response: dict | None = None):
    client = _Client(payload)
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
        {"claim_type": "moisture_resistance", "attribute_key": ""},
        {
            "claim_type": "material_composition",
            "attribute_key": "material",
            "supporting_only": True,
        },
    ]
    context["admitted_evidence"] = []
    context["claim_resolutions"] = [
        _resolution(
            "claim-dependency",
            "material_composition",
            "unresolved",
            attribute_key="material",
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
    assert [item["claim_type"] for item in prompt["customer_goals"]] == [
        "moisture_resistance",
    ]
    assert updated["suggested_reply"] == "防潮表现目前无法确认。"


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
        context["requested_claims"].append({
            "claim_type": claim_type,
            "attribute_key": claim_type,
        })
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
        json.loads(first_client.messages[1]["content"])["customer_goals"]
        == json.loads(second_client.messages[1]["content"])["customer_goals"]
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
        "formal_llm_error:JSONDecodeError",
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
