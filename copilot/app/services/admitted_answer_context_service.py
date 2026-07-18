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
from app.services.claim_resolution_service import build_claim_resolutions, expand_claim_dependencies
from app.services.fact_type_alias_service import normalize_high_risk_claim_type
from app.services.product_structured_evidence_service import material_evidence_admission_reason


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
    "需要人工核实",
    "人工确认",
    "未明确",
    "暂无明确",
    "暂未明确",
    "以详情页为准",
    "以实物为准",
)
# Variants where characters may intervene between the negation and the claim
# (e.g. "未在现有结构资料中明确尺寸").
_PLACEHOLDER_PATTERNS = (
    re.compile(r"未.{0,24}明确"),
)

COMPATIBLE_FACT_TYPES = {
    "installation_media": {"installation", "installation_media", "installation_media_request"},
    "material_composition": {"material", "material_composition"},
    # High-risk claims require evidence explicitly reviewed for that claim.
    # A composition fact can answer "what is it made of", but cannot establish
    # non-toxicity, certification, child safety, or another safety conclusion.
    "material_safety": {"material_safety"},
    "moisture_resistance": {"moisture_resistance"},
    "pinch_safety": {"pinch_safety"},
    "child_safety": {"child_safety"},
    "child_suitability": {"child_suitability"},
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


def is_placeholder_evidence_text(value: Any) -> bool:
    """Return whether text is a verification placeholder rather than a fact."""
    text = sanitize_text(value)
    return bool(text) and (
        any(term in text for term in PLACEHOLDER_TERMS)
        or any(pattern.search(text) for pattern in _PLACEHOLDER_PATTERNS)
    )


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


def _scope_values(item: dict[str, Any], field: str) -> set[str]:
    value = item.get(field)
    if not isinstance(value, list):
        return set()
    return {sanitize_text(item_value) for item_value in value if sanitize_text(item_value)}


def _normalise_product_context_candidate(
    source: str,
    item: dict[str, Any],
    product_identity: dict[str, Any],
) -> dict[str, Any]:
    """Promote only explicit structured-profile protocol metadata to its direct role.

    Product Context Pack already creates these candidates from a reviewed
    ``KBProduct`` field.  This adapter preserves that existing eligibility for
    the shadow admission contract; it does not derive new facts or relax any
    review, gate, or identity requirement for arbitrary retrieved chunks.
    """
    metadata = _as_dict(item.get("metadata"))
    if not (
        source.startswith("product_context_pack.")
        and metadata.get("product_evidence_protocol") is True
        and sanitize_text(metadata.get("verification_status")).lower() in REVIEWED_STATUSES
        and metadata.get("can_direct_answer") is True
    ):
        return item

    normalised = dict(item)
    normalised.update({
        "evidence_role": "product_fact_direct",
        "fact_review_status": sanitize_text(metadata.get("verification_status")),
        "gate_status": "allowed",
        "direct_answer_allowed": True,
    })
    if not sanitize_text(normalised.get("content")):
        normalised["content"] = sanitize_text(item.get("customer_text") or item.get("chunk_text"))
    expected_sku = sanitize_text(product_identity.get("sku_code"))
    expected_i_id = sanitize_text(product_identity.get("i_id"))
    if expected_sku and expected_sku in _scope_values(item, "sku_scope"):
        normalised["sku_code"] = expected_sku
    if expected_i_id and expected_i_id in _scope_values(item, "product_scope"):
        normalised["i_id"] = expected_i_id
    return normalised


def _normalise_formal_evidence_candidate(
    item: dict[str, Any],
    product_identity: dict[str, Any],
) -> dict[str, Any]:
    """Adapt an already-gated retrieval candidate to the shared admission contract.

    The upstream evidence filter remains the owner of retrieval/gate decisions.
    This adapter only gives an explicitly direct, reviewed candidate the role and
    text fields required by :func:`_admission_reason`; all identity, claim-type,
    placeholder, and conflict checks still run below.
    """
    source_type = _source_type(item)
    if source_type not in {"product_facts", "faq", "installation_guide", "policy", "policy_facts"}:
        return item

    normalised = dict(item)
    if source_type in {"policy", "policy_facts"}:
        normalised["evidence_role"] = "policy_fact_direct"
    elif source_type == "faq":
        normalised["evidence_role"] = "faq_direct"
    else:
        normalised["evidence_role"] = "product_fact_direct"
    if not sanitize_text(normalised.get("content")):
        normalised["content"] = sanitize_text(
            item.get("fact") or item.get("chunk_text") or item.get("customer_text")
        )
    if not sanitize_text(normalised.get("fact_review_status")):
        normalised["fact_review_status"] = sanitize_text(
            item.get("review_status") or item.get("verification_status") or item.get("entry_status")
        )
    if (
        item.get("direct_answer_allowed") is True
        or item.get("evidence_allowed_for_direct_answer") is True
    ):
        normalised["direct_answer_allowed"] = True
    expected_sku = sanitize_text(product_identity.get("sku_code"))
    expected_i_id = sanitize_text(product_identity.get("i_id"))
    if not sanitize_text(normalised.get("sku_code")) and expected_sku and expected_sku in _scope_values(item, "sku_scope"):
        normalised["sku_code"] = expected_sku
    if not sanitize_text(normalised.get("i_id")) and expected_i_id and expected_i_id in _scope_values(item, "product_scope"):
        normalised["i_id"] = expected_i_id
    return normalised


def _evidence_uid(source: str, item: dict[str, Any], text: str) -> str:
    explicit = sanitize_text(item.get("evidence_uid") or item.get("chunk_id") or item.get("source_chunk_id"))
    if explicit:
        return explicit
    seed = "|".join(
        [source, _source_type(item), _role(item), _fact_type(item), _attribute_key(item), text]
        + [f"{scope['namespace']}={scope['value']}" for scope in _identity_scope(item)]
    )
    return f"ev-{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def _origin_evidence_key(item: dict[str, Any], text: str) -> str:
    explicit_origin = sanitize_text(item.get("origin_evidence_key"))
    if explicit_origin:
        return explicit_origin
    for field in ("evidence_uid", "evidence_id", "chunk_id", "entry_id", "source_id", "asset_id", "id"):
        value = sanitize_text(item.get(field))
        if value:
            return f"{sanitize_text(item.get('source_table') or item.get('source_type'))}:{value}"
    seed = "|".join((_source_type(item), _fact_type(item), _attribute_key(item), text))
    return f"derived:{sha256(seed.encode('utf-8')).hexdigest()[:16]}"


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
        "origin_evidence_key": _origin_evidence_key(item, text),
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
    if not expected:
        return "resolved_product_identity_missing"
    actual = {key: sanitize_text(item.get(key)) for key in _IDENTITY_KEYS if sanitize_text(item.get(key))}
    common = set(expected).intersection(actual)
    if common:
        return "product_identity_mismatch" if any(expected[key] != actual[key] for key in common) else ""

    scoped_matches = False
    scoped_mismatches = False
    scope_fields = {
        "sku_code": "sku_scope",
        "i_id": "product_scope",
        "product_id": "product_scope",
    }
    for namespace, scope_field in scope_fields.items():
        expected_value = expected.get(namespace)
        values = _scope_values(item, scope_field)
        if not expected_value or not values:
            continue
        if expected_value in values:
            scoped_matches = True
        else:
            scoped_mismatches = True
    if scoped_matches:
        return ""
    if scoped_mismatches:
        return "product_identity_mismatch"
    if not actual:
        return "product_identity_missing"
    return "product_identity_namespace_missing"


def _claim_types(item: dict[str, Any]) -> list[str]:
    declared = item.get("claim_types_supported") or item.get("supported_claim_types") or []
    values = [
        normalize_high_risk_claim_type(value) or value
        for value in _unique(declared if isinstance(declared, list) else [declared])
    ]
    fact_type = _fact_type(item)
    fact_type = normalize_high_risk_claim_type(fact_type) or fact_type
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
    if is_placeholder_evidence_text(text):
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
    material_reason = material_evidence_admission_reason(item)
    if material_reason:
        return material_reason
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
        ("response.formal_evidence_candidates", response.get("formal_evidence_candidates")),
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

    prepared_candidates: list[tuple[str, dict[str, Any]]] = []
    for source, raw_item in _candidate_containers(response):
        item = _normalise_product_context_candidate(source, raw_item, product_identity)
        if source == "response.formal_evidence_candidates":
            item = _normalise_formal_evidence_candidate(item, product_identity)
        prepared_candidates.append((source, item))

    for source, item in sorted(
        prepared_candidates,
        key=lambda pair: (
            _evidence_uid(pair[0], pair[1], _text(pair[1])),
            0 if _role(pair[1]) in DIRECT_PRODUCT_ROLES else 1,
            _source_type(pair[1]),
            pair[0],
        ),
    ):
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
            conflict_reason = "material_conflicting_evidence" if all(
                sanitize_text(item.get("fact_type")) in {"material", "material_composition"}
                for item in comparable
            ) else "conflicting_evidence"
            rejected.extend({**item, "reason": conflict_reason, "conflict_status": "blocked"} for item in comparable)
            continue
        admitted.append(comparable[0])
        rejected.extend({**item, "reason": "duplicate_evidence"} for item in comparable[1:])
    return admitted[:12], rejected, warnings


def build_evidence_convergence_trace(
    response: dict[str, Any],
    *,
    product_identity: dict[str, Any],
    admitted_context: dict[str, Any],
) -> dict[str, Any]:
    """Explain where candidate evidence is available, selected, or excluded.

    This is a read-only shadow diagnostic. It reuses the same normalization and
    admission helpers as the answer context, so it cannot report a different
    eligibility decision from the context a future decision model would see.
    """
    admitted_uids = {
        sanitize_text(item.get("evidence_uid"))
        for item in [
            *(admitted_context.get("direct_product_facts") or []),
            *(admitted_context.get("direct_policy_facts") or []),
        ]
        if sanitize_text(item.get("evidence_uid"))
    }
    rejected_by_uid = {
        sanitize_text(item.get("evidence_uid")): sanitize_text(item.get("reason"))
        for item in admitted_context.get("rejected_evidence") or []
        if sanitize_text(item.get("evidence_uid"))
    }
    records: dict[str, dict[str, Any]] = {}
    for source, raw_item in _candidate_containers(response):
        item = _normalise_product_context_candidate(source, raw_item, product_identity)
        if source == "response.formal_evidence_candidates":
            item = _normalise_formal_evidence_candidate(item, product_identity)
        text = _text(item)
        provenance = _provenance(source, item, text)
        key = provenance["origin_evidence_key"]
        record = records.setdefault(key, {
            "origin_evidence_key": key,
            "evidence_uids": [],
            "source_containers": [],
            "fact_type": _fact_type(item),
            "attribute_key": _attribute_key(item),
            "evidence_role": _role(item),
            "product_identity_scope": provenance["product_identity_scope"],
            "context_pack_candidate": False,
            "formal_selected": False,
            "shadow_admission": "not_evaluated",
            "shadow_reason": "",
            "llm_context": False,
        })
        if provenance["evidence_uid"] not in record["evidence_uids"]:
            record["evidence_uids"].append(provenance["evidence_uid"])
        if source not in record["source_containers"]:
            record["source_containers"].append(source)
        record["context_pack_candidate"] = record["context_pack_candidate"] or source.startswith("product_context_pack.")
        record["formal_selected"] = record["formal_selected"] or source.endswith("selected_evidence")
        uid = provenance["evidence_uid"]
        if uid in admitted_uids:
            record["shadow_admission"] = "admitted"
            record["shadow_reason"] = ""
            record["llm_context"] = True
        elif uid in rejected_by_uid:
            record["shadow_admission"] = "rejected"
            record["shadow_reason"] = rejected_by_uid[uid]
        elif record["shadow_admission"] == "not_evaluated":
            record["shadow_admission"] = "not_direct_candidate"
            record["shadow_reason"] = _admission_reason(
                item,
                product_identity=product_identity,
                requested_claim_types=[],
            ) or "not_direct_candidate"

    rows = sorted(records.values(), key=lambda row: (row["origin_evidence_key"], row["evidence_uids"]))
    rejected_reasons: dict[str, int] = {}
    for row in rows:
        if row["shadow_admission"] == "rejected":
            reason = row["shadow_reason"] or "unknown"
            rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
    return sanitize_obj({
        "schema_version": "evidence-convergence-trace-v1",
        "records": rows[:80],
        "summary": {
            "record_count": len(rows),
            "context_pack_candidate_count": sum(1 for row in rows if row["context_pack_candidate"]),
            "formal_selected_count": sum(1 for row in rows if row["formal_selected"]),
            "shadow_admitted_count": sum(1 for row in rows if row["shadow_admission"] == "admitted"),
            "llm_context_count": sum(1 for row in rows if row["llm_context"]),
            "context_pack_not_formal_selected_count": sum(
                1 for row in rows if row["context_pack_candidate"] and not row["formal_selected"]
            ),
            "rejected_by_reason": rejected_reasons,
        },
        "read_only": True,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    })


def _requested_claims(understanding: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(understanding.get("requested_claims")):
        if isinstance(item, dict):
            raw_claim_type = sanitize_text(item.get("claim_type")).lower()
            claim_type = normalize_high_risk_claim_type(raw_claim_type) or raw_claim_type
            if claim_type:
                result.append({
                    "claim_type": claim_type,
                    "attribute_key": sanitize_text(item.get("attribute_key")).lower(),
                    "question": _clip(item.get("question"), 160),
                    "risk_level": sanitize_text(item.get("risk_level")).lower() or "medium",
                    "direct_handling_prohibited": item.get("direct_handling_prohibited") is True,
                    "prohibited": item.get("prohibited") is True,
                    "prohibition_reason": sanitize_text(item.get("prohibition_reason")),
                })
        elif sanitize_text(item):
            raw_claim_type = sanitize_text(item).lower()
            result.append({
                "claim_type": normalize_high_risk_claim_type(raw_claim_type) or raw_claim_type,
                "question": "",
                "risk_level": "medium",
            })
    return expand_claim_dependencies(result)


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
        for source, raw_item in _candidate_containers(response):
            item = _normalise_product_context_candidate(source, raw_item, identity)
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

        conflicts = [item for item in rejected if item.get("reason") in {
            "conflicting_evidence", "material_conflicting_evidence", "incomparable_unit_domain",
        }]
        claim_resolutions = build_claim_resolutions(
            requested_claims,
            direct_product_facts=direct_product,
            direct_policy_facts=direct_policy,
            conflicts=conflicts,
        )
        requested_by_claim = {
            sanitize_text(item.get("claim_type")): item
            for item in requested_claims
            if sanitize_text(item.get("claim_type"))
        }
        unresolved = [
            {
                **requested_by_claim.get(sanitize_text(resolution.get("claim_type")), {}),
                "claim_uid": sanitize_text(resolution.get("claim_uid")),
                "reason": resolution["reason"],
                "status": resolution["status"],
                "evidence_uids": list(resolution.get("evidence_uids") or []),
                "conflicting_evidence_uids": list(resolution.get("conflicting_evidence_uids") or []),
            }
            for resolution in claim_resolutions
            if resolution["status"] != "supported"
        ]
        conflicting_claims = [item for item in unresolved if item.get("status") == "conflicting"]
        context = {
            "schema_version": "admitted-answer-context-v1",
            "direct_product_facts": direct_product,
            "direct_policy_facts": direct_policy,
            "handoff_action_guidance": actions[:12],
            "media_candidates": media[:12],
            "rejected_evidence": rejected[:40],
            "admission_warnings": warnings[:20],
            "claim_resolutions": claim_resolutions,
            "unresolved_claims": unresolved,
            "conflicting_claims": conflicting_claims,
            "conflicts": conflicts,
            "requested_claims": requested_claims,
            "product_identity": identity,
            "read_only": True,
            "used_for_final_reply": False,
            "can_change_can_send": False,
        }
        context["evidence_convergence"] = build_evidence_convergence_trace(
            response,
            product_identity=identity,
            admitted_context=context,
        )
        return sanitize_obj(context)


def canonical_selected_evidence(admitted_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the deterministic, direct-evidence-only formal selection.

    This is intentionally derived from the shared admitted context rather than
    from a second set of eligibility rules.  Service actions and media remain in
    their own non-factual context roles.
    """
    records: list[dict[str, Any]] = []
    for item in [
        *(_as_list(admitted_context.get("direct_product_facts"))),
        *(_as_list(admitted_context.get("direct_policy_facts"))),
    ]:
        if not isinstance(item, dict):
            continue
        uid = sanitize_text(item.get("evidence_uid"))
        if not uid:
            continue
        records.append({
            "evidence_uid": uid,
            "source": sanitize_text(item.get("source")),
            "source_type": sanitize_text(item.get("source_type")),
            "evidence_role": sanitize_text(item.get("evidence_role")),
            "review_status": sanitize_text(item.get("review_status")),
            "fact_review_status": sanitize_text(item.get("review_status")),
            "gate_status": "allowed",
            "direct_answer_allowed": True,
            "product_identity_scope": _as_list(item.get("product_identity_scope")),
            "identity_scopes": _as_list(item.get("identity_scopes")),
            "fact_type": sanitize_text(item.get("fact_type")),
            "attribute_key": sanitize_text(item.get("attribute_key")),
            "content": sanitize_text(item.get("text")),
            "value": sanitize_text(item.get("value")),
            "original_value": sanitize_text(item.get("original_value")),
            "provenance": {
                "origin_evidence_key": sanitize_text(item.get("origin_evidence_key")),
                "source_container": sanitize_text(item.get("source_container")),
            },
        })
    deduplicated: dict[str, dict[str, Any]] = {}
    for record in sorted(
        records,
        key=lambda item: (
            sanitize_text(item.get("evidence_uid")),
            sanitize_text(item.get("source_type")),
            sanitize_text(item.get("content")),
        ),
    ):
        origin_key = sanitize_text((record.get("provenance") or {}).get("origin_evidence_key"))
        deduplicated.setdefault(origin_key or record["evidence_uid"], record)
    return sanitize_obj(sorted(
        deduplicated.values(),
        key=lambda item: (
            sanitize_text(item.get("fact_type")),
            sanitize_text(item.get("attribute_key")),
            sanitize_text(item.get("evidence_uid")),
        ),
    ))


def build_minimal_decision_context(
    admitted_context: dict[str, Any],
    *,
    customer_message: str,
    conversation_summary: dict[str, Any] | None = None,
    channel_capabilities: dict[str, Any] | None = None,
    allowed_read_only_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Build bounded, non-reasoning context for a strict decision provider."""
    selected = canonical_selected_evidence(admitted_context)
    trim_reasons: list[str] = []
    if len(selected) > 6:
        trim_reasons.append("admitted_evidence_limit")
        selected = selected[:6]
    actions = [
        {"evidence_uid": sanitize_text(item.get("evidence_uid")), "text": _clip(item.get("text")), "non_fact": True}
        for item in _as_list(admitted_context.get("handoff_action_guidance"))[:4]
        if isinstance(item, dict)
    ]
    media = [
        {
            "evidence_uid": sanitize_text(item.get("evidence_uid")),
            "asset_type": sanitize_text(item.get("asset_type")),
            "media_role": sanitize_text(item.get("media_role")),
            "non_fact": True,
        }
        for item in _as_list(admitted_context.get("media_candidates"))[:4]
        if isinstance(item, dict)
    ]
    sources: dict[str, int] = {}
    for item in selected:
        source = sanitize_text(item.get("source_type")) or "unknown"
        sources[source] = sources.get(source, 0) + 1
    summary = _as_dict(conversation_summary)
    compact_summary = {
        key: _clip(value, 180)
        for key, value in summary.items()
        if key in {"summary", "current_turn", "customer_concern", "unresolved_slots"}
        and sanitize_text(value)
    }
    context = {
        "schema_version": "minimal-decision-context-v1",
        "customer_goal": _clip(customer_message, 300),
        "requested_claims": _as_list(admitted_context.get("requested_claims")),
        "conversation_summary": compact_summary,
        "product_identity": _as_dict(admitted_context.get("product_identity")),
        "admitted_evidence": selected,
        "claim_resolutions": _as_list(admitted_context.get("claim_resolutions")),
        "unresolved_claims": _as_list(admitted_context.get("unresolved_claims")),
        "conflicting_claims": _as_list(admitted_context.get("conflicting_claims")),
        "service_actions": actions,
        "media_candidates": media,
        "allowed_read_only_tools": sorted(_unique(allowed_read_only_tools or [])),
        "channel_capabilities": _as_dict(channel_capabilities),
        "safety_constraints": {
            "only_admitted_evidence_for_facts": True,
            "unresolved_or_conflicting_claims_cannot_be_asserted": True,
            "service_actions_and_media_are_not_facts": True,
        },
        "context_stats": {
            "admitted_evidence_count": len(selected),
            "admitted_evidence_source_distribution": sources,
            "estimated_token_count": max(1, len(str(selected) + str(actions) + str(media)) // 4),
            "trim_reasons": trim_reasons,
            "excluded_context_categories": [
                "raw_candidate_store",
                "rejected_evidence",
                "answer_memory_history",
                "benchmark_expected_text",
                "full_trace",
            ],
        },
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }
    return sanitize_obj(context)
