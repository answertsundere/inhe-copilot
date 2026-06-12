"""Classify the concrete fact field being requested by the customer."""

from __future__ import annotations

import time

from app.services.semantic_fact_type_service import classify_query_fact_type_llm_first


def query_fact_type_classifier(state: dict) -> dict:
    t0 = time.time()
    result = classify_query_fact_type_llm_first(state)

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "query_fact_type_classifier",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "query_fact_type": result.get("query_fact_type", ""),
        "confidence": result.get("confidence", 0),
        "matched_terms": result.get("matched_terms", []),
        "reason": result.get("reason", ""),
        "secondary_fact_types": result.get("secondary_fact_types", []),
        "summary": (
            f"query_fact_type={result.get('query_fact_type', '') or 'unknown'} "
            f"source={result.get('source', '')}"
        ),
    }

    return {
        **result,
        "query_fact_type_confidence": result.get("confidence", 0),
        "query_fact_type_source": result.get("source", ""),
        "query_fact_type_terms": result.get("matched_terms", []),
        "query_fact_type_reason": result.get("reason", ""),
        "secondary_fact_types": result.get("secondary_fact_types", []),
        "query_fact_type_risk_hint": result.get("risk_hint", ""),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
