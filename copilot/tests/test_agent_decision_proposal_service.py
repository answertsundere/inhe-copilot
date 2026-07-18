from __future__ import annotations

from copy import deepcopy

from app.services.agent_decision_proposal_service import AgentDecisionProposalService, _safe_error_reason
from app.services.claim_resolution_service import build_claim_resolutions


def _fact():
    return {
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


def _understanding():
    return {
        "primary_question": "材质是否安全并且防潮",
        "requested_claims": [
            {"claim_type": "material_composition", "question": "是什么材质", "risk_level": "medium"},
            {"claim_type": "material_safety", "question": "是否安全", "risk_level": "high"},
            {"claim_type": "moisture_resistance", "question": "是否防潮", "risk_level": "medium"},
        ],
        "uncertainty_items": [],
        "requested_fact_types": ["material", "material_safety", "moisture_resistance"],
    }


def _tool_plan():
    return {
        "retrieval_needed": True,
        "product_identity_lookup_needed": False,
        "order_lookup_needed": False,
        "media_lookup_needed": False,
    }


def _intake():
    return {"understanding": _understanding(), "tool_plan": _tool_plan()}


def _tool_execution():
    return {
        "schema_version": "llm-decision-shadow-tool-execution-v1",
        "shadow_only": True,
        "planned_tool_flags": _tool_plan(),
        "executed_tool_names": ["rag_search_tool"],
        "deferred_capabilities": [],
        "tool_results": {},
        "tool_traces": [],
        "total_duration_ms": 1,
        "timed_out": False,
        "requires_human_review": False,
    }


def _stub_tool_execution(monkeypatch, service):
    monkeypatch.setattr(service, "_execute_shadow_tool_plan", lambda **kwargs: _tool_execution())


def _proposal():
    proposal = {
        "understanding": _understanding(),
        "tool_plan": _tool_plan(),
        "evidence_selection": {
            "candidate_evidence_uids": ["fact-material"],
            "requested_evidence_uids": ["fact-material"],
            "unsupported_claims": ["material_safety", "moisture_resistance"],
        },
        "claim_resolutions": [
            {
                "claim_type": "material_composition",
                "status": "supported",
                "evidence_uids": ["fact-material"],
                "admitted_fact_texts": ["主体材质为PP。"],
                "requires_human_review": False,
                "reason": "admitted_direct_evidence",
            },
            {
                "claim_type": "material_safety",
                "status": "unresolved",
                "evidence_uids": [],
                "admitted_fact_texts": [],
                "requires_human_review": True,
                "reason": "no_admitted_direct_evidence",
            },
            {
                "claim_type": "moisture_resistance",
                "status": "unresolved",
                "evidence_uids": [],
                "admitted_fact_texts": [],
                "requires_human_review": True,
                "reason": "no_admitted_direct_evidence",
            },
        ],
        "confirmed_clauses": [{
            "claim_type": "material_composition",
            "evidence_uids": ["fact-material"],
            "customer_facing_clause": "这款主体材质为PP。",
        }],
        "pending_clauses": [
            {
                "claim_type": "material_safety",
                "reason": "no_admitted_direct_evidence",
                "customer_facing_clause": "安全性还需要按商品资料确认。",
            },
            {
                "claim_type": "moisture_resistance",
                "reason": "no_admitted_direct_evidence",
                "customer_facing_clause": "防潮表现还需要按商品资料确认。",
            },
        ],
        "reply_plan": {
            "mode": "controlled_handoff",
            "factual_clause_evidence_uids": ["fact-material"],
            "action_guidance_evidence_uids": [],
            "proposed_reply": "这款主体材质为PP。安全性还需要按商品资料确认。防潮表现还需要按商品资料确认。",
        },
        "delivery_intent": {"proposed_reply_block_refs": [], "requires_human_review": True},
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }
    proposal["claim_resolutions"] = build_claim_resolutions(
        _understanding()["requested_claims"],
        direct_product_facts=[{
            "evidence_uid": "fact-material",
            "text": proposal["claim_resolutions"][0]["admitted_fact_texts"][0],
            "claim_types_supported": ["material", "material_composition"],
        }],
        direct_policy_facts=[],
        conflicts=[],
    )
    return proposal


def test_proposal_only_references_admitted_evidence(monkeypatch):
    service = AgentDecisionProposalService()
    outputs = iter([_intake(), _proposal()])
    monkeypatch.setattr(service, "_request_json_schema", lambda **kwargs: next(outputs))
    _stub_tool_execution(monkeypatch, service)
    response = {
        "suggested_reply": "正式回复保持不变。",
        "can_send": False,
        "requires_human_review": True,
        "selected_evidence": [_fact()],
    }

    updated = service.attach_shadow_decision(
        deepcopy(response),
        customer_message="这个材质安全吗，会不会受潮？",
        product_identity={"sku_code": "SKU-A"},
    )

    assert updated["suggested_reply"] == response["suggested_reply"]
    assert updated["can_send"] is False
    proposal = updated["evidence_debug"]["llm_decision_proposal"]
    context = updated["evidence_debug"]["admitted_answer_context"]
    assert proposal["shadow_status"] == "completed"
    assert proposal["reply_plan"]["factual_clause_evidence_uids"] == ["fact-material"]
    assert {item["claim_type"] for item in context["unresolved_claims"]} == {
        "material_safety", "moisture_resistance",
    }
    assert context["shadow_tool_execution"]["executed_tool_names"] == ["rag_search_tool"]
    trace = updated["answer_trace"]["llm_decision_shadow"]
    assert {item["claim_type"] for item in trace["claim_resolutions"]} == {
        "material_composition", "material_safety", "moisture_resistance",
    }
    assert trace["confirmed_clauses"][0]["evidence_uids"] == ["fact-material"]


def test_invalid_schema_fails_closed(monkeypatch):
    service = AgentDecisionProposalService()
    monkeypatch.setattr(service, "_request_json_schema", lambda **kwargs: {"free_text": "send=true"})

    proposal, _ = service.build_for_response(
        {"selected_evidence": [_fact()]},
        customer_message="什么材质",
        product_identity={"sku_code": "SKU-A"},
    )

    assert proposal["shadow_status"] == "degraded"
    assert proposal["reply_plan"]["proposed_reply"] == ""
    assert proposal["delivery_intent"]["requires_human_review"] is True
    assert proposal["can_change_can_send"] is False


def test_unqualified_decision_provider_has_a_safe_explicit_fallback_reason():
    assert _safe_error_reason("understanding", RuntimeError("provider_not_qualified")) == (
        "understanding_error:provider_not_qualified"
    )


def test_extra_send_field_is_rejected(monkeypatch):
    service = AgentDecisionProposalService()
    bad = _proposal()
    bad["send"] = True
    outputs = iter([_intake(), bad])
    monkeypatch.setattr(service, "_request_json_schema", lambda **kwargs: next(outputs))
    _stub_tool_execution(monkeypatch, service)

    proposal, _ = service.build_for_response(
        {"selected_evidence": [_fact()]},
        customer_message="什么材质",
        product_identity={"sku_code": "SKU-A"},
    )

    assert proposal["shadow_status"] == "degraded"
    assert proposal["fallback_reason"].startswith("proposal_error:")


def test_unadmitted_reference_and_unsupported_claim_fail_closed(monkeypatch):
    service = AgentDecisionProposalService()
    bad = _proposal()
    bad["reply_plan"]["factual_clause_evidence_uids"] = ["raw-rag-chunk"]
    bad["reply_plan"]["proposed_reply"] = "这款安全而且防潮。"
    outputs = iter([_intake(), bad])
    monkeypatch.setattr(service, "_request_json_schema", lambda **kwargs: next(outputs))
    _stub_tool_execution(monkeypatch, service)

    proposal, _ = service.build_for_response(
        {"selected_evidence": [_fact()]},
        customer_message="这个材质安全吗，会不会受潮？",
        product_identity={"sku_code": "SKU-A"},
    )

    assert proposal["shadow_status"] == "degraded"
    assert "unadmitted_factual_evidence_reference" in proposal["contract_violations"]
    assert "unsupported_claim_asserted" in proposal["contract_violations"]


def test_supported_claim_omission_fails_closed(monkeypatch):
    service = AgentDecisionProposalService()
    bad = _proposal()
    bad["confirmed_clauses"] = []
    outputs = iter([_intake(), bad])
    monkeypatch.setattr(service, "_request_json_schema", lambda **kwargs: next(outputs))
    _stub_tool_execution(monkeypatch, service)

    proposal, _ = service.build_for_response(
        {"selected_evidence": [_fact()]},
        customer_message="这个材质安全吗，会不会受潮？",
        product_identity={"sku_code": "SKU-A"},
    )

    assert proposal["shadow_status"] == "degraded"
    assert "supported_claim_omitted" in proposal["contract_violations"]


def test_pending_claim_must_not_be_rendered_as_a_positive_fact(monkeypatch):
    service = AgentDecisionProposalService()
    bad = _proposal()
    bad["reply_plan"]["proposed_reply"] = "这款主体材质为PP。安全性还需要按商品资料确认。这款防潮表现很好。"
    bad["pending_clauses"][1]["customer_facing_clause"] = "这款防潮表现很好。"
    outputs = iter([_intake(), bad])
    monkeypatch.setattr(service, "_request_json_schema", lambda **kwargs: next(outputs))
    _stub_tool_execution(monkeypatch, service)

    proposal, _ = service.build_for_response(
        {"selected_evidence": [_fact()]},
        customer_message="这个材质安全吗，会不会受潮？",
        product_identity={"sku_code": "SKU-A"},
    )

    assert proposal["shadow_status"] == "degraded"
    assert "unsupported_claim_asserted" in proposal["contract_violations"]


def test_paraphrases_use_structured_understanding_not_fixed_reply_template(monkeypatch):
    service = AgentDecisionProposalService()
    seen_payloads = []

    def fake_request(**kwargs):
        seen_payloads.append(kwargs["payload"])
        return _intake() if kwargs["name"] == "agent_decision_intake" else _proposal()

    monkeypatch.setattr(service, "_request_json_schema", fake_request)
    _stub_tool_execution(monkeypatch, service)
    for message in ("这个材质安全吗，会不会受潮？", "遇到潮气怎么样，材料用着放心吗？"):
        proposal, _ = service.build_for_response(
            {"selected_evidence": [_fact()]},
            customer_message=message,
            product_identity={"sku_code": "SKU-A"},
        )
        assert proposal["understanding"]["requested_claims"] == _understanding()["requested_claims"]
    assert seen_payloads[0]["customer_message"] != seen_payloads[2]["customer_message"]


def test_application_executes_tool_plan_before_proposal(monkeypatch):
    service = AgentDecisionProposalService()
    events = []

    def fake_request(**kwargs):
        events.append(kwargs["name"])
        if kwargs["name"] == "agent_decision_intake":
            return _intake()
        assert kwargs["payload"]["shadow_tool_execution"]["executed_tool_names"] == ["rag_search_tool"]
        return _proposal()

    def fake_execute(**kwargs):
        events.append("application_tool_execution")
        assert kwargs["tool_plan"] == _tool_plan()
        return _tool_execution()

    monkeypatch.setattr(service, "_request_json_schema", fake_request)
    monkeypatch.setattr(service, "_execute_shadow_tool_plan", fake_execute)

    proposal, admitted = service.build_for_response(
        {"selected_evidence": [_fact()]},
        customer_message="这个材质安全吗，会不会受潮？",
        product_identity={"sku_code": "SKU-A"},
    )

    assert events == ["agent_decision_intake", "application_tool_execution", "agent_decision_proposal"]
    assert proposal["shadow_status"] == "completed"
    assert admitted["shadow_tool_execution"]["shadow_only"] is True


def test_order_and_media_requests_are_deferred_without_shadow_adapters():
    service = AgentDecisionProposalService()
    plan = {
        "retrieval_needed": False,
        "product_identity_lookup_needed": False,
        "order_lookup_needed": True,
        "media_lookup_needed": True,
    }

    execution = service._execute_shadow_tool_plan(
        tool_plan=plan,
        understanding=_understanding(),
        response={},
        customer_message="请查订单并发安装图",
        product_identity={},
        copilot_context={},
    )

    assert execution["executed_tool_names"] == []
    assert {item["capability"] for item in execution["deferred_capabilities"]} == {
        "order_lookup", "media_lookup",
    }
    assert execution["tool_results"] == {}
