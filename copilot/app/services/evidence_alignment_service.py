"""Semantic alignment between a customer query and one evidence item.

This module deliberately does not inspect raw customer keywords. It consumes the
semantic query type produced upstream and the evidence type attached to each
fact/media/rule. The goal is to keep retrieval routing generic and auditable.
"""

from __future__ import annotations

from typing import Any

from app.services.fact_type_service import fact_type_matches, is_strict_fact_type


def align_evidence_to_query(
    *,
    query_fact_type: str = "",
    evidence_fact_type: str = "",
    semantic_query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return whether evidence can answer the semantic query.

    Contract:
    - primary_match: can directly answer and receives the strongest boost.
    - secondary_match: useful context only; it must not become the final direct
      answer when a primary fact type is requested.
    - strict_mismatch: excluded for strict fact types such as dimensions,
      space_fit, placement_scene, detachable, certification, etc.
    - non_strict_mismatch: retained only as weak background.
    """

    query_type = _normalize_fact_type(query_fact_type)
    evidence_type = _normalize_fact_type(evidence_fact_type)
    secondary_types = _secondary_fact_types(semantic_query)

    if not query_type:
        return _result(
            allowed=True,
            direct_answer_allowed=True,
            score_delta=0.0,
            alignment="no_query_fact_type",
            query_fact_type=query_type,
            evidence_fact_type=evidence_type,
            reason="No specific query fact type was requested.",
        )

    if evidence_type and fact_type_matches(query_type, evidence_type):
        return _result(
            allowed=True,
            direct_answer_allowed=True,
            score_delta=12.0,
            alignment="primary_match",
            query_fact_type=query_type,
            evidence_fact_type=evidence_type,
            reason="Evidence fact type directly answers the primary query fact type.",
        )

    if evidence_type and evidence_type in secondary_types:
        return _result(
            allowed=True,
            direct_answer_allowed=False,
            score_delta=3.0,
            alignment="secondary_match",
            query_fact_type=query_type,
            evidence_fact_type=evidence_type,
            reason="Evidence matches a secondary query facet, so it can only support context.",
        )

    if is_strict_fact_type(query_type):
        return _result(
            allowed=False,
            direct_answer_allowed=False,
            score_delta=0.0,
            alignment="strict_mismatch",
            query_fact_type=query_type,
            evidence_fact_type=evidence_type,
            reason="Strict query fact type cannot be answered by neighboring evidence.",
        )

    if evidence_type:
        return _result(
            allowed=True,
            direct_answer_allowed=False,
            score_delta=-4.0,
            alignment="non_strict_mismatch",
            query_fact_type=query_type,
            evidence_fact_type=evidence_type,
            reason="Evidence is related to the product but does not directly answer the query type.",
        )

    return _result(
        allowed=True,
        direct_answer_allowed=False,
        score_delta=-1.0,
        alignment="unknown_evidence_fact_type",
        query_fact_type=query_type,
        evidence_fact_type=evidence_type,
        reason="Evidence has no fact type and can only be weak background.",
    )


def _secondary_fact_types(semantic_query: dict[str, Any] | None) -> set[str]:
    if not isinstance(semantic_query, dict):
        return set()
    values = semantic_query.get("secondary_fact_types") or []
    if not isinstance(values, list):
        return set()
    return {
        _normalize_fact_type(item)
        for item in values
        if _normalize_fact_type(item)
    }


def _normalize_fact_type(value: Any) -> str:
    return str(value or "").strip()


def _result(
    *,
    allowed: bool,
    direct_answer_allowed: bool,
    score_delta: float,
    alignment: str,
    query_fact_type: str,
    evidence_fact_type: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "allowed": bool(allowed),
        "direct_answer_allowed": bool(direct_answer_allowed),
        "score_delta": float(score_delta),
        "alignment": alignment,
        "query_fact_type": query_fact_type,
        "evidence_fact_type": evidence_fact_type,
        "reason": reason,
    }
