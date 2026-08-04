"""Final customer-facing semantic fit check.

This service runs after the reply has been polished. It does not route tools,
retrieve data, or create new facts. It only judges the final text against:

- the customer's current question;
- the semantic query/fact type already produced by upstream nodes;
- the product context evidence selected for this turn;
- the media blocks that will be sent with the reply.

The primary path is an LLM judge because "does this answer the question?" is a
semantic task. The deterministic path only enforces structural guarantees and
does not try to classify Chinese customer intent from raw keywords.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from app import config
from app.services.customer_facing_safe_handoff_service import customer_facing_safe_handoff_reply
from app.services.model_first_answer_composer_service import (
    COMPOSER_ENVELOPE_CONTRACT_VERSION,
    ModelFirstAnswerComposerService,
)
from app.services.no_evidence_reply_policy_service import apply_no_evidence_reply_policy
from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
)


_LLM_SEMANTIC_ISSUE_CODES = {
    "accessory_availability_answered_with_installation",
    "advice_scope_exceeded",
    "answered_space_fit_as_load_capacity",
    "gross_weight_answered_with_dimensions_or_capacity",
    "gross_weight_answered_with_load_capacity",
    "historical_agent_fact_used",
    "inference_scope_exceeded",
    "installation_answered_with_unrelated_product_fact",
    "internal_language_exposure",
    "known_context_re_requested",
    "missing_evidence_without_human_review",
    "omitted_customer_goal",
    "query_reply_mismatch",
    "repeated_generic_reply",
    "restricted_boundary_violation",
    "semantic_mismatch",
    "structure_function_answered_with_scene_or_space",
    "unnecessary_handoff",
    "unresolved_claim_asserted",
    "unsupported_claim",
    "unsupported_media_claim",
    "unsupported_product_claim",
    "unsupported_service_action_completion",
    "variability_factor_asserted_as_fact",
    "variability_factor_scope_exceeded",
}
_FINDING_ONTOLOGY_VERSION = "unified-textual-finding-ontology-v1"
_FINDING_OWNERSHIP = {
    "accessory_availability_answered_with_installation": {
        "canonical_family": "relevance",
        "specificity": 90,
        "role": "root",
    },
    "advice_scope_exceeded": {
        "canonical_family": "policy_semantic_budget",
        "specificity": 100,
        "role": "root",
    },
    "answered_space_fit_as_load_capacity": {
        "canonical_family": "relevance",
        "specificity": 90,
        "role": "root",
    },
    "gross_weight_answered_with_dimensions_or_capacity": {
        "canonical_family": "relevance",
        "specificity": 90,
        "role": "root",
    },
    "gross_weight_answered_with_load_capacity": {
        "canonical_family": "relevance",
        "specificity": 90,
        "role": "root",
    },
    "historical_agent_fact_used": {
        "canonical_family": "conversation_continuity",
        "specificity": 90,
        "role": "root",
    },
    "inference_scope_exceeded": {
        "canonical_family": "factual_fidelity",
        "specificity": 95,
        "role": "root",
    },
    "installation_answered_with_unrelated_product_fact": {
        "canonical_family": "relevance",
        "specificity": 90,
        "role": "root",
    },
    "internal_language_exposure": {
        "canonical_family": "communication_quality",
        "specificity": 90,
        "role": "root",
    },
    "known_context_re_requested": {
        "canonical_family": "conversation_continuity",
        "specificity": 90,
        "role": "root",
    },
    "missing_evidence_without_human_review": {
        "canonical_family": "factual_fidelity",
        "specificity": 95,
        "role": "root",
    },
    "omitted_customer_goal": {
        "canonical_family": "goal_coverage",
        "specificity": 95,
        "role": "root",
    },
    "query_reply_mismatch": {
        "canonical_family": "relevance",
        "specificity": 80,
        "role": "root",
    },
    "repeated_generic_reply": {
        "canonical_family": "communication_quality",
        "specificity": 80,
        "role": "root",
    },
    "restricted_boundary_violation": {
        "canonical_family": "unresolved_boundary",
        "specificity": 100,
        "role": "root",
    },
    "semantic_mismatch": {
        "canonical_family": "relevance",
        "specificity": 10,
        "role": "generic_symptom",
    },
    "structure_function_answered_with_scene_or_space": {
        "canonical_family": "relevance",
        "specificity": 90,
        "role": "root",
    },
    "unnecessary_handoff": {
        "canonical_family": "relevance",
        "specificity": 80,
        "role": "root",
    },
    "unresolved_claim_asserted": {
        "canonical_family": "unresolved_boundary",
        "specificity": 100,
        "role": "root",
    },
    "unsupported_claim": {
        "canonical_family": "factual_fidelity",
        "canonical_root_code": "unsupported_claim",
        "canonical_subtype": "generic",
        "specificity": 100,
        "role": "root",
    },
    "unsupported_media_claim": {
        "canonical_family": "unsupported_completion",
        "specificity": 100,
        "role": "root",
    },
    "unsupported_product_claim": {
        "canonical_family": "factual_fidelity",
        "canonical_root_code": "unsupported_claim",
        "canonical_subtype": "product_claim",
        "specificity": 100,
        "role": "root",
    },
    "unsupported_service_action_completion": {
        "canonical_family": "unsupported_completion",
        "specificity": 100,
        "role": "root",
    },
    "variability_factor_asserted_as_fact": {
        "canonical_family": "policy_semantic_budget",
        "specificity": 100,
        "role": "root",
    },
    "variability_factor_scope_exceeded": {
        "canonical_family": "policy_semantic_budget",
        "specificity": 100,
        "role": "root",
    },
}
_FINDING_SECONDARY_OVERLAPS = {
    "unsupported_claim": {"semantic_mismatch"},
}
_FINDING_CONFLICTS = {
    frozenset({
        "missing_evidence_without_human_review",
        "unnecessary_handoff",
    }),
}
_SEMANTIC_BUDGET_FINDING_CODES = {
    "advice_scope_exceeded",
    "inference_scope_exceeded",
    "restricted_boundary_violation",
    "variability_factor_asserted_as_fact",
    "variability_factor_scope_exceeded",
}
_NON_BUDGET_FINDING_CODES = (
    _LLM_SEMANTIC_ISSUE_CODES - _SEMANTIC_BUDGET_FINDING_CODES
)
_ATOMIC_SEMANTIC_SCHEMA_VERSION = "unified-textual-audit-v2"
_ATOMIC_SEMANTIC_OUTPUT_FIELDS = {
    "schema_version",
    "goal_reviews",
    "semantic_budget_checks",
    "global_finding_codes",
}
_ATOMIC_SEGMENT_FIELDS = {
    "goal_ref",
    "clause_ref",
    "clause_kind",
    "textual_status",
    "finding_codes",
}
_ATOMIC_SEMANTIC_BUDGET_CHECK_FIELDS = {
    "goal_ref",
    "clause_ref",
    "advice_status",
    "variability_factor_status",
    "restricted_boundary_status",
    "conclusion_status",
}
_ATOMIC_ADVICE_STATUSES = {
    "absent",
    "authorized",
    "unauthorized",
    "indeterminate",
}
_ATOMIC_VARIABILITY_FACTOR_STATUSES = {
    "none",
    "within_budget",
    "outside_budget",
    "asserted_as_fact",
    "indeterminate",
}
_ATOMIC_RESTRICTED_BOUNDARY_STATUSES = {
    "preserved",
    "violated",
    "not_applicable",
    "indeterminate",
}
_ATOMIC_CONCLUSION_STATUSES = {
    "within_budget",
    "outside_budget",
    "indeterminate",
}
_ATOMIC_EXPECTED_KINDS = {
    "supported_fact",
    "unresolved",
    "allowed_inference",
}


def _atomic_semantic_json_schema(
    atomic_contract: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the provider schema; local validation remains authoritative."""
    goal_refs = sorted({item["goal_ref"] for item in atomic_contract})
    clause_refs = sorted({item["clause_ref"] for item in atomic_contract})
    budget_targets = [
        item
        for item in atomic_contract
        if item.get("semantic_budget_applicable") is True
    ]
    budget_goal_refs = sorted({
        item["goal_ref"] for item in budget_targets
    }) or goal_refs
    budget_clause_refs = sorted({
        item["clause_ref"] for item in budget_targets
    }) or clause_refs
    finding_codes = sorted(_NON_BUDGET_FINDING_CODES)
    goal_review = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_ATOMIC_SEGMENT_FIELDS),
        "properties": {
            "goal_ref": {"type": "string", "enum": goal_refs},
            "clause_ref": {"type": "string", "enum": clause_refs},
            "clause_kind": {
                "type": "string",
                "enum": sorted(_ATOMIC_EXPECTED_KINDS),
            },
            "textual_status": {
                "type": "string",
                "enum": ["accepted", "rejected"],
            },
            "finding_codes": {
                "type": "array",
                "items": {"type": "string", "enum": finding_codes},
                "uniqueItems": True,
            },
        },
    }
    budget_check = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_ATOMIC_SEMANTIC_BUDGET_CHECK_FIELDS),
        "properties": {
            "goal_ref": {
                "type": "string",
                "enum": budget_goal_refs,
            },
            "clause_ref": {
                "type": "string",
                "enum": budget_clause_refs,
            },
            "advice_status": {
                "type": "string",
                "enum": sorted(_ATOMIC_ADVICE_STATUSES),
            },
            "variability_factor_status": {
                "type": "string",
                "enum": sorted(_ATOMIC_VARIABILITY_FACTOR_STATUSES),
            },
            "restricted_boundary_status": {
                "type": "string",
                "enum": sorted(_ATOMIC_RESTRICTED_BOUNDARY_STATUSES),
            },
            "conclusion_status": {
                "type": "string",
                "enum": sorted(_ATOMIC_CONCLUSION_STATUSES),
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_ATOMIC_SEMANTIC_OUTPUT_FIELDS),
        "properties": {
            "schema_version": {
                "type": "string",
                "const": _ATOMIC_SEMANTIC_SCHEMA_VERSION,
            },
            "goal_reviews": {
                "type": "array",
                "items": goal_review,
                "minItems": len(atomic_contract),
                "maxItems": len(atomic_contract),
            },
            "semantic_budget_checks": {
                "type": "array",
                "items": budget_check,
                "minItems": len(budget_targets),
                "maxItems": len(budget_targets),
            },
            "global_finding_codes": {
                "type": "array",
                "items": {"type": "string", "enum": finding_codes},
                "uniqueItems": True,
            },
        },
    }


def audit_customer_reply_semantic_fit(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reply = str(response.get("suggested_reply") or "").strip()
    if not reply:
        return _result(False, ["empty_reply"], "Final reply is empty.", "deterministic")

    if _is_model_first_candidate(response):
        result = _llm_semantic_fit_check(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context or {},
        )
        return result or _semantic_judge_failure("semantic_judge_unavailable")

    structural = _structural_semantic_checks(response)
    if structural["issues"]:
        return _result(False, structural["issues"], structural["reason"], "deterministic")

    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)

    # Visual/installation questions can be answered by attached media assets.
    # Accept the reply deterministically when it references the attached asset.
    if _is_visual_media_answer(response):
        return _result(
            True,
            [],
            "Visual/installation question answered with an attached image/video asset.",
            "deterministic",
        )

    if _no_evidence_controlled_reply_acceptable(response):
        return _result(
            True,
            [],
            "Controlled no-evidence handoff reply accepted deterministically.",
            "deterministic",
        )

    # Generic-rule fallbacks are intentionally conservative policy replies.
    # When a matching generic rule exists and the reply avoids forbidden claims,
    # accept it without calling the LLM judge.
    if _generic_rule_fallback_acceptable(response, evidence_pack, query_fact_type):
        return _result(
            True,
            [],
            "Generic rule fallback reply accepted deterministically.",
            "deterministic",
        )

    llm_result = _llm_semantic_fit_check(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context or {},
    )
    if llm_result:
        return llm_result

    return _result(True, [], "No structural semantic issue detected.", "deterministic")


def apply_semantic_fit_result(
    response: dict[str, Any],
    result: dict[str, Any],
    *,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response["final_semantic_fit_audit"] = result
    response.setdefault("evidence_debug", {})["final_semantic_fit_audit"] = result
    if result.get("passed", True):
        return response

    if _is_model_first_candidate(response):
        response["requires_human_review"] = True
        response["can_send"] = False
        response["sendable_reply"] = ""
        response["reply_status"] = "needs_human_review"
        response["reason_for_review"] = _append_reason(
            str(response.get("reason_for_review") or ""),
            "model_first_unified_textual_audit_failed",
        )
        return response

    original = str(response.get("suggested_reply") or "")
    response["suggested_reply"] = _semantic_fit_fallback(response)
    response["requires_human_review"] = True
    if _is_model_first_candidate(response):
        response["can_send"] = False
        response["sendable_reply"] = ""
        response["reply_status"] = "needs_human_review"
    response["generation_mode"] = "final_semantic_fit_fallback"
    response["reason_for_review"] = _append_reason(
        str(response.get("reason_for_review") or ""),
        "最终回复语义一致性未通过",
    )
    response.setdefault("guard_warnings", []).append(
        "final_semantic_fit_audit: " + ",".join(result.get("issues") or [])
    )
    response.setdefault("trace_steps", []).append({
        "node": "final_semantic_fit_audit",
        "status": "blocked",
        "issues": result.get("issues", []),
        "summary": result.get("reason", "final semantic fit failed"),
    })
    result["fallback_used"] = True
    result["original_reply"] = original
    response = apply_no_evidence_reply_policy(response, copilot_context)
    return response


def _structural_semantic_checks(response: dict[str, Any]) -> dict[str, Any]:
    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)
    try:
        from app.services.no_evidence_reply_policy_service import media_delivery_claim_issues

        media_issues = media_delivery_claim_issues(response)
        if media_issues:
            return {
                "issues": ["unsupported_media_claim"],
                "reason": "Customer-facing media wording does not match the attached reply blocks.",
            }
    except Exception:
        return {
            "issues": ["media_delivery_contract_check_failed"],
            "reason": "Media delivery contract could not be validated.",
        }
    if not query_fact_type:
        return {"issues": [], "reason": ""}

    product_fact_issues = _strict_product_fact_boundary_issues(response, query_fact_type)
    if product_fact_issues:
        return {
            "issues": product_fact_issues,
            "reason": "Final reply answers a different product fact type than the customer asked.",
        }

    answerability = str(evidence_pack.get("answerability") or "")
    if answerability in {"missing_product_fact", "no_product_profile", "no_product_identity"}:
        # If upstream already determined the reply is relevant and on-topic,
        # do not let a stale "missing product fact" pack force a fallback.
        debug = response.get("evidence_debug") or {}
        if bool(debug.get("answer_relevance_passed")) or bool(debug.get("direct_answer_supported")):
            return {"issues": [], "reason": ""}
        if not bool(response.get("requires_human_review")):
            return {
                "issues": ["missing_evidence_without_human_review"],
                "reason": "Required product fact is missing but reply is not marked for human review.",
            }

    matched_facts = evidence_pack.get("matched_facts") or []
    if answerability == "direct_answer" and not matched_facts:
        # A direct-answer pack may have been promoted from a generic-rule or
        # template-supported reply. Accept it when such supporting evidence is
        # present and matches the query fact type.
        if _generic_or_template_supports_fact_type(response, evidence_pack, query_fact_type):
            return {"issues": [], "reason": ""}
        return {
            "issues": ["direct_answer_without_matched_fact"],
            "reason": "Evidence pack claims direct answer but no matched fact is attached.",
        }

    for fact in matched_facts:
        alignment = fact.get("semantic_alignment") or {}
        if alignment and alignment.get("direct_answer_allowed") is False:
            return {
                "issues": ["selected_fact_not_direct_answer_allowed"],
                "reason": "A selected fact is marked as non-direct-answer evidence.",
            }

    return {"issues": [], "reason": ""}


def _strict_product_fact_boundary_issues(response: dict[str, Any], query_fact_type: str) -> list[str]:
    reply = str(response.get("suggested_reply") or "")
    issues: list[str] = []
    if query_fact_type == "gross_weight":
        weight_terms = ("\u6bdb\u91cd", "\u5305\u88c5\u91cd\u91cf", "\u5546\u54c1\u91cd\u91cf", "\u91cd\u91cf", "\u6838\u5bf9")
        load_terms = ("\u627f\u91cd", "\u8f7d\u91cd", "\u5bb9\u91cf")
        dimension_terms = ("\u5bbd", "\u6df1", "\u9ad8", "\u5c3a\u5bf8", "\u9884\u7559", "\u7a7a\u95f4", "\u653e\u5f97\u4e0b", "\u653e\u7684\u4e0b")
        has_weight_context = any(term in reply for term in weight_terms)
        if any(term in reply for term in load_terms) and not has_weight_context:
            issues.append("gross_weight_answered_with_load_capacity")
        if any(term in reply for term in dimension_terms) and not has_weight_context:
            issues.append("gross_weight_answered_with_dimensions_or_capacity")
    if query_fact_type == "accessory_availability":
        availability_terms = (
            "\u6709\u5356",
            "\u552e\u5356",
            "\u5355\u72ec\u4e70",
            "\u5355\u72ec\u8d2d\u4e70",
            "\u8865\u4e70",
            "\u8865\u8d2d",
            "\u53ef\u552e",
            "\u80fd\u4e70",
            "\u6838\u5bf9",
        )
        installation_terms = ("\u5b89\u88c5\u8d44\u6599", "\u8bf4\u660e\u4e66", "\u600e\u4e48\u88c5", "\u5b89\u88c5\u89c6\u9891", "\u5b89\u88c5\u8bf4\u660e")
        if any(term in reply for term in installation_terms) and not any(term in reply for term in availability_terms):
            issues.append("accessory_availability_answered_with_installation")
    if query_fact_type == "installation":
        installation_terms = (
            "\u5b89\u88c5",
            "\u7ec4\u88c5",
            "\u6559\u7a0b",
            "\u8bf4\u660e\u4e66",
            "\u56fe\u7eb8",
            "\u89c6\u9891",
            "\u6b65\u9aa4",
            "\u5b54\u4f4d",
            "\u87ba\u4e1d",
            "\u914d\u4ef6",
            "\u5361\u4f4f",
            "\u62cd\u7167",
            "\u6838\u5bf9",
            "\u4eba\u5de5",
        )
        wrong_product_fact_terms = (
            "\u5c3a\u5bf8",
            "\u5bbd",
            "\u6df1",
            "\u9ad8",
            "\u9884\u7559",
            "\u7a7a\u95f4",
            "\u6750\u8d28",
            "\u6750\u6599",
            "\u627f\u91cd",
            "\u8f7d\u91cd",
            "\u6bdb\u91cd",
            "\u91cd\u91cf",
            "\u9002\u7528\u5e74\u9f84",
            "\u5e74\u9f84",
        )
        has_installation_context = any(term in reply for term in installation_terms)
        if any(term in reply for term in wrong_product_fact_terms) and not has_installation_context:
            issues.append("installation_answered_with_unrelated_product_fact")
    if query_fact_type == "structure_function":
        structure_terms = (
            "结构",
            "孔位",
            "结构件",
            "配件规格",
            "侧板",
            "护栏",
            "围栏",
            "挡板",
            "板子",
            "补配",
            "加装",
            "适配",
            "翻下",
            "翻起",
            "打开",
            "收起",
            "折叠",
            "调节",
            "核对",
            "确认",
        )
        scene_or_space_terms = ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "预留位置", "走动空间", "宽度", "进深", "高度", "空间小")
        has_structure_context = any(term in reply for term in structure_terms)
        if any(term in reply for term in scene_or_space_terms) and not has_structure_context:
            issues.append("structure_function_answered_with_scene_or_space")
    if query_fact_type in {"aftersales", "aftersales_policy", "after_sales"}:
        aftersales_terms = ("售后", "补发", "换件", "换货", "破损", "断裂", "裂了", "损坏", "核实", "订单")
        wrong_fact_terms = ("安装步骤", "怎么装", "尺寸", "材质", "卧室", "客厅", "预留位置")
        has_aftersales_context = any(term in reply for term in aftersales_terms)
        if any(term in reply for term in wrong_fact_terms) and not has_aftersales_context:
            issues.append("aftersales_answered_with_product_fact")
    return issues


def _llm_semantic_fit_check(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not config.COPILOT_FINAL_AUDIT_LLM_ENABLED:
        return None
    model_first_candidate = _is_model_first_candidate(response)
    if (
        model_first_candidate
        and config.COPILOT_UNIFIED_AUDIT_STRICT_ENABLED
    ):
        return _strict_model_first_semantic_fit_check(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        if not client.api_key:
            if model_first_candidate:
                return _semantic_judge_failure("semantic_judge_unavailable")
            return None

        payload = _semantic_payload(response, customer_message, copilot_context)
        atomic_contract = (
            _atomic_semantic_contract(response)
            if model_first_candidate
            else []
        )
        if model_first_candidate:
            if not atomic_contract:
                return _semantic_judge_failure("semantic_judge_schema_invalid")
            payload["unified_textual_contract"] = atomic_contract
        started_at = time.perf_counter()
        completion_kwargs = {
            "model": client.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        _atomic_semantic_system_prompt()
                        if model_first_candidate
                        else
                        "You are the final semantic quality judge for a customer-service agent. "
                        "Judge only whether final_reply can be sent as a coherent answer to customer_message. "
                        "Use semantic_query and admitted_direct_facts as the only factual ground truth. "
                        "Treat unresolved_claims as facts the reply must not assert. "
                        "When model_first_candidate_contract.enabled is true, review_only is a delivery boundary, "
                        "not a requirement to add handoff wording. A resolved product identity lets phrases such as "
                        "'this product' anchor the answer; do not require the full product title to be repeated. "
                        "The listed allowed_low_risk_reasoning may be used only as a qualified explanation and must "
                        "not become a durability, safety, load, certification, suitability, order, refund, or media promise. "
                        "Do not require exact wording. Do not judge style unless it affects answerability. "
                        "Fail if the reply answers a different fact type, asks for information already provided, "
                        "turns to human review while direct evidence is available, or claims facts not supported by evidence. "
                        "Pass if the reply gives a safe handoff because evidence is missing or risk requires review. "
                        "Return exactly three JSON fields: passed, issues, reason. "
                        f"issues may contain only these codes: {sorted(_LLM_SEMANTIC_ISSUE_CODES)}. "
                        "If passed=true, issues must be empty. If passed=false, issues must contain at least one code. "
                        "reason must be one short sentence under 500 characters. "
                        "Do not include analysis, self-correction, alternatives, markdown, or prose inside issues."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": 800 if model_first_candidate else 120,
            "response_format": {"type": "json_object"},
        }
        if model_first_candidate:
            completion_kwargs["_single_attempt_no_repair"] = True
        result = client.create_chat_completion(
            **completion_kwargs,
        )
        provider_latency_ms = int((time.perf_counter() - started_at) * 1000)
        choice = result.choices[0]
        raw = choice.message.content
        raw_text = str(raw or "")
        provider_diagnostics = _semantic_provider_diagnostics(
            raw_text,
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
            latency_ms=provider_latency_ms,
        )
        if model_first_candidate:
            if str(getattr(choice, "finish_reason", "") or "") == "length":
                return _semantic_judge_failure(
                    "semantic_judge_schema_invalid",
                    provider_diagnostics=provider_diagnostics,
                    validation_diagnostics=_semantic_validation_diagnostics(
                        "truncated_response",
                        json_path="$",
                        expected_type="complete_json_object",
                        actual_type="truncated",
                    ),
                )
            (
                bounded_json,
                response_envelope,
                envelope_unwrap_count,
                envelope_issue,
            ) = ModelFirstAnswerComposerService._unwrap_json_envelope(raw_text)
            provider_diagnostics.update({
                "response_envelope": response_envelope,
                "envelope_unwrap_count": envelope_unwrap_count,
            })
            if envelope_issue:
                return _semantic_judge_failure(
                    "semantic_judge_schema_invalid",
                    provider_diagnostics=provider_diagnostics,
                    validation_diagnostics=_semantic_validation_diagnostics(
                        envelope_issue,
                        json_path="$",
                        expected_type="raw_json_or_single_json_fence",
                        actual_type=response_envelope,
                    ),
                )
        else:
            bounded_json = raw_text
        try:
            parsed = json.loads(bounded_json)
        except (TypeError, json.JSONDecodeError):
            if model_first_candidate:
                return _semantic_judge_failure(
                    "semantic_judge_schema_invalid",
                    provider_diagnostics=provider_diagnostics,
                    validation_diagnostics=_semantic_validation_diagnostics(
                        "json_decode_error",
                        json_path="$",
                        expected_type="json_object",
                        actual_type="invalid_json",
                    ),
                )
            return _result(
                True,
                [],
                "LLM semantic fit unavailable: schema_invalid",
                "deterministic",
            )
        if model_first_candidate:
            atomic_result, validation_diagnostics = _atomic_semantic_result_with_diagnostics(
                parsed,
                atomic_contract=atomic_contract,
            )
            if atomic_result is None:
                failure = _semantic_judge_failure(
                    "semantic_judge_schema_invalid",
                    provider_diagnostics=provider_diagnostics,
                    validation_diagnostics=validation_diagnostics,
                )
                safe_raw_checks = (
                    _safe_raw_semantic_budget_checks(
                        parsed.get("semantic_budget_checks"),
                        atomic_contract=atomic_contract,
                    )
                    if isinstance(parsed, dict)
                    else None
                )
                if safe_raw_checks is not None:
                    failure["raw_semantic_budget_checks"] = (
                        safe_raw_checks
                    )
                return failure
            atomic_result["provider_diagnostics"] = provider_diagnostics
            atomic_result["validation_diagnostics"] = validation_diagnostics
            return atomic_result

        validation_issue = _validate_llm_semantic_result(parsed)
        if validation_issue:
            if model_first_candidate:
                return _semantic_judge_failure("semantic_judge_schema_invalid")
            return _result(
                True,
                [],
                "LLM semantic fit unavailable: schema_invalid",
                "deterministic",
            )
        return _result(
            parsed["passed"],
            list(parsed["issues"]),
            parsed["reason"],
            "llm_semantic_fit",
        )
    except Exception as exc:
        if model_first_candidate:
            return _semantic_judge_failure(
                "semantic_judge_unavailable",
                provider_diagnostics=_semantic_provider_failure_diagnostics(exc),
                validation_diagnostics=_semantic_validation_diagnostics(
                    "provider_error",
                    json_path="$",
                    expected_type="strict_semantic_response",
                    actual_type=type(exc).__name__,
                ),
            )
        return _result(True, [], f"LLM semantic fit unavailable: {type(exc).__name__}", "deterministic")


def _strict_model_first_semantic_fit_check(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any]:
    atomic_contract = _atomic_semantic_contract(response)
    if not atomic_contract:
        return _semantic_judge_failure(
            "semantic_judge_schema_invalid",
            validation_diagnostics=_semantic_validation_diagnostics(
                "atomic_contract_missing",
                json_path="$.unified_textual_contract",
                expected_type="non_empty_atomic_contract",
                actual_type="empty",
            ),
        )

    payload = _semantic_payload(
        response,
        customer_message,
        copilot_context,
    )
    payload["unified_textual_contract"] = atomic_contract
    provider = StrictDecisionProviderService(
        config=StrictDecisionProviderConfig.from_unified_audit_environment()
    )
    try:
        parsed = provider.request(
            name="unified_textual_audit_v2",
            schema=_atomic_semantic_json_schema(atomic_contract),
            system_prompt=_atomic_semantic_system_prompt(),
            payload=payload,
            max_tokens=800,
            allow_unqualified=False,
        )
    except StrictDecisionProviderError as exc:
        category = str(exc) or "provider_request_failed"
        model_call_count = (
            0
            if category in {
                "provider_not_configured",
                "provider_not_qualified",
                "strict_capability_not_supported",
            }
            else 1
        )
        return _semantic_judge_failure(
            "semantic_judge_unavailable",
            provider_diagnostics=_strict_semantic_provider_diagnostics(
                provider,
                error_type=category,
                model_call_count=model_call_count,
            ),
            validation_diagnostics=_semantic_validation_diagnostics(
                "strict_provider_error",
                json_path="$",
                expected_type="strict_semantic_response",
                actual_type=category,
            ),
        )
    except Exception as exc:
        return _semantic_judge_failure(
            "semantic_judge_unavailable",
            provider_diagnostics=_strict_semantic_provider_diagnostics(
                provider,
                error_type=type(exc).__name__,
                model_call_count=1,
            ),
            validation_diagnostics=_semantic_validation_diagnostics(
                "strict_provider_error",
                json_path="$",
                expected_type="strict_semantic_response",
                actual_type=type(exc).__name__,
            ),
        )

    provider_diagnostics = _strict_semantic_provider_diagnostics(
        provider,
        parsed=parsed,
        model_call_count=1,
    )
    atomic_result, validation_diagnostics = (
        _atomic_semantic_result_with_diagnostics(
            parsed,
            atomic_contract=atomic_contract,
        )
    )
    if atomic_result is None:
        failure = _semantic_judge_failure(
            "semantic_judge_schema_invalid",
            provider_diagnostics=provider_diagnostics,
            validation_diagnostics=validation_diagnostics,
        )
        safe_raw_checks = _safe_raw_semantic_budget_checks(
            parsed.get("semantic_budget_checks"),
            atomic_contract=atomic_contract,
        )
        if safe_raw_checks is not None:
            failure["raw_semantic_budget_checks"] = safe_raw_checks
        return failure

    atomic_result["provider_diagnostics"] = provider_diagnostics
    atomic_result["validation_diagnostics"] = validation_diagnostics
    return atomic_result


def _atomic_semantic_system_prompt() -> str:
    return (
        "You are the sole textual fidelity auditor for a model-first customer-service candidate. "
        "The deterministic final contract has already validated references, clause kinds, media blocks, "
        "structured action completion, high-risk gates, and delivery boundaries. Do not relabel that "
        "structured truth. Evaluate each unified_textual_contract item once against final_reply, its "
        "cited anonymous evidence, canonical resolution, and continuity-only conversation context. "
        "History can show what the customer already supplied, but historical agent text never proves a "
        "fact or completed action. A supported_fact clause must stay within cited evidence. An unresolved "
        "clause that directly says the requested proposition cannot be confirmed or guaranteed answers "
        "the goal without asserting the fact. For every unified_textual_contract item whose "
        "semantic_budget_applicable is true, return exactly one semantic_budget_checks row in the same order. "
        "All six fields are required and no extra fields are allowed. Determine each dimension independently "
        "from clause_text and its supplied semantic budget. Natural paraphrases count by meaning, not literal "
        "word overlap. advice_status is absent when there is no customer-directed advice, authorized only when "
        "present advice is permitted by advice_mode, unauthorized when present advice exceeds advice_mode, and "
        "indeterminate only when you cannot decide. A refusal or concise restricted-boundary statement is not "
        "advice. variability_factor_status is none when no factor is used, within_budget when every used factor "
        "belongs to allowed_variability_factor_families and remains a possible variable, outside_budget when "
        "any used factor is outside that set, asserted_as_fact when a factor is stated as a verified product "
        "fact, material property, causal explanation, or guarantee, and indeterminate only when undecidable. "
        "An allowed factor may be mentioned as a possible source of variability; the allowed-factor list does "
        "not authorize presenting that factor or its effect as established truth. If allowed and unauthorized "
        "factors both appear, choose outside_budget. restricted_boundary_status is mechanically keyed by the "
        "supplied restricted_request_boundary: when that object is empty, return not_applicable regardless of "
        "caveats or refusal language in clause_text; when it is non-empty, return preserved or violated. Do not "
        "infer a restricted boundary from wording alone; use indeterminate only when an applicable boundary "
        "cannot be judged. "
        "conclusion_status is within_budget only when every conclusion stays within allowed_conclusion_family "
        "and required qualifiers, otherwise outside_budget; use indeterminate only when undecidable. "
        "trusted_domain_pack_ref and pack_content_sha256 identify the governing budget but are not evidence. "
        "Do not repeat policy, Pack, factor lists, findings, explanations, or candidate text in the check row. "
        "The server derives all semantic-budget findings from these required statuses. Therefore never emit "
        "semantic-budget finding codes in goal_reviews or global_finding_codes. Continue using goal_reviews and "
        "global_finding_codes only for the supplied non-budget finding codes: omitted goals, unrelated answers, "
        "unsupported inference outside the budget dimensions, use of "
        "history as truth, repeated requests for known information, unsupported service/media completion, "
        "internal language, and materially repetitive generic replies. "
        "Echo every goal_ref, clause_ref, and clause_kind exactly once. For each goal return textual_status "
        "accepted with an empty finding_codes list, or rejected with one or more allowed finding codes. "
        "Return strict JSON with exactly schema_version, goal_reviews, semantic_budget_checks, "
        "global_finding_codes. schema_version must be unified-textual-audit-v2. Each goal review must contain "
        "exactly goal_ref, "
        "clause_ref, clause_kind, textual_status, finding_codes. Use only codes supplied in "
        "allowed_finding_codes. Do not return passed, verdict, reason, conclusion, analysis, markdown, "
        "self-correction, or extra fields."
    )


def _atomic_policy_pack_identity_by_ref(
    response: dict[str, Any],
) -> dict[str, dict[str, str]]:
    minimal = response.get("minimal_decision_context")
    if not isinstance(minimal, dict):
        return {}
    projections: dict[str, dict[str, str]] = {}
    for resolution in minimal.get("claim_resolutions") or []:
        if not isinstance(resolution, dict):
            continue
        options = resolution.get("eligible_policy_options") or []
        if not isinstance(options, list):
            return {}
        for option in options:
            if not isinstance(option, dict):
                return {}
            policy_ref = str(option.get("policy_ref") or "").strip()
            if not policy_ref:
                return {}
            pack_ref = str(
                option.get("trusted_domain_pack_ref") or ""
            ).strip()
            pack_hash = str(
                option.get("pack_content_sha256") or ""
            ).strip().lower()
            if (
                not pack_ref
                or not re.fullmatch(r"[0-9a-f]{64}", pack_hash)
            ):
                return {}
            projection = {
                "trusted_domain_pack_ref": pack_ref,
                "pack_content_sha256": pack_hash,
            }
            if (
                policy_ref in projections
                and projections[policy_ref] != projection
            ):
                return {}
            projections[policy_ref] = projection
    return projections


def _atomic_semantic_contract(response: dict[str, Any]) -> list[dict[str, Any]]:
    from app.services.final_answer_auditor import _model_first_audit_context

    composer = response.get("model_first_answer_composer")
    if not isinstance(composer, dict) or composer.get("status") != "accepted":
        return []
    audit_context = _model_first_audit_context(response, {})
    truth = audit_context.get("canonical_truth")
    clauses = (
        truth.get("candidate_clauses")
        if isinstance(truth, dict)
        and isinstance(truth.get("candidate_clauses"), list)
        else []
    )
    if not clauses:
        return []
    pack_identity_by_policy_ref = _atomic_policy_pack_identity_by_ref(
        response
    )
    contract: list[dict[str, Any]] = []
    seen_goals: set[str] = set()
    seen_clauses: set[str] = set()
    for clause in clauses:
        if not isinstance(clause, dict):
            return []
        goal_ref = str(clause.get("goal_ref") or "").strip()
        clause_ref = str(clause.get("clause_ref") or "").strip()
        if (
            not goal_ref
            or not clause_ref
            or goal_ref in seen_goals
            or clause_ref in seen_clauses
        ):
            return []
        seen_goals.add(goal_ref)
        seen_clauses.add(clause_ref)
        clause_kind = str(clause.get("expected_kind") or "").strip()
        if clause_kind not in _ATOMIC_EXPECTED_KINDS:
            return []
        inference_policy_refs = sorted({
            str(item).strip()
            for item in clause.get("inference_policy_refs") or []
            if str(item).strip()
        })
        variability_factors = clause.get(
            "allowed_variability_factor_families"
        )
        if clause_kind == "allowed_inference" and (
            len(inference_policy_refs) != 1
            or inference_policy_refs[0] not in pack_identity_by_policy_ref
            or not str(
                clause.get("allowed_conclusion_family") or ""
            ).strip()
            or not isinstance(variability_factors, list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in variability_factors
            )
            or variability_factors
            != sorted(set(variability_factors))
            or clause.get("advice_mode") not in {
                "none",
                "concise_care_only",
                "safety_handoff_required",
            }
        ):
            return []
        contract.append({
            "goal_ref": goal_ref,
            "clause_ref": clause_ref,
            "clause_kind": clause_kind,
            "clause_text": str(clause.get("text") or "").strip(),
            "evidence_refs": list(clause.get("evidence_refs") or []),
            "premise_evidence_refs": list(
                clause.get("premise_evidence_refs") or []
            ),
            "inference_policy_refs": inference_policy_refs,
            "scope_qualifier": str(
                clause.get("scope_qualifier") or ""
            ).strip(),
            "inference_risk_level": str(
                clause.get("inference_risk_level") or ""
            ).strip(),
            "requested_claim_risk_level": str(
                clause.get("requested_claim_risk_level") or ""
            ).strip(),
            "maximum_risk_level": str(
                clause.get("maximum_risk_level") or ""
            ).strip(),
            "restricted_request_boundary": dict(
                clause.get("restricted_request_boundary") or {}
            ),
            "inference_review_only": (
                clause.get("inference_review_only") is True
            ),
            "allowed_conclusion_family": str(
                clause.get("allowed_conclusion_family") or ""
            ).strip(),
            "allowed_variability_factor_families": sorted({
                str(item).strip()
                for item in clause.get(
                    "allowed_variability_factor_families"
                )
                or []
                if str(item).strip()
            }),
            "advice_mode": str(
                clause.get("advice_mode") or ""
            ).strip(),
            "prohibited_extensions": sorted({
                str(item).strip()
                for item in clause.get("prohibited_extensions") or []
                if str(item).strip()
            }),
            "trusted_domain_pack_ref": (
                pack_identity_by_policy_ref[
                    inference_policy_refs[0]
                ]["trusted_domain_pack_ref"]
                if clause_kind == "allowed_inference"
                else ""
            ),
            "pack_content_sha256": (
                pack_identity_by_policy_ref[
                    inference_policy_refs[0]
                ]["pack_content_sha256"]
                if clause_kind == "allowed_inference"
                else ""
            ),
            "semantic_budget_applicable": (
                clause_kind == "allowed_inference"
            ),
            "allowed_finding_codes": sorted(
                _NON_BUDGET_FINDING_CODES
            ),
        })
    return contract


def _atomic_semantic_result(
    parsed: Any,
    *,
    atomic_contract: list[dict[str, Any]],
) -> dict[str, Any] | None:
    result, _ = _atomic_semantic_result_with_diagnostics(
        parsed,
        atomic_contract=atomic_contract,
    )
    return result


def finding_ownership_matrix() -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for code in sorted(_FINDING_OWNERSHIP):
        item = _FINDING_OWNERSHIP[code]
        matrix.append({
            "raw_finding_code": code,
            "canonical_family": item["canonical_family"],
            "canonical_root_code": item.get(
                "canonical_root_code",
                code,
            ),
            "canonical_subtype": item.get(
                "canonical_subtype",
                "",
            ),
            "specificity": item["specificity"],
            "blocking": True,
            "can_be_primary": True,
            "diagnostic_role": item["role"],
            "secondary_when_primary_codes": sorted(
                primary
                for primary, secondary_codes in _FINDING_SECONDARY_OVERLAPS.items()
                if code in secondary_codes
            ),
            "conflicts_with": sorted({
                other
                for pair in _FINDING_CONFLICTS
                if code in pair
                for other in pair
                if other != code
            }),
        })
    return matrix


def _canonicalize_finding_codes(
    raw_finding_codes: Any,
) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(raw_finding_codes, list):
        return None, "finding_codes_type_invalid"
    if any(
        not isinstance(item, str)
        or item not in _FINDING_OWNERSHIP
        for item in raw_finding_codes
    ):
        return None, "finding_code_unknown"

    raw_codes = list(raw_finding_codes)
    unique_codes = sorted(set(raw_codes))
    unique_set = set(unique_codes)
    if any(pair <= unique_set for pair in _FINDING_CONFLICTS):
        return None, "finding_code_conflict"

    raw_codes_by_root: dict[str, set[str]] = {}
    for code in unique_codes:
        root_code = str(
            _FINDING_OWNERSHIP[code].get(
                "canonical_root_code",
                code,
            )
        )
        raw_codes_by_root.setdefault(root_code, set()).add(code)

    secondary_by_primary: dict[str, list[str]] = {}
    root_codes = set(raw_codes_by_root)
    for primary, possible_secondary in _FINDING_SECONDARY_OVERLAPS.items():
        if primary not in root_codes:
            continue
        secondary = sorted(
            code
            for code in unique_codes
            if code in possible_secondary
        )
        if secondary:
            secondary_by_primary[primary] = secondary
            root_codes.difference_update({
                str(
                    _FINDING_OWNERSHIP[code].get(
                        "canonical_root_code",
                        code,
                    )
                )
                for code in secondary
            })

    canonical_findings = [
        {
            "finding_family": _FINDING_OWNERSHIP[
                sorted(raw_codes_by_root[code])[0]
            ][
                "canonical_family"
            ],
            "finding_code": code,
            "canonical_root_code": code,
            "raw_finding_codes": sorted(raw_codes_by_root[code]),
            "canonical_subtypes": sorted({
                str(
                    _FINDING_OWNERSHIP[raw_code].get(
                        "canonical_subtype",
                        "",
                    )
                )
                for raw_code in raw_codes_by_root[code]
                if str(
                    _FINDING_OWNERSHIP[raw_code].get(
                        "canonical_subtype",
                        "",
                    )
                )
            }),
            "blocking": True,
            "secondary_finding_codes": secondary_by_primary.get(code, []),
        }
        for code in sorted(
            root_codes,
            key=lambda item: (
                -max(
                    int(_FINDING_OWNERSHIP[raw]["specificity"])
                    for raw in raw_codes_by_root[item]
                ),
                item,
            ),
        )
    ]
    primary = canonical_findings[0] if canonical_findings else {}
    changed = (
        len(raw_codes) != len(unique_codes)
        or bool(secondary_by_primary)
        or raw_codes != unique_codes
        or any(
            str(
                _FINDING_OWNERSHIP[code].get(
                    "canonical_root_code",
                    code,
                )
            )
            != code
            for code in unique_codes
        )
        or len(raw_codes_by_root) != len(unique_codes)
    )
    return {
        "blocking": bool(canonical_findings),
        "primary_finding_family": str(
            primary.get("finding_family") or ""
        ),
        "primary_finding_code": str(primary.get("finding_code") or ""),
        "primary_canonical_root_code": str(
            primary.get("canonical_root_code") or ""
        ),
        "primary_raw_finding_codes": list(
            primary.get("raw_finding_codes") or []
        ),
        "primary_canonical_subtypes": list(
            primary.get("canonical_subtypes") or []
        ),
        "secondary_finding_codes": sorted({
            item
            for finding in canonical_findings
            for item in finding["secondary_finding_codes"]
        }),
        "raw_finding_codes": raw_codes,
        "raw_finding_details": [
            {
                "raw_finding_code": code,
                "canonical_family": _FINDING_OWNERSHIP[code][
                    "canonical_family"
                ],
                "canonical_root_code": _FINDING_OWNERSHIP[
                    code
                ].get("canonical_root_code", code),
                "canonical_subtype": _FINDING_OWNERSHIP[
                    code
                ].get("canonical_subtype", ""),
                "blocking": True,
            }
            for code in raw_codes
        ],
        "canonical_findings": canonical_findings,
        "normalization_status": (
            "canonicalized"
            if changed
            else "unchanged"
            if canonical_findings
            else "no_findings"
        ),
    }, ""


def _canonical_goal_finding(
    check: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    normalized, issue = _canonicalize_finding_codes(
        check.get("finding_codes")
    )
    if normalized is None:
        return None, issue
    return {
        "goal_ref": check["goal_ref"],
        "clause_ref": check["clause_ref"],
        **normalized,
    }, ""


def _semantic_budget_finding_codes(
    check: dict[str, Any],
) -> list[str]:
    findings = []
    if check["advice_status"] == "unauthorized":
        findings.append("advice_scope_exceeded")
    if check["variability_factor_status"] == "outside_budget":
        findings.append("variability_factor_scope_exceeded")
    elif check["variability_factor_status"] == "asserted_as_fact":
        findings.append("variability_factor_asserted_as_fact")
    if check["restricted_boundary_status"] == "violated":
        findings.append("restricted_boundary_violation")
    if check["conclusion_status"] == "outside_budget":
        findings.append("inference_scope_exceeded")
    return sorted(findings)


def _safe_raw_semantic_budget_checks(
    raw_checks: Any,
    *,
    atomic_contract: list[dict[str, Any]],
) -> list[dict[str, str]] | None:
    if not isinstance(raw_checks, list):
        return None
    expected_refs = {
        (item["goal_ref"], item["clause_ref"])
        for item in atomic_contract
        if item.get("semantic_budget_applicable") is True
    }
    status_contracts = {
        "advice_status": _ATOMIC_ADVICE_STATUSES,
        "variability_factor_status": (
            _ATOMIC_VARIABILITY_FACTOR_STATUSES
        ),
        "restricted_boundary_status": (
            _ATOMIC_RESTRICTED_BOUNDARY_STATUSES
        ),
        "conclusion_status": _ATOMIC_CONCLUSION_STATUSES,
    }
    projected: list[dict[str, str]] = []
    for check in raw_checks:
        if (
            not isinstance(check, dict)
            or set(check) != _ATOMIC_SEMANTIC_BUDGET_CHECK_FIELDS
            or not all(isinstance(value, str) for value in check.values())
            or (
                check["goal_ref"],
                check["clause_ref"],
            )
            not in expected_refs
            or any(
                check[field] not in allowed
                for field, allowed in status_contracts.items()
            )
        ):
            return None
        projected.append(dict(check))
    return projected


def _validated_semantic_budget_checks(
    raw_checks: Any,
    *,
    atomic_contract: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]] | None,
    dict[tuple[str, str], list[str]],
    dict[str, Any],
]:
    if not isinstance(raw_checks, list):
        return None, {}, _semantic_validation_diagnostics(
            "semantic_budget_checks_type_invalid",
            json_path="$.semantic_budget_checks",
            expected_type="array",
            actual_type=type(raw_checks).__name__,
        )
    targets = [
        item
        for item in atomic_contract
        if item.get("semantic_budget_applicable") is True
    ]
    if len(raw_checks) != len(targets):
        return None, {}, _semantic_validation_diagnostics(
            "semantic_budget_check_count_invalid",
            json_path="$.semantic_budget_checks",
            expected_type="one_check_per_applicable_clause",
            actual_type="incomplete_or_extra_check_set",
            missing_field_count=max(0, len(targets) - len(raw_checks)),
            extra_field_count=max(0, len(raw_checks) - len(targets)),
        )
    normalized: list[dict[str, Any]] = []
    derived_by_ref: dict[tuple[str, str], list[str]] = {}
    for index, (check, target) in enumerate(
        zip(raw_checks, targets, strict=True)
    ):
        path = f"$.semantic_budget_checks[{index}]"
        if not isinstance(check, dict):
            return None, {}, _semantic_validation_diagnostics(
                "semantic_budget_check_type_invalid",
                json_path=path,
                expected_type="object",
                actual_type=type(check).__name__,
            )
        if set(check) != _ATOMIC_SEMANTIC_BUDGET_CHECK_FIELDS:
            return None, {}, _semantic_validation_diagnostics(
                "semantic_budget_check_fields_invalid",
                json_path=path,
                expected_type="exact_semantic_budget_check_fields",
                actual_type="object",
                missing_field_count=len(
                    _ATOMIC_SEMANTIC_BUDGET_CHECK_FIELDS - set(check)
                ),
                extra_field_count=len(
                    set(check) - _ATOMIC_SEMANTIC_BUDGET_CHECK_FIELDS
                ),
            )
        goal_ref = check.get("goal_ref")
        clause_ref = check.get("clause_ref")
        if (
            not isinstance(goal_ref, str)
            or not isinstance(clause_ref, str)
            or goal_ref != target["goal_ref"]
            or clause_ref != target["clause_ref"]
        ):
            return None, {}, _semantic_validation_diagnostics(
                "semantic_budget_check_order_or_reference_invalid",
                json_path=path,
                expected_type=(
                    f"{target['goal_ref']}:{target['clause_ref']}"
                ),
                actual_type=f"{goal_ref}:{clause_ref}",
            )
        status_contracts = (
            (
                "advice_status",
                _ATOMIC_ADVICE_STATUSES,
            ),
            (
                "variability_factor_status",
                _ATOMIC_VARIABILITY_FACTOR_STATUSES,
            ),
            (
                "restricted_boundary_status",
                _ATOMIC_RESTRICTED_BOUNDARY_STATUSES,
            ),
            (
                "conclusion_status",
                _ATOMIC_CONCLUSION_STATUSES,
            ),
        )
        for field, allowed in status_contracts:
            if check.get(field) not in allowed:
                return None, {}, _semantic_validation_diagnostics(
                    "semantic_budget_status_invalid",
                    json_path=f"{path}.{field}",
                    expected_type="allowed_semantic_budget_status",
                    actual_type=str(check.get(field) or ""),
                    invalid_enum_count=1,
                )
        if any(
            check[field] == "indeterminate"
            for field, _allowed in status_contracts
        ):
            return None, {}, _semantic_validation_diagnostics(
                "semantic_budget_indeterminate",
                json_path=path,
                expected_type="determinate_semantic_budget_vector",
                actual_type="indeterminate",
                invalid_enum_count=1,
            )
        boundary_applicable = bool(
            target.get("restricted_request_boundary")
        )
        if (
            boundary_applicable
            and check["restricted_boundary_status"]
            == "not_applicable"
        ) or (
            not boundary_applicable
            and check["restricted_boundary_status"]
            != "not_applicable"
        ):
            return None, {}, _semantic_validation_diagnostics(
                "semantic_budget_boundary_applicability_invalid",
                json_path=f"{path}.restricted_boundary_status",
                expected_type=(
                    "preserved_or_violated"
                    if boundary_applicable
                    else "not_applicable"
                ),
                actual_type=check["restricted_boundary_status"],
                invalid_enum_count=1,
            )
        if (
            target.get("advice_mode") == "none"
            and check["advice_status"] == "authorized"
        ):
            return None, {}, _semantic_validation_diagnostics(
                "semantic_budget_advice_authorization_invalid",
                json_path=f"{path}.advice_status",
                expected_type="absent_or_unauthorized",
                actual_type="authorized",
                invalid_enum_count=1,
            )
        current = dict(check)
        normalized.append(current)
        derived_by_ref[(goal_ref, clause_ref)] = (
            _semantic_budget_finding_codes(current)
        )
    return (
        normalized,
        derived_by_ref,
        _semantic_validation_diagnostics(
            "accepted",
            json_path="$.semantic_budget_checks",
            expected_type="complete_semantic_budget_check_matrix",
            actual_type="complete_semantic_budget_check_matrix",
        ),
    )


def _atomic_semantic_result_with_diagnostics(
    parsed: Any,
    *,
    atomic_contract: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(parsed, dict):
        return None, _semantic_validation_diagnostics(
            "top_level_type_invalid",
            json_path="$",
            expected_type="object",
            actual_type=type(parsed).__name__,
        )
    if set(parsed) != _ATOMIC_SEMANTIC_OUTPUT_FIELDS:
        return None, _semantic_validation_diagnostics(
            "top_level_fields_invalid",
            json_path="$",
            expected_type="exact_atomic_semantic_fields",
            actual_type="object",
            missing_field_count=len(_ATOMIC_SEMANTIC_OUTPUT_FIELDS - set(parsed)),
            extra_field_count=len(set(parsed) - _ATOMIC_SEMANTIC_OUTPUT_FIELDS),
        )
    if parsed.get("schema_version") != _ATOMIC_SEMANTIC_SCHEMA_VERSION:
        return None, _semantic_validation_diagnostics(
            "schema_version_invalid",
            json_path="$.schema_version",
            expected_type=_ATOMIC_SEMANTIC_SCHEMA_VERSION,
            actual_type=type(parsed.get("schema_version")).__name__,
        )
    checks = parsed.get("goal_reviews")
    raw_semantic_budget_checks = parsed.get(
        "semantic_budget_checks"
    )
    global_issues = parsed.get("global_finding_codes")
    if not isinstance(checks, list):
        return None, _semantic_validation_diagnostics(
            "goal_reviews_type_invalid",
            json_path="$.goal_reviews",
            expected_type="array",
            actual_type=type(checks).__name__,
        )
    if not isinstance(global_issues, list):
        return None, _semantic_validation_diagnostics(
            "global_finding_codes_type_invalid",
            json_path="$.global_finding_codes",
            expected_type="array",
            actual_type=type(global_issues).__name__,
        )
    if any(
        not isinstance(item, str)
        or item not in _NON_BUDGET_FINDING_CODES
        for item in global_issues
    ):
        return None, _semantic_validation_diagnostics(
            "global_issue_code_invalid",
            json_path="$.global_finding_codes",
            expected_type="allowed_issue_codes",
            actual_type="invalid_issue_code",
            invalid_enum_count=1,
        )

    expected = {
        (item["goal_ref"], item["clause_ref"]): item
        for item in atomic_contract
    }
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    for index, check in enumerate(checks):
        path = f"$.goal_reviews[{index}]"
        if not isinstance(check, dict):
            return None, _semantic_validation_diagnostics(
                "segment_type_invalid",
                json_path=path,
                expected_type="object",
                actual_type=type(check).__name__,
            )
        if set(check) != _ATOMIC_SEGMENT_FIELDS:
            return None, _semantic_validation_diagnostics(
                "segment_fields_invalid",
                json_path=path,
                expected_type="exact_atomic_segment_fields",
                actual_type="object",
                missing_field_count=len(_ATOMIC_SEGMENT_FIELDS - set(check)),
                extra_field_count=len(set(check) - _ATOMIC_SEGMENT_FIELDS),
            )
        goal_ref = str(check.get("goal_ref") or "").strip()
        clause_ref = str(check.get("clause_ref") or "").strip()
        key = (goal_ref, clause_ref)
        contract = expected.get(key)
        if key in observed:
            return None, _semantic_validation_diagnostics(
                "duplicate_segment_reference",
                json_path=path,
                expected_type="unique_goal_and_clause_reference",
                actual_type="duplicate_reference",
            )
        if contract is None:
            return None, _semantic_validation_diagnostics(
                "unknown_segment_reference",
                json_path=path,
                expected_type="known_goal_and_clause_reference",
                actual_type="unknown_reference",
            )
        if check.get("clause_kind") != contract["clause_kind"]:
            return None, _semantic_validation_diagnostics(
                "clause_kind_mismatch",
                json_path=f"{path}.clause_kind",
                expected_type=contract["clause_kind"],
                actual_type=str(check.get("clause_kind") or ""),
            )
        textual_status = check.get("textual_status")
        if textual_status not in {"accepted", "rejected"}:
            return None, _semantic_validation_diagnostics(
                "textual_status_invalid",
                json_path=f"{path}.textual_status",
                expected_type="accepted_or_rejected",
                actual_type=str(textual_status or ""),
                invalid_enum_count=1,
            )
        issue_codes = check.get("finding_codes")
        if not isinstance(issue_codes, list):
            return None, _semantic_validation_diagnostics(
                "finding_codes_type_invalid",
                json_path=f"{path}.finding_codes",
                expected_type="array",
                actual_type=type(issue_codes).__name__,
            )
        if any(
            not isinstance(item, str)
            or item not in _NON_BUDGET_FINDING_CODES
            for item in issue_codes
        ):
            return None, _semantic_validation_diagnostics(
                "issue_code_invalid",
                json_path=f"{path}.finding_codes",
                expected_type="allowed_issue_codes",
                actual_type="invalid_issue_code",
                invalid_enum_count=1,
            )
        if (
            textual_status == "accepted" and issue_codes
        ) or (
            textual_status == "rejected" and not issue_codes
        ):
            return None, _semantic_validation_diagnostics(
                "textual_status_finding_mismatch",
                json_path=f"{path}.finding_codes",
                expected_type="status_consistent_finding_set",
                actual_type="inconsistent_finding_set",
            )
        observed[key] = {
            **check,
            "finding_codes": list(issue_codes),
        }
    if set(observed) != set(expected):
        return None, _semantic_validation_diagnostics(
            "segment_reference_set_incomplete",
            json_path="$.goal_reviews",
            expected_type="complete_atomic_contract",
            actual_type="incomplete_reference_set",
            missing_field_count=len(set(expected) - set(observed)),
        )

    (
        semantic_budget_checks,
        budget_findings_by_ref,
        budget_validation,
    ) = _validated_semantic_budget_checks(
        raw_semantic_budget_checks,
        atomic_contract=atomic_contract,
    )
    if semantic_budget_checks is None:
        return None, budget_validation

    raw_goal_reviews = [
        observed[(item["goal_ref"], item["clause_ref"])]
        for item in atomic_contract
    ]
    normalized_checks = []
    checks_for_canonicalization = []
    semantic_budget_derivations = []
    for check in raw_goal_reviews:
        key = (check["goal_ref"], check["clause_ref"])
        derived = list(budget_findings_by_ref.get(key) or [])
        combined_raw = [
            *check["finding_codes"],
            *derived,
        ]
        combined = sorted(set(combined_raw))
        normalized_checks.append({
            **check,
            "textual_status": (
                "rejected" if combined else "accepted"
            ),
            "finding_codes": combined,
        })
        checks_for_canonicalization.append({
            **check,
            "textual_status": (
                "rejected" if combined_raw else "accepted"
            ),
            "finding_codes": combined_raw,
        })
        if key in budget_findings_by_ref:
            semantic_budget_derivations.append({
                "goal_ref": key[0],
                "clause_ref": key[1],
                "canonical_finding_codes": derived,
            })
    canonical_goal_findings: list[dict[str, Any]] = []
    for index, check in enumerate(checks_for_canonicalization):
        canonical, normalization_issue = _canonical_goal_finding(check)
        if canonical is None:
            return None, _semantic_validation_diagnostics(
                normalization_issue,
                json_path=f"$.goal_reviews[{index}].finding_codes",
                expected_type="consistent_known_finding_codes",
                actual_type="normalization_invalid",
            )
        canonical_goal_findings.append(canonical)

    canonical_global_findings, global_normalization_issue = (
        _canonicalize_finding_codes(global_issues)
    )
    if canonical_global_findings is None:
        return None, _semantic_validation_diagnostics(
            global_normalization_issue,
            json_path="$.global_finding_codes",
            expected_type="consistent_known_finding_codes",
            actual_type="normalization_invalid",
        )
    goal_bound_codes = {
        finding["finding_code"]
        for goal in canonical_goal_findings
        for finding in goal["canonical_findings"]
    }
    duplicate_global_codes = sorted(
        goal_bound_codes
        & {
            finding["finding_code"]
            for finding in canonical_global_findings["canonical_findings"]
        }
    )
    if duplicate_global_codes:
        retained_global_findings = [
            finding
            for finding in canonical_global_findings["canonical_findings"]
            if finding["finding_code"] not in duplicate_global_codes
        ]
        primary_global = (
            retained_global_findings[0]
            if retained_global_findings
            else {}
        )
        canonical_global_findings.update({
            "blocking": bool(retained_global_findings),
            "primary_finding_family": str(
                primary_global.get("finding_family") or ""
            ),
            "primary_finding_code": str(
                primary_global.get("finding_code") or ""
            ),
            "primary_canonical_root_code": str(
                primary_global.get("canonical_root_code") or ""
            ),
            "primary_raw_finding_codes": list(
                primary_global.get("raw_finding_codes") or []
            ),
            "primary_canonical_subtypes": list(
                primary_global.get("canonical_subtypes") or []
            ),
            "secondary_finding_codes": sorted({
                *canonical_global_findings["secondary_finding_codes"],
                *duplicate_global_codes,
            }),
            "canonical_findings": retained_global_findings,
            "normalization_status": "goal_attribution_preferred",
        })

    issues = sorted({
        *global_issues,
        *(
            issue
            for check in normalized_checks
            for issue in check["finding_codes"]
        ),
    })
    blocking = (
        any(item["blocking"] for item in canonical_goal_findings)
        or canonical_global_findings["blocking"]
    )
    result = _result(
        not blocking,
        issues,
        (
            "Unified textual audit passed."
            if not blocking
            else "Unified textual audit failed: " + ",".join(issues)
        ),
        "llm_unified_textual_audit",
    )
    result.update({
        "schema_version": _ATOMIC_SEMANTIC_SCHEMA_VERSION,
        "raw_goal_reviews": raw_goal_reviews,
        "goal_reviews": normalized_checks,
        "semantic_budget_checks": semantic_budget_checks,
        "semantic_budget_derivations": (
            semantic_budget_derivations
        ),
        "global_finding_codes": list(global_issues),
        "finding_ontology_version": _FINDING_ONTOLOGY_VERSION,
        "canonical_goal_findings": canonical_goal_findings,
        "canonical_global_findings": canonical_global_findings,
        "normalization_status": (
            "canonicalized"
            if any(
                item["canonical_finding_codes"]
                for item in semantic_budget_derivations
            )
            or any(
                item["normalization_status"] != "unchanged"
                and item["normalization_status"] != "no_findings"
                for item in canonical_goal_findings
            )
            or canonical_global_findings["normalization_status"]
            not in {"unchanged", "no_findings"}
            else "unchanged"
        ),
    })
    return result, _semantic_validation_diagnostics(
        "accepted",
        json_path="$",
        expected_type="unified_textual_audit_response",
        actual_type="unified_textual_audit_response",
    )


def _validate_llm_semantic_result(parsed: Any) -> str:
    if not isinstance(parsed, dict) or set(parsed) != {"passed", "issues", "reason"}:
        return "object_schema_invalid"
    if not isinstance(parsed["passed"], bool):
        return "passed_type_invalid"
    issues = parsed["issues"]
    if not isinstance(issues, list) or any(
        not isinstance(item, str) or item not in _LLM_SEMANTIC_ISSUE_CODES
        for item in issues
    ):
        return "issue_code_invalid"
    if len(issues) != len(set(issues)):
        return "duplicate_issue_code"
    if parsed["passed"] and issues:
        return "passed_with_issues"
    if not parsed["passed"] and not issues:
        return "failed_without_issue"
    reason = parsed["reason"]
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 500
        or "\n" in reason
        or "\r" in reason
    ):
        return "reason_invalid"
    return ""


def _semantic_judge_failure(
    issue: str,
    *,
    provider_diagnostics: dict[str, Any] | None = None,
    validation_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason = (
        "Semantic judge is unavailable."
        if issue == "semantic_judge_unavailable"
        else "Semantic judge response schema is invalid."
    )
    result = _result(False, [issue], reason, "llm_semantic_fit")
    if provider_diagnostics is not None:
        result["provider_diagnostics"] = provider_diagnostics
    if validation_diagnostics is not None:
        result["validation_diagnostics"] = validation_diagnostics
    return result


def _semantic_provider_diagnostics(
    content: str,
    *,
    finish_reason: str,
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "response_envelope": "unclassified",
        "response_length": len(content),
        "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "finish_reason": finish_reason,
        "provider_latency_ms": max(0, latency_ms),
        "provider_error_type": "",
        "model_call_count": 1,
        "retry_count": 0,
        "repair_count": 0,
        "json_repair_count": 0,
        "envelope_contract_version": COMPOSER_ENVELOPE_CONTRACT_VERSION,
        "envelope_unwrap_count": 0,
    }


def _semantic_provider_failure_diagnostics(exc: Exception) -> dict[str, Any]:
    return {
        "response_envelope": "provider_error",
        "response_length": 0,
        "response_sha256": "",
        "finish_reason": "",
        "provider_latency_ms": None,
        "provider_error_type": type(exc).__name__,
        "model_call_count": 1,
        "retry_count": 0,
        "repair_count": 0,
        "json_repair_count": 0,
        "envelope_contract_version": COMPOSER_ENVELOPE_CONTRACT_VERSION,
        "envelope_unwrap_count": 0,
    }


def _strict_semantic_provider_diagnostics(
    provider: StrictDecisionProviderService,
    *,
    parsed: dict[str, Any] | None = None,
    error_type: str = "",
    model_call_count: int,
) -> dict[str, Any]:
    metadata = provider.metadata()
    canonical_response = (
        json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if parsed is not None
        else ""
    )
    latency = provider.last_latency_ms
    return {
        "response_envelope": (
            "native_strict_object"
            if parsed is not None
            else "provider_error"
        ),
        "response_length": len(canonical_response),
        "response_sha256": (
            hashlib.sha256(
                canonical_response.encode("utf-8")
            ).hexdigest()
            if canonical_response
            else ""
        ),
        "finish_reason": (
            "strict_schema_completed" if parsed is not None else ""
        ),
        "provider_latency_ms": (
            max(0, int(latency)) if latency is not None else None
        ),
        "provider_error_type": error_type,
        "model_call_count": model_call_count,
        "retry_count": 0,
        "repair_count": 0,
        "json_repair_count": 0,
        "envelope_contract_version": "native-strict-output/v1",
        "envelope_unwrap_count": 0,
        "provider_role": "unified_textual_audit",
        "provider_name": metadata["provider_name"],
        "host_fingerprint": metadata["host_fingerprint"],
        "model_name": metadata["model_name"],
        "capability": metadata["capability"],
        "configured": metadata["configured"],
        "qualified": metadata["qualified"],
    }


def _semantic_validation_diagnostics(
    category: str,
    *,
    json_path: str,
    expected_type: str,
    actual_type: str,
    missing_field_count: int = 0,
    extra_field_count: int = 0,
    invalid_enum_count: int = 0,
) -> dict[str, Any]:
    return {
        "category": category,
        "json_path": json_path,
        "expected_type": expected_type,
        "actual_type": actual_type,
        "missing_field_count": missing_field_count,
        "extra_field_count": extra_field_count,
        "invalid_enum_count": invalid_enum_count,
    }


def _is_model_first_candidate(response: dict[str, Any]) -> bool:
    composer = response.get("model_first_answer_composer")
    return isinstance(composer, dict) and composer.get("status") == "accepted"


def _model_first_unified_audit_payload(
    response: dict[str, Any],
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any]:
    from app.services.canonical_conversation_turn_service import (
        project_text_for_external_model,
    )
    from app.services.final_answer_auditor import _model_first_audit_context

    audit_context = _model_first_audit_context(response, copilot_context)
    truth = audit_context.get("canonical_truth")
    if not isinstance(truth, dict):
        truth = {}
    candidate_clauses = [
        item
        for item in truth.get("candidate_clauses") or []
        if isinstance(item, dict)
    ]
    goal_refs = {
        str(item.get("goal_ref") or "")
        for item in candidate_clauses
        if str(item.get("goal_ref") or "")
    }
    evidence_refs = {
        str(ref)
        for item in candidate_clauses
        for ref in (
            list(item.get("evidence_refs") or [])
            + list(item.get("premise_evidence_refs") or [])
        )
        if str(ref)
    }
    completed_action_refs = sorted({
        "action_"
        + hashlib.sha256(
            str(item.get("action_id") or "").encode("utf-8")
        ).hexdigest()[:12]
        for item in response.get("action_events") or []
        if isinstance(item, dict)
        and str(item.get("status") or "") == "completed"
        and str(item.get("action_id") or "").strip()
    })
    media_blocks = [
        {
            "type": str(item.get("type") or ""),
            "send_mode": str(item.get("send_mode") or ""),
        }
        for item in response.get("reply_blocks") or []
        if isinstance(item, dict)
        and str(item.get("type") or "") in {"image", "video"}
        and str(item.get("url") or item.get("asset_url") or "").strip()
    ]
    final_audit = response.get("final_answer_audit")
    if not isinstance(final_audit, dict):
        final_audit = {}
    return {
        "schema_version": "unified-textual-audit-input-v1",
        "current_customer_message": project_text_for_external_model(
            customer_message
        ),
        "final_reply": project_text_for_external_model(
            response.get("suggested_reply") or ""
        ),
        "canonical_truth": {
            "evidence": [
                item
                for item in truth.get("evidence") or []
                if isinstance(item, dict)
                and str(item.get("evidence_ref") or "") in evidence_refs
            ],
            "claim_resolutions": [
                item
                for item in truth.get("claim_resolutions") or []
                if isinstance(item, dict)
                and str(item.get("claim_ref") or "") in goal_refs
            ],
            "candidate_clauses": candidate_clauses,
            "unresolved_or_prohibited_claims": [
                item
                for item in truth.get("unresolved_or_prohibited_claims") or []
                if isinstance(item, dict)
                and str(item.get("claim_ref") or "") in goal_refs
            ],
        },
        "conversation_continuity": audit_context.get(
            "conversation_continuity"
        )
        or {},
        "completion_evidence": {
            "completed_action_refs": completed_action_refs,
            "attached_media_blocks": media_blocks,
        },
        "deterministic_final_contract": {
            "passed": final_audit.get("passed") is True,
            "issues": list(final_audit.get("issues") or []),
            "model_call_count": int(final_audit.get("model_call_count") or 0),
        },
    }


def _semantic_payload(
    response: dict[str, Any],
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any]:
    if _is_model_first_candidate(response):
        return _model_first_unified_audit_payload(
            response,
            customer_message,
            copilot_context,
        )

    debug = response.get("evidence_debug") or {}
    evidence_pack = _evidence_pack(response)
    admitted = debug.get("admitted_answer_context")
    if not isinstance(admitted, dict):
        from app.services.admitted_answer_context_service import (
            AdmittedAnswerContextService,
            resolved_product_identity_for_response,
        )

        query_fact_type = _query_fact_type(response, evidence_pack)
        understanding = {
            "requested_claims": ([{
                "claim_type": query_fact_type,
                "question": customer_message,
                "risk_level": str(response.get("risk_level") or debug.get("risk_level") or "medium"),
            }] if query_fact_type else [])
        }
        request_identity = {
            "sku_code": response.get("sku_code") or debug.get("sku_code") or copilot_context.get("sku_code") or "",
            "i_id": response.get("i_id") or debug.get("i_id") or copilot_context.get("i_id") or "",
            "product_id": response.get("product_id") or debug.get("product_id") or copilot_context.get("product_id") or "",
        }
        product_identity = resolved_product_identity_for_response(response, request_identity)
        admitted = AdmittedAnswerContextService().build_for_response(
            response,
            product_identity=product_identity,
            understanding=understanding,
        )
    admitted_facts = [
        {
            "evidence_uid": item.get("evidence_uid", ""),
            "source_type": item.get("source_type", ""),
            "evidence_role": item.get("evidence_role", ""),
            "claim_types_supported": item.get("claim_types_supported", []),
            "text": item.get("text", ""),
        }
        for item in [
            *(admitted.get("direct_product_facts") or []),
            *(admitted.get("direct_policy_facts") or []),
        ][:8]
        if isinstance(item, dict)
    ]
    minimal_context = response.get("minimal_decision_context")
    if not isinstance(minimal_context, dict):
        minimal_context = debug.get("minimal_decision_context")
    if not isinstance(minimal_context, dict):
        minimal_context = {}
    composer = response.get("model_first_answer_composer")
    if not isinstance(composer, dict):
        composer = {}
    model_first_enabled = composer.get("status") == "accepted"
    return {
        "customer_message": customer_message,
        "final_reply": response.get("suggested_reply", ""),
        "requires_human_review": bool(response.get("requires_human_review")),
        "review_reason": response.get("reason_for_review") or response.get("review_reason") or "",
        "intent": response.get("intent", ""),
        "semantic_query": debug.get("semantic_query") or response.get("semantic_query") or {},
        "query_fact_type": _query_fact_type(response, evidence_pack),
        "evidence_pack_status": {
            "answerability": evidence_pack.get("answerability", ""),
            "matched_fields": evidence_pack.get("matched_fields", []),
            "missing_fields": evidence_pack.get("missing_fields", []),
        },
        "admitted_direct_facts": admitted_facts,
        "unresolved_claims": admitted.get("unresolved_claims") or [],
        "model_first_candidate_contract": {
            "enabled": model_first_enabled,
            "review_only": model_first_enabled,
            "product_identity_resolved": bool(minimal_context.get("product_identity")),
            "full_product_title_required": False,
            "allowed_low_risk_reasoning": (
                list(composer.get("allowed_low_risk_reasoning") or [])
                if model_first_enabled
                else []
            ),
        },
        "recommended_assets": [
            {
                "asset_type": item.get("asset_type", ""),
                "asset_title": item.get("asset_title", ""),
            }
            for item in (response.get("recommended_assets") or [])[:5]
        ],
        "reply_blocks": [
            {"type": item.get("type", ""), "title": item.get("title", "")}
            for item in (response.get("reply_blocks") or [])[:5]
            if isinstance(item, dict)
        ],
        "copilot_context": {
            "order_id_present": bool(
                copilot_context.get("order_id")
                or copilot_context.get("platform_order_id")
                or copilot_context.get("platform_trade_id")
            ),
            "product_name": copilot_context.get("product_name", ""),
        },
    }


def _is_visual_media_answer(response: dict[str, Any]) -> bool:
    """Return True when the reply includes a media asset for a visual fact type."""
    fact_type = str(
        ((response.get("evidence_debug") or {}).get("query_fact_type"))
        or (response.get("query_fact_type"))
        or ""
    )
    visual_fact_types = {"dimensions", "space_fit", "installation", "detachable", "accessories", "packaging"}
    if fact_type not in visual_fact_types:
        return False
    try:
        from app.services.no_evidence_reply_policy_service import media_delivery_claim_issues

        if media_delivery_claim_issues(response):
            return False
    except Exception:
        return False
    has_media = bool([
        b
        for b in (response.get("reply_blocks") or [])
        if isinstance(b, dict) and b.get("type") in {"image", "video"}
    ])
    if not has_media:
        return False
    reply = str(response.get("suggested_reply") or "").lower()
    return any(term in reply for term in (
        "图", "图片", "尺寸图", "视频", "安装视频", "参考下面", "下面发您",
    ))


def _no_evidence_controlled_reply_acceptable(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") or {}
    mode = str(debug.get("answer_mode") or response.get("answer_mode") or "")
    if mode not in {"no_evidence_controlled_reply", "no_evidence_clarification"}:
        return False
    if not response.get("requires_human_review"):
        return False
    trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    policy = trace.get("no_evidence_reply_policy") or debug.get("no_evidence_reply_policy") or {}
    if not isinstance(policy, dict) or not policy.get("reply_strategy"):
        return False
    try:
        from app.services.no_evidence_reply_policy_service import media_delivery_claim_issues

        if media_delivery_claim_issues(response):
            return False
    except Exception:
        return False
    return True


def _generic_rule_fallback_acceptable(
    response: dict[str, Any],
    evidence_pack: dict[str, Any],
    query_fact_type: str,
) -> bool:
    """Return True when the reply is a policy-grounded generic-rule fallback."""
    if str(evidence_pack.get("answerability") or "") != "generic_rule_fallback":
        return False
    if not query_fact_type:
        return False
    matched_rules = [
        rule
        for rule in (evidence_pack.get("matched_generic_rules") or [])
        if isinstance(rule, dict) and str(rule.get("fact_type") or "") == query_fact_type
    ]
    if not matched_rules:
        return False

    # Look up the full rule definition to check risk and auto-reply flags.
    debug = response.get("evidence_debug") or {}
    product_pack = (
        response.get("product_context_pack")
        or debug.get("product_context_pack_summary")
        or {}
    )
    full_rules = {
        str(rule.get("rule_key") or ""): rule
        for rule in (product_pack.get("generic_rules") or [])
        if isinstance(rule, dict)
    }
    for rule in matched_rules:
        full = full_rules.get(str(rule.get("rule_key") or "")) or {}
        if full.get("auto_reply_allowed") is False:
            return False
        if str(full.get("risk_level") or "low").lower() not in {"low", "medium"}:
            return False

    # Do not accept replies that repeat forbidden claims from the rule.
    reply = str(response.get("suggested_reply") or "").lower()
    for rule in matched_rules:
        for claim in rule.get("forbidden_claims") or []:
            if claim and claim.lower() in reply:
                return False
    return True


def _generic_or_template_supports_fact_type(
    response: dict[str, Any],
    evidence_pack: dict[str, Any],
    query_fact_type: str,
) -> bool:
    """Return True when generic rules or template evidence support query_fact_type."""
    matched_generic = [
        rule
        for rule in (evidence_pack.get("matched_generic_rules") or [])
        if isinstance(rule, dict) and str(rule.get("fact_type") or "") == query_fact_type
    ]
    if matched_generic:
        return True
    debug = response.get("evidence_debug") or {}
    for item in (debug.get("template_evidence") or []):
        if not isinstance(item, dict):
            continue
        ev_ft = str(item.get("evidence_fact_type") or item.get("fact_type") or "")
        if ev_ft == query_fact_type:
            return True
    return False


def _evidence_pack(response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    summary = debug.get("product_context_pack_summary") or {}
    if isinstance(summary, dict):
        pack = summary.get("evidence_pack")
        if isinstance(pack, dict):
            return pack
    pack = response.get("product_card_evidence_pack")
    if isinstance(pack, dict):
        return pack
    product_pack = response.get("product_context_pack")
    if isinstance(product_pack, dict):
        pack = product_pack.get("evidence_pack")
        if isinstance(pack, dict):
            return pack
    return {}


def _query_fact_type(response: dict[str, Any], evidence_pack: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") or {}
    semantic = debug.get("semantic_query") or response.get("semantic_query") or {}
    if isinstance(semantic, dict) and semantic.get("primary_fact_type"):
        return str(semantic.get("primary_fact_type") or "")
    return str(
        evidence_pack.get("query_fact_type")
        or debug.get("query_fact_type")
        or response.get("query_fact_type")
        or ""
    )


def _semantic_fit_fallback(response: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    partial = debug.get("formal_partial_answer") if isinstance(debug.get("formal_partial_answer"), dict) else {}
    partial_text = str(partial.get("candidate_text") or "").strip()
    if partial_text and partial.get("supported_clauses"):
        return partial_text
    display_name = str(response.get("display_product_name") or "").strip()
    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)
    if query_fact_type in {"material", "material_safety", "certification_report", "odor"}:
        return "亲，我先帮您对一下这款的材质、安全和防潮说明，确认后回您。"
    if query_fact_type:
        reply = customer_facing_safe_handoff_reply(query_fact_type, inputs={"product_name": display_name})
        if reply:
            return reply
    product = "这款" if display_name else "这款商品"
    return (
        f"亲，{product}我再帮您对一下资料，确认清楚后回您。"
    )


def _append_reason(existing: str, reason: str) -> str:
    existing = str(existing or "").strip()
    if not existing:
        return reason
    if reason in existing:
        return existing
    return f"{existing}; {reason}"


def _result(passed: bool, issues: list[str], reason: str, mode: str) -> dict[str, Any]:
    return {
        "checked": True,
        "passed": bool(passed),
        "issues": issues,
        "reason": reason,
        "mode": mode,
    }
