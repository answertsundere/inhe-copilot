"""Classify the concrete fact field being requested by the customer."""

from __future__ import annotations

import time

from app.services.logistics_fast_path import get_explicit_logistics_identifier
from app.services.semantic_fact_type_service import classify_query_fact_type_llm_first


def _requested_claims_from_customer_goals(
    goals: list[dict],
    *,
    question: str,
    risk_hint: str,
) -> list[dict]:
    claims: list[dict] = []
    seen: set[str] = set()
    for goal in goals:
        if not isinstance(goal, dict) or goal.get("goal_kind") != "customer_goal":
            continue
        goal_ref = str(goal.get("goal_ref") or "").strip()
        if not goal_ref or goal_ref in seen:
            continue
        seen.add(goal_ref)
        claim = {
            "goal_ref": goal_ref,
            "goal_kind": "customer_goal",
            "claim_type": str(goal.get("claim_type") or "").strip(),
            "attribute_key": str(goal.get("attribute_key") or "").strip(),
            "semantic_key": str(goal.get("semantic_key") or "").strip(),
            "policy_intent_ref": str(
                goal.get("policy_intent_ref") or ""
            ).strip(),
            "policy_goal_family": str(
                goal.get("policy_goal_family") or ""
            ).strip(),
            "policy_intent_kind": str(
                goal.get("policy_intent_kind") or ""
            ).strip(),
            "goal_summary": str(goal.get("goal_summary") or "").strip(),
            "source": str(goal.get("source") or "").strip(),
            "source_span_start": goal.get("source_span_start"),
            "source_span_end": goal.get("source_span_end"),
            "source_span_sha256": str(goal.get("source_span_sha256") or "").strip(),
            "owner": "turn_understanding_owner",
            "source_stage": "query_fact_type_classifier",
            "question": question,
            "risk_level": risk_hint,
        }
        for field in (
            "schema_version",
            "claim_type_status",
            "claim_type_exact_match",
            "source_turn_uid",
            "source_text_sha256",
        ):
            if field in goal:
                claim[field] = goal[field]
        claims.append(claim)
    return sorted(claims, key=lambda item: item["goal_ref"])


def _turn_understanding_from_result(state: dict, result: dict) -> dict:
    goals = [
        dict(item)
        for item in result.get("customer_goals") or []
        if isinstance(item, dict)
    ]
    status = str(
        result.get("goal_understanding_status") or "degraded"
    ).strip().lower()
    diagnostics = result.get("goal_understanding_diagnostics")
    diagnostics = list(diagnostics) if isinstance(diagnostics, list) else []
    diagnostics = list(dict.fromkeys(
        str(reason).strip()
        for reason in diagnostics
        if str(reason or "").strip()
    ))
    requested_claims = []
    if status == "valid":
        requested_claims = _requested_claims_from_customer_goals(
            goals,
            question=str(
                state.get("normalized_message")
                or state.get("customer_message")
                or ""
            ),
            risk_hint=str(result.get("risk_hint") or ""),
        )
        customer_goal_count = sum(
            1
            for goal in goals
            if goal.get("goal_kind") == "customer_goal"
        )
        if len(requested_claims) != customer_goal_count:
            status = "invalid"
            requested_claims = []
            diagnostics = list(dict.fromkeys([
                *diagnostics,
                "requested_claim_count_mismatch",
            ]))
    return {
        "schema_version": "turn-understanding/v2",
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "query_fact_type": result.get("query_fact_type", ""),
        "secondary_fact_types": result.get("secondary_fact_types", []),
        "customer_goals": goals,
        "goal_understanding_status": status,
        "goal_understanding_diagnostics": diagnostics,
        "requested_claims": requested_claims,
    }


def query_fact_type_classifier(state: dict) -> dict:
    t0 = time.time()
    if get_explicit_logistics_identifier(state):
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
            "summary": "query_fact_type skipped for explicit logistics identifier",
        }
        return {
            "query_fact_type": "",
            "query_fact_type_confidence": 1.0,
            "query_fact_type_source": "explicit_logistics_identifier_fast_path",
            "query_fact_type_terms": [],
            "query_fact_type_reason": "explicit_logistics_identifier_fast_path",
            "secondary_fact_types": [],
            "query_fact_type_risk_hint": "",
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    result = classify_query_fact_type_llm_first(state)
    if (
        not result.get("query_fact_type")
        and state.get("query_fact_type")
        and not (result.get("customer_goals") or [])
        and str(
            result.get("goal_understanding_status") or ""
        ).strip().lower() not in {"invalid", "degraded"}
    ):
        result = {
            **result,
            "query_fact_type": state.get("query_fact_type", ""),
            "confidence": result.get("confidence") or 0.7,
            "source": result.get("source") or "preclassified_state",
            "reason": result.get("reason") or "preserve_preclassified_query_fact_type",
        }

    duration_ms = int((time.time() - t0) * 1000)
    turn_understanding = _turn_understanding_from_result(state, result)
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
        "semantic_query": result.get("semantic_query", {}),
        "goal_count": len(turn_understanding.get("customer_goals") or []),
        "goal_understanding_status": turn_understanding.get("goal_understanding_status", ""),
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
        "semantic_query": result.get("semantic_query", {}),
        "needs_visual_asset": bool((result.get("semantic_query") or {}).get("needs_visual_asset")),
        "turn_understanding": turn_understanding,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
