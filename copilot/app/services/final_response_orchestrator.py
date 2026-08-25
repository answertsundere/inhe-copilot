"""Final response orchestration for customer-facing replies.

The final layer has four explicit responsibilities:

1. semantic / red-line audit before language polishing;
2. customer-language polish without changing facts;
3. lightweight red-line check after polishing, because polishers can also
   introduce forbidden language;
4. keep text reply blocks in sync with the final suggested reply.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app import config
from app.services.customer_reply_polisher import polish_customer_reply, _polish_text
from app.services.final_answer_auditor import audit_final_answer
from app.services.final_semantic_quality_service import (
    apply_semantic_fit_result,
    audit_customer_reply_semantic_fit,
)
from app.services.generic_service_rule_service import unsafe_promise_terms
from app.services.no_evidence_reply_policy_service import (
    align_delivery_media_reference,
    apply_no_evidence_reply_policy,
)


FINAL_RESPONSE_PIPELINE_VERSION = "final-response-orchestrator-v1"


_POST_POLISH_INTERNAL_TERMS = (
    "RAG",
    "Evidence Gate",
    "query_fact_type",
    "fact_type",
    "系统",
    "资料库",
    "知识库",
    "已审核资料",
    "四级控价",
    "大促价",
    "内部价",
    "成本价",
    "利润",
    # Existing files contain mojibake in some generated strings. Keep these
    # variants until the repository-wide encoding cleanup is done.
    "绯荤粺",
    "璧勬枡搴",
    "鐭ヨ瘑搴",
    "宸插鏍歌祫鏂",
)


def orchestrate_final_response(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the authoritative final output pipeline.

    This function is intentionally the only API-facing final output entrypoint.
    Do not call final_answer_auditor and customer_reply_polisher separately from
    API handlers; doing so makes the final node order ambiguous.
    """
    if (
        (response.get("model_first_answer_composer") or {}).get("status")
        == "accepted"
        and (response.get("model_first_answer_composer") or {}).get(
            "used_for_final_reply"
        ) is True
    ):
        return _orchestrate_model_first_response(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )

    pipeline: list[dict[str, Any]] = []

    _apply_formal_delivery_boundary(response)
    response = apply_no_evidence_reply_policy(response, copilot_context)
    response = _apply_formal_partial_answer(response)

    response = audit_final_answer(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    audit = response.get("final_answer_audit") or {}
    pipeline.append({
        "stage": "semantic_and_redline_audit",
        "passed": bool(audit.get("passed", True)),
        "mode": audit.get("mode", ""),
        "issues": audit.get("issues", []),
    })

    before_polish = str(response.get("suggested_reply") or "")
    response = polish_customer_reply(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    _restore_formal_partial_if_lost(response)
    polish = response.get("customer_reply_polish") or {}
    pipeline.append({
        "stage": "customer_language_polish",
        "applied": bool(polish.get("applied")),
        "mode": polish.get("mode", ""),
        "changed": before_polish != str(response.get("suggested_reply") or ""),
    })

    pre_llm_polish_reply = str(response.get("suggested_reply") or "")
    llm_polish = _optional_llm_language_polish(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context or {},
    )
    if llm_polish and not _preserves_current_product_anchor(
        pre_llm_polish_reply,
        llm_polish["reply"],
    ):
        response.setdefault("evidence_debug", {})["llm_customer_language_polish_rejected"] = {
            "reason": "current_product_anchor_dropped",
        }
        llm_polish = None
    if llm_polish:
        response["suggested_reply"] = llm_polish["reply"]
        response["llm_customer_language_polish"] = {
            "applied": True,
            "mode": "llm_customer_language_expert",
            "reason": llm_polish.get("reason", ""),
        }
        response.setdefault("evidence_debug", {})["llm_customer_language_polish"] = response["llm_customer_language_polish"]

    # The LLM polish may reintroduce deterministic blocked phrases or handoff
    # wording that the first polish removed. Run the deterministic polish again
    # before the final redline checks.
    before_repolish = str(response.get("suggested_reply") or "")
    repolished = _polish_text(before_repolish)
    response["suggested_reply"] = repolished
    _restore_formal_partial_if_lost(response)
    if not _preserves_customer_product_name(before_repolish, repolished, response):
        response["suggested_reply"] = before_repolish
        response.setdefault("evidence_debug", {})["customer_reply_repolish_rejected"] = {
            "reason": "display_product_name_dropped",
        }
    before_media_alignment = str(response.get("suggested_reply") or "")
    response["suggested_reply"] = align_delivery_media_reference(
        before_media_alignment,
        response,
    )
    media_alignment_changed = str(response.get("suggested_reply") or "") != before_media_alignment
    if media_alignment_changed:
        response.setdefault("evidence_debug", {})["media_reference_alignment"] = {
            "applied": True,
            "source": "attached_reply_blocks",
        }
    before_second_policy_reply = str(response.get("suggested_reply") or "")
    response = apply_no_evidence_reply_policy(response, copilot_context)
    policy_changed = str(response.get("suggested_reply") or "") != before_second_policy_reply
    if llm_polish or media_alignment_changed or policy_changed:
        response = audit_final_answer(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )
    if (
        _is_no_evidence_controlled_response(response)
        and bool((response.get("final_answer_audit") or {}).get("passed", False))
    ):
        _mark_no_evidence_final_answer_audit_passed(response)

    pipeline.append({
        "stage": "llm_customer_language_polish",
        "enabled": bool(config.COPILOT_FINAL_POLISH_LLM_ENABLED),
        "applied": bool(llm_polish),
    })
    pipeline.append({
        "stage": "post_polish_final_audit",
        "changed_by_policy": policy_changed,
        "required": bool(llm_polish or media_alignment_changed or policy_changed),
        "passed": bool((response.get("final_answer_audit") or {}).get("passed", True)),
        "issues": (response.get("final_answer_audit") or {}).get("issues", []),
    })

    semantic_fit = audit_customer_reply_semantic_fit(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    response = apply_semantic_fit_result(response, semantic_fit, copilot_context=copilot_context)
    pipeline.append({
        "stage": "final_semantic_fit_audit",
        "passed": bool(semantic_fit.get("passed", True)),
        "mode": semantic_fit.get("mode", ""),
        "issues": semantic_fit.get("issues", []),
    })
    if semantic_fit.get("fallback_used"):
        response = audit_final_answer(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )
        settled_semantic_fit = audit_customer_reply_semantic_fit(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )
        settled_semantic_fit["fallback_from_issues"] = list(semantic_fit.get("issues") or [])
        response["final_semantic_fit_audit"] = settled_semantic_fit
        response.setdefault("evidence_debug", {})["final_semantic_fit_audit"] = settled_semantic_fit
        pipeline.append({
            "stage": "post_semantic_fallback_audit",
            "passed": bool((response.get("final_answer_audit") or {}).get("passed", True)),
            "issues": (response.get("final_answer_audit") or {}).get("issues", []),
        })
        pipeline.append({
            "stage": "post_semantic_fallback_fit",
            "passed": bool(settled_semantic_fit.get("passed", True)),
            "issues": settled_semantic_fit.get("issues", []),
        })

    post_issues = _post_polish_redline_issues(str(response.get("suggested_reply") or ""))
    if post_issues:
        original_reply = str(response.get("suggested_reply") or "")
        response["suggested_reply"] = _safe_post_polish_fallback(response)
        response["requires_human_review"] = True
        response["generation_mode"] = "post_polish_redline_fallback"
        response["reason_for_review"] = _append_reason(
            str(response.get("reason_for_review") or ""),
            "最终润色后命中红线，已改为保守客服话术",
        )
        response.setdefault("guard_warnings", []).append(
            "post_polish_redline: " + ",".join(post_issues)
        )
        response.setdefault("evidence_debug", {})["post_polish_redline"] = {
            "passed": False,
            "issues": post_issues,
            "original_reply": original_reply,
        }
    else:
        response.setdefault("evidence_debug", {})["post_polish_redline"] = {
            "passed": True,
            "issues": [],
        }
    pipeline.append({
        "stage": "post_polish_redline",
        "passed": not post_issues,
        "issues": post_issues,
    })

    _sync_text_reply_block(response)

    # Preserve the upstream evidence-relevance signal. Final semantic fit only
    # describes the customer-visible response, not whether an admitted fact
    # matched the requested claim.
    final_answer_passed = bool((response.get("final_answer_audit") or {}).get("passed", True))
    semantic_fit_passed = bool((response.get("final_semantic_fit_audit") or {}).get("passed", True))
    response.setdefault("evidence_debug", {})["final_response_relevance_passed"] = (
        final_answer_passed and semantic_fit_passed
    )

    response["final_response_pipeline"] = {
        "version": FINAL_RESPONSE_PIPELINE_VERSION,
        "order": [
            "semantic_and_redline_audit",
            "customer_language_polish",
            "llm_customer_language_polish",
            "post_polish_final_audit",
            "final_semantic_fit_audit",
            "post_semantic_fallback_audit",
            "post_semantic_fallback_fit",
            "post_polish_redline",
            "reply_block_sync",
        ],
        "stages": pipeline,
    }
    response.setdefault("evidence_debug", {})["final_response_pipeline"] = response["final_response_pipeline"]
    response.setdefault("trace_steps", []).append({
        "node": "final_response_orchestrator",
        "status": "completed",
        "summary": "final semantic audit, redline, polish and block sync completed",
        "stages": pipeline,
    })
    _apply_sendable_reply_contract(response, post_issues=post_issues)
    return response


def _orchestrate_model_first_response(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run one deterministic contract and one textual audit for a candidate."""
    pipeline: list[dict[str, Any]] = []
    _apply_formal_delivery_boundary(response)

    before_cleanup = str(response.get("suggested_reply") or "")
    cleaned = _non_semantic_reply_cleanup(before_cleanup)
    response["suggested_reply"] = cleaned
    response["customer_reply_polish"] = {
        "checked": True,
        "applied": cleaned != before_cleanup,
        "mode": "non_semantic_cleanup_only",
    }
    pipeline.append({
        "stage": "non_semantic_cleanup",
        "changed": cleaned != before_cleanup,
    })

    post_issues = _post_polish_redline_issues(cleaned)
    response.setdefault("evidence_debug", {})[
        "model_first_preflight_redline"
    ] = {
        "passed": not post_issues,
        "issues": post_issues,
    }
    pipeline.append({
        "stage": "model_first_preflight_redline",
        "passed": not post_issues,
        "issues": post_issues,
    })
    response = audit_final_answer(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    final_audit = response.get("final_answer_audit") or {}
    pipeline.append({
        "stage": "model_first_deterministic_final_contract",
        "passed": bool(final_audit.get("passed", False)),
        "issues": list(final_audit.get("issues") or []),
        "model_call_count": int(final_audit.get("model_call_count") or 0),
        "fallback_used": False,
    })

    if final_audit.get("passed") is True:
        semantic_fit = audit_customer_reply_semantic_fit(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )
    else:
        semantic_fit = {
            "checked": False,
            "passed": False,
            "issues": ["deterministic_final_contract_failed"],
            "reason": "Unified textual audit was not run.",
            "mode": "unified_textual_audit_not_run",
            "provider_diagnostics": {
                "model_call_count": 0,
                "retry_count": 0,
                "repair_count": 0,
            },
        }
    response["final_semantic_fit_audit"] = semantic_fit
    response.setdefault("evidence_debug", {})[
        "final_semantic_fit_audit"
    ] = semantic_fit
    pipeline.append({
        "stage": "model_first_unified_textual_audit",
        "passed": bool(semantic_fit.get("passed", False)),
        "issues": list(semantic_fit.get("issues") or []),
        "model_call_count": int(
            (semantic_fit.get("provider_diagnostics") or {}).get(
                "model_call_count"
            )
            or 0
        ),
        "fallback_used": False,
    })

    if semantic_fit.get("passed") is not True:
        response["reason_for_review"] = _append_reason(
            str(response.get("reason_for_review") or ""),
            "model_first_unified_textual_audit_failed",
        )
    response["requires_human_review"] = True
    response["can_send"] = False
    response["sendable_reply"] = ""
    response["reply_status"] = "needs_human_review"
    _sync_text_reply_block(response)
    response["final_response_pipeline"] = {
        "version": FINAL_RESPONSE_PIPELINE_VERSION,
        "mode": "model_first_candidate",
        "order": [
            "non_semantic_cleanup",
            "model_first_preflight_redline",
            "model_first_deterministic_final_contract",
            "model_first_unified_textual_audit",
            "reply_block_sync",
        ],
        "stages": pipeline,
    }
    response.setdefault("evidence_debug", {})[
        "final_response_pipeline"
    ] = response["final_response_pipeline"]
    response.setdefault("trace_steps", []).append({
        "node": "final_response_orchestrator",
        "status": "completed",
        "summary": "model-first candidate audited without semantic rewriting",
        "stages": pipeline,
    })
    _apply_sendable_reply_contract(response, post_issues=post_issues)
    return response


def _non_semantic_reply_cleanup(reply: str) -> str:
    lines = [
        " ".join(str(line).strip().split())
        for line in str(reply or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    compact: list[str] = []
    for line in lines:
        if not line:
            if compact and compact[-1]:
                compact.append("")
            continue
        compact.append(line)
    return "\n".join(compact).strip()


def _formal_evidence_convergence_enabled() -> bool:
    return os.getenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _formal_admitted_context(response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    admitted = debug.get("admitted_answer_context")
    return admitted if isinstance(admitted, dict) else {}


def _formal_non_fact_only(response: dict[str, Any]) -> bool:
    if not _formal_evidence_convergence_enabled():
        return False
    admitted = _formal_admitted_context(response)
    if not admitted:
        return False
    direct = [
        item
        for item in [
            *(admitted.get("direct_product_facts") or []),
            *(admitted.get("direct_policy_facts") or []),
        ]
        if isinstance(item, dict)
    ]
    non_fact = [
        item
        for item in [
            *(admitted.get("handoff_action_guidance") or []),
            *(admitted.get("media_candidates") or []),
        ]
        if isinstance(item, dict)
    ]
    return not direct and bool(non_fact)


def _selected_non_fact_roles(response: dict[str, Any]) -> set[str]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    selected = response.get("selected_evidence") or debug.get("selected_evidence") or []
    return {
        str(item.get("evidence_role") or item.get("role") or "").strip().lower()
        for item in selected
        if isinstance(item, dict)
        and str(item.get("evidence_role") or item.get("role") or "").strip().lower()
        in {"service_action", "fallback_only", "media_reference"}
    }


def _validated_review_media_blocks(
    response: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    debug = response.get("evidence_debug")
    if not isinstance(debug, dict):
        return []
    contract = debug.get("media_delivery_contract")
    if not isinstance(contract, dict):
        return []
    attached = [
        item
        for item in contract.get("attached_media") or []
        if isinstance(item, dict)
    ]
    expected_count = int(contract.get("actual_attached_media_count") or 0)
    if (
        contract.get("candidate_source") != "product_context_pack"
        or expected_count < 1
        or expected_count != len(attached)
        or int(contract.get("eligible_asset_count") or 0) < expected_count
    ):
        return []
    valid_contracts = {
        (
            str(item.get("type") or ""),
            str(item.get("asset_type") or ""),
            str(item.get("delivery_candidate_source") or ""),
        )
        for item in attached
        if (
            item.get("type") in {"image", "video"}
            and str(item.get("asset_type") or "")
            and item.get("delivery_candidate_source") == "product_context_pack"
            and str(item.get("review_status") or "").lower() == "approved"
            and item.get("review_approved") is True
            and item.get("usable_for_agent") is True
            and item.get("identity_present") is True
            and item.get("identity_matched") is True
            and item.get("role_matched") is True
        )
    }
    if len(valid_contracts) != expected_count:
        return []
    return [
        item
        for item in blocks
        if (
            item.get("type") in {"image", "video"}
            and bool(str(item.get("url") or item.get("asset_url") or "").strip())
            and str(item.get("status") or item.get("review_status") or "").lower()
            == "approved"
            and item.get("usable_for_agent") in {True, 1}
            and bool(item.get("product_id") or item.get("i_id") or item.get("sku_code"))
            and (
                str(item.get("type") or ""),
                str(item.get("asset_type") or ""),
                str(item.get("delivery_candidate_source") or ""),
            )
            in valid_contracts
        )
    ]


def _apply_formal_delivery_boundary(response: dict[str, Any]) -> None:
    """Prevent non-factual guidance from becoming a delivery decision."""
    if not _formal_non_fact_only(response):
        return
    blocks = [item for item in (response.get("reply_blocks") or []) if isinstance(item, dict)]
    media_blocks = [item for item in blocks if item.get("type") in {"image", "video"}]
    validated_media = _validated_review_media_blocks(response, blocks)
    response["reply_blocks"] = [
        item
        for item in blocks
        if item.get("type") not in {"image", "video"} or item in validated_media
    ]
    removed = [item for item in media_blocks if item not in validated_media]
    response["can_send"] = False
    response["requires_human_review"] = True
    response["sendable_reply"] = ""
    response["reply_status"] = "needs_human_review"
    delivery = response.get("reply_delivery")
    if isinstance(delivery, dict):
        delivery["auto_send_ready"] = False
        delivery["reason"] = (
            "formal_non_fact_media_review_only"
            if validated_media
            else "formal_non_fact_evidence_only"
        )
    debug = response.setdefault("evidence_debug", {})
    selected_non_fact_roles = _selected_non_fact_roles(response)
    debug["formal_delivery_contract"] = {
        "non_fact_only": True,
        "service_action_used_for_fact": bool(selected_non_fact_roles & {"service_action", "fallback_only"}),
        "media_reference_used_for_fact": "media_reference" in selected_non_fact_roles,
        "removed_media_block_count": len(removed),
        "actual_attached_media_count": len(validated_media),
        "validated_media_review_only": bool(validated_media),
        "can_send_source": "formal_non_fact_evidence_only",
        "requires_human_review_source": "formal_non_fact_evidence_only",
    }


def _apply_formal_partial_answer(response: dict[str, Any]) -> dict[str, Any]:
    """Promote only a bounded, already-admitted partial preview.

    This path is opt-in and keeps delivery blocked.  It is deliberately not a
    second generator: each retained clause already carries the admitted
    evidence UID from Claim Resolution.
    """
    if not _formal_evidence_convergence_enabled():
        return response
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    preview = debug.get("supervisor_candidate_preview")
    if not isinstance(preview, dict):
        return response
    safety = preview.get("safety_validation") if isinstance(preview.get("safety_validation"), dict) else {}
    confirmed = [item for item in (preview.get("confirmed_clauses") or []) if isinstance(item, dict)]
    pending = [item for item in (preview.get("pending_clauses") or []) if isinstance(item, dict)]
    conflicting = [item for item in (preview.get("conflicting_clauses") or []) if isinstance(item, dict)]
    text = str(preview.get("candidate_text") or "").strip()
    if not (text and confirmed and (pending or conflicting) and safety.get("passed") is True):
        return response
    response["suggested_reply"] = text
    response["can_send"] = False
    response["requires_human_review"] = True
    response["sendable_reply"] = ""
    response["reply_status"] = "needs_human_review"
    response["generation_mode"] = "formal_partial_answer_composer"
    response["answer_mode"] = "formal_partial_evidence_answer"
    debug["formal_partial_answer"] = {
        "preserve_no_evidence_policy": True,
        "candidate_text": text,
        "supported_clauses": confirmed,
        "unresolved_clauses": pending,
        "conflicting_clauses": conflicting,
        "evidence_uids": list(preview.get("evidence_uids") or []),
    }
    response["evidence_debug"] = debug
    return response


def _restore_formal_partial_if_lost(response: dict[str, Any]) -> None:
    """Keep an admitted partial answer intact when a stylistic pass drops it."""
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    partial = debug.get("formal_partial_answer") if isinstance(debug.get("formal_partial_answer"), dict) else {}
    candidate = str(partial.get("candidate_text") or "").strip()
    supported = [item for item in (partial.get("supported_clauses") or []) if isinstance(item, dict)]
    unresolved = [
        item for item in [*(partial.get("unresolved_clauses") or []), *(partial.get("conflicting_clauses") or [])]
        if isinstance(item, dict)
    ]
    current = str(response.get("suggested_reply") or "")
    required = [
        str(item.get("customer_facing_clause") or "").strip()
        for item in [*supported, *unresolved]
        if str(item.get("customer_facing_clause") or "").strip()
    ]
    if candidate and required and not all(clause in current for clause in required):
        response["suggested_reply"] = candidate
        debug["formal_partial_clause_restore"] = {
            "reason": "stylistic_transform_dropped_claim_clause",
            "evidence_uids": list(partial.get("evidence_uids") or []),
        }
        response["evidence_debug"] = debug


def _apply_sendable_reply_contract(response: dict[str, Any], *, post_issues: list[str]) -> None:
    draft_reply = str(response.get("suggested_reply") or "")
    final_answer = response.get("final_answer_audit") or {}
    semantic_fit = response.get("final_semantic_fit_audit") or {}
    block_reasons: list[str] = []
    upstream_status = str(response.get("reply_status") or "").strip().lower()
    if upstream_status in {"blocked", "needs_human_review"}:
        block_reasons.append(
            "upstream_reply_blocked" if upstream_status == "blocked" else "upstream_human_review_required"
        )
    if not bool(final_answer.get("passed", True)):
        block_reasons.extend(str(item) for item in (final_answer.get("issues") or []))
        if final_answer.get("reason"):
            block_reasons.append(str(final_answer.get("reason")))
    if not bool(semantic_fit.get("passed", True)):
        block_reasons.extend(str(item) for item in (semantic_fit.get("issues") or []))
        if semantic_fit.get("reason"):
            block_reasons.append(str(semantic_fit.get("reason")))
    block_reasons.extend(str(item) for item in (post_issues or []))
    formal_review_reasons = _formal_review_reasons(response)
    block_reasons.extend(formal_review_reasons)
    if response.get("requires_human_review"):
        block_reasons.append(str(response.get("reason_for_review") or response.get("review_reason") or "requires_human_review"))
    block_reasons = [item for item in dict.fromkeys(block_reasons) if item]
    if not draft_reply:
        block_reasons.append("empty_reply")
    requires_human_review = bool(response.get("requires_human_review")) or bool(block_reasons)
    can_send = bool(draft_reply) and not block_reasons and not requires_human_review
    response["draft_reply"] = draft_reply
    response["can_send"] = can_send
    response["requires_human_review"] = requires_human_review
    response["reply_status"] = "sendable" if can_send else "needs_human_review"
    response["sendable_reply"] = draft_reply if can_send else ""
    response["block_reasons"] = block_reasons
    if not can_send:
        for block in response.get("reply_blocks") or []:
            if isinstance(block, dict) and block.get("type") in {"image", "video"}:
                block["send_mode"] = "manual"
    delivery = response.get("reply_delivery")
    if isinstance(delivery, dict):
        delivery["auto_send_ready"] = _media_delivery_ready(response) and can_send
        if not can_send:
            delivery["reason"] = "final_sendable_contract_blocked"
        elif delivery["auto_send_ready"]:
            delivery["reason"] = ""
        response["reply_delivery"] = delivery
    debug = response.setdefault("evidence_debug", {})
    debug["sendable_reply_contract"] = {
        "can_send": can_send,
        "reply_status": response["reply_status"],
        "block_reasons": block_reasons,
        "can_send_source": "final_sendable_contract",
        "requires_human_review_source": (
            "final_sendable_contract" if requires_human_review else "none"
        ),
    }
    formal_delivery = debug.setdefault("formal_delivery_contract", {})
    selected_non_fact_roles = _selected_non_fact_roles(response)
    formal_delivery["service_action_used_for_fact"] = bool(
        selected_non_fact_roles & {"service_action", "fallback_only"}
    )
    formal_delivery["media_reference_used_for_fact"] = "media_reference" in selected_non_fact_roles
    formal_delivery["actual_attached_media_count"] = sum(
        1
        for block in response.get("reply_blocks") or []
        if isinstance(block, dict) and block.get("type") in {"image", "video"}
    )
    formal_delivery["final_can_send"] = can_send
    formal_delivery["final_requires_human_review"] = requires_human_review


def _formal_review_reasons(response: dict[str, Any]) -> list[str]:
    if not _formal_evidence_convergence_enabled():
        return []
    admitted = _formal_admitted_context(response)
    reasons: list[str] = []
    if _formal_non_fact_only(response):
        reasons.append("formal_non_fact_evidence_only")
    if _selected_non_fact_roles(response):
        reasons.append("formal_non_fact_selected_as_fact")
    unresolved = [
        item
        for item in (admitted.get("unresolved_claims") or [])
        if isinstance(item, dict)
    ]
    if any(
        str(item.get("risk_level") or "").strip().lower() in {"high", "critical"}
        or item.get("direct_handling_prohibited") is True
        or str(item.get("status") or "").strip().lower() == "prohibited"
        for item in unresolved
    ):
        reasons.append("formal_high_risk_claim_unresolved")
    return reasons


def _is_no_evidence_controlled_response(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    mode = str(debug.get("answer_mode") or response.get("answer_mode") or "")
    if mode in {"no_evidence_controlled_reply", "no_evidence_clarification"}:
        return True
    if response.get("generation_mode") == "no_evidence_reply_policy":
        return True
    trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    return bool(trace.get("no_evidence_reply_policy") or debug.get("no_evidence_reply_policy"))


def _mark_no_evidence_final_answer_audit_passed(response: dict[str, Any]) -> None:
    audit = {
        "checked": True,
        "passed": True,
        "issues": [],
        "expected_topics": (response.get("final_answer_audit") or {}).get("expected_topics", []),
        "reply_topics": (response.get("final_answer_audit") or {}).get("reply_topics", []),
        "mode": "no_evidence_controlled_reply",
        "no_evidence_controlled_accepted": True,
    }
    response["final_answer_audit"] = audit
    response.setdefault("evidence_debug", {})["final_answer_audit"] = audit


def _media_delivery_ready(response: dict[str, Any]) -> bool:
    from app.services.media_asset_service import is_delivery_media_asset_eligible

    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    fact_type = str(response.get("query_fact_type") or debug.get("query_fact_type") or "")
    context = response.get("context_used") if isinstance(response.get("context_used"), dict) else {}
    pack = context.get("product_context_pack") if isinstance(context.get("product_context_pack"), dict) else {}
    pack_identity = pack.get("identity") if isinstance(pack.get("identity"), dict) else {}
    identity = {
        "product_id": response.get("product_id") or pack_identity.get("product_id"),
        "i_id": response.get("i_id") or pack_identity.get("i_id"),
        "sku_code": response.get("sku_code") or pack_identity.get("sku_code") or pack_identity.get("sku"),
    }
    media_block_urls: set[str] = set()
    for block in response.get("reply_blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {"image", "video"}:
            continue
        url = str(block.get("url") or "").strip()
        if not url:
            continue
        if block.get("send_mode") not in ("", None, "auto_when_platform_connected"):
            continue
        if not is_delivery_media_asset_eligible(
            block,
            query_fact_type=fact_type,
            product_identity=identity,
        ):
            continue
        media_block_urls.add(_canonical_media_url(url))
    if not media_block_urls:
        return False

    auto_asset_urls: set[str] = set()
    for asset in response.get("recommended_assets") or []:
        if not isinstance(asset, dict):
            continue
        url = str(asset.get("asset_url") or asset.get("url") or "").strip()
        if not url:
            continue
        if str(asset.get("auto_send_level") or "auto").lower() != "auto":
            continue
        if not is_delivery_media_asset_eligible(
            asset,
            query_fact_type=fact_type,
            product_identity=identity,
        ):
            continue
        auto_asset_urls.add(_canonical_media_url(url))
    return bool(media_block_urls & auto_asset_urls)


def _canonical_media_url(url: str) -> str:
    return str(url or "").split("?", 1)[0].strip().lower()


def ensure_sendable_reply_contract(response: dict[str, Any]) -> dict[str, Any]:
    """Ensure legacy graph/API results expose a conservative sendable contract."""
    response = dict(response or {})
    response["draft_reply"] = str(response.get("draft_reply") or response.get("suggested_reply") or "")
    requested_can_send = bool(response.get("can_send"))
    response["sendable_reply"] = str(response.get("sendable_reply") or "")
    reasons = response.get("block_reasons")
    if not isinstance(reasons, list):
        reasons = []
    if not reasons and response.get("requires_human_review"):
        reasons.append(str(response.get("reason_for_review") or response.get("review_reason") or "requires_human_review"))
    if not reasons and response.get("suggested_reply") and not requested_can_send:
        reasons.append("sendable_contract_missing")
    response["block_reasons"] = [str(item) for item in reasons if str(item)]
    can_send = requested_can_send and bool(response["sendable_reply"]) and not response["block_reasons"] and not response.get("requires_human_review")
    if requested_can_send and not can_send:
        response["block_reasons"] = response["block_reasons"] or ["sendable_contract_invalid"]
    if not can_send:
        response["sendable_reply"] = ""
    response["can_send"] = can_send
    response["reply_status"] = "sendable" if can_send else (
        "needs_human_review" if response.get("requires_human_review") else "blocked"
    )
    evidence_debug = response.get("evidence_debug")
    if not isinstance(evidence_debug, dict):
        evidence_debug = {}
        response["evidence_debug"] = evidence_debug
    evidence_debug["sendable_reply_contract"] = {
        "can_send": bool(response.get("can_send")),
        "reply_status": response.get("reply_status", "blocked"),
        "block_reasons": response.get("block_reasons", []),
    }
    return response


def _post_polish_redline_issues(reply: str) -> list[str]:
    issues: list[str] = []
    lowered = reply.lower()
    leaked = [term for term in _POST_POLISH_INTERNAL_TERMS if term.lower() in lowered]
    if leaked:
        issues.append("internal_language:" + ",".join(leaked[:5]))
    unsafe_terms = unsafe_promise_terms(reply)
    if unsafe_terms:
        issues.append("unsafe_promise:" + ",".join(unsafe_terms[:5]))
    return issues


def _optional_llm_language_polish(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, str] | None:
    if not config.COPILOT_FINAL_POLISH_LLM_ENABLED:
        return None
    reply = str(response.get("suggested_reply") or "").strip()
    if not reply:
        return None
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        if not client.api_key:
            return None

        evidence_debug = response.get("evidence_debug") or {}
        payload = {
            "customer_message": customer_message,
            "draft_reply": reply,
            "intent": response.get("intent", ""),
            "risk_level": response.get("risk_level", ""),
            "requires_human_review": response.get("requires_human_review", False),
            "query_fact_type": evidence_debug.get("query_fact_type", ""),
            "display_product_name": response.get("display_product_name", ""),
            "conversation_context": copilot_context,
            "selected_evidence_summary": {
                "evidence_used": response.get("evidence_used", ""),
                "generic_service_rule_used": response.get("generic_service_rule_used", {}),
                "final_answer_audit": response.get("final_answer_audit", {}),
            },
            "reply_blocks": response.get("reply_blocks", []),
            "recommended_assets": response.get("recommended_assets", []),
        }
        result = client.create_chat_completion(
            model=client.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 INHE 母婴儿童用品店铺的金牌客服语言专家。"
                        "你只负责把 draft_reply 改写成自然、专业、可直接发给客户的话。"
                        "禁止新增事实、禁止编造尺寸/材质/承重/优惠/物流，禁止改变是否需要人工跟进的业务决定。"
                        "如果 draft_reply 表示需要跟进，就把它改写成客户能接受的服务话术，不要说系统、资料库、RAG、已审核资料、fact_type。"
                        "只有 reply_blocks 中实际附带的素材才能提及；只附图片就说图片，只附视频就说视频，不能把单一素材说成图片和视频。"
                        "recommended_assets 只是候选，不能据此承诺已经发送素材；不要把链接当正文发。"
                        "不要输出思考过程。只输出 JSON: {\"reply\": string, \"reason\": string}。"
                    ),
                },
                {"role": "user", "content": _json_dumps(payload)},
            ],
            temperature=0.2,
            max_tokens=420,
            response_format={"type": "json_object"},
        )
        parsed = _json_loads(result.choices[0].message.content)
        polished = str(parsed.get("reply") or "").strip()
        if not polished:
            return None
        if _post_polish_redline_issues(polished):
            return None
        if not _preserves_customer_product_name(reply, polished, response):
            return None
        return {
            "reply": polished,
            "reason": str(parsed.get("reason") or "")[:200],
        }
    except Exception:
        return None


def _safe_post_polish_fallback(response: dict[str, Any]) -> str:
    if str(response.get("intent") or "").lower() in {"complaint", "high_risk"}:
        return (
            "亲～非常抱歉让您有不好的体验，您的反馈我已经收到，会优先帮您跟进处理。\n"
            "我这边会按当前情况继续核对并推进处理，尽快给您明确回复。"
        )
    return (
        "亲～这个问题我已经记下来了，我这边继续帮您跟进处理，"
        "确认好后尽快回复您。"
    )


def _preserves_customer_product_name(
    original_reply: str,
    polished_reply: str,
    response: dict[str, Any],
) -> bool:
    display_name = str(response.get("display_product_name") or "").strip()
    if not display_name or len(display_name) < 4:
        return True
    if display_name not in original_reply:
        return True
    return display_name in polished_reply


def _preserves_current_product_anchor(original_reply: str, polished_reply: str) -> bool:
    """Keep scoped product verification from becoming an unscoped handoff."""
    anchor_terms = (
        "当前这款",
        "按当前这款",
        "按当前商品",
        "这款商品",
        "按这款",
        "按您这款",
        "您这款",
        "这款「",
    )
    context_terms = (
        "安装", "结构", "配件", "资料", "尺寸", "材质", "承重",
        "优惠", "活动", "售后", "核对",
    )
    original = str(original_reply or "")
    if not any(term in original for term in anchor_terms):
        return True
    if not any(term in original for term in context_terms):
        return True
    polished = str(polished_reply or "")
    return any(term in polished for term in anchor_terms)


def _sync_text_reply_block(response: dict[str, Any]) -> None:
    blocks = response.get("reply_blocks")
    reply = str(response.get("suggested_reply") or "")
    if not isinstance(blocks, list) or not blocks:
        response["reply_blocks"] = [{"type": "text", "content": reply}]
        return
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            block["content"] = reply
            return
    response["reply_blocks"] = [{"type": "text", "content": reply}] + blocks


def _append_reason(existing: str, reason: str) -> str:
    if not existing:
        return reason
    if reason in existing:
        return existing
    return f"{existing}；{reason}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str) -> dict[str, Any]:
    parsed = json.loads(str(value or "{}"))
    return parsed if isinstance(parsed, dict) else {}
