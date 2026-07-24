import copy
import json

import pytest

from app.services.final_answer_auditor import (
    _model_first_audit_context,
    audit_final_answer,
)


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Completion:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Client:
    api_key = "configured"
    model = "test-model"

    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return _Completion(self.content)


def _audit_json(**overrides):
    payload = {
        "passed": True,
        "issues": [],
        "reason_code": "canonical_reply_valid",
        "canonical_truth_respected": True,
        "unresolved_declaration_recognized": True,
        "conversation_continuity_checked": True,
        "historical_agent_fact_used": False,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def _response():
    evidence = {
        "evidence_uid": "ev-material",
        "evidence_role": "product_fact_direct",
        "fact_type": "material",
        "attribute_key": "material",
        "content": "材质是 ABS",
        "provenance": {
            "origin_evidence_key": "formal:material",
            "source_container": "selected_evidence",
        },
    }
    resolutions = [
        {
            "claim_uid": "claim-material",
            "claim_type": "material",
            "attribute_key": "material",
            "status": "supported",
            "evidence_uids": ["ev-material"],
            "conflicting_evidence_uids": [],
        },
        {
            "claim_uid": "claim-safety",
            "claim_type": "material_safety",
            "attribute_key": "material_safety",
            "status": "unresolved",
            "evidence_uids": [],
            "conflicting_evidence_uids": [],
        },
    ]
    minimal = {
        "admitted_evidence": [copy.deepcopy(evidence)],
        "claim_resolutions": copy.deepcopy(resolutions),
        "unresolved_claims": [copy.deepcopy(resolutions[1])],
        "conflicting_claims": [],
        "requested_claims": [
            {"claim_type": "material", "attribute_key": "material"},
            {"claim_type": "material_safety", "attribute_key": "material_safety"},
        ],
        "media_candidates": [],
    }
    composer = {
        "status": "accepted",
        "clauses": [
            {
                "goal_ref": "claim-material",
                "clause_kind": "supported_fact",
                "text": "这款是 ABS 材质。",
                "evidence_uids": ["ev-material"],
            },
            {
                "goal_ref": "claim-safety",
                "clause_kind": "unresolved",
                "text": "安全性目前无法确认。",
                "evidence_uids": [],
            },
        ],
    }
    return {
        "intent": "product_question",
        "suggested_reply": "这款是 ABS 材质。\n安全性目前无法确认。",
        "draft_reply": "这款是 ABS 材质。\n安全性目前无法确认。",
        "requires_human_review": True,
        "can_send": False,
        "sendable_reply": "",
        "selected_evidence": [copy.deepcopy(evidence)],
        "minimal_decision_context": copy.deepcopy(minimal),
        "model_first_answer_composer": copy.deepcopy(composer),
        "evidence_debug": {
            "selected_evidence": [copy.deepcopy(evidence)],
            "minimal_decision_context": copy.deepcopy(minimal),
            "admitted_answer_context": {
                "direct_product_facts": [copy.deepcopy(evidence)],
                "claim_resolutions": copy.deepcopy(resolutions),
                "unresolved_claims": [copy.deepcopy(resolutions[1])],
                "conflicting_claims": [],
            },
        },
    }


def _context():
    return {
        "order_id": "2026072400012345",
        "sku_code": "SKU-PRIVATE-01",
        "conversation_history": [
            {
                "role": "customer",
                "content": "订单号 2026072400012345，手机号 13812345678。",
                "turn_index": 1,
                "turn_uid": "turn-customer-private",
            },
            {
                "role": "agent",
                "content": "这款是金属材质，我会继续查询。",
                "turn_index": 2,
                "turn_uid": "turn-agent-wrong-fact",
            },
        ],
    }


def _install_client(monkeypatch, client):
    from app import config
    from app.llm import client as client_module

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(client_module, "get_llm_client", lambda: client)


def test_model_first_projection_separates_canonical_truth_and_continuity(monkeypatch):
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert audited["final_answer_audit"]["passed"] is True
    assert set(payload) == {
        "customer_message",
        "suggested_reply",
        "model_first_candidate",
        "schema_version",
        "canonical_truth",
        "conversation_continuity",
        "context_presence",
    }
    assert payload["canonical_truth"]["evidence"][0]["content"] == "材质是 ABS"
    assert "金属材质" not in json.dumps(payload["canonical_truth"], ensure_ascii=False)
    agent_turn = payload["conversation_continuity"][
        "historical_agent_turns_non_authoritative"
    ][0]
    assert "金属材质" in agent_turn["content"]
    assert agent_turn["authoritative_for_product_facts"] is False
    assert agent_turn["authoritative_for_policy_facts"] is False
    assert agent_turn["authoritative_for_order_status"] is False
    assert agent_turn["usable_for_conversation_continuity"] is True
    assert payload["context_presence"]["order_context_present"] is True


@pytest.mark.parametrize(
    "historical_agent_text",
    [
        "这款是 ABS 材质。",
        "退款已经完成。",
    ],
)
def test_historical_agent_facts_and_actions_remain_non_authoritative(
    historical_agent_text,
):
    context = _context()
    context["conversation_history"][1]["content"] = historical_agent_text

    projected = _model_first_audit_context(_response(), context)

    truth_text = json.dumps(projected["canonical_truth"], ensure_ascii=False)
    continuity = projected["conversation_continuity"]
    agent_turn = continuity["historical_agent_turns_non_authoritative"][0]
    assert historical_agent_text not in truth_text
    assert historical_agent_text in agent_turn["content"]
    assert agent_turn["authoritative_for_product_facts"] is False
    assert agent_turn["authoritative_for_order_status"] is False
    assert "service_action_completion_proof" in continuity["prohibited_uses"]


def test_order_already_provided_is_not_requested_again(monkeypatch):
    response = _response()
    response["suggested_reply"] = "请提供订单号。"
    response["draft_reply"] = response["suggested_reply"]
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        response,
        customer_message="刚才已经发过了。",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "asks_for_existing_order_id" in audited["final_answer_audit"]["issues"]


def test_historical_refund_completion_without_live_tool_result_is_rejected(
    monkeypatch,
):
    response = _response()
    response["suggested_reply"] = "退款已经完成。"
    response["draft_reply"] = response["suggested_reply"]
    context = _context()
    context["conversation_history"][1]["content"] = "上一位客服说退款已经处理。"
    client = _Client(
        _audit_json(
            passed=False,
            issues=["unsupported_service_action_completion"],
            reason_code="unsupported_service_action_completion",
        )
    )
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        response,
        customer_message="那退款呢？",
        copilot_context=context,
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert (
        "llm:unsupported_service_action_completion"
        in audited["final_answer_audit"]["issues"]
    )


def test_history_order_does_not_change_canonical_fact_projection():
    forward = _context()
    reverse = copy.deepcopy(forward)
    reverse["conversation_history"].reverse()

    assert (
        _model_first_audit_context(_response(), forward)["canonical_truth"]
        == _model_first_audit_context(_response(), reverse)["canonical_truth"]
    )


@pytest.mark.parametrize(
    "mutation,expected_issue",
    [
        ("delete_supported", "model_first_candidate_goal_set_mismatch"),
        ("delete_unresolved", "model_first_candidate_goal_set_mismatch"),
        ("assert_unresolved", "model_first_candidate_unresolved_clause_invalid"),
        ("unknown_evidence", "model_first_candidate_unknown_evidence"),
    ],
)
def test_model_first_candidate_mutations_fail_closed(
    monkeypatch,
    mutation,
    expected_issue,
):
    response = _response()
    clauses = response["model_first_answer_composer"]["clauses"]
    if mutation == "delete_supported":
        clauses.pop(0)
    elif mutation == "delete_unresolved":
        clauses.pop()
    elif mutation == "assert_unresolved":
        clauses[1]["clause_kind"] = "supported_fact"
        clauses[1]["evidence_uids"] = ["ev-material"]
    else:
        clauses[0]["evidence_uids"] = ["ev-unknown"]
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        response,
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert expected_issue in audited["final_answer_audit"]["issues"]


def test_historical_agent_fact_use_is_rejected_even_when_provider_says_passed(monkeypatch):
    client = _Client(_audit_json(historical_agent_fact_used=True))
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "llm:historical_agent_fact_used" in audited["final_answer_audit"]["issues"]


@pytest.mark.parametrize(
    "client,issue_prefix",
    [
        (_Client(error=TimeoutError("provider timeout")), "llm:model_first_audit_provider_error"),
        (_Client('{"passed":true}'), "llm:model_first_audit_schema_invalid"),
    ],
)
def test_model_first_provider_failure_and_schema_error_fail_closed(
    monkeypatch,
    client,
    issue_prefix,
):
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert any(
        str(issue).startswith(issue_prefix)
        for issue in audited["final_answer_audit"]["issues"]
    )


def test_evidence_order_does_not_change_canonical_truth():
    first = _response()
    extra = {
        "evidence_uid": "ev-size",
        "evidence_role": "product_fact_direct",
        "fact_type": "dimensions",
        "attribute_key": "width",
        "content": "宽度 80cm",
    }
    for container in (
        first["selected_evidence"],
        first["evidence_debug"]["selected_evidence"],
        first["evidence_debug"]["admitted_answer_context"]["direct_product_facts"],
        first["minimal_decision_context"]["admitted_evidence"],
        first["evidence_debug"]["minimal_decision_context"]["admitted_evidence"],
    ):
        container.append(copy.deepcopy(extra))
    second = copy.deepcopy(first)
    for container in (
        second["selected_evidence"],
        second["evidence_debug"]["selected_evidence"],
        second["evidence_debug"]["admitted_answer_context"]["direct_product_facts"],
        second["minimal_decision_context"]["admitted_evidence"],
        second["evidence_debug"]["minimal_decision_context"]["admitted_evidence"],
    ):
        container.reverse()

    assert (
        _model_first_audit_context(first, _context())["canonical_truth"]
        == _model_first_audit_context(second, _context())["canonical_truth"]
    )


@pytest.mark.parametrize(
    "history",
    [
        [],
        [{"role": "customer", "content": "那这个呢？", "turn_index": 1}],
        [{"role": "agent", "content": "我会继续处理。", "turn_index": 1}],
    ],
)
def test_empty_customer_only_and_agent_only_history_remain_explicit(history):
    context = {"conversation_history": history}

    projected = _model_first_audit_context(_response(), context)

    assert projected["conversation_continuity"]["turn_count"] == len(history)
    continuity = projected["conversation_continuity"]
    for turn in (
        continuity["customer_turns"]
        + continuity["historical_agent_turns_non_authoritative"]
    ):
        assert turn["usable_for_conversation_continuity"] is True
        assert turn["authoritative_for_product_facts"] is False


def test_customer_visible_private_values_are_blocked_without_storing_raw_reply(monkeypatch):
    response = _response()
    response["suggested_reply"] = "订单 2026072400012345，联系 13812345678。"
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        response,
        customer_message="帮我看一下",
        copilot_context=_context(),
    )

    audit = audited["final_answer_audit"]
    assert audit["passed"] is False
    assert "customer_reply_identity_leakage" in audit["issues"]
    assert "original_reply" not in audit
    assert len(audit["original_reply_sha256"]) == 64


def test_auditor_request_uses_provider_privacy_projection_without_losing_product_facts(
    monkeypatch,
):
    from app.llm.client import LLMClient

    class CapturingCompletions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return _Completion(_audit_json())

    completions = CapturingCompletions()
    transport = type(
        "Transport",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()
    client = LLMClient(
        api_key="configured",
        api_base="https://provider.invalid/v1",
        model="test-model",
    )
    client._client = transport
    _install_client(monkeypatch, client)
    context = {
        "order_id": "2026072400012345",
        "sku_code": "SKU-PRIVATE-01",
        "conversation_history": [
            {
                "role": "customer",
                "content": (
                    "客厅卧室收纳柜是 ABS 材质，宽度 80cm。"
                    "订单号 2026072400012345，物流号 SF1234567890123，"
                    "手机号 13812345678，邮箱 buyer@example.com，"
                    "地址：上海市浦东新区测试路88号，"
                    "链接 https://shop.example/item?buyer=private，"
                    "SKU: SKU-PRIVATE-01，api_key=secret-value。"
                ),
                "turn_index": 1,
            }
        ],
    }

    audited = audit_final_answer(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=context,
    )

    serialized = json.dumps(
        completions.kwargs["messages"],
        ensure_ascii=False,
    )
    assert audited["final_answer_audit"]["passed"] is True
    for private_value in (
        "2026072400012345",
        "SF1234567890123",
        "13812345678",
        "buyer@example.com",
        "浦东新区测试路88号",
        "buyer=private",
        "SKU-PRIVATE-01",
        "secret-value",
    ):
        assert private_value not in serialized
    assert "客厅卧室收纳柜" in serialized
    assert "ABS 材质" in serialized
    assert "宽度 80cm" in serialized
