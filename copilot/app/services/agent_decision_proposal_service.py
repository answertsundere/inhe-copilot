"""Strict, evidence-first decision proposal for post-graph shadow comparison."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    resolved_product_identity_for_response,
)
from app.services.claim_polarity_service import contains_asserted_claim
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


class RequestedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: str
    question: str
    risk_level: Literal["low", "medium", "high", "critical"]


class DecisionUnderstanding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_question: str
    requested_claims: list[RequestedClaim]
    uncertainty_items: list[str]
    requested_fact_types: list[str]


class ToolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_needed: bool
    product_identity_lookup_needed: bool
    order_lookup_needed: bool
    media_lookup_needed: bool


class DecisionIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")

    understanding: DecisionUnderstanding
    tool_plan: ToolPlan


class EvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_evidence_uids: list[str]
    requested_evidence_uids: list[str]
    unsupported_claims: list[str]


class ReplyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["direct_answer", "controlled_handoff", "ask_clarification"]
    factual_clause_evidence_uids: list[str]
    action_guidance_evidence_uids: list[str]
    proposed_reply: str


class DeliveryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_reply_block_refs: list[str]
    requires_human_review: bool


class AgentDecisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    understanding: DecisionUnderstanding
    tool_plan: ToolPlan
    evidence_selection: EvidenceSelection
    reply_plan: ReplyPlan
    delivery_intent: DeliveryIntent
    used_for_final_reply: Literal[False]
    can_change_can_send: Literal[False]


_UNDERSTANDING_SYSTEM_PROMPT = """You are the understanding and tool-planning stage of a customer-service decision system.
Return only the requested strict JSON object. Split compound questions into independent claims and
propose which read-only information tools the application should run before drafting a reply.
Material composition does not prove material safety, non-toxicity, certification, child suitability,
or moisture resistance. Do not invent product, order, media, policy, or delivery facts. Tool booleans
are proposals only; the application owns tool execution and permissions. Never output can_send,
send, refund, replacement, compensation, or an action execution result."""

_PROPOSAL_SYSTEM_PROMPT = """You are a shadow-only customer-service decision planner.
Return only the requested strict JSON object. Product factual clauses may cite only evidence UIDs
from direct_product_facts or direct_policy_facts. Service actions may cite only
handoff_action_guidance. Media candidates are references, not proof that media was sent.
Do not turn unresolved claims into facts. Do not claim refund, replacement, compensation,
certification, safety, child suitability, load limits, or sent media without admitted evidence and
an actual reply block. You propose wording; the application owns delivery and can_send."""

_UNSUPPORTED_CLAIM_TERMS = {
    "material_safety": ("安全", "无毒", "食品级", "放心咬"),
    "moisture_resistance": ("防潮", "耐潮", "不会受潮", "不受潮"),
    "certification_report": ("有检测报告", "有认证", "有证书"),
    "load_capacity": ("承重", "能承受", "可承载"),
    "child_suitability": ("适合儿童", "宝宝可以用", "儿童适用"),
}


def llm_decision_shadow_enabled() -> bool:
    return sanitize_text(os.getenv("COPILOT_LLM_DECISION_SHADOW_ENABLED", "")).lower() in {
        "1", "true", "yes", "on",
    }


def _schema_for(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def _empty_understanding(customer_message: str) -> dict[str, Any]:
    return {
        "primary_question": sanitize_text(customer_message),
        "requested_claims": [],
        "uncertainty_items": ["structured_understanding_unavailable"],
        "requested_fact_types": [],
    }


def _safe_fallback(
    customer_message: str,
    *,
    understanding: dict[str, Any] | None = None,
    tool_plan: dict[str, Any] | None = None,
    error: str,
) -> dict[str, Any]:
    return {
        "understanding": understanding or _empty_understanding(customer_message),
        "tool_plan": tool_plan or {
            "retrieval_needed": False,
            "product_identity_lookup_needed": False,
            "order_lookup_needed": False,
            "media_lookup_needed": False,
        },
        "evidence_selection": {
            "candidate_evidence_uids": [],
            "requested_evidence_uids": [],
            "unsupported_claims": ["decision_proposal_unavailable"],
        },
        "reply_plan": {
            "mode": "controlled_handoff",
            "factual_clause_evidence_uids": [],
            "action_guidance_evidence_uids": [],
            "proposed_reply": "",
        },
        "delivery_intent": {
            "proposed_reply_block_refs": [],
            "requires_human_review": True,
        },
        "used_for_final_reply": False,
        "can_change_can_send": False,
        "shadow_status": "degraded",
        "fallback_reason": error,
    }


def _safe_error_reason(stage: str, exc: Exception) -> str:
    detail = sanitize_text(str(exc)).lower()
    allowed = {
        "llm_not_configured",
        "provider_not_configured",
        "provider_not_qualified",
        "strict_capability_not_supported",
        "strict_schema_rejected",
        "strict_tool_call_missing",
        "structured_output_not_json",
        "empty_structured_output",
        "structured_output_not_object",
        "timeout",
        "rate_limited",
        "authentication_failed",
        "provider_request_failed",
    }
    category = detail if detail in allowed else type(exc).__name__
    return f"{stage}_error:{category}"


def _reply_block_refs(response: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for index, block in enumerate(response.get("reply_blocks") or []):
        if not isinstance(block, dict):
            continue
        refs.add(sanitize_text(block.get("block_id") or block.get("ref") or f"reply_block:{index}"))
    return {item for item in refs if item}


def _unique_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = sanitize_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _shadow_tool_state(
    response: dict[str, Any],
    *,
    customer_message: str,
    product_identity: dict[str, Any],
    copilot_context: dict[str, Any],
) -> dict[str, Any]:
    context_used = response.get("context_used") if isinstance(response.get("context_used"), dict) else {}
    evidence_debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    source_types = _unique_text([
        *(context_used.get("allowed_source_types") or []),
        *(evidence_debug.get("fusion_allowed_source_types") or []),
    ])
    matched_name = sanitize_text(
        product_identity.get("matched_product_name")
        or product_identity.get("product_name")
        or product_identity.get("product_title")
        or response.get("display_product_name")
    )
    identity = {
        **product_identity,
        "status": "resolved" if product_identity else "",
        "matched_product_name": matched_name,
        "sku_id": sanitize_text(product_identity.get("sku_code") or product_identity.get("sku")),
    }
    return {
        "input_message": customer_message,
        "intent": sanitize_text(response.get("intent")),
        "query_fact_type": sanitize_text(evidence_debug.get("query_fact_type")),
        "allowed_source_types": source_types,
        "matched_product_name": matched_name,
        "order_product_identity": identity,
        "slots": {
            "product_name": matched_name,
            "sku_code": sanitize_text(product_identity.get("sku_code") or product_identity.get("sku")),
        },
        "copilot_context": {**copilot_context, "shadow_only": True},
    }


def _unsupported_assertions(reply: str, unresolved_claims: list[dict[str, Any]]) -> list[str]:
    violations: list[str] = []
    for claim in unresolved_claims:
        claim_type = sanitize_text(claim.get("claim_type")).lower()
        for term in _UNSUPPORTED_CLAIM_TERMS.get(claim_type, ()):
            pending_context = False
            for index in [match.start() for match in re.finditer(re.escape(term), reply)]:
                window = reply[max(0, index - 12):min(len(reply), index + len(term) + 28)]
                if ("需要" in window or "待" in window) and ("确认" in window or "核实" in window):
                    pending_context = True
                    break
            if contains_asserted_claim(reply, term) and not pending_context:
                violations.append(claim_type)
                break
    return sorted(set(violations))


class AgentDecisionProposalService:
    """Run strict schema calls and attach a read-only shadow decision."""

    def _execute_shadow_tool_plan(
        self,
        *,
        tool_plan: dict[str, Any],
        understanding: dict[str, Any],
        response: dict[str, Any],
        customer_message: str,
        product_identity: dict[str, Any],
        copilot_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute only registered, read-only local tools for the shadow proposal.

        Order and media proposals remain explicit deferred requests until a bounded,
        read-only shadow adapter exists for those capabilities.
        """
        from app.agent.tools.executor import ToolExecutor

        state = _shadow_tool_state(
            response,
            customer_message=customer_message,
            product_identity=product_identity,
            copilot_context=copilot_context,
        )
        calls: list[dict[str, Any]] = []
        deferred: list[dict[str, str]] = []
        if tool_plan.get("product_identity_lookup_needed"):
            calls.append({"tool_name": "product_resolver_tool", "inputs": {"message": customer_message}})
        if tool_plan.get("retrieval_needed"):
            product_scope = _unique_text([
                state.get("matched_product_name"),
                product_identity.get("product_title"),
            ])
            calls.append({
                "tool_name": "rag_search_tool",
                "inputs": {
                    "query": customer_message,
                    "source_types": state.get("allowed_source_types") or [],
                    "intent": state.get("intent") or "",
                    "product_scope": product_scope,
                    "fact_type": (
                        (understanding.get("requested_fact_types") or [""])[0]
                        or state.get("query_fact_type")
                        or ""
                    ),
                },
            })
        if tool_plan.get("order_lookup_needed"):
            deferred.append({
                "capability": "order_lookup",
                "reason": "bounded_shadow_adapter_not_available",
            })
        if tool_plan.get("media_lookup_needed"):
            deferred.append({
                "capability": "media_lookup",
                "reason": "registered_read_only_tool_not_available",
            })

        execution = ToolExecutor().execute_plan(calls, state, total_timeout_ms=5000) if calls else {
            "tool_results": {},
            "tool_traces": [],
            "total_duration_ms": 0,
            "timed_out": False,
            "requires_human_review": False,
        }
        return sanitize_obj({
            "schema_version": "llm-decision-shadow-tool-execution-v1",
            "shadow_only": True,
            "planned_tool_flags": tool_plan,
            "executed_tool_names": [call["tool_name"] for call in calls],
            "deferred_capabilities": deferred,
            **execution,
        })

    def _request_json_schema(
        self,
        *,
        name: str,
        schema: dict[str, Any],
        system_prompt: str,
        payload: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        from app.services.strict_decision_provider_service import StrictDecisionProviderService

        return StrictDecisionProviderService().request(
            name=name,
            schema=schema,
            system_prompt=system_prompt,
            payload=payload,
            max_tokens=max_tokens,
        )

    def build_for_response(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        product_identity: dict[str, Any] | None = None,
        copilot_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        message = sanitize_text(customer_message)
        identity = resolved_product_identity_for_response(response, product_identity)
        context = copilot_context if isinstance(copilot_context, dict) else {}
        understanding_payload = {
            "customer_message": message,
            "intent": sanitize_text(response.get("intent")),
            "resolved_product_identity": identity,
            "has_order_identifier": bool(
                context.get("order_id") or context.get("platform_order_id") or context.get("platform_trade_id")
            ),
            "structured_turn_understanding": sanitize_obj(response.get("turn_understanding") or {}),
        }
        try:
            raw_intake = self._request_json_schema(
                name="agent_decision_intake",
                schema=_schema_for(DecisionIntake),
                system_prompt=_UNDERSTANDING_SYSTEM_PROMPT,
                payload=understanding_payload,
                max_tokens=700,
            )
            intake = DecisionIntake.model_validate(raw_intake).model_dump()
            understanding = intake["understanding"]
            tool_plan = intake["tool_plan"]
        except Exception as exc:
            fallback = _safe_fallback(message, error=_safe_error_reason("understanding", exc))
            admitted = AdmittedAnswerContextService().build_for_response(
                response,
                product_identity=identity,
                understanding=fallback["understanding"],
            )
            return sanitize_obj(fallback), admitted

        tool_execution = self._execute_shadow_tool_plan(
            tool_plan=tool_plan,
            understanding=understanding,
            response=response,
            customer_message=message,
            product_identity=identity,
            copilot_context=context,
        )
        admission_response = deepcopy(response)
        admission_response.setdefault("evidence_debug", {})[
            "llm_decision_shadow_tool_results"
        ] = tool_execution.get("tool_results") or {}
        admitted = AdmittedAnswerContextService().build_for_response(
            admission_response,
            product_identity=identity,
            understanding=understanding,
        )
        admitted["shadow_tool_execution"] = tool_execution
        proposal_payload = {
            "customer_message": message,
            "understanding": understanding,
            "tool_plan": tool_plan,
            "shadow_tool_execution": tool_execution,
            "admitted_answer_context": admitted,
            "actual_reply_block_refs": sorted(_reply_block_refs(response)),
        }
        try:
            raw_proposal = self._request_json_schema(
                name="agent_decision_proposal",
                schema=_schema_for(AgentDecisionProposal),
                system_prompt=_PROPOSAL_SYSTEM_PROMPT,
                payload=proposal_payload,
                max_tokens=1500,
            )
            proposal = AgentDecisionProposal.model_validate(raw_proposal).model_dump()
        except Exception as exc:
            return sanitize_obj(
                _safe_fallback(message, understanding=understanding, error=_safe_error_reason("proposal", exc))
            ), admitted

        direct_uids = {
            sanitize_text(item.get("evidence_uid"))
            for item in [*(admitted.get("direct_product_facts") or []), *(admitted.get("direct_policy_facts") or [])]
        }
        action_uids = {
            sanitize_text(item.get("evidence_uid"))
            for item in admitted.get("handoff_action_guidance") or []
        }
        media_uids = {
            sanitize_text(item.get("evidence_uid"))
            for item in admitted.get("media_candidates") or []
        }
        all_uids = direct_uids | action_uids | media_uids
        violations: list[str] = []
        if proposal["understanding"] != understanding:
            violations.append("understanding_changed_after_tool_execution")
        if proposal["tool_plan"] != tool_plan:
            violations.append("tool_plan_changed_after_execution")
        if not set(proposal["reply_plan"]["factual_clause_evidence_uids"]).issubset(direct_uids):
            violations.append("unadmitted_factual_evidence_reference")
        if not set(proposal["reply_plan"]["action_guidance_evidence_uids"]).issubset(action_uids):
            violations.append("invalid_action_guidance_reference")
        if not set(proposal["evidence_selection"]["candidate_evidence_uids"]).issubset(all_uids):
            violations.append("unknown_candidate_evidence_reference")
        if not set(proposal["evidence_selection"]["requested_evidence_uids"]).issubset(direct_uids | action_uids):
            violations.append("invalid_requested_evidence_reference")
        if not set(proposal["delivery_intent"]["proposed_reply_block_refs"]).issubset(_reply_block_refs(response)):
            violations.append("unattached_reply_block_reference")
        unsupported = _unsupported_assertions(
            proposal["reply_plan"]["proposed_reply"],
            admitted.get("unresolved_claims") or [],
        )
        if unsupported:
            violations.append("unsupported_claim_asserted")
        if violations:
            fallback = _safe_fallback(message, understanding=understanding, error="contract_violation")
            fallback["contract_violations"] = sorted(set(violations))
            fallback["unsupported_assertion_claim_types"] = unsupported
            return sanitize_obj(fallback), admitted

        proposal["shadow_status"] = "completed"
        proposal["fallback_reason"] = ""
        proposal["contract_violations"] = []
        return sanitize_obj(proposal), admitted

    def attach_shadow_decision(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        product_identity: dict[str, Any] | None = None,
        copilot_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        original = deepcopy(response)
        proposal, admitted = self.build_for_response(
            original,
            customer_message=customer_message,
            product_identity=product_identity,
            copilot_context=copilot_context,
        )
        response.setdefault("evidence_debug", {})["llm_decision_proposal"] = proposal
        response["evidence_debug"]["admitted_answer_context"] = admitted
        response.setdefault("answer_trace", {})["llm_decision_shadow"] = {
            "schema_version": "agent-decision-proposal-v1",
            "shadow_only": True,
            "used_for_final_reply": False,
            "can_change_can_send": False,
            "status": proposal.get("shadow_status"),
            "formal_reply": sanitize_text(original.get("suggested_reply")),
            "shadow_proposal_reply": sanitize_text((proposal.get("reply_plan") or {}).get("proposed_reply")),
            "admitted_fact_uids": [item.get("evidence_uid") for item in admitted.get("direct_product_facts") or []],
            "unresolved_claims": admitted.get("unresolved_claims") or [],
            "unsupported_claims": (proposal.get("evidence_selection") or {}).get("unsupported_claims") or [],
            "formal_can_send": bool(original.get("can_send")),
            "tool_execution": admitted.get("shadow_tool_execution") or {},
        }
        return response
