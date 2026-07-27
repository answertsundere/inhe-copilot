import copy
import json

import pytest

from app.services.final_answer_auditor import (
    _model_first_audit_context,
    audit_final_answer,
)
from app.services.final_semantic_quality_service import (
    audit_customer_reply_semantic_fit,
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


def _audit_json(
    *,
    goal_reviews=None,
    global_finding_codes=None,
    **extra,
):
    payload = {
        "schema_version": "unified-textual-audit-v1",
        "goal_reviews": goal_reviews if goal_reviews is not None else [
            {
                "clause_ref": "clause_01",
                "goal_ref": "goal_01",
                "clause_kind": "supported_fact",
                "textual_status": "accepted",
                "finding_codes": [],
            },
            {
                "clause_ref": "clause_02",
                "goal_ref": "goal_02",
                "clause_kind": "unresolved",
                "textual_status": "accepted",
                "finding_codes": [],
            },
        ],
        "global_finding_codes": (
            global_finding_codes
            if global_finding_codes is not None
            else []
        ),
    }
    payload.update(extra)
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
                "clause_ref": "C1",
                "goal_ref": "claim-material",
                "clause_kind": "supported_fact",
                "text": "这款是 ABS 材质。",
                "evidence_uids": ["ev-material"],
            },
            {
                "clause_ref": "C2",
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


def _run_unified_audit(
    response,
    *,
    customer_message,
    copilot_context,
):
    audited = audit_final_answer(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    assert audited["final_answer_audit"]["model_call_count"] == 0
    semantic = audit_customer_reply_semantic_fit(
        audited,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    return audited, semantic


def test_model_first_projection_separates_canonical_truth_and_continuity(monkeypatch):
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert audited["final_answer_audit"]["passed"] is True
    assert set(payload) == {
        "schema_version",
        "current_customer_message",
        "final_reply",
        "canonical_truth",
        "conversation_continuity",
        "completion_evidence",
        "deterministic_final_contract",
        "unified_textual_contract",
    }
    assert payload["canonical_truth"]["evidence"][0]["content"] == "材质是 ABS"
    assert payload["canonical_truth"]["candidate_clauses"] == [
        {
            "clause_ref": "clause_01",
            "goal_ref": "goal_01",
            "canonical_status": "supported",
            "expected_kind": "supported_fact",
            "text": "这款是 ABS 材质。",
            "evidence_refs": ["E1"],
            "premise_evidence_refs": [],
            "inference_policy_refs": [],
            "scope_qualifier": "",
            "required_qualifiers": [],
            "prohibited_extensions": [],
        },
        {
            "clause_ref": "clause_02",
            "goal_ref": "goal_02",
            "canonical_status": "unresolved",
            "expected_kind": "unresolved",
            "text": "安全性目前无法确认。",
            "evidence_refs": [],
            "premise_evidence_refs": [],
            "inference_policy_refs": [],
            "scope_qualifier": "",
            "required_qualifiers": [],
            "prohibited_extensions": [],
        },
    ]
    assert "金属材质" not in json.dumps(payload["canonical_truth"], ensure_ascii=False)
    agent_turn = payload["conversation_continuity"][
        "historical_agent_turns_non_authoritative"
    ][0]
    assert "金属材质" in agent_turn["content"]
    assert agent_turn["authoritative_for_product_facts"] is False
    assert agent_turn["authoritative_for_policy_facts"] is False
    assert agent_turn["authoritative_for_order_status"] is False
    assert agent_turn["usable_for_conversation_continuity"] is True
    assert semantic["passed"] is True


@pytest.mark.parametrize(
    "boundary_text",
    [
        "目前无法确认能否保证摔不坏。",
        "现有资料不能支持绝对耐摔保证。",
        "这一点不能作确定保证。",
    ],
)
def test_atomic_final_audit_accepts_supported_fact_and_unresolved_variants(
    monkeypatch,
    boundary_text,
):
    response = _response()
    response["model_first_answer_composer"]["clauses"][1]["text"] = boundary_text
    response["suggested_reply"] = (
        response["model_first_answer_composer"]["clauses"][0]["text"]
        + "\n"
        + boundary_text
    )
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        response,
        customer_message="这款是什么材质，能保证摔不坏吗？",
        copilot_context=_context(),
    )

    assert len(client.calls) == 1
    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is True
    assert semantic["goal_reviews"][1]["textual_status"] == "accepted"


def test_atomic_final_audit_rejects_unresolved_asserted_as_guarantee(monkeypatch):
    response = _response()
    response["model_first_answer_composer"]["clauses"][1][
        "text"
    ] = "这款肯定摔不坏。"
    response["suggested_reply"] = "这款是 ABS 材质。\n这款肯定摔不坏。"
    reviews = json.loads(_audit_json())["goal_reviews"]
    reviews[1].update({
        "textual_status": "rejected",
        "finding_codes": ["unresolved_claim_asserted"],
    })
    client = _Client(_audit_json(goal_reviews=reviews))
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        response,
        customer_message="这款是什么材质，能保证摔不坏吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is False
    assert "unresolved_claim_asserted" in semantic["issues"]


@pytest.mark.parametrize(
    ("mutate", "error_category"),
    [
        (
            lambda payload: payload.pop("global_finding_codes"),
            "top_level_fields_invalid",
        ),
        (
            lambda payload: payload.update({"analysis": "not allowed"}),
            "top_level_fields_invalid",
        ),
        (
            lambda payload: payload["goal_reviews"][0].pop("finding_codes"),
            "segment_fields_invalid",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {"reason": "not allowed"}
            ),
            "segment_fields_invalid",
        ),
        (
            lambda payload: payload["goal_reviews"].pop(),
            "segment_reference_set_incomplete",
        ),
        (
            lambda payload: payload["goal_reviews"].append(
                copy.deepcopy(payload["goal_reviews"][0])
            ),
            "duplicate_segment_reference",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {"goal_ref": "goal_unknown"}
            ),
            "unknown_segment_reference",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {"clause_ref": "clause_unknown"}
            ),
            "unknown_segment_reference",
        ),
        (
            lambda payload: payload.update(
                {"schema_version": "unified-textual-audit-unknown"}
            ),
            "schema_version_invalid",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {"clause_kind": "unknown"}
            ),
            "clause_kind_mismatch",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {"textual_status": True}
            ),
            "textual_status_invalid",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {"finding_codes": ["free_text_issue"]}
            ),
            "issue_code_invalid",
        ),
        (
            lambda payload: payload["goal_reviews"][0].update(
                {
                    "textual_status": "rejected",
                    "finding_codes": [],
                }
            ),
            "textual_status_finding_mismatch",
        ),
        (
            lambda payload: payload.update({"passed": False}),
            "top_level_fields_invalid",
        ),
    ],
)
def test_atomic_final_audit_rejects_invalid_schema_and_references(
    monkeypatch,
    mutate,
    error_category,
):
    payload = json.loads(_audit_json())
    mutate(payload)
    client = _Client(json.dumps(payload, ensure_ascii=False))
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert len(client.calls) == 1
    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is False
    assert semantic["issues"] == ["semantic_judge_schema_invalid"]
    assert semantic["validation_diagnostics"]["category"] == error_category


def test_atomic_final_audit_rejects_diagnostic_reason_as_extra_schema(
    monkeypatch,
):
    payload = json.loads(_audit_json())
    payload.update({
        "passed": True,
        "reason": "diagnostic text must not enter the audit report",
    })
    client = _Client(json.dumps(payload, ensure_ascii=False))
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is False
    assert semantic["validation_diagnostics"]["category"] == (
        "top_level_fields_invalid"
    )


def test_atomic_final_audit_is_order_independent(monkeypatch):
    first_response = _response()
    second_response = _response()
    second_response["model_first_answer_composer"]["clauses"].reverse()
    second_response["minimal_decision_context"]["claim_resolutions"].reverse()
    second_response["evidence_debug"]["minimal_decision_context"][
        "claim_resolutions"
    ].reverse()
    second_response["evidence_debug"]["admitted_answer_context"][
        "claim_resolutions"
    ].reverse()
    reversed_payload = json.loads(_audit_json())
    reversed_payload["goal_reviews"].reverse()
    clients = iter([
        _Client(_audit_json()),
        _Client(json.dumps(reversed_payload, ensure_ascii=False)),
    ])
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: next(clients),
    )
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)

    first_final, first = _run_unified_audit(
        first_response,
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )
    second_final, second = _run_unified_audit(
        second_response,
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert first_final["final_answer_audit"]["model_call_count"] == 0
    assert second_final["final_answer_audit"]["model_call_count"] == 0
    first.pop("provider_diagnostics")
    second.pop("provider_diagnostics")
    assert first == second


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

    canonical_source_text = json.dumps(
        {
            "evidence": projected["canonical_truth"]["evidence"],
            "claim_resolutions": projected["canonical_truth"][
                "claim_resolutions"
            ],
        },
        ensure_ascii=False,
    )
    continuity = projected["conversation_continuity"]
    agent_turn = continuity["historical_agent_turns_non_authoritative"][0]
    assert historical_agent_text not in canonical_source_text
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
            global_finding_codes=[
                "unsupported_service_action_completion"
            ],
        )
    )
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        response,
        customer_message="那退款呢？",
        copilot_context=context,
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is False
    assert "unsupported_service_action_completion" in semantic["issues"]


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
        (
            "delete_supported_evidence",
            "model_first_candidate_supported_clause_invalid",
        ),
        (
            "duplicate_goal",
            "model_first_candidate_goal_duplicate_or_missing",
        ),
        ("unknown_goal", "model_first_candidate_goal_set_mismatch"),
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
    elif mutation == "delete_supported_evidence":
        clauses[0]["evidence_uids"] = []
    elif mutation == "duplicate_goal":
        clauses[1]["goal_ref"] = clauses[0]["goal_ref"]
    elif mutation == "unknown_goal":
        clauses[1]["goal_ref"] = "claim-unknown"
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
    assert client.calls == []


def test_supported_clause_cannot_bind_another_admitted_evidence(monkeypatch):
    response = _response()
    other = {
        "evidence_uid": "ev-other",
        "evidence_role": "product_fact_direct",
        "fact_type": "dimensions",
        "attribute_key": "width",
        "content": "宽度 80cm",
    }
    response["selected_evidence"].append(copy.deepcopy(other))
    response["minimal_decision_context"]["admitted_evidence"].append(
        copy.deepcopy(other)
    )
    response["evidence_debug"]["selected_evidence"].append(
        copy.deepcopy(other)
    )
    response["evidence_debug"]["minimal_decision_context"][
        "admitted_evidence"
    ].append(copy.deepcopy(other))
    response["evidence_debug"]["admitted_answer_context"][
        "direct_product_facts"
    ].append(copy.deepcopy(other))
    response["model_first_answer_composer"]["clauses"][0][
        "evidence_uids"
    ] = ["ev-other"]
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        response,
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "model_first_candidate_supported_clause_invalid" in audited[
        "final_answer_audit"
    ]["issues"]
    assert client.calls == []


def test_historical_agent_fact_use_is_rejected_even_when_provider_says_passed(monkeypatch):
    client = _Client(
        _audit_json(
            global_finding_codes=["historical_agent_fact_used"]
        )
    )
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is False
    assert "historical_agent_fact_used" in semantic["issues"]


@pytest.mark.parametrize(
    "client,expected_issue,error_category",
    [
        (
            _Client(error=TimeoutError("provider timeout")),
            "semantic_judge_unavailable",
            "provider_error",
        ),
        (
            _Client(error=RuntimeError("provider failed")),
            "semantic_judge_unavailable",
            "provider_error",
        ),
        (
            _Client(""),
            "semantic_judge_schema_invalid",
            "free_text_response",
        ),
        (
            _Client("not-json"),
            "semantic_judge_schema_invalid",
            "free_text_response",
        ),
        (
            _Client('{"passed":true}'),
            "semantic_judge_schema_invalid",
            "top_level_fields_invalid",
        ),
    ],
)
def test_model_first_provider_failure_and_schema_error_fail_closed(
    monkeypatch,
    client,
    expected_issue,
    error_category,
):
    _install_client(monkeypatch, client)

    audited, semantic = _run_unified_audit(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=_context(),
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is False
    assert semantic["issues"] == [expected_issue]
    assert semantic["validation_diagnostics"]["category"] == error_category


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
    assert len(audit["candidate_reply_sha256"]) == 64


def test_customer_visible_redaction_marker_remains_blocked(monkeypatch):
    response = _response()
    response["suggested_reply"] = "这款可以放在[ADDRESS_REDACTED]。"
    client = _Client(_audit_json())
    _install_client(monkeypatch, client)

    audited = audit_final_answer(
        response,
        customer_message="能放在房间里吗",
        copilot_context=_context(),
    )

    audit = audited["final_answer_audit"]
    assert audit["passed"] is False
    assert "customer_reply_identity_leakage" in audit["issues"]
    assert audited["can_send"] is False
    assert audited["requires_human_review"] is True
    assert audited["sendable_reply"] == ""


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

    audited, semantic = _run_unified_audit(
        _response(),
        customer_message="这款什么材质，安全吗？",
        copilot_context=context,
    )

    serialized = json.dumps(
        completions.kwargs["messages"],
        ensure_ascii=False,
    )
    assert audited["final_answer_audit"]["passed"] is True
    assert semantic["passed"] is True
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
