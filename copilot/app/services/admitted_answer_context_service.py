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
from app.services.claim_resolution_service import (
    build_claim_resolutions,
    build_inference_requirement_status,
    expand_claim_dependencies,
)
from app.services.fact_type_alias_service import (
    build_risk_policy_status,
    canonical_attribute_slot,
    canonical_material_composition_claim_type,
    normalize_high_risk_claim_type,
)
from app.services.product_structured_evidence_service import material_evidence_admission_reason
from app.services.semantic_fact_type_service import (
    GOAL_IDENTITY_SCHEMA_VERSION,
    canonical_source_span_text,
    goal_understanding_eligibility_status,
)


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
    "已收录尺寸图",
    "以尺寸图或商品详情页标注为准",
)
# Variants where characters may intervene between the negation and the claim
# (e.g. "未在现有结构资料中明确尺寸").
_PLACEHOLDER_PATTERNS = (
    re.compile(r"未.{0,24}明确"),
)

COMPATIBLE_FACT_TYPES = {
    "installation_media": {"installation", "installation_media", "installation_media_request"},
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
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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


def _structured_sha256(value: Any) -> str:
    """Parse a provenance digest without applying free-text PII sanitization."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    return candidate if _SHA256_PATTERN.fullmatch(candidate) else ""


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


def _canonical_attribute_key(item: dict[str, Any]) -> str:
    declared_claim_type = sanitize_text(item.get("claim_type")).lower()
    return canonical_attribute_slot(
        sanitize_text(
            item.get("canonical_attribute_key") or _attribute_key(item)
        ).lower(),
        fact_type=_fact_type(item) or declared_claim_type,
        supported_claim_types=item.get("claim_types_supported")
        or item.get("supported_claim_types")
        or (),
    )


def _dimension_subject_scope(item: dict[str, Any]) -> str:
    """Return the subject bucket used for dimension conflict isolation."""
    fact_types = {
        _fact_type(item),
        *(_claim_types(item)),
    }
    if not fact_types.intersection({"dimensions", "size", "space_fit"}):
        return ""
    subject_scope = sanitize_text(item.get("subject_scope")).lower()
    return "product" if subject_scope in {"product", "product_overall"} else subject_scope


def _conflict_group_key(item: dict[str, Any]) -> str:
    """Keep independently scoped dimensions out of the same conflict group."""
    slot = sanitize_text(item.get("canonical_attribute_key"))
    subject_scope = _dimension_subject_scope(item)
    if slot and subject_scope:
        return f"{slot}|subject:{subject_scope}"
    if slot and _dimension_subject_scope(item) == "":
        fact_types = {_fact_type(item), *(_claim_types(item))}
        if fact_types.intersection({"dimensions", "size", "space_fit"}):
            return f"{slot}|subject:__missing__"
    return slot


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
    return values


def _canonical_claim_types(values: list[str] | set[str]) -> set[str]:
    return {
        canonical_material_composition_claim_type(value)
        for value in values
        if sanitize_text(value)
    }


def _compatible_claim_types(claim_type: str) -> set[str]:
    return _canonical_claim_types(
        COMPATIBLE_FACT_TYPES.get(claim_type, {claim_type})
    )


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
        supported = _canonical_claim_types(_claim_types(item))
        compatible = set().union(
            *(_compatible_claim_types(claim) for claim in requested_claim_types)
        )
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
        if explicit_value and (
            canonical_material_composition_claim_type(fact_type)
            == "material_composition"
            or fact_type in {"color", "colour"}
        ):
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


def _product_context_capabilities(
    response: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    debug = _as_dict(response.get("evidence_debug"))
    context = _as_dict(response.get("context_used"))
    pack = (
        _as_dict(response.get("product_context_pack"))
        or _as_dict(context.get("product_context_pack"))
        or _as_dict(debug.get("product_context_pack_summary"))
    )
    profile = _as_dict(pack.get("structured_profile"))
    category = _as_dict(profile.get("category"))
    has_category = (
        sanitize_text(profile.get("source")) == "kb_product"
        and any(
            sanitize_text(category.get(level))
            for level in ("l1", "l2", "l3")
        )
    )
    return (
        {
            "product_category": {
                "available": True,
                "source": "product_context_pack.structured_profile.category",
            }
        }
        if has_category
        else {}
    )


def _bounded_inference_policy_projection(
    domain_policy_pack: dict[str, Any],
) -> list[dict[str, Any]]:
    if sanitize_text(domain_policy_pack.get("status")).lower() != "loaded":
        return []
    prefix = (
        f"domain-policy:{sanitize_text(domain_policy_pack.get('domain_id'))}"
        f"@{sanitize_text(domain_policy_pack.get('version'))}"
    )
    projections: list[dict[str, Any]] = []
    for item in _as_list(domain_policy_pack.get("bounded_inference_policies")):
        if not isinstance(item, dict):
            continue
        policy_intent_ref = sanitize_text(
            item.get("policy_intent_ref")
        ).lower()
        if not policy_intent_ref:
            continue
        projections.append({
            "policy_ref": f"{prefix}:intent:{policy_intent_ref}",
            "pack_content_sha256": _structured_sha256(
                domain_policy_pack.get("pack_content_sha256")
            ),
            "policy_intent_ref": policy_intent_ref,
            "goal_family": sanitize_text(
                item.get("goal_family")
            ).lower(),
            "intent_kind": sanitize_text(
                item.get("intent_kind")
            ).lower(),
            "premise_fact_families": sorted(_unique(
                sanitize_text(value)
                for value in _as_list(item.get("premise_fact_families"))
                if sanitize_text(value)
            )),
            "required_context_capabilities": sorted(_unique(
                sanitize_text(value)
                for value in _as_list(
                    item.get("required_context_capabilities")
                )
                if sanitize_text(value)
            )),
            "allowed_scope": sanitize_text(item.get("allowed_scope")),
            "allowed_conclusion_family": sanitize_text(
                item.get("allowed_conclusion_family")
            ).lower(),
            "allowed_variability_factor_families": sorted(_unique(
                sanitize_text(value).lower()
                for value in _as_list(
                    item.get("allowed_variability_factor_families")
                )
                if sanitize_text(value)
            )),
            "advice_mode": sanitize_text(
                item.get("advice_mode")
            ).lower(),
            "maximum_risk_level": sanitize_text(
                item.get("maximum_risk_level")
            ).lower(),
            "required_qualifiers": sorted(_unique(
                sanitize_text(value)
                for value in _as_list(item.get("required_qualifiers"))
                if sanitize_text(value)
            )),
            "prohibited_claim_families": sorted(_unique(
                sanitize_text(value)
                for value in _as_list(item.get("prohibited_claim_families"))
                if sanitize_text(value)
            )),
            "review_only": item.get("review_only") is True,
            "used_for_evidence": False,
            "used_for_fact_support": False,
            "can_change_can_send": False,
        })
    return sorted(
        projections,
        key=lambda item: sanitize_text(item.get("policy_ref")),
    )


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
            "canonical_attribute_key": _canonical_attribute_key(item),
            "original_fact_type": _fact_type(item),
            "original_evidence_attribute_key": _attribute_key(item),
            "subject_scope": sanitize_text(item.get("subject_scope")).lower(),
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
        slot = _conflict_group_key(candidate)
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
            conflict_reason = (
                "material_conflicting_evidence"
                if all(
                    canonical_material_composition_claim_type(
                        item.get("fact_type")
                    )
                    == "material_composition"
                    for item in comparable
                )
                else "conflicting_evidence"
            )
            rejected.extend({**item, "reason": conflict_reason, "conflict_status": "blocked"} for item in comparable)
            continue
        admitted.append(comparable[0])
        rejected.extend({**item, "reason": "duplicate_evidence"} for item in comparable[1:])
    return admitted[:12], rejected, warnings


def _deduplicate_admitted_origins(
    facts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse multiple transport copies of one admitted source fact."""
    selected: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for fact in sorted(
        facts,
        key=lambda item: (
            sanitize_text(item.get("origin_evidence_key")) or sanitize_text(item.get("evidence_uid")),
            sanitize_text(item.get("evidence_uid")),
        ),
    ):
        key = sanitize_text(fact.get("origin_evidence_key")) or sanitize_text(fact.get("evidence_uid"))
        if key in selected:
            duplicates.append({**fact, "reason": "duplicate_evidence"})
            continue
        selected[key] = fact
    return list(selected.values()), duplicates


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


_FUNNEL_REASON_ALIASES = {
    "resolved_product_identity_missing": "product_identity_missing",
    "product_identity_namespace_missing": "product_identity_missing",
    "product_identity_mismatch": "product_identity_mismatch",
    "fact_type_incompatible": "fact_type_mismatch",
    "review_status_missing": "review_status_missing",
    "not_direct_answerable": "direct_answer_not_allowed",
    "reference_only": "reference_only",
    "placeholder_evidence": "placeholder_fact",
    "conflicting_evidence": "conflicting_evidence",
    "material_conflicting_evidence": "conflicting_evidence",
    "incomparable_unit_domain": "conflicting_evidence",
}


def _funnel_reason(item: dict[str, Any], reason: str) -> str:
    role = _role(item)
    source_type = _source_type(item)
    if reason in {"ineligible_role_or_gate", "evidence_role_not_direct", "reference_only"}:
        if role in ACTION_ROLES or source_type in ACTION_ROLES:
            return "service_action_only"
        if role in MEDIA_ROLES or source_type in MEDIA_ROLES:
            return "media_reference_only"
    if reason == "fact_type_incompatible" and not _fact_type(item):
        return "fact_type_missing"
    return _FUNNEL_REASON_ALIASES.get(reason, reason or "not_direct_candidate")


def _funnel_uid(origin_key: str) -> str:
    return f"funnel-{sha256(origin_key.encode('utf-8')).hexdigest()[:20]}"


def build_turn_evidence_funnel(
    response: dict[str, Any],
    *,
    product_identity: dict[str, Any],
    admitted_context: dict[str, Any],
    convergence_enabled: bool,
) -> dict[str, Any]:
    """Project the shared admission result into a content-free turn funnel.

    This function performs no retrieval and owns no eligibility rules. It reads
    the same candidate containers and admission result used by
    :class:`AdmittedAnswerContextService`, then removes evidence text and
    identity values before the diagnostic is persisted.
    """
    requested_claim_types = [
        sanitize_text(item.get("claim_type")).lower()
        for item in _as_list(admitted_context.get("requested_claims"))
        if isinstance(item, dict) and sanitize_text(item.get("claim_type"))
    ]
    admitted_uids = {
        sanitize_text(item.get("evidence_uid"))
        for item in [
            *(_as_list(admitted_context.get("direct_product_facts"))),
            *(_as_list(admitted_context.get("direct_policy_facts"))),
        ]
        if isinstance(item, dict) and sanitize_text(item.get("evidence_uid"))
    }
    rejected_by_uid = {
        sanitize_text(item.get("evidence_uid")): sanitize_text(item.get("reason"))
        for item in _as_list(admitted_context.get("rejected_evidence"))
        if isinstance(item, dict) and sanitize_text(item.get("evidence_uid"))
    }

    rows_by_origin: dict[str, dict[str, Any]] = {}
    selected_origins: set[str] = set()
    for source, raw_item in _candidate_containers(response):
        item = _normalise_product_context_candidate(source, raw_item, product_identity)
        if source == "response.formal_evidence_candidates":
            item = _normalise_formal_evidence_candidate(item, product_identity)
        text = _text(item)
        provenance = _provenance(source, item, text)
        origin_key = sanitize_text(provenance.get("origin_evidence_key"))
        if source.endswith("selected_evidence"):
            selected_origins.add(origin_key)
        row = rows_by_origin.setdefault(origin_key, {
            "evidence_uid": _funnel_uid(origin_key),
            "source_types": [],
            "source_containers": [],
            "evidence_role": _role(item),
            "fact_type": _fact_type(item),
            "attribute_key": _attribute_key(item),
            "identity_namespaces": [],
            "candidate": True,
            "direct_reviewed": False,
            "identity_matched": False,
            "fact_type_compatible": False,
            "non_placeholder": False,
            "non_conflicting": False,
            "formally_admissible": False,
            "formal_selected": False,
            "rejection_reason": "",
        })
        for value, key in ((source, "source_containers"), (_source_type(item), "source_types")):
            if value and value not in row[key]:
                row[key].append(value)
        row["identity_namespaces"] = sorted(set(row["identity_namespaces"]) | {
            sanitize_text(scope.get("namespace"))
            for scope in _identity_scope(item)
            if sanitize_text(scope.get("namespace"))
        })

        role = _role(item)
        status = sanitize_text(
            item.get("fact_review_status") or item.get("review_status") or item.get("verification_status")
        ).lower()
        gate = sanitize_text(item.get("gate_status")).lower()
        direct_role = role in DIRECT_PRODUCT_ROLES | DIRECT_POLICY_ROLES
        row["direct_reviewed"] = row["direct_reviewed"] or bool(
            direct_role
            and status in REVIEWED_STATUSES
            and gate not in {"blocked", "reference_only", "rejected"}
            and item.get("reference_only") is not True
        )
        policy = role in DIRECT_POLICY_ROLES
        identity_reason = "" if policy else _identity_reason(
            item,
            product_identity,
            allow_global=role == "faq_direct",
        )
        row["identity_matched"] = row["identity_matched"] or bool(row["direct_reviewed"] and not identity_reason)
        supported = _canonical_claim_types(_claim_types(item))
        compatible = (
            set().union(
                *(
                    _compatible_claim_types(claim)
                    for claim in requested_claim_types
                )
            )
            if requested_claim_types else supported
        )
        fact_compatible = not requested_claim_types or not supported.isdisjoint(compatible)
        row["fact_type_compatible"] = row["fact_type_compatible"] or bool(row["identity_matched"] and fact_compatible)

        uid = sanitize_text(provenance.get("evidence_uid"))
        reason = rejected_by_uid.get(uid) or _admission_reason(
            item,
            product_identity=product_identity,
            requested_claim_types=requested_claim_types,
            policy=policy,
        )
        canonical_reason = _funnel_reason(item, reason)
        row["non_placeholder"] = row["non_placeholder"] or canonical_reason != "placeholder_fact"
        row["non_conflicting"] = row["non_conflicting"] or canonical_reason != "conflicting_evidence"
        if uid in admitted_uids:
            row["non_placeholder"] = True
            row["non_conflicting"] = True
            row["formally_admissible"] = True
            row["rejection_reason"] = ""
        elif canonical_reason:
            row["rejection_reason"] = canonical_reason

    for origin_key, row in rows_by_origin.items():
        row["formal_selected"] = origin_key in selected_origins
        row["source_types"].sort()
        row["source_containers"].sort()

    rows = sorted(rows_by_origin.values(), key=lambda item: item["evidence_uid"])
    counts = {
        "product_context_candidate_count": sum(
            1 for row in rows if any(source.startswith("product_context_pack.") for source in row["source_containers"])
        ),
        "candidate_count": len(rows),
        "direct_fact_candidate_count": sum(
            1 for row in rows if row.get("evidence_role") in DIRECT_PRODUCT_ROLES | DIRECT_POLICY_ROLES
        ),
        "direct_reviewed_count": sum(1 for row in rows if row["direct_reviewed"]),
        "identity_matched_count": sum(1 for row in rows if row["identity_matched"]),
        "fact_type_compatible_count": sum(1 for row in rows if row["fact_type_compatible"]),
        "non_placeholder_count": sum(1 for row in rows if row["non_placeholder"]),
        "non_conflicting_count": sum(1 for row in rows if row["non_conflicting"]),
        "formally_admissible_count": sum(1 for row in rows if row["formally_admissible"]),
        "formal_selected_count": sum(1 for row in rows if row["formal_selected"]),
    }
    counts.update({
        "direct_reviewed_candidate_count": counts["direct_reviewed_count"],
        "identity_matched_candidate_count": counts["identity_matched_count"],
        "fact_type_compatible_candidate_count": counts["fact_type_compatible_count"],
        "non_placeholder_candidate_count": counts["non_placeholder_count"],
        "non_conflicting_candidate_count": counts["non_conflicting_count"],
        "formally_admissible_candidate_count": counts["formally_admissible_count"],
        "selected_evidence_count": counts["formal_selected_count"],
    })
    rejected_by_reason: dict[str, int] = {}
    for row in rows:
        reason = sanitize_text(row.get("rejection_reason"))
        if reason:
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1

    identity_present = any(sanitize_text((product_identity or {}).get(key)) for key in _IDENTITY_KEYS)
    if not requested_claim_types:
        earliest_breakpoint = "context_missing"
    elif not identity_present:
        earliest_breakpoint = "product_identity_missing"
    elif not rows:
        earliest_breakpoint = "source_coverage_gap"
    elif counts["direct_fact_candidate_count"] == 0:
        earliest_breakpoint = "evidence_role_ineligible"
    elif counts["direct_reviewed_count"] == 0:
        earliest_breakpoint = "review_status_ineligible"
    elif counts["identity_matched_count"] == 0:
        earliest_breakpoint = "identity_mismatch"
    elif counts["fact_type_compatible_count"] == 0:
        earliest_breakpoint = "fact_type_mismatch"
    elif counts["non_placeholder_count"] == 0:
        earliest_breakpoint = "placeholder_value"
    elif counts["non_conflicting_count"] == 0:
        earliest_breakpoint = "conflicting_evidence"
    elif counts["formally_admissible_count"] == 0:
        reason_priority = (
            "placeholder_value" if rejected_by_reason.get("placeholder_fact")
            else "conflicting_evidence" if rejected_by_reason.get("conflicting_evidence")
            else "evidence_role_ineligible"
        )
        earliest_breakpoint = reason_priority
    elif counts["formal_selected_count"] == 0 and not convergence_enabled:
        earliest_breakpoint = "convergence_disabled"
    elif counts["formal_selected_count"] == 0:
        earliest_breakpoint = "graph_selection_gap"
    else:
        earliest_breakpoint = "selected_successfully"

    gap_classification = earliest_breakpoint

    rejection_reason_counts = dict(rejected_by_reason)
    if earliest_breakpoint in {
        "context_missing", "product_identity_missing", "source_coverage_gap",
        "evidence_role_ineligible", "convergence_disabled", "graph_selection_gap",
    }:
        rejection_reason_counts[earliest_breakpoint] = rejection_reason_counts.get(earliest_breakpoint, 0) + 1

    return sanitize_obj({
        "schema_version": "turn-evidence-funnel-v1",
        "counts": counts,
        "rejected_evidence": [row for row in rows if row.get("rejection_reason")],
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
        "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        "earliest_breakpoint": earliest_breakpoint,
        "gap_classification": gap_classification,
        "records": rows[:80],
        "convergence_enabled": bool(convergence_enabled),
        "read_only": True,
        "contains_evidence_text": False,
        "identity_values_redacted": True,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    })


def _requested_claims(understanding: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(understanding.get("requested_claims")):
        if isinstance(item, dict):
            allowed_fields = {
                "schema_version", "goal_ref", "goal_kind",
                "claim_type_status", "claim_type", "claim_type_exact_match",
                "attribute_key",
                "semantic_key", "policy_intent_ref", "policy_goal_family",
                "policy_intent_kind", "goal_summary", "source", "source_span_start",
                "source_span_end", "source_span_sha256", "source_text_sha256",
                "source_turn_uid", "question", "risk_level",
                "owner", "source_stage", "supporting_only", "eligibility_source",
                "customer_goal_eligible", "direct_handling_prohibited",
                "prohibited", "prohibition_reason",
            }
            raw_claim_type = sanitize_text(item.get("claim_type")).lower()
            claim_type = normalize_high_risk_claim_type(raw_claim_type) or raw_claim_type
            goal_kind = sanitize_text(item.get("goal_kind")).lower()
            claim_type_status = sanitize_text(
                item.get("claim_type_status")
            ).lower()
            semantic_key = sanitize_text(item.get("semantic_key")).lower()
            preserve_unmapped_goal = (
                goal_kind == "customer_goal"
                and claim_type_status == "unmapped"
                and not claim_type
            )
            if claim_type or preserve_unmapped_goal:
                result.append({
                    "schema_version": sanitize_text(
                        item.get("schema_version")
                    ),
                    "goal_ref": sanitize_text(item.get("goal_ref")),
                    "goal_kind": goal_kind,
                    "claim_type_status": claim_type_status,
                    "claim_type": claim_type,
                    "claim_type_exact_match": (
                        item.get("claim_type_exact_match") is True
                    ),
                    "attribute_key": sanitize_text(item.get("attribute_key")).lower(),
                    "semantic_key": semantic_key,
                    "policy_intent_ref": sanitize_text(
                        item.get("policy_intent_ref")
                    ).lower(),
                    "policy_goal_family": sanitize_text(
                        item.get("policy_goal_family")
                    ).lower(),
                    "policy_intent_kind": sanitize_text(
                        item.get("policy_intent_kind")
                    ).lower(),
                    "goal_summary": _clip(item.get("goal_summary"), 160),
                    "question": _clip(item.get("question"), 160),
                    "risk_level": sanitize_text(item.get("risk_level")).lower() or "medium",
                    "source": sanitize_text(item.get("source")).lower(),
                    "source_span_start": item.get("source_span_start"),
                    "source_span_end": item.get("source_span_end"),
                    "source_span_sha256": _structured_sha256(
                        item.get("source_span_sha256")
                    ),
                    "source_text_sha256": _structured_sha256(
                        item.get("source_text_sha256")
                    ),
                    "source_turn_uid": sanitize_text(
                        item.get("source_turn_uid")
                    ).lower(),
                    "owner": sanitize_text(item.get("owner")).lower(),
                    "source_stage": sanitize_text(item.get("source_stage")).lower(),
                    "unexpected_fields": sorted(set(item) - allowed_fields),
                    "supporting_only": item.get("supporting_only") is True,
                    "eligibility_source": sanitize_text(
                        item.get("eligibility_source")
                    ).lower(),
                    "customer_goal_eligible": (
                        item.get("customer_goal_eligible") is not False
                    ),
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


def _canonical_customer_goals_for_eligibility(
    requested_claims: list[dict[str, Any]],
    *,
    current_customer_message: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    goals: list[dict[str, Any]] = []
    reasons: list[str] = []
    for item in requested_claims:
        if (
            not isinstance(item, dict)
            or item.get("supporting_only") is True
            or sanitize_text(item.get("goal_kind")).lower() != "customer_goal"
        ):
            continue
        if not sanitize_text(item.get("goal_ref")):
            reasons.append("canonical_customer_goal_goal_ref_missing")
            continue
        if (
            sanitize_text(item.get("schema_version"))
            != GOAL_IDENTITY_SCHEMA_VERSION
            or not re.fullmatch(
                r"turn-[0-9a-f]{20}",
                sanitize_text(item.get("source_turn_uid")).lower(),
            )
        ):
            reasons.append("canonical_customer_goal_identity_invalid")
            continue
        if not sanitize_text(item.get("claim_type")).lower():
            reasons.append("canonical_customer_goal_claim_type_missing")
            continue
        if (
            sanitize_text(item.get("owner")).lower() != "turn_understanding_owner"
            or sanitize_text(item.get("source_stage")).lower()
            != "query_fact_type_classifier"
        ):
            reasons.append("canonical_customer_goal_provenance_invalid")
            continue
        if item.get("unexpected_fields"):
            reasons.append("canonical_customer_goal_schema_invalid")
            continue
        if sanitize_text(item.get("source")).lower() != "current_customer_message":
            reasons.append("canonical_customer_goal_source_invalid")
            continue
        start = item.get("source_span_start")
        end = item.get("source_span_end")
        digest = _structured_sha256(item.get("source_span_sha256"))
        source_text_digest = _structured_sha256(
            item.get("source_text_sha256")
        )
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or source_text_digest != digest
        ):
            reasons.append("canonical_customer_goal_source_span_missing")
            continue
        if end > len(current_customer_message):
            reasons.append("canonical_customer_goal_source_span_out_of_range")
            continue
        canonical_slice = canonical_source_span_text(
            current_customer_message[start:end]
        )
        if not canonical_slice:
            reasons.append("canonical_customer_goal_source_span_empty")
            continue
        expected_digest = sha256(canonical_slice.encode("utf-8")).hexdigest()
        if digest != expected_digest:
            reasons.append("canonical_customer_goal_source_span_digest_mismatch")
            continue
        if item.get("customer_goal_eligible") is False:
            reasons.append("canonical_customer_goal_ineligible")
            continue
        goals.append(item)
    if not goals:
        reasons.append("canonical_customer_goal_missing")
    elif len(goals) != 1:
        reasons.append("canonical_customer_goal_count_not_one")
    return goals, sorted(set(reasons))


def _normalised_owner_status(
    value: Any,
    *,
    allowed: set[str],
    default_source_stage: str,
    missing_reason: str,
    include_tool_refs: bool = False,
) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    status = sanitize_text(raw.get("status")).lower()
    if status not in allowed:
        status = "unknown"
    reasons = sorted({
        sanitize_text(reason)
        for reason in _as_list(raw.get("reason_codes"))
        if sanitize_text(reason)
    })
    if status == "unknown" and not reasons:
        reasons = [missing_reason]
    result = {
        "status": status,
        "source_stage": sanitize_text(raw.get("source_stage"))
        or default_source_stage,
        "reason_codes": reasons,
    }
    if include_tool_refs:
        result["required_tool_refs"] = sorted(_unique(
            sanitize_text(item)
            for item in _as_list(raw.get("required_tool_refs"))
            if sanitize_text(item)
        ))
        result["completed_tool_refs"] = sorted(_unique(
            sanitize_text(item)
            for item in _as_list(raw.get("completed_tool_refs"))
            if sanitize_text(item)
        ))
    return result


def _domain_policy_projection(pack: dict[str, Any]) -> dict[str, Any]:
    status = sanitize_text(pack.get("status")).lower()
    if status not in {"loaded", "missing", "invalid"}:
        status = "unknown"
    return {
        "domain_id": sanitize_text(pack.get("domain_id")),
        "version": sanitize_text(pack.get("version")),
        "pack_ref": sanitize_text(pack.get("pack_ref")),
        "pack_content_sha256": _structured_sha256(
            pack.get("pack_content_sha256")
        ),
        "status": status,
    }


def _resolution_matches_goal(
    resolution: dict[str, Any],
    goal: dict[str, Any],
) -> bool:
    goal_claim_type = canonical_material_composition_claim_type(
        goal.get("claim_type")
    )
    resolution_claim_type = canonical_material_composition_claim_type(
        resolution.get("claim_type")
    )
    canonical_compatible_claim_types = _compatible_claim_types(goal_claim_type)
    if resolution_claim_type not in canonical_compatible_claim_types:
        return False
    goal_attribute = _canonical_attribute_key(goal)
    if goal_attribute and (
        _canonical_attribute_key(resolution)
        != goal_attribute
    ):
        return False
    return True


def _admitted_fact_matches_goal(
    fact: dict[str, Any],
    goal: dict[str, Any],
    product_identity: dict[str, Any],
) -> bool:
    goal_claim_type = canonical_material_composition_claim_type(
        goal.get("claim_type")
    )
    canonical_compatible_claim_types = _compatible_claim_types(goal_claim_type)
    fact_claim_types = {
        canonical_material_composition_claim_type(item)
        for item in _claim_types(fact)
    }
    if fact_claim_types.isdisjoint(canonical_compatible_claim_types):
        return False

    goal_attribute = _canonical_attribute_key(goal)
    if goal_attribute and _canonical_attribute_key(fact) != goal_attribute:
        return False

    expected = {
        key: sanitize_text(product_identity.get(key))
        for key in _IDENTITY_KEYS
        if sanitize_text(product_identity.get(key))
    }
    actual: dict[str, set[str]] = {}
    for scope in _as_list(
        fact.get("product_identity_scope") or fact.get("identity_scopes")
    ):
        if not isinstance(scope, dict):
            continue
        namespace = sanitize_text(scope.get("namespace"))
        value = sanitize_text(scope.get("value"))
        if namespace in _IDENTITY_KEYS and value:
            actual.setdefault(namespace, set()).add(value)
    common = set(expected).intersection(actual)
    return bool(common) and all(
        actual[namespace] == {expected[namespace]}
        for namespace in common
    )


def _fast_path_block_reasons(
    *,
    domain_policy_pack: dict[str, Any],
    requested_claims: list[dict[str, Any]],
    current_customer_message: str,
    claim_resolutions: list[dict[str, Any]],
    goal_status: dict[str, Any],
    reference_status: dict[str, Any],
    tool_status: dict[str, Any],
    inference_status: dict[str, Any],
    risk_status: dict[str, Any],
    admitted_direct_facts: list[dict[str, Any]],
    product_identity: dict[str, Any],
    has_actions: bool,
    has_media: bool,
) -> list[str]:
    reasons: list[str] = []
    if domain_policy_pack.get("status") != "loaded":
        reasons.append("domain_policy_not_loaded")
    if goal_status["status"] != "valid":
        reasons.append("goal_understanding_not_valid")
    canonical_goals, canonical_goal_reasons = (
        _canonical_customer_goals_for_eligibility(
            requested_claims,
            current_customer_message=current_customer_message,
        )
    )
    reasons.extend(canonical_goal_reasons)
    if any(
        isinstance(item, dict)
        and (
            sanitize_text(item.get("goal_kind")).lower()
            == "evidence_dependency"
            or item.get("supporting_only") is True
        )
        for item in requested_claims
    ) or any(
        isinstance(item, dict) and item.get("supporting_only") is True
        for item in claim_resolutions
    ):
        reasons.append("evidence_dependency_present")
    if reference_status["status"] not in {"not_required", "resolved"}:
        reasons.append("conversation_reference_not_resolved")
    if tool_status["status"] not in {
        "not_required",
        "static_knowledge_completed",
    }:
        reasons.append("tool_requirement_not_fast_path_eligible")
    if inference_status["status"] != "direct_evidence_only":
        reasons.append("direct_evidence_only_not_verified")
    if risk_status["status"] != "low_risk_verified":
        reasons.append("low_risk_not_verified")
    if any(
        item.get("support_basis") != "direct_evidence"
        for item in claim_resolutions
        if isinstance(item, dict) and item.get("status")
    ):
        reasons.append("claim_support_not_direct")
    for resolution in claim_resolutions:
        if not isinstance(resolution, dict):
            continue
        if resolution.get("supporting_only") is True and (
            resolution.get("status") != "supported"
            or resolution.get("support_basis") != "direct_evidence"
        ):
            reasons.append("supporting_dependency_unsatisfied")
        status = sanitize_text(resolution.get("status")).lower()
        if status == "unresolved":
            reasons.append("unresolved_claim_present")
        elif status == "conflicting":
            reasons.append("conflicting_claim_present")
        elif status == "prohibited":
            reasons.append("prohibited_claim_present")

    if len(canonical_goals) == 1:
        goal = canonical_goals[0]
        goal_ref = sanitize_text(goal.get("goal_ref"))
        goal_resolutions = [
            item
            for item in claim_resolutions
            if isinstance(item, dict)
            and item.get("supporting_only") is not True
            and sanitize_text(item.get("goal_ref")) == goal_ref
            and _resolution_matches_goal(item, goal)
        ]
        evidence_uids = sorted({
            sanitize_text(uid)
            for resolution in goal_resolutions
            if sanitize_text(resolution.get("status")).lower() == "supported"
            for uid in _as_list(resolution.get("evidence_uids"))
            if sanitize_text(uid)
        })
        admitted_by_uid = {
            sanitize_text(item.get("evidence_uid")): item
            for item in admitted_direct_facts
            if isinstance(item, dict) and sanitize_text(item.get("evidence_uid"))
        }
        aligned_evidence = [
            admitted_by_uid[uid]
            for uid in evidence_uids
            if uid in admitted_by_uid
            and _admitted_fact_matches_goal(
                admitted_by_uid[uid],
                goal,
                product_identity,
            )
        ]
        if not evidence_uids or len(aligned_evidence) != len(evidence_uids):
            reasons.append("single_direct_evidence_not_verified")
        elif len(aligned_evidence) > 1:
            reasons.append("multiple_direct_evidence_present")

    policies = domain_policy_pack.get("claim_policies")
    policies = policies if isinstance(policies, dict) else {}
    for claim in canonical_goals:
        policy = policies.get(sanitize_text(claim.get("claim_type")).lower())
        if not isinstance(policy, dict):
            reasons.append("claim_policy_missing")
            continue
        if policy.get("direct_fact_fast_path_allowed") is not True:
            reasons.append("domain_policy_fast_path_not_allowed")
        if policy.get("freshness_requirement") != "static":
            reasons.append("domain_policy_requires_nonstatic_state")
    if has_actions:
        reasons.append("service_action_present")
    if has_media:
        reasons.append("media_candidate_present")
    return sorted(set(reasons))


def build_answer_eligibility_context(
    *,
    understanding: dict[str, Any],
    requested_claims: list[dict[str, Any]],
    current_customer_message: str,
    claim_resolutions: list[dict[str, Any]],
    domain_policy_pack: dict[str, Any],
    conversation_reference_status: dict[str, Any] | None,
    tool_requirement_status: dict[str, Any] | None,
    admitted_direct_facts: list[dict[str, Any]],
    product_identity: dict[str, Any],
    has_actions: bool,
    has_media: bool,
    trusted_domain_policy_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble owner verdicts without routing or changing formal behavior."""
    goal_status = goal_understanding_eligibility_status(understanding)
    reference_status = _normalised_owner_status(
        conversation_reference_status,
        allowed={"not_required", "resolved", "ambiguous", "missing", "unknown"},
        default_source_stage="canonical_context_resolution",
        missing_reason="conversation_reference_owner_missing",
    )
    tool_status = _normalised_owner_status(
        tool_requirement_status,
        allowed={
            "not_required",
            "static_knowledge_completed",
            "live_tool_required",
            "live_tool_completed",
            "live_tool_failed",
            "action_tool_required",
            "unknown",
        },
        default_source_stage="tool_router_and_executor",
        missing_reason="tool_requirement_status_missing",
        include_tool_refs=True,
    )
    inference_status = build_inference_requirement_status(
        claim_resolutions,
        domain_policy_status=sanitize_text(
            domain_policy_pack.get("status")
        ).lower(),
    )
    risk_status = build_risk_policy_status(
        requested_claims,
        domain_policy_pack=domain_policy_pack,
    )
    block_reasons = _fast_path_block_reasons(
        domain_policy_pack=domain_policy_pack,
        requested_claims=requested_claims,
        current_customer_message=current_customer_message,
        claim_resolutions=claim_resolutions,
        goal_status=goal_status,
        reference_status=reference_status,
        tool_status=tool_status,
        inference_status=inference_status,
        risk_status=risk_status,
        admitted_direct_facts=admitted_direct_facts,
        product_identity=product_identity,
        has_actions=has_actions,
        has_media=has_media,
    )
    return sanitize_obj({
        "schema_version": "answer-eligibility-context/v1",
        "domain_policy": _domain_policy_projection(domain_policy_pack),
        "trusted_domain_policy_context": _as_dict(
            trusted_domain_policy_context
        ),
        "goal_understanding_status": goal_status,
        "conversation_reference_status": reference_status,
        "tool_requirement_status": tool_status,
        "inference_requirement_status": inference_status,
        "risk_policy_status": risk_status,
        "fast_path_preconditions_complete": not block_reasons,
        "fast_path_block_reasons": block_reasons,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    })


class AdmittedAnswerContextService:
    """Compile candidate evidence into auditable answer-context roles."""

    def build_for_response(
        self,
        response: dict[str, Any],
        *,
        product_identity: dict[str, Any] | None = None,
        understanding: dict[str, Any] | None = None,
        current_customer_message: str = "",
        answer_eligibility_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity = resolved_product_identity_for_response(response, product_identity)
        understanding = _as_dict(understanding)
        eligibility_inputs = _as_dict(answer_eligibility_inputs)
        trusted_domain_policy_context = _as_dict(
            eligibility_inputs.get("trusted_domain_policy_context")
        )
        domain_policy_pack = _as_dict(
            eligibility_inputs.get("domain_policy_pack")
        )
        if not domain_policy_pack:
            domain_policy_pack = {
                "schema_version": "domain-policy-pack/v1",
                "domain_id": "",
                "version": "",
                "status": "missing",
                "reason_codes": ["domain_policy_pack_not_provided"],
                "claim_policies": {},
                "bounded_inference_policies": [],
            }
        product_context_capabilities = _product_context_capabilities(response)
        bounded_inference_policies = _bounded_inference_policy_projection(
            domain_policy_pack
        )
        requested_claims = _requested_claims(understanding)
        requested_claim_types = [
            item["claim_type"]
            for item in requested_claims
            if item.get("claim_type")
        ]
        direct_product, rejected, warnings = collect_admitted_product_facts(
            response,
            product_identity=identity,
            requested_claim_types=requested_claim_types,
        )
        direct_product, duplicate_origins = _deduplicate_admitted_origins(direct_product)
        rejected.extend(duplicate_origins)

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
            claim_policies=_as_dict(domain_policy_pack.get("claim_policies")),
            bounded_inference_policies=bounded_inference_policies,
            context_capabilities=product_context_capabilities,
            policy_ref_prefix=(
                f"domain-policy:{sanitize_text(domain_policy_pack.get('domain_id'))}"
                f"@{sanitize_text(domain_policy_pack.get('version'))}"
                if domain_policy_pack.get("status") == "loaded"
                else ""
            ),
        )
        answer_eligibility_context = build_answer_eligibility_context(
            understanding=understanding,
            requested_claims=requested_claims,
            current_customer_message=str(current_customer_message or ""),
            claim_resolutions=claim_resolutions,
            domain_policy_pack=domain_policy_pack,
            conversation_reference_status=_as_dict(
                eligibility_inputs.get("conversation_reference_status")
            ),
            tool_requirement_status=_as_dict(
                eligibility_inputs.get("tool_requirement_status")
            ),
            admitted_direct_facts=[*direct_product, *direct_policy],
            product_identity=identity,
            has_actions=bool(actions),
            has_media=bool(media),
            trusted_domain_policy_context=trusted_domain_policy_context,
        )
        requested_by_goal = {
            sanitize_text(item.get("goal_ref")): item
            for item in requested_claims
            if sanitize_text(item.get("goal_ref"))
        }
        requested_by_claim = {
            sanitize_text(item.get("claim_type")): item
            for item in requested_claims
            if sanitize_text(item.get("claim_type"))
        }
        unresolved = [
            {
                **(
                    requested_by_goal.get(
                        sanitize_text(resolution.get("goal_ref"))
                    )
                    or requested_by_claim.get(
                        sanitize_text(resolution.get("claim_type"))
                    )
                    or {}
                ),
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
            "product_context_capabilities": product_context_capabilities,
            "bounded_inference_policies": bounded_inference_policies,
            "trusted_domain_policy_context": (
                trusted_domain_policy_context
            ),
            "answer_eligibility_context": answer_eligibility_context,
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
    conversation_turns: list[dict[str, Any]] | None = None,
    channel_capabilities: dict[str, Any] | None = None,
    allowed_read_only_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Build bounded, non-reasoning context for a strict decision provider."""
    from app.services.canonical_conversation_turn_service import (
        project_conversation_turns_for_external_model,
        project_text_for_external_model,
    )

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
        key: _clip(project_text_for_external_model(value), 180)
        for key, value in summary.items()
        if key in {"summary", "current_turn", "customer_concern", "unresolved_slots"}
        and sanitize_text(value)
    }
    recent_turns = [
        {
            "role": turn.get("role"),
            "content": _clip(turn.get("content"), 280),
            "turn_index": turn.get("turn_index"),
        }
        for turn in project_conversation_turns_for_external_model(_as_list(conversation_turns), max_turns=8)
        if turn.get("content")
    ]
    context = {
        "schema_version": "minimal-decision-context-v1",
        "answer_eligibility_context": _as_dict(
            admitted_context.get("answer_eligibility_context")
        ),
        "trusted_domain_policy_context": _as_dict(
            admitted_context.get("trusted_domain_policy_context")
        ),
        "customer_goal": _clip(project_text_for_external_model(customer_message), 300),
        "requested_claims": _as_list(admitted_context.get("requested_claims")),
        "conversation_summary": compact_summary,
        "recent_conversation_turns": recent_turns,
        "product_identity": _as_dict(admitted_context.get("product_identity")),
        "admitted_evidence": selected,
        "claim_resolutions": _as_list(admitted_context.get("claim_resolutions")),
        "product_context_capabilities": _as_dict(
            admitted_context.get("product_context_capabilities")
        ),
        "bounded_inference_policies": _as_list(
            admitted_context.get("bounded_inference_policies")
        ),
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
            "recent_turn_count": len(recent_turns),
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
