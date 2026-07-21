from __future__ import annotations

import json

from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_turn_evidence_funnel,
)
from app.services.analysis_pipeline_service import AnalysisPipelineRequest, AnalysisPipelineService


def _fact(uid: str = "fact-material", sku: str = "SKU-A") -> dict:
    return {
        "evidence_uid": uid,
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "fact_type": "material_composition",
        "attribute_key": "material",
        "content": "主体材质为 PP。",
        "material_provenance": "structured_product_record",
        "sku_code": sku,
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
    }


def _understanding() -> dict:
    return {
        "requested_claims": [{
            "claim_type": "material_composition",
            "attribute_key": "material",
            "question": "是什么材质",
            "risk_level": "medium",
        }],
    }


def _response() -> dict:
    return {
        "suggested_reply": "正式回复保持不变。",
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
        "reply_status": "needs_human_review",
        "selected_evidence": [],
        "formal_evidence_candidates": [_fact()],
        "turn_understanding": _understanding(),
        "reply_blocks": [{"type": "text", "content": "正式回复保持不变。"}],
    }


def _funnel(response: dict, *, identity: dict, understanding: dict, enabled: bool) -> dict:
    admitted = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity=identity,
        understanding=understanding,
    )
    return build_turn_evidence_funnel(
        response,
        product_identity=identity,
        admitted_context=admitted,
        convergence_enabled=enabled,
    )


def test_funnel_reports_convergence_disabled_without_leaking_fact_content():
    funnel = _funnel(
        _response(),
        identity={"sku_code": "SKU-A"},
        understanding=_understanding(),
        enabled=False,
    )

    assert funnel["counts"]["formally_admissible_count"] == 1
    assert funnel["counts"]["formal_selected_count"] == 0
    assert funnel["earliest_breakpoint"] == "convergence_disabled"
    assert funnel["gap_classification"] == "convergence_disabled"
    serialized = json.dumps(funnel, ensure_ascii=False)
    assert "SKU-A" not in serialized
    assert "主体材质为 PP" not in serialized


def test_funnel_assigns_one_earliest_breakpoint_for_context_identity_and_source():
    response = _response()
    assert _funnel(
        response,
        identity={"sku_code": "SKU-A"},
        understanding={"requested_claims": []},
        enabled=False,
    )["earliest_breakpoint"] == "context_missing"
    assert _funnel(
        response,
        identity={},
        understanding=_understanding(),
        enabled=False,
    )["earliest_breakpoint"] == "product_identity_missing"
    response["formal_evidence_candidates"] = []
    assert _funnel(
        response,
        identity={"sku_code": "SKU-A"},
        understanding=_understanding(),
        enabled=False,
    )["earliest_breakpoint"] == "source_coverage_gap"


def test_funnel_distinguishes_ineligible_role_graph_gap_and_selected_success():
    response = _response()
    response["formal_evidence_candidates"] = [{
        "evidence_uid": "service-action",
        "source_type": "service_action",
        "evidence_role": "service_action",
        "content": "核对商品资料",
        "reference_only": True,
    }]
    assert _funnel(
        response,
        identity={"sku_code": "SKU-A"},
        understanding=_understanding(),
        enabled=False,
    )["earliest_breakpoint"] == "evidence_role_ineligible"

    response = _response()
    assert _funnel(
        response,
        identity={"sku_code": "SKU-A"},
        understanding=_understanding(),
        enabled=True,
    )["earliest_breakpoint"] == "graph_selection_gap"
    response["selected_evidence"] = [_fact()]
    selected = _funnel(
        response,
        identity={"sku_code": "SKU-A"},
        understanding=_understanding(),
        enabled=True,
    )
    assert selected["earliest_breakpoint"] == "selected_successfully"
    assert selected["counts"]["formal_selected_count"] == 1


def test_pipeline_keeps_evidence_action_paused_even_when_stale_flag_is_set(monkeypatch):
    monkeypatch.setenv("COPILOT_EVIDENCE_ACTION_SHADOW_ENABLED", "true")
    monkeypatch.delenv("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("COPILOT_LLM_DECISION_SHADOW_ENABLED", raising=False)
    response = _response()

    updated, stages = AnalysisPipelineService()._attach_shadow_layers(
        response,
        AnalysisPipelineRequest(customer_message="问题", reply_service=object()),
        {"sku_code": "SKU-A", "i_id": "", "product_name": ""},
    )

    assert updated["suggested_reply"] == "正式回复保持不变。"
    assert updated["can_send"] is False
    stage = next(item for item in stages if item["stage"] == "evidence_action_shadow")
    assert stage == {
        "stage": "evidence_action_shadow",
        "status": "disabled",
        "reason": "paused_not_qualified",
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }
