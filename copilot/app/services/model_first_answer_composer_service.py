"""Evidence-bounded, review-only model-first answer composition."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any

from app.services.customer_facing_safe_handoff_service import (
    CUSTOMER_FACING_INTERNAL_REDLINE_TERMS,
)
from app.services.claim_resolution_service import (
    valid_restricted_request_boundary,
)
from app.services.media_asset_service import is_delivery_media_asset_eligible
from app.services.no_evidence_reply_policy_service import (
    _claimed_delivery_media_kinds,
    contains_unsupported_media_promise,
    has_attached_sendable_media_asset,
    media_delivery_claim_issues,
)


COMPOSER_VERSION = "model-first-answer-composer-v6"
COMPOSER_ENVELOPE_CONTRACT_VERSION = "bounded-json-envelope-v1"
COMPOSER_DECISION_INPUT_SCHEMA = "composer-decision-input/v1"
COMPOSER_DECISION_INPUT_OWNER = "model_first_answer_composer"
COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA = (
    "composer-decision-input-privacy-diagnostics/v1"
)
COMPOSER_PRIVACY_DIAGNOSTICS_OWNER = COMPOSER_DECISION_INPUT_OWNER
COMPOSER_PRIVACY_DIAGNOSTICS_MAX_DIFFS = 32
COMPOSER_RESPONSE_SCHEMA_VERSION = "composer-response/v2"
COMPOSER_RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": COMPOSER_RESPONSE_SCHEMA_VERSION,
    "type": "object",
    "required": ["clauses"],
    "additionalProperties": False,
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "goal_ref",
                    "text",
                    "evidence_refs",
                    "selected_option_refs",
                ],
                "additionalProperties": False,
                "properties": {
                    "goal_ref": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "text": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "evidence_refs": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "uniqueItems": True,
                    },
                    "selected_option_refs": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "uniqueItems": True,
                        "maxItems": 1,
                    },
                },
            },
        },
    },
}
_CLAUSE_RESPONSE_SCHEMA = COMPOSER_RESPONSE_SCHEMA[
    "properties"
]["clauses"]["items"]
_ALLOWED_OUTPUT_FIELDS = frozenset(
    COMPOSER_RESPONSE_SCHEMA["properties"]
)
_ALLOWED_CLAUSE_FIELDS = frozenset(
    _CLAUSE_RESPONSE_SCHEMA["properties"]
)
_CANONICAL_CLAUSE_FIELDS = frozenset({
    "goal_ref",
    "clause_kind",
    "text",
    "evidence_refs",
    "selected_policy_ref",
    "premise_evidence_refs",
    "inference_scope",
})
_ALLOWED_CLAUSE_KINDS = frozenset({
    "supported_fact",
    "unresolved",
    "allowed_inference",
})
_UNRESOLVED_STATUSES = {"unresolved", "conflicting", "prohibited"}
_INFERENCE_RISK_RANK = {"low": 0, "medium": 1}
_REQUEST_CLAIM_RISK_LEVELS = {
    "low",
    "medium",
    "high",
    "critical",
    "prohibited",
}
_OPTION_SELECTION_MODES = {
    "forbidden",
    "optional",
    "required",
}
COMPOSER_CLAUSE_FIELD_OWNERSHIP = {
    "model_owned": (
        "goal_ref",
        "text",
        "evidence_refs",
        "selected_option_refs",
        "presentation_order",
    ),
    "server_owned": (
        "clause_kind",
        "selected_policy_ref",
        "premise_evidence_refs",
        "inference_scope",
        "requested_claim_risk",
        "answer_strategy_risk",
        "maximum_risk_level",
        "allowed_conclusion_family",
        "allowed_variability_factor_families",
        "advice_mode",
        "required_qualifiers",
        "prohibited_claim_families",
        "trusted_domain_pack_ref",
        "pack_content_sha256",
        "restricted_request_boundary",
    ),
    "mixed_or_not_proven": (),
}
_NON_RENDERABLE_GOAL_KINDS = {
    "evidence_dependency",
    "service_action",
    "media_request",
    "media_candidate",
    "contextual_constraint",
}
_AUTHORITATIVE_GOAL_SCHEMA = "turn-understanding-goal-identity/v2"
_AUTHORITATIVE_GOAL_OWNER = "turn_understanding_owner"
_AUTHORITATIVE_GOAL_SOURCE = "current_customer_message"
_DECISION_INPUT_FIELDS = {
    "schema_version",
    "owner",
    "request_ref",
    "source_turn_ref",
    "customer_goal",
    "recent_conversation_turns",
    "product_scope",
    "requested_claims",
    "admitted_evidence",
    "claim_resolutions",
    "bounded_inference_policies",
    "trusted_domain_policy_context",
    "service_actions",
    "media_candidates",
    "conflicting_claim_count",
    "safety_constraints",
    "context_stats",
    "actual_attached_media_types",
    "used_for_final_reply",
    "used_as_evidence",
    "can_change_can_send",
}
_DECISION_GOAL_FIELDS = {
    "schema_version",
    "goal_ref",
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "attribute_key",
    "semantic_key",
    "goal_summary",
    "source",
    "source_span_start",
    "source_span_end",
    "source_span_sha256",
    "source_text_sha256",
    "source_turn_uid",
    "owner",
    "source_stage",
    "supporting_only",
    "supporting_for_goal_ref",
    "customer_goal_eligible",
}
_DECISION_RESOLUTION_FIELDS = {
    "claim_uid",
    "goal_ref",
    "goal_kind",
    "claim_type",
    "claim_type_status",
    "attribute_key",
    "semantic_key",
    "goal_summary",
    "status",
    "evidence_uids",
    "support_basis",
    "premise_evidence_uids",
    "inference_policy_refs",
    "scope_qualifier",
    "inference_risk_level",
    "maximum_risk_level",
    "allowed_conclusion_family",
    "allowed_variability_factor_families",
    "advice_mode",
    "inference_review_only",
    "required_qualifiers",
    "prohibited_extensions",
    "eligible_policy_options",
    "supporting_only",
    "supporting_for_goal_ref",
    "requested_claim_risk",
    "restricted_request_boundary",
}
_DECISION_OPTION_FIELDS = {
    "policy_ref",
    "trusted_domain_pack_ref",
    "pack_content_sha256",
    "applicable_goal_ref",
    "policy_intent_ref",
    "goal_family",
    "intent_kind",
    "premise_evidence_refs",
    "premise_families",
    "allowed_scope",
    "allowed_conclusion_family",
    "allowed_variability_factor_families",
    "advice_mode",
    "forbidden_claim_families",
    "maximum_risk",
    "requested_risk",
    "requested_claim_risk",
    "answer_strategy_risk",
    "required_qualifiers",
    "review_only",
    "used_for_evidence",
    "used_for_fact_support",
    "can_change_can_send",
    "option_provenance",
    "restricted_request_boundary",
}
_DECISION_POLICY_FIELDS = {
    "policy_ref",
    "pack_content_sha256",
    "policy_intent_ref",
    "goal_family",
    "intent_kind",
    "premise_fact_families",
    "allowed_scope",
    "allowed_conclusion_family",
    "allowed_variability_factor_families",
    "advice_mode",
    "maximum_risk_level",
    "required_qualifiers",
    "prohibited_claim_families",
    "review_only",
    "used_for_evidence",
    "used_for_fact_support",
    "can_change_can_send",
}
_DECISION_EVIDENCE_FIELDS = {
    "evidence_uid",
    "admission_owner",
    "source",
    "source_type",
    "evidence_role",
    "review_status",
    "fact_review_status",
    "gate_status",
    "direct_answer_allowed",
    "identity_scope_refs",
    "fact_type",
    "attribute_key",
    "content",
    "value",
    "original_value",
    "provenance",
}
_DECISION_RECENT_TURN_FIELDS = {
    "role",
    "content",
    "turn_index",
}
_DECISION_SERVICE_ACTION_FIELDS = {
    "evidence_uid",
    "text",
    "non_fact",
}
_DECISION_MEDIA_FIELDS = {
    "evidence_uid",
    "asset_type",
    "media_role",
    "non_fact",
}
_DECISION_PRODUCT_SCOPE_FIELDS = {
    "resolved",
    "variant_context_present",
}
_DECISION_CONTEXT_STATS_FIELDS = {
    "admitted_evidence_count",
    "admitted_evidence_source_distribution",
    "estimated_token_count",
    "recent_turn_count",
    "trim_reasons",
    "excluded_context_categories",
}
_DECISION_SAFETY_FIELDS = {
    "only_admitted_evidence_for_facts",
    "unresolved_or_conflicting_claims_cannot_be_asserted",
    "service_actions_and_media_are_not_facts",
}
_DECISION_TRUSTED_PACK_FIELDS = {
    "schema_version",
    "status",
    "trusted_owner",
    "selection_source",
    "pack_ref",
    "pack_schema_version",
    "pack_content_sha256",
    "domain_ref",
    "binding_summary",
    "provenance",
    "selected_at_stage",
    "validation_reasons",
    "used_for_evidence",
    "used_for_fact_support",
    "can_change_can_send",
}
_DECISION_RESTRICTED_BOUNDARY_FIELDS = {
    "schema_version",
    "status",
    "reason_code",
    "requested_claim_risk",
    "policy_intent_ref",
    "policy_goal_family",
    "policy_intent_kind",
    "high_risk_claim_families",
    "must_remain_unresolved",
    "allows_bounded_alternative",
}
_DECISION_OPTION_PROVENANCE_FIELDS = {
    "policy_owner",
    "filter_owner",
    "premise_owner",
    "intent_narrowed",
    "alternative_for_restricted_request",
}
_DECISION_EVIDENCE_PROVENANCE_FIELDS = {
    "origin_ref",
    "source_container",
}
_DECISION_IDENTITY_SCOPE_FIELDS = {
    "namespace",
    "scope_ref",
}
_DECISION_IDENTITY_SCOPE_NAMESPACES = {
    "sku_code",
    "i_id",
    "product_id",
}
_DECISION_CONTROLLED_REFERENCE_FIELDS = {
    "request_ref",
    "source_turn_ref",
    "source_turn_uid",
    "goal_ref",
    "claim_uid",
    "evidence_uid",
    "supporting_for_goal_ref",
    "applicable_goal_ref",
    "policy_ref",
    "trusted_domain_pack_ref",
    "pack_ref",
    "domain_ref",
    "evidence_uids",
    "premise_evidence_uids",
    "premise_evidence_refs",
    "inference_policy_refs",
    "origin_ref",
    "scope_ref",
    "namespace",
}
_DECISION_STRUCTURED_HASH_FIELDS = {
    "source_span_sha256",
    "source_text_sha256",
    "pack_content_sha256",
}
_DIAGNOSTIC_GOAL_REFERENCE_FIELDS = {
    "goal_ref",
    "applicable_goal_ref",
    "supporting_for_goal_ref",
}
_DIAGNOSTIC_CLAIM_REFERENCE_FIELDS = {"claim_uid"}
_DIAGNOSTIC_EVIDENCE_REFERENCE_FIELDS = {
    "evidence_uid",
    "evidence_uids",
    "premise_evidence_uids",
    "premise_evidence_refs",
}
_DIAGNOSTIC_POLICY_REFERENCE_FIELDS = {
    "policy_ref",
    "policy_intent_ref",
    "inference_policy_refs",
}
_DIAGNOSTIC_OPTION_REFERENCE_FIELDS = {
    "option_ref",
    "selected_option_refs",
}
_DIAGNOSTIC_PACK_REFERENCE_FIELDS = {
    "trusted_domain_pack_ref",
    "pack_ref",
    "domain_ref",
}
_DIAGNOSTIC_OWNER_PROVENANCE_FIELDS = {
    "owner",
    "admission_owner",
    "trusted_owner",
    "source_stage",
    "selected_at_stage",
    "policy_owner",
    "filter_owner",
    "premise_owner",
}
_DIAGNOSTIC_FREE_TEXT_FIELDS = {
    "customer_goal",
    "content",
    "value",
    "original_value",
    "goal_summary",
    "text",
}
_DIAGNOSTIC_ENUM_FIELDS = {
    "role",
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "attribute_key",
    "semantic_key",
    "source",
    "source_type",
    "evidence_role",
    "review_status",
    "fact_review_status",
    "gate_status",
    "status",
    "support_basis",
    "scope_qualifier",
    "inference_risk_level",
    "maximum_risk_level",
    "allowed_scope",
    "allowed_conclusion_family",
    "advice_mode",
    "requested_claim_risk",
    "answer_strategy_risk",
    "namespace",
    "source_container",
}
_DIAGNOSTIC_SAFE_PATH_FIELDS = frozenset().union(
    _DECISION_INPUT_FIELDS,
    _DECISION_GOAL_FIELDS,
    _DECISION_RESOLUTION_FIELDS,
    _DECISION_OPTION_FIELDS,
    _DECISION_POLICY_FIELDS,
    _DECISION_EVIDENCE_FIELDS,
    _DECISION_RECENT_TURN_FIELDS,
    _DECISION_SERVICE_ACTION_FIELDS,
    _DECISION_MEDIA_FIELDS,
    _DECISION_PRODUCT_SCOPE_FIELDS,
    _DECISION_CONTEXT_STATS_FIELDS,
    _DECISION_SAFETY_FIELDS,
    _DECISION_TRUSTED_PACK_FIELDS,
    _DECISION_RESTRICTED_BOUNDARY_FIELDS,
    _DECISION_OPTION_PROVENANCE_FIELDS,
    _DECISION_EVIDENCE_PROVENANCE_FIELDS,
    _DECISION_IDENTITY_SCOPE_FIELDS,
    {"provenance", "product_scope", "safety_constraints"},
)
_PROCESS_LANGUAGE_TERMS = (
    "帮您核对",
    "我先核对",
    "确认后回复",
    "确认后再回复",
    "请稍等",
    "您稍等",
    "转人工",
    "资料显示",
    "系统显示",
    "公司资料",
)
_INTERNAL_LANGUAGE_TRIGGER_CATEGORIES = {
    "不直接说": "reply_policy_meta_language",
    "不直接承诺": "reply_policy_meta_language",
    "不能承诺": "reply_policy_meta_language",
    "不敢保证": "reply_policy_meta_language",
    "缺少证据": "evidence_process_language",
    "没有证据": "evidence_process_language",
    "人工审核": "review_process_language",
    "需要人工审核": "review_process_language",
    "有依据再": "evidence_process_language",
    "当前知识库": "internal_knowledge_language",
    "知识库": "internal_knowledge_language",
    "final gate": "internal_system_language",
    "RAG": "internal_system_language",
}
_PROCESS_LANGUAGE_TRIGGER_CATEGORIES = {
    "帮您核对": "deferred_process_language",
    "我先核对": "deferred_process_language",
    "确认后回复": "deferred_process_language",
    "确认后再回复": "deferred_process_language",
    "请稍等": "deferred_process_language",
    "您稍等": "deferred_process_language",
    "转人工": "handoff_process_language",
    "资料显示": "source_process_language",
    "系统显示": "source_process_language",
    "公司资料": "source_process_language",
}


def _structured_sha256(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return (
        candidate
        if len(candidate) == 64
        and all(character in "0123456789abcdef" for character in candidate)
        else ""
    )


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ordered_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _diagnostic_json_type(value: Any) -> str:
    if value is _DIAGNOSTIC_MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _diagnostic_value_size(value: Any) -> int | None:
    if isinstance(value, (str, list, dict)):
        return len(value)
    return None


def _diagnostic_value_sha256(value: Any) -> str:
    from app.services.formal_knowledge_database_guard_service import (
        formal_kb_audit_hmac_key,
    )
    from app.services.high_quality_long_conversation_review_service import (
        stable_evaluation_alias,
    )

    secret = formal_kb_audit_hmac_key()
    if not secret:
        raise ValueError("diagnostic_alias_key_required")
    if value is _DIAGNOSTIC_MISSING:
        serialized = "missing"
    else:
        try:
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            serialized = f"type:{_diagnostic_json_type(value)}"
    alias = stable_evaluation_alias(
        "diagnostic_value",
        serialized,
        alias_secret=secret,
    )
    # Keep the existing fixed-width diagnostics schema after keyed aliasing.
    return hashlib.sha256(alias.encode("ascii")).hexdigest()


def _diagnostic_path_segment(value: Any) -> str:
    text = str(value or "")
    if (
        text in _DIAGNOSTIC_SAFE_PATH_FIELDS
        and len(text) <= 64
    ):
        return text
    return _privacy_diagnostic_alias("key", text)


def _diagnostic_field_role(
    field_name: str,
    first: Any,
    second: Any,
) -> str:
    if field_name in _DIAGNOSTIC_GOAL_REFERENCE_FIELDS:
        return "controlled_goal_ref"
    if field_name in _DIAGNOSTIC_CLAIM_REFERENCE_FIELDS:
        return "controlled_claim_ref"
    if field_name in _DIAGNOSTIC_EVIDENCE_REFERENCE_FIELDS:
        return "controlled_evidence_ref"
    if field_name in _DIAGNOSTIC_POLICY_REFERENCE_FIELDS:
        return "controlled_policy_ref"
    if field_name in _DIAGNOSTIC_OPTION_REFERENCE_FIELDS:
        return "controlled_option_ref"
    if field_name in _DIAGNOSTIC_PACK_REFERENCE_FIELDS:
        return "controlled_pack_ref"
    if field_name in {"source_span_sha256", "source_text_sha256"}:
        return "source_text_hash"
    if field_name == "pack_content_sha256":
        return "canonical_hash"
    if field_name in _DIAGNOSTIC_OWNER_PROVENANCE_FIELDS:
        return "owner_provenance"
    if isinstance(first, dict) or isinstance(second, dict):
        return "object_container"
    if isinstance(first, list) or isinstance(second, list):
        return "list_container"
    if isinstance(first, bool) or isinstance(second, bool):
        return "boolean"
    if (
        isinstance(first, int)
        and not isinstance(first, bool)
    ) or (
        isinstance(second, int)
        and not isinstance(second, bool)
    ):
        return "integer"
    if field_name in _DIAGNOSTIC_FREE_TEXT_FIELDS:
        return "free_text"
    if field_name in _DIAGNOSTIC_ENUM_FIELDS:
        return "enum"
    return "unknown"


def _diagnostic_reference_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(
        isinstance(item, str) for item in value
    ):
        return list(value)
    return []


def _diagnostic_trusted_reference_class(
    role: str,
    first: Any,
    *,
    provenance_validated: bool,
) -> str:
    controlled_roles = {
        "controlled_goal_ref",
        "controlled_claim_ref",
        "controlled_evidence_ref",
        "controlled_policy_ref",
        "controlled_option_ref",
        "controlled_pack_ref",
    }
    if role in {"source_text_hash", "canonical_hash"}:
        return (
            role
            if provenance_validated and bool(_structured_sha256(first))
            else "untrusted_reference"
        )
    if role not in controlled_roles:
        return "not_applicable"
    values = _diagnostic_reference_values(first)
    def valid_reference(item: str) -> bool:
        candidate = item.strip()
        local, separator, domain = candidate.partition("@")
        email_shaped = bool(
            separator and local and "." in domain
        )
        long_numeric = (
            len(candidate) >= 12 and candidate.isdigit()
        )
        return bool(
            candidate
            and "[" not in candidate
            and "]" not in candidate
            and not email_shaped
            and not long_numeric
        )
    valid = bool(values) and all(
        valid_reference(item)
        for item in values
    )
    return (
        role
        if provenance_validated and valid
        else "untrusted_reference"
    )


def _diagnostic_projection_action(
    category: str,
    role: str,
) -> str:
    if category == "privacy_reprojection_changed":
        return "privacy_reprojection_changed"
    if category in {"missing_in_d1", "missing_in_d2", "object_key_changed"}:
        return "structure_changed"
    if category in {"array_length_changed", "array_order_changed"}:
        return category
    if category == "type_changed":
        return "type_changed"
    if category == "canonical_order_only":
        return "canonical_order_only"
    if role.startswith("controlled_") or role.endswith("_hash"):
        return "controlled_value_changed"
    return "serialization_changed"


_DIAGNOSTIC_MISSING = object()


def _privacy_diagnostic_base() -> dict[str, Any]:
    return {
        "schema_version": COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA,
        "owner": COMPOSER_PRIVACY_DIAGNOSTICS_OWNER,
        "request_alias": "",
        "turn_alias": "",
        "stage_reached": "initialized",
        "decision_input_build_attempted": False,
        "decision_input_build_completed": False,
        "d1_generated": False,
        "d2_generated": False,
        "d1_ordered_sha256": "",
        "d1_canonical_sha256": "",
        "d2_ordered_sha256": "",
        "d2_canonical_sha256": "",
        "privacy_projection_equal": None,
        "diff_total_count": 0,
        "diff_retained_count": 0,
        "diff_truncated_count": 0,
        "diff_truncated": False,
        "diff_category_counts": {},
        "first_diff_path": "",
        "retained_diff_paths": [],
        "diffs": [],
        "early_return_reason": "",
        "provider_material_attempted": False,
        "provider_material_completed": False,
        "transport_attempted": False,
        "transport_forwarded": False,
        "diagnostic_error": "",
        "used_for_final_reply": False,
        "used_as_evidence": False,
        "can_change_can_send": False,
        "can_change_model_call_count": False,
    }


def _privacy_diagnostic_initialize(
    sink: dict[str, Any] | None,
) -> None:
    if not isinstance(sink, dict):
        return
    try:
        sink.clear()
        sink.update(_privacy_diagnostic_base())
    except Exception:
        return


def _privacy_diagnostic_update(
    sink: dict[str, Any] | None,
    **values: Any,
) -> None:
    if not isinstance(sink, dict):
        return
    try:
        sink.update(deepcopy(values))
    except Exception:
        try:
            sink["diagnostic_error"] = "diagnostics_sink_update_failed"
        except Exception:
            return


def _privacy_diagnostic_finish(
    sink: dict[str, Any] | None,
    result: dict[str, Any],
    *,
    stage: str,
) -> None:
    _privacy_diagnostic_update(
        sink,
        stage_reached=stage,
        early_return_reason=str(
            result.get("rejection_reason") or ""
        ),
    )


def _privacy_diagnostic_alias(kind: str, value: Any) -> str:
    from app.services.formal_knowledge_database_guard_service import (
        formal_kb_audit_hmac_key,
    )
    from app.services.high_quality_long_conversation_review_service import (
        stable_evaluation_alias,
    )

    text = str(value or "").strip()
    if not text:
        return ""
    secret = formal_kb_audit_hmac_key()
    if not secret:
        raise ValueError("diagnostic_alias_key_required")
    return stable_evaluation_alias(
        kind,
        text,
        alias_secret=secret,
    )


def _privacy_diff_record(
    *,
    path: str,
    field_name: str,
    first: Any,
    second: Any,
    category: str,
    provenance_validated: bool,
) -> dict[str, Any]:
    role = _diagnostic_field_role(field_name, first, second)
    return {
        "json_path": path,
        "field_role": role,
        "d1_type": _diagnostic_json_type(first),
        "d2_type": _diagnostic_json_type(second),
        "d1_length_or_count": _diagnostic_value_size(first),
        "d2_length_or_count": _diagnostic_value_size(second),
        "d1_value_sha256": _diagnostic_value_sha256(first),
        "d2_value_sha256": _diagnostic_value_sha256(second),
        "projection_action_category": _diagnostic_projection_action(
            category,
            role,
        ),
        "difference_category": category,
        "trusted_reference_class": (
            _diagnostic_trusted_reference_class(
                role,
                first,
                provenance_validated=provenance_validated,
            )
        ),
        "owner_provenance_validation_status": (
            "validated_before_privacy_idempotence"
            if provenance_validated
            else "not_validated"
        ),
    }


def _structured_privacy_diff(
    first: Any,
    second: Any,
    *,
    provenance_validated: bool,
    max_retained: int = COMPOSER_PRIVACY_DIAGNOSTICS_MAX_DIFFS,
) -> tuple[int, list[dict[str, Any]], dict[str, int]]:
    retained: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    total = 0

    def add(
        path: str,
        field_name: str,
        left: Any,
        right: Any,
        category: str,
    ) -> None:
        nonlocal total
        total += 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(retained) >= max_retained:
            return
        retained.append(_privacy_diff_record(
            path=path,
            field_name=field_name,
            first=left,
            second=right,
            category=category,
            provenance_validated=provenance_validated,
        ))

    def compare(
        left: Any,
        right: Any,
        path: str,
        field_name: str,
    ) -> None:
        if left is _DIAGNOSTIC_MISSING:
            add(path, field_name, left, right, "missing_in_d1")
            return
        if right is _DIAGNOSTIC_MISSING:
            add(path, field_name, left, right, "missing_in_d2")
            return
        left_type = _diagnostic_json_type(left)
        right_type = _diagnostic_json_type(right)
        if left_type != right_type:
            add(path, field_name, left, right, "type_changed")
            return
        if isinstance(left, dict):
            if left == right:
                if _ordered_json_sha256(left) != _ordered_json_sha256(right):
                    add(
                        path,
                        field_name,
                        left,
                        right,
                        "canonical_order_only",
                    )
                return
            left_keys = list(left)
            right_keys = list(right)
            if set(left_keys) != set(right_keys):
                add(path, field_name, left, right, "object_key_changed")
            for key in left_keys:
                segment = _diagnostic_path_segment(key)
                compare(
                    left[key],
                    right.get(key, _DIAGNOSTIC_MISSING),
                    f"{path}.{segment}",
                    str(key),
                )
            for key in right_keys:
                if key in left:
                    continue
                segment = _diagnostic_path_segment(key)
                compare(
                    _DIAGNOSTIC_MISSING,
                    right[key],
                    f"{path}.{segment}",
                    str(key),
                )
            return
        if isinstance(left, list):
            if left == right:
                return
            if len(left) != len(right):
                add(
                    path,
                    field_name,
                    left,
                    right,
                    "array_length_changed",
                )
            elif sorted(
                _diagnostic_value_sha256(item) for item in left
            ) == sorted(
                _diagnostic_value_sha256(item) for item in right
            ):
                add(
                    path,
                    field_name,
                    left,
                    right,
                    "array_order_changed",
                )
                return
            for index in range(max(len(left), len(right))):
                compare(
                    left[index]
                    if index < len(left)
                    else _DIAGNOSTIC_MISSING,
                    right[index]
                    if index < len(right)
                    else _DIAGNOSTIC_MISSING,
                    f"{path}[{index}]",
                    field_name,
                )
            return
        if left != right:
            add(
                path,
                field_name,
                left,
                right,
                "privacy_reprojection_changed"
                if isinstance(left, str)
                else "scalar_changed",
            )
            return
        try:
            if _ordered_json_sha256(left) != _ordered_json_sha256(right):
                add(
                    path,
                    field_name,
                    left,
                    right,
                    "serialization_changed",
                )
        except (TypeError, ValueError):
            return

    compare(first, second, "$", "")
    return total, retained, category_counts


class ModelFirstAnswerComposerService:
    """Compose one candidate reply without owning facts, safety, or delivery."""

    def compose(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        copilot_context: dict[str, Any] | None = None,
        client: Any | None = None,
        privacy_diagnostics_sink: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        diagnostics_enabled = isinstance(privacy_diagnostics_sink, dict)
        if diagnostics_enabled:
            _privacy_diagnostic_initialize(privacy_diagnostics_sink)
        original = deepcopy(response)
        source_context = self._minimal_context(original)
        result = self._base_result(source_context)
        if not source_context:
            result["rejection_reason"] = "minimal_decision_context_missing"
            if diagnostics_enabled:
                _privacy_diagnostic_finish(
                    privacy_diagnostics_sink,
                    result,
                    stage="minimal_context_missing",
                )
            return original, result

        decision_input, decision_error = (
            self.build_composer_decision_input(
                original,
                customer_message=customer_message,
                privacy_diagnostics_sink=privacy_diagnostics_sink,
            )
        )
        if decision_error:
            result["rejection_reason"] = decision_error
            if diagnostics_enabled:
                _privacy_diagnostic_finish(
                    privacy_diagnostics_sink,
                    result,
                    stage="decision_input_rejected",
                )
            return original, result
        result["provider_diagnostics"].update({
            "decision_input_schema": COMPOSER_DECISION_INPUT_SCHEMA,
            "decision_input_sha256": _canonical_json_sha256(
                decision_input
            ),
            "decision_input_privacy_projected": True,
            "decision_input_used_for_final_reply": True,
            "decision_input_used_as_evidence": False,
            "decision_input_can_change_can_send": False,
        })
        if diagnostics_enabled:
            _privacy_diagnostic_update(
                privacy_diagnostics_sink,
                provider_material_attempted=True,
                stage_reached="provider_material_build",
            )
        material, material_error = (
            self.build_provider_material_from_decision_input(
                decision_input
            )
        )
        if material_error:
            result["rejection_reason"] = material_error
            if diagnostics_enabled:
                _privacy_diagnostic_finish(
                    privacy_diagnostics_sink,
                    result,
                    stage="provider_material_rejected",
                )
            return original, result
        if diagnostics_enabled:
            _privacy_diagnostic_update(
                privacy_diagnostics_sink,
                provider_material_completed=True,
                stage_reached="provider_material_completed",
            )
        evidence = material["evidence"]
        uid_by_ref = material["uid_by_ref"]
        known_refs = set(uid_by_ref)
        partitions = material["partitions"]
        goal_uid_by_ref = material["goal_uid_by_ref"]
        customer_goals = material["customer_goals"]
        offered_option_bindings = material[
            "offered_option_bindings"
        ]
        presentation_order = list(
            partitions.get("presentation_order") or []
        )
        result["input_eligibility"] = dict(
            partitions.get("eligibility_metrics") or {}
        )
        payload = material["prompt_payload"]
        system_prompt = material["system_prompt"]
        provider_messages = material["messages"]
        output_contract = self._output_contract_projection()
        result["provider_diagnostics"].update({
            "system_prompt_sha256": hashlib.sha256(
                system_prompt.encode("utf-8")
            ).hexdigest(),
            "prompt_payload_sha256": _canonical_json_sha256(payload),
            "provider_input_sha256": _canonical_json_sha256(
                provider_messages
            ),
            "offered_projection_sha256": _canonical_json_sha256(
                customer_goals
            ),
            "output_contract_sha256": _canonical_json_sha256(
                output_contract
            ),
            "response_schema_sha256": output_contract[
                "response_schema_sha256"
            ],
            "prompt_schema_summary_sha256": output_contract[
                "prompt_schema_summary_sha256"
            ],
            "offered_goal_refs": [
                str(goal["goal_ref"]) for goal in customer_goals
            ],
            "presentation_order": presentation_order,
            "presentation_order_sha256": _canonical_json_sha256(
                presentation_order
            ),
            "offered_option_refs": sorted(
                offered_option_bindings
            ),
        })

        if not customer_goals:
            result["provider_diagnostics"][
                "decision_input_used_for_final_reply"
            ] = False
            result.update({
                "status": "accepted",
                "rejection_reason": "",
                "candidate_reply": "",
                "used_for_final_reply": False,
                "composition_applicable": False,
            })
            updated = deepcopy(original)
            updated["model_first_answer_composer"] = result
            updated.setdefault("evidence_debug", {})[
                "model_first_answer_composer"
            ] = result
            if diagnostics_enabled:
                _privacy_diagnostic_finish(
                    privacy_diagnostics_sink,
                    result,
                    stage="composition_not_applicable",
                )
            return updated, result

        started = time.perf_counter()
        try:
            if client is None:
                from app.llm.client import get_llm_client

                client = get_llm_client()
            if not getattr(client, "api_key", ""):
                result["rejection_reason"] = "formal_llm_not_configured"
                if diagnostics_enabled:
                    _privacy_diagnostic_finish(
                        privacy_diagnostics_sink,
                        result,
                        stage="transport_not_configured",
                    )
                return original, result
            result["provider_diagnostics"]["model_call_count"] = 1
            result["provider_diagnostics"]["model_name"] = str(
                getattr(client, "model", "") or ""
            ).strip()
            if diagnostics_enabled:
                _privacy_diagnostic_update(
                    privacy_diagnostics_sink,
                    transport_attempted=True,
                    transport_forwarded=False,
                    stage_reached="transport_attempted",
                )
            completion = client.create_chat_completion(
                model=client.model,
                messages=provider_messages,
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
                _single_attempt_no_repair=True,
            )
            if diagnostics_enabled:
                _privacy_diagnostic_update(
                    privacy_diagnostics_sink,
                    transport_forwarded=True,
                    stage_reached="transport_forwarded",
                )
            choice = completion.choices[0] if completion.choices else None
            content = str(
                getattr(getattr(choice, "message", None), "content", "") or ""
            )
            finish_reason = str(
                getattr(choice, "finish_reason", "") or ""
            )
            self._record_provider_response(
                result,
                content=content,
                finish_reason=finish_reason,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            envelope = result["provider_diagnostics"]["response_envelope"]
            if finish_reason == "length":
                result["rejection_reason"] = "composer_truncated_response"
                result["validation_diagnostics"] = self._diagnostics(
                    "truncated_response",
                    json_path="$",
                    expected_type="complete_json_object",
                    actual_type=envelope,
                )
                if diagnostics_enabled:
                    _privacy_diagnostic_finish(
                        privacy_diagnostics_sink,
                        result,
                        stage="provider_response_rejected",
                    )
                return original, result
            if not content.strip():
                result["rejection_reason"] = "composer_completion_empty"
                result["validation_diagnostics"] = self._diagnostics(
                    "completion_empty",
                    json_path="$",
                    expected_type="json_object",
                    actual_type="empty",
                )
                if diagnostics_enabled:
                    _privacy_diagnostic_finish(
                        privacy_diagnostics_sink,
                        result,
                        stage="provider_response_rejected",
                    )
                return original, result
            (
                json_payload,
                envelope,
                envelope_unwrap_count,
                envelope_error,
            ) = self._unwrap_json_envelope(content)
            result["provider_diagnostics"].update({
                "response_envelope": envelope,
                "envelope_unwrap_count": envelope_unwrap_count,
            })
            if envelope_error:
                result["rejection_reason"] = "composer_fenced_or_free_text"
                result["validation_diagnostics"] = self._diagnostics(
                    envelope_error,
                    json_path="$",
                    expected_type="raw_json_or_single_json_fence",
                    actual_type=envelope,
                )
                if diagnostics_enabled:
                    _privacy_diagnostic_finish(
                        privacy_diagnostics_sink,
                        result,
                        stage="provider_response_rejected",
                    )
                return original, result
            try:
                parsed = json.loads(json_payload)
            except json.JSONDecodeError:
                result["rejection_reason"] = "composer_json_parse_error"
                result["validation_diagnostics"] = self._diagnostics(
                    "json_parse_error",
                    json_path="$",
                    expected_type="complete_json_object",
                    actual_type=envelope,
                )
                if diagnostics_enabled:
                    _privacy_diagnostic_finish(
                        privacy_diagnostics_sink,
                        result,
                        stage="provider_response_rejected",
                    )
                return original, result
        except Exception as exc:
            result["provider_diagnostics"]["provider_latency_ms"] = int(
                (time.perf_counter() - started) * 1000
            )
            result["provider_diagnostics"]["provider_error_type"] = type(
                exc
            ).__name__
            result["validation_diagnostics"] = self._diagnostics(
                "provider_error",
                json_path="$",
                expected_type="completion",
                actual_type=type(exc).__name__,
            )
            result["rejection_reason"] = f"formal_llm_error:{type(exc).__name__}"
            if diagnostics_enabled:
                _privacy_diagnostic_finish(
                    privacy_diagnostics_sink,
                    result,
                    stage="provider_error",
                )
            return original, result

        validation_error, validation_diagnostics = (
            self._validate_output_with_diagnostics(
            parsed,
            known_refs=known_refs,
            customer_goals=customer_goals,
            presentation_order=presentation_order,
            offered_option_bindings=offered_option_bindings,
            non_renderable_goal_refs=set(
                partitions.get("non_renderable_goal_refs") or set()
            ),
            response=original,
            )
        )
        result["validation_diagnostics"] = validation_diagnostics
        if validation_error:
            result["rejection_reason"] = validation_error
            if validation_error == "composer_unsupported_media_promise":
                result["media_claim_diagnostics"] = (
                    self._media_claim_diagnostics(
                        parsed,
                        customer_goals=customer_goals,
                        response=original,
                        minimal_context=source_context,
                    )
                )
            if diagnostics_enabled:
                _privacy_diagnostic_finish(
                    privacy_diagnostics_sink,
                    result,
                    stage="composer_output_rejected",
                )
            return original, result

        result["input_eligibility"]["non_customer_goal_clause_count"] = 0
        result["input_eligibility"]["customer_goal_clause_coverage"] = {
            "numerator": len(customer_goals),
            "denominator": len(customer_goals),
            "rate": 1.0 if customer_goals else None,
        }
        ordered_clauses = list(parsed["clauses"])
        reply = "".join(
            str(item["text"]).strip() for item in ordered_clauses
        )
        goals_by_ref = {
            str(goal["goal_ref"]): goal for goal in customer_goals
        }
        used_refs = sorted({
            str(ref)
            for item in ordered_clauses
            for ref in item["evidence_refs"]
        })
        unresolved_types = {
            str(goals_by_ref[str(clause["goal_ref"])]["claim_type"])
            for clause in ordered_clauses
            if goals_by_ref[
                str(clause["goal_ref"])
            ]["resolution_status"] in _UNRESOLVED_STATUSES
            and clause["clause_kind"] == "unresolved"
            and str(
                goals_by_ref[
                    str(clause["goal_ref"])
                ].get("claim_type")
                or ""
            ).strip()
        }
        allowed_reasoning = sorted({
            str(clause.get("inference_scope") or "")
            for clause in ordered_clauses
            if clause.get("clause_kind") == "allowed_inference"
            and str(clause.get("inference_scope") or "")
        })
        result.update({
            "status": "accepted",
            "rejection_reason": "",
            "candidate_reply": reply,
            "used_evidence_uids": [uid_by_ref[ref] for ref in used_refs],
            "unresolved_claim_types": sorted(unresolved_types),
            "covered_goal_refs": [
                goal_uid_by_ref[str(clause["goal_ref"])]
                for clause in ordered_clauses
            ],
            "clauses": [
                {
                    "clause_ref": f"C{index}",
                    "goal_ref": goal_uid_by_ref[str(clause["goal_ref"])],
                    "clause_kind": str(clause["clause_kind"]),
                    "text": str(clause["text"]).strip(),
                    "evidence_uids": [
                        uid_by_ref[str(ref)] for ref in clause["evidence_refs"]
                    ],
                    **self._selected_policy_clause_metadata(
                        clause,
                        goals_by_ref[str(clause["goal_ref"])],
                        offered_option_bindings=offered_option_bindings,
                        uid_by_ref=uid_by_ref,
                    ),
                }
                for index, clause in enumerate(ordered_clauses, start=1)
            ],
            "used_for_final_reply": True,
            "composition_applicable": True,
            "allowed_low_risk_reasoning": allowed_reasoning,
        })
        updated = deepcopy(original)
        updated["suggested_reply"] = reply
        updated["draft_reply"] = reply
        updated["generation_mode"] = "model_first_answer_composer"
        updated["requires_human_review"] = True
        updated["can_send"] = False
        updated["sendable_reply"] = ""
        updated["reply_status"] = "needs_human_review"
        updated["reason_for_review"] = self._append_reason(
            str(updated.get("reason_for_review") or ""),
            "model_first_candidate_review_only",
        )
        updated["model_first_answer_composer"] = result
        updated.setdefault("evidence_debug", {})["model_first_answer_composer"] = result
        if diagnostics_enabled:
            _privacy_diagnostic_finish(
                privacy_diagnostics_sink,
                result,
                stage="completed",
            )
        return updated, result

    @staticmethod
    def _minimal_context(response: dict[str, Any]) -> dict[str, Any]:
        candidates = (
            response.get("minimal_decision_context"),
            (response.get("evidence_debug") or {}).get("minimal_decision_context"),
        )
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate:
                return deepcopy(candidate)
        return {}

    @staticmethod
    def _allowlisted_rows(
        value: Any,
        allowed_fields: set[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [
            {
                key: deepcopy(item)
                for key, item in row.items()
                if key in allowed_fields
            }
            for row in value
            if isinstance(row, dict)
        ]

    @staticmethod
    def _anonymous_reference(kind: str, value: Any) -> str:
        digest = _canonical_json_sha256(value)
        return f"{kind}-{digest[:20]}"

    @classmethod
    def _privacy_project_decision_value(
        cls,
        value: Any,
        *,
        field_name: str = "",
    ) -> Any:
        """Reuse the formal projector while preserving owner-controlled refs."""
        if field_name in (
            _DECISION_CONTROLLED_REFERENCE_FIELDS
            | _DECISION_STRUCTURED_HASH_FIELDS
        ):
            return deepcopy(value)
        if isinstance(value, dict):
            return {
                str(key): cls._privacy_project_decision_value(
                    item,
                    field_name=str(key),
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                cls._privacy_project_decision_value(
                    item,
                    field_name=field_name,
                )
                for item in value
            ]
        if isinstance(value, tuple):
            return [
                cls._privacy_project_decision_value(
                    item,
                    field_name=field_name,
                )
                for item in value
            ]
        if isinstance(value, str):
            from app.services.canonical_conversation_turn_service import (
                project_value_for_external_model,
            )

            return project_value_for_external_model(value)
        return value

    @classmethod
    def _record_decision_input_privacy_diagnostics(
        cls,
        sink: dict[str, Any] | None,
        *,
        d1: dict[str, Any],
        d2: Any,
        provenance_validated: bool,
    ) -> None:
        if not isinstance(sink, dict):
            return
        try:
            total, retained, category_counts = (
                _structured_privacy_diff(
                    d1,
                    d2,
                    provenance_validated=provenance_validated,
                )
            )
            paths = [str(item["json_path"]) for item in retained]
            _privacy_diagnostic_update(
                sink,
                request_alias=_privacy_diagnostic_alias(
                    "request",
                    d1.get("request_ref"),
                ),
                turn_alias=_privacy_diagnostic_alias(
                    "turn",
                    d1.get("source_turn_ref"),
                ),
                stage_reached="privacy_idempotence_checked",
                d1_generated=True,
                d2_generated=isinstance(d2, dict),
                d1_ordered_sha256=_ordered_json_sha256(d1),
                d1_canonical_sha256=_canonical_json_sha256(d1),
                d2_ordered_sha256=_ordered_json_sha256(d2),
                d2_canonical_sha256=_canonical_json_sha256(d2),
                privacy_projection_equal=(d1 == d2),
                diff_total_count=total,
                diff_retained_count=len(retained),
                diff_truncated_count=max(total - len(retained), 0),
                diff_truncated=total > len(retained),
                diff_category_counts=category_counts,
                first_diff_path=paths[0] if paths else "",
                retained_diff_paths=paths,
                diffs=retained,
            )
        except Exception:
            _privacy_diagnostic_update(
                sink,
                diagnostic_error="privacy_diff_generation_failed",
            )

    @classmethod
    def _decision_evidence_rows(
        cls,
        value: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            scopes = (
                item.get("product_identity_scope")
                or item.get("identity_scopes")
                or []
            )
            identity_scope_refs = []
            for scope in scopes if isinstance(scopes, list) else []:
                if not isinstance(scope, dict):
                    continue
                namespace = str(
                    scope.get("namespace") or ""
                ).strip()
                scope_value = scope.get("value")
                if not namespace or scope_value in {None, ""}:
                    continue
                identity_scope_refs.append({
                    "namespace": namespace,
                    "scope_ref": cls._anonymous_reference(
                        "scope",
                        {
                            "namespace": namespace,
                            "value": scope_value,
                        },
                    ),
                })
            provenance = item.get("provenance")
            provenance = (
                provenance
                if isinstance(provenance, dict)
                else {}
            )
            origin = (
                provenance.get("origin_evidence_key")
                or item.get("origin_evidence_key")
                or ""
            )
            source_container = (
                provenance.get("source_container")
                or item.get("source_container")
                or ""
            )
            rows.append({
                "evidence_uid": deepcopy(
                    item.get("evidence_uid")
                ),
                "admission_owner": "admitted_answer_context",
                "source": deepcopy(item.get("source")),
                "source_type": deepcopy(item.get("source_type")),
                "evidence_role": deepcopy(
                    item.get("evidence_role")
                ),
                "review_status": deepcopy(
                    item.get("review_status")
                ),
                "fact_review_status": deepcopy(
                    item.get("fact_review_status")
                ),
                "gate_status": deepcopy(item.get("gate_status")),
                "direct_answer_allowed": deepcopy(
                    item.get("direct_answer_allowed")
                ),
                "identity_scope_refs": identity_scope_refs,
                "fact_type": deepcopy(item.get("fact_type")),
                "attribute_key": deepcopy(
                    item.get("attribute_key")
                ),
                "content": deepcopy(item.get("content")),
                "value": deepcopy(item.get("value")),
                "original_value": deepcopy(
                    item.get("original_value")
                ),
                "provenance": {
                    "origin_ref": (
                        cls._anonymous_reference(
                            "origin",
                            origin,
                        )
                        if origin
                        else ""
                    ),
                    "source_container": source_container,
                },
            })
        return rows

    @classmethod
    def build_composer_decision_input(
        cls,
        response: dict[str, Any],
        *,
        customer_message: str,
        privacy_diagnostics_sink: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Build the privacy-safe, lossless pre-presentation contract."""
        diagnostics_enabled = isinstance(privacy_diagnostics_sink, dict)
        if (
            diagnostics_enabled
            and privacy_diagnostics_sink.get("schema_version")
            != COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA
        ):
            _privacy_diagnostic_initialize(privacy_diagnostics_sink)
        if diagnostics_enabled:
            _privacy_diagnostic_update(
                privacy_diagnostics_sink,
                decision_input_build_attempted=True,
                stage_reached="decision_input_build",
            )
        minimal_context = cls._minimal_context(response)
        if not minimal_context:
            if diagnostics_enabled:
                _privacy_diagnostic_update(
                    privacy_diagnostics_sink,
                    stage_reached="minimal_context_missing",
                    early_return_reason="minimal_decision_context_missing",
                )
            return {}, "minimal_decision_context_missing"

        requested_claims = cls._allowlisted_rows(
            minimal_context.get("requested_claims"),
            _DECISION_GOAL_FIELDS,
        )
        source_turn_refs: list[str] = []
        for claim in requested_claims:
            source_turn_uid = str(
                claim.get("source_turn_uid") or ""
            ).strip()
            if not source_turn_uid:
                continue
            anonymous = cls._anonymous_reference(
                "turn",
                source_turn_uid,
            )
            claim["source_turn_uid"] = anonymous
            source_turn_refs.append(anonymous)
        source_turn_ref = (
            source_turn_refs[0]
            if len(set(source_turn_refs)) == 1
            else cls._anonymous_reference(
                "turn-set",
                sorted(set(source_turn_refs)),
            )
        )
        current_question = str(
            minimal_context.get("customer_goal")
            or customer_message
            or ""
        )
        product_identity = minimal_context.get("product_identity")
        product_identity = (
            product_identity
            if isinstance(product_identity, dict)
            else {}
        )
        decision_input = {
            "schema_version": COMPOSER_DECISION_INPUT_SCHEMA,
            "owner": COMPOSER_DECISION_INPUT_OWNER,
            "request_ref": cls._anonymous_reference(
                "request",
                {
                    "source_turn_ref": source_turn_ref,
                    "customer_goal": current_question,
                },
            ),
            "source_turn_ref": source_turn_ref,
            "customer_goal": current_question,
            "recent_conversation_turns": cls._allowlisted_rows(
                minimal_context.get("recent_conversation_turns"),
                _DECISION_RECENT_TURN_FIELDS,
            ),
            "product_scope": {
                "resolved": bool(product_identity),
                "variant_context_present": bool(
                    product_identity.get("variant_reference")
                ),
            },
            "requested_claims": requested_claims,
            "admitted_evidence": cls._decision_evidence_rows(
                minimal_context.get("admitted_evidence"),
            ),
            "claim_resolutions": cls._allowlisted_rows(
                minimal_context.get("claim_resolutions"),
                _DECISION_RESOLUTION_FIELDS,
            ),
            "bounded_inference_policies": cls._allowlisted_rows(
                minimal_context.get("bounded_inference_policies"),
                _DECISION_POLICY_FIELDS,
            ),
            "trusted_domain_policy_context": {
                key: deepcopy(item)
                for key, item in (
                    minimal_context.get(
                        "trusted_domain_policy_context"
                    )
                    or {}
                ).items()
                if key in _DECISION_TRUSTED_PACK_FIELDS
            },
            "service_actions": cls._allowlisted_rows(
                minimal_context.get("service_actions"),
                _DECISION_SERVICE_ACTION_FIELDS,
            ),
            "media_candidates": cls._allowlisted_rows(
                minimal_context.get("media_candidates"),
                _DECISION_MEDIA_FIELDS,
            ),
            "conflicting_claim_count": len(
                minimal_context.get("conflicting_claims") or []
            ),
            "safety_constraints": {
                key: deepcopy(item)
                for key, item in (
                    minimal_context.get("safety_constraints")
                    or {}
                ).items()
                if key in _DECISION_SAFETY_FIELDS
            },
            "context_stats": {
                key: deepcopy(item)
                for key, item in (
                    minimal_context.get("context_stats") or {}
                ).items()
                if key in _DECISION_CONTEXT_STATS_FIELDS
            },
            "actual_attached_media_types": cls._actual_media_types(
                response
            ),
            "used_for_final_reply": True,
            "used_as_evidence": False,
            "can_change_can_send": False,
        }
        projected = cls._privacy_project_decision_value(
            decision_input
        )
        if not isinstance(projected, dict):
            if diagnostics_enabled:
                _privacy_diagnostic_update(
                    privacy_diagnostics_sink,
                    stage_reached="d1_generation_failed",
                    early_return_reason=(
                        "composer_decision_input_privacy_invalid"
                    ),
                )
            return {}, "composer_decision_input_privacy_invalid"
        if diagnostics_enabled:
            try:
                request_alias = _privacy_diagnostic_alias(
                    "request",
                    projected.get("request_ref"),
                )
                turn_alias = _privacy_diagnostic_alias(
                    "turn",
                    projected.get("source_turn_ref"),
                )
            except Exception:
                request_alias = ""
                turn_alias = ""
                _privacy_diagnostic_update(
                    privacy_diagnostics_sink,
                    diagnostic_error="diagnostic_alias_unavailable",
                )
            _privacy_diagnostic_update(
                privacy_diagnostics_sink,
                request_alias=request_alias,
                turn_alias=turn_alias,
                stage_reached="d1_generated",
                d1_generated=True,
                d1_ordered_sha256=_ordered_json_sha256(projected),
                d1_canonical_sha256=_canonical_json_sha256(projected),
            )
        validation_error = cls.validate_composer_decision_input(
            projected,
            privacy_diagnostics_sink=privacy_diagnostics_sink,
        )
        if validation_error:
            if diagnostics_enabled:
                _privacy_diagnostic_update(
                    privacy_diagnostics_sink,
                    early_return_reason=validation_error,
                )
            return {}, validation_error
        if diagnostics_enabled:
            _privacy_diagnostic_update(
                privacy_diagnostics_sink,
                decision_input_build_completed=True,
                stage_reached="decision_input_build_completed",
            )
        return projected, ""

    @staticmethod
    def _has_only_fields(
        value: Any,
        allowed_fields: set[str],
    ) -> bool:
        return (
            isinstance(value, dict)
            and set(value) <= allowed_fields
        )

    @classmethod
    def validate_composer_decision_input(
        cls,
        decision_input: Any,
        *,
        privacy_diagnostics_sink: dict[str, Any] | None = None,
    ) -> str:
        """Validate the replay boundary without inferring missing fields."""
        diagnostics_enabled = isinstance(privacy_diagnostics_sink, dict)
        if (
            diagnostics_enabled
            and privacy_diagnostics_sink.get("schema_version")
            != COMPOSER_PRIVACY_DIAGNOSTICS_SCHEMA
        ):
            _privacy_diagnostic_initialize(privacy_diagnostics_sink)
        if (
            not isinstance(decision_input, dict)
            or set(decision_input) != _DECISION_INPUT_FIELDS
        ):
            return "composer_decision_input_schema_invalid"
        if (
            decision_input.get("schema_version")
            != COMPOSER_DECISION_INPUT_SCHEMA
            or decision_input.get("owner")
            != COMPOSER_DECISION_INPUT_OWNER
            or decision_input.get("used_for_final_reply") is not True
            or decision_input.get("used_as_evidence") is not False
            or decision_input.get("can_change_can_send") is not False
        ):
            return "composer_decision_input_authority_invalid"
        for key in ("request_ref", "source_turn_ref"):
            value = str(decision_input.get(key) or "")
            if not value or "[" in value or "]" in value:
                return "composer_decision_input_reference_invalid"
        if not isinstance(
            decision_input.get("customer_goal"),
            str,
        ):
            return "composer_decision_input_schema_invalid"
        if not cls._has_only_fields(
            decision_input.get("product_scope"),
            _DECISION_PRODUCT_SCOPE_FIELDS,
        ):
            return "composer_decision_input_schema_invalid"
        if set(decision_input["product_scope"]) != (
            _DECISION_PRODUCT_SCOPE_FIELDS
        ):
            return "composer_decision_input_schema_invalid"

        row_contracts = (
            ("recent_conversation_turns", _DECISION_RECENT_TURN_FIELDS),
            ("requested_claims", _DECISION_GOAL_FIELDS),
            ("admitted_evidence", _DECISION_EVIDENCE_FIELDS),
            ("claim_resolutions", _DECISION_RESOLUTION_FIELDS),
            (
                "bounded_inference_policies",
                _DECISION_POLICY_FIELDS,
            ),
            ("service_actions", _DECISION_SERVICE_ACTION_FIELDS),
            ("media_candidates", _DECISION_MEDIA_FIELDS),
        )
        for key, allowed_fields in row_contracts:
            rows = decision_input.get(key)
            if (
                not isinstance(rows, list)
                or any(
                    not cls._has_only_fields(row, allowed_fields)
                    for row in rows
                )
            ):
                return "composer_decision_input_schema_invalid"
        if not cls._has_only_fields(
            decision_input.get("trusted_domain_policy_context"),
            _DECISION_TRUSTED_PACK_FIELDS,
        ):
            return "composer_decision_input_schema_invalid"
        if not cls._has_only_fields(
            decision_input.get("safety_constraints"),
            _DECISION_SAFETY_FIELDS,
        ):
            return "composer_decision_input_schema_invalid"
        if not cls._has_only_fields(
            decision_input.get("context_stats"),
            _DECISION_CONTEXT_STATS_FIELDS,
        ):
            return "composer_decision_input_schema_invalid"
        if (
            not isinstance(
                decision_input.get("conflicting_claim_count"),
                int,
            )
            or isinstance(
                decision_input.get("conflicting_claim_count"),
                bool,
            )
            or decision_input["conflicting_claim_count"] < 0
            or not isinstance(
                decision_input.get("actual_attached_media_types"),
                list,
            )
            or any(
                item not in {"image", "video"}
                for item in decision_input[
                    "actual_attached_media_types"
                ]
            )
        ):
            return "composer_decision_input_schema_invalid"

        for claim in decision_input["requested_claims"]:
            goal_kind = str(claim.get("goal_kind") or "").strip()
            if (
                goal_kind == "compatibility_claim"
                or (
                    not goal_kind
                    and claim.get("supporting_only") is True
                )
            ):
                continue
            if (
                not cls._has_authoritative_provenance(claim)
                or not _structured_sha256(
                    claim.get("source_span_sha256")
                )
                or not _structured_sha256(
                    claim.get("source_text_sha256")
                )
            ):
                return "composer_goal_provenance_invalid"
        seen_evidence_refs: set[str] = set()
        for evidence in decision_input["admitted_evidence"]:
            evidence_uid = str(
                evidence.get("evidence_uid") or ""
            ).strip()
            if (
                not evidence_uid
                or evidence_uid in seen_evidence_refs
                or evidence.get("admission_owner")
                != "admitted_answer_context"
                or not cls._has_only_fields(
                    evidence.get("provenance"),
                    _DECISION_EVIDENCE_PROVENANCE_FIELDS,
                )
                or set(evidence.get("provenance") or {})
                != _DECISION_EVIDENCE_PROVENANCE_FIELDS
                or not isinstance(
                    evidence.get("identity_scope_refs"),
                    list,
                )
                or any(
                    not cls._has_only_fields(
                        scope,
                        _DECISION_IDENTITY_SCOPE_FIELDS,
                    )
                    or set(scope)
                    != _DECISION_IDENTITY_SCOPE_FIELDS
                    or str(
                        scope.get("namespace") or ""
                    ).strip() not in (
                        _DECISION_IDENTITY_SCOPE_NAMESPACES
                    )
                    or not str(
                        scope.get("scope_ref") or ""
                    ).startswith("scope-")
                    for scope in (
                        evidence.get("identity_scope_refs")
                        or []
                    )
                )
            ):
                return "composer_evidence_provenance_invalid"
            seen_evidence_refs.add(evidence_uid)
        for resolution in decision_input["claim_resolutions"]:
            boundary = resolution.get(
                "restricted_request_boundary"
            )
            if boundary and not cls._has_only_fields(
                boundary,
                _DECISION_RESTRICTED_BOUNDARY_FIELDS,
            ):
                return "composer_decision_input_schema_invalid"
            options = resolution.get("eligible_policy_options") or []
            if not isinstance(options, list):
                return "composer_decision_input_schema_invalid"
            for option in options:
                if not cls._has_only_fields(
                    option,
                    _DECISION_OPTION_FIELDS,
                ):
                    return "composer_decision_input_schema_invalid"
                option_boundary = option.get(
                    "restricted_request_boundary"
                )
                if option_boundary and not cls._has_only_fields(
                    option_boundary,
                    _DECISION_RESTRICTED_BOUNDARY_FIELDS,
                ):
                    return "composer_decision_input_schema_invalid"
                provenance = option.get("option_provenance")
                if not cls._has_only_fields(
                    provenance,
                    _DECISION_OPTION_PROVENANCE_FIELDS,
                ):
                    return "composer_decision_input_schema_invalid"

        second_projection = cls._privacy_project_decision_value(
            decision_input
        )
        if diagnostics_enabled:
            cls._record_decision_input_privacy_diagnostics(
                privacy_diagnostics_sink,
                d1=decision_input,
                d2=second_projection,
                provenance_validated=True,
            )
        if (
            _canonical_json_sha256(second_projection)
            != _canonical_json_sha256(decision_input)
        ):
            return "composer_decision_input_privacy_invalid"
        try:
            json.dumps(
                decision_input,
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return "composer_decision_input_schema_invalid"
        return ""

    @classmethod
    def build_provider_material_from_decision_input(
        cls,
        decision_input: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Build the existing prompt solely from the replayable input."""
        validation_error = cls.validate_composer_decision_input(
            decision_input
        )
        if validation_error:
            return {}, validation_error
        evidence, uid_by_ref = cls._project_evidence(decision_input)
        _, policy_by_ref, policy_error = (
            cls._project_bounded_inference_policies(
                decision_input
            )
        )
        if policy_error:
            return {}, policy_error
        partitions, goal_uid_by_ref, goal_error = (
            cls._partition_composer_inputs(
                decision_input,
                uid_by_ref,
                policy_by_ref,
                actual_media_types=list(
                    decision_input[
                        "actual_attached_media_types"
                    ]
                ),
            )
        )
        if goal_error:
            return {}, goal_error
        (
            customer_goals,
            offered_option_bindings,
            offered_error,
        ) = cls._build_goal_scoped_offered_projection(
            partitions["renderable_customer_goals"]
        )
        if offered_error:
            return {}, offered_error
        partitions["renderable_customer_goals"] = customer_goals
        prompt_payload = cls._prompt_payload(
            decision_input,
            customer_message="",
            evidence=evidence,
            partitions=partitions,
        )
        system_prompt = cls._system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    prompt_payload,
                    ensure_ascii=False,
                ),
            },
        ]
        return {
            "evidence": evidence,
            "uid_by_ref": uid_by_ref,
            "partitions": partitions,
            "goal_uid_by_ref": goal_uid_by_ref,
            "customer_goals": customer_goals,
            "offered_option_bindings": offered_option_bindings,
            "prompt_payload": prompt_payload,
            "system_prompt": system_prompt,
            "messages": messages,
        }, ""

    @staticmethod
    def _base_result(minimal_context: dict[str, Any]) -> dict[str, Any]:
        stats = minimal_context.get("context_stats") if isinstance(minimal_context, dict) else {}
        return {
            "version": COMPOSER_VERSION,
            "status": "provider_blocked",
            "rejection_reason": "",
            "candidate_reply": "",
            "used_evidence_uids": [],
            "unresolved_claim_types": [],
            "covered_goal_refs": [],
            "clauses": [],
            "context_metrics": dict(stats or {}),
            "used_for_final_reply": False,
            "can_change_can_send": False,
            "requires_human_review": True,
            "can_send": False,
            "provider_diagnostics": {
                "response_envelope": "not_called",
                "response_length": 0,
                "response_sha256": "",
                "finish_reason": "",
                "provider_latency_ms": None,
                "provider_error_type": "",
                "model_call_count": 0,
                "retry_count": 0,
                "repair_count": 0,
                "json_repair_count": 0,
                "envelope_contract_version": COMPOSER_ENVELOPE_CONTRACT_VERSION,
                "envelope_unwrap_count": 0,
                "system_prompt_sha256": "",
                "prompt_payload_sha256": "",
                "provider_input_sha256": "",
                "offered_projection_sha256": "",
                "output_contract_sha256": "",
                "response_schema_sha256": "",
                "prompt_schema_summary_sha256": "",
                "offered_goal_refs": [],
                "presentation_order": [],
                "presentation_order_sha256": "",
                "offered_option_refs": [],
                "model_name": "",
                "decision_input_schema": "",
                "decision_input_sha256": "",
                "decision_input_privacy_projected": False,
                "decision_input_used_for_final_reply": False,
                "decision_input_used_as_evidence": False,
                "decision_input_can_change_can_send": False,
            },
            "validation_diagnostics": ModelFirstAnswerComposerService._diagnostics(
                "not_started",
            ),
            "media_claim_diagnostics": {},
            "input_eligibility": {
                "renderable_customer_goal_count": 0,
                "supporting_dependency_count": 0,
                "excluded_compatibility_dependency_count": 0,
                "non_customer_goal_clause_count": 0,
                "customer_goal_clause_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "dependency_evidence_link_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "unknown_goal_kind_count": 0,
            },
        }

    @staticmethod
    def _project_evidence(
        minimal_context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        rows = [
            item
            for item in minimal_context.get("admitted_evidence") or []
            if isinstance(item, dict) and str(item.get("evidence_uid") or "").strip()
        ]
        rows.sort(key=lambda item: str(item.get("evidence_uid") or ""))
        projected: list[dict[str, Any]] = []
        uid_by_ref: dict[str, str] = {}
        for index, item in enumerate(rows, start=1):
            ref = f"E{index}"
            uid_by_ref[ref] = str(item["evidence_uid"]).strip()
            projected.append({
                "evidence_ref": ref,
                "fact_type": str(item.get("fact_type") or ""),
                "attribute_key": str(item.get("attribute_key") or ""),
                "content": str(item.get("content") or item.get("value") or ""),
            })
        return projected, uid_by_ref

    @staticmethod
    def _partition_composer_inputs(
        minimal_context: dict[str, Any],
        uid_by_ref: dict[str, str],
        policy_by_ref: dict[str, dict[str, Any]],
        *,
        actual_media_types: list[str],
    ) -> tuple[dict[str, Any], dict[str, str], str]:
        partitions = {
            "renderable_customer_goals": [],
            "presentation_order": [],
            "supporting_dependencies": [],
            "service_actions": list(
                minimal_context.get("service_actions") or []
            ),
            "media_context": {
                "candidate_count": len(
                    minimal_context.get("media_candidates") or []
                ),
                "request_refs": [],
                "actual_attached_media_types": list(actual_media_types),
            },
            "contextual_constraints": {
                "conflicting_claim_count": int(
                    minimal_context.get(
                        "conflicting_claim_count"
                    )
                    or len(
                        minimal_context.get(
                            "conflicting_claims"
                        )
                        or []
                    )
                ),
                "constraint_refs": [],
                "safety_constraints": dict(
                    minimal_context.get("safety_constraints") or {}
                ),
            },
            "non_renderable_goal_refs": set(),
            "eligibility_metrics": {
                "renderable_customer_goal_count": 0,
                "supporting_dependency_count": 0,
                "excluded_compatibility_dependency_count": 0,
                "non_customer_goal_clause_count": 0,
                "customer_goal_clause_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "dependency_evidence_link_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "unknown_goal_kind_count": 0,
            },
        }
        ref_by_uid = {uid: ref for ref, uid in uid_by_ref.items()}
        requested_claims = [
            item
            for item in minimal_context.get("requested_claims") or []
            if isinstance(item, dict)
        ]
        resolutions = [
            item
            for item in minimal_context.get("claim_resolutions") or []
            if isinstance(item, dict)
        ]
        resolutions_by_goal_ref: dict[str, list[dict[str, Any]]] = {}
        for resolution in resolutions:
            goal_ref = str(resolution.get("goal_ref") or "").strip()
            if goal_ref:
                resolutions_by_goal_ref.setdefault(goal_ref, []).append(
                    resolution
                )

        authoritative_goals: list[dict[str, Any]] = []
        dependencies: list[dict[str, Any]] = []
        non_renderable_claims: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for claim in requested_claims:
            goal_kind = str(claim.get("goal_kind") or "").strip()
            goal_ref = str(claim.get("goal_ref") or "").strip()
            if not goal_kind:
                if claim.get("supporting_only") is True:
                    partitions["eligibility_metrics"][
                        "excluded_compatibility_dependency_count"
                    ] += 1
                    continue
                partitions["eligibility_metrics"][
                    "unknown_goal_kind_count"
                ] += 1
                return (
                    partitions,
                    {},
                    "composer_goal_kind_missing",
                )
            if goal_kind == "compatibility_claim":
                if claim.get("customer_goal_eligible") is False:
                    non_renderable_claims.append(claim)
                    continue
                partitions["eligibility_metrics"][
                    "unknown_goal_kind_count"
                ] += 1
                return (
                    partitions,
                    {},
                    "composer_unknown_goal_kind",
                )
            if goal_kind not in {
                "customer_goal",
                *_NON_RENDERABLE_GOAL_KINDS,
            }:
                partitions["eligibility_metrics"][
                    "unknown_goal_kind_count"
                ] += 1
                return (
                    partitions,
                    {},
                    "composer_unknown_goal_kind",
                )
            if not goal_ref or goal_ref in seen_refs:
                return (
                    partitions,
                    {},
                    "composer_goal_ref_invalid",
                )
            seen_refs.add(goal_ref)
            if not ModelFirstAnswerComposerService._has_authoritative_provenance(
                claim
            ):
                return (
                    partitions,
                    {},
                    "composer_goal_provenance_invalid",
                )
            if goal_kind == "customer_goal":
                if (
                    claim.get("supporting_only") is True
                    or claim.get("customer_goal_eligible") is False
                ):
                    non_renderable_claims.append(claim)
                    continue
                authoritative_goals.append(claim)
            elif goal_kind == "evidence_dependency":
                dependencies.append(claim)
            else:
                non_renderable_claims.append(claim)

        authoritative_ref_set = {
            str(item["goal_ref"]).strip() for item in authoritative_goals
        }
        source_turn_uids = {
            str(item.get("source_turn_uid") or "").strip()
            for item in authoritative_goals
        }
        if len(source_turn_uids) > 1:
            return (
                partitions,
                {},
                "composer_customer_goal_source_turn_mismatch",
            )
        resolution_goal_refs = {
            str(item.get("goal_ref") or "").strip()
            for item in resolutions
            if str(item.get("goal_kind") or "").strip() == "customer_goal"
        }
        if resolution_goal_refs - authoritative_ref_set:
            return (
                partitions,
                {},
                "composer_non_authoritative_customer_resolution",
            )

        goals: list[dict[str, Any]] = []
        goal_uid_by_ref: dict[str, str] = {}
        seen_uids: set[str] = set()
        prompt_ref_by_goal_ref: dict[str, str] = {}
        for index, claim in enumerate(
            sorted(
                authoritative_goals,
                key=lambda item: str(item.get("goal_ref") or ""),
            ),
            start=1,
        ):
            authoritative_goal_ref = str(claim["goal_ref"]).strip()
            matching = resolutions_by_goal_ref.get(
                authoritative_goal_ref,
                [],
            )
            if len(matching) != 1:
                return (
                    partitions,
                    {},
                    "composer_customer_goal_resolution_invalid",
                )
            resolution = matching[0]
            if (
                str(resolution.get("goal_kind") or "").strip()
                != "customer_goal"
                or resolution.get("supporting_only") is True
            ):
                return (
                    partitions,
                    {},
                    "composer_customer_goal_resolution_invalid",
                )
            claim_uid = str(resolution.get("claim_uid") or "").strip()
            claim_type = str(resolution.get("claim_type") or "").strip()
            claim_type_status = str(
                resolution.get("claim_type_status") or ""
            ).strip()
            status = str(resolution.get("status") or "").strip()
            support_basis = str(
                resolution.get("support_basis") or ""
            ).strip()
            unmapped_customer_goal = (
                not claim_type
                and claim_type_status == "unmapped"
                and str(resolution.get("goal_kind") or "").strip()
                == "customer_goal"
                and (
                    (
                        status in _UNRESOLVED_STATUSES
                        and not resolution.get("evidence_uids")
                        and not resolution.get("inference_policy_refs")
                    )
                    or (
                        status == "supported"
                        and support_basis == "bounded_inference"
                    )
                )
            )
            if (
                not claim_uid
                or claim_uid in seen_uids
                or (not claim_type and not unmapped_customer_goal)
                or status not in {"supported", *_UNRESOLVED_STATUSES}
            ):
                return (
                    partitions,
                    {},
                    "composer_customer_goal_contract_invalid",
                )
            seen_uids.add(claim_uid)
            goal_ref = f"goal_{index:02d}"
            prompt_ref_by_goal_ref[authoritative_goal_ref] = goal_ref
            goal_uid_by_ref[goal_ref] = claim_uid
            evidence_refs = sorted({
                ref_by_uid[str(uid)]
                for uid in resolution.get("evidence_uids") or []
                if str(uid) in ref_by_uid
            })
            if status == "supported" and not evidence_refs:
                return (
                    partitions,
                    {},
                    "composer_supported_goal_evidence_missing",
                )
            required_clause_kind = (
                "supported_fact"
                if status == "supported"
                else "unresolved"
            )
            eligible_options, option_error = (
                ModelFirstAnswerComposerService._project_goal_policy_options(
                    resolution,
                    authoritative_goal_ref=authoritative_goal_ref,
                    ref_by_uid=ref_by_uid,
                    policy_by_ref=policy_by_ref,
                )
            )
            if option_error:
                return partitions, {}, option_error
            restricted_boundary = resolution.get(
                "restricted_request_boundary"
            )
            if restricted_boundary:
                if (
                    status not in _UNRESOLVED_STATUSES
                    or not valid_restricted_request_boundary(
                        restricted_boundary
                    )
                    or str(
                        resolution.get("requested_claim_risk") or ""
                    ).strip()
                    != str(
                        restricted_boundary.get(
                            "requested_claim_risk"
                        )
                        or ""
                    ).strip()
                ):
                    return (
                        partitions,
                        {},
                        "composer_restricted_request_boundary_invalid",
                    )
            goals.append({
                "goal_ref": goal_ref,
                "authoritative_goal_ref": authoritative_goal_ref,
                "claim_type": claim_type,
                "claim_type_status": claim_type_status,
                "attribute_key": str(
                    resolution.get("attribute_key") or ""
                ).strip(),
                "semantic_key": str(
                    resolution.get("semantic_key") or ""
                ).strip(),
                "goal_summary": str(
                    resolution.get("goal_summary") or ""
                ).strip(),
                "resolution_status": status,
                "support_basis": support_basis,
                "required_clause_kind": required_clause_kind,
                "required_evidence_refs": evidence_refs,
                "eligible_policy_options": eligible_options,
                "requested_claim_risk": str(
                    resolution.get("requested_claim_risk") or ""
                ).strip(),
                "restricted_request_boundary": (
                    dict(restricted_boundary)
                    if isinstance(restricted_boundary, dict)
                    else {}
                ),
            })

        partitions["presentation_order"] = [
            prompt_ref_by_goal_ref[str(claim["goal_ref"]).strip()]
            for claim in sorted(
                authoritative_goals,
                key=lambda item: (
                    int(item["source_span_start"]),
                    int(item["source_span_end"]),
                    str(item["goal_ref"]).strip(),
                ),
            )
        ]

        dependency_rows: list[dict[str, Any]] = []
        dependency_link_denominator = len(dependencies)
        dependency_link_numerator = 0
        for index, dependency in enumerate(
            sorted(
                dependencies,
                key=lambda item: str(item.get("goal_ref") or ""),
            ),
            start=1,
        ):
            dependency_goal_ref = str(dependency["goal_ref"]).strip()
            supporting_for_goal_ref = str(
                dependency.get("supporting_for_goal_ref") or ""
            ).strip()
            if (
                dependency.get("supporting_only") is not True
                or not supporting_for_goal_ref
            ):
                return (
                    partitions,
                    {},
                    "composer_dependency_binding_missing",
                )
            if supporting_for_goal_ref not in prompt_ref_by_goal_ref:
                return (
                    partitions,
                    {},
                    "composer_dependency_target_unknown",
                )
            matching = resolutions_by_goal_ref.get(dependency_goal_ref, [])
            if (
                len(matching) != 1
                or str(matching[0].get("goal_kind") or "").strip()
                != "evidence_dependency"
            ):
                return (
                    partitions,
                    {},
                    "composer_dependency_resolution_invalid",
                )
            resolution = matching[0]
            status = str(resolution.get("status") or "").strip()
            if status not in {"supported", *_UNRESOLVED_STATUSES}:
                return (
                    partitions,
                    {},
                    "composer_dependency_resolution_invalid",
                )
            evidence_uids = sorted({
                str(item).strip()
                for item in resolution.get("evidence_uids") or []
                if str(item).strip()
            })
            evidence_refs = sorted({
                ref_by_uid[uid]
                for uid in evidence_uids
                if uid in ref_by_uid
            })
            if len(evidence_refs) != len(evidence_uids):
                return (
                    partitions,
                    {},
                    "composer_dependency_evidence_unknown",
                )
            dependency_ref = f"dependency_{index:02d}"
            partitions["non_renderable_goal_refs"].add(dependency_ref)
            dependency_rows.append({
                "dependency_ref": dependency_ref,
                "supporting_for_goal_ref": prompt_ref_by_goal_ref[
                    supporting_for_goal_ref
                ],
                "admitted_evidence_refs": evidence_refs,
                "resolution_status": status,
                "provenance_status": "valid",
            })
            dependency_link_numerator += 1

        for index, claim in enumerate(
            sorted(
                non_renderable_claims,
                key=lambda item: (
                    str(item.get("goal_kind") or ""),
                    str(item.get("goal_ref") or ""),
                ),
            ),
            start=1,
        ):
            goal_kind = str(claim.get("goal_kind") or "").strip()
            goal_ref = str(claim.get("goal_ref") or "").strip()
            if not goal_ref or goal_kind == "compatibility_claim":
                continue
            prompt_ref = f"non_renderable_{index:02d}"
            partitions["non_renderable_goal_refs"].add(prompt_ref)
            matching = resolutions_by_goal_ref.get(goal_ref, [])
            status = (
                str(matching[0].get("status") or "").strip()
                if len(matching) == 1
                else "not_resolved"
            )
            projection = {
                "goal_ref": prompt_ref,
                "goal_kind": goal_kind,
                "status": status,
                "renderable": False,
            }
            if goal_kind == "service_action":
                partitions["service_actions"].append(projection)
            elif goal_kind in {"media_request", "media_candidate"}:
                partitions["media_context"]["request_refs"].append(
                    projection
                )
            elif goal_kind == "contextual_constraint":
                partitions["contextual_constraints"][
                    "constraint_refs"
                ].append(projection)

        metrics = partitions["eligibility_metrics"]
        metrics["renderable_customer_goal_count"] = len(goals)
        metrics["supporting_dependency_count"] = len(dependency_rows)
        metrics["customer_goal_clause_coverage"]["denominator"] = len(goals)
        metrics["dependency_evidence_link_coverage"] = {
            "numerator": dependency_link_numerator,
            "denominator": dependency_link_denominator,
            "rate": (
                dependency_link_numerator / dependency_link_denominator
                if dependency_link_denominator
                else None
            ),
        }
        partitions["renderable_customer_goals"] = goals
        partitions["supporting_dependencies"] = dependency_rows
        return partitions, goal_uid_by_ref, ""

    @staticmethod
    def _has_authoritative_provenance(claim: dict[str, Any]) -> bool:
        source_span_start = claim.get("source_span_start")
        source_span_end = claim.get("source_span_end")
        return bool(
            claim.get("schema_version") == _AUTHORITATIVE_GOAL_SCHEMA
            and claim.get("owner") == _AUTHORITATIVE_GOAL_OWNER
            and claim.get("source") == _AUTHORITATIVE_GOAL_SOURCE
            and str(claim.get("source_stage") or "").strip()
            and str(claim.get("source_turn_uid") or "").strip()
            and isinstance(source_span_start, int)
            and not isinstance(source_span_start, bool)
            and isinstance(source_span_end, int)
            and not isinstance(source_span_end, bool)
            and source_span_start >= 0
            and source_span_end >= source_span_start
        )

    @staticmethod
    def _project_goal_policy_options(
        resolution: dict[str, Any],
        *,
        authoritative_goal_ref: str,
        ref_by_uid: dict[str, str],
        policy_by_ref: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str]:
        raw_options = resolution.get("eligible_policy_options") or []
        if not isinstance(raw_options, list):
            return [], "composer_inference_policy_schema_invalid"
        if (
            resolution.get("status") in {"conflicting", "prohibited"}
            and raw_options
        ):
            return [], "composer_bounded_inference_contract_invalid"

        projected: list[dict[str, Any]] = []
        seen_policy_refs: set[str] = set()
        for item in raw_options:
            if not isinstance(item, dict):
                return [], "composer_inference_policy_schema_invalid"
            policy_ref = str(item.get("policy_ref") or "").strip()
            if (
                not policy_ref
                or policy_ref not in policy_by_ref
                or str(item.get("applicable_goal_ref") or "").strip()
                != authoritative_goal_ref
            ):
                return [], "composer_unknown_inference_policy_reference"
            if policy_ref in seen_policy_refs:
                return [], "composer_duplicate_offered_option"
            seen_policy_refs.add(policy_ref)
            policy = policy_by_ref[policy_ref]
            premise_uids = sorted({
                str(value).strip()
                for value in item.get("premise_evidence_refs") or []
                if str(value).strip()
            })
            premise_refs = sorted({
                ref_by_uid[uid]
                for uid in premise_uids
                if uid in ref_by_uid
            })
            premise_families = sorted({
                str(value).strip()
                for value in item.get("premise_families") or []
                if str(value).strip()
            })
            required_qualifiers = sorted({
                str(value).strip()
                for value in item.get("required_qualifiers") or []
                if str(value).strip()
            })
            prohibited = sorted({
                str(value).strip()
                for value in item.get("forbidden_claim_families") or []
                if str(value).strip()
            })
            allowed_conclusion_family = str(
                item.get("allowed_conclusion_family") or ""
            ).strip()
            allowed_variability_factor_families = sorted({
                str(value).strip()
                for value in (
                    item.get("allowed_variability_factor_families")
                    or []
                )
                if str(value).strip()
            })
            advice_mode = str(
                item.get("advice_mode") or ""
            ).strip()
            requested_risk = str(
                item.get("requested_risk") or ""
            ).strip()
            requested_claim_risk = str(
                item.get("requested_claim_risk")
                or requested_risk
                or ""
            ).strip()
            answer_strategy_risk = str(
                item.get("answer_strategy_risk")
                or (
                    requested_risk
                    if requested_risk in _INFERENCE_RISK_RANK
                    else ""
                )
                or ""
            ).strip()
            maximum_risk = str(
                item.get("maximum_risk") or ""
            ).strip()
            restricted_boundary = item.get(
                "restricted_request_boundary"
            )
            restricted_boundary = (
                restricted_boundary
                if isinstance(restricted_boundary, dict)
                else {}
            )
            resolution_boundary = resolution.get(
                "restricted_request_boundary"
            )
            resolution_boundary = (
                resolution_boundary
                if isinstance(resolution_boundary, dict)
                else {}
            )
            trusted_domain_pack_ref = str(
                item.get("trusted_domain_pack_ref") or ""
            ).strip()
            pack_content_sha256 = _structured_sha256(
                item.get("pack_content_sha256")
            )
            provenance = item.get("option_provenance")
            if not isinstance(provenance, dict):
                provenance = {}
            if (
                not premise_uids
                or len(premise_refs) != len(premise_uids)
                or not premise_families
                or premise_families != policy["premise_fact_families"]
                or str(item.get("policy_intent_ref") or "").strip()
                != policy["policy_intent_ref"]
                or str(item.get("goal_family") or "").strip()
                != policy["goal_family"]
                or str(item.get("intent_kind") or "").strip()
                != policy["intent_kind"]
                or str(item.get("allowed_scope") or "").strip()
                != policy["allowed_scope"]
                or allowed_conclusion_family
                != policy["allowed_conclusion_family"]
                or allowed_variability_factor_families
                != policy["allowed_variability_factor_families"]
                or advice_mode != policy["advice_mode"]
                or maximum_risk != policy["maximum_risk_level"]
                or requested_claim_risk not in _REQUEST_CLAIM_RISK_LEVELS
                or requested_risk != requested_claim_risk
                or answer_strategy_risk not in _INFERENCE_RISK_RANK
                or maximum_risk not in _INFERENCE_RISK_RANK
                or _INFERENCE_RISK_RANK[answer_strategy_risk]
                > _INFERENCE_RISK_RANK[maximum_risk]
                or required_qualifiers != policy["required_qualifiers"]
                or prohibited != policy["prohibited_claim_families"]
                or item.get("review_only") is not True
                or trusted_domain_pack_ref
                != policy["trusted_domain_pack_ref"]
                or not pack_content_sha256
                or pack_content_sha256
                != policy["pack_content_sha256"]
                or item.get("used_for_evidence") is not False
                or item.get("used_for_fact_support") is not False
                or item.get("can_change_can_send") is not False
                or provenance.get("policy_owner")
                != "domain_policy_pack"
                or provenance.get("filter_owner")
                != "claim_resolution"
                or provenance.get("premise_owner")
                != "admitted_answer_context"
                or restricted_boundary != resolution_boundary
                or (
                    bool(restricted_boundary)
                    and (
                        not valid_restricted_request_boundary(
                            restricted_boundary
                        )
                        or restricted_boundary.get(
                            "allows_bounded_alternative"
                        )
                        is not True
                        or provenance.get(
                            "alternative_for_restricted_request"
                        )
                        is not True
                        or provenance.get("intent_narrowed") is not False
                    )
                )
                or (
                    not restricted_boundary
                    and provenance.get(
                        "alternative_for_restricted_request"
                    )
                    not in {None, False}
                )
            ):
                return [], "composer_bounded_inference_contract_invalid"
            projected.append({
                "policy_ref": policy_ref,
                "trusted_domain_pack_ref": trusted_domain_pack_ref,
                "pack_content_sha256": pack_content_sha256,
                "goal_family": policy["goal_family"],
                "intent_kind": policy["intent_kind"],
                "premise_evidence_refs": premise_refs,
                "premise_evidence_uids": premise_uids,
                "premise_families": premise_families,
                "allowed_scope": policy["allowed_scope"],
                "allowed_conclusion_family": (
                    allowed_conclusion_family
                ),
                "allowed_variability_factor_families": (
                    allowed_variability_factor_families
                ),
                "advice_mode": advice_mode,
                "maximum_risk_level": maximum_risk,
                "requested_risk": requested_risk,
                "requested_claim_risk": requested_claim_risk,
                "answer_strategy_risk": answer_strategy_risk,
                "restricted_request_boundary": dict(
                    restricted_boundary
                ),
                "required_qualifiers": required_qualifiers,
                "prohibited_claim_families": prohibited,
                "review_only": True,
                "used_for_evidence": False,
                "used_for_fact_support": False,
                "can_change_can_send": False,
                "option_provenance": {
                    "trusted_domain_pack": True,
                    "admitted_premises": True,
                    "intent_narrowed": (
                        provenance.get("intent_narrowed") is True
                    ),
                    "alternative_for_restricted_request": (
                        provenance.get(
                            "alternative_for_restricted_request"
                        )
                        is True
                    ),
                },
            })
        return sorted(projected, key=lambda item: item["policy_ref"]), ""

    @staticmethod
    def _derive_option_selection_mode(
        *,
        resolution_status: str,
        option_count: int,
        selection_required: bool = False,
    ) -> str:
        if option_count < 0:
            return ""
        if option_count == 0:
            return "forbidden"
        if resolution_status == "supported":
            return "optional"
        if resolution_status in _UNRESOLVED_STATUSES:
            return (
                "required"
                if selection_required
                else "optional"
            )
        return ""

    @staticmethod
    def _build_goal_scoped_offered_projection(
        goals: list[dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        str,
    ]:
        binding_rows: list[dict[str, Any]] = []
        semantic_signatures: set[str] = set()
        for goal in goals:
            goal_ref = str(goal.get("goal_ref") or "").strip()
            authoritative_goal_ref = str(
                goal.get("authoritative_goal_ref") or ""
            ).strip()
            if not goal_ref or not authoritative_goal_ref:
                return [], {}, "composer_offered_projection_invalid"
            for option in goal.get("eligible_policy_options") or []:
                if not isinstance(option, dict):
                    return [], {}, "composer_offered_projection_invalid"
                binding = {
                    "goal_ref": goal_ref,
                    "authoritative_goal_ref": authoritative_goal_ref,
                    "policy_ref": str(
                        option.get("policy_ref") or ""
                    ).strip(),
                    "premise_evidence_refs": sorted(
                        str(value).strip()
                        for value in (
                            option.get("premise_evidence_refs") or []
                        )
                        if str(value).strip()
                    ),
                    "premise_evidence_uids": sorted(
                        str(value).strip()
                        for value in (
                            option.get("premise_evidence_uids") or []
                        )
                        if str(value).strip()
                    ),
                    "allowed_scope": str(
                        option.get("allowed_scope") or ""
                    ).strip(),
                    "allowed_conclusion_family": str(
                        option.get("allowed_conclusion_family") or ""
                    ).strip(),
                    "allowed_variability_factor_families": sorted(
                        str(value).strip()
                        for value in (
                            option.get(
                                "allowed_variability_factor_families"
                            )
                            or []
                        )
                        if str(value).strip()
                    ),
                    "advice_mode": str(
                        option.get("advice_mode") or ""
                    ).strip(),
                    "requested_claim_risk": str(
                        option.get("requested_claim_risk") or ""
                    ).strip(),
                    "answer_strategy_risk": str(
                        option.get("answer_strategy_risk") or ""
                    ).strip(),
                    "maximum_risk_level": str(
                        option.get("maximum_risk_level") or ""
                    ).strip(),
                    "trusted_domain_pack_ref": str(
                        option.get("trusted_domain_pack_ref") or ""
                    ).strip(),
                    "pack_content_sha256": _structured_sha256(
                        option.get("pack_content_sha256")
                    ),
                    "required_qualifiers": sorted(
                        str(value).strip()
                        for value in (
                            option.get("required_qualifiers") or []
                        )
                        if str(value).strip()
                    ),
                    "prohibited_claim_families": sorted(
                        str(value).strip()
                        for value in (
                            option.get(
                                "prohibited_claim_families"
                            )
                            or []
                        )
                        if str(value).strip()
                    ),
                    "restricted_request_boundary": dict(
                        option.get("restricted_request_boundary")
                        or {}
                    ),
                    "review_only": option.get("review_only") is True,
                    "used_for_evidence": (
                        option.get("used_for_evidence") is True
                    ),
                    "used_for_fact_support": (
                        option.get("used_for_fact_support") is True
                    ),
                    "can_change_can_send": (
                        option.get("can_change_can_send") is True
                    ),
                    "selection_required": any((
                        (
                            option.get("option_provenance")
                            or {}
                        ).get("intent_narrowed") is True,
                        (
                            option.get("option_provenance")
                            or {}
                        ).get(
                            "alternative_for_restricted_request"
                        ) is True,
                    )),
                }
                if (
                    not binding["policy_ref"]
                    or not binding["premise_evidence_refs"]
                    or not binding["premise_evidence_uids"]
                    or len(binding["premise_evidence_refs"])
                    != len(binding["premise_evidence_uids"])
                    or not binding["allowed_scope"]
                    or not binding["allowed_conclusion_family"]
                    or binding["advice_mode"] not in {
                        "none",
                        "concise_care_only",
                        "safety_handoff_required",
                    }
                    or not binding["trusted_domain_pack_ref"]
                    or not binding["pack_content_sha256"]
                    or binding["review_only"] is not True
                    or binding["used_for_evidence"] is not False
                    or binding["used_for_fact_support"] is not False
                    or binding["can_change_can_send"] is not False
                ):
                    return [], {}, "composer_offered_projection_invalid"
                signature = _canonical_json_sha256(binding)
                if signature in semantic_signatures:
                    return [], {}, "composer_duplicate_offered_option"
                semantic_signatures.add(signature)
                binding_rows.append({
                    **binding,
                    "option_ref": f"option_{signature[:12]}",
                })

        bindings: dict[str, dict[str, Any]] = {}
        for binding in sorted(
            binding_rows,
            key=lambda item: (
                str(item["goal_ref"]),
                str(item["option_ref"]),
            ),
        ):
            option_ref = str(binding["option_ref"])
            if option_ref in bindings:
                return [], {}, "composer_option_alias_collision"
            bindings[option_ref] = binding

        public_goals: list[dict[str, Any]] = []
        for goal in goals:
            goal_options = [
                binding
                for binding in bindings.values()
                if binding["goal_ref"] == str(goal["goal_ref"])
            ]
            option_selection_mode = (
                ModelFirstAnswerComposerService._derive_option_selection_mode(
                    resolution_status=str(
                        goal.get("resolution_status") or ""
                    ).strip(),
                    option_count=len(goal_options),
                    selection_required=any(
                        option.get("selection_required") is True
                        for option in goal_options
                    ),
                )
            )
            if not option_selection_mode:
                return [], {}, "composer_offered_projection_invalid"
            public_goal = {
                key: deepcopy(value)
                for key, value in goal.items()
                if key not in {
                    "authoritative_goal_ref",
                    "eligible_policy_options",
                }
            }
            goal_ref = str(goal["goal_ref"])
            public_goal["option_selection_mode"] = option_selection_mode
            public_goal["eligible_policy_options"] = [
                {
                    "option_ref": binding["option_ref"],
                    "premise_evidence_refs": list(
                        binding["premise_evidence_refs"]
                    ),
                    "allowed_scope": binding["allowed_scope"],
                    "allowed_conclusion_family": binding[
                        "allowed_conclusion_family"
                    ],
                    "allowed_variability_factor_families": list(
                        binding[
                            "allowed_variability_factor_families"
                        ]
                    ),
                    "advice_mode": binding["advice_mode"],
                    "requested_claim_risk": binding[
                        "requested_claim_risk"
                    ],
                    "answer_strategy_risk": binding[
                        "answer_strategy_risk"
                    ],
                    "maximum_risk_level": binding[
                        "maximum_risk_level"
                    ],
                    "required_qualifiers": list(
                        binding["required_qualifiers"]
                    ),
                    "prohibited_claim_families": list(
                        binding["prohibited_claim_families"]
                    ),
                    "restricted_request_boundary": dict(
                        binding["restricted_request_boundary"]
                    ),
                    "review_only": True,
                }
                for binding in goal_options
            ]
            public_goals.append(public_goal)
        return public_goals, bindings, ""

    @staticmethod
    def _selected_policy_clause_metadata(
        clause: dict[str, Any],
        goal: dict[str, Any],
        *,
        offered_option_bindings: dict[str, dict[str, Any]],
        uid_by_ref: dict[str, str],
    ) -> dict[str, Any]:
        if clause.get("clause_kind") != "allowed_inference":
            return {
                "inference_policy_refs": [],
                "premise_evidence_uids": [],
                "scope_qualifier": "",
                "inference_risk_level": "",
                "maximum_risk_level": "",
                "allowed_conclusion_family": "",
                "allowed_variability_factor_families": [],
                "advice_mode": "",
                "requested_claim_risk_level": "",
                "restricted_request_boundary": {},
                "inference_review_only": False,
                "required_qualifiers": [],
                "prohibited_extensions": [],
            }
        selected_ref = str(
            clause.get("selected_policy_ref") or ""
        ).strip()
        option = offered_option_bindings.get(selected_ref, {})
        premise_refs = list(clause.get("premise_evidence_refs") or [])
        return {
            "inference_policy_refs": [
                str(option.get("policy_ref") or "")
            ],
            "premise_evidence_uids": [
                uid_by_ref[str(ref)]
                for ref in premise_refs
            ],
            "scope_qualifier": str(
                clause.get("inference_scope") or ""
            ).strip(),
            "inference_risk_level": str(
                option.get("answer_strategy_risk") or ""
            ).strip(),
            "maximum_risk_level": str(
                option.get("maximum_risk_level") or ""
            ).strip(),
            "allowed_conclusion_family": str(
                option.get("allowed_conclusion_family") or ""
            ).strip(),
            "allowed_variability_factor_families": list(
                option.get("allowed_variability_factor_families") or []
            ),
            "advice_mode": str(
                option.get("advice_mode") or ""
            ).strip(),
            "requested_claim_risk_level": str(
                option.get("requested_claim_risk") or ""
            ).strip(),
            "restricted_request_boundary": dict(
                option.get("restricted_request_boundary") or {}
            ),
            "inference_review_only": option.get("review_only") is True,
            "required_qualifiers": list(
                option.get("required_qualifiers") or []
            ),
            "prohibited_extensions": list(
                option.get("prohibited_claim_families") or []
            ),
        }

    @staticmethod
    def _project_bounded_inference_policies(
        minimal_context: dict[str, Any],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        str,
    ]:
        raw_policies = minimal_context.get("bounded_inference_policies") or []
        if not isinstance(raw_policies, list):
            return [], {}, "composer_inference_policy_schema_invalid"
        trusted_context = minimal_context.get(
            "trusted_domain_policy_context"
        )
        trusted_context = (
            trusted_context
            if isinstance(trusted_context, dict)
            else {}
        )
        trusted_pack_ref = str(
            trusted_context.get("pack_ref") or ""
        ).strip()
        trusted_pack_hash = _structured_sha256(
            trusted_context.get("pack_content_sha256")
        )
        if raw_policies and (
            trusted_context.get("schema_version")
            != "trusted-domain-policy-context/v1"
            or trusted_context.get("status") != "selected"
            or trusted_context.get("trusted_owner") != "analysis_pipeline"
            or trusted_context.get("provenance")
            != {
                "boundary": "analysis_pipeline_internal",
                "selector_owner": "file_policy_repository",
            }
            or trusted_context.get("selected_at_stage")
            != "canonical_input"
            or trusted_context.get("used_for_evidence") is not False
            or trusted_context.get("used_for_fact_support") is not False
            or trusted_context.get("can_change_can_send") is not False
            or not trusted_pack_ref
            or not trusted_pack_hash
        ):
            return [], {}, "composer_domain_policy_context_invalid"
        projected: list[dict[str, Any]] = []
        by_ref: dict[str, dict[str, Any]] = {}
        for item in raw_policies:
            if not isinstance(item, dict):
                return [], {}, "composer_inference_policy_schema_invalid"
            policy_ref = str(item.get("policy_ref") or "").strip()
            policy_intent_ref = str(
                item.get("policy_intent_ref") or ""
            ).strip()
            goal_family = str(item.get("goal_family") or "").strip()
            intent_kind = str(item.get("intent_kind") or "").strip()
            allowed_scope = str(item.get("allowed_scope") or "").strip()
            allowed_conclusion_family = str(
                item.get("allowed_conclusion_family") or ""
            ).strip()
            allowed_variability_factor_families = sorted({
                str(value).strip()
                for value in (
                    item.get("allowed_variability_factor_families")
                    or []
                )
                if str(value).strip()
            })
            advice_mode = str(
                item.get("advice_mode") or ""
            ).strip()
            maximum_risk_level = str(
                item.get("maximum_risk_level") or ""
            ).strip()
            required_qualifiers = sorted({
                str(value).strip()
                for value in item.get("required_qualifiers") or []
                if str(value).strip()
            })
            prohibited_claim_families = sorted({
                str(value).strip()
                for value in item.get("prohibited_claim_families") or []
                if str(value).strip()
            })
            premise_fact_families = sorted({
                str(value).strip()
                for value in item.get("premise_fact_families") or []
                if str(value).strip()
            })
            trusted_domain_pack_ref = (
                policy_ref.rsplit(":intent:", 1)[0]
                if ":intent:" in policy_ref
                else ""
            )
            pack_content_sha256 = _structured_sha256(
                item.get("pack_content_sha256")
            )
            if (
                not policy_ref
                or policy_ref in by_ref
                or not policy_intent_ref
                or not goal_family
                or not intent_kind
                or not allowed_scope
                or not allowed_conclusion_family
                or advice_mode not in {
                    "none",
                    "concise_care_only",
                    "safety_handoff_required",
                }
                or maximum_risk_level not in _INFERENCE_RISK_RANK
                or not premise_fact_families
                or not trusted_domain_pack_ref
                or trusted_domain_pack_ref != trusted_pack_ref
                or not pack_content_sha256
                or pack_content_sha256 != trusted_pack_hash
                or not required_qualifiers
                or not prohibited_claim_families
                or item.get("review_only") is not True
                or item.get("used_for_evidence") is not False
                or item.get("used_for_fact_support") is not False
                or item.get("can_change_can_send") is not False
            ):
                return [], {}, "composer_inference_policy_schema_invalid"
            projection = {
                "policy_ref": policy_ref,
                "policy_intent_ref": policy_intent_ref,
                "goal_family": goal_family,
                "intent_kind": intent_kind,
                "trusted_domain_pack_ref": trusted_domain_pack_ref,
                "pack_content_sha256": pack_content_sha256,
                "premise_fact_families": premise_fact_families,
                "allowed_scope": allowed_scope,
                "allowed_conclusion_family": (
                    allowed_conclusion_family
                ),
                "allowed_variability_factor_families": (
                    allowed_variability_factor_families
                ),
                "advice_mode": advice_mode,
                "maximum_risk_level": maximum_risk_level,
                "required_qualifiers": required_qualifiers,
                "prohibited_claim_families": prohibited_claim_families,
                "review_only": True,
                "used_for_evidence": False,
                "used_for_fact_support": False,
                "can_change_can_send": False,
            }
            by_ref[policy_ref] = projection
            projected.append(projection)
        return (
            sorted(projected, key=lambda item: item["policy_ref"]),
            by_ref,
            "",
        )

    @staticmethod
    def _actual_media_types(response: dict[str, Any]) -> list[str]:
        return sorted({
            str(block.get("type"))
            for block in response.get("reply_blocks") or []
            if (
                isinstance(block, dict)
                and block.get("type") in {"image", "video"}
                and str(block.get("url") or block.get("asset_url") or "").strip()
            )
        })

    @staticmethod
    def _prompt_payload(
        minimal_context: dict[str, Any],
        *,
        customer_message: str,
        evidence: list[dict[str, Any]],
        partitions: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "current_customer_question": str(
                minimal_context.get("customer_goal") or customer_message or ""
            ),
            "recent_conversation_turns": list(
                minimal_context.get("recent_conversation_turns") or []
            ),
            "product_scope": {
                "resolved": bool(
                    (
                        minimal_context.get("product_scope")
                        or {}
                    ).get("resolved")
                    if isinstance(
                        minimal_context.get("product_scope"),
                        dict,
                    )
                    else minimal_context.get("product_identity")
                ),
                "variant_context_present": bool(
                    (
                        minimal_context.get("product_scope")
                        or {}
                    ).get("variant_context_present")
                    if isinstance(
                        minimal_context.get("product_scope"),
                        dict,
                    )
                    else (
                        minimal_context.get("product_identity")
                        or {}
                    ).get("variant_reference")
                ),
            },
            "admitted_evidence": evidence,
            "renderable_customer_goals": list(
                partitions["renderable_customer_goals"]
            ),
            "presentation_order": list(
                partitions["presentation_order"]
            ),
            "supporting_dependencies": list(
                partitions["supporting_dependencies"]
            ),
            "service_actions": list(partitions["service_actions"]),
            "media_context": dict(partitions["media_context"]),
            "contextual_constraints": dict(
                partitions["contextual_constraints"]
            ),
        }

    @staticmethod
    def _schema_type_summary(schema: dict[str, Any]) -> str:
        value_type = str(schema.get("type") or "unknown")
        if value_type == "array":
            item_schema = schema.get("items")
            item_type = (
                ModelFirstAnswerComposerService._schema_type_summary(
                    item_schema
                )
                if isinstance(item_schema, dict)
                else "unknown"
            )
            return f"array<{item_type}>"
        enum_values = schema.get("enum")
        if isinstance(enum_values, list):
            return (
                f"{value_type}["
                + "|".join(str(item) for item in enum_values)
                + "]"
            )
        return value_type

    @classmethod
    def _schema_prompt_contract(
        cls,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response_schema = deepcopy(
            schema if schema is not None else COMPOSER_RESPONSE_SCHEMA
        )
        top_properties = response_schema.get("properties")
        clauses_schema = (
            top_properties.get("clauses")
            if isinstance(top_properties, dict)
            else None
        )
        clause_schema = (
            clauses_schema.get("items")
            if isinstance(clauses_schema, dict)
            else None
        )
        clause_properties = (
            clause_schema.get("properties")
            if isinstance(clause_schema, dict)
            else None
        )
        if (
            response_schema.get("type") != "object"
            or not isinstance(top_properties, dict)
            or not isinstance(clause_schema, dict)
            or clause_schema.get("type") != "object"
            or not isinstance(clause_properties, dict)
        ):
            raise ValueError("composer_response_schema_invalid")
        schema_sha256 = _canonical_json_sha256(response_schema)
        top_fields = list(top_properties)
        clause_fields = list(clause_properties)
        top_required = [
            str(item)
            for item in response_schema.get("required") or []
        ]
        clause_required = [
            str(item)
            for item in clause_schema.get("required") or []
        ]
        top_types = [
            f"{name}:{cls._schema_type_summary(top_properties[name])}"
            for name in top_fields
        ]
        clause_types = [
            f"{name}:{cls._schema_type_summary(clause_properties[name])}"
            for name in clause_fields
        ]
        summary = (
            f"唯一输出结构（schema_sha256={schema_sha256}）："
            f"顶层字段=[{','.join(top_types)}]，"
            f"required=[{','.join(top_required)}]，"
            "additionalProperties="
            f"{str(response_schema.get('additionalProperties')).lower()}；"
            f"clauses[*]字段=[{','.join(clause_types)}]，"
            f"required=[{','.join(clause_required)}]，"
            "additionalProperties="
            f"{str(clause_schema.get('additionalProperties')).lower()}。"
        )
        return {
            "schema_sha256": schema_sha256,
            "summary": summary,
            "summary_sha256": hashlib.sha256(
                summary.encode("utf-8")
            ).hexdigest(),
            "top_level_fields": top_fields,
            "top_level_required": top_required,
            "top_level_additional_properties": response_schema.get(
                "additionalProperties"
            ),
            "clause_fields": clause_fields,
            "clause_required": clause_required,
            "clause_additional_properties": clause_schema.get(
                "additionalProperties"
            ),
        }

    @classmethod
    def _output_contract_projection(cls) -> dict[str, Any]:
        schema_contract = cls._schema_prompt_contract()
        return {
            "schema_version": COMPOSER_RESPONSE_SCHEMA_VERSION,
            "response_schema_sha256": schema_contract[
                "schema_sha256"
            ],
            "prompt_schema_summary_sha256": schema_contract[
                "summary_sha256"
            ],
            "top_level_fields": schema_contract[
                "top_level_fields"
            ],
            "top_level_required": schema_contract[
                "top_level_required"
            ],
            "top_level_additional_properties": schema_contract[
                "top_level_additional_properties"
            ],
            "clause_fields": schema_contract["clause_fields"],
            "clause_required": schema_contract["clause_required"],
            "clause_additional_properties": schema_contract[
                "clause_additional_properties"
            ],
            "selected_option_refs_semantics": (
                "zero_or_one_goal_scoped_request_option_alias"
            ),
            "canonical_clause_metadata_owner": "server",
            "field_ownership": {
                key: list(value)
                for key, value in COMPOSER_CLAUSE_FIELD_OWNERSHIP.items()
            },
            "one_clause_per_goal": True,
            "clauses_follow_presentation_order": True,
            "one_option_per_goal": True,
            "option_selection_modes": sorted(_OPTION_SELECTION_MODES),
        }

    @classmethod
    def _system_prompt(cls) -> str:
        schema_summary = cls._schema_prompt_contract()["summary"]
        return (
            "你是电商金牌客服，只负责一次性组织候选回复，不决定事实资格和发送权限。"
            "仅使用 admitted_evidence 中的商品事实；service_actions 不是商品事实。"
            "低风险解释不得升级为承重、无毒、食品级、认证、儿童安全、防倾倒、安装处方、"
            "订单状态、退款、补发或物流结论。"
            "media_context 和 service_actions 不是可渲染商品事实；媒体候选数量不代表已经发送。"
            f"{schema_summary}"
            "renderable_customer_goals 中每个 goal_ref 必须恰好返回一个 clause，"
            "按 presentation_order 排列，不得遗漏、重复、新增、缩写或改写 goal_ref。"
            "supporting_dependencies 只提供绑定证据，不得为 dependency_ref 输出 clause。"
            "每个 goal 先按 option_selection_mode 决定 option 选择；该规则优先于"
            " required_clause_kind："
            "required 必须从该 goal 的 eligible_policy_options 恰好选择一个，"
            "selected_option_refs 必须是只含该 option_ref 的单元素数组；"
            "即使 required_clause_kind=unresolved 也相同。"
            "required clause 的 text 同时表达所选 allowed_scope、required_qualifiers"
            " 允许的具体低风险帮助和必要的 restricted boundary。"
            "allowed_conclusion_family 是唯一可表达的低风险结论族；"
            "allowed_variability_factor_families 只授权可选提及的一般变量，"
            "不是已验证商品事实，不要为了列全而形成因素清单。"
            "advice_mode=none 时不得主动给建议；concise_care_only 时至多一条"
            "与当前 goal 直接相关的简短保养建议；safety_handoff_required"
            " 只允许安全复核边界，不能承诺安全结论。"
            "restricted_request_boundary.must_remain_unresolved 只约束客户原始受限主张，"
            "不表示整个 clause 必须使用 unresolved，也不禁止表达所选有界帮助。"
            "optional 的 selected_option_refs 可以为空或只含一个 option_ref；"
            "forbidden 的 selected_option_refs 必须为空数组。"
            "未选择 option 时 evidence_refs 必须逐字复制 required_evidence_refs。"
            "选择 option 时 selected_option_refs 必须只含同一 goal 的 option_ref，"
            "evidence_refs 必须与该 option 的 premise_evidence_refs 完全相同；"
            "不得输出内部 policy ID、"
            "跨 goal 引用或新增 option、premise、scope。"
            "若 goal 带 restricted_request_boundary，所选有界说明必须保留该请求边界，"
            "不得把绝对保证、测试结论或责任承诺改写成已确认事实。"
            "未选择 option 且 required_clause_kind=supported_fact 时直接陈述已确认事实，"
            "不复述来源、审核或核对过程。"
            "选择 option 时只能在所选 policy scope 内解释，"
            "保留非绝对边界，不得扩展到 prohibited claim。"
            "未选择 option 且 required_clause_kind=unresolved 时结合 goal_summary 和当前问题，"
            "自然说明目前无法确认或不能保证，不补充原因、概率、性能、适用或使用建议。"
            "按客户提问顺序先回答已支持事实，再补充必要的低风险解释或边界；"
            "只问解决当前问题必需的一项信息。"
            "不得声称系统、资料库、RAG、字段缺失或转人工流程；不得承诺稍后回复。"
            "不要说“没有证据”“缺少证据”或“人工审核”，不要重复完整商品标题。"
            "多目标 clause 各自只回答对应 goal，拼接后应自然、礼貌、简洁，"
            "避免重复主语、边界、法务声明、报告字段、机器人语气和内部处理语言。"
            "结构优先：只返回一个 JSON object；只使用 schema 定义字段；"
            "每个 clause 只使用 clause schema 字段；不得增加说明、reasoning、metadata"
            " 或 diagnostics；结构义务优先于表达风格；客户可见文字只放在 text；"
            "内部引用只放在对应 schema 字段；JSON 外不得输出文字。"
        )

    @staticmethod
    def _validate_output(
        parsed: Any,
        *,
        known_refs: set[str],
        customer_goals: list[dict[str, Any]],
        presentation_order: list[str] | None = None,
        response: dict[str, Any],
        offered_option_bindings: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        reason, _ = ModelFirstAnswerComposerService._validate_output_with_diagnostics(
            parsed,
            known_refs=known_refs,
            customer_goals=customer_goals,
            presentation_order=presentation_order,
            response=response,
            offered_option_bindings=offered_option_bindings,
        )
        return reason

    @staticmethod
    def _validate_output_with_diagnostics(
        parsed: Any,
        *,
        known_refs: set[str],
        customer_goals: list[dict[str, Any]],
        presentation_order: list[str] | None = None,
        response: dict[str, Any],
        offered_option_bindings: dict[str, dict[str, Any]] | None = None,
        non_renderable_goal_refs: set[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        canonical, reconstruction_error, diagnostics = (
            ModelFirstAnswerComposerService
            ._reconstruct_canonical_output_with_diagnostics(
                parsed,
                known_refs=known_refs,
                customer_goals=customer_goals,
                presentation_order=presentation_order,
                offered_option_bindings=offered_option_bindings,
                non_renderable_goal_refs=non_renderable_goal_refs,
            )
        )
        if reconstruction_error:
            return reconstruction_error, diagnostics
        validation_error, diagnostics = (
            ModelFirstAnswerComposerService
            ._validate_canonical_output_with_diagnostics(
                canonical,
                known_refs=known_refs,
                customer_goals=customer_goals,
                presentation_order=presentation_order,
                response=response,
                offered_option_bindings=offered_option_bindings,
                non_renderable_goal_refs=non_renderable_goal_refs,
            )
        )
        if not validation_error and isinstance(parsed, dict):
            parsed.clear()
            parsed.update(deepcopy(canonical))
        return validation_error, diagnostics

    @staticmethod
    def _reconstruct_canonical_output_with_diagnostics(
        parsed: Any,
        *,
        known_refs: set[str],
        customer_goals: list[dict[str, Any]],
        presentation_order: list[str] | None = None,
        offered_option_bindings: dict[str, dict[str, Any]] | None = None,
        non_renderable_goal_refs: set[str] | None = None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        offered_option_bindings = dict(
            offered_option_bindings or {}
        )
        if not isinstance(parsed, dict):
            return {}, "composer_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                "top_level_schema_invalid",
                json_path="$",
                expected_type="object",
                actual_type=ModelFirstAnswerComposerService._type_name(parsed),
            )
        top_fields = set(parsed)
        if top_fields != _ALLOWED_OUTPUT_FIELDS:
            extra = top_fields - _ALLOWED_OUTPUT_FIELDS
            missing = _ALLOWED_OUTPUT_FIELDS - top_fields
            category = "extra_field" if extra else "top_level_schema_invalid"
            return {}, "composer_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                category,
                json_path="$",
                expected_type="object_with_exact_fields",
                actual_type="object",
                missing_field_count=len(missing),
                extra_field_count=len(extra),
            )
        clauses = parsed.get("clauses")
        if not isinstance(clauses, list):
            return {}, "composer_clauses_invalid", ModelFirstAnswerComposerService._diagnostics(
                "top_level_schema_invalid",
                json_path="$.clauses",
                expected_type="array",
                actual_type=ModelFirstAnswerComposerService._type_name(clauses),
            )
        goals_by_ref = {
            str(goal["goal_ref"]): goal for goal in customer_goals
        }
        expected_presentation_order = list(
            presentation_order
            if presentation_order is not None
            else goals_by_ref
        )
        if (
            len(expected_presentation_order)
            != len(set(expected_presentation_order))
            or set(expected_presentation_order) != set(goals_by_ref)
        ):
            return {}, "composer_presentation_order_invalid", ModelFirstAnswerComposerService._diagnostics(
                "presentation_order_invalid",
                parsed=parsed,
                json_path="$.presentation_order",
                expected_type="exact_goal_ref_permutation",
                actual_type="invalid_projection",
            )
        all_offered_option_refs = {
            str(option.get("option_ref") or "")
            for goal in customer_goals
            for option in goal.get("eligible_policy_options") or []
            if str(option.get("option_ref") or "")
        }
        canonical_policy_refs = {
            str(binding.get("policy_ref") or "")
            for binding in offered_option_bindings.values()
            if str(binding.get("policy_ref") or "")
        }
        clauses_by_ref: dict[str, dict[str, Any]] = {}
        selected_aliases: set[str] = set()
        for index, clause in enumerate(clauses):
            path = f"$.clauses[{index}]"
            if not isinstance(clause, dict):
                return {}, "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=path,
                    expected_type="object",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        clause
                    ),
                )
            clause_fields = set(clause)
            if clause_fields != _ALLOWED_CLAUSE_FIELDS:
                extra = clause_fields - _ALLOWED_CLAUSE_FIELDS
                missing = _ALLOWED_CLAUSE_FIELDS - clause_fields
                category = "extra_field" if extra else "clause_schema_invalid"
                return {}, "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    category,
                    parsed=parsed,
                    json_path=path,
                    expected_type="object_with_exact_fields",
                    actual_type="object",
                    missing_field_count=len(missing),
                    extra_field_count=len(extra),
                )
            goal_ref_value = clause.get("goal_ref")
            text_value = clause.get("text")
            if not isinstance(goal_ref_value, str) or not goal_ref_value.strip():
                return {}, "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="non_empty_string",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        goal_ref_value
                    ),
                )
            if not isinstance(text_value, str) or not text_value.strip():
                return {}, "composer_goal_clause_text_missing", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.text",
                    expected_type="non_empty_string",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        text_value
                    ),
                )
            goal_ref = goal_ref_value.strip()
            text = text_value.strip()
            evidence_refs = clause.get("evidence_refs")
            selected_option_refs = clause.get("selected_option_refs")
            if goal_ref not in goals_by_ref:
                if goal_ref in (non_renderable_goal_refs or set()):
                    return {}, "composer_non_renderable_goal_reference", ModelFirstAnswerComposerService._diagnostics(
                        "non_renderable_goal_ref",
                        parsed=parsed,
                        json_path=f"{path}.goal_ref",
                        expected_type="renderable_customer_goal_ref",
                        actual_type="non_renderable_goal_ref",
                    )
                return {}, "composer_unknown_goal_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_goal_ref",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="known_goal_ref",
                    actual_type="string",
                )
            if goal_ref in clauses_by_ref:
                return {}, "composer_duplicate_goal_clause", ModelFirstAnswerComposerService._diagnostics(
                    "duplicate_goal_clause",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="unique_goal_ref",
                    actual_type="duplicate_string",
                )
            if not isinstance(evidence_refs, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in evidence_refs
            ):
                return {}, "composer_evidence_refs_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="array_of_non_empty_strings",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        evidence_refs
                    ),
                )
            if not isinstance(selected_option_refs, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in selected_option_refs
            ):
                return {}, "composer_inference_policy_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.selected_option_refs",
                    expected_type="array_of_non_empty_strings",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        selected_option_refs
                    ),
                )
            refs = [str(item).strip() for item in evidence_refs]
            option_refs = [
                str(item).strip() for item in selected_option_refs
            ]
            if len(refs) != len(set(refs)):
                return {}, "composer_duplicate_evidence_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="unique_known_evidence_refs",
                    actual_type="array_with_duplicates",
                )
            if not set(refs).issubset(known_refs):
                return {}, "composer_unknown_evidence_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="known_evidence_refs",
                    actual_type="array",
                )
            if len(option_refs) != len(set(option_refs)):
                return {}, "composer_duplicate_inference_option_reference", ModelFirstAnswerComposerService._diagnostics(
                    "duplicate_policy_ref",
                    parsed=parsed,
                    json_path=f"{path}.selected_option_refs",
                    expected_type="unique_goal_scoped_option_refs",
                    actual_type="array_with_duplicates",
                )
            if len(option_refs) > 1:
                return {}, "composer_option_selection_count_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.selected_option_refs",
                    expected_type="array_with_at_most_one_item",
                    actual_type="array_with_multiple_items",
                )
            goal = goals_by_ref[goal_ref]
            option_selection_mode = str(
                goal.get("option_selection_mode") or ""
            ).strip()
            goal_options = {
                str(option.get("option_ref") or ""): option
                for option in goal.get("eligible_policy_options") or []
                if str(option.get("option_ref") or "")
            }
            expected_selection_mode = (
                ModelFirstAnswerComposerService._derive_option_selection_mode(
                    resolution_status=str(
                        goal.get("resolution_status") or ""
                    ).strip(),
                    option_count=len(goal_options),
                    selection_required=any(
                        (offered_option_bindings or {}).get(
                            option_ref,
                            {},
                        ).get("selection_required") is True
                        for option_ref in goal_options
                    ),
                )
            )
            if (
                option_selection_mode not in _OPTION_SELECTION_MODES
                or option_selection_mode != expected_selection_mode
            ):
                return {}, "composer_offered_projection_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "offered_projection_invalid",
                    parsed=parsed,
                    json_path=f"{path}.selected_option_refs",
                    expected_type="derived_option_selection_mode",
                    actual_type="projection_mismatch",
                )
            if option_refs:
                selected_option_ref = option_refs[0]
                if option_selection_mode == "forbidden":
                    return {}, "composer_forbidden_option_selected", ModelFirstAnswerComposerService._diagnostics(
                        "forbidden_option_selected",
                        parsed=parsed,
                        json_path=f"{path}.selected_option_refs",
                        expected_type="empty_option_selection",
                        actual_type="policy_selection",
                    )
                if selected_option_ref not in goal_options:
                    if selected_option_ref in canonical_policy_refs:
                        reason = (
                            "composer_canonical_policy_reference_forbidden"
                        )
                    else:
                        reason = (
                        "composer_wrong_goal_inference_policy_reference"
                        if selected_option_ref in all_offered_option_refs
                        else "composer_unknown_inference_policy_reference"
                        )
                    return {}, reason, ModelFirstAnswerComposerService._diagnostics(
                        "unknown_policy_ref",
                        parsed=parsed,
                        json_path=f"{path}.selected_option_refs",
                        expected_type="goal_scoped_offered_option_alias",
                        actual_type="array",
                        invalid_reference_sha256=hashlib.sha256(
                            selected_option_ref.encode("utf-8")
                        ).hexdigest(),
                    )
                if selected_option_ref in selected_aliases:
                    return {}, "composer_duplicate_inference_option_reference", ModelFirstAnswerComposerService._diagnostics(
                        "duplicate_policy_ref",
                        parsed=parsed,
                        json_path=f"{path}.selected_option_refs",
                        expected_type="unique_offered_option_alias",
                        actual_type="duplicate_string",
                        invalid_reference_sha256=hashlib.sha256(
                            selected_option_ref.encode("utf-8")
                        ).hexdigest(),
                    )
                selected_aliases.add(selected_option_ref)
                option = goal_options[selected_option_ref]
                binding = offered_option_bindings.get(
                    selected_option_ref
                )
                if (
                    not isinstance(binding, dict)
                    or binding.get("goal_ref") != goal_ref
                    or binding.get("premise_evidence_refs")
                    != option.get("premise_evidence_refs")
                    or binding.get("allowed_scope")
                    != option.get("allowed_scope")
                ):
                    return {}, "composer_offered_projection_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "offered_projection_invalid",
                        parsed=parsed,
                        json_path=f"{path}.selected_option_refs",
                        expected_type="exact_offered_option_binding",
                        actual_type="projection_mismatch",
                    )
                option_premises = list(
                    option.get("premise_evidence_refs") or []
                )
                if refs != option_premises:
                    return {}, "composer_bounded_inference_premise_omitted", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="exact_option_premise_evidence_refs",
                        actual_type="array",
                    )
                canonical_clause = {
                    "goal_ref": goal_ref,
                    "clause_kind": "allowed_inference",
                    "text": text,
                    "evidence_refs": list(option_premises),
                    "selected_policy_ref": selected_option_ref,
                    "premise_evidence_refs": list(option_premises),
                    "inference_scope": str(
                        binding.get("allowed_scope") or ""
                    ).strip(),
                }
            elif option_selection_mode == "required":
                return {}, "composer_required_option_not_selected", ModelFirstAnswerComposerService._diagnostics(
                    "required_option_not_selected",
                    parsed=parsed,
                    json_path=f"{path}.selected_option_refs",
                    expected_type="one_goal_scoped_offered_option_alias",
                    actual_type="empty_array",
                )
            elif goal["resolution_status"] == "supported":
                required_refs = list(goal["required_evidence_refs"])
                if refs != required_refs:
                    return {}, "composer_supported_claim_omitted", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="exact_required_evidence_refs",
                        actual_type="array",
                    )
                canonical_clause = {
                    "goal_ref": goal_ref,
                    "clause_kind": "supported_fact",
                    "text": text,
                    "evidence_refs": required_refs,
                    "selected_policy_ref": "",
                    "premise_evidence_refs": [],
                    "inference_scope": "",
                }
            else:
                if refs:
                    return {}, "composer_unresolved_goal_evidence_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="empty_array",
                        actual_type="non_empty_array",
                    )
                canonical_clause = {
                    "goal_ref": goal_ref,
                    "clause_kind": "unresolved",
                    "text": text,
                    "evidence_refs": [],
                    "selected_policy_ref": "",
                    "premise_evidence_refs": [],
                    "inference_scope": "",
                }
            clauses_by_ref[goal_ref] = canonical_clause
        if set(clauses_by_ref) != set(goals_by_ref):
            return {}, "composer_goal_clause_omitted", ModelFirstAnswerComposerService._diagnostics(
                "missing_goal_clause",
                parsed=parsed,
                json_path="$.clauses",
                expected_type="one_clause_per_goal",
                actual_type="incomplete_goal_set",
            )
        actual_presentation_order = [
            clause["goal_ref"] for clause in clauses_by_ref.values()
        ]
        if actual_presentation_order != expected_presentation_order:
            return {}, "composer_clause_presentation_order_invalid", ModelFirstAnswerComposerService._diagnostics(
                "clause_presentation_order_invalid",
                parsed=parsed,
                json_path="$.clauses[*].goal_ref",
                expected_type="presentation_order",
                actual_type="different_goal_ref_sequence",
            )
        canonical = {
            "clauses": [
                clauses_by_ref[goal_ref]
                for goal_ref in actual_presentation_order
            ]
        }
        return canonical, "", ModelFirstAnswerComposerService._diagnostics(
            "canonical_reconstruction_accepted",
            parsed=canonical,
        )

    @staticmethod
    def _validate_canonical_output_with_diagnostics(
        parsed: Any,
        *,
        known_refs: set[str],
        customer_goals: list[dict[str, Any]],
        presentation_order: list[str] | None = None,
        response: dict[str, Any],
        offered_option_bindings: dict[str, dict[str, Any]] | None = None,
        non_renderable_goal_refs: set[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        offered_option_bindings = dict(
            offered_option_bindings or {}
        )
        if not isinstance(parsed, dict):
            return "composer_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                "top_level_schema_invalid",
                json_path="$",
                expected_type="object",
                actual_type=ModelFirstAnswerComposerService._type_name(parsed),
            )
        top_fields = set(parsed)
        if top_fields != _ALLOWED_OUTPUT_FIELDS:
            extra = top_fields - _ALLOWED_OUTPUT_FIELDS
            missing = _ALLOWED_OUTPUT_FIELDS - top_fields
            category = "extra_field" if extra else "top_level_schema_invalid"
            return "composer_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                category,
                json_path="$",
                expected_type="object_with_exact_fields",
                actual_type="object",
                missing_field_count=len(missing),
                extra_field_count=len(extra),
            )
        clauses = parsed.get("clauses")
        if not isinstance(clauses, list):
            return "composer_clauses_invalid", ModelFirstAnswerComposerService._diagnostics(
                "top_level_schema_invalid",
                json_path="$.clauses",
                expected_type="array",
                actual_type=ModelFirstAnswerComposerService._type_name(clauses),
            )
        goals_by_ref = {
            str(goal["goal_ref"]): goal for goal in customer_goals
        }
        expected_presentation_order = list(
            presentation_order
            if presentation_order is not None
            else goals_by_ref
        )
        if (
            len(expected_presentation_order)
            != len(set(expected_presentation_order))
            or set(expected_presentation_order) != set(goals_by_ref)
        ):
            return "composer_presentation_order_invalid", ModelFirstAnswerComposerService._diagnostics(
                "presentation_order_invalid",
                parsed=parsed,
                json_path="$.presentation_order",
                expected_type="exact_goal_ref_permutation",
                actual_type="invalid_projection",
            )
        clauses_by_ref: dict[str, dict[str, Any]] = {}
        selected_option_refs: set[str] = set()
        for index, clause in enumerate(clauses):
            path = f"$.clauses[{index}]"
            if not isinstance(clause, dict):
                return "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=path,
                    expected_type="object",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        clause
                    ),
                )
            clause_fields = set(clause)
            if clause_fields != _CANONICAL_CLAUSE_FIELDS:
                extra = clause_fields - _CANONICAL_CLAUSE_FIELDS
                missing = _CANONICAL_CLAUSE_FIELDS - clause_fields
                category = "extra_field" if extra else "clause_schema_invalid"
                return "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    category,
                    parsed=parsed,
                    json_path=path,
                    expected_type="canonical_clause_with_exact_fields",
                    actual_type="object",
                    missing_field_count=len(missing),
                    extra_field_count=len(extra),
                )
            goal_ref = str(clause.get("goal_ref") or "").strip()
            clause_kind = str(clause.get("clause_kind") or "").strip()
            text = str(clause.get("text") or "").strip()
            evidence_refs = clause.get("evidence_refs")
            selected_policy_ref = clause.get("selected_policy_ref")
            premise_evidence_refs = clause.get("premise_evidence_refs")
            inference_scope = clause.get("inference_scope")
            if goal_ref not in goals_by_ref:
                if goal_ref in (non_renderable_goal_refs or set()):
                    return "composer_non_renderable_goal_reference", ModelFirstAnswerComposerService._diagnostics(
                        "non_renderable_goal_ref",
                        parsed=parsed,
                        json_path=f"{path}.goal_ref",
                        expected_type="renderable_customer_goal_ref",
                        actual_type="non_renderable_goal_ref",
                    )
                return "composer_unknown_goal_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_goal_ref",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="known_goal_ref",
                    actual_type="string",
                )
            if goal_ref in clauses_by_ref:
                return "composer_duplicate_goal_clause", ModelFirstAnswerComposerService._diagnostics(
                    "duplicate_goal_clause",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="unique_goal_ref",
                    actual_type="duplicate_string",
                )
            if clause_kind not in _ALLOWED_CLAUSE_KINDS:
                return "composer_clause_kind_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "wrong_clause_kind",
                    parsed=parsed,
                    json_path=f"{path}.clause_kind",
                    expected_type="allowed_enum",
                    actual_type="string",
                    invalid_enum_count=1,
                )
            if not text:
                return "composer_goal_clause_text_missing", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.text",
                    expected_type="non_empty_string",
                    actual_type="empty_string",
                )
            if not isinstance(evidence_refs, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in evidence_refs
            ):
                return "composer_evidence_refs_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="array_of_non_empty_strings",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        evidence_refs
                    ),
                )
            if not isinstance(selected_policy_ref, str):
                return "composer_inference_policy_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.selected_policy_ref",
                    expected_type="string",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        selected_policy_ref
                    ),
                )
            if not isinstance(inference_scope, str):
                return "composer_inference_policy_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.inference_scope",
                    expected_type="string",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        inference_scope
                    ),
                )
            if not isinstance(premise_evidence_refs, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in premise_evidence_refs
            ):
                return "composer_inference_policy_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.premise_evidence_refs",
                    expected_type="array_of_non_empty_strings",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        premise_evidence_refs
                    ),
                )
            refs = [str(item).strip() for item in evidence_refs]
            premise_refs = [
                str(item).strip() for item in premise_evidence_refs
            ]
            if len(refs) != len(set(refs)):
                return "composer_duplicate_evidence_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="unique_known_evidence_refs",
                    actual_type="array_with_duplicates",
                )
            if not set(refs).issubset(known_refs):
                return "composer_unknown_evidence_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="known_evidence_refs",
                    actual_type="array",
                )
            if (
                len(premise_refs) != len(set(premise_refs))
                or not set(premise_refs).issubset(known_refs)
            ):
                return "composer_bounded_inference_premise_omitted", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.premise_evidence_refs",
                    expected_type="unique_known_evidence_refs",
                    actual_type="array",
                )
            selected_policy_ref = selected_policy_ref.strip()
            inference_scope = inference_scope.strip()
            goal = goals_by_ref[goal_ref]
            required_kind = goal["required_clause_kind"]
            option_selection_mode = str(
                goal.get("option_selection_mode") or ""
            ).strip()
            goal_options = {
                str(option.get("option_ref") or ""): option
                for option in goal.get("eligible_policy_options") or []
                if str(option.get("option_ref") or "")
            }
            expected_selection_mode = (
                ModelFirstAnswerComposerService._derive_option_selection_mode(
                    resolution_status=str(
                        goal.get("resolution_status") or ""
                    ).strip(),
                    option_count=len(goal_options),
                    selection_required=any(
                        (offered_option_bindings or {}).get(
                            option_ref,
                            {},
                        ).get("selection_required") is True
                        for option_ref in goal_options
                    ),
                )
            )
            if (
                option_selection_mode not in _OPTION_SELECTION_MODES
                or option_selection_mode != expected_selection_mode
            ):
                return "composer_offered_projection_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "offered_projection_invalid",
                    parsed=parsed,
                    json_path=f"{path}.selected_policy_ref",
                    expected_type="derived_option_selection_mode",
                    actual_type="projection_mismatch",
                )
            all_offered_option_refs = {
                str(option.get("option_ref") or "")
                for offered_goal in customer_goals
                for option in offered_goal.get("eligible_policy_options") or []
                if str(option.get("option_ref") or "")
            }
            if clause_kind == "allowed_inference":
                if option_selection_mode == "forbidden":
                    return "composer_forbidden_option_selected", ModelFirstAnswerComposerService._diagnostics(
                        "forbidden_option_selected",
                        parsed=parsed,
                        json_path=f"{path}.selected_policy_ref",
                        expected_type="empty_policy_selection_fields",
                        actual_type="policy_selection",
                    )
                if not selected_policy_ref:
                    return "composer_unknown_inference_policy_reference", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_policy_ref",
                        parsed=parsed,
                        json_path=f"{path}.selected_policy_ref",
                        expected_type="offered_option_alias",
                        actual_type="empty_string",
                    )
                canonical_policy_refs = {
                    str(binding.get("policy_ref") or "")
                    for binding in offered_option_bindings.values()
                    if str(binding.get("policy_ref") or "")
                }
                if selected_policy_ref not in goal_options:
                    reason = (
                        "composer_canonical_policy_reference_forbidden"
                        if selected_policy_ref in canonical_policy_refs
                        else (
                            "composer_wrong_goal_inference_policy_reference"
                            if selected_policy_ref in all_offered_option_refs
                            else "composer_unknown_inference_policy_reference"
                        )
                    )
                    return reason, ModelFirstAnswerComposerService._diagnostics(
                        "unknown_policy_ref",
                        parsed=parsed,
                        json_path=f"{path}.selected_policy_ref",
                        expected_type="goal_scoped_offered_option_alias",
                        actual_type="string",
                        invalid_reference_sha256=hashlib.sha256(
                            selected_policy_ref.encode("utf-8")
                        ).hexdigest(),
                    )
                if selected_policy_ref in selected_option_refs:
                    return "composer_duplicate_inference_option_reference", ModelFirstAnswerComposerService._diagnostics(
                        "duplicate_policy_ref",
                        parsed=parsed,
                        json_path=f"{path}.selected_policy_ref",
                        expected_type="unique_offered_option_alias",
                        actual_type="duplicate_string",
                        invalid_reference_sha256=hashlib.sha256(
                            selected_policy_ref.encode("utf-8")
                        ).hexdigest(),
                    )
                selected_option_refs.add(selected_policy_ref)
                option = goal_options[selected_policy_ref]
                binding = offered_option_bindings.get(selected_policy_ref)
                if (
                    not isinstance(binding, dict)
                    or binding.get("goal_ref") != goal_ref
                    or binding.get("premise_evidence_refs")
                    != option.get("premise_evidence_refs")
                    or binding.get("allowed_scope")
                    != option.get("allowed_scope")
                ):
                    return "composer_offered_projection_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "offered_projection_invalid",
                        parsed=parsed,
                        json_path=f"{path}.selected_policy_ref",
                        expected_type="exact_offered_option_binding",
                        actual_type="projection_mismatch",
                    )
                option_premises = list(
                    option.get("premise_evidence_refs") or []
                )
                if (
                    refs != option_premises
                    or premise_refs != option_premises
                ):
                    return "composer_bounded_inference_premise_omitted", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.premise_evidence_refs",
                        expected_type="exact_option_premise_evidence_refs",
                        actual_type="array",
                    )
                if inference_scope != option.get("allowed_scope"):
                    return "composer_bounded_inference_scope_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "clause_content_invalid",
                        parsed=parsed,
                        json_path=f"{path}.inference_scope",
                        expected_type="offered_policy_scope",
                        actual_type="string",
                    )
            elif selected_policy_ref or premise_refs or inference_scope:
                return "composer_unselected_policy_metadata_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=path,
                    expected_type="empty_policy_selection_fields",
                    actual_type="policy_metadata_without_allowed_inference",
                )
            elif option_selection_mode == "required":
                return "composer_required_option_not_selected", ModelFirstAnswerComposerService._diagnostics(
                    "required_option_not_selected",
                    parsed=parsed,
                    json_path=f"{path}.selected_policy_ref",
                    expected_type="one_goal_scoped_offered_option_alias",
                    actual_type="empty_string",
                )
            elif goal["resolution_status"] == "supported":
                if clause_kind != required_kind:
                    return "composer_supported_goal_clause_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "wrong_clause_kind",
                        parsed=parsed,
                        json_path=f"{path}.clause_kind",
                        expected_type="required_clause_kind",
                        actual_type="allowed_enum",
                        invalid_enum_count=1,
                    )
                if refs != list(goal["required_evidence_refs"]):
                    return "composer_supported_claim_omitted", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="exact_required_evidence_refs",
                        actual_type="array",
                    )
            else:
                if clause_kind != "unresolved":
                    return "composer_unresolved_goal_asserted", ModelFirstAnswerComposerService._diagnostics(
                        "wrong_clause_kind",
                        parsed=parsed,
                        json_path=f"{path}.clause_kind",
                        expected_type="unresolved",
                        actual_type="allowed_enum",
                        invalid_enum_count=1,
                    )
                if refs:
                    return "composer_unresolved_goal_evidence_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="empty_array",
                        actual_type="non_empty_array",
                    )
            clauses_by_ref[goal_ref] = {
                "goal_ref": goal_ref,
                "clause_kind": clause_kind,
                "text": text,
                "evidence_refs": refs,
                "selected_policy_ref": selected_policy_ref,
                "premise_evidence_refs": premise_refs,
                "inference_scope": inference_scope,
            }
        if set(clauses_by_ref) != set(goals_by_ref):
            return "composer_goal_clause_omitted", ModelFirstAnswerComposerService._diagnostics(
                "missing_goal_clause",
                parsed=parsed,
                json_path="$.clauses",
                expected_type="one_clause_per_goal",
                actual_type="incomplete_goal_set",
            )
        actual_presentation_order = [
            str(clause["goal_ref"]).strip() for clause in clauses
        ]
        if actual_presentation_order != expected_presentation_order:
            return "composer_clause_presentation_order_invalid", ModelFirstAnswerComposerService._diagnostics(
                "clause_presentation_order_invalid",
                parsed=parsed,
                json_path="$.clauses[*].goal_ref",
                expected_type="presentation_order",
                actual_type="different_goal_ref_sequence",
            )
        ordered_output_clauses = [
            clauses_by_ref[goal_ref]
            for goal_ref in actual_presentation_order
        ]
        internal_language_match = (
            ModelFirstAnswerComposerService
            ._customer_visible_language_match(
                ordered_output_clauses,
                terms=CUSTOMER_FACING_INTERNAL_REDLINE_TERMS,
                trigger_categories=(
                    _INTERNAL_LANGUAGE_TRIGGER_CATEGORIES
                ),
                detector_family="customer_facing_internal_redline",
                case_insensitive=True,
            )
        )
        if internal_language_match:
            return "composer_internal_language", ModelFirstAnswerComposerService._diagnostics(
                "clause_content_invalid",
                parsed=parsed,
                json_path=internal_language_match["json_path"],
                expected_type="customer_facing_text",
                actual_type="internal_language",
                language_match=internal_language_match,
            )
        process_language_match = (
            ModelFirstAnswerComposerService
            ._customer_visible_language_match(
                ordered_output_clauses,
                terms=_PROCESS_LANGUAGE_TERMS,
                trigger_categories=(
                    _PROCESS_LANGUAGE_TRIGGER_CATEGORIES
                ),
                detector_family="composer_process_language",
                case_insensitive=False,
            )
        )
        if process_language_match:
            return "composer_process_language", ModelFirstAnswerComposerService._diagnostics(
                "clause_content_invalid",
                parsed=parsed,
                json_path=process_language_match["json_path"],
                expected_type="direct_customer_answer",
                actual_type="process_language",
                language_match=process_language_match,
            )
        media_diagnostics = ModelFirstAnswerComposerService._media_claim_diagnostics(
            parsed,
            customer_goals=customer_goals,
            response=response,
            minimal_context=ModelFirstAnswerComposerService._minimal_context(
                response
            ),
        )
        if media_diagnostics:
            return "composer_unsupported_media_promise", ModelFirstAnswerComposerService._diagnostics(
                "unsupported_media_promise",
                parsed=parsed,
                json_path=media_diagnostics["json_path"],
                expected_type="media_delivery_contract",
                actual_type="unsupported_media_claim",
            )
        return "", ModelFirstAnswerComposerService._diagnostics(
            "accepted",
            parsed=parsed,
        )

    @staticmethod
    def _record_provider_response(
        result: dict[str, Any],
        *,
        content: str,
        finish_reason: str,
        latency_ms: int,
    ) -> None:
        stripped = content.strip()
        if not stripped:
            envelope = "empty"
        elif stripped.startswith("```"):
            envelope = "fenced_text"
        elif stripped.startswith("{"):
            envelope = "json_object" if stripped.endswith("}") else "json_fragment"
        elif stripped.startswith("["):
            envelope = "json_value" if stripped.endswith("]") else "json_fragment"
        else:
            envelope = "free_text"
        result["provider_diagnostics"].update({
            "response_envelope": envelope,
            "response_length": len(content),
            "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "finish_reason": finish_reason,
            "provider_latency_ms": max(0, latency_ms),
        })

    @staticmethod
    def _unwrap_json_envelope(
        content: str,
    ) -> tuple[str, str, int, str]:
        """Unwrap one complete JSON fence without repairing its payload."""

        stripped = str(content or "").strip()
        if "```" not in stripped:
            if stripped.startswith("{"):
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

    @staticmethod
    def _diagnostics(
        category: str,
        *,
        parsed: Any = None,
        json_path: str = "",
        expected_type: str = "",
        actual_type: str = "",
        missing_field_count: int = 0,
        extra_field_count: int = 0,
        invalid_enum_count: int = 0,
        invalid_reference_sha256: str = "",
        language_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clauses = (
            parsed.get("clauses")
            if isinstance(parsed, dict)
            and isinstance(parsed.get("clauses"), list)
            else []
        )
        clause_rows = [item for item in clauses if isinstance(item, dict)]
        diagnostics = {
            "category": category,
            "json_path": json_path,
            "expected_type": expected_type,
            "actual_type": actual_type,
            "missing_field_count": max(0, missing_field_count),
            "extra_field_count": max(0, extra_field_count),
            "invalid_enum_count": max(0, invalid_enum_count),
            "invalid_reference_sha256": _structured_sha256(
                invalid_reference_sha256
            ),
            "clause_count": len(clauses),
            "goal_ref_count": sum(
                1
                for item in clause_rows
                if str(item.get("goal_ref") or "").strip()
            ),
            "evidence_ref_count": sum(
                len(item.get("evidence_refs") or [])
                for item in clause_rows
                if isinstance(item.get("evidence_refs"), list)
            ),
        }
        if language_match:
            diagnostics["language_match"] = {
                "detector_family": str(
                    language_match.get("detector_family") or ""
                ),
                "reason_code": str(
                    language_match.get("reason_code") or ""
                ),
                "trigger_category": str(
                    language_match.get("trigger_category") or ""
                ),
                "clause_index": int(
                    language_match.get("clause_index") or 0
                ),
                "goal_ref": str(
                    language_match.get("goal_ref") or ""
                ),
                "json_path": str(
                    language_match.get("json_path") or ""
                ),
                "text_sha256": _structured_sha256(
                    language_match.get("text_sha256")
                ),
                "rule_sha256": _structured_sha256(
                    language_match.get("rule_sha256")
                ),
            }
        return diagnostics

    @staticmethod
    def _customer_visible_language_match(
        clauses: list[dict[str, Any]],
        *,
        terms: tuple[str, ...],
        trigger_categories: dict[str, str],
        detector_family: str,
        case_insensitive: bool,
    ) -> dict[str, Any]:
        """Attribute an existing text-only rule without changing its meaning."""

        texts = [
            str(clause.get("text") or "")
            for clause in clauses
        ]
        joined = "".join(texts)
        comparable = joined.lower() if case_insensitive else joined
        for term in terms:
            needle = term.lower() if case_insensitive else term
            offset = comparable.find(needle)
            if offset < 0:
                continue
            clause_index = 0
            consumed = 0
            for index, text in enumerate(texts):
                clause_index = index
                consumed += len(text)
                if offset < consumed:
                    break
            clause = (
                clauses[clause_index]
                if clause_index < len(clauses)
                else {}
            )
            return {
                "detector_family": detector_family,
                "reason_code": (
                    "customer_visible_internal_language_detected"
                    if detector_family
                    == "customer_facing_internal_redline"
                    else "customer_visible_process_language_detected"
                ),
                "trigger_category": str(
                    trigger_categories.get(term)
                    or "uncategorized_internal_language"
                ),
                "clause_index": clause_index,
                "goal_ref": str(clause.get("goal_ref") or ""),
                "json_path": (
                    f"$.clauses[{clause_index}].text"
                ),
                "text_sha256": hashlib.sha256(
                    str(clause.get("text") or "").encode("utf-8")
                ).hexdigest(),
                "rule_sha256": hashlib.sha256(
                    term.encode("utf-8")
                ).hexdigest(),
            }
        return {}

    @staticmethod
    def _type_name(value: Any) -> str:
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

    @staticmethod
    def _media_claim_diagnostics(
        parsed: Any,
        *,
        customer_goals: list[dict[str, Any]],
        response: dict[str, Any],
        minimal_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("clauses"),
            list,
        ):
            return {}
        goals_by_ref = {
            str(goal.get("goal_ref") or ""): goal
            for goal in customer_goals
            if isinstance(goal, dict)
        }
        actual_types = ModelFirstAnswerComposerService._actual_media_types(
            response
        )
        attached_count = len([
            block
            for block in response.get("reply_blocks") or []
            if (
                isinstance(block, dict)
                and block.get("type") in {"image", "video"}
                and str(block.get("url") or block.get("asset_url") or "").strip()
            )
        ])
        for index, clause in enumerate(parsed["clauses"]):
            if not isinstance(clause, dict):
                continue
            text = str(clause.get("text") or "").strip()
            makes_delivery_claim = (
                bool(_claimed_delivery_media_kinds(text))
                or contains_unsupported_media_promise(text, False)
                or ModelFirstAnswerComposerService._unsupported_dimension_media_promise(
                    text,
                    {"reply_blocks": []},
                )
            )
            if not makes_delivery_claim:
                continue
            goal_ref = str(clause.get("goal_ref") or "").strip()
            goal = goals_by_ref.get(goal_ref) or {}
            goal_is_media_request = goal.get("media_request") is True
            issue_codes = list(
                media_delivery_claim_issues(response, reply=text)
            )
            if not goal_is_media_request:
                issue_codes.append("media_goal_missing")
            if not actual_types:
                issue_codes.append("actual_media_block_missing")
            fact_type = str(
                response.get("query_fact_type")
                or (response.get("evidence_debug") or {}).get(
                    "query_fact_type"
                )
                or ""
            ).strip()
            if fact_type in {"dimensions", "space_fit"} and actual_types:
                identity_context = (
                    minimal_context.get("product_identity")
                    if isinstance(
                        minimal_context.get("product_identity"),
                        dict,
                    )
                    else {}
                )
                identity = {
                    key: response.get(key) or identity_context.get(key)
                    for key in ("product_id", "i_id", "sku_code")
                }
                attached_blocks = [
                    block
                    for block in response.get("reply_blocks") or []
                    if (
                        isinstance(block, dict)
                        and block.get("type") in {"image", "video"}
                        and str(
                            block.get("url") or block.get("asset_url") or ""
                        ).strip()
                    )
                ]
                if not any(
                    is_delivery_media_asset_eligible(
                        block,
                        query_fact_type=fact_type,
                        product_identity=identity,
                    )
                    for block in attached_blocks
                ):
                    for media_type in actual_types:
                        issue_codes.append(
                            f"{fact_type}_{media_type}_role_or_identity_mismatch"
                        )
            issue_codes = sorted(set(issue_codes))
            if not issue_codes and has_attached_sendable_media_asset(response):
                continue
            return {
                "json_path": f"$.clauses[{index}].text",
                "clause_kind": str(clause.get("clause_kind") or ""),
                "goal_ref": goal_ref,
                "goal_is_media_request": goal_is_media_request,
                "media_candidate_count": len(
                    minimal_context.get("media_candidates") or []
                ),
                "actual_attached_media_count": attached_count,
                "actual_attached_media_type_count": len(actual_types),
                "issue_codes": issue_codes,
                "source": "model_clause",
            }
        return {}

    @staticmethod
    def _unsupported_dimension_media_promise(
        reply: str,
        response: dict[str, Any],
    ) -> bool:
        if has_attached_sendable_media_asset(response):
            return False
        return (
            "尺寸图" in reply
            and any(term in reply for term in ("已发", "已经发", "发给您", "给您发", "下面", "下方"))
        )

    @staticmethod
    def _append_reason(existing: str, reason: str) -> str:
        values = [item for item in (existing.strip(), reason.strip()) if item]
        return "; ".join(dict.fromkeys(values))
