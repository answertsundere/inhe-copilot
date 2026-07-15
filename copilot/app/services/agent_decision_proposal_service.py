"""Strict, evidence-first decision proposal for post-graph shadow comparison."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_minimal_decision_context,
    resolved_product_identity_for_response,
)
from app.services.claim_polarity_service import contains_asserted_claim
from app.services.customer_facing_safe_handoff_service import (
    CUSTOMER_FACING_INTERNAL_REDLINE_TERMS,
    customer_facing_safe_handoff_reply,
)
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.fact_type_service import FACT_TYPE_LABELS
from app.services.grounded_reasoning_draft_service import has_mojibake_draft
from app.services.no_evidence_reply_policy_service import (
    contains_unsupported_media_promise,
    has_attached_sendable_media_asset,
)


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


class ClaimResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: str
    claim_uid: str
    attribute_key: str = ""
    status: Literal["supported", "unresolved", "conflicting", "prohibited", "not_applicable"]
    evidence_uids: list[str]
    admitted_fact_texts: list[str]
    conflicting_evidence_uids: list[str]
    requires_human_review: bool
    reason: str


class ConfirmedClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: str
    evidence_uids: list[str]
    customer_facing_clause: str


class PendingClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: str
    reason: str
    customer_facing_clause: str


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
    claim_resolutions: list[ClaimResolution]
    confirmed_clauses: list[ConfirmedClause]
    pending_clauses: list[PendingClause]
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
Copy claim_resolutions from the application context exactly. Create one confirmed clause for every
supported claim and one pending clause for every unresolved or conflicting claim. Do not turn
unresolved claims into facts. Do not claim refund, replacement, compensation,
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
        "claim_resolutions": [],
        "confirmed_clauses": [],
        "pending_clauses": [],
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
        "structured_output_truncated",
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
                sentence = _sentence_containing(reply, index)
                if ("需要" in sentence or "待" in sentence) and ("确认" in sentence or "核实" in sentence):
                    pending_context = True
                    break
            if contains_asserted_claim(reply, term) and not pending_context:
                violations.append(claim_type)
                break
    return sorted(set(violations))


def _sentence_containing(text: str, index: int) -> str:
    start = max(text.rfind(mark, 0, index) for mark in "。！？!?；;\n") + 1
    endings = [text.find(mark, index) for mark in "。！？!?；;\n"]
    end = min((position for position in endings if position >= 0), default=len(text))
    return text[start:end]


def _partial_answer_contract_violations(
    proposal: dict[str, Any],
    claim_resolutions: list[dict[str, Any]],
) -> list[str]:
    """Ensure the model renders every supported claim and preserves every pending one."""
    expected = {
        sanitize_text(item.get("claim_type")): item
        for item in claim_resolutions
        if sanitize_text(item.get("claim_type"))
    }
    submitted = {
        sanitize_text(item.get("claim_type")): item
        for item in proposal.get("claim_resolutions") or []
        if sanitize_text(item.get("claim_type"))
    }
    violations: list[str] = []
    if submitted != expected:
        violations.append("claim_resolution_changed")

    expected_confirmed = {
        claim_type: item for claim_type, item in expected.items()
        if item.get("status") == "supported"
    }
    expected_pending = {
        claim_type: item for claim_type, item in expected.items()
        if item.get("status") in {"unresolved", "conflicting", "prohibited"}
    }
    confirmed = {
        sanitize_text(item.get("claim_type")): item
        for item in proposal.get("confirmed_clauses") or []
        if sanitize_text(item.get("claim_type"))
    }
    pending = {
        sanitize_text(item.get("claim_type")): item
        for item in proposal.get("pending_clauses") or []
        if sanitize_text(item.get("claim_type"))
    }
    if set(confirmed) != set(expected_confirmed):
        violations.append("supported_claim_omitted")
    if set(pending) != set(expected_pending):
        violations.append("pending_claim_omitted")

    reply = sanitize_text((proposal.get("reply_plan") or {}).get("proposed_reply"))
    for claim_type, expected_resolution in expected_confirmed.items():
        clause = confirmed.get(claim_type) or {}
        clause_uids = {sanitize_text(value) for value in clause.get("evidence_uids") or [] if sanitize_text(value)}
        allowed_uids = {
            sanitize_text(value) for value in expected_resolution.get("evidence_uids") or [] if sanitize_text(value)
        }
        customer_clause = sanitize_text(clause.get("customer_facing_clause"))
        if not clause_uids or not clause_uids.issubset(allowed_uids):
            violations.append("confirmed_clause_evidence_invalid")
        if not customer_clause or customer_clause not in reply:
            violations.append("confirmed_clause_not_rendered")
    for claim_type, expected_resolution in expected_pending.items():
        clause = pending.get(claim_type) or {}
        customer_clause = sanitize_text(clause.get("customer_facing_clause"))
        if sanitize_text(clause.get("reason")) != sanitize_text(expected_resolution.get("reason")):
            violations.append("pending_clause_reason_changed")
        if not customer_clause or customer_clause not in reply:
            violations.append("pending_clause_not_rendered")
    return sorted(set(violations))


_PREVIEW_INTERNAL_TERMS = (*CUSTOMER_FACING_INTERNAL_REDLINE_TERMS, "evidence_uid", "rag", "RAG")


def _preview_claim_label(claim_type: str) -> str:
    return sanitize_text(FACT_TYPE_LABELS.get(claim_type)) or "相关信息"


def _preview_fact_index(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    blocked_roles = {"service_action", "fallback_only", "media_reference", "answer_memory", "correct_answer"}
    return {
        sanitize_text(item.get("evidence_uid")): item
        for item in context.get("admitted_evidence") or []
        if isinstance(item, dict)
        and sanitize_text(item.get("evidence_uid"))
        and sanitize_text(item.get("evidence_role")).lower() not in blocked_roles
        and sanitize_text(item.get("source_type")).lower() not in blocked_roles
    }


def _preview_clause_text(facts: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for fact in facts:
        value = sanitize_text(fact.get("content"))
        if value and not any(term.lower() in value.lower() for term in _PREVIEW_INTERNAL_TERMS):
            values.append(value)
    return "；".join(dict.fromkeys(values))


def _preview_pending_text(claim_type: str, status: str) -> str:
    label = _preview_claim_label(claim_type)
    if status == "conflicting":
        return f"{label}的现有资料存在不一致，需要进一步核对。"
    if status == "prohibited":
        return f"{label}属于需要谨慎确认的信息，暂不作结论。"
    return f"{label}还需要结合当前商品资料确认。"


def _preview_safety_validation(
    preview: dict[str, Any],
    *,
    minimal_context: dict[str, Any],
) -> dict[str, Any]:
    """Validate a preview on copies only; final orchestration never observes it."""
    text = sanitize_text(preview.get("candidate_text"))
    issues: list[str] = []
    cited = set(preview.get("evidence_uids") or [])
    known = set(_preview_fact_index(minimal_context))
    if not cited.issubset(known):
        issues.append("unknown_preview_evidence")
    if any(term.lower() in text.lower() for term in _PREVIEW_INTERNAL_TERMS):
        issues.append("internal_jargon")
    if has_mojibake_draft({"grounded_draft": text}):
        issues.append("mojibake")
    identity = minimal_context.get("product_identity") or {}
    identity_values = {
        sanitize_text(identity.get(key))
        for key in ("sku_code", "i_id", "product_id", "order_id", "order_id_hash", "content_hash")
        if sanitize_text(identity.get(key))
    }
    if any(value in text for value in identity_values):
        issues.append("identity_leakage")
    if contains_unsupported_media_promise(
        text,
        has_attached_sendable_media_asset({"reply_blocks": preview.get("reply_blocks") or []}),
    ):
        issues.append("unsupported_media_promise")
    if preview.get("can_send") is not False or preview.get("used_for_final_reply") is not False:
        issues.append("formal_delivery_contract_violation")

    # Reuse the formal audit implementations on an isolated copy as a
    # diagnostic signal. Their output never replaces or mutates the response.
    audit_summary: dict[str, Any] = {}
    if text:
        try:
            from app.services.final_answer_auditor import audit_final_answer
            from app.services.final_semantic_quality_service import audit_customer_reply_semantic_fit

            probe = {
                "suggested_reply": text,
                "can_send": False,
                "requires_human_review": True,
                "reply_blocks": [{"type": "text", "content": text}],
                "selected_evidence": list(minimal_context.get("admitted_evidence") or []),
                "query_fact_type": sanitize_text(
                    ((minimal_context.get("requested_claims") or [{}])[0] or {}).get("claim_type")
                ),
            }
            audited = audit_final_answer(deepcopy(probe), customer_message=sanitize_text(minimal_context.get("customer_goal")))
            semantic = audit_customer_reply_semantic_fit(
                deepcopy(audited), customer_message=sanitize_text(minimal_context.get("customer_goal"))
            )
            audit_summary = {
                "final_answer_audit_passed": bool((audited.get("final_answer_audit") or {}).get("passed", False)),
                "semantic_fit_passed": bool(semantic.get("passed", False)),
            }
            if not audit_summary["final_answer_audit_passed"]:
                issues.append("final_answer_audit_failed")
            if not audit_summary["semantic_fit_passed"]:
                issues.append("semantic_fit_failed")
        except Exception as exc:  # Diagnostic failure must not alter the preview contract.
            audit_summary = {"diagnostic_error": type(exc).__name__}
            issues.append("safety_diagnostic_error")
    return sanitize_obj({"passed": not issues, "issues": sorted(set(issues)), "audit_summary": audit_summary})


def build_supervisor_partial_answer_preview(
    minimal_context: dict[str, Any],
    *,
    provider_status: str = "not_qualified",
) -> dict[str, Any]:
    """Render only admitted claim outcomes for supervisor review.

    The renderer deliberately accepts the bounded Minimal Decision Context, not
    a response, pack, trace, or benchmark definition. It is deterministic so an
    unqualified strict provider cannot suppress an independently supported
    clause or turn a pending clause into a fact.
    """
    context = minimal_context if isinstance(minimal_context, dict) else {}
    facts_by_uid = _preview_fact_index(context)
    resolutions = sorted(
        (item for item in context.get("claim_resolutions") or [] if isinstance(item, dict)),
        key=lambda item: sanitize_text(item.get("claim_uid")) or sanitize_text(item.get("claim_type")),
    )
    confirmed: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    conflicting: list[dict[str, Any]] = []
    evidence_uids: list[str] = []
    for resolution in resolutions:
        claim_type = sanitize_text(resolution.get("claim_type"))
        status = sanitize_text(resolution.get("status"))
        claim_uid = sanitize_text(resolution.get("claim_uid"))
        if status == "supported":
            uids = [uid for uid in resolution.get("evidence_uids") or [] if uid in facts_by_uid]
            clause = _preview_clause_text([facts_by_uid[uid] for uid in uids])
            if not clause:
                pending.append({
                    "claim_uid": claim_uid,
                    "claim_type": claim_type,
                    "reason": "admitted_fact_not_customer_renderable",
                    "customer_facing_clause": _preview_pending_text(claim_type, "unresolved"),
                })
                continue
            confirmed.append({
                "claim_uid": claim_uid,
                "claim_type": claim_type,
                "evidence_uids": uids,
                "customer_facing_clause": clause,
            })
            evidence_uids.extend(uids)
        elif status == "conflicting":
            conflicting.append({
                "claim_uid": claim_uid,
                "claim_type": claim_type,
                "reason": sanitize_text(resolution.get("reason")),
                "evidence_uids": list(resolution.get("conflicting_evidence_uids") or []),
                "customer_facing_clause": _preview_pending_text(claim_type, status),
            })
        else:
            pending.append({
                "claim_uid": claim_uid,
                "claim_type": claim_type,
                "reason": sanitize_text(resolution.get("reason")),
                "customer_facing_clause": _preview_pending_text(claim_type, status),
            })

    clauses = [item["customer_facing_clause"] for item in confirmed]
    clauses.extend(item["customer_facing_clause"] for item in pending)
    clauses.extend(item["customer_facing_clause"] for item in conflicting)
    if clauses:
        candidate_text = "亲，" + " ".join(clauses)
    else:
        requested = context.get("requested_claims") or []
        fallback_type = sanitize_text((requested[0] if requested else {}).get("claim_type"))
        candidate_text = customer_facing_safe_handoff_reply(fallback_type, inputs={}) if fallback_type else "亲，我先帮您核对一下当前商品资料，确认后给您回复。"

    preview = {
        "preview_version": "supervisor-partial-answer-preview-v2",
        "render_mode": "deterministic",
        "provider_status": provider_status or "not_qualified",
        "customer_goal": sanitize_text(context.get("customer_goal")),
        "claim_resolutions": resolutions,
        "confirmed_clauses": confirmed,
        "pending_clauses": pending,
        "conflicting_clauses": conflicting,
        "candidate_text": candidate_text,
        # Kept for the existing supervisor response shape while consumers move
        # to the explicit candidate_text field.
        "candidate_reply": candidate_text,
        "evidence_uids": sorted(set(evidence_uids)),
        "requires_human_review": True,
        "can_send": False,
        "used_for_final_reply": False,
        "context_metrics": dict(context.get("context_stats") or {}),
    }
    preview["safety_validation"] = _preview_safety_validation(preview, minimal_context=context)
    return sanitize_obj(preview)


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
        minimal_context = build_minimal_decision_context(
            admitted,
            customer_message=message,
            conversation_summary=response.get("conversation_context_summary") if isinstance(response.get("conversation_context_summary"), dict) else {},
            channel_capabilities=context.get("channel_capabilities") if isinstance(context.get("channel_capabilities"), dict) else {},
            allowed_read_only_tools=[
                sanitize_text(item)
                for item in tool_execution.get("executed_tool_names") or []
                if sanitize_text(item)
            ],
        )
        proposal_payload = {
            "minimal_decision_context": minimal_context,
            "tool_plan": tool_plan,
            "shadow_tool_execution": tool_execution,
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
        violations.extend(_partial_answer_contract_violations(
            proposal,
            admitted.get("claim_resolutions") or [],
        ))
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
        minimal_context = build_minimal_decision_context(
            admitted,
            customer_message=customer_message,
            conversation_summary=original.get("conversation_context_summary") if isinstance(original.get("conversation_context_summary"), dict) else {},
            channel_capabilities=(copilot_context or {}).get("channel_capabilities") if isinstance(copilot_context, dict) else {},
            allowed_read_only_tools=list((admitted.get("shadow_tool_execution") or {}).get("executed_tool_names") or []),
        )
        response["evidence_debug"]["supervisor_candidate_preview"] = build_supervisor_partial_answer_preview(
            minimal_context,
            provider_status=("not_qualified" if proposal.get("shadow_status") != "completed" else "qualified_deterministic_guard"),
        )
        response.setdefault("answer_trace", {})["llm_decision_shadow"] = {
            "schema_version": "agent-decision-proposal-v1",
            "shadow_only": True,
            "used_for_final_reply": False,
            "can_change_can_send": False,
            "status": proposal.get("shadow_status"),
            "formal_reply": sanitize_text(original.get("suggested_reply")),
            "shadow_proposal_reply": sanitize_text((proposal.get("reply_plan") or {}).get("proposed_reply")),
            "supervisor_candidate_preview": response["evidence_debug"]["supervisor_candidate_preview"],
            "admitted_fact_uids": [item.get("evidence_uid") for item in admitted.get("direct_product_facts") or []],
            "claim_resolutions": proposal.get("claim_resolutions") or [],
            "confirmed_clauses": proposal.get("confirmed_clauses") or [],
            "pending_clauses": proposal.get("pending_clauses") or [],
            "unresolved_claims": admitted.get("unresolved_claims") or [],
            "unsupported_claims": (proposal.get("evidence_selection") or {}).get("unsupported_claims") or [],
            "formal_can_send": bool(original.get("can_send")),
            "tool_execution": admitted.get("shadow_tool_execution") or {},
        }
        return response
