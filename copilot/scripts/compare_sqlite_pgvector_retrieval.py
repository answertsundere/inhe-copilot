"""Shadow compare current SQLite retrieval against pgvector retrieval."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.eval_tables import EvalRun, EvalTrace  # noqa: E402
from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402
from app.services.fact_type_alias_service import (  # noqa: E402
    expand_fact_type_aliases,
    is_alias_safe_for_direct_answer,
    is_high_risk_fact_type,
)
from app.services.pgvector_retriever_service import PgVectorRetrieverService  # noqa: E402

SERVICE_ACTION_SOURCE_TYPES = ["generic_rule", "generic_rules", "response_templates"]
SERVICE_ACTION_EVIDENCE_ROLES = ["service_action", "fallback_only"]
FILTER_ABLATION_MODES = (
    "strict",
    "no_fact_type",
    "product_only",
    "no_product",
    "fact_type_alias",
    "service_action_merge",
)


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _query_fact_type(trace: EvalTrace) -> str:
    turn = trace.get_turn_understanding() or {}
    answer = trace.get_answer_trace() or {}
    raw = trace.get_raw_response() or {}
    return sanitize_text(
        trace.query_fact_type
        or turn.get("query_fact_type")
        or answer.get("query_fact_type")
        or raw.get("query_fact_type")
    )


def _sidecar(trace: EvalTrace) -> dict[str, str]:
    raw = trace.get_raw_response() or {}
    context = raw.get("copilot_context") if isinstance(raw.get("copilot_context"), dict) else {}
    sidecar = context.get("sidecar_context") if isinstance(context.get("sidecar_context"), dict) else {}
    if not sidecar:
        sidecar = raw.get("sidecar_context") if isinstance(raw.get("sidecar_context"), dict) else {}
    return {
        "product_title": sanitize_text(sidecar.get("product_title") or sidecar.get("product_name") or raw.get("product_name")),
        "sku_code": sanitize_text(sidecar.get("sku_code") or raw.get("sku_code")),
        "i_id": sanitize_text(sidecar.get("i_id") or raw.get("i_id")),
    }


def _load_traces(db, run_uid: str, limit: int) -> list[EvalTrace]:
    query = db.query(EvalTrace).filter(EvalTrace.run_uid == run_uid).order_by(EvalTrace.id.asc())
    if limit:
        query = query.limit(max(1, int(limit)))
    return query.all()


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for row in rows:
        raw = str(row.get("chunk_id") or row.get("source_chunk_id") or "")
        if raw.startswith("pgvector:"):
            raw = raw.split(":", 1)[1]
        ids.append(raw)
    return [item for item in ids if item]


def _has_direct_answerable(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if _candidate_role(row) in {"product_fact_direct", "faq_direct"}:
            return True
    return False


def _candidate_role(row: dict[str, Any]) -> str:
    if row.get("alias_direct_answer_safe") is False:
        return "reference_only"
    evidence_role = str(row.get("evidence_role") or "").strip()
    source_type = str(row.get("source_type") or "").strip()
    if evidence_role in {"product_fact_direct", "faq_direct", "service_action", "fallback_only", "media_reference"}:
        return evidence_role
    if source_type in {"product_fact", "product_facts", "dingtalk_product_detail", "product_activity_rule", "manual"}:
        return "product_fact_direct"
    if source_type in {"faq", "kbqa"}:
        return "faq_direct"
    if source_type in {"generic_rule", "generic_rules", "response_templates", "aftersales_policy"}:
        return "service_action"
    if source_type == "media_asset":
        return "media_reference"
    if evidence_role in {"service_action", "fallback_only"}:
        return evidence_role
    if evidence_role == "media_reference":
        return "media_reference"
    return "reference_only"


def _role_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "product_fact_direct": 0,
        "faq_direct": 0,
        "service_action": 0,
        "media_reference": 0,
        "reference_only": 0,
    }
    for row in rows:
        role = _candidate_role(row)
        counts[role if role in counts else "reference_only"] += 1
    return counts


def _annotate_alias_candidate(row: dict[str, Any], *, requested_fact_type: str, alias_values: list[str]) -> dict[str, Any]:
    candidate = dict(row)
    candidate_fact_type = str(candidate.get("fact_type") or candidate.get("query_fact_type") or "")
    alias_used = bool(candidate_fact_type and candidate_fact_type != requested_fact_type)
    candidate["fact_type_alias_used"] = alias_used
    candidate["alias_requested"] = requested_fact_type
    candidate["alias_expanded"] = alias_values
    candidate["alias_candidate_matched"] = candidate_fact_type
    candidate["alias_direct_answer_safe"] = is_alias_safe_for_direct_answer(
        requested_fact_type,
        candidate_fact_type,
        str(candidate.get("evidence_role") or ""),
        str(candidate.get("source_type") or ""),
    )
    return candidate


def _safe_alias_candidates(
    rows: list[dict[str, Any]],
    *,
    requested_fact_type: str,
    alias_values: list[str],
) -> list[dict[str, Any]]:
    candidates = [
        _annotate_alias_candidate(row, requested_fact_type=requested_fact_type, alias_values=alias_values)
        for row in rows
    ]
    return [row for row in candidates if row.get("alias_direct_answer_safe") is True]


def _service_action_fact_types(query_fact_type: str) -> list[str]:
    values = expand_fact_type_aliases(query_fact_type, context="retrieval")
    return values or ([query_fact_type] if query_fact_type else [])


def _retrieve_pgvector(
    pg_service: PgVectorRetrieverService,
    *,
    query_text: str,
    query_embedding: list[float],
    sidecar: dict[str, str],
    query_fact_type: str,
    mode: str,
) -> tuple[list[dict[str, Any]], float, bool]:
    started = time.perf_counter()
    timed_out = False
    try:
        if mode == "strict":
            rows = pg_service.retrieve(
                query_text=query_text,
                query_embedding=query_embedding,
                i_id=sidecar["i_id"],
                sku_code=sidecar["sku_code"],
                query_fact_type=query_fact_type,
                top_k=5,
            )
            if not rows and query_fact_type:
                alias_values = expand_fact_type_aliases(query_fact_type, context="retrieval")
                alias_only = [item for item in alias_values if item != query_fact_type]
                if alias_only:
                    alias_rows = pg_service.retrieve(
                        query_text=query_text,
                        query_embedding=query_embedding,
                        i_id=sidecar["i_id"],
                        sku_code=sidecar["sku_code"],
                        query_fact_types=alias_only,
                        top_k=5,
                    )
                    rows = _safe_alias_candidates(
                        alias_rows,
                        requested_fact_type=query_fact_type,
                        alias_values=alias_values,
                    )
        elif mode == "no_fact_type":
            rows = pg_service.retrieve(
                query_text=query_text,
                query_embedding=query_embedding,
                i_id=sidecar["i_id"],
                sku_code=sidecar["sku_code"],
                query_fact_type="",
                top_k=5,
            )
        elif mode == "product_only":
            rows = pg_service.retrieve(
                query_text=query_text,
                query_embedding=query_embedding,
                i_id=sidecar["i_id"],
                sku_code=sidecar["sku_code"],
                query_fact_type="",
                allowed_source_types=[],
                allowed_evidence_roles=[],
                top_k=5,
            )
        elif mode == "no_product":
            rows = pg_service.retrieve(
                query_text=query_text,
                query_embedding=query_embedding,
                i_id="",
                sku_code="",
                query_fact_type=query_fact_type,
                top_k=5,
                allow_broad_search=True,
            )
        elif mode == "fact_type_alias":
            alias_values = expand_fact_type_aliases(query_fact_type, context="retrieval")
            alias_only = [item for item in alias_values if item != query_fact_type]
            alias_rows = pg_service.retrieve(
                query_text=query_text,
                query_embedding=query_embedding,
                i_id=sidecar["i_id"],
                sku_code=sidecar["sku_code"],
                query_fact_types=alias_only,
                top_k=5,
            ) if alias_only else []
            rows = _safe_alias_candidates(
                alias_rows,
                requested_fact_type=query_fact_type,
                alias_values=alias_values,
            )
            rows = rows[:5]
        elif mode == "service_action_merge":
            rows = pg_service.retrieve(
                query_text=query_text,
                query_embedding=query_embedding,
                i_id="",
                sku_code="",
                query_fact_types=_service_action_fact_types(query_fact_type),
                allowed_source_types=SERVICE_ACTION_SOURCE_TYPES,
                allowed_evidence_roles=SERVICE_ACTION_EVIDENCE_ROLES,
                top_k=5,
                allow_broad_search=True,
            )
        else:
            rows = []
    except Exception:
        timed_out = True
        rows = []
    latency = round((time.perf_counter() - started) * 1000, 2)
    return rows, latency, timed_out


def _sqlite_source_chunk_ids(rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        raw = str(row.get("chunk_id") or "")
        if raw.isdigit():
            values.append(raw)
    return values


def _metadata_mismatches(sqlite_rows: list[dict[str, Any]], pg_rows_by_id: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for row in sqlite_rows:
        source_chunk_id = str(row.get("chunk_id") or "")
        if not source_chunk_id.isdigit() or source_chunk_id not in pg_rows_by_id:
            continue
        pg_row = pg_rows_by_id[source_chunk_id]
        checks = {
            "query_fact_type": (row.get("fact_type") or "", pg_row.get("query_fact_type") or ""),
            "source_type": (row.get("source_type") or "", pg_row.get("source_type") or ""),
        }
        for field, (sqlite_value, pg_value) in checks.items():
            if str(sqlite_value or "") and str(pg_value or "") and str(sqlite_value) != str(pg_value):
                mismatches.append({
                    "source_chunk_id": source_chunk_id,
                    "field": field,
                    "sqlite_value": str(sqlite_value),
                    "pgvector_value": str(pg_value),
                })
    return mismatches


def compare_retrieval(
    *,
    run_uid: str = "",
    limit: int = 0,
    json_output: str = "",
    sqlite_retriever=None,
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

    sqlite_retriever = sqlite_retriever or CurrentSQLiteRetriever()
    pg_service = pg_service or PgVectorRetrieverService()
    embedding_provider = embedding_provider or EmbeddingService.get_embeddings
    pg_check = pg_service.check()
    if not pg_check.get("pgvector_available"):
        result = sanitize_obj({
            "summary": {
                "run_uid": resolved_run_uid,
                "resolved_run_uid": resolved_run_uid,
                "pgvector_available": False,
                "extension_available": bool(pg_check.get("extension_available")),
                "compare_trace_count": 0,
                "sqlite_avg_latency_ms": 0.0,
                "pgvector_avg_latency_ms": 0.0,
                "pgvector_timeout_count": 0,
                "pgvector_direct_answerable_count": 0,
                "service_action_merge_candidate_count": 0,
                "service_action_merge_hit_count": 0,
                "service_action_merge_helped_count": 0,
                "service_action_merge_kept_as_fallback_count": 0,
                "overlap_count": 0,
                "pgvector_only_direct_candidates": 0,
                "pgvector_error": pg_check.get("error") or "pgvector_unavailable",
                "skipped_reason": "pgvector_unavailable",
            },
            "rows": [],
        })
        _write_json(json_output, result)
        return result
    rows: list[dict[str, Any]] = []
    sqlite_latencies: list[float] = []
    pg_latencies: list[float] = []
    pgvector_timeout_count = 0
    pgvector_direct_answerable_count = 0
    pgvector_product_fact_direct_count = 0
    pgvector_faq_direct_count = 0
    pgvector_service_action_count = 0
    pgvector_media_reference_count = 0
    overlap_total = 0
    pgvector_only_direct_candidates = 0
    missing_in_pgvector_count = 0
    metadata_mismatch_count = 0
    strict_empty_but_product_only_has_candidates_count = 0
    fact_type_alias_helped_count = 0
    high_risk_alias_blocked_count = 0
    service_action_merge_candidate_count = 0
    service_action_merge_hit_count = 0
    service_action_merge_helped_count = 0
    service_action_merge_kept_as_fallback_count = 0
    service_action_merge_fact_type_distribution: dict[str, int] = {}
    service_action_merge_source_type_distribution: dict[str, int] = {}
    service_action_merge_evidence_role_distribution: dict[str, int] = {}
    evidence_misuse_risk_samples: list[dict[str, Any]] = []

    for trace in traces:
        qft = _query_fact_type(trace)
        sidecar = _sidecar(trace)
        if not qft or not (sidecar["i_id"] or sidecar["sku_code"] or sidecar["product_title"]):
            continue
        query_text = sanitize_text(trace.buyer_message)
        if not query_text:
            continue
        started = time.perf_counter()
        sqlite_rows = sqlite_retriever.retrieve(
            query=query_text,
            product_scope=[sidecar["product_title"]] if sidecar["product_title"] else [],
            sku_scope=[sidecar["sku_code"] or sidecar["i_id"]] if (sidecar["sku_code"] or sidecar["i_id"]) else [],
            fact_type=qft,
            top_k=5,
        )
        sqlite_latency = round((time.perf_counter() - started) * 1000, 2)
        sqlite_latencies.append(sqlite_latency)
        pg_rows: list[dict[str, Any]] = []
        pg_latency = 0.0
        ablation: dict[str, dict[str, Any]] = {}
        sqlite_source_ids = _sqlite_source_chunk_ids(sqlite_rows)
        pg_rows_by_source_id = (
            pg_service.fetch_rows_by_source_ids(sqlite_source_ids)
            if sqlite_source_ids and hasattr(pg_service, "fetch_rows_by_source_ids")
            else {}
        )
        missing_ids = [item for item in sqlite_source_ids if item not in pg_rows_by_source_id]
        missing_in_pgvector_count += len(missing_ids)
        mismatches = _metadata_mismatches(sqlite_rows, pg_rows_by_source_id)
        metadata_mismatch_count += len(mismatches)
        if pg_check.get("pgvector_available"):
            embedding = embedding_provider([query_text])
            query_embedding = embedding[0] if embedding else []
            for mode in FILTER_ABLATION_MODES:
                mode_rows, mode_latency, mode_timed_out = _retrieve_pgvector(
                    pg_service,
                    query_text=query_text,
                    query_embedding=query_embedding,
                    sidecar=sidecar,
                    query_fact_type=qft,
                    mode=mode,
                )
                ablation[mode] = {
                    "candidate_count": len(mode_rows),
                    "direct_answerable": _has_direct_answerable(mode_rows),
                    "latency_ms": mode_latency,
                    "top_ids": _ids(mode_rows)[:3],
                }
                if mode_timed_out:
                    pgvector_timeout_count += 1
                if mode == "strict":
                    pg_rows = mode_rows
                    pg_latency = mode_latency
                if mode == "service_action_merge":
                    service_role_counts = _role_counts(mode_rows)
                    service_action_merge_candidate_count += len(mode_rows)
                    if mode_rows:
                        service_action_merge_hit_count += 1
                    if not ablation.get("strict", {}).get("candidate_count", 0) and mode_rows:
                        service_action_merge_helped_count += 1
                    service_action_merge_kept_as_fallback_count += service_role_counts["service_action"]
                    pgvector_service_action_count += service_role_counts["service_action"]
                    for row in mode_rows:
                        fact_type = str(row.get("fact_type") or row.get("query_fact_type") or "__empty__")
                        source_type = str(row.get("source_type") or "__empty__")
                        evidence_role = str(row.get("evidence_role") or "__empty__")
                        service_action_merge_fact_type_distribution[fact_type] = (
                            service_action_merge_fact_type_distribution.get(fact_type, 0) + 1
                        )
                        service_action_merge_source_type_distribution[source_type] = (
                            service_action_merge_source_type_distribution.get(source_type, 0) + 1
                        )
                        service_action_merge_evidence_role_distribution[evidence_role] = (
                            service_action_merge_evidence_role_distribution.get(evidence_role, 0) + 1
                        )
            if ablation.get("strict", {}).get("candidate_count", 0) == 0 and ablation.get("product_only", {}).get("candidate_count", 0) > 0:
                strict_empty_but_product_only_has_candidates_count += 1
            alias_helped = any(row.get("fact_type_alias_used") for row in pg_rows)
            if alias_helped or (
                ablation.get("strict", {}).get("candidate_count", 0) == 0
                and ablation.get("fact_type_alias", {}).get("candidate_count", 0) > 0
            ):
                fact_type_alias_helped_count += 1
            if (
                is_high_risk_fact_type(qft)
                and ablation.get("strict", {}).get("candidate_count", 0) == 0
                and ablation.get("no_fact_type", {}).get("candidate_count", 0) > 0
            ):
                high_risk_alias_blocked_count += 1
            pg_latencies.append(pg_latency)

        sqlite_ids = set(_ids(sqlite_rows))
        pg_ids = set(_ids(pg_rows))
        overlap = len(sqlite_ids & pg_ids)
        pg_only = pg_ids - sqlite_ids
        pg_direct = _has_direct_answerable(pg_rows)
        if pg_direct:
            pgvector_direct_answerable_count += 1
        role_counts = _role_counts(pg_rows)
        pgvector_product_fact_direct_count += role_counts["product_fact_direct"]
        pgvector_faq_direct_count += role_counts["faq_direct"]
        pgvector_service_action_count += role_counts["service_action"]
        pgvector_media_reference_count += role_counts["media_reference"]
        if pg_only and pg_direct:
            pgvector_only_direct_candidates += len(pg_only)
        overlap_total += overlap
        rows.append({
            "case_uid": trace.case_uid,
            "turn_uid": trace.turn_uid,
            "query_fact_type": qft,
            "buyer_message_preview": query_text[:120],
            "sidecar": sidecar,
            "sqlite_candidate_count": len(sqlite_rows),
            "pgvector_candidate_count": len(pg_rows),
            "sqlite_top_ids": list(sqlite_ids)[:5],
            "pgvector_top_ids": list(pg_ids)[:5],
            "sqlite_latency_ms": sqlite_latency,
            "pgvector_latency_ms": pg_latency,
            "overlap_count": overlap,
            "pgvector_only_count": len(pg_only),
            "sqlite_only_count": len(sqlite_ids - pg_ids),
            "whether_pgvector_has_direct_answerable": pg_direct,
            "pgvector_role_counts": role_counts,
            "missing_in_pgvector_ids": missing_ids[:5],
            "metadata_mismatches": mismatches[:5],
            "filter_ablation": ablation,
        })

    summary = {
        "run_uid": resolved_run_uid,
        "resolved_run_uid": resolved_run_uid,
        "pgvector_available": bool(pg_check.get("pgvector_available")),
        "extension_available": bool(pg_check.get("extension_available")),
        "compare_trace_count": len(rows),
        "sqlite_avg_latency_ms": round(statistics.mean(sqlite_latencies), 2) if sqlite_latencies else 0.0,
        "pgvector_avg_latency_ms": round(statistics.mean(pg_latencies), 2) if pg_latencies else 0.0,
        "pgvector_timeout_count": pgvector_timeout_count,
        "pgvector_product_fact_direct_count": pgvector_product_fact_direct_count,
        "pgvector_faq_direct_count": pgvector_faq_direct_count,
        "pgvector_service_action_count": pgvector_service_action_count,
        "pgvector_media_reference_count": pgvector_media_reference_count,
        "pgvector_direct_answerable_count": pgvector_direct_answerable_count,
        "overlap_count": overlap_total,
        "pgvector_only_direct_candidates": pgvector_only_direct_candidates,
        "missing_in_pgvector_count": missing_in_pgvector_count,
        "metadata_mismatch_count": metadata_mismatch_count,
        "strict_empty_but_product_only_has_candidates_count": strict_empty_but_product_only_has_candidates_count,
        "fact_type_alias_helped_count": fact_type_alias_helped_count,
        "high_risk_alias_blocked_count": high_risk_alias_blocked_count,
        "service_action_merge_candidate_count": service_action_merge_candidate_count,
        "service_action_merge_hit_count": service_action_merge_hit_count,
        "service_action_merge_helped_count": service_action_merge_helped_count,
        "service_action_merge_kept_as_fallback_count": service_action_merge_kept_as_fallback_count,
        "service_action_merge_fact_type_distribution": dict(
            sorted(service_action_merge_fact_type_distribution.items(), key=lambda item: item[1], reverse=True)
        ),
        "service_action_merge_source_type_distribution": dict(
            sorted(service_action_merge_source_type_distribution.items(), key=lambda item: item[1], reverse=True)
        ),
        "service_action_merge_evidence_role_distribution": dict(
            sorted(service_action_merge_evidence_role_distribution.items(), key=lambda item: item[1], reverse=True)
        ),
        "evidence_misuse_risk_samples": evidence_misuse_risk_samples[:5],
        "pgvector_error": pg_check.get("error") or "",
    }
    result = sanitize_obj({"summary": summary, "rows": rows})
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Shadow compare current SQLite retrieval against pgvector retrieval.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = compare_retrieval(run_uid=args.run_uid, limit=args.limit, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("summary", {}).get("pgvector_available") else 2


if __name__ == "__main__":
    raise SystemExit(main())
