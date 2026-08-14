"""Canonical, role-aware conversation turns for analysis entry points.

Formal turns preserve operational text for local orchestration and tools.  A
separate projection is used whenever a turn is placed in an external-model
prompt or an evaluation artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.services.fact_type_alias_service import (
    canonical_dimension_subject_scope,
    is_dimension_claim_type,
)


_ROLE_ALIASES = {
    "customer": "customer", "buyer": "customer", "user": "customer",
    "agent": "agent", "assistant": "agent", "seller": "agent", "csr": "agent", "system": "system",
}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_ORDER_REFERENCE = re.compile(
    r"(?i)(?:订单(?:号|编号)?|order(?:\s*(?:no|id))?)\s*[:：#-]?\s*[a-z0-9-]{4,}"
)
_TRACKING_REFERENCE = re.compile(
    r"(?i)(?:快递(?:单号)?|物流(?:单号)?|tracking(?:\s*(?:no|id))?)\s*[:：#-]?\s*[a-z0-9-]{6,}"
)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w.+-])")
_SECRET = re.compile(r"(?i)\b(token|secret|api[_-]?key|access[_-]?key|signature|password)\b\s*[:=]\s*[^\s&]+")
_URL = re.compile(r"https?://[^\s\"'<>]+")
_LONG_ID = re.compile(r"(?<!\d)\d{12,}(?!\d)")
_ADDRESS = re.compile(
    r"(?:(?:收货地址|地址|寄往|送到|收件人住址)\s*[:：]?\s*)?"
    r"(?:[一-鿿]{2,}(?:省|市|区|县))?[一-鿿0-9-]{2,}(?:路|街|巷|弄|小区)[一-鿿0-9#-]{1,}(?:号|栋|室|单元)"
)
_LABELED_IDENTIFIER_REFERENCE = re.compile(
    r"(?ix)(?P<label>['\"]?(?:"
    r"订单(?:号|编号)?|order(?:[_\s-]*(?:id|no))?|"
    r"快递(?:单号)?|物流(?:单号)?|tracking(?:[_\s-]*(?:id|no))?|"
    r"sku(?:[_\s-]*(?:code|id))?|i[_\s-]?id|product[_\s-]?id|item[_\s-]?id"
    r")[ '\"]*)\s*[:：]?\s*(?P<value>\"[^\"]*\"|'[^']*'|[A-Za-z0-9_-]{4,})"
)
_PRIVATE_IDENTIFIER_FIELDS = frozenset({
    "order_id", "platform_order_id", "platform_trade_id", "tracking_no", "tracking_number",
    "phone", "mobile", "address", "buyer_nick", "buyer_name", "buyer_id", "account", "email",
})
_PRODUCT_IDENTIFIER_FIELDS = frozenset({"sku", "sku_code", "sku_id", "i_id", "product_id", "item_id"})
_STRICT_EVALUATION_SOURCES = frozenset({
    "agent_benchmark",
    "real_conversation_eval",
    "real_accuracy_baseline",
    "tier_d_long_conversation_simulation",
})
_CONVERSATION_GOAL_LIFECYCLE_SCHEMA_VERSION = "conversation-goal-lifecycle/v1"
_CONVERSATION_GOAL_OPEN_FIELDS = frozenset({
    "goal_alias",
    "goal_ref",
    "conversation_ref",
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "attribute_key",
    "subject_scope",
    "semantic_key",
    "policy_intent_ref",
    "policy_goal_family",
    "policy_intent_kind",
    "source_turn_uid",
    "source_span_sha256",
})


@dataclass(frozen=True)
class ConversationContextContractError(ValueError):
    reason: str

    def __str__(self) -> str:
        return self.reason


def is_strict_evaluation_source(source: Any, context: dict[str, Any] | None = None) -> bool:
    """Return whether malformed history must stop before graph execution."""
    if str(source or "").strip() in _STRICT_EVALUATION_SOURCES:
        return True
    return bool(isinstance(context, dict) and context.get("evaluation_context_contract") == "strict")


def canonical_conversation_reference_status(
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project an internal Canonical Conversation verdict, or remain unknown."""
    context = normalize_trusted_answer_eligibility_owner_context(context)
    raw = context.get("conversation_reference_status")
    if not isinstance(raw, dict):
        return {
            "status": "unknown",
            "source_stage": "canonical_context_resolution",
            "reason_codes": ["conversation_reference_owner_missing"],
        }
    if (
        str(raw.get("owner") or "").strip() != "canonical_conversation"
        or str(raw.get("source_stage") or "").strip()
        != "canonical_context_resolution"
    ):
        return {
            "status": "unknown",
            "source_stage": "canonical_context_resolution",
            "reason_codes": ["conversation_reference_owner_invalid"],
        }
    allowed = {
        "not_required",
        "resolved",
        "ambiguous",
        "missing",
        "unknown",
    }
    status = str(raw.get("status") or "").strip().lower()
    if status not in allowed:
        return {
            "status": "unknown",
            "source_stage": "canonical_context_resolution",
            "reason_codes": ["conversation_reference_status_invalid"],
        }
    reasons = raw.get("reason_codes")
    if not isinstance(reasons, list):
        reasons = []
    return {
        "status": status,
        "source_stage": "canonical_context_resolution",
        "reason_codes": sorted({
            str(reason).strip()
            for reason in reasons
            if str(reason or "").strip()
        }),
    }


def normalize_conversation_goal_open_candidates(value: Any) -> list[dict[str, str]]:
    """Validate the internal, privacy-minimal projection of unfinished goals."""
    if not isinstance(value, list) or len(value) > 12:
        return []
    aliases: set[str] = set()
    normalized: list[dict[str, str]] = []
    legacy_fields = _CONVERSATION_GOAL_OPEN_FIELDS - {"subject_scope"}
    for item in value:
        if not isinstance(item, dict) or (
            set(item) != _CONVERSATION_GOAL_OPEN_FIELDS
            and set(item) != legacy_fields
        ):
            return []
        normalized_item = {
            key: str(item.get(key) or "").strip()
            for key in _CONVERSATION_GOAL_OPEN_FIELDS
        }
        if (
            not re.fullmatch(r"open-goal-[0-9a-f]{24}", normalized_item["goal_alias"])
            or not re.fullmatch(r"goal-[0-9a-f]{16}", normalized_item["goal_ref"])
            or not re.fullmatch(r"conversation-[0-9a-f]{32}", normalized_item["conversation_ref"])
            or not re.fullmatch(r"turn-[0-9a-f]{20}", normalized_item["source_turn_uid"])
            or not re.fullmatch(r"[0-9a-f]{64}", normalized_item["source_span_sha256"])
            or normalized_item["goal_kind"] != "customer_goal"
            or normalized_item["claim_type_status"] not in {"canonical", "unmapped"}
            or normalized_item["goal_alias"] in aliases
        ):
            return []
        if normalized_item["claim_type_status"] == "canonical":
            if (
                not normalized_item["claim_type"]
                or normalized_item["semantic_key"]
            ):
                return []
        elif normalized_item["claim_type"]:
            return []
        scope = canonical_dimension_subject_scope(
            normalized_item["subject_scope"]
        )
        if (
            normalized_item["subject_scope"] and not scope
        ) or (
            scope and not is_dimension_claim_type(
                normalized_item["claim_type"]
            )
        ):
            return []
        normalized_item["subject_scope"] = scope
        aliases.add(normalized_item["goal_alias"])
        normalized.append(normalized_item)
    return sorted(normalized, key=lambda item: item["goal_alias"])


def normalize_trusted_conversation_goal_lifecycle_context(
    value: Any,
) -> dict[str, Any]:
    """Accept only the Pipeline-owned lifecycle projection for one conversation."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "owner", "conversation_ref", "open_goals"
    }:
        return {}
    if (
        value.get("schema_version") != _CONVERSATION_GOAL_LIFECYCLE_SCHEMA_VERSION
        or value.get("owner") != "analysis_pipeline"
    ):
        return {}
    conversation_ref = str(value.get("conversation_ref") or "").strip()
    if not re.fullmatch(r"conversation-[0-9a-f]{32}", conversation_ref):
        return {}
    open_goals = normalize_conversation_goal_open_candidates(value.get("open_goals"))
    if len(open_goals) != len(value.get("open_goals") or []):
        return {}
    if any(goal["conversation_ref"] != conversation_ref for goal in open_goals):
        return {}
    return {
        "schema_version": _CONVERSATION_GOAL_LIFECYCLE_SCHEMA_VERSION,
        "owner": "analysis_pipeline",
        "conversation_ref": conversation_ref,
        "open_goals": open_goals,
    }


def normalize_trusted_answer_eligibility_owner_context(
    value: Any,
) -> dict[str, Any]:
    """Accept only the server-side Pipeline owner-input contract.

    Public request context is never authoritative. The Pipeline removes the
    reserved key from client context and may re-add only this normalized
    internal projection from a separate request field.
    """
    raw = value if isinstance(value, dict) else {}
    allowed_top_level = {
        "schema_version",
        "source",
        "owner",
        "provenance",
        "domain_policy_context",
        "conversation_reference_status",
        "conversation_goal_lifecycle",
    }
    if set(raw) - allowed_top_level:
        return {}
    provenance = raw.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if (
        raw.get("schema_version") != "answer-eligibility-owner-context/v1"
        or raw.get("source")
        not in {
            "server_configuration",
            "verified_server_mapping",
            "evaluation_fixture",
        }
        or raw.get("owner") != "analysis_pipeline"
        or provenance != {"boundary": "analysis_pipeline_internal"}
    ):
        return {}

    result: dict[str, Any] = {
        "schema_version": "answer-eligibility-owner-context/v1",
        "source": raw["source"],
        "owner": "analysis_pipeline",
        "provenance": {"boundary": "analysis_pipeline_internal"},
    }
    domain_context = raw.get("domain_policy_context")
    if "domain_policy_context" in raw:
        if not isinstance(domain_context, dict):
            return {}
        if domain_context.get("schema_version") == (
            "trusted-domain-policy-context/v1"
        ):
            required_domain_keys = {
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
            binding_summary = domain_context.get("binding_summary")
            validation_reasons = domain_context.get("validation_reasons")
            if (
                set(domain_context) != required_domain_keys
                or domain_context.get("status")
                not in {"selected", "missing", "invalid"}
                or domain_context.get("trusted_owner") != "analysis_pipeline"
                or domain_context.get("selection_source")
                not in {
                    "server_configuration",
                    "verified_server_mapping",
                    "evaluation_fixture",
                }
                or domain_context.get("selection_source") != raw.get("source")
                or not isinstance(binding_summary, dict)
                or set(binding_summary) != {"tenant", "store", "catalog"}
                or any(
                    not isinstance(item, bool)
                    for item in binding_summary.values()
                )
                or domain_context.get("provenance")
                != {
                    "boundary": "analysis_pipeline_internal",
                    "selector_owner": "file_policy_repository",
                }
                or domain_context.get("selected_at_stage")
                != "canonical_input"
                or not isinstance(validation_reasons, list)
                or validation_reasons != sorted(set(validation_reasons))
                or any(
                    not isinstance(reason, str) or not reason
                    for reason in validation_reasons
                )
                or domain_context.get("used_for_evidence") is not False
                or domain_context.get("used_for_fact_support") is not False
                or domain_context.get("can_change_can_send") is not False
                or (
                    bool(domain_context.get("domain_ref"))
                    and not re.fullmatch(
                        r"domain-[0-9a-f]{20}",
                        str(domain_context.get("domain_ref") or ""),
                    )
                )
            ):
                return {}
            if domain_context.get("status") == "selected":
                if (
                    not re.fullmatch(
                        r"domain-policy:[a-z0-9][a-z0-9_-]{0,63}"
                        r"@\d+\.\d+\.\d+",
                        str(domain_context.get("pack_ref") or ""),
                    )
                    or domain_context.get("pack_schema_version")
                    != "domain-policy-pack/v1"
                    or not re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(
                            domain_context.get(
                                "pack_content_sha256"
                            )
                            or ""
                        ),
                    )
                    or not re.fullmatch(
                        r"domain-[0-9a-f]{20}",
                        str(domain_context.get("domain_ref") or ""),
                    )
                    or validation_reasons
                    or not any(binding_summary.values())
                ):
                    return {}
            elif any(
                domain_context.get(key)
                for key in (
                    "pack_ref",
                    "pack_schema_version",
                    "pack_content_sha256",
                )
            ):
                return {}
            result["domain_policy_context"] = {
                key: (
                    dict(item)
                    if isinstance(item, dict)
                    else list(item)
                    if isinstance(item, list)
                    else item
                )
                for key, item in domain_context.items()
            }
        else:
            if not domain_context:
                result["domain_policy_context"] = {}
                domain_context = None
            if domain_context is None:
                pass
            else:
                allowed_domain_keys = {
                    "tenant_metadata",
                    "store_metadata",
                    "catalog_metadata",
                }
                if not set(domain_context) <= allowed_domain_keys:
                    return {}
                normalized_selector: dict[str, dict[str, str]] = {}
                for key, item in domain_context.items():
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"domain_policy_id"}
                        or not isinstance(item.get("domain_policy_id"), str)
                    ):
                        return {}
                    normalized_selector[key] = {
                        "domain_policy_id": item["domain_policy_id"]
                    }
                result["domain_policy_context"] = normalized_selector
    reference_status = raw.get("conversation_reference_status")
    if isinstance(reference_status, dict):
        allowed_reference_keys = {
            "status",
            "source_stage",
            "owner",
            "reason_codes",
        }
        if set(reference_status) <= allowed_reference_keys:
            result["conversation_reference_status"] = dict(reference_status)
    if "conversation_goal_lifecycle" in raw:
        lifecycle = normalize_trusted_conversation_goal_lifecycle_context(
            raw.get("conversation_goal_lifecycle")
        )
        if not lifecycle:
            return {}
        result["conversation_goal_lifecycle"] = lifecycle
    return result


def _formal_text(value: Any) -> str:
    """Normalize presentation noise without redacting operational content."""
    text = str(value or "")
    text = _CONTROL_CHARACTERS.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def _stable_turn_uid(role: str, content: str, turn_index: int, timestamp: str) -> str:
    payload = json.dumps(
        {"role": role, "content": content, "turn_index": turn_index, "timestamp": timestamp},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return "turn-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def canonical_current_customer_turn_uid(
    message: Any,
    *,
    conversation_history: Any = None,
) -> str:
    """Build the current buyer-turn UID from canonical content and position.

    Caller-supplied turn UIDs are deliberately ignored. The current message is
    not yet part of conversation history, so its canonical index follows the
    last normalized history turn.
    """
    content = _formal_text(message)
    if not content:
        return ""

    next_index = 0
    if isinstance(conversation_history, list):
        for position, item in enumerate(conversation_history):
            if not isinstance(item, dict):
                continue
            turn_index = item.get("turn_index")
            if not isinstance(turn_index, int) or isinstance(turn_index, bool):
                turn_index = position
            next_index = max(next_index, turn_index + 1)
    return _stable_turn_uid("customer", content, next_index, "")


def _diagnostics(*, status: str, reason: str = "", turn_count: int = 0, repairs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    repair_rows = repairs or []
    return {
        "schema_version": "canonical-conversation-turn-v2",
        "status": status,
        "reason": reason,
        "degraded_context": status == "degraded",
        "turn_count": turn_count,
        "repair_count": len(repair_rows),
        "repairs": repair_rows,
    }


def _strict_error(reason: str) -> None:
    raise ConversationContextContractError(reason)


def normalize_conversation_turns(
    value: Any,
    *,
    strict: bool = False,
    max_turns: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the canonical conversation contract without reordering turns.

    Strict evaluation inputs fail before graph execution. Online inputs preserve
    input order and make narrowly repaired indices explicit in diagnostics.
    Legacy fields are accepted only at this boundary; emitted turns contain
    ``content`` rather than ``text`` or ``message``.
    """
    if value in (None, []):
        return [], _diagnostics(status="valid")
    if not isinstance(value, list):
        if strict:
            _strict_error("conversation_history_expected_list")
        return [], _diagnostics(status="degraded", reason="conversation_history_legacy_nonlist")

    turns: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    previous_index: int | None = None
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            if strict:
                _strict_error("conversation_turn_expected_object")
            repairs.append({"position": position, "reason": "conversation_turn_expected_object"})
            continue

        role_value = _formal_text(item.get("role") or item.get("speaker_role") or item.get("speaker")).lower()
        role = _ROLE_ALIASES.get(role_value, "")
        if not role:
            if strict:
                _strict_error("conversation_turn_invalid_role")
            repairs.append({"position": position, "reason": "conversation_turn_invalid_role"})
            continue

        content = _formal_text(item.get("content") or item.get("text") or item.get("message"))
        if not content:
            if strict:
                _strict_error("conversation_turn_content_missing")
            repairs.append({"position": position, "reason": "conversation_turn_content_missing"})
            continue

        original_index = item.get("turn_index")
        if isinstance(original_index, int) and not isinstance(original_index, bool):
            turn_index = original_index
        else:
            if strict:
                _strict_error("conversation_turn_index_missing_or_invalid")
            turn_index = (previous_index + 1) if previous_index is not None else position
            repairs.append({
                "position": position,
                "reason": "conversation_turn_index_missing_or_invalid",
                "original_turn_index": original_index,
                "repaired_turn_index": turn_index,
            })

        if previous_index is not None and turn_index <= previous_index:
            if strict:
                _strict_error(
                    "conversation_turn_index_duplicate" if turn_index == previous_index
                    else "conversation_turn_index_out_of_order"
                )
            repaired_index = previous_index + 1
            repairs.append({
                "position": position,
                "reason": (
                    "conversation_turn_index_duplicate" if turn_index == previous_index
                    else "conversation_turn_index_out_of_order"
                ),
                "original_turn_index": turn_index,
                "repaired_turn_index": repaired_index,
            })
            turn_index = repaired_index

        timestamp = _formal_text(item.get("timestamp") or item.get("time"))
        turn = {
            "role": role,
            "content": content,
            "turn_index": turn_index,
            "turn_uid": _formal_text(item.get("turn_uid")) or _stable_turn_uid(role, content, turn_index, timestamp),
        }
        if timestamp:
            turn["timestamp"] = timestamp
        message_type = _formal_text(item.get("message_type"))
        if message_type:
            turn["message_type"] = message_type
        turns.append(turn)
        previous_index = turn_index

    if len(turns) > max_turns:
        removed = len(turns) - max_turns
        turns = turns[-max_turns:]
        repairs.append({"reason": "conversation_turn_limit_applied", "removed_turn_count": removed})
    if repairs:
        return turns, _diagnostics(status="degraded", reason=str(repairs[0]["reason"]), turn_count=len(turns), repairs=repairs)
    return turns, _diagnostics(status="valid", turn_count=len(turns))


def _stable_private_reference(kind: str, value: Any) -> str:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:12]
    return f"[{kind}_REDACTED:{digest}]"


def _project_labeled_identifier_references(text: str) -> str:
    """Remove labelled IDs without trying to repair malformed structured text."""
    def replace(match: re.Match[str]) -> str:
        label = match.group("label")
        value = match.group("value").strip().strip("\"'")
        normalized = label.lower().replace(" ", "").replace("_", "").replace("-", "")
        kind = "PRODUCT_ID" if any(token in normalized for token in ("sku", "iid", "product", "item")) else "REFERENCE"
        return f"{label}: {_stable_private_reference(kind, value)}"

    return _LABELED_IDENTIFIER_REFERENCE.sub(replace, text)


def project_text_for_external_model(value: Any) -> str:
    """Project free text with precise PII rules, never generic address matching.

    Product titles and admitted fact text may legitimately contain room words
    such as ``客厅`` or ``卧室``.  The projection therefore redacts only phone,
    labelled order/logistics identifiers, explicit address shapes, credentials,
    email, and long personal identifiers.
    """
    text = _formal_text(value)
    if not text:
        return ""
    text = _SECRET.sub(lambda match: f"{match.group(1)}=[SECRET_REDACTED]", text)
    text = _project_labeled_identifier_references(text)
    text = _PHONE.sub("[PHONE_REDACTED]", text)
    text = _EMAIL.sub("[EMAIL_REDACTED]", text)
    text = _ORDER_REFERENCE.sub("[ORDER_REFERENCE_REDACTED]", text)
    text = _TRACKING_REFERENCE.sub("[TRACKING_REFERENCE_REDACTED]", text)
    text = _ADDRESS.sub("[ADDRESS_REDACTED]", text)
    text = _LONG_ID.sub(lambda match: _stable_private_reference("LONG_ID", match.group(0)), text)
    # URLs can contain customer identifiers in a path or query. They are not
    # useful to the external reply model, while product titles remain intact.
    text = _URL.sub("[URL_REDACTED]", text)
    return text.strip()


def project_provider_message_text(value: Any) -> str:
    """Project mixed provider prompt text without requiring whole-message JSON.

    Valid JSON values embedded in prose or Markdown fences are projected by
    field name. Invalid JSON is deliberately not repaired; its raw text still
    receives the precise labelled-identifier and PII projection.
    """
    text = _formal_text(value)
    if not text:
        return ""
    decoder = json.JSONDecoder()
    result: list[str] = []
    cursor = 0
    probe = 0
    while probe < len(text):
        starts = [position for position in (text.find("{", probe), text.find("[", probe)) if position >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            parsed, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            probe = start + 1
            continue
        result.append(project_text_for_external_model(text[cursor:start]))
        result.append(json.dumps(project_value_for_external_model(parsed), ensure_ascii=False, separators=(",", ":")))
        cursor = end
        probe = end
    result.append(project_text_for_external_model(text[cursor:]))
    return "".join(result).strip()


def project_value_for_external_model(value: Any, *, field_name: str = "") -> Any:
    """Recursively project prompt data while withholding structured private IDs."""
    if isinstance(value, str):
        return project_text_for_external_model(value)
    if isinstance(value, list):
        return [project_value_for_external_model(item, field_name=field_name) for item in value]
    if isinstance(value, tuple):
        return [project_value_for_external_model(item, field_name=field_name) for item in value]
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_lower in _PRIVATE_IDENTIFIER_FIELDS:
                projected[key_text] = _stable_private_reference("STRUCTURED_PRIVATE_ID", item)
            elif key_lower in _PRODUCT_IDENTIFIER_FIELDS:
                projected[key_text] = _stable_private_reference("PRODUCT_ID", item)
            elif key_lower in {"token", "secret", "password", "api_key", "apikey", "signature"}:
                projected[key_text] = "[SECRET_REDACTED]"
            else:
                projected[key_text] = project_value_for_external_model(item, field_name=key_lower)
        return projected
    return value


def project_conversation_turns_for_external_model(
    turns: list[dict[str, Any]],
    *,
    max_turns: int = 12,
) -> list[dict[str, Any]]:
    """Return the privacy-safe view of canonical turns for an external model.

    The sanitizer is intentionally called here, not during formal canonical
    normalization. Structured order/product identities remain available to
    local tools and are never reconstructed from this projected text.
    """
    projected: list[dict[str, Any]] = []
    for position, item in enumerate((turns or [])[-max_turns:]):
        if not isinstance(item, dict):
            continue
        content = project_text_for_external_model(turn_content(item))
        if not content:
            continue
        projected.append({
            "role": _formal_text(item.get("role")).lower(),
            "content": content,
            "turn_index": position,
        })
    return projected


def turn_content(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return _formal_text(item.get("content") or item.get("text") or item.get("message"))
