from __future__ import annotations

import time
from typing import Any

from app.agent.schemas.understanding import DecisionFusionResult


RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def decision_fusion(state: dict) -> dict:
    t0 = time.time()
    pu = state.get("parallel_understanding") or {}

    intent_data = _data(pu, "intent_classifier")
    risk_data = _data(pu, "risk_classifier")
    slot_data = _data(pu, "slot_entity_extractor")
    context_data = _data(pu, "context_resolver")
    customer_data = _data(pu, "customer_state_analyzer")
    tool_data = _data(pu, "tool_need_predictor")
    scope_data = _data(pu, "knowledge_scope_predictor")
    safety_data = _data(pu, "safety_precheck")

    identifiers = slot_data.get("identifiers", [])
    id_types = {item.get("type") for item in identifiers}
    fusion_reasons: list[str] = []

    final_intent = intent_data.get("primary_intent") or "general"
    secondary_intents = list(intent_data.get("secondary_intents") or [])

    if id_types and final_intent == "product_question":
        final_intent = "logistics_eta"
        fusion_reasons.append("identifier_present_prevents_product_question")
    if context_data.get("is_followup") and context_data.get("active_issue"):
        active_issue = context_data.get("active_issue")
        if active_issue in ("delivery_not_received", "logistics_eta", "logistics_tracking"):
            final_intent = active_issue
            fusion_reasons.append("followup_active_issue_preserved")

    risk_level = risk_data.get("risk_level") or "low"
    risk_reasons = list(risk_data.get("risk_reasons") or [])
    need_human_review = bool(risk_data.get("need_human_review"))
    if any(item in secondary_intents for item in ("complaint", "complaint_threat")):
        if RISK_ORDER.get(risk_level, 0) < RISK_ORDER["high"]:
            risk_level = "high"
        need_human_review = True
        fusion_reasons.append("complaint_secondary_forces_high_risk")

    if final_intent in ("missing_item", "damaged_item", "wrong_item", "delivery_not_received"):
        if RISK_ORDER.get(risk_level, 0) < RISK_ORDER["medium"]:
            risk_level = "medium"
        need_human_review = True
        fusion_reasons.append("issue_requires_manual_followup")

    required_tools = _merge_tools(tool_data.get("required_tools", []), [])
    allowed_tools = list(tool_data.get("allowed_tools") or [])
    forbidden_tools = [tool for tool in (tool_data.get("forbidden_tools") or []) if tool not in required_tools]

    if "platform_trade_id" in id_types and final_intent.startswith("logistics"):
        required_tools = _merge_tools(required_tools, ["jst_lookup_outbound_tool"])
        fusion_reasons.append("platform_trade_id_requires_outbound_lookup")
    if "tracking_no" in id_types:
        required_tools = _merge_tools(required_tools, ["jst_lookup_tracking_tool"])
        fusion_reasons.append("tracking_no_requires_tracking_lookup")
    if final_intent in ("product_question", "material_question", "size_question", "installation_question"):
        required_tools = _merge_tools(required_tools, ["product_resolver_tool", "rag_search_tool"])
        forbidden_tools = _merge_tools(forbidden_tools, [
            tool for tool in ("jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool")
            if tool not in required_tools
        ])
        fusion_reasons.append("product_fact_question_requires_product_and_rag")
    if risk_level == "high" or final_intent in ("complaint", "compensation_request"):
        required_tools = _merge_tools(required_tools, ["sop_lookup_tool"])
        fusion_reasons.append("high_risk_requires_sop")

    allowed_source_types = list(scope_data.get("allowed_source_types") or [])
    forbidden_source_types = list(scope_data.get("forbidden_source_types") or [])

    answer_mode = _answer_mode(final_intent, safety_data, required_tools, slot_data)
    reply_goal = _reply_goal(final_intent, customer_data, risk_level)
    missing_slots = list(slot_data.get("missing_slots") or [])
    customer_concern = customer_data.get("customer_concern", "")
    confidence = min(
        float(intent_data.get("confidence", 0.7)),
        float(risk_data.get("confidence", 0.8)),
        float(tool_data.get("confidence", 0.8)),
    )

    result = DecisionFusionResult(
        final_intent=final_intent,
        secondary_intents=_unique(secondary_intents),
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        need_human_review=need_human_review,
        answer_mode=answer_mode,
        reply_goal=reply_goal,
        required_tools=required_tools,
        allowed_tools=allowed_tools,
        forbidden_tools=forbidden_tools,
        allowed_source_types=allowed_source_types,
        forbidden_source_types=forbidden_source_types,
        safety_contract=_safety_contract_from(safety_data),
        customer_concern=customer_concern,
        missing_slots=_unique(missing_slots),
        fusion_reasons=_unique(fusion_reasons),
        confidence=round(confidence, 3),
        status="success" if pu else "skipped",
    ).to_dict()

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "decision_fusion",
        "status": result["status"],
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"final_intent={result['final_intent']}, risk={result['risk_level']}, mode=observation",
    }
    return {
        "decision_fusion": result,
        "safety_contract": result.get("safety_contract", {}),
        "final_intent": result.get("final_intent", ""),
        "secondary_intents": result.get("secondary_intents", []),
        "fusion_reasons": result.get("fusion_reasons", []),
        "parallel_observation_mode": True,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _data(pu: dict, key: str) -> dict[str, Any]:
    item = pu.get(key) or {}
    if isinstance(item, dict) and isinstance(item.get("data"), dict):
        return item["data"]
    return {}


def _safety_contract_from(data: dict) -> dict[str, Any]:
    keys = (
        "forbidden_claims",
        "requires_evidence_for",
        "must_escalate_if",
        "allowed_fact_sources",
        "forbidden_reply_patterns",
        "must_include",
        "must_not_include",
    )
    return {key: list(data.get(key) or []) for key in keys}


def _answer_mode(final_intent: str, safety_data: dict, required_tools: list[str], slot_data: dict) -> str:
    if final_intent in ("complaint", "compensation_request") or safety_data.get("must_escalate_if"):
        return "sop_human_review_answer"
    if final_intent in ("material_question", "size_question", "product_question", "installation_question"):
        if safety_data.get("requires_evidence_for"):
            return "no_evidence_clarification"
        return "product_fact_answer"
    if final_intent in ("logistics_eta", "logistics_tracking"):
        if "jst_lookup_outbound_tool" in required_tools or "jst_lookup_tracking_tool" in required_tools:
            return "logistics_fact_answer"
        return "policy_grounded_answer"
    if final_intent in ("missing_item", "damaged_item", "wrong_item", "refund_request", "return_request"):
        return "sop_human_review_answer"
    if slot_data.get("missing_slots"):
        return "no_evidence_clarification"
    return "policy_grounded_answer"


def _reply_goal(final_intent: str, customer_data: dict, risk_level: str) -> str:
    concern = customer_data.get("customer_concern")
    if concern == "wants_eta_certainty":
        return "explain_no_guarantee"
    if risk_level == "high":
        return "deescalate_and_human_review"
    if final_intent in ("material_question", "product_question"):
        return "answer_with_evidence_or_clarify"
    if final_intent.startswith("logistics"):
        return "query_logistics_or_request_identifier"
    return "answer_or_clarify"


def _merge_tools(base: list[str], extra: list[str]) -> list[str]:
    return _unique(list(base or []) + list(extra or []))


def _unique(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
