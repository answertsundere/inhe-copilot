"""Build first-class evidence candidates from structured product data.

This service is intentionally narrow: it converts explicit, already-resolved
product fields into evidence candidates. It does not infer high-risk facts from
nearby fields and it does not generate customer replies by itself.
"""

from __future__ import annotations

from typing import Any

from app.services.fact_type_alias_service import (
    canonical_material_composition_claim_type,
)


BLOCKED_DIRECT_FACT_TYPES = {
    "certification_report",
    "pinch_safety",
    "safety_small_parts",
    "material_safety",
}

STRONG_MATERIAL_CLAIM_TERMS = (
    "食品级",
    "无毒",
    "环保",
    "安全",
    "认证",
    "检测",
    "甲醛",
)

UNTRUSTED_STRUCTURED_FIELD_SOURCES = {
    "conservative_placeholder",
    "placeholder",
    "unverified",
}

_FIELD_TOKENS = {
    "material": ("material", "\u6750\u8d28", "\u6750\u6599", "\u7528\u6599"),
    "dimensions": (
        "size",
        "\u5c3a\u5bf8",
        "\u957f\u5bbd\u9ad8",
        "height",
        "width",
        "length",
        "\u89c4\u683c",
        "dimension",
    ),
    "space_fit": (
        "size",
        "\u5c3a\u5bf8",
        "\u957f\u5bbd\u9ad8",
        "height",
        "width",
        "length",
        "\u89c4\u683c",
        "dimension",
    ),
    "placement_scene": ("usage_scene", "scene", "room", "\u9002\u7528\u573a\u666f", "\u6446\u653e"),
    "load_capacity": ("load_capacity", "\u627f\u91cd", "\u8f7d\u91cd"),
    "gross_weight": (
        "gross_weight",
        "gross_weight_kg",
        "package_weight",
        "product_weight",
        "weight",
        "\u6bdb\u91cd",
        "\u5305\u88c5\u91cd\u91cf",
        "\u5546\u54c1\u91cd\u91cf",
    ),
    "installation": ("install_method", "installation", "\u5b89\u88c5", "\u7ec4\u88c5", "\u6253\u5b54"),
    "accessory_availability": (
        "accessory_availability",
        "accessory_purchase",
        "accessory_sale",
        "spare_part_purchase",
        "\u914d\u4ef6\u552e\u5356",
        "\u914d\u4ef6\u8865\u8d2d",
        "\u914d\u4ef6\u5355\u5356",
    ),
    "detachable": ("detachable", "\u53ef\u62c6", "\u62c6\u5378", "\u62c6\u88c5"),
    "odor": ("odor", "odor_note", "\u6c14\u5473", "\u5473\u9053", "\u5f02\u5473", "\u6563\u5473"),
    "cleaning_care": ("cleaning", "\u6e05\u6d17", "\u4fdd\u517b", "\u6c34\u6d17"),
    "age_range": ("age_range", "\u9002\u7528\u5e74\u9f84", "\u6708\u9f84", "\u5e74\u9f84"),
    "accessories": ("accessories", "\u914d\u4ef6", "\u6e05\u5355", "parts"),
    "stock_shipping": ("shipping", "\u53d1\u8d27", "\u7269\u6d41", "\u5e93\u5b58"),
    "aftersales_policy": ("warranty", "\u8d28\u4fdd", "\u552e\u540e"),
}


def build_product_spec_evidence_candidates(
    profile: dict[str, Any],
    *,
    requested_fact_type: str,
) -> list[dict[str, Any]]:
    """Return direct-answer candidates for explicit product profile fields."""

    requested = str(requested_fact_type or "").strip()
    if not profile or not requested or requested in BLOCKED_DIRECT_FACT_TYPES:
        return []

    field_fact_type = (
        "material"
        if canonical_material_composition_claim_type(requested)
        == "material_composition"
        else requested
    )
    values = _pick_values(profile, field_fact_type)
    if not values:
        return []

    if (
        field_fact_type == "material"
        and material_direct_answer_block_reason(profile, values)
    ):
        return []

    value_text = _format_values(values)
    customer_text = _customer_text(field_fact_type, value_text)
    product_id = profile.get("product_id")
    source_field_keys = [key for key, _value in values]
    sku_list = [
        str(item.get("sku_code") or "").strip()
        for item in profile.get("sku_list", [])
        if isinstance(item, dict) and str(item.get("sku_code") or "").strip()
    ]
    sku = sku_list[0] if sku_list else ""
    return [{
        "evidence_id": f"kbproduct:{product_id}:{requested}:{'|'.join(source_field_keys)}",
        "source_type": "product_spec",
        "source_table": "kb_product",
        "source_id": str(product_id or ""),
        "product_id": product_id,
        "sku": sku,
        "item_id": profile.get("i_id", ""),
        "product_name": profile.get("product_name", ""),
        "fact_type": requested,
        "requested_fact_type": requested,
        "source_field_keys": source_field_keys,
        "value": value_text,
        "customer_text": customer_text,
        "verification_status": "verified",
        "material_provenance": structured_field_source_kind(profile, "material") if field_fact_type == "material" else "",
        "source_confidence": 0.85,
        "can_direct_answer": True,
        "needs_human_review": False,
        "media_asset_id": "",
        "media_url": "",
        "block_reasons": [],
    }]


def structured_field_source_kind(profile: dict[str, Any], field_name: str) -> str:
    """Return explicit field provenance without inventing it from product status."""
    specs = profile.get("specs") if isinstance(profile.get("specs"), dict) else {}
    root = specs.get("_auto_backfill")
    if not isinstance(root, dict):
        return "structured_product_record"
    source_kind = ""
    for batch in root.values():
        if not isinstance(batch, dict):
            continue
        sources = batch.get("sources")
        if isinstance(sources, dict) and str(sources.get(field_name) or "").strip():
            source_kind = str(sources[field_name]).strip()
    return source_kind or "structured_product_record"


def material_direct_answer_block_reason(
    profile: dict[str, Any],
    values: list[tuple[str, Any]] | None = None,
) -> str:
    """Block composition evidence when field provenance or claim scope is unsafe."""
    picked = values if values is not None else _pick_values(profile, "material")
    return material_evidence_admission_reason({
        "fact_type": "material",
        "value": _format_values(picked),
        "material_provenance": structured_field_source_kind(profile, "material"),
    })


def material_evidence_admission_reason(candidate: dict[str, Any]) -> str:
    """Return the reusable direct-answer rejection reason for material evidence.

    This deliberately validates the field itself.  A published product record
    is not field provenance and cannot turn an imported placeholder into a
    direct composition fact.
    """
    fact_type = str(candidate.get("requested_fact_type") or candidate.get("evidence_fact_type") or candidate.get("fact_type") or "").strip()
    if fact_type not in {"material", "material_composition"}:
        return ""
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    value = " ".join(str(candidate.get(key) or "") for key in ("value", "fact_value", "content", "chunk_text", "customer_text", "fact"))
    value = value.strip()
    if not value:
        return "material_placeholder"
    # Import lazily to keep the shared product-field helper independent from
    # the larger admission service at module import time.
    from app.services.admitted_answer_context_service import is_placeholder_evidence_text

    if is_placeholder_evidence_text(value):
        return "material_placeholder"
    provenance = str(
        candidate.get("material_provenance")
        or candidate.get("field_provenance")
        or candidate.get("provenance_kind")
        or candidate.get("source_kind")
        or metadata.get("material_provenance")
        or metadata.get("field_provenance")
        or metadata.get("provenance_kind")
        or ""
    ).strip().lower()
    if not provenance:
        return "material_provenance_missing"
    if provenance in UNTRUSTED_STRUCTURED_FIELD_SOURCES or any(token in provenance for token in UNTRUSTED_STRUCTURED_FIELD_SOURCES):
        return "material_source_untrusted"
    if any(term in value for term in STRONG_MATERIAL_CLAIM_TERMS):
        return "material_strong_claim_mixed"
    return ""


def _pick_values(profile: dict[str, Any], fact_type: str) -> list[tuple[str, Any]]:
    specs = profile.get("specs") if isinstance(profile.get("specs"), dict) else {}
    logistics = profile.get("logistics") if isinstance(profile.get("logistics"), dict) else {}
    warranty = profile.get("warranty") if isinstance(profile.get("warranty"), dict) else {}
    values = {**specs, **logistics, **warranty}
    tokens = _FIELD_TOKENS.get(fact_type, ())
    picked: list[tuple[str, Any]] = []
    for key, value in values.items():
        if value in (None, "", [], {}, "-"):
            continue
        key_text = str(key).lower()
        if any(token.lower() in key_text or token in str(key) for token in tokens):
            picked.append((str(key), value))
    if not picked:
        picked.extend(_pick_sku_values(profile, fact_type))
    return picked


def _pick_sku_values(profile: dict[str, Any], fact_type: str) -> list[tuple[str, Any]]:
    if fact_type != "gross_weight":
        return []
    sku_list = profile.get("sku_list") if isinstance(profile.get("sku_list"), list) else []
    rows = []
    for item in sku_list:
        if not isinstance(item, dict):
            continue
        weight = str(item.get("gross_weight_kg") or item.get("gross_weight") or item.get("package_weight") or "").strip()
        if not weight:
            continue
        spec = str(item.get("spec") or item.get("sku_name") or "").strip()
        color = str(item.get("color") or "").strip()
        label = " ".join(part for part in (spec, color) if part).strip() or str(item.get("sku_code") or "").strip() or "该规格"
        suffix = "" if weight.endswith(("kg", "KG", "Kg", "公斤")) else "kg"
        rows.append((label, f"{weight}{suffix}"))
    if not rows:
        return []

    unique_weights = []
    for _label, weight in rows:
        if weight not in unique_weights:
            unique_weights.append(weight)
    if len(unique_weights) == 1:
        return [("sku_list.gross_weight_kg", unique_weights[0])]

    preview = "；".join(f"{label}：{weight}" for label, weight in rows[:8])
    if len(rows) > 8:
        preview = f"{preview}；另有{len(rows) - 8}个规格需按具体规格核对"
    return [("sku_list.gross_weight_kg", f"不同规格毛重不同，{preview}")]


def _format_values(values: list[tuple[str, Any]]) -> str:
    parts = []
    for _key, value in values:
        if isinstance(value, (list, tuple)):
            text = "\u3001".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            text = "\uff1b".join(f"{k}{v}" for k, v in value.items() if v not in (None, "", [], {}, "-"))
        else:
            text = str(value).strip()
        if text and text not in parts:
            parts.append(text)
    return "\uff1b".join(parts)


def _customer_text(fact_type: str, value_text: str) -> str:
    labels = {
        "material": "\u8fd9\u6b3e\u5546\u54c1\u7684\u6750\u8d28\u4fe1\u606f\u4e3a",
        "dimensions": "\u8fd9\u6b3e\u5546\u54c1\u7684\u5c3a\u5bf8/\u89c4\u683c\u4e3a",
        "space_fit": "\u8fd9\u6b3e\u5546\u54c1\u7684\u5c3a\u5bf8/\u89c4\u683c\u4e3a",
        "placement_scene": "\u8fd9\u6b3e\u5546\u54c1\u7684\u9002\u7528\u6446\u653e\u573a\u666f\u4e3a",
        "load_capacity": "\u8fd9\u6b3e\u5546\u54c1\u7684\u627f\u91cd\u4fe1\u606f\u4e3a",
        "gross_weight": "\u8fd9\u6b3e\u5546\u54c1\u7684\u6bdb\u91cd/\u5305\u88c5\u91cd\u91cf\u4e3a",
        "installation": "\u8fd9\u6b3e\u5546\u54c1\u7684\u5b89\u88c5\u65b9\u5f0f/\u8bf4\u660e\u4e3a",
        "accessory_availability": "\u8fd9\u6b3e\u5546\u54c1\u7684\u914d\u4ef6\u552e\u5356/\u8865\u8d2d\u89c4\u5219\u4e3a",
        "detachable": "\u8fd9\u6b3e\u5546\u54c1\u7684\u62c6\u88c5\u8bf4\u660e\u4e3a",
        "odor": "\u8fd9\u6b3e\u5546\u54c1\u7684\u6c14\u5473\u8bf4\u660e\u4e3a",
        "cleaning_care": "\u8fd9\u6b3e\u5546\u54c1\u7684\u6e05\u6d01\u4fdd\u517b\u8bf4\u660e\u4e3a",
        "age_range": "\u8fd9\u6b3e\u5546\u54c1\u7684\u9002\u7528\u5e74\u9f84\u4fe1\u606f\u4e3a",
        "accessories": "\u8fd9\u6b3e\u5546\u54c1\u7684\u914d\u4ef6\u6e05\u5355\u4e3a",
        "stock_shipping": "\u8fd9\u6b3e\u5546\u54c1\u7684\u53d1\u8d27/\u7269\u6d41\u4fe1\u606f\u4e3a",
        "aftersales_policy": "\u8fd9\u6b3e\u5546\u54c1\u7684\u552e\u540e/\u8d28\u4fdd\u4fe1\u606f\u4e3a",
    }
    label = labels.get(fact_type, "\u8fd9\u6b3e\u5546\u54c1\u7684\u76f8\u5173\u8d44\u6599\u4e3a")
    return f"{label}\uff1a{value_text}\u3002"
