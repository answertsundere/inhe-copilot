"""Read-only export helpers for real-derived evidence validation fixtures.

The fixture retains reviewed customer-answerable values but replaces every
source identity with a keyed pseudonym.  It is deliberately separate from the
formal knowledge database and cannot write to it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.admitted_answer_context_service import is_placeholder_evidence_text
from app.services.product_structured_evidence_service import (
    build_product_spec_evidence_candidates,
)


FIXTURE_SCHEMA_VERSION = "real-derived-evidence-fixture-v2"
REAL_DERIVED_SOURCE_KIND = "real_derived"
REAL_DERIVED_DATASET_ID = "real-derived-product-evidence-v1"
LOW_RISK_FACT_TYPES = ("material", "dimensions", "gross_weight", "detachable")
INVENTORY_FIELDS = {
    "material_composition": "material",
    "dimensions": "dimensions",
    "gross_weight": "gross_weight",
    "detachable": "detachable",
    "included_components": "accessories",
}
UNSUPPORTED_INVENTORY_FIELD_KEYS = {
    "layer_count": ("layer_count", "layers", "tier_count"),
    "compartment_count": ("compartment_count", "compartments"),
    "color": ("color", "colour"),
}
MINIMUM_PRODUCT_COUNT = 5
MINIMUM_FACTS_PER_PRODUCT = 1
MINIMUM_TOTAL_FACTS = 15
MINIMUM_FACT_TYPE_COUNT = 3
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SENSITIVE_PATTERNS = (
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{15,18}[0-9Xx]\b"),
    re.compile(r"(?:sk-|api[_-]?key|password|token|dsn)\s*[:=]", re.I),
    re.compile(r"https?://", re.I),
)


class RealDerivedFixtureError(ValueError):
    """Raised when a source cannot safely produce a real-derived fixture."""


def validate_real_derived_fixture(fixture: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate provenance before a real-derived vertical slice can run."""
    if not isinstance(fixture, dict):
        raise RealDerivedFixtureError("fixture_invalid")
    if not isinstance(manifest, dict) or not manifest:
        raise RealDerivedFixtureError("manifest_required")
    if fixture.get("source_kind") != REAL_DERIVED_SOURCE_KIND:
        raise RealDerivedFixtureError("real_derived_source_kind_required")
    if fixture.get("real_derived") is not True:
        raise RealDerivedFixtureError("real_derived_fixture_required")
    if fixture.get("dataset_id") != REAL_DERIVED_DATASET_ID:
        raise RealDerivedFixtureError("real_derived_dataset_id_required")
    if fixture.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise RealDerivedFixtureError("fixture_schema_version_invalid")
    if fixture.get("source_type") != "published_kb_product_structured_fields":
        raise RealDerivedFixtureError("real_derived_source_type_invalid")
    if not _is_sha256(fixture.get("source_snapshot_hash")):
        raise RealDerivedFixtureError("source_snapshot_hash_required")
    if not sanitize_text(fixture.get("sanitization_version")):
        raise RealDerivedFixtureError("sanitization_version_required")
    if fixture.get("query_only") is not True:
        raise RealDerivedFixtureError("source_query_only_required")
    if fixture.get("source_database_mutated") is not False:
        raise RealDerivedFixtureError("source_database_mutation_detected")
    privacy = scan_fixture_privacy(fixture)
    if not privacy.get("passed"):
        raise RealDerivedFixtureError("fixture_privacy_scan_failed")
    expected_hash = _canonical_hash(fixture)
    for field in (
        "dataset_id", "dataset_version", "schema_version", "source_kind",
        "real_derived", "source_type", "source_snapshot_hash",
        "sanitization_version", "query_only", "source_database_mutated",
    ):
        if manifest.get(field) != fixture.get(field):
            raise RealDerivedFixtureError(f"manifest_{field}_mismatch")
    if manifest.get("qualification") != fixture.get("qualification"):
        raise RealDerivedFixtureError("manifest_qualification_mismatch")
    qualification = fixture.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("passed") is not True:
        raise RealDerivedFixtureError("fixture_qualification_failed")
    if manifest.get("fixture_sha256") != expected_hash:
        raise RealDerivedFixtureError("fixture_hash_mismatch")
    for product in fixture.get("products") or []:
        for fact in product.get("facts") or []:
            if not _is_sha256(fact.get("provenance_hash")):
                raise RealDerivedFixtureError("fact_provenance_hash_invalid")
    manifest_privacy = manifest.get("privacy_scan") if isinstance(manifest.get("privacy_scan"), dict) else {}
    if manifest_privacy.get("passed") is not True:
        raise RealDerivedFixtureError("manifest_privacy_scan_failed")
    return fixture


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.stat().st_size == 0:
        raise RealDerivedFixtureError("source_database_unavailable")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise RealDerivedFixtureError("source_database_not_query_only")
    return connection


def _database_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value or "").strip().lower()))


def _table_fingerprint(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return {"table": table, "exists": False, "row_count": 0, "schema_hash": ""}
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    schema_hash = hashlib.sha256("|".join(columns).encode("utf-8")).hexdigest()
    return {
        "table": table,
        "exists": True,
        "row_count": int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]),
        "schema_hash": schema_hash,
    }


def source_inventory(source_database: str | Path) -> dict[str, Any]:
    """Return only metadata and eligibility counts from a query-only source."""
    path = Path(source_database).expanduser().resolve()
    connection = _read_only_connection(path)
    try:
        before = [_table_fingerprint(connection, table) for table in ("kb_product", "kb_qa", "knowledge_entries", "knowledge_chunks")]
        if not next((row for row in before if row["table"] == "kb_product" and row["exists"]), None):
            raise RealDerivedFixtureError("kb_product_table_missing")
        rows = connection.execute(
            "SELECT id, i_id, sku_list_json, specs_json, logistics_json, warranty_json "
            "FROM kb_product WHERE lower(status) IN ('published', 'approved', 'reviewed', 'verified') "
            "ORDER BY i_id"
        ).fetchall()
        counts: Counter[str] = Counter()
        product_count_by_type: Counter[str] = Counter()
        dimension_attributes: set[str] = set()
        products_with_facts = 0
        products_with_three_fact_types = 0
        identity_and_provenance_count = 0
        rejection_reasons: Counter[str] = Counter()
        field_inventory = {
            field: {"candidate_count": 0, "eligible_direct_fact_count": 0}
            for field in (*INVENTORY_FIELDS, *UNSUPPORTED_INVENTORY_FIELD_KEYS, "installation_asset_availability")
        }
        for row in rows:
            profile = _profile_from_row(row)
            facts = _exportable_facts(profile)
            if facts:
                products_with_facts += 1
            if len({fact["fact_type"] for fact in facts}) >= MINIMUM_FACT_TYPE_COUNT:
                products_with_three_fact_types += 1
            for fact in facts:
                fact_type = fact["fact_type"]
                counts[fact_type] += 1
                field = "material_composition" if fact_type == "material" else fact_type
                if field in field_inventory:
                    field_inventory[field]["eligible_direct_fact_count"] += 1
                if fact.get("provenance_hash") and (sanitize_text(profile.get("i_id")) or any(
                    sanitize_text(item.get("sku_code")) for item in profile.get("sku_list") or [] if isinstance(item, dict)
                )):
                    identity_and_provenance_count += 1
                if fact_type == "dimensions":
                    attribute = sanitize_text(fact.get("attribute_key"))
                    if attribute:
                        dimension_attributes.add(attribute)
            exported_types = {fact["fact_type"] for fact in facts}
            for fact_type in exported_types:
                product_count_by_type[fact_type] += 1
            for field, fact_type in INVENTORY_FIELDS.items():
                candidates = build_product_spec_evidence_candidates(profile, requested_fact_type=fact_type)
                if candidates:
                    field_inventory[field]["candidate_count"] += 1
                if fact_type not in exported_types and candidates:
                    rejection_reasons["placeholder_conflict_or_field_contract"] += 1
            mappings = [profile.get("specs") or {}, profile.get("logistics") or {}, profile.get("warranty") or {}]
            available_keys = {
                str(key).lower()
                for mapping in mappings if isinstance(mapping, dict)
                for key, value in mapping.items() if value not in (None, "", [], {}, "-")
            }
            for field, aliases in UNSUPPORTED_INVENTORY_FIELD_KEYS.items():
                if any(alias in available_keys for alias in aliases):
                    field_inventory[field]["candidate_count"] += 1
                    rejection_reasons["formal_protocol_not_supported"] += 1
            if "install_videos" in available_keys:
                field_inventory["installation_asset_availability"]["candidate_count"] += 1
                rejection_reasons["media_availability_is_not_product_fact"] += 1
        after = [_table_fingerprint(connection, table) for table in ("kb_product", "kb_qa", "knowledge_entries", "knowledge_chunks")]
        return sanitize_obj({
            "source_database": {"path_form": "explicit_source_database", "sha256": _database_hash(path), "bytes": path.stat().st_size},
            "query_only": True,
            "tables_before": before,
            "tables_after": after,
            "published_product_count": len(rows),
            "eligible_fact_count_by_type": dict(sorted(counts.items())),
            "eligible_product_count_by_type": dict(sorted(product_count_by_type.items())),
            "eligible_product_count": products_with_facts,
            "eligible_fact_count": sum(counts.values()),
            "products_with_at_least_three_fact_types": products_with_three_fact_types,
            "identity_and_provenance_eligible_fact_count": identity_and_provenance_count,
            "requested_field_inventory": field_inventory,
            "rejection_reason_distribution": dict(sorted(rejection_reasons.items())),
            "dimension_attribute_keys": sorted(dimension_attributes),
            "dimension_attribute_coverage_complete": len(dimension_attributes) >= 2,
            "source_database_mutated": before != after,
        })
    finally:
        connection.close()


def build_real_derived_fixture(
    source_database: str | Path,
    *,
    pseudonymization_key: str,
    limit_products: int = 20,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a deterministic, privacy-checked fixture from published structured facts."""
    if not sanitize_text(pseudonymization_key):
        raise RealDerivedFixtureError("pseudonymization_key_required")
    path = Path(source_database).expanduser().resolve()
    connection = _read_only_connection(path)
    try:
        before = [_table_fingerprint(connection, table) for table in ("kb_product", "kb_qa", "knowledge_entries", "knowledge_chunks")]
        rows = connection.execute(
            "SELECT id, i_id, sku_list_json, specs_json, logistics_json, warranty_json "
            "FROM kb_product WHERE lower(status) IN ('published', 'approved', 'reviewed', 'verified') "
            "ORDER BY i_id"
        ).fetchall()
        eligible_products: list[tuple[int, sqlite3.Row, list[dict[str, Any]]]] = []
        for index, row in enumerate(rows):
            facts = _exportable_facts(_profile_from_row(row))
            if len(facts) < MINIMUM_FACTS_PER_PRODUCT:
                continue
            eligible_products.append((index, row, facts))

        selected: list[tuple[int, sqlite3.Row, list[dict[str, Any]]]] = []
        selected_indexes: set[int] = set()
        covered_fact_types: set[str] = set()
        for fact_type in LOW_RISK_FACT_TYPES:
            if fact_type in covered_fact_types or len(selected) >= limit_products:
                continue
            candidate = next((
                item for item in eligible_products
                if item[0] not in selected_indexes
                and fact_type in {fact["fact_type"] for fact in item[2]}
            ), None)
            if candidate is None:
                continue
            selected.append(candidate)
            selected_indexes.add(candidate[0])
            covered_fact_types.update(fact["fact_type"] for fact in candidate[2])

        for candidate in eligible_products:
            if candidate[0] in selected_indexes or len(selected) >= limit_products:
                continue
            selected.append(candidate)
            selected_indexes.add(candidate[0])
            covered_fact_types.update(fact["fact_type"] for fact in candidate[2])
            if (
                len(selected) >= MINIMUM_PRODUCT_COUNT
                and sum(len(item[2]) for item in selected) >= MINIMUM_TOTAL_FACTS
                and len(covered_fact_types) >= MINIMUM_FACT_TYPE_COUNT
            ):
                break

        products: list[dict[str, Any]] = []
        for _index, row, facts in sorted(selected, key=lambda item: item[0]):
            identity = _pseudonymous_identity(row, pseudonymization_key)
            products.append({"identity": identity, "facts": facts})
        if not products:
            raise RealDerivedFixtureError("no_eligible_real_derived_products")
        fact_types = Counter(fact["fact_type"] for product in products for fact in product["facts"])
        qualification = {
            "minimum_product_count": MINIMUM_PRODUCT_COUNT,
            "minimum_facts_per_product": MINIMUM_FACTS_PER_PRODUCT,
            "minimum_total_fact_count": MINIMUM_TOTAL_FACTS,
            "minimum_fact_type_count": MINIMUM_FACT_TYPE_COUNT,
            "product_count": len(products),
            "fact_count": sum(fact_types.values()),
            "fact_type_count": len(fact_types),
        }
        qualification["passed"] = bool(
            qualification["product_count"] >= MINIMUM_PRODUCT_COUNT
            and qualification["fact_count"] >= MINIMUM_TOTAL_FACTS
            and qualification["fact_type_count"] >= MINIMUM_FACT_TYPE_COUNT
            and all(len(product["facts"]) >= MINIMUM_FACTS_PER_PRODUCT for product in products)
        )
        fixture = {
            "dataset_id": REAL_DERIVED_DATASET_ID,
            "dataset_version": "1.0.0",
            "schema_version": FIXTURE_SCHEMA_VERSION,
            "source_kind": REAL_DERIVED_SOURCE_KIND,
            "real_derived": True,
            "sanitization_version": "hmac-sha256-v1",
            "source_snapshot_hash": _database_hash(path),
            "source_type": "published_kb_product_structured_fields",
            "query_only": True,
            "source_database_mutated": False,
            "qualification": qualification,
            "products": products,
            "negative_controls": [
                {"kind": "identity_mismatch", "expected_rejection_reason": "product_identity_mismatch"},
                {"kind": "review_state_insufficient", "expected_rejection_reason": "review_status_missing"},
                {"kind": "reference_only", "expected_rejection_reason": "reference_only"},
                {"kind": "service_action", "expected_rejection_reason": "non_factual_role"},
                {"kind": "media_reference", "expected_rejection_reason": "non_factual_role"},
                {"kind": "blocked_high_risk", "expected_rejection_reason": "gate_not_allowed"},
                {"kind": "conflicting_value", "expected_rejection_reason": "conflicting_evidence"},
            ],
        }
        privacy = scan_fixture_privacy(fixture)
        if not privacy["passed"]:
            raise RealDerivedFixtureError("fixture_privacy_scan_failed")
        after = [_table_fingerprint(connection, table) for table in ("kb_product", "kb_qa", "knowledge_entries", "knowledge_chunks")]
        if before != after:
            raise RealDerivedFixtureError("source_database_mutation_detected")
        dimension_attributes = sorted({
            fact["attribute_key"] for product in products for fact in product["facts"]
            if fact["fact_type"] == "dimensions" and fact["attribute_key"]
        })
        manifest = {
            "dataset_id": fixture["dataset_id"],
            "dataset_version": fixture["dataset_version"],
            "schema_version": fixture["schema_version"],
            "source_kind": fixture["source_kind"],
            "real_derived": fixture["real_derived"],
            "source_type": fixture["source_type"],
            "source_snapshot_hash": fixture["source_snapshot_hash"],
            "sanitization_version": fixture["sanitization_version"],
            "query_only": fixture["query_only"],
            "product_count": len(products),
            "fact_count": sum(fact_types.values()),
            "fact_type_counts": dict(sorted(fact_types.items())),
            "dimension_attribute_keys": dimension_attributes,
            "dimension_attribute_coverage_complete": len(dimension_attributes) >= 2,
            "qualification": qualification,
            "fixture_sha256": _canonical_hash(fixture),
            "privacy_scan": privacy,
            "source_database_mutated": False,
        }
        return fixture, manifest
    finally:
        connection.close()


def scan_fixture_privacy(payload: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    for path, text in _walk_strings(payload):
        if any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS):
            findings.append(path)
    prohibited = {"product_name", "title", "url", "order_id", "customer", "row_id", "source_id"}
    for product in payload.get("products") or []:
        identity = product.get("identity") if isinstance(product, dict) else {}
        if isinstance(identity, dict) and prohibited.intersection(identity):
            findings.append("products.identity.prohibited_field")
    return {"passed": not findings, "finding_count": len(findings), "findings": sorted(set(findings))}


def _profile_from_row(row: sqlite3.Row) -> dict[str, Any]:
    def load(name: str, default: Any):
        try:
            value = json.loads(row[name] or json.dumps(default))
            return value if isinstance(value, type(default)) else default
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return default
    return {
        "product_id": row["id"] if "id" in row.keys() else "",
        "i_id": sanitize_text(row["i_id"]),
        "product_name": "",
        "sku_list": load("sku_list_json", []),
        "specs": load("specs_json", {}),
        "logistics": load("logistics_json", {}),
        "warranty": load("warranty_json", {}),
    }


def _exportable_facts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for fact_type in LOW_RISK_FACT_TYPES:
        candidates = build_product_spec_evidence_candidates(profile, requested_fact_type=fact_type)
        if len(candidates) != 1:
            continue
        candidate = candidates[0]
        keys = [sanitize_text(item) for item in candidate.get("source_field_keys") or [] if sanitize_text(item)]
        if fact_type == "dimensions" and any(_is_packaging_field(key) for key in keys):
            # A mixed product/packaging candidate cannot safely demonstrate a
            # product-dimension claim, even in a supervisor-only fixture.
            continue
        attribute = _attribute_key(fact_type, keys)
        value = sanitize_text(candidate.get("value"))
        if not value or _contains_sensitive(value):
            continue
        if is_placeholder_evidence_text(value):
            # Placeholder values are not reviewable product truth and must not
            # be exported as positive-evidence fixtures.
            continue
        origin = "|".join((sanitize_text(profile.get("i_id")), fact_type, attribute, value))
        facts.append({
            "evidence_uid": "real-" + hashlib.sha256(origin.encode("utf-8")).hexdigest()[:20],
            "fact_type": fact_type,
            "attribute_key": attribute,
            "evidence_role": "product_fact_direct",
            "review_status": "published",
            "direct_answer_allowed": True,
            "content": value,
            "source_field_keys": keys,
            "provenance_hash": hashlib.sha256(origin.encode("utf-8")).hexdigest(),
            "expected_admission_result": "admitted",
        })
    return facts


def _attribute_key(fact_type: str, field_keys: list[str]) -> str:
    if fact_type != "dimensions":
        return fact_type
    attributes = sorted(_dimension_attributes(field_keys))
    return attributes[0] if len(attributes) == 1 else ""


def _dimension_attributes(field_keys: list[str]) -> set[str]:
    aliases = {
        "width": ("width", "宽"), "height": ("height", "高"), "length": ("length", "长"),
        "depth": ("depth", "深"), "diameter": ("diameter", "直径"), "thickness": ("thickness", "厚"),
    }
    result = set()
    for key in field_keys:
        text = key.lower()
        for attribute, terms in aliases.items():
            if any(term.lower() in text for term in terms):
                result.add(attribute)
    return result


def _is_packaging_field(field_key: str) -> bool:
    value = field_key.lower()
    return any(token in value for token in ("carton", "package", "packaging", "包装", "外箱"))


def _pseudonymous_identity(row: sqlite3.Row, key: str) -> dict[str, str]:
    raw_iid = sanitize_text(row["i_id"])
    try:
        sku_rows = json.loads(row["sku_list_json"] or "[]")
    except json.JSONDecodeError:
        sku_rows = []
    raw_sku = next((sanitize_text(item.get("sku_code")) for item in sku_rows if isinstance(item, dict) and sanitize_text(item.get("sku_code"))), "")
    return {
        "i_id": "fixture-iid-" + _hmac_token(key, raw_iid),
        "sku_code": "fixture-sku-" + _hmac_token(key, raw_sku or raw_iid),
    }


def _hmac_token(key: str, value: str) -> str:
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()[:18]


def _contains_sensitive(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SENSITIVE_PATTERNS)


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _walk_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")
