"""Build one read-only, role-separated answer context from candidate evidence.

The service is deterministic. It does not retrieve, generate customer copy, write
knowledge, or change delivery decisions. Candidate presence is not admission.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


DIRECT_PRODUCT_ROLES = {"product_fact_direct", "faq_direct"}
DIRECT_POLICY_ROLES = {"policy_fact_direct"}
ACTION_ROLES = {"service_action", "fallback_only"}
MEDIA_ROLES = {"media_reference"}
REJECTED_FACT_ROLES = {
    "answer_memory",
    "correct_answer",
    "expected_reply",
    "media_reference",
    "rubric",
    "service_action",
    "fallback_only",
}
REVIEWED_STATUSES = {"reviewed", "verified", "published", "approved"}
ALLOWED_GATES = {"allowed", "approved", "passed"}
PLACEHOLDER_TERMS = (
    "待核实",
    "待确认",
    "需要核实",
    "需要确认",
    "人工确认",
    "未明确",
    "暂无明确",
    "以详情页为准",
    "以实物为准",
)

COMPATIBLE_FACT_TYPES = {
    "installation_media": {"installation", "installation_media", "installation_media_request"},
    "material_composition": {"material", "material_composition"},
    "material_safety": {"material", "material_composition", "material_safety", "odor", "certification_report"},
    "moisture_resistance": {"moisture_resistance"},
    "pinch_safety": {"pinch_safety", "structure_function", "structure", "material"},
    "child_safety": {"child_safety", "structure_function", "structure", "material"},
    "child_suitability": {"child_suitability", "structure_function", "structure", "material", "age_range"},
}

_IDENTITY_KEYS = ("sku_code", "i_id", "product_id")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def resolved_product_identity_for_response(
    response: dict[str, Any],
    provided: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return explicit identity fields without translating between namespaces."""
    debug = _as_dict(response.get("evidence_debug"))
    context = _as_dict(response.get("context_used"))
    packs = [
        _as_dict(response.get("product_context_pack")),
        _as_dict(context.get("product_context_pack")),
        _as_dict(debug.get("product_context_pack_summary")),
    ]
    sources = [
        _as_dict(provided),
        _as_dict(debug.get("order_product_identity")),
    ]
    for pack in packs:
        sources.append(_as_dict(_as_dict(pack.get("evidence_pack")).get("identity")))
        sources.append(_as_dict(pack.get("identity")))

    result: dict[str, Any] = {}
    aliases = {
        "sku_code": ("sku_code", "sku"),
        "i_id": ("i_id",),
        "product_id": ("product_id",),
        "product_name": ("product_name", "product_title", "matched_product_name"),
    }
    for canonical, keys in aliases.items():
        for source in sources:
            value = next((sanitize_text(source.get(key)) for key in keys if sanitize_text(source.get(key))), "")
            if value:
                result[canonical] = value
                break
    return sanitize_obj(result)


def _clip(value: Any, limit: int = 220) -> str:
    text = sanitize_text(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = sanitize_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _fact_type(item: dict[str, Any]) -> str:
    for key in ("fact_type", "query_fact_type", "requested_fact_type"):
        value = sanitize_text(item.get(key)).lower()
        if value:
            return value
    return ""


def _role(item: dict[str, Any]) -> str:
    return sanitize_text(item.get("evidence_role") or item.get("role")).lower()


def _source_type(item: dict[str, Any]) -> str:
    return sanitize_text(item.get("source_type") or item.get("type")).lower()


def _text(item: dict[str, Any]) -> str:
    for key in ("content", "answer", "value", "fact_value", "text", "preview", "summary", "title"):
        value = sanitize_text(item.get(key))
        if value:
            return value
    return ""


def _attribute_key(item: dict[str, Any]) -> str:
    return sanitize_text(
        item.get("attribute_key")
        or item.get("field_name")
        or item.get("fact_key")
        or item.get("structured_field")
    ).lower()


def _identity_scope(item: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"namespace": key, "value": value}
        for key in _IDENTITY_KEYS
        if (value := sanitize_text(item.get(key)))
    ]


def _evidence_uid(source: str, item: dict[str, Any], text: str) -> str:
    explicit = sanitize_text(item.get("evidence_uid") or item.get("chunk_id") or item.get("source_chunk_id"))
    if explicit:
        return explicit
    seed = "|".join(
        [source, _source_type(item), _role(item), _fact_type(item), _attribute_key(item), text]
        + [f"{scope['namespace']}={scope['value']}" for scope in _identity_scope(item)]
    )
    return f"ev-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _provenance(source: str, item: dict[str, Any], text: str) -> dict[str, Any]:
    scopes = _identity_scope(item)
    legacy_source = "selected_evidence" if source.endswith("selected_evidence") else source
    primary_scope = scopes[0] if scopes else {"namespace": "", "value": ""}
    return {
        "evidence_uid": _evidence_uid(source, item, text),
        "source_type": _source_type(item),
        "source_id": sanitize_text(item.get("source_id") or item.get("entry_id") or item.get("id")),
        "source_container": source,
        "source": legacy_source,
        "evidence_role": _role(item),
        "role": _role(item),
        "product_identity_scope": scopes,
        "identity_scopes": scopes,
        "identity_namespace": primary_scope["namespace"],
        "identity_value": primary_scope["value"],
    }


def _identity_reason(item: dict[str, Any], product_identity: dict[str, Any], *, allow_global: bool) -> str:
    scope = sanitize_text(item.get("fact_scope") or item.get("product_scope")).lower()
    if allow_global and scope in {"global", "all"}:
        return ""
    expected = {key: sanitize_text(product_identity.get(key)) for key in _IDENTITY_KEYS if sanitize_text(product_identity.get(key))}
    actual = {key: sanitize_text(item.get(key)) for key in _IDENTITY_KEYS if sanitize_text(item.get(key))}
    if not actual:
        return "product_identity_missing"
    if not expected:
        return "resolved_product_identity_missing"
    common = set(expected).intersection(actual)
    if not common:
        return "product_identity_namespace_missing"
    if any(expected[key] != actual[key] for key in common):
        return "product_identity_mismatch"
    return ""


def _claim_types(item: dict[str, Any]) -> list[str]:
    declared = item.get("claim_types_supported") or item.get("supported_claim_types") or []
    values = _unique(declared if isinstance(declared, list) else [declared])
    fact_type = _fact_type(item)
    if fact_type and fact_type not in values:
        values.append(fact_type)
    if fact_type == "material" and "material_composition" not in values:
        values.append("material_composition")
    return values


def _admission_reason(
    item: dict[str, Any],
    *,
    product_identity: dict[str, Any],
    requested_claim_types: list[str],
    policy: bool = False,
) -> str:
    role = _role(item)
    gate = sanitize_text(item.get("gate_status")).lower()
    status = sanitize_text(
        item.get("fact_review_status") or item.get("review_status") or item.get("verification_status")
    ).lower()
    text = _text(item)
    if item.get("reference_only") is True or item.get("fallback_only") is True:
        return "reference_only"
    if role in REJECTED_FACT_ROLES or _source_type(item) in REJECTED_FACT_ROLES:
        return "ineligible_role_or_gate"
    if gate in {"blocked", "reference_only", "rejected"}:
        return "gate_not_allowed"
    if item.get("direct_answer_allowed") is not True and item.get("can_direct_answer") is not True:
        return "not_direct_answerable"
    expected_roles = DIRECT_POLICY_ROLES if policy else DIRECT_PRODUCT_ROLES
    if role not in expected_roles:
        return "evidence_role_not_direct"
    if gate and gate not in ALLOWED_GATES:
        return "gate_not_allowed"
    if status not in REVIEWED_STATUSES:
        return "review_status_missing"
    if not text:
        return "fact_text_missing"
    if any(term in text for term in PLACEHOLDER_TERMS):
        return "placeholder_evidence"
    if not policy:
        identity_reason = _identity_reason(item, product_identity, allow_global=role == "faq_direct")
        if identity_reason:
            return identity_reason
    if requested_claim_types:
        supported = set(_claim_types(item))
        compatible = set().union(*(COMPATIBLE_FACT_TYPES.get(claim, {claim}) for claim in requested_claim_types))
        if supported.isdisjoint(compatible):
            return "fact_type_incompatible"
    return ""


def _normalized_quantity(item: dict[str, Any], text: str) -> tuple[str, str, str]:
    value = sanitize_text(item.get("value") or item.get("fact_value") or text).lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|公斤|千克|g|克|斤|mm|毫米|cm|厘米|m|米)?", value)
    if not match:
        fact_type = _fact_type(item)
        explicit_value = sanitize_text(item.get("value") or item.get("fact_value")).lower()
        if explicit_value and fact_type in {"material", "material_composition", "color", "colour"}:
            canonical = re.sub(r"\s+", "", explicit_value)
            return value, "structured_text", f"text:{canonical}"
        return value, "", ""
    try:
        amount = Decimal(match.group(1))
    except InvalidOperation:
        return value, "", ""
    unit = match.group(2) or ""
    if unit in {"kg", "公斤", "千克"}:
        return value, "mass_metric", f"mass_g:{(amount * Decimal(1000)).normalize()}"
    if unit in {"g", "克"}:
        return value, "mass_metric", f"mass_g:{amount.normalize()}"
    if unit == "斤":
        return value, "mass_jin", f"jin:{amount.normalize()}"
    if unit in {"m", "米"}:
        return value, "length_metric", f"length_mm:{(amount * Decimal(1000)).normalize()}"
    if unit in {"cm", "厘米"}:
        return value, "length_metric", f"length_mm:{(amount * Decimal(10)).normalize()}"
    if unit in {"mm", "毫米"}:
        return value, "length_metric", f"length_mm:{amount.normalize()}"
    return value, "", ""


def _candidate_containers(response: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    debug = _as_dict(response.get("evidence_debug"))
    context = _as_dict(response.get("context_used"))
    pack = (
        _as_dict(response.get("product_context_pack"))
        or _as_dict(context.get("product_context_pack"))
        or _as_dict(debug.get("product_context_pack_summary"))
    )
    candidates: list[tuple[str, dict[str, Any]]] = []
    shadow_tool_results = _as_dict(debug.get("llm_decision_shadow_tool_results"))
    rag_result = _as_dict(shadow_tool_results.get("rag_search_tool"))
    for item in _as_list(rag_result.get("chunks")):
        if isinstance(item, dict):
            candidates.append(("llm_decision_shadow_tool_results.rag_search_tool", item))
    for source, values in (
        ("response.selected_evidence", response.get("selected_evidence")),
        ("evidence_debug.selected_evidence", debug.get("selected_evidence")),
    ):
        for item in _as_list(values):
            if isinstance(item, dict):
                candidates.append((source, item))
    for bucket in ("facts", "chunks", "product_scoped_chunks", "matched_facts", "generic_rules", "media_assets", "recommended_assets"):
        for item in _as_list(pack.get(bucket)):
            if isinstance(item, dict):
                candidates.append((f"product_context_pack.{bucket}", item))
    for pack_key in ("product_first_evidence_pack", "evidence_pack"):
        nested = _as_dict(pack.get(pack_key))
        for bucket in (
            "product_structured_facts",
            "product_scoped_chunks",
            "matched_facts",
            "generic_rules",
            "product_media_assets",
            "media_candidates",
        ):
            for item in _as_list(nested.get(bucket)):
                if isinstance(item, dict):
                    candidates.append((f"product_context_pack.{pack_key}.{bucket}", item))
    for item in _as_list(response.get("recommended_assets")):
        if isinstance(item, dict):
            candidates.append(("response.recommended_assets", item))
    return candidates


def collect_admitted_product_facts(
    response: dict[str, Any],
    *,
    product_identity: dict[str, Any],
    requested_claim_types: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return direct product facts, rejected evidence, and non-blocking warnings."""
    claims = _unique(requested_claim_types or [])
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_inputs: set[str] = set()

    for source, item in _candidate_containers(response):
        text = _text(item)
        provenance = _provenance(source, item, text)
        dedupe_key = provenance["evidence_uid"]
        if dedupe_key in seen_inputs:
            continue
        seen_inputs.add(dedupe_key)
        reason = _admission_reason(
            item,
            product_identity=product_identity,
            requested_claim_types=claims,
        )
        if reason:
            if _role(item) in DIRECT_PRODUCT_ROLES or source.endswith("selected_evidence") or source.endswith("matched_facts"):
                rejected.append({**provenance, "fact_type": _fact_type(item), "reason": reason})
            continue
        original_value, unit_domain, normalized_value = _normalized_quantity(item, text)
        candidates.append({
            **provenance,
            "review_status": sanitize_text(
                item.get("fact_review_status") or item.get("review_status") or item.get("verification_status")
            ).lower(),
            "direct_answer_allowed": True,
            "claim_types_supported": _claim_types(item),
            "fact_type": _fact_type(item),
            "attribute_key": _attribute_key(item),
            "fact_scope": sanitize_text(item.get("fact_scope") or item.get("product_scope")).lower(),
            "text": _clip(text),
            "value": _clip(item.get("value") or item.get("fact_value") or text),
            "original_value": original_value,
            "unit_domain": unit_domain,
            "normalized_value": normalized_value,
            "conflict_status": "clear",
        })

    admitted: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        slot = sanitize_text(candidate.get("attribute_key"))
        if not slot:
            admitted.append(candidate)
            warnings.append({**candidate, "reason": "conflict_check_skipped"})
        else:
            grouped.setdefault(slot, []).append(candidate)

    for slot in sorted(grouped):
        group = sorted(grouped[slot], key=lambda item: (sanitize_text(item.get("unit_domain")), sanitize_text(item.get("normalized_value")), sanitize_text(item.get("evidence_uid"))))
        comparable = [item for item in group if sanitize_text(item.get("normalized_value"))]
        incomparable = [item for item in group if not sanitize_text(item.get("normalized_value"))]
        admitted.extend(incomparable)
        warnings.extend({**item, "reason": "conflict_check_skipped"} for item in incomparable)
        if not comparable:
            continue
        if len({sanitize_text(item.get("unit_domain")) for item in comparable}) > 1:
            rejected.extend({**item, "reason": "incomparable_unit_domain", "conflict_status": "blocked"} for item in comparable)
            continue
        if len({sanitize_text(item.get("normalized_value")) for item in comparable}) > 1:
            rejected.extend({**item, "reason": "conflicting_evidence", "conflict_status": "blocked"} for item in comparable)
            continue
        admitted.append(comparable[0])
        rejected.extend({**item, "reason": "duplicate_evidence"} for item in comparable[1:])
    return admitted[:12], rejected, warnings


def _requested_claims(understanding: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(understanding.get("requested_claims")):
        if isinstance(item, dict):
            claim_type = sanitize_text(item.get("claim_type")).lower()
            if claim_type:
                result.append({
                    "claim_type": claim_type,
                    "question": _clip(item.get("question"), 160),
                    "risk_level": sanitize_text(item.get("risk_level")).lower() or "medium",
                })
        elif sanitize_text(item):
            result.append({"claim_type": sanitize_text(item).lower(), "question": "", "risk_level": "medium"})
    return result


class AdmittedAnswerContextService:
    """Compile candidate evidence into auditable answer-context roles."""

    def build_for_response(
        self,
        response: dict[str, Any],
        *,
        product_identity: dict[str, Any] | None = None,
        understanding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity = resolved_product_identity_for_response(response, product_identity)
        requested_claims = _requested_claims(_as_dict(understanding))
        requested_claim_types = [item["claim_type"] for item in requested_claims]
        direct_product, rejected, warnings = collect_admitted_product_facts(
            response,
            product_identity=identity,
            requested_claim_types=requested_claim_types,
        )

        direct_policy: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        media: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for source, item in _candidate_containers(response):
            text = _text(item)
            provenance = _provenance(source, item, text)
            key = (provenance["evidence_uid"], source)
            if key in seen:
                continue
            seen.add(key)
            role = _role(item)
            source_type = _source_type(item)
            if role in DIRECT_POLICY_ROLES:
                reason = _admission_reason(
                    item,
                    product_identity=identity,
                    requested_claim_types=requested_claim_types,
                    policy=True,
                )
                if reason:
                    rejected.append({**provenance, "fact_type": _fact_type(item), "reason": reason})
                else:
                    direct_policy.append({**provenance, "claim_types_supported": _claim_types(item), "text": _clip(text), "direct_answer_allowed": True})
            elif role in ACTION_ROLES or source_type in {"generic_rule", "generic_rules", "response_template", "response_templates"}:
                actions.append({**provenance, "text": _clip(text), "reference_only": True})
            elif role in MEDIA_ROLES or item.get("asset_type") or item.get("asset_url") or item.get("url"):
                media.append({
                    **provenance,
                    "asset_type": sanitize_text(item.get("asset_type")),
                    "media_role": sanitize_text(item.get("media_role")),
                    "reference_only": True,
                    "attached_reply_block": False,
                })

        supported_claims = {
            claim
            for fact in [*direct_product, *direct_policy]
            for claim in _as_list(fact.get("claim_types_supported"))
        }
        unresolved = [
            {**claim, "reason": "no_admitted_direct_evidence"}
            for claim in requested_claims
            if claim["claim_type"] not in supported_claims
        ]
        conflicts = [item for item in rejected if item.get("reason") in {"conflicting_evidence", "incomparable_unit_domain"}]
        return sanitize_obj({
            "schema_version": "admitted-answer-context-v1",
            "direct_product_facts": direct_product,
            "direct_policy_facts": direct_policy,
            "handoff_action_guidance": actions[:12],
            "media_candidates": media[:12],
            "rejected_evidence": rejected[:40],
            "admission_warnings": warnings[:20],
            "unresolved_claims": unresolved,
            "conflicts": conflicts,
            "requested_claims": requested_claims,
            "product_identity": identity,
            "read_only": True,
            "used_for_final_reply": False,
            "can_change_can_send": False,
        })
