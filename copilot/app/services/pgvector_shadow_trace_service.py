"""Read-only pgvector shadow trace helpers for eval replay diagnostics."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from app.services.embedding_service import EmbeddingService
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.fact_type_alias_service import (
    expand_fact_type_aliases,
    is_alias_safe_for_direct_answer,
)
from app.services.pgvector_retriever_service import PgVectorRetrieverService


SERVICE_ACTION_SOURCE_TYPES = ["generic_rule", "generic_rules", "response_templates"]
SERVICE_ACTION_EVIDENCE_ROLES = ["service_action", "fallback_only"]
MEDIA_REFERENCE_SOURCE_TYPES = ["media_asset"]
MEDIA_REFERENCE_EVIDENCE_ROLES = ["media_reference"]


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
    if source_type in SERVICE_ACTION_SOURCE_TYPES:
        return "service_action"
    if source_type == "media_asset":
        return "media_reference"
    return "reference_only"


def _has_direct_answerable(rows: list[dict[str, Any]]) -> bool:
    return any(_candidate_role(row) in {"product_fact_direct", "faq_direct"} for row in rows)


def _distribution(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[str(row.get(field) or "__empty__")] += 1
    return dict(counter.most_common())


def _top_candidates(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows[: max(1, int(limit or 3))]:
        candidates.append({
            "id": str(row.get("chunk_id") or row.get("source_chunk_id") or ""),
            "source_type": str(row.get("source_type") or ""),
            "evidence_role": str(row.get("evidence_role") or ""),
            "media_role": str(row.get("media_role") or ""),
            "query_fact_type": str(row.get("fact_type") or row.get("query_fact_type") or ""),
            "score": row.get("score") or row.get("vector_score") or 0,
            "preview": sanitize_text(str(row.get("chunk_text") or ""))[:120],
        })
    return candidates


def _annotate_alias_candidate(row: dict[str, Any], *, requested_fact_type: str, alias_values: list[str]) -> dict[str, Any]:
    candidate = dict(row)
    candidate_fact_type = str(candidate.get("fact_type") or candidate.get("query_fact_type") or "")
    candidate["fact_type_alias_used"] = bool(candidate_fact_type and candidate_fact_type != requested_fact_type)
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


def _direct_product_rows(
    *,
    pg_service: PgVectorRetrieverService,
    query_text: str,
    query_embedding: list[float],
    sidecar: dict[str, str],
    query_fact_type: str,
    top_k: int,
) -> list[dict[str, Any]]:
    rows = pg_service.retrieve(
        query_text=query_text,
        query_embedding=query_embedding,
        i_id=sidecar.get("i_id", ""),
        sku_code=sidecar.get("sku_code", ""),
        query_fact_type=query_fact_type,
        top_k=top_k,
    )
    if rows or not query_fact_type:
        return rows
    alias_values = expand_fact_type_aliases(query_fact_type, context="retrieval")
    alias_only = [item for item in alias_values if item != query_fact_type]
    if not alias_only:
        return rows
    alias_rows = pg_service.retrieve(
        query_text=query_text,
        query_embedding=query_embedding,
        i_id=sidecar.get("i_id", ""),
        sku_code=sidecar.get("sku_code", ""),
        query_fact_types=alias_only,
        top_k=top_k,
    )
    return _safe_alias_candidates(alias_rows, requested_fact_type=query_fact_type, alias_values=alias_values)


def _service_action_rows(
    *,
    pg_service: PgVectorRetrieverService,
    query_text: str,
    query_embedding: list[float],
    query_fact_type: str,
    top_k: int,
) -> list[dict[str, Any]]:
    fact_types = expand_fact_type_aliases(query_fact_type, context="retrieval")
    if query_fact_type and not fact_types:
        fact_types = [query_fact_type]
    return pg_service.retrieve(
        query_text=query_text,
        query_embedding=query_embedding,
        i_id="",
        sku_code="",
        query_fact_types=fact_types,
        allowed_source_types=SERVICE_ACTION_SOURCE_TYPES,
        allowed_evidence_roles=SERVICE_ACTION_EVIDENCE_ROLES,
        top_k=top_k,
        allow_broad_search=True,
    )


def _media_reference_rows(
    *,
    pg_service: PgVectorRetrieverService,
    query_text: str,
    query_embedding: list[float],
    sidecar: dict[str, str],
    query_fact_type: str,
    top_k: int,
) -> list[dict[str, Any]]:
    if not (sidecar.get("i_id") or sidecar.get("sku_code")):
        return []
    return pg_service.retrieve(
        query_text=query_text,
        query_embedding=query_embedding,
        i_id=sidecar.get("i_id", ""),
        sku_code=sidecar.get("sku_code", ""),
        query_fact_type=query_fact_type,
        allowed_source_types=MEDIA_REFERENCE_SOURCE_TYPES,
        allowed_evidence_roles=MEDIA_REFERENCE_EVIDENCE_ROLES,
        top_k=top_k,
    )


def _bucket(rows: list[dict[str, Any]], *, top_k: int, direct: bool = False) -> dict[str, Any]:
    payload = {
        "candidate_count": len(rows),
        "source_type_distribution": _distribution(rows, "source_type"),
        "evidence_role_distribution": _distribution(rows, "evidence_role"),
        "top_candidates": _top_candidates(rows, limit=min(3, top_k)),
    }
    if direct:
        payload["direct_answerable_count"] = 1 if _has_direct_answerable(rows) else 0
    return payload


def build_pgvector_shadow_trace(
    *,
    query_text: str,
    query_fact_type: str,
    sidecar: dict[str, Any],
    top_k: int = 5,
    pg_service: PgVectorRetrieverService | None = None,
    embedding_provider=None,
) -> dict[str, Any]:
    """Build read-only pgvector shadow diagnostics for one replay turn."""
    started = time.perf_counter()
    pg_service = pg_service or PgVectorRetrieverService()
    embedding_provider = embedding_provider or EmbeddingService.get_embeddings
    top_k = max(1, min(int(top_k or 5), 20))
    result: dict[str, Any] = {
        "enabled": True,
        "available": False,
        "latency_ms": 0.0,
        "error": "",
        "product_fact": _bucket([], top_k=top_k, direct=True),
        "service_action": {"hit_count": 0, **_bucket([], top_k=top_k)},
        "media_reference": {
            "candidate_count": 0,
            "media_role_distribution": {},
            "top_candidates": [],
        },
        "safety": {
            "direct_answerable_excludes_service_action": True,
            "can_send_unchanged": True,
            "selected_evidence_unchanged": True,
            "used_for_generation": False,
        },
    }
    def finish() -> dict[str, Any]:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return sanitize_obj(result)

    try:
        check = pg_service.check()
        result["available"] = bool(check.get("pgvector_available"))
        result["error"] = sanitize_text(check.get("error") or "")
        if not result["available"]:
            return finish()
        query_text = sanitize_text(query_text)
        if not query_text:
            result["error"] = "empty_query_text"
            return finish()
        embedding = embedding_provider([query_text])
        query_embedding = embedding[0] if embedding else []
        if not query_embedding:
            result["error"] = "query_embedding_failed"
            return finish()
        clean_sidecar = {
            "i_id": sanitize_text(sidecar.get("i_id") or ""),
            "sku_code": sanitize_text(sidecar.get("sku_code") or ""),
        }
        product_rows = _direct_product_rows(
            pg_service=pg_service,
            query_text=query_text,
            query_embedding=query_embedding,
            sidecar=clean_sidecar,
            query_fact_type=sanitize_text(query_fact_type),
            top_k=top_k,
        )
        service_rows = _service_action_rows(
            pg_service=pg_service,
            query_text=query_text,
            query_embedding=query_embedding,
            query_fact_type=sanitize_text(query_fact_type),
            top_k=top_k,
        )
        media_rows = _media_reference_rows(
            pg_service=pg_service,
            query_text=query_text,
            query_embedding=query_embedding,
            sidecar=clean_sidecar,
            query_fact_type=sanitize_text(query_fact_type),
            top_k=top_k,
        )
        direct_product_rows = [
            row for row in product_rows if _candidate_role(row) in {"product_fact_direct", "faq_direct"}
        ]
        result["product_fact"] = _bucket(direct_product_rows, top_k=top_k, direct=True)
        result["service_action"] = {
            "hit_count": 1 if service_rows else 0,
            **_bucket(service_rows, top_k=top_k),
        }
        result["media_reference"] = {
            "candidate_count": len(media_rows),
            "media_role_distribution": _distribution(media_rows, "media_role"),
            "top_candidates": _top_candidates(media_rows, limit=min(3, top_k)),
        }
        return finish()
    except Exception as exc:
        result["available"] = False
        result["error"] = type(exc).__name__
        return finish()
