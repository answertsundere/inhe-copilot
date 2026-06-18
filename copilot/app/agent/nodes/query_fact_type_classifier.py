"""Classify the concrete fact field being requested by the customer."""

from __future__ import annotations

import time

from app.agent.query_understanding import build_query_understanding
from app.services.logistics_fast_path import get_explicit_logistics_identifier
from app.services.semantic_fact_type_service import classify_query_fact_type_llm_first


def query_fact_type_classifier(state: dict) -> dict:
    t0 = time.time()
    if get_explicit_logistics_identifier(state):
        understanding = build_query_understanding(state, {
            "query_fact_type": "",
            "confidence": 1.0,
            "source": "explicit_logistics_identifier_fast_path",
            "secondary_fact_types": [],
        })
        trace = {
            "node": "query_fact_type_classifier",
            "status": "success",
            "duration_ms": int((time.time() - t0) * 1000),
            "cache_hit": False,
            "query_fact_type": "",
            "confidence": 1.0,
            "matched_terms": [],
            "reason": "explicit_logistics_identifier_fast_path",
            "secondary_fact_types": [],
            "query_understanding": understanding,
            "summary": "query_fact_type skipped for explicit logistics identifier",
        }
        return {
            "query_fact_type": "",
            "query_fact_type_confidence": 1.0,
            "query_fact_type_source": "explicit_logistics_identifier_fast_path",
            "query_fact_type_terms": [],
            "query_fact_type_reason": "explicit_logistics_identifier_fast_path",
            "secondary_fact_types": [],
            "llm_rejected_fact_type": "",
            "query_fact_type_risk_hint": "",
            "query_understanding": understanding,
            "retrieval_query": understanding.get("retrieval_query", ""),
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    result = classify_query_fact_type_llm_first(state)
    if not result.get("query_fact_type") and state.get("query_fact_type"):
        result = {
            **result,
            "query_fact_type": state.get("query_fact_type", ""),
            "confidence": result.get("confidence") or 0.7,
            "source": result.get("source") or "preclassified_state",
            "reason": result.get("reason") or "preserve_preclassified_query_fact_type",
        }

    duration_ms = int((time.time() - t0) * 1000)
    understanding = build_query_understanding(state, result)
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
        "llm_rejected_fact_type": result.get("llm_rejected_fact_type", ""),
        "semantic_query": result.get("semantic_query", {}),
        "query_understanding": understanding,
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
        "llm_rejected_fact_type": result.get("llm_rejected_fact_type", ""),
        "query_fact_type_risk_hint": result.get("risk_hint", ""),
        "semantic_query": result.get("semantic_query", {}),
        "needs_visual_asset": bool((result.get("semantic_query") or {}).get("needs_visual_asset")),
        "query_understanding": understanding,
        "retrieval_query": understanding.get("retrieval_query", ""),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
