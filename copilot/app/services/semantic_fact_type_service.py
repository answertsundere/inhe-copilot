"""LLM-first semantic classifier for the current customer question.

This module decides what fact field the customer is actually asking for. It is
not a reply generator and it must not choose evidence by keyword alone.
Deterministic rules are kept only as a fallback when the LLM is unavailable or
returns an unusably low-confidence result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from app import config
from app.llm.client import get_llm_client
from app.services.canonical_conversation_turn_service import (
    canonical_current_customer_turn_uid,
)
from app.services.fact_type_service import FACT_TYPE_LABELS, classify_query_fact_type
from app.services.strict_decision_provider_service import safe_provider_identity

logger = logging.getLogger(__name__)


ALLOWED_FACT_TYPES = set(FACT_TYPE_LABELS)

HIGH_RISK_BOUNDARY_TYPES = {
    "certification_report",
    "pinch_safety",
    "safety_small_parts",
    "stability",
    "aftersales_policy",
    "invoice_policy",
    "price_protection",
}

ALLOWED_GOAL_KINDS = {
    "customer_goal",
    "evidence_dependency",
    "service_action",
    "contextual_constraint",
}

ALLOWED_CLAIM_TYPE_STATUSES = {"canonical", "unmapped"}

_LLM_RESULT_FIELDS = {"goals"}

_RAW_GOAL_FIELDS = {
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "attribute_key",
    "semantic_key",
    "policy_intent_ref",
    "source_text",
}
_RAW_GOAL_REQUIRED_FIELDS = _RAW_GOAL_FIELDS - {"semantic_key"}

_CANONICAL_GOAL_FIELDS = {
    "schema_version",
    "goal_ref",
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "claim_type_exact_match",
    "attribute_key",
    "semantic_key",
    "policy_intent_ref",
    "policy_goal_family",
    "policy_intent_kind",
    "goal_summary",
    "confidence",
    "source",
    "source_span_start",
    "source_span_end",
    "source_span_sha256",
    "source_text_sha256",
    "source_turn_uid",
    "owner",
    "source_stage",
    "claim_type_reason_code",
}

_DIAGNOSTICS_SCHEMA_VERSION = "turn-understanding-diagnostics/v4"
MINIMAL_PROVIDER_SCHEMA_VERSION = "turn-understanding-provider-output/v3"
GOAL_IDENTITY_SCHEMA_VERSION = "turn-understanding-goal-identity/v2"
JSON_ENVELOPE_CONTRACT_VERSION = "turn-understanding-json-envelope/v1"
ATOMIC_GOAL_SPAN_CONTRACT_VERSION = "turn-understanding-atomic-goal-span/v2"
SERVER_SPAN_RESOLVER_VERSION = "turn-understanding-server-span-resolver/v1"
UNMAPPED_METADATA_CONTRACT_VERSION = (
    "turn-understanding-unmapped-metadata/v1"
)

MINIMAL_PROVIDER_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goals"],
    "properties": {
        "goals": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_RAW_GOAL_REQUIRED_FIELDS),
                "properties": {
                    "goal_kind": {
                        "type": "string",
                        "enum": sorted(ALLOWED_GOAL_KINDS),
                    },
                    "claim_type_status": {
                        "type": "string",
                        "enum": sorted(ALLOWED_CLAIM_TYPE_STATUSES),
                    },
                    "claim_type": {"type": "string"},
                    "attribute_key": {"type": "string"},
                    "semantic_key": {"type": "string"},
                    "policy_intent_ref": {"type": "string"},
                    "source_text": {"type": "string"},
                },
            },
        },
    },
}
MINIMAL_PROVIDER_OUTPUT_SCHEMA_SHA256 = hashlib.sha256(
    json.dumps(
        MINIMAL_PROVIDER_OUTPUT_SCHEMA,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

_POLICY_INTENT_DESCRIPTIONS = {
    "practical_guidance": (
        "Low-risk practical guidance within the declared scope, without an "
        "absolute guarantee."
    ),
    "absolute_guarantee": (
        "A request for an absolute performance guarantee or an out-of-scope "
        "extreme condition."
    ),
    "test_standard_request": (
        "A request for a test standard, test result, or formal test proof."
    ),
    "warranty_or_liability_request": (
        "A request for warranty, compensation, liability, or another policy "
        "commitment."
    ),
}

SYSTEM_PROMPT = """
You are the Turn Understanding owner for INHE customer-service Copilot.
Identify every explicit atomic need in the current buyer message. Do not answer
the buyer and do not select evidence.

Return exactly one JSON object with the single top-level field "goals". Do not
return Markdown, explanations, owner fields, versions, status summaries,
counts, offsets, hashes, goal references, confidence, or diagnostics.

For each goal:
- goal_kind is exactly one of customer_goal, evidence_dependency,
  service_action, or contextual_constraint.
- A fact needed to support an answer is evidence_dependency unless the buyer
  explicitly asks for that fact.
- claim_type_status is canonical only for an exact semantic match to one
  canonical_fact_type_candidates fact_type_id. Then claim_type is that ID.
- Otherwise claim_type_status is unmapped and claim_type is empty.
- semantic_key is optional, non-authoritative metadata. If included, it is
  either empty or a concise lowercase ASCII identifier. Omit it when no stable
  semantic hint is available. Never invent a placeholder.
- attribute_key is an optional semantic attribute candidate.
- policy_intent_ref is empty or exactly one supplied policy_intent_candidates
  ID. It is a nomination, not an authorization.
- source_text is the smallest continuous exact substring that expresses this
  one goal and occurs exactly once in the current customer_message. Copy it
  verbatim without normalization. Distinct goals must not reuse the same exact
  source fragment.

Return this allowed shape and no additional fields. semantic_key may be
omitted:
{"goals":[{"goal_kind":"","claim_type_status":"","claim_type":"",
"attribute_key":"","semantic_key":"","policy_intent_ref":"",
"source_text":""}]}
"""


def classify_query_fact_type_llm_first(
    state: dict[str, Any],
    *,
    diagnostics_sink: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the current question with LLM as the primary decision maker."""

    message = state.get("normalized_message", state.get("customer_message", "")) or ""
    intent = state.get("intent", "general") or "general"
    deterministic = classify_query_fact_type(message, intent)

    llm_result: dict[str, Any] | None = None
    call_diagnostics = (
        diagnostics_sink
        if isinstance(diagnostics_sink, dict)
        else {}
    )
    if config.COPILOT_FACT_TYPE_LLM_ENABLED:
        llm_result = _classify_with_llm(
            state,
            message,
            intent,
            diagnostics_sink=call_diagnostics,
        )
    failure_reason = str(
        call_diagnostics.get("reason_code") or ""
    ).strip()
    if failure_reason and isinstance(llm_result, dict):
        existing_reasons = llm_result.get(
            "goal_understanding_diagnostics"
        )
        llm_result["goal_understanding_diagnostics"] = list(
            dict.fromkeys([
                *(
                    existing_reasons
                    if isinstance(existing_reasons, list)
                    else []
                ),
                failure_reason,
            ])
        )

    if _is_usable_llm_result(llm_result):
        guarded = _semantic_consistency_guard(deterministic, llm_result)
        if guarded:
            guarded["semantic_query"] = _semantic_query_from_result(guarded, message)
            return guarded
        result = dict(llm_result)
        result["deterministic_hint"] = _compact_hint(deterministic)
        result["semantic_query"] = _semantic_query_from_result(result, message)
        return result

    fallback = _fallback_from_rule(deterministic, llm_result)
    if failure_reason:
        existing_reasons = (
            fallback.get("goal_understanding_diagnostics") or []
        )
        fallback["goal_understanding_diagnostics"] = list(dict.fromkeys([
            failure_reason,
            *(
                existing_reasons
                if isinstance(existing_reasons, list)
                else []
            ),
        ]))
        fallback["customer_goals"] = []
        if _invalidates_authoritative_understanding(call_diagnostics):
            fallback["goal_understanding_status"] = "invalid"
    fallback["semantic_query"] = _semantic_query_from_result(fallback, message)
    return fallback


def _is_usable_llm_result(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    return (
        result.get("goal_understanding_status") == "valid"
        and bool(result.get("customer_goals"))
    )


def _fallback_from_rule(deterministic: dict[str, Any], llm_result: dict[str, Any] | None) -> dict[str, Any]:
    fallback = dict(deterministic or {})
    fallback["source"] = "rule_fallback"
    fallback["fallback_reason"] = "llm_unavailable_or_low_confidence"
    if llm_result:
        fallback["llm_low_confidence_result"] = {
            "query_fact_type": llm_result.get("query_fact_type", ""),
            "confidence": llm_result.get("confidence", 0),
            "reason": llm_result.get("reason", ""),
        }
    fact_type = str(fallback.get("query_fact_type") or "")
    if fact_type in HIGH_RISK_BOUNDARY_TYPES:
        fallback["risk_hint"] = fallback.get("risk_hint") or "high"
    else:
        fallback.setdefault("risk_hint", "")
    fallback.setdefault("secondary_fact_types", [])
    fallback.setdefault("reason", fallback.get("fallback_reason", ""))
    fallback.setdefault("needs_visual_asset", _visual_need_for_fact_type(fact_type))
    fallback.setdefault("visual_asset_reason", "")
    fallback.setdefault("retrieval_focus", _retrieval_focus_for_fact_type(fact_type))
    fallback.setdefault("customer_goals", [])
    fallback.setdefault("goal_understanding_status", "degraded")
    fallback.setdefault("goal_understanding_diagnostics", ["llm_goal_understanding_unavailable"])
    return fallback


def _invalidates_authoritative_understanding(
    diagnostics: dict[str, Any],
) -> bool:
    stage = str(diagnostics.get("stage") or "").strip()
    return stage in {
        "json_parse",
        "top_level_schema",
        "goal_schema",
        "known_unmapped",
        "source_provenance",
        "schema_validation",
        "provenance_validation",
    }


def _semantic_consistency_guard(
    deterministic: dict[str, Any],
    llm_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Prevent a clearly off-topic LLM classification from poisoning retrieval.

    This is a consistency guard, not the primary router. It only activates when
    the fallback semantic channel has a high-confidence category and the LLM
    chooses a fact type that would retrieve a mutually incompatible evidence
    family, such as answering a size/installation/material question with load
    capacity.
    """

    if not llm_result:
        return None
    rule_type = str(deterministic.get("query_fact_type") or "")
    llm_type = str(llm_result.get("query_fact_type") or "")
    if not rule_type or not llm_type or rule_type == llm_type:
        return None
    if float(deterministic.get("confidence") or 0) < 0.75:
        return None
    if float(llm_result.get("confidence") or 0) < 0.55:
        return None

    incompatible = {
        "material": {"load_capacity", "installation", "dimensions"},
        "installation": {"load_capacity", "material", "dimensions"},
        "dimensions": {"load_capacity", "material", "installation"},
        "gross_weight": {"load_capacity", "dimensions", "space_fit", "installation"},
        "accessory_availability": {"installation", "accessory_usage", "dimensions", "space_fit", "load_capacity"},
        "space_fit": {"load_capacity", "material", "installation", "placement_scene"},
        "placement_scene": {"load_capacity", "material", "installation"},
        "odor": {"load_capacity", "installation", "dimensions"},
        "pinch_safety": {"load_capacity", "material", "installation", "safety_small_parts"},
        "safety_small_parts": {"load_capacity", "material", "installation", "pinch_safety"},
        "aftersales_policy": {"installation", "load_capacity", "material"},
    }
    if llm_type not in incompatible.get(rule_type, set()):
        return None

    guarded = dict(deterministic)
    guarded["source"] = "semantic_consistency_guard"
    guarded["reason"] = "LLM classification conflicts with a high-confidence semantic guard"
    guarded["llm_rejected_fact_type"] = llm_type
    guarded["llm_rejected_confidence"] = llm_result.get("confidence", 0)
    guarded["secondary_fact_types"] = list(dict.fromkeys(
        [llm_type] + list(llm_result.get("secondary_fact_types") or [])
    ))[:5]
    fact_type = str(guarded.get("query_fact_type") or "")
    guarded["needs_visual_asset"] = _visual_need_for_fact_type(fact_type)
    guarded["retrieval_focus"] = _retrieval_focus_for_fact_type(fact_type)
    return guarded


def _policy_intent_candidates(state: dict[str, Any]) -> list[dict[str, str]]:
    """Project only trusted Domain Pack intent IDs into Turn Understanding."""
    from app.repositories.file_policy_repository import FilePolicyRepository
    from app.services.canonical_conversation_turn_service import (
        normalize_trusted_answer_eligibility_owner_context,
    )

    copilot_context = (
        state.get("copilot_context")
        if isinstance(state.get("copilot_context"), dict)
        else {}
    )
    owner_context = normalize_trusted_answer_eligibility_owner_context(
        copilot_context.get("_answer_eligibility_owner_context")
    )
    pack = FilePolicyRepository().resolve_domain_policy_pack(
        owner_context.get("domain_policy_context")
    )
    if pack.get("status") != "loaded":
        return []
    candidates = []
    for policy in pack.get("bounded_inference_policies") or []:
        if not isinstance(policy, dict):
            continue
        policy_intent_ref = _bounded_text(
            policy.get("policy_intent_ref"),
            96,
        ).lower()
        goal_family = _bounded_text(policy.get("goal_family"), 96).lower()
        intent_kind = _bounded_text(policy.get("intent_kind"), 64).lower()
        description = _POLICY_INTENT_DESCRIPTIONS.get(intent_kind, "")
        if not policy_intent_ref or not goal_family or not description:
            continue
        candidates.append({
            "policy_intent_ref": policy_intent_ref,
            "goal_family": goal_family,
            "intent_kind": intent_kind,
            "allowed_scope": _bounded_text(
                policy.get("allowed_scope"),
                96,
            ).lower(),
            "description": description,
        })
    return sorted(
        candidates,
        key=lambda item: item["policy_intent_ref"],
    )


def _canonical_fact_type_candidates() -> list[dict[str, str]]:
    """Project the server registry without exposing rules or sample mappings."""
    return [
        {
            "fact_type_id": fact_type_id,
            "meaning": _bounded_text(FACT_TYPE_LABELS[fact_type_id], 80),
            "attribute_contract": "optional_explicit_attribute_key",
        }
        for fact_type_id in sorted(FACT_TYPE_LABELS)
    ]


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _field_name_hash(field_name: Any) -> str:
    return hashlib.sha256(
        str(field_name or "").encode("utf-8")
    ).hexdigest()[:16]


def _diagnostic_field_name(
    json_pointer: str,
    *,
    unknown_field: Any = None,
) -> str:
    if unknown_field is not None:
        return "<extra>"
    path = str(json_pointer or "")
    if not path or path == "$":
        return "<root>"
    field_name = path.rsplit(".", 1)[-1]
    if "[" in field_name:
        field_name = field_name.split("[", 1)[0]
    return field_name or "<root>"


def _violation(
    *,
    stage: str,
    json_pointer: str,
    reason_code: str,
    expected_type: str = "",
    actual_value: Any = None,
    expected_count: int | None = None,
    actual_count: int | None = None,
    unknown_field: Any = None,
    value_present: bool = True,
    required: bool = True,
) -> dict[str, Any]:
    missing = not value_present
    extra = unknown_field is not None
    return {
        "stage": stage,
        "error_category": reason_code,
        "json_pointer": json_pointer,
        "field_name": _diagnostic_field_name(
            json_pointer,
            unknown_field=unknown_field,
        ),
        "reason_code": reason_code,
        "expected_type": expected_type,
        "actual_type": (
            _value_type(actual_value)
            if value_present
            else "missing"
        ),
        "expected_count": expected_count,
        "actual_count": actual_count,
        "field_name_hash": (
            _field_name_hash(unknown_field)
            if unknown_field is not None
            else ""
        ),
        "required": bool(required),
        "missing": missing,
        "extra": extra,
        "value_present": bool(value_present),
        "array_item_count": None,
        "root_key_count": None,
    }


def _annotate_violation_shape(
    violations: list[dict[str, Any]],
    *,
    root_key_count: int,
    array_item_count: int | None,
) -> list[dict[str, Any]]:
    for violation in violations:
        violation["root_key_count"] = root_key_count
        violation["array_item_count"] = array_item_count
    return violations


def _new_turn_understanding_diagnostics(client: Any) -> dict[str, Any]:
    identity = safe_provider_identity(
        provider_name=str(
            getattr(client, "provider_name", "") or "unknown"
        ),
        api_base=str(getattr(client, "api_base", "") or ""),
        model=str(getattr(client, "model", "") or ""),
    )
    return {
        "schema_version": _DIAGNOSTICS_SCHEMA_VERSION,
        "attempted": False,
        "model_call_count": 0,
        "stage": "not_started",
        "status": "pending",
        "reason_code": "",
        "error_category": "",
        "provider": {
            "provider_family": identity["provider_name"],
            "model": identity["model_name"],
            "host_fingerprint": identity["host_fingerprint"],
            "http_status": None,
            "provider_error_category": "",
        },
        "completion": {
            "choices_count": 0,
            "finish_reason": "",
            "content_present": False,
            "content_char_count": 0,
            "content_sha256": "",
            "reasoning_content_present": False,
        },
        "json_parse": {
            "attempted": False,
            "passed": False,
            "root_type": "",
        },
        "json_envelope_contract_version": JSON_ENVELOPE_CONTRACT_VERSION,
        "provider_output_schema_version": MINIMAL_PROVIDER_SCHEMA_VERSION,
        "provider_output_schema_sha256": (
            MINIMAL_PROVIDER_OUTPUT_SCHEMA_SHA256
        ),
        "atomic_goal_span_contract_version": (
            ATOMIC_GOAL_SPAN_CONTRACT_VERSION
        ),
        "server_span_resolver_version": SERVER_SPAN_RESOLVER_VERSION,
        "unmapped_metadata_contract_version": (
            UNMAPPED_METADATA_CONTRACT_VERSION
        ),
        "optional_metadata": {
            "semantic_key_present_count": 0,
            "semantic_key_empty_count": 0,
            "semantic_key_missing_count": 0,
        },
        "span_reference": {
            "text_length": 0,
            "text_sha256": "",
        },
        "span_resolution": {
            "goal_count": 0,
            "resolved_count": 0,
            "provider_offset_match_count": 0,
            "provider_offset_mismatch_count": 0,
            "records": [],
        },
        "response_envelope": "invalid",
        "envelope_unwrap_count": 0,
        "json_parse_success": False,
        "schema_success": False,
        "response_content_length": 0,
        "response_content_sha256": "",
        "schema_validation": {
            "passed": False,
            "violation_count": 0,
            "violations": [],
            "root_key_count": None,
            "array_item_count": None,
        },
        "provenance_validation": {
            "passed": False,
            "violation_count": 0,
            "violations": [],
        },
        "latency": {
            "provider_ms": None,
            "parse_ms": None,
            "schema_ms": None,
            "provenance_ms": None,
            "total_ms": None,
        },
        "retry_count": 0,
        "json_repair_count": 0,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def _set_failure(
    diagnostics: dict[str, Any],
    *,
    stage: str,
    reason_code: str,
) -> None:
    diagnostics["status"] = "failed"
    if not diagnostics.get("reason_code"):
        diagnostics["stage"] = stage
        diagnostics["reason_code"] = reason_code
        diagnostics["error_category"] = reason_code


def _append_validation_violations(
    diagnostics: dict[str, Any],
    *,
    section: str,
    violations: list[dict[str, Any]],
) -> None:
    target = diagnostics[section]
    target["violations"] = violations
    target["violation_count"] = len(violations)
    target["passed"] = not violations
    if section == "schema_validation":
        target["root_key_count"] = (
            violations[0].get("root_key_count")
            if violations
            else target.get("root_key_count")
        )
        target["array_item_count"] = (
            violations[0].get("array_item_count")
            if violations
            else target.get("array_item_count")
        )
    if violations:
        first = violations[0]
        _set_failure(
            diagnostics,
            stage=str(first["stage"]),
            reason_code=str(first["reason_code"]),
        )


def _finish_diagnostics(
    diagnostics: dict[str, Any],
    *,
    started_at: float,
) -> None:
    diagnostics["latency"]["total_ms"] = round(
        (time.perf_counter() - started_at) * 1000,
        2,
    )
    if diagnostics.get("status") == "pending":
        diagnostics["stage"] = "understanding_built"
        diagnostics["status"] = "passed"


def _provider_error_details(exc: Exception) -> tuple[str, int | None]:
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    status = status if isinstance(status, int) else None
    if status in {401, 403}:
        return "provider_auth_error", status
    if status == 402:
        return "provider_quota_error", status
    if status == 429:
        return "provider_rate_limited", status

    type_name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in type_name:
        return "provider_timeout", status
    if isinstance(exc, ConnectionError) or "connection" in type_name:
        return "provider_connection_error", status
    if status is not None:
        return "provider_http_error", status
    return "provider_unknown_error", None


def _safe_finish_reason(value: Any) -> str:
    reason = str(value or "").strip().lower()
    if reason in {
        "stop",
        "length",
        "tool_calls",
        "function_call",
        "content_filter",
    }:
        return reason
    return "other" if reason else ""


def _validate_raw_llm_result(
    data: dict[str, Any],
    *,
    message: str,
    history_texts: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    schema: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    root_key_count = len(data)
    goals = data.get("goals")
    array_item_count = len(goals) if isinstance(goals, list) else None

    missing = sorted(_LLM_RESULT_FIELDS - set(data))
    extras = sorted(set(data) - _LLM_RESULT_FIELDS)
    for field in missing:
        schema.append(_violation(
            stage="top_level_schema",
            json_pointer=f"$.{field}",
            reason_code="top_level_field_missing",
            expected_type="array",
            value_present=False,
        ))
    for field in extras:
        schema.append(_violation(
            stage="top_level_schema",
            json_pointer="$.<extra>",
            reason_code="top_level_extra_field",
            actual_value=data[field],
            unknown_field=field,
            required=False,
        ))

    if not isinstance(goals, list):
        if "goals" in data:
            schema.append(_violation(
                stage="top_level_schema",
                json_pointer="$.goals",
                reason_code="top_level_field_type_invalid",
                expected_type="array",
                actual_value=goals,
            ))
        return (
            _annotate_violation_shape(
                schema,
                root_key_count=root_key_count,
                array_item_count=array_item_count,
            ),
            _annotate_violation_shape(
                provenance,
                root_key_count=root_key_count,
                array_item_count=array_item_count,
            ),
        )
    if not goals:
        schema.append(_violation(
            stage="goal_schema",
            json_pointer="$.goals",
            reason_code="goal_count_invalid",
            expected_type="non_empty_array",
            actual_value=goals,
            expected_count=1,
            actual_count=0,
        ))
    if len(goals) > 12:
        schema.append(_violation(
            stage="goal_schema",
            json_pointer="$.goals",
            reason_code="goal_count_invalid",
            expected_type="array_max_12",
            actual_value=goals,
            expected_count=12,
            actual_count=len(goals),
        ))

    seen_goal_provenance: set[tuple[int, int, str]] = set()
    for index, goal in enumerate(goals[:12]):
        base = f"$.goals[{index}]"
        if not isinstance(goal, dict):
            schema.append(_violation(
                stage="goal_schema",
                json_pointer=base,
                reason_code="goal_not_object",
                expected_type="object",
                actual_value=goal,
            ))
            continue

        missing_goal_fields = sorted(_RAW_GOAL_REQUIRED_FIELDS - set(goal))
        extra_goal_fields = sorted(set(goal) - _RAW_GOAL_FIELDS)
        for field in missing_goal_fields:
            schema.append(_violation(
                stage="known_unmapped" if field == "claim_type_status" else "goal_schema",
                json_pointer=f"{base}.{field}",
                reason_code=(
                    "claim_type_status_missing"
                    if field == "claim_type_status"
                    else "goal_field_missing"
                ),
                value_present=False,
            ))
        for field in extra_goal_fields:
            schema.append(_violation(
                stage="goal_schema",
                json_pointer=f"{base}.<extra>",
                reason_code=(
                    "owner_invalid"
                    if field in {"owner", "provenance", "source_stage"}
                    else "goal_extra_field"
                ),
                actual_value=goal[field],
                unknown_field=field,
                required=False,
            ))

        for field in sorted(_RAW_GOAL_FIELDS):
            if field not in goal:
                continue
            value = goal[field]
            if not isinstance(value, str):
                schema.append(_violation(
                    stage="goal_schema",
                    json_pointer=f"{base}.{field}",
                    reason_code="goal_field_type_invalid",
                    expected_type="string",
                    actual_value=value,
                ))

        goal_kind = goal.get("goal_kind")
        if (
            isinstance(goal_kind, str)
            and goal_kind.strip().lower() not in ALLOWED_GOAL_KINDS
        ):
            schema.append(_violation(
                stage="goal_schema",
                json_pointer=f"{base}.goal_kind",
                reason_code="goal_kind_invalid",
                expected_type="allowed_goal_kind",
                actual_value=goal_kind,
            ))

        status = goal.get("claim_type_status")
        claim_type = goal.get("claim_type")
        semantic_key = goal.get("semantic_key")
        if isinstance(status, str):
            normalized_status = status.strip().lower()
            if normalized_status not in ALLOWED_CLAIM_TYPE_STATUSES:
                schema.append(_violation(
                    stage="known_unmapped",
                    json_pointer=f"{base}.claim_type_status",
                    reason_code="claim_type_status_invalid",
                    expected_type="canonical|unmapped",
                    actual_value=status,
                ))
            elif normalized_status == "canonical":
                if not isinstance(claim_type, str) or not claim_type.strip():
                    schema.append(_violation(
                        stage="known_unmapped",
                        json_pointer=f"{base}.claim_type",
                        reason_code="canonical_claim_type_missing",
                        expected_type="canonical_fact_type",
                        actual_value=claim_type,
                    ))
                elif claim_type.strip() not in ALLOWED_FACT_TYPES:
                    schema.append(_violation(
                        stage="known_unmapped",
                        json_pointer=f"{base}.claim_type",
                        reason_code="canonical_claim_type_not_allowed",
                        expected_type="canonical_fact_type",
                        actual_value=claim_type,
                    ))
                if isinstance(semantic_key, str) and semantic_key.strip():
                    schema.append(_violation(
                        stage="known_unmapped",
                        json_pointer=f"{base}.semantic_key",
                        reason_code="canonical_with_semantic_key",
                        expected_type="empty_string",
                        actual_value=semantic_key,
                    ))
            elif normalized_status == "unmapped":
                if isinstance(claim_type, str) and claim_type.strip():
                    schema.append(_violation(
                        stage="known_unmapped",
                        json_pointer=f"{base}.claim_type",
                        reason_code="unmapped_claim_type_not_empty",
                        expected_type="empty_string",
                        actual_value=claim_type,
                    ))
                if (
                    isinstance(semantic_key, str)
                    and semantic_key.strip()
                    and not _normalized_semantic_key(semantic_key)
                ):
                    schema.append(_violation(
                        stage="known_unmapped",
                        json_pointer=f"{base}.semantic_key",
                        reason_code="unmapped_semantic_key_invalid",
                        expected_type="bounded_semantic_key",
                        actual_value=semantic_key,
                    ))

        source_provenance, resolution_reason = (
            _resolve_source_span_provenance(
                goal.get("source_text"),
                message,
                history_texts=history_texts,
            )
        )
        if source_provenance is None:
            provenance.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source_text",
                reason_code=resolution_reason,
                expected_type="unique_exact_current_message_slice",
                actual_value=goal.get("source_text"),
            ))
        else:
            provenance_key = (
                int(source_provenance.get("source_span_start", -1)),
                int(source_provenance.get("source_span_end", -1)),
                str(source_provenance.get("source_text_sha256") or ""),
            )
            if provenance_key in seen_goal_provenance:
                provenance.append(_violation(
                    stage="source_provenance",
                    json_pointer=base,
                    reason_code="duplicate_resolved_provenance",
                    expected_count=1,
                    actual_count=2,
                ))
            seen_goal_provenance.add(provenance_key)

    return (
        _annotate_violation_shape(
            schema,
            root_key_count=root_key_count,
            array_item_count=array_item_count,
        ),
        _annotate_violation_shape(
            provenance,
            root_key_count=root_key_count,
            array_item_count=array_item_count,
        ),
    )


def _canonical_provenance_violations(
    goals: Any,
    *,
    message: str,
    source_turn_uid: str,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    if not isinstance(goals, list):
        return violations
    seen_provenance: set[tuple[str, int, int, str]] = set()
    for index, goal in enumerate(goals):
        if not isinstance(goal, dict):
            continue
        base = f"$.customer_goals[{index}]"
        if goal.get("owner") != "turn_understanding_owner":
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.owner",
                reason_code="owner_invalid",
                expected_type="turn_understanding_owner",
                actual_value=goal.get("owner"),
            ))
        if goal.get("schema_version") != GOAL_IDENTITY_SCHEMA_VERSION:
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.schema_version",
                reason_code="goal_identity_schema_invalid",
                expected_type=GOAL_IDENTITY_SCHEMA_VERSION,
                actual_value=goal.get("schema_version"),
            ))
        if goal.get("source_turn_uid") != source_turn_uid:
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source_turn_uid",
                reason_code="source_turn_uid_mismatch",
                expected_type="server_generated_current_turn_uid",
                actual_value=goal.get("source_turn_uid"),
            ))
        if (
            goal.get("source_stage") != "semantic_fact_type_service"
            or goal.get("source") != "current_customer_message"
        ):
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source",
                reason_code="source_message_mismatch",
                expected_type="current_customer_message",
                actual_value=goal.get("source"),
            ))
        start = goal.get("source_span_start")
        end = goal.get("source_span_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source_span",
                reason_code="source_span_type_invalid",
                expected_type="integer_range",
                actual_value=start,
            ))
            continue
        if start < 0 or end <= start or end > len(message):
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source_span",
                reason_code="source_span_out_of_range",
                expected_type="current_message_range",
                actual_value=[start, end],
            ))
            continue
        expected_digest = hashlib.sha256(
            canonical_source_span_text(
                message[start:end]
            ).encode("utf-8")
        ).hexdigest()
        if goal.get("source_span_sha256") != expected_digest:
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source_span_sha256",
                reason_code="source_span_digest_mismatch",
                expected_type="sha256_current_message_slice",
                actual_value=goal.get("source_span_sha256"),
            ))
        if goal.get("source_text_sha256") != expected_digest:
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.source_text_sha256",
                reason_code="source_text_digest_mismatch",
                expected_type="sha256_current_message_slice",
                actual_value=goal.get("source_text_sha256"),
            ))
        provenance_key = (
            str(goal.get("source_turn_uid") or ""),
            start,
            end,
            str(goal.get("source_text_sha256") or ""),
        )
        if provenance_key in seen_provenance:
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=base,
                reason_code="duplicate_resolved_provenance",
                expected_count=1,
                actual_count=2,
            ))
        seen_provenance.add(provenance_key)
        if goal.get("goal_ref") != _goal_ref(goal):
            violations.append(_violation(
                stage="source_provenance",
                json_pointer=f"{base}.goal_ref",
                reason_code="goal_identity_mismatch",
                expected_type="server_generated_goal_ref",
                actual_value=goal.get("goal_ref"),
            ))
    return violations


def _unwrap_turn_understanding_json_envelope(
    raw: str,
) -> tuple[str, str, int, str]:
    """Unwrap one complete JSON fence without altering its payload."""

    stripped = raw.strip()
    if "```" not in stripped:
        if stripped.startswith(("{", "[")):
            return stripped, "raw_json", 0, ""
        return "", "invalid", 0, "free_text_response"

    lines = stripped.splitlines()
    if (
        len(lines) < 3
        or lines[0].strip().lower() not in {"```", "```json"}
        or lines[-1].strip() != "```"
    ):
        return "", "invalid", 0, "json_envelope_invalid"
    body = "\n".join(lines[1:-1]).strip()
    if not body or "```" in body:
        return "", "invalid", 0, "json_envelope_invalid"
    return body, "single_json_fence", 1, ""


def _classify_with_llm(
    state: dict[str, Any],
    message: str,
    intent: str,
    *,
    diagnostics_sink: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    client = get_llm_client()
    started_at = time.perf_counter()
    diagnostics = _new_turn_understanding_diagnostics(client)
    if isinstance(diagnostics_sink, dict):
        diagnostics_sink.clear()
        diagnostics_sink.update(diagnostics)
        diagnostics = diagnostics_sink
    span_reference_text = str(message)
    diagnostics["span_reference"] = {
        "text_length": len(span_reference_text),
        "text_sha256": hashlib.sha256(
            span_reference_text.encode("utf-8")
        ).hexdigest(),
    }
    if not client.api_key:
        diagnostics["provider"]["provider_error_category"] = (
            "provider_auth_error"
        )
        _set_failure(
            diagnostics,
            stage="provider_request",
            reason_code="provider_auth_error",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    policy_intent_candidates = _policy_intent_candidates(state)
    source_turn_uid = _current_source_turn_uid(
        state,
        span_reference_text,
    )
    payload = {
        "customer_message": span_reference_text,
        "current_intent": intent,
        "canonical_fact_type_candidates": _canonical_fact_type_candidates(),
        "policy_intent_candidates": policy_intent_candidates,
    }

    diagnostics["attempted"] = True
    diagnostics["model_call_count"] = 1
    diagnostics["stage"] = "provider_request"
    provider_started = time.perf_counter()
    try:
        response = client.create_chat_completion(
            model=client.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=360,
            response_format={"type": "json_object"},
            _single_attempt_no_repair=True,
        )
    except Exception as exc:
        diagnostics["latency"]["provider_ms"] = round(
            (time.perf_counter() - provider_started) * 1000,
            2,
        )
        reason_code, http_status = _provider_error_details(exc)
        diagnostics["provider"]["http_status"] = http_status
        diagnostics["provider"]["provider_error_category"] = (
            reason_code
        )
        _set_failure(
            diagnostics,
            stage="provider_request",
            reason_code=reason_code,
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        logger.warning(
            "LLM fact type classifier failed at provider_request: %s",
            reason_code,
        )
        return None

    diagnostics["latency"]["provider_ms"] = round(
        (time.perf_counter() - provider_started) * 1000,
        2,
    )
    diagnostics["stage"] = "completion"
    if response is None:
        _set_failure(
            diagnostics,
            stage="completion",
            reason_code="completion_missing",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    choices = getattr(response, "choices", None)
    if not isinstance(choices, (list, tuple)):
        _set_failure(
            diagnostics,
            stage="completion",
            reason_code="choices_missing",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None
    diagnostics["completion"]["choices_count"] = len(choices)
    if not choices:
        _set_failure(
            diagnostics,
            stage="completion",
            reason_code="choices_missing",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    choice = choices[0]
    finish_reason = _safe_finish_reason(
        getattr(choice, "finish_reason", "")
    )
    diagnostics["completion"]["finish_reason"] = finish_reason
    message_object = getattr(choice, "message", None)
    if message_object is None:
        _set_failure(
            diagnostics,
            stage="completion",
            reason_code="message_missing",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    reasoning_present = bool(
        getattr(message_object, "reasoning_content", None)
        or getattr(message_object, "reasoning_details", None)
    )
    diagnostics["completion"]["reasoning_content_present"] = (
        reasoning_present
    )
    content = getattr(message_object, "content", None)
    raw = content if isinstance(content, str) else ""
    diagnostics["completion"]["content_present"] = bool(raw.strip())
    diagnostics["completion"]["content_char_count"] = len(raw)
    diagnostics["completion"]["content_sha256"] = (
        hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if raw
        else ""
    )
    diagnostics["response_content_length"] = len(raw)
    diagnostics["response_content_sha256"] = diagnostics[
        "completion"
    ]["content_sha256"]
    if finish_reason == "length":
        _set_failure(
            diagnostics,
            stage="completion",
            reason_code="response_truncated",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None
    if not raw.strip():
        _set_failure(
            diagnostics,
            stage="completion",
            reason_code=(
                "reasoning_only_response"
                if reasoning_present
                else "content_empty"
            ),
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    diagnostics["stage"] = "json_parse"
    diagnostics["json_parse"]["attempted"] = True
    parse_started = time.perf_counter()
    (
        json_payload,
        response_envelope,
        envelope_unwrap_count,
        envelope_error,
    ) = _unwrap_turn_understanding_json_envelope(raw)
    diagnostics["response_envelope"] = response_envelope
    diagnostics["envelope_unwrap_count"] = envelope_unwrap_count
    if envelope_error:
        diagnostics["latency"]["parse_ms"] = round(
            (time.perf_counter() - parse_started) * 1000,
            2,
        )
        _set_failure(
            diagnostics,
            stage="json_parse",
            reason_code=envelope_error,
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None
    try:
        parsed = json.loads(json_payload)
    except json.JSONDecodeError:
        diagnostics["latency"]["parse_ms"] = round(
            (time.perf_counter() - parse_started) * 1000,
            2,
        )
        _set_failure(
            diagnostics,
            stage="json_parse",
            reason_code="json_decode_error",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None
    diagnostics["latency"]["parse_ms"] = round(
        (time.perf_counter() - parse_started) * 1000,
        2,
    )
    diagnostics["json_parse"]["passed"] = True
    diagnostics["json_parse_success"] = True
    diagnostics["json_parse"]["root_type"] = _value_type(parsed)
    if not isinstance(parsed, dict):
        _set_failure(
            diagnostics,
            stage="json_parse",
            reason_code="json_root_not_object",
        )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    parsed_goals = parsed.get("goals")
    if isinstance(parsed_goals, list):
        for goal in parsed_goals:
            if not isinstance(goal, dict):
                continue
            if "semantic_key" not in goal:
                diagnostics["optional_metadata"][
                    "semantic_key_missing_count"
                ] += 1
            elif (
                isinstance(goal.get("semantic_key"), str)
                and not goal["semantic_key"].strip()
            ):
                diagnostics["optional_metadata"][
                    "semantic_key_empty_count"
                ] += 1
            else:
                diagnostics["optional_metadata"][
                    "semantic_key_present_count"
                ] += 1

    history_texts = _historical_customer_texts(state)
    diagnostics["span_resolution"] = _span_resolution_diagnostics(
        parsed.get("goals"),
        span_reference_text=span_reference_text,
        history_texts=history_texts,
    )
    diagnostics["schema_validation"]["root_key_count"] = len(parsed)
    diagnostics["schema_validation"]["array_item_count"] = (
        len(parsed["goals"])
        if isinstance(parsed.get("goals"), list)
        else None
    )
    schema_started = time.perf_counter()
    schema_violations, raw_provenance_violations = (
        _validate_raw_llm_result(
            parsed,
            message=span_reference_text,
            history_texts=history_texts,
        )
    )
    diagnostics["latency"]["schema_ms"] = round(
        (time.perf_counter() - schema_started) * 1000,
        2,
    )
    _append_validation_violations(
        diagnostics,
        section="schema_validation",
        violations=schema_violations,
    )
    diagnostics["schema_success"] = not schema_violations

    provenance_started = time.perf_counter()
    canonical_goals: list[dict[str, Any]] = []
    result = _sanitize_llm_result(
        parsed,
        message=span_reference_text,
        source_turn_uid=source_turn_uid,
        policy_intent_candidates=policy_intent_candidates,
        canonical_goals_sink=canonical_goals,
        history_texts=history_texts,
    )
    canonical_provenance = _canonical_provenance_violations(
        canonical_goals,
        message=span_reference_text,
        source_turn_uid=source_turn_uid,
    )
    provenance_violations = (
        raw_provenance_violations + canonical_provenance
    )
    _annotate_violation_shape(
        provenance_violations,
        root_key_count=len(parsed),
        array_item_count=(
            len(parsed["goals"])
            if isinstance(parsed.get("goals"), list)
            else None
        ),
    )
    diagnostics["latency"]["provenance_ms"] = round(
        (time.perf_counter() - provenance_started) * 1000,
        2,
    )
    _append_validation_violations(
        diagnostics,
        section="provenance_validation",
        violations=provenance_violations,
    )

    if schema_violations or provenance_violations:
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None
    if result is None:
        if not schema_violations and not provenance_violations:
            local_violation = _violation(
                stage="schema_validation",
                json_pointer="$",
                reason_code="local_validator_rejected_valid_output",
                expected_type="valid_turn_understanding",
                actual_value=parsed,
            )
            _append_validation_violations(
                diagnostics,
                section="schema_validation",
                violations=[local_violation],
            )
        _finish_diagnostics(diagnostics, started_at=started_at)
        return None

    _finish_diagnostics(diagnostics, started_at=started_at)
    return result


def _sanitize_llm_result(
    data: dict[str, Any],
    *,
    message: str = "",
    source_turn_uid: str = "",
    policy_intent_candidates: list[dict[str, Any]] | None = None,
    canonical_goals_sink: list[dict[str, Any]] | None = None,
    history_texts: list[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict) or set(data) != _LLM_RESULT_FIELDS:
        return None

    source_turn_uid = (
        source_turn_uid.strip()
        if isinstance(source_turn_uid, str)
        else ""
    ) or canonical_current_customer_turn_uid(message)
    customer_goals, goal_understanding_status, goal_diagnostics = _sanitize_customer_goals(
        data.get("goals"),
        message=message,
        source_turn_uid=source_turn_uid,
        policy_intent_candidates=policy_intent_candidates,
        history_texts=history_texts,
    )
    if isinstance(canonical_goals_sink, list):
        canonical_goals_sink.clear()
        canonical_goals_sink.extend(
            dict(goal)
            for goal in customer_goals
            if isinstance(goal, dict)
        )
    if "duplicate_resolved_provenance" in goal_diagnostics:
        return None
    goals_valid, canonical_diagnostics = _validate_canonical_customer_goals(
        customer_goals,
        message=message,
        source_turn_uid=source_turn_uid,
    )
    if not goals_valid:
        return None
    goal_diagnostics = list(dict.fromkeys(
        goal_diagnostics + canonical_diagnostics
    ))
    ordered_goals = sorted(
        customer_goals,
        key=lambda goal: (
            int(goal.get("source_span_start", 0)),
            int(goal.get("source_span_end", 0)),
            str(goal.get("goal_ref") or ""),
        ),
    )
    canonical_customer_types = [
        str(goal.get("claim_type") or "")
        for goal in ordered_goals
        if (
            goal.get("goal_kind") == "customer_goal"
            and goal.get("claim_type_status") == "canonical"
            and goal.get("claim_type") in ALLOWED_FACT_TYPES
        )
    ]
    canonical_supporting_types = [
        str(goal.get("claim_type") or "")
        for goal in ordered_goals
        if (
            goal.get("claim_type_status") == "canonical"
            and goal.get("claim_type") in ALLOWED_FACT_TYPES
        )
    ]
    canonical_types = list(dict.fromkeys([
        *canonical_customer_types,
        *canonical_supporting_types,
    ]))
    fact_type = canonical_types[0] if canonical_types else ""
    secondary = canonical_types[1:6]
    risk_hint = (
        "high"
        if any(
            (
                goal.get("claim_type") in HIGH_RISK_BOUNDARY_TYPES
                or goal.get("policy_intent_kind") in {
                    "absolute_guarantee",
                    "test_standard_request",
                    "warranty_or_liability_request",
                }
            )
            for goal in customer_goals
        )
        else (
            "medium"
            if any(
                goal.get("claim_type_status") == "unmapped"
                for goal in customer_goals
            )
            else "low"
        )
    )
    needs_visual_asset = any(
        _visual_need_for_fact_type(item)
        for item in canonical_types
    )
    return {
        "query_fact_type": fact_type,
        "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
        "confidence": 1.0,
        "matched_terms": [],
        "source": "llm",
        "reason": "minimal_turn_understanding_validated",
        "risk_hint": risk_hint,
        "secondary_fact_types": secondary,
        "needs_visual_asset": needs_visual_asset,
        "visual_asset_reason": "",
        "retrieval_focus": _retrieval_focus_for_fact_type(fact_type),
        "customer_goals": customer_goals,
        "goal_understanding_status": goal_understanding_status,
        "goal_understanding_diagnostics": goal_diagnostics,
    }


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def canonical_source_span_text(value: Any) -> str:
    """Return the exact slice from the already-normalized current message."""
    return str(value or "")


def _exact_source_text_matches(
    span_reference_text: str,
    source_text: str,
) -> list[int]:
    matches: list[int] = []
    start = span_reference_text.find(source_text)
    while start >= 0:
        matches.append(start)
        start = span_reference_text.find(source_text, start + 1)
    return matches


def _historical_customer_texts(state: dict[str, Any]) -> list[str]:
    context = state.get("copilot_context")
    context = context if isinstance(context, dict) else {}
    history = context.get("conversation_history")
    if not isinstance(history, list):
        return []
    texts: list[str] = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        if role not in {"customer", "buyer", "user"}:
            continue
        content = turn.get("content")
        if not isinstance(content, str):
            content = turn.get("text")
        if isinstance(content, str) and content:
            texts.append(content)
    return texts


def _span_resolution_diagnostics(
    goals: Any,
    *,
    span_reference_text: str,
    history_texts: list[str] | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen: dict[tuple[int, int, str], list[int]] = {}
    goal_items = goals if isinstance(goals, list) else []
    for index, goal in enumerate(goal_items[:12]):
        source_text = (
            goal.get("source_text")
            if isinstance(goal, dict)
            else None
        )
        provider_start = (
            goal.get("source_span_start")
            if isinstance(goal, dict)
            else None
        )
        provider_end = (
            goal.get("source_span_end")
            if isinstance(goal, dict)
            else None
        )
        provider_offsets_present = (
            provider_start is not None
            or provider_end is not None
        )
        source_text_valid = (
            isinstance(source_text, str)
            and bool(source_text)
            and len(source_text) <= 240
        )
        source_digest = (
            hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            if isinstance(source_text, str)
            else ""
        )
        matches = (
            _exact_source_text_matches(
                span_reference_text,
                source_text,
            )
            if source_text_valid
            else []
        )
        resolved_start = matches[0] if len(matches) == 1 else None
        resolved_end = (
            resolved_start + len(source_text)
            if resolved_start is not None
            else None
        )
        provider_offset_match = (
            provider_start == resolved_start
            and provider_end == resolved_end
            if resolved_start is not None and provider_offsets_present
            else None
        )
        if not source_text_valid:
            reason_code = "source_text_schema_invalid"
        elif not matches:
            from_history = any(
                source_text in history_text
                for history_text in (history_texts or [])
            )
            reason_code = (
                "source_text_from_wrong_turn"
                if from_history
                else "source_text_not_found"
            )
        elif len(matches) > 1:
            reason_code = "source_text_multiple_matches"
        elif not provider_offsets_present or provider_offset_match:
            reason_code = "source_text_resolved"
        else:
            reason_code = "provider_offset_mismatch_unique_text_match"

        provider_hash = (
            goal.get("source_text_sha256")
            if isinstance(goal, dict)
            else None
        )
        if (
            resolved_start is not None
            and isinstance(provider_hash, str)
            and provider_hash != source_digest
        ):
            reason_code = "source_text_hash_mismatch"

        record = {
            "goal_index": index,
            "source_text_length": (
                len(source_text)
                if isinstance(source_text, str)
                else None
            ),
            "source_text_sha256": source_digest,
            "exact_match_count": len(matches),
            "provider_span_start": (
                provider_start
                if isinstance(provider_start, int)
                and not isinstance(provider_start, bool)
                else None
            ),
            "provider_span_end": (
                provider_end
                if isinstance(provider_end, int)
                and not isinstance(provider_end, bool)
                else None
            ),
            "resolved_span_start": resolved_start,
            "resolved_span_end": resolved_end,
            "provider_offset_present": provider_offsets_present,
            "provider_offset_match": provider_offset_match,
            "reason_code": reason_code,
        }
        records.append(record)
        if resolved_start is not None:
            key = (resolved_start, resolved_end, source_digest)
            seen.setdefault(key, []).append(index)

    duplicate_indexes = {
        index
        for indexes in seen.values()
        if len(indexes) > 1
        for index in indexes
    }
    for record in records:
        if record["goal_index"] in duplicate_indexes:
            record["reason_code"] = "duplicate_resolved_provenance"

    return {
        "goal_count": len(goal_items),
        "resolved_count": sum(
            record["resolved_span_start"] is not None
            for record in records
        ),
        "provider_offset_match_count": sum(
            record["provider_offset_match"] is True
            for record in records
        ),
        "provider_offset_mismatch_count": sum(
            record["provider_offset_match"] is False
            for record in records
        ),
        "records": records,
    }


def _current_source_turn_uid(state: dict[str, Any], message: str) -> str:
    context = state.get("copilot_context")
    context = context if isinstance(context, dict) else {}
    return canonical_current_customer_turn_uid(
        message,
        conversation_history=context.get("conversation_history"),
    )


def _resolve_source_span_provenance(
    source_text: Any,
    message: str,
    *,
    source_span_start: Any = None,
    source_span_end: Any = None,
    history_texts: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    if (
        not isinstance(source_text, str)
        or not source_text
        or len(source_text) > 240
    ):
        return None, "source_text_schema_invalid"
    matches = _exact_source_text_matches(message, source_text)
    if not matches:
        if any(
            source_text in history_text
            for history_text in (history_texts or [])
        ):
            return None, "source_text_from_wrong_turn"
        return None, "source_text_not_found"
    if len(matches) > 1:
        return None, "source_text_multiple_matches"

    resolved_start = matches[0]
    resolved_end = resolved_start + len(source_text)
    source_text_sha256 = hashlib.sha256(
        canonical_source_span_text(source_text).encode("utf-8")
    ).hexdigest()
    provider_offsets_present = (
        source_span_start is not None
        or source_span_end is not None
    )
    provider_offset_match = (
        isinstance(source_span_start, int)
        and not isinstance(source_span_start, bool)
        and isinstance(source_span_end, int)
        and not isinstance(source_span_end, bool)
        and source_span_start == resolved_start
        and source_span_end == resolved_end
    )
    return {
        "source_span_start": resolved_start,
        "source_span_end": resolved_end,
        "source_span_sha256": source_text_sha256,
        "source_text_sha256": source_text_sha256,
    }, (
        "source_text_resolved"
        if not provider_offsets_present or provider_offset_match
        else "provider_offset_mismatch_unique_text_match"
    )


def _source_span_provenance(
    source_text: Any,
    message: str,
    *,
    source_span_start: Any = None,
    source_span_end: Any = None,
) -> dict[str, Any] | None:
    """Compatibility wrapper for the server-owned exact span resolver."""
    provenance, _reason_code = _resolve_source_span_provenance(
        source_text,
        message,
        source_span_start=source_span_start,
        source_span_end=source_span_end,
    )
    return provenance


def _goal_ref(goal: dict[str, Any]) -> str:
    canonical = {
        "owner": goal.get("owner", ""),
        "schema_version": goal.get("schema_version", ""),
        "source_turn_uid": goal.get("source_turn_uid", ""),
        "source_span_start": goal.get("source_span_start"),
        "source_span_end": goal.get("source_span_end"),
        "source_text_sha256": goal.get("source_text_sha256", ""),
    }
    digest = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"goal-{digest}"


def _normalized_semantic_key(value: Any) -> str:
    semantic_key = _bounded_text(value, 80).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]{0,79}", semantic_key):
        return ""
    return semantic_key


def _goal_type_reason_code(raw: dict[str, Any], goal_kind: str) -> str:
    if "claim_type_status" not in raw:
        return "claim_type_status_missing"
    status_value = raw.get("claim_type_status")
    if not isinstance(status_value, str):
        return "claim_type_status_invalid"
    status = status_value.strip().lower()
    if status not in ALLOWED_CLAIM_TYPE_STATUSES:
        return "claim_type_status_invalid"
    if (
        not _RAW_GOAL_REQUIRED_FIELDS.issubset(raw)
        or not set(raw).issubset(_RAW_GOAL_FIELDS)
    ):
        return "customer_goal_fields_invalid"

    claim_type_value = raw.get("claim_type")
    semantic_key_value = raw.get("semantic_key", "")
    if not isinstance(claim_type_value, str):
        return "claim_type_schema_invalid"
    if not isinstance(semantic_key_value, str):
        return "semantic_key_schema_invalid"
    claim_type = claim_type_value.strip().lower()
    semantic_key = _normalized_semantic_key(semantic_key_value)

    if status == "canonical":
        if not claim_type:
            return "canonical_claim_type_missing"
        if claim_type not in ALLOWED_FACT_TYPES:
            return "canonical_claim_type_unknown"
        if semantic_key:
            return "canonical_with_semantic_key"
        if goal_kind == "service_action":
            return "service_action_canonical_claim_forbidden"
        return ""

    if claim_type:
        return "unmapped_claim_type_present"
    if semantic_key_value.strip() and not semantic_key:
        return "unmapped_semantic_key_invalid"
    return ""


def _sanitize_customer_goals(
    value: Any,
    *,
    message: str = "",
    source_turn_uid: str = "",
    policy_intent_candidates: list[dict[str, Any]] | None = None,
    history_texts: list[str] | None = None,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    if value is None:
        return [], "degraded", ["customer_goals_missing"]
    if not isinstance(value, list):
        return [], "invalid", ["customer_goals_not_array"]
    source_turn_uid = (
        source_turn_uid.strip()
        if isinstance(source_turn_uid, str)
        else ""
    ) or canonical_current_customer_turn_uid(message)
    if not re.fullmatch(r"turn-[0-9a-f]{20}", source_turn_uid):
        return [], "invalid", ["customer_goal_source_turn_uid_invalid"]

    candidate_by_ref = {
        _bounded_text(item.get("policy_intent_ref"), 96).lower(): item
        for item in (policy_intent_candidates or [])
        if isinstance(item, dict)
        and _bounded_text(item.get("policy_intent_ref"), 96)
    }
    goals: dict[str, dict[str, Any]] = {}
    diagnostics: list[str] = []
    duplicate_provenance = False
    invalid_provenance = False
    if len(value) > 12:
        diagnostics.append("customer_goals_limit_exceeded")
    for raw in value[:12]:
        if not isinstance(raw, dict):
            diagnostics.append("customer_goal_not_object")
            continue
        goal_kind = _bounded_text(raw.get("goal_kind"), 40).lower()
        if goal_kind not in ALLOWED_GOAL_KINDS:
            diagnostics.append("customer_goal_kind_invalid")
            continue

        source_provenance, resolution_reason = (
            _resolve_source_span_provenance(
                raw.get("source_text"),
                message,
                history_texts=history_texts,
            )
        )
        if source_provenance is None:
            diagnostics.append(resolution_reason)
            invalid_provenance = True
            continue

        reason_code = _goal_type_reason_code(raw, goal_kind)
        if reason_code:
            diagnostics.append(reason_code)
        declared_status = _bounded_text(
            raw.get("claim_type_status"),
            24,
        ).lower()
        claim_type_status = (
            declared_status
            if not reason_code
            else "unmapped"
        )
        claim_type = (
            _bounded_text(raw.get("claim_type"), 80).lower()
            if claim_type_status == "canonical"
            else ""
        )
        claim_type_exact_match = claim_type_status == "canonical"
        attribute_key = _bounded_text(raw.get("attribute_key"), 80).lower()
        semantic_key = (
            ""
            if claim_type_status == "canonical"
            else _normalized_semantic_key(raw.get("semantic_key"))
        )
        policy_intent_ref = _bounded_text(
            raw.get("policy_intent_ref"),
            96,
        ).lower()
        selected_policy = candidate_by_ref.get(policy_intent_ref)
        if reason_code:
            policy_intent_ref = ""
            selected_policy = None
        elif policy_intent_ref and selected_policy is None:
            diagnostics.append("customer_goal_policy_intent_ref_unknown")
            policy_intent_ref = ""
        elif policy_intent_ref and goal_kind != "customer_goal":
            diagnostics.append("customer_goal_policy_intent_kind_invalid")
            policy_intent_ref = ""
        goal_summary = canonical_source_span_text(
            raw.get("source_text")
        )[:240]
        goal = {
            "schema_version": GOAL_IDENTITY_SCHEMA_VERSION,
            "goal_kind": goal_kind,
            "claim_type_status": claim_type_status,
            "claim_type": claim_type,
            "claim_type_exact_match": claim_type_exact_match,
            "attribute_key": attribute_key,
            "semantic_key": semantic_key,
            "policy_intent_ref": policy_intent_ref,
            "policy_goal_family": (
                _bounded_text(selected_policy.get("goal_family"), 96).lower()
                if policy_intent_ref and isinstance(selected_policy, dict)
                else ""
            ),
            "policy_intent_kind": (
                _bounded_text(selected_policy.get("intent_kind"), 64).lower()
                if policy_intent_ref and isinstance(selected_policy, dict)
                else ""
            ),
            "goal_summary": goal_summary,
            "confidence": 1.0,
            "source": "current_customer_message",
            **source_provenance,
            "source_turn_uid": source_turn_uid,
            "owner": "turn_understanding_owner",
            "source_stage": "semantic_fact_type_service",
            "claim_type_reason_code": reason_code,
        }
        goal["goal_ref"] = _goal_ref(goal)
        if goal["goal_ref"] in goals:
            diagnostics.append("duplicate_resolved_provenance")
            duplicate_provenance = True
            continue
        goals[goal["goal_ref"]] = goal

    if duplicate_provenance or invalid_provenance:
        return [], "invalid", list(dict.fromkeys(diagnostics))
    status = "valid" if goals and not diagnostics else (
        "degraded" if goals else "invalid"
    )
    return (
        [goals[key] for key in sorted(goals)],
        status,
        list(dict.fromkeys(diagnostics)),
    )


def _validate_canonical_customer_goals(
    value: Any,
    *,
    message: str,
    source_turn_uid: str = "",
) -> tuple[bool, list[str]]:
    if not isinstance(value, list):
        return False, ["customer_goals_not_array"]

    source_turn_uid = (
        source_turn_uid.strip()
        if isinstance(source_turn_uid, str)
        else ""
    ) or canonical_current_customer_turn_uid(message)
    reasons: list[str] = []
    seen_refs: set[str] = set()
    for goal in value:
        if not isinstance(goal, dict):
            reasons.append("customer_goal_not_object")
            continue
        if set(goal) != _CANONICAL_GOAL_FIELDS:
            if not str(goal.get("goal_ref") or "").strip():
                reasons.append("customer_goal_ref_missing")
            else:
                reasons.append("canonical_customer_goal_schema_invalid")
            continue

        goal_ref = str(goal.get("goal_ref") or "").strip()
        if not goal_ref:
            reasons.append("customer_goal_ref_missing")
        elif goal_ref in seen_refs:
            reasons.append("duplicate_resolved_provenance")
        else:
            seen_refs.add(goal_ref)
        if goal.get("schema_version") != GOAL_IDENTITY_SCHEMA_VERSION:
            reasons.append("customer_goal_identity_schema_invalid")
        if (
            not re.fullmatch(r"turn-[0-9a-f]{20}", source_turn_uid)
            or goal.get("source_turn_uid") != source_turn_uid
        ):
            reasons.append("customer_goal_source_turn_uid_invalid")

        if goal.get("goal_kind") not in ALLOWED_GOAL_KINDS:
            reasons.append("customer_goal_kind_invalid")

        status = str(goal.get("claim_type_status") or "")
        claim_type = str(goal.get("claim_type") or "")
        semantic_key_value = goal.get("semantic_key")
        semantic_key = _normalized_semantic_key(semantic_key_value)
        if not isinstance(semantic_key_value, str):
            reasons.append("semantic_key_schema_invalid")
            continue
        if status == "canonical":
            if (
                claim_type not in ALLOWED_FACT_TYPES
                or goal.get("claim_type_exact_match") is not True
                or semantic_key
            ):
                reasons.append("canonical_claim_type_contract_invalid")
        elif status == "unmapped":
            if (
                claim_type
                or goal.get("claim_type_exact_match") is not False
                or (
                    semantic_key_value.strip()
                    and not semantic_key
                )
            ):
                reasons.append("unmapped_claim_type_contract_invalid")
        else:
            reasons.append("claim_type_status_invalid")

        if (
            goal.get("owner") != "turn_understanding_owner"
            or goal.get("source_stage")
            != "semantic_fact_type_service"
            or goal.get("source")
            != "current_customer_message"
        ):
            reasons.append("canonical_customer_goal_provenance_invalid")

        start = goal.get("source_span_start")
        end = goal.get("source_span_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(message)
        ):
            reasons.append("customer_goal_source_span_invalid")
            continue
        expected_digest = hashlib.sha256(
            canonical_source_span_text(
                message[start:end]
            ).encode("utf-8")
        ).hexdigest()
        if goal.get("source_span_sha256") != expected_digest:
            reasons.append("customer_goal_source_digest_invalid")
        if goal.get("source_text_sha256") != expected_digest:
            reasons.append("customer_goal_source_text_digest_invalid")
        if goal_ref and goal_ref != _goal_ref(goal):
            reasons.append("customer_goal_identity_mismatch")

    reasons = list(dict.fromkeys(reasons))
    return not reasons, reasons


def goal_understanding_eligibility_status(
    understanding: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project the Turn Understanding owner verdict without recomputing it."""
    understanding = understanding if isinstance(understanding, dict) else {}
    status = str(
        understanding.get("goal_understanding_status") or ""
    ).strip().lower()
    if status not in {"valid", "degraded", "invalid"}:
        status = "unknown"
    diagnostics = understanding.get("goal_understanding_diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []
    reasons = list(dict.fromkeys(
        str(reason).strip()
        for reason in diagnostics
        if str(reason or "").strip()
    ))
    if status == "unknown" and not reasons:
        reasons = ["goal_understanding_status_missing"]
    return {
        "status": status,
        "source_stage": "turn_understanding",
        "reason_codes": reasons,
    }


def _semantic_query_from_result(result: dict[str, Any], message: str) -> dict[str, Any]:
    fact_type = str(result.get("query_fact_type") or "")
    return {
        "current_query": message,
        "primary_fact_type": fact_type,
        "secondary_fact_types": result.get("secondary_fact_types") or [],
        "retrieval_focus": result.get("retrieval_focus") or _retrieval_focus_for_fact_type(fact_type),
        "needs_visual_asset": bool(result.get("needs_visual_asset") or _visual_need_for_fact_type(fact_type)),
        "source": result.get("source", ""),
        "confidence": float(result.get("confidence") or 0),
        "reason": result.get("reason", ""),
    }


def _compact_hint(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_fact_type": result.get("query_fact_type", ""),
        "confidence": result.get("confidence", 0),
        "matched_terms": result.get("matched_terms", []),
        "source": result.get("source", ""),
    }


def _visual_need_for_fact_type(fact_type: str) -> bool:
    return fact_type in {
        "dimensions",
        "space_fit",
        "detachable",
        "installation",
        "accessories",
        "gift_policy",
    }


def _retrieval_focus_for_fact_type(fact_type: str) -> str:
    return {
        "space_fit": "product dimensions, size image, reserved width/depth/height, room fit",
        "placement_scene": "suitable placement scene and usage environment",
        "dimensions": "product dimensions and size image",
        "installation": "installation method, guide image or video",
        "detachable": "detachable structure and related size/install image",
        "odor": "new product smell and ventilation guidance",
        "material": "product material and verified material notes",
        "load_capacity": "load capacity and what items can be placed",
    }.get(fact_type, fact_type)
