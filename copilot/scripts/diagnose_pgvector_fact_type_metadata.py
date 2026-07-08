"""Diagnose pgvector fact-type metadata normalization gaps."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import init_db  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402
from app.services.fact_type_metadata_normalizer import normalize_pgvector_fact_type_metadata  # noqa: E402
from app.services.pgvector_retriever_service import PgVectorRetrieverService, pgvector_config_from_env  # noqa: E402


SUSPICIOUS_FACT_TYPES = {"", "unknown", "other", "general", "generic", "__empty__"}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata") or {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def _preview(row: dict[str, Any]) -> str:
    return sanitize_text(row.get("chunk_text"))[:140]


def _sample(row: dict[str, Any], normalized) -> dict[str, Any]:
    return {
        "source_chunk_id": sanitize_text(row.get("source_chunk_id")),
        "source_type": sanitize_text(row.get("source_type")),
        "original_query_fact_type": normalized.original_query_fact_type,
        "recommended_query_fact_type": normalized.normalized_query_fact_type,
        "evidence_role": sanitize_text(row.get("evidence_role")),
        "recommended_evidence_role": normalized.normalized_evidence_role,
        "product_identity": {
            "i_id": sanitize_text(row.get("i_id")),
            "sku_code": sanitize_text(row.get("sku_code")),
            "product_title": sanitize_text(row.get("product_title")),
        },
        "text_preview": _preview(row),
        "reason": normalized.reason,
    }


def _append_sample(samples: dict[str, list[dict[str, Any]]], key: str, sample: dict[str, Any]) -> None:
    if len(samples[key]) < 5:
        samples[key].append(sample)


def run(*, json_output: str = "", limit: int = 0, service: PgVectorRetrieverService | None = None) -> dict[str, Any]:
    service = service or PgVectorRetrieverService()
    check = service.check()
    if not check.get("pgvector_available"):
        result = {
            "config": pgvector_config_from_env(),
            "pgvector_available": False,
            "error": check.get("error") or "pgvector_unavailable",
        }
        _write_json(json_output, result)
        return sanitize_obj(result)

    rows = service.fetch_rows_for_metadata_normalization(limit=limit)
    source_counter: Counter[str] = Counter()
    role_counter: Counter[str] = Counter()
    fact_counter: Counter[str] = Counter()
    fact_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    role_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    recommended_counter: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mismatch_count = 0
    suspicious_count = 0
    unknown_count = 0
    recommended_count = 0
    high_risk_blocked_count = 0
    normalized_metadata_count = 0

    for row in rows:
        source = sanitize_text(row.get("source_type")) or "__empty__"
        role = sanitize_text(row.get("evidence_role")) or "__empty__"
        fact = sanitize_text(row.get("query_fact_type")) or "__empty__"
        source_counter[source] += 1
        role_counter[role] += 1
        fact_counter[fact] += 1
        fact_by_source[source][fact] += 1
        role_by_source[source][role] += 1
        metadata = _metadata(row)
        if sanitize_text(metadata.get("normalized_query_fact_type")):
            normalized_metadata_count += 1
        normalized = normalize_pgvector_fact_type_metadata(row)
        sample = _sample(row, normalized)
        if normalized.changed:
            recommended_count += 1
            recommended_counter[normalized.reason] += 1
            _append_sample(samples, "recommended_normalization", sample)
        if normalized.high_risk_blocked:
            high_risk_blocked_count += 1
            _append_sample(samples, "high_risk_blocked", sample)
        if fact in SUSPICIOUS_FACT_TYPES:
            suspicious_count += 1
            unknown_count += 1
            _append_sample(samples, "unknown_or_generic_fact_type", sample)
        if fact != (sanitize_text(metadata.get("normalized_query_fact_type")) or fact) and metadata.get("normalized_query_fact_type"):
            mismatch_count += 1
            _append_sample(samples, "mismatch", sample)
        if fact == "accessories" or normalized.normalized_query_fact_type in {"accessories", "accessory_availability", "accessory_usage"}:
            _append_sample(samples, "rows_with_accessories_like_fact_type", sample)
        if fact == "installation" or normalized.normalized_query_fact_type in {"installation", "structure_function"}:
            _append_sample(samples, "rows_with_installation_like_fact_type", sample)
        if fact in {"material", "material_safety"} or normalized.normalized_query_fact_type in {"material", "material_safety", "certification_report"}:
            _append_sample(samples, "rows_with_material_like_fact_type", sample)
        if fact in {"dimensions", "space_fit"} or normalized.normalized_query_fact_type in {"dimensions", "space_fit"}:
            _append_sample(samples, "rows_with_dimensions_like_fact_type", sample)
        if fact in {"stock_shipping", "delivery", "shipping"} or normalized.normalized_query_fact_type == "stock_shipping":
            _append_sample(samples, "rows_with_stock_shipping_like_fact_type", sample)
        if fact in {"aftersales", "aftersales_policy"} or normalized.normalized_query_fact_type in {"refund_policy", "replacement_policy", "return_pickup", "aftersales_policy"}:
            _append_sample(samples, "rows_with_aftersales_like_fact_type", sample)

    result = {
        "config": pgvector_config_from_env(),
        "pgvector_available": True,
        "total_rows": len(rows),
        "mismatch_count": mismatch_count,
        "suspicious_fact_type_count": suspicious_count,
        "unknown_or_generic_fact_type_count": unknown_count,
        "source_type_distribution": dict(source_counter.most_common()),
        "evidence_role_distribution": dict(role_counter.most_common()),
        "fact_type_distribution": dict(fact_counter.most_common()),
        "fact_type_by_source_type": {key: dict(value.most_common()) for key, value in fact_by_source.items()},
        "evidence_role_by_source_type": {key: dict(value.most_common()) for key, value in role_by_source.items()},
        "normalized_query_fact_type_metadata_count": normalized_metadata_count,
        "recommended_normalization_count": recommended_count,
        "recommended_normalization_reason_counts": dict(recommended_counter.most_common()),
        "high_risk_blocked_count": high_risk_blocked_count,
        "samples": dict(samples),
    }
    result = sanitize_obj(result)
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Diagnose pgvector fact-type metadata normalization gaps.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(limit=args.limit, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("pgvector_available") else 2


if __name__ == "__main__":
    raise SystemExit(main())
