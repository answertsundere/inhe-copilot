"""Qualify an explicit Composer role across five profiles and five attempts per profile.

This evaluation-only command never enables a role, changes a feature flag,
uses formal knowledge, or changes a customer reply or ``can_send``.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

from app.api.runtime_routes import _source_tree_sha256  # noqa: E402
from app import config  # noqa: E402
from app.llm.client import (  # noqa: E402
    ComposerRoleConfigurationError,
    composer_role_configuration_fingerprint,
    get_composer_llm_client,
)
from app.services.model_first_answer_composer_service import (  # noqa: E402
    ModelFirstAnswerComposerService,
)
from app.services.strict_decision_provider_service import (  # noqa: E402
    safe_provider_identity,
)


REPORT_SCHEMA_VERSION = "composer-role-qualification/v5"
_FIXTURE_PACK_SHA256 = hashlib.sha256(
    b"composer-role-qualification-fixture-v5"
).hexdigest()
_QUALIFICATION_CUSTOMER_MESSAGE = (
    "请说明这款商品已确认的材质，并给出日常轻微碰撞的有边界判断，"
    "对于长期耐用程度，没有直接依据时请保留未决，且不要作绝对保证。"
)
_UNRESOLVED_ONLY_CUSTOMER_MESSAGE = (
    "不能作绝对保证时，请分别说明保证边界和当前无法确认的日常使用限度。"
)
_HISTORY_FACT_CUSTOMER_MESSAGE = (
    "不能保证耐用程度时，请只说明当前能确认的边界。"
)
_UNADMITTED_HISTORY_FACT_MARKER = "合成材质甲"
_ATTACHED_MEDIA_CUSTOMER_MESSAGE = (
    "请说明当前能否拆洗，并把对应的安装视频附在本次回复里。"
)
_SERVICE_ACTION_CUSTOMER_MESSAGE = (
    "请继续处理退款或换货，需要我提供什么信息？"
)


class _ComposerClient(Protocol):
    api_key: str
    api_base: str
    model: str

    def create_chat_completion(self, **kwargs: Any) -> Any: ...


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _goal(
    goal_ref: str,
    *,
    claim_type: str,
    attribute_key: str,
    source_text: str,
    customer_message: str = _QUALIFICATION_CUSTOMER_MESSAGE,
    claim_type_status: str = "mapped",
    semantic_key: str = "",
) -> dict[str, Any]:
    span_start = customer_message.index(source_text)
    span_end = span_start + len(source_text)
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    return {
        "schema_version": "turn-understanding-goal-identity/v2",
        "goal_ref": goal_ref,
        "goal_kind": "customer_goal",
        "claim_type_status": claim_type_status,
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "semantic_key": semantic_key or attribute_key,
        "goal_summary": "合成资格目标",
        "source": "current_customer_message",
        "source_span_start": span_start,
        "source_span_end": span_end,
        "source_span_sha256": source_hash,
        "source_text_sha256": source_hash,
        "source_turn_uid": "qualification-current-turn",
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "supporting_only": False,
        "supporting_for_goal_ref": "",
        "customer_goal_eligible": True,
    }


def qualification_response() -> dict[str, Any]:
    """Return an isolated fact-plus-bounded-inference Composer input."""
    policy_ref = (
        "domain-policy:qualification@1.0.0:"
        "intent:ordinary-impact-guidance"
    )
    boundary = {
        "schema_version": "restricted-request-boundary/v1",
        "status": "prohibited",
        "reason_code": "absolute_guarantee_prohibited",
        "requested_claim_risk": "high",
        "policy_intent_ref": "absolute_guarantee",
        "policy_goal_family": "ordinary_impact",
        "policy_intent_kind": "absolute_guarantee",
        "high_risk_claim_families": [],
        "must_remain_unresolved": True,
        "allows_bounded_alternative": True,
    }
    option = {
        "policy_ref": policy_ref,
        "trusted_domain_pack_ref": "domain-policy:qualification@1.0.0",
        "pack_content_sha256": _FIXTURE_PACK_SHA256,
        "applicable_goal_ref": "goal-durability",
        "policy_intent_ref": "ordinary-impact-guidance",
        "goal_family": "ordinary_impact",
        "intent_kind": "practical_guidance",
        "premise_evidence_refs": ["evidence-material"],
        "premise_families": ["material_composition"],
        "allowed_scope": "ordinary_minor_accidental_impact",
        "allowed_conclusion_family": "ordinary_minor_impact_tolerance",
        "allowed_variability_factor_families": [],
        "advice_mode": "none",
        "forbidden_claim_families": ["certification", "safety", "warranty"],
        "maximum_risk": "medium",
        "requested_risk": "high",
        "requested_claim_risk": "high",
        "answer_strategy_risk": "medium",
        "required_qualifiers": ["no_absolute_guarantee"],
        "review_only": True,
        "used_for_evidence": False,
        "used_for_fact_support": False,
        "can_change_can_send": False,
        "restricted_request_boundary": boundary,
        "option_provenance": {
            "policy_owner": "domain_policy_pack",
            "filter_owner": "claim_resolution",
            "premise_owner": "admitted_answer_context",
            "intent_narrowed": False,
            "alternative_for_restricted_request": True,
        },
    }
    material_resolution = {
        "claim_uid": "claim-material",
        "goal_ref": "goal-material",
        "goal_kind": "customer_goal",
        "claim_type": "material_composition",
        "claim_type_status": "mapped",
        "attribute_key": "material",
        "status": "supported",
        "evidence_uids": ["evidence-material"],
        "support_basis": "direct_evidence",
        "premise_evidence_uids": [],
        "inference_policy_refs": [],
        "scope_qualifier": "",
        "inference_risk_level": "",
        "maximum_risk_level": "",
        "inference_review_only": False,
        "required_qualifiers": [],
        "prohibited_extensions": [],
        "eligible_policy_options": [],
        "supporting_only": False,
        "supporting_for_goal_ref": "",
    }
    durability_resolution = {
        "claim_uid": "claim-durability",
        "goal_ref": "goal-durability",
        "goal_kind": "customer_goal",
        "claim_type": "ordinary_impact",
        "claim_type_status": "mapped",
        "attribute_key": "ordinary_impact",
        "status": "unresolved",
        "evidence_uids": [],
        "support_basis": "bounded_inference",
        "premise_evidence_uids": ["evidence-material"],
        "inference_policy_refs": [policy_ref],
        "scope_qualifier": "ordinary_minor_accidental_impact",
        "inference_risk_level": "medium",
        "maximum_risk_level": "medium",
        "inference_review_only": True,
        "required_qualifiers": ["no_absolute_guarantee"],
        "prohibited_extensions": [],
        "eligible_policy_options": [option],
        "requested_claim_risk": "high",
        "restricted_request_boundary": boundary,
        "supporting_only": False,
        "supporting_for_goal_ref": "",
    }
    unresolved_resolution = _unresolved_resolution(
        "goal-long-term-limit",
        semantic_key="long_term_durability_limit",
        requested_claim_risk="medium",
    )
    return {
        "suggested_reply": "prior reply",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "prior reply"}],
        "minimal_decision_context": {
            "customer_goal": _QUALIFICATION_CUSTOMER_MESSAGE,
            "product_identity": {"resolved": True},
            "requested_claims": [
                _goal(
                    "goal-material",
                    claim_type="material_composition",
                    attribute_key="material",
                    source_text="已确认的材质",
                ),
                _goal(
                    "goal-durability",
                    claim_type="ordinary_impact",
                    attribute_key="ordinary_impact",
                    source_text="日常轻微碰撞的有边界判断",
                ),
                _goal(
                    "goal-long-term-limit",
                    claim_type="",
                    attribute_key="",
                    source_text="长期耐用程度",
                    claim_type_status="unmapped",
                    semantic_key="long_term_durability_limit",
                ),
            ],
            "admitted_evidence": [{
                "evidence_uid": "evidence-material",
                "fact_type": "material_composition",
                "attribute_key": "material",
                "content": "已确认的合成材质前提",
            }],
            "claim_resolutions": [
                material_resolution,
                durability_resolution,
                unresolved_resolution,
            ],
            "bounded_inference_policies": [{
                "policy_ref": policy_ref,
                "pack_content_sha256": _FIXTURE_PACK_SHA256,
                "policy_intent_ref": "ordinary-impact-guidance",
                "goal_family": "ordinary_impact",
                "intent_kind": "practical_guidance",
                "premise_fact_families": ["material_composition"],
                "allowed_scope": "ordinary_minor_accidental_impact",
                "allowed_conclusion_family": "ordinary_minor_impact_tolerance",
                "allowed_variability_factor_families": [],
                "advice_mode": "none",
                "maximum_risk_level": "medium",
                "required_qualifiers": ["no_absolute_guarantee"],
                "prohibited_claim_families": ["certification", "safety", "warranty"],
                "review_only": True,
                "used_for_evidence": False,
                "used_for_fact_support": False,
                "can_change_can_send": False,
            }],
            "trusted_domain_policy_context": {
                "schema_version": "trusted-domain-policy-context/v1",
                "status": "selected",
                "trusted_owner": "analysis_pipeline",
                "selection_source": "evaluation_fixture",
                "pack_ref": "domain-policy:qualification@1.0.0",
                "pack_schema_version": "domain-policy-pack/v1",
                "pack_content_sha256": _FIXTURE_PACK_SHA256,
                "domain_ref": "qualification-domain",
                "binding_summary": {"tenant": False, "store": False, "catalog": True},
                "provenance": {
                    "boundary": "analysis_pipeline_internal",
                    "selector_owner": "file_policy_repository",
                },
                "selected_at_stage": "canonical_input",
                "validation_reasons": [],
                "used_for_evidence": False,
                "used_for_fact_support": False,
                "can_change_can_send": False,
            },
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 50},
        },
    }


def _unresolved_resolution(
    goal_ref: str,
    *,
    semantic_key: str,
    requested_claim_risk: str,
) -> dict[str, Any]:
    return {
        "claim_uid": f"claim-{goal_ref}",
        "goal_ref": goal_ref,
        "goal_kind": "customer_goal",
        "claim_type": "",
        "claim_type_status": "unmapped",
        "attribute_key": "",
        "semantic_key": semantic_key,
        "status": "unresolved",
        "evidence_uids": [],
        "support_basis": "none",
        "premise_evidence_uids": [],
        "inference_policy_refs": [],
        "scope_qualifier": "",
        "inference_risk_level": "",
        "maximum_risk_level": "",
        "inference_review_only": False,
        "required_qualifiers": [],
        "prohibited_extensions": [],
        "eligible_policy_options": [],
        "requested_claim_risk": requested_claim_risk,
        "restricted_request_boundary": {},
        "supporting_only": False,
        "supporting_for_goal_ref": "",
    }


def unresolved_only_qualification_response() -> dict[str, Any]:
    goals = [
        _goal(
            "goal-guarantee-boundary",
            claim_type="",
            attribute_key="",
            source_text="不能作绝对保证",
            customer_message=_UNRESOLVED_ONLY_CUSTOMER_MESSAGE,
            claim_type_status="unmapped",
            semantic_key="absolute_guarantee_boundary",
        ),
        _goal(
            "goal-daily-use-limit",
            claim_type="",
            attribute_key="",
            source_text="当前无法确认的日常使用限度",
            customer_message=_UNRESOLVED_ONLY_CUSTOMER_MESSAGE,
            claim_type_status="unmapped",
            semantic_key="daily_use_limit",
        ),
    ]
    resolutions = [
        _unresolved_resolution(
            "goal-guarantee-boundary",
            semantic_key="absolute_guarantee_boundary",
            requested_claim_risk="high",
        ),
        _unresolved_resolution(
            "goal-daily-use-limit",
            semantic_key="daily_use_limit",
            requested_claim_risk="medium",
        ),
    ]
    return {
        "suggested_reply": "prior reply",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "prior reply"}],
        "minimal_decision_context": {
            "customer_goal": _UNRESOLVED_ONLY_CUSTOMER_MESSAGE,
            "product_identity": {"resolved": True},
            "requested_claims": goals,
            "admitted_evidence": [],
            "claim_resolutions": resolutions,
            "bounded_inference_policies": [],
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 30},
        },
    }


def unadmitted_history_fact_qualification_response() -> dict[str, Any]:
    goal = _goal(
        "goal-history-boundary",
        claim_type="",
        attribute_key="",
        source_text=_HISTORY_FACT_CUSTOMER_MESSAGE,
        customer_message=_HISTORY_FACT_CUSTOMER_MESSAGE,
        claim_type_status="unmapped",
        semantic_key="ordinary_use_durability_assessment",
    )
    return {
        "suggested_reply": "prior reply",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "prior reply"}],
        "minimal_decision_context": {
            "customer_goal": _HISTORY_FACT_CUSTOMER_MESSAGE,
            "recent_conversation_turns": [{
                "role": "customer",
                "content": (
                    "商品资料里写的是"
                    f"{_UNADMITTED_HISTORY_FACT_MARKER}。"
                ),
                "turn_index": 1,
            }],
            "product_identity": {"resolved": True},
            "requested_claims": [goal],
            "admitted_evidence": [],
            "claim_resolutions": [_unresolved_resolution(
                "goal-history-boundary",
                semantic_key="ordinary_use_durability_assessment",
                requested_claim_risk="medium",
            )],
            "bounded_inference_policies": [],
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 40},
        },
    }


def attached_media_request_qualification_response() -> dict[str, Any]:
    detachable_goal = _goal(
        "goal-detachable",
        claim_type="",
        attribute_key="",
        source_text="当前能否拆洗",
        customer_message=_ATTACHED_MEDIA_CUSTOMER_MESSAGE,
        claim_type_status="unmapped",
        semantic_key="detachable",
    )
    media_goal = _goal(
        "goal-installation-video",
        claim_type="",
        attribute_key="",
        source_text="安装视频",
        customer_message=_ATTACHED_MEDIA_CUSTOMER_MESSAGE,
        claim_type_status="unmapped",
        semantic_key="installation_video",
    )
    media_goal.update({
        "goal_kind": "media_request",
        "customer_goal_eligible": False,
    })
    return {
        "suggested_reply": "prior reply",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [
            {"type": "text", "content": "prior reply"},
            {
                "type": "video",
                "url": "https://static.invalid/qualification-video.mp4",
                "asset_type": "install_video",
                "status": "approved",
                "usable_for_agent": True,
            },
        ],
        "minimal_decision_context": {
            "customer_goal": _ATTACHED_MEDIA_CUSTOMER_MESSAGE,
            "product_identity": {"resolved": True},
            "requested_claims": [detachable_goal, media_goal],
            "admitted_evidence": [],
            "claim_resolutions": [_unresolved_resolution(
                "goal-detachable",
                semantic_key="detachable",
                requested_claim_risk="low",
            )],
            "bounded_inference_policies": [],
            "media_candidates": [{
                "evidence_uid": "qualification-install-video",
                "asset_type": "install_video",
                "media_role": "installation_video",
                "non_fact": True,
            }],
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 35},
        },
    }


def customer_input_service_action_qualification_response() -> dict[str, Any]:
    goal = _goal(
        "goal-aftersales-outcome",
        claim_type="",
        attribute_key="",
        source_text="退款或换货",
        customer_message=_SERVICE_ACTION_CUSTOMER_MESSAGE,
        claim_type_status="unmapped",
        semantic_key="aftersales_outcome",
    )
    return {
        "suggested_reply": "prior reply",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "prior reply"}],
        "minimal_decision_context": {
            "customer_goal": _SERVICE_ACTION_CUSTOMER_MESSAGE,
            "product_identity": {"resolved": True},
            "requested_claims": [goal],
            "admitted_evidence": [],
            "claim_resolutions": [_unresolved_resolution(
                "goal-aftersales-outcome",
                semantic_key="aftersales_outcome",
                requested_claim_risk="medium",
            )],
            "bounded_inference_policies": [],
            "service_actions": [{
                "action_type": "request_customer_input",
                "accepted_input_slots": ["order_id", "tracking_no"],
                "input_selection_mode": "any_of",
                "source_owner": "response_strategy_planner",
                "non_fact": True,
                "completed": False,
                "can_change_can_send": False,
            }],
            "answer_eligibility_context": {
                "goal_understanding_status": {"status": "valid"},
            },
            "context_stats": {"estimated_token_count": 35},
        },
    }


def qualification_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "unresolved_only",
            "response": unresolved_only_qualification_response(),
            "forbidden_reply_markers": [],
        },
        {
            "name": "unadmitted_history_fact",
            "response": unadmitted_history_fact_qualification_response(),
            "forbidden_reply_markers": [
                _UNADMITTED_HISTORY_FACT_MARKER,
            ],
        },
        {
            "name": "fact_bounded_and_unresolved",
            "response": qualification_response(),
            "forbidden_reply_markers": [],
        },
        {
            "name": "customer_input_service_action",
            "response": customer_input_service_action_qualification_response(),
            "forbidden_reply_markers": [],
        },
        {
            "name": "attached_media_request",
            "response": attached_media_request_qualification_response(),
            "forbidden_reply_markers": [],
        },
    ]


def _provider_metadata(client: _ComposerClient) -> dict[str, Any]:
    identity = safe_provider_identity(
        provider_name=str(getattr(client, "provider_name", "unknown")),
        api_base=str(getattr(client, "api_base", "")),
        model=str(getattr(client, "model", "")),
    )
    return {**identity, "configured": bool(getattr(client, "api_key", ""))}


def _role_override_requested() -> bool:
    return any(
        str(value or "").strip()
        for value in (
            config.COPILOT_COMPOSER_LLM_API_BASE,
            config.COPILOT_COMPOSER_LLM_API_KEY,
            config.COPILOT_COMPOSER_LLM_MODEL,
        )
    )


def _record(
    *,
    attempt: int,
    profile: str,
    response: dict[str, Any],
    client: _ComposerClient,
    forbidden_reply_markers: list[str] | None = None,
) -> dict[str, Any]:
    service = ModelFirstAnswerComposerService()
    customer_message = str(
        response["minimal_decision_context"]["customer_goal"]
    )
    decision_input, decision_error = service.build_composer_decision_input(
        deepcopy(response),
        customer_message=customer_message,
    )
    if decision_error:
        raise ValueError(decision_error)
    material, material_error = service.build_provider_material_from_decision_input(
        decision_input
    )
    if material_error:
        raise ValueError(material_error)
    expected_order = [
        material["goal_uid_by_ref"][goal_ref]
        for goal_ref in material["partitions"]["presentation_order"]
    ]
    calls = 0
    original_create = client.create_chat_completion

    def counted_create(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original_create(**kwargs)

    client.create_chat_completion = counted_create  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        updated, result = service.compose(
            deepcopy(response),
            customer_message=customer_message,
            client=client,
        )
    finally:
        client.create_chat_completion = original_create  # type: ignore[method-assign]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    clauses = [
        item for item in result.get("clauses") or [] if isinstance(item, dict)
    ]
    diagnostics = result.get("provider_diagnostics") or {}
    validation = result.get("validation_diagnostics") or {}
    inference = [item for item in clauses if item.get("clause_kind") == "allowed_inference"]
    supported = [item for item in clauses if item.get("clause_kind") == "supported_fact"]
    unresolved = [item for item in clauses if item.get("clause_kind") == "unresolved"]
    resolutions = [
        item
        for item in response["minimal_decision_context"]["claim_resolutions"]
        if isinstance(item, dict)
    ]
    expected_supported = sum(
        item.get("status") == "supported" for item in resolutions
    )
    expected_inference = sum(
        bool(item.get("eligible_policy_options")) for item in resolutions
    )
    expected_unresolved = sum(
        item.get("status") in {"unresolved", "conflicting", "prohibited"}
        and not item.get("eligible_policy_options")
        for item in resolutions
    )
    expected_restricted = sum(
        bool(
            (item.get("restricted_request_boundary") or {}).get(
                "must_remain_unresolved"
            )
        )
        for item in resolutions
    )
    expected_media_request_refs = sorted(
        material["media_request_bindings"]
    )
    expected_service_action_refs = sorted(
        material["service_action_bindings"]
    )
    service_action_requests = [
        item
        for item in result.get("service_action_requests") or []
        if isinstance(item, dict)
    ]
    request_by_ref = {
        str(item.get("action_ref") or ""): item
        for item in service_action_requests
        if str(item.get("action_ref") or "")
    }

    def service_action_request_is_valid(action_ref: str) -> bool:
        binding = material["service_action_bindings"].get(action_ref) or {}
        request = request_by_ref.get(action_ref) or {}
        accepted_slots = set(binding.get("accepted_input_slots") or [])
        requested_slots = set(request.get("requested_input_slots") or [])
        mode = str(binding.get("input_selection_mode") or "")
        slots_valid = (
            requested_slots == accepted_slots
            if mode == "all_of"
            else bool(requested_slots) and requested_slots <= accepted_slots
        )
        request_text = str(request.get("text") or "")
        return bool(request_text) and request_text in reply and slots_valid

    reply = str(result.get("candidate_reply") or "")
    forbidden_markers = [
        str(item).strip()
        for item in forbidden_reply_markers or []
        if str(item).strip()
    ]
    prompt_payload_text = json.dumps(
        material["prompt_payload"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    checks = {
        "single_provider_call": calls == 1,
        "accepted": result.get("status") == "accepted",
        "validation_accepted": validation.get("category") == "accepted",
        "goal_order_exact": [item.get("goal_ref") for item in clauses] == expected_order,
        "direct_fact_preserved": len(supported) == expected_supported,
        "required_option_selected": (
            len(inference) == expected_inference
            and all(item.get("inference_policy_refs") for item in inference)
        ),
        "restricted_boundary_preserved": (
            sum(
                bool(
                    (item.get("restricted_request_boundary") or {}).get(
                        "must_remain_unresolved"
                    )
                )
                for item in inference
            )
            == expected_restricted
        ),
        "unresolved_boundary_preserved": (
            len(unresolved) == expected_unresolved
            and all(not item.get("evidence_uids") for item in unresolved)
            and all(
                not item.get("inference_policy_refs")
                for item in unresolved
            )
        ),
        "unadmitted_history_fact_excluded": all(
            marker.casefold() not in reply.casefold()
            for marker in forbidden_markers
        ),
        "unadmitted_history_fact_not_exposed": all(
            marker.casefold() not in prompt_payload_text.casefold()
            for marker in forbidden_markers
        ),
        "required_media_requests_selected": (
            sorted(result.get("selected_media_request_refs") or [])
            == expected_media_request_refs
        ),
        "required_service_actions_rendered": (
            sorted(result.get("selected_service_action_refs") or [])
            == expected_service_action_refs
            and sorted(request_by_ref) == expected_service_action_refs
            and all(
                service_action_request_is_valid(action_ref)
                for action_ref in expected_service_action_refs
            )
        ),
        "no_retry_or_repair": all(
            int(diagnostics.get(name, 0) or 0) == 0
            for name in ("retry_count", "repair_count", "json_repair_count")
        ),
        "can_send_unchanged": updated.get("can_send") is False,
        "human_review_required": updated.get("requires_human_review") is True,
    }
    return {
        "attempt": attempt,
        "profile": profile,
        "qualified": all(checks.values()),
        "checks": checks,
        "status": result.get("status"),
        "rejection_reason": str(result.get("rejection_reason") or ""),
        "validation_category": str(validation.get("category") or ""),
        "provider_call_count": calls,
        "provider_latency_ms": diagnostics.get("provider_latency_ms"),
        "elapsed_ms": elapsed_ms,
        "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
        "clause_projection": [
            {
                "goal_ref": item.get("goal_ref"),
                "clause_kind": item.get("clause_kind"),
                "evidence_uid_count": len(item.get("evidence_uids") or []),
                "policy_ref_count": len(item.get("inference_policy_refs") or []),
            }
            for item in clauses
        ],
    }


def run_qualification(
    *,
    repeat: int = 5,
    client: _ComposerClient | None = None,
) -> tuple[dict[str, Any], int]:
    if repeat != 5:
        raise ValueError("repeat_must_equal_5")
    if client is None and not _role_override_requested():
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "invalid_run",
            "reason": "provider_not_configured",
            "provider": {"configured": False},
            "real_customer_accuracy": None,
        }, 2
    try:
        role_client = client or get_composer_llm_client(allow_unqualified=True)
    except ComposerRoleConfigurationError as exc:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "invalid_run",
            "reason": str(exc),
            "real_customer_accuracy": None,
        }, 2
    metadata = _provider_metadata(role_client)
    if metadata["configured"] is not True:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "invalid_run",
            "reason": "provider_not_configured",
            "provider": metadata,
            "real_customer_accuracy": None,
        }, 2

    profiles = qualification_profiles()
    qualification_fingerprint = composer_role_configuration_fingerprint(
        api_base=str(role_client.api_base or ""),
        model=str(role_client.model or ""),
        timeout_seconds=int(getattr(role_client, "timeout_seconds", 30) or 30),
        transport_thinking=str(
            getattr(role_client, "transport_thinking", "") or ""
        ),
        minimum_output_tokens=int(
            getattr(role_client, "minimum_output_tokens", 0) or 0
        ),
    )
    records: list[dict[str, Any]] = []
    hard_stop_reason = ""
    global_attempt = 0
    for profile in profiles:
        for attempt in range(1, repeat + 1):
            global_attempt += 1
            record = _record(
                attempt=global_attempt,
                profile=str(profile["name"]),
                response=profile["response"],
                client=role_client,
                forbidden_reply_markers=list(
                    profile.get("forbidden_reply_markers") or []
                ),
            )
            records.append(record)
            if not record["qualified"]:
                hard_stop_reason = str(record["rejection_reason"] or next(
                    name
                    for name, passed in record["checks"].items()
                    if not passed
                ))
                break
        if hard_stop_reason:
            break

    latencies = [
        item["provider_latency_ms"]
        for item in records
        if isinstance(item["provider_latency_ms"], (int, float))
    ]
    expected_attempts = repeat * len(profiles)
    qualified = len(records) == expected_attempts and all(
        item["qualified"] for item in records
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "qualified" if qualified else "not_qualified",
        "source_tree_sha256": _source_tree_sha256(),
        "provider": metadata,
        "qualification_fingerprint": qualification_fingerprint,
        "fixture_sha256": _canonical_hash(profiles),
        "profile_count": len(profiles),
        "attempts_per_profile": repeat,
        "attempted": len(records),
        "provider_call_count": sum(int(item["provider_call_count"]) for item in records),
        "retry_count": 0,
        "repair_count": 0,
        "fallback_count": 0,
        "formal_knowledge_read_count": 0,
        "formal_knowledge_dml": 0,
        "gold_loaded": False,
        "can_change_can_send": False,
        "hard_stop_reason": hard_stop_reason,
        "p50_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_ms": max(latencies) if latencies else None,
        "records": records,
        "real_customer_accuracy": None,
    }
    report["report_content_sha256"] = _canonical_hash(report)
    return report, 0 if qualified else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    output = Path(args.json_output)
    if output.exists():
        raise SystemExit("qualification_output_exists")
    try:
        report, exit_code = run_qualification()
    except ValueError as exc:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "invalid_run",
            "reason": str(exc),
            "real_customer_accuracy": None,
        }
        exit_code = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "attempted": report.get("attempted", 0),
        "hard_stop_reason": report.get("hard_stop_reason", ""),
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
