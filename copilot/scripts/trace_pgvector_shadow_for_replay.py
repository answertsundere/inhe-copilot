"""Trace pgvector shadow retrieval for replay turns without affecting formal RAG."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import statistics
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402
from app.services.fact_type_alias_service import is_high_risk_fact_type  # noqa: E402
from app.services.pgvector_retriever_service import PgVectorRetrieverService  # noqa: E402
from scripts.compare_sqlite_pgvector_retrieval import (  # noqa: E402
    _candidate_role,
    _has_direct_answerable,
    _ids,
    _latest_run_uid,
    _load_traces,
    _query_fact_type,
    _retrieve_pgvector,
    _role_counts,
    _sidecar,
)


FILTER_MODES = ("strict", "no_fact_type", "product_only", "no_product", "fact_type_alias")
UNKNOWN_MEDIA_ROLES = {"", "unknown", "other", "image", "product_photo", "sku_image"}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _top_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        value = str(row.get(field) or "").strip() or "__empty__"
        counter[value] += 1
    return dict(counter.most_common(5))


def _top_candidates(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows[:limit]:
        candidates.append({
            "id": str(row.get("chunk_id") or row.get("source_chunk_id") or ""),
            "source_type": str(row.get("source_type") or ""),
            "evidence_role": str(row.get("evidence_role") or ""),
            "media_role": str(row.get("media_role") or ""),
            "query_fact_type": str(row.get("fact_type") or row.get("query_fact_type") or ""),
            "fact_type_alias_used": bool(row.get("fact_type_alias_used")),
            "alias_requested": str(row.get("alias_requested") or ""),
            "alias_expanded": row.get("alias_expanded") or [],
            "alias_candidate_matched": str(row.get("alias_candidate_matched") or ""),
            "alias_direct_answer_safe": row.get("alias_direct_answer_safe"),
            "score": row.get("score") or row.get("vector_score") or 0,
            "preview": sanitize_text(str(row.get("chunk_text") or ""))[:120],
        })
    return candidates


def _mode_result(rows: list[dict[str, Any]], latency_ms: float, error: str = "") -> dict[str, Any]:
    role_counts = _role_counts(rows)
    return {
        "candidate_count": len(rows),
        "latency_ms": latency_ms,
        "error": error,
        "top_source_types": _top_counts(rows, "source_type"),
        "top_evidence_roles": _top_counts(rows, "evidence_role"),
        "fact_type_alias_used_count": sum(1 for row in rows if row.get("fact_type_alias_used")),
        "alias_direct_answer_safe_count": sum(1 for row in rows if row.get("alias_direct_answer_safe") is True),
        "product_fact_direct_count": role_counts["product_fact_direct"],
        "faq_direct_count": role_counts["faq_direct"],
        "service_action_count": role_counts["service_action"],
        "media_reference_count": role_counts["media_reference"],
        "direct_answerable_count": 1 if _has_direct_answerable(rows) else 0,
        "top_candidates": _top_candidates(rows),
    }


def _media_reference_unknown_role_count(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        if _candidate_role(row) != "media_reference":
            continue
        media_role = str(row.get("media_role") or "").strip()
        if media_role in UNKNOWN_MEDIA_ROLES:
            total += 1
    return total


def _exclusion_reason(
    *,
    sidecar: dict[str, str],
    query_fact_type: str,
    query_embedding: list[float],
    mode_results: dict[str, dict[str, Any]],
    pgvector_available: bool,
    error: str = "",
) -> str:
    if not pgvector_available:
        return "pgvector_unavailable"
    if error:
        return error
    if not query_embedding:
        return "query_embedding_failed"
    if not (sidecar.get("i_id") or sidecar.get("sku_code") or sidecar.get("product_title")):
        return "no_product_identity"
    if mode_results.get("strict", {}).get("candidate_count", 0) > 0:
        return "strict_hit"
    if not query_fact_type:
        return "fact_type_filter_empty"
    if mode_results.get("no_fact_type", {}).get("candidate_count", 0) > 0:
        return "fact_type_filter_empty"
    if mode_results.get("product_only", {}).get("candidate_count", 0) > 0:
        return "evidence_role_filter_empty"
    if mode_results.get("no_product", {}).get("candidate_count", 0) > 0:
        return "no_product_identity"
    return "no_embedding"


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 2)


def trace_pgvector_shadow(
    *,
    run_uid: str = "",
    limit: int = 0,
    json_output: str = "",
    pg_service: PgVectorRetrieverService | None = None,
    embedding_provider=None,
    db_factory=SessionLocal,
) -> dict[str, Any]:
    db = db_factory()
    try:
        resolved_run_uid = sanitize_text(run_uid) or _latest_run_uid(db)
        traces = _load_traces(db, resolved_run_uid, limit)
    finally:
        db.close()

    pg_service = pg_service or PgVectorRetrieverService()
    embedding_provider = embedding_provider or EmbeddingService.get_embeddings
    pg_check = pg_service.check()
    pgvector_available = bool(pg_check.get("pgvector_available"))
    rows: list[dict[str, Any]] = []
    filter_reason_counts: Counter[str] = Counter()
    source_type_counter: Counter[str] = Counter()
    query_fact_type_counter: Counter[str] = Counter()
    mode_latency: dict[str, list[float]] = defaultdict(list)
    mode_source_distribution: dict[str, Counter[str]] = {mode: Counter() for mode in FILTER_MODES}
    searchable_trace_count = 0
    pgvector_available_count = 0
    pgvector_error_count = 0
    strict_hit_count = 0
    no_fact_type_helped_count = 0
    product_only_helped_count = 0
    no_product_only_helped_count = 0
    pgvector_product_fact_direct_count = 0
    pgvector_faq_direct_count = 0
    pgvector_service_action_count = 0
    pgvector_media_reference_count = 0
    pgvector_direct_answerable_count = 0
    media_reference_with_unknown_role_count = 0
    fact_type_alias_helped_count = 0
    high_risk_alias_blocked_count = 0

    for trace in traces:
        query_text = sanitize_text(getattr(trace, "buyer_message", "") or "")
        query_fact_type = _query_fact_type(trace)
        sidecar = _sidecar(trace)
        if query_fact_type:
            query_fact_type_counter[query_fact_type] += 1
        if not query_text:
            filter_reason_counts["query_embedding_failed"] += 1
            continue
        searchable_trace_count += 1
        query_embedding: list[float] = []
        embedding_error = ""
        if pgvector_available:
            try:
                embedding = embedding_provider([query_text])
                query_embedding = embedding[0] if embedding else []
            except Exception:
                embedding_error = "query_embedding_failed"
                query_embedding = []
        mode_results: dict[str, dict[str, Any]] = {}
        raw_mode_rows: dict[str, list[dict[str, Any]]] = {}
        if pgvector_available and query_embedding:
            pgvector_available_count += 1
            for mode in FILTER_MODES:
                mode_rows, latency_ms, timed_out = _retrieve_pgvector(
                    pg_service,
                    query_text=query_text,
                    query_embedding=query_embedding,
                    sidecar=sidecar,
                    query_fact_type=query_fact_type,
                    mode=mode,
                )
                raw_mode_rows[mode] = mode_rows
                mode_results[mode] = _mode_result(mode_rows, latency_ms, "timeout" if timed_out else "")
                mode_latency[mode].append(latency_ms)
                for row in mode_rows:
                    mode_source_distribution[mode][str(row.get("source_type") or "__empty__")] += 1
        else:
            if not pgvector_available or embedding_error:
                pgvector_error_count += 1
            for mode in FILTER_MODES:
                mode_results[mode] = _mode_result([], 0.0, pg_check.get("error") or embedding_error)

        strict_rows = raw_mode_rows.get("strict", [])
        role_counts = _role_counts(strict_rows)
        pgvector_product_fact_direct_count += role_counts["product_fact_direct"]
        pgvector_faq_direct_count += role_counts["faq_direct"]
        pgvector_service_action_count += role_counts["service_action"]
        pgvector_media_reference_count += role_counts["media_reference"]
        media_reference_with_unknown_role_count += _media_reference_unknown_role_count(strict_rows)
        if _has_direct_answerable(strict_rows):
            pgvector_direct_answerable_count += 1
        for row in strict_rows:
            source_type_counter[str(row.get("source_type") or "__empty__")] += 1
        strict_count = mode_results["strict"]["candidate_count"]
        no_fact_type_count = mode_results["no_fact_type"]["candidate_count"]
        product_only_count = mode_results["product_only"]["candidate_count"]
        no_product_count = mode_results["no_product"]["candidate_count"]
        alias_used = any(row.get("fact_type_alias_used") for row in strict_rows)
        if strict_count > 0:
            strict_hit_count += 1
            if alias_used:
                fact_type_alias_helped_count += 1
        elif no_fact_type_count > 0:
            no_fact_type_helped_count += 1
        elif product_only_count > 0:
            product_only_helped_count += 1
        elif no_product_count > 0:
            no_product_only_helped_count += 1
        if is_high_risk_fact_type(query_fact_type) and strict_count == 0 and no_fact_type_count > 0:
            high_risk_alias_blocked_count += 1

        reason = _exclusion_reason(
            sidecar=sidecar,
            query_fact_type=query_fact_type,
            query_embedding=query_embedding,
            mode_results=mode_results,
            pgvector_available=pgvector_available,
            error=embedding_error,
        )
        filter_reason_counts[reason] += 1
        rows.append({
            "case_uid": sanitize_text(getattr(trace, "case_uid", "") or ""),
            "turn_uid": sanitize_text(getattr(trace, "turn_uid", "") or ""),
            "query_fact_type": query_fact_type,
            "buyer_message_preview": query_text[:120],
            "sidecar": sidecar,
            "pgvector_shadow": {
                "enabled": True,
                "available": pgvector_available,
                "latency_ms": mode_results.get("strict", {}).get("latency_ms", 0.0),
                "error": pg_check.get("error") or embedding_error,
                "filter_mode_results": mode_results,
                "filter_exclusion_reason": reason,
            },
            "pgvector_top_ids": _ids(strict_rows)[:5],
        })

    avg_latency = {mode: _mean(values) for mode, values in mode_latency.items()}
    p95_latency = {mode: _p95(values) for mode, values in mode_latency.items()}
    summary = {
        "run_uid": resolved_run_uid,
        "trace_count": len(traces),
        "searchable_trace_count": searchable_trace_count,
        "pgvector_available_count": pgvector_available_count,
        "pgvector_error_count": pgvector_error_count,
        "strict_hit_count": strict_hit_count,
        "no_fact_type_helped_count": no_fact_type_helped_count,
        "product_only_helped_count": product_only_helped_count,
        "no_product_only_helped_count": no_product_only_helped_count,
        "pgvector_product_fact_direct_count": pgvector_product_fact_direct_count,
        "pgvector_faq_direct_count": pgvector_faq_direct_count,
        "pgvector_service_action_count": pgvector_service_action_count,
        "pgvector_media_reference_count": pgvector_media_reference_count,
        "pgvector_direct_answerable_count": pgvector_direct_answerable_count,
        "media_reference_with_unknown_role_count": media_reference_with_unknown_role_count,
        "fact_type_alias_helped_count": fact_type_alias_helped_count,
        "high_risk_alias_blocked_count": high_risk_alias_blocked_count,
        "filter_exclusion_reason_counts": dict(filter_reason_counts.most_common()),
        "avg_latency_ms_by_mode": avg_latency,
        "p95_latency_ms_by_mode": p95_latency,
        "strict_source_type_distribution": dict(source_type_counter.most_common()),
        "query_fact_type_distribution": dict(query_fact_type_counter.most_common()),
        "per_mode_source_type_distribution": {
            mode: dict(counter.most_common()) for mode, counter in mode_source_distribution.items()
        },
        "pgvector_available": pgvector_available,
        "pgvector_error": pg_check.get("error") or "",
        "notes": [
            "Shadow trace is read-only and does not affect formal RAG, selected evidence, reply_blocks, or can_send.",
            "service_action is a customer-service action fallback, not product fact evidence.",
            "media_reference is diagnostic reference only and must still pass media role and reply block contracts before delivery.",
        ],
    }
    result = sanitize_obj({"summary": summary, "rows": rows})
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Trace pgvector shadow retrieval for replay turns.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = trace_pgvector_shadow(run_uid=args.run_uid, limit=args.limit, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("summary", {}).get("pgvector_available") else 2


if __name__ == "__main__":
    raise SystemExit(main())
