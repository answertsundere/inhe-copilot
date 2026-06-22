"""Deterministic failure classification for eval replay results."""

from __future__ import annotations

from typing import Any


SUGGESTED_FILES = {
    "query_understanding": ["app/services/fact_type_service.py", "app/agent/nodes/parallel_understanding.py"],
    "tool_policy": ["app/agent/tools/tool_policy.py", "app/agent/tools/tool_policy_gate.py"],
    "product_card_data": ["app/services/product_context_pack_service.py"],
    "media_asset_data": ["app/services/media_asset_service.py", "app/models/kb_tables.py"],
    "final_answer_auditor": ["app/services/final_answer_auditor.py"],
    "semantic_compiler": ["app/services/semantic_compiler_service.py", "app/services/final_semantic_quality_service.py"],
    "evidence_rerank": ["app/services/evidence_rerank_service.py"],
}


def classify_eval_failure(
    eval_case: dict[str, Any],
    response: dict[str, Any],
    failed_contract: str,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    answer_trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    tool_policy_trace = debug.get("tool_policy_trace") or response.get("tool_policy_trace") or {}

    failure_type = _failure_type(failed_contract, response, answer_trace, tool_policy_trace)
    suggested_fix_area = _fix_area(failure_type, failed_contract, debug)
    severity = _severity(failure_type, response)
    return {
        "failure_type": failure_type,
        "severity": severity,
        "root_cause_hint": _root_cause_hint(failure_type, failed_contract, debug),
        "failed_contract": failed_contract,
        "expected": expected,
        "actual": actual,
        "suggested_fix_area": suggested_fix_area,
        "suggested_files": SUGGESTED_FILES.get(suggested_fix_area, []),
    }


def _failure_type(failed_contract: str, response: dict, answer_trace: dict, tool_policy_trace: dict) -> str:
    if failed_contract == "must_have_intent":
        return "intent_mismatch"
    if failed_contract == "must_have_fact_type":
        return "fact_type_mismatch"
    if failed_contract in {"must_have_evidence_type", "evidence_missing"}:
        return "missing_evidence"
    if failed_contract == "must_not_contain":
        return "internal_term_leak"
    if failed_contract == "must_not_call_tools":
        return "wrong_tool_called"
    if failed_contract == "must_call_tools":
        return "required_tool_missing"
    if failed_contract == "must_not_require_human":
        return "final_quality_failed"
    if response.get("error"):
        return "model_error"
    if _has_tool_error(tool_policy_trace):
        return "tool_error"
    if _has_media_issue(answer_trace):
        return "media_contract_violation"
    return "unknown"


def _fix_area(failure_type: str, failed_contract: str, debug: dict) -> str:
    if failure_type in {"intent_mismatch", "fact_type_mismatch"}:
        return "query_understanding"
    if failure_type in {"wrong_tool_called", "required_tool_missing", "tool_error"}:
        return "tool_policy"
    if failure_type == "missing_evidence":
        if debug.get("selected_assets") or debug.get("needs_visual_asset"):
            return "media_asset_data"
        return "product_card_data"
    if failure_type == "internal_term_leak":
        return "semantic_compiler"
    if failure_type == "final_quality_failed":
        return "final_answer_auditor"
    if failure_type == "media_contract_violation":
        return "media_asset_data"
    return "semantic_compiler"


def _severity(failure_type: str, response: dict) -> str:
    if response.get("error") or failure_type in {"unsafe_claim", "wrong_tool_called"}:
        return "high"
    if failure_type in {"intent_mismatch", "fact_type_mismatch", "missing_evidence"}:
        return "medium"
    return "low"


def _root_cause_hint(failure_type: str, failed_contract: str, debug: dict) -> str:
    hints = {
        "intent_mismatch": "Structured intent did not match the eval contract.",
        "fact_type_mismatch": "Query fact type did not match the eval contract.",
        "missing_evidence": "Required evidence type was not visible in answer trace or evidence debug.",
        "internal_term_leak": "Customer-facing reply leaked internal implementation vocabulary.",
        "wrong_tool_called": "Tool policy trace shows a forbidden tool was called.",
        "required_tool_missing": "Tool policy trace did not include a required tool call.",
        "final_quality_failed": "Final quality gate or human-review contract did not match expected behavior.",
    }
    return hints.get(failure_type, f"Failed eval contract: {failed_contract}")


def _has_tool_error(tool_policy_trace: dict) -> bool:
    return any(item.get("status") == "error" for item in tool_policy_trace.get("evaluated_tools") or [])


def _has_media_issue(answer_trace: dict) -> bool:
    fallback = set(answer_trace.get("fallback_fact_types") or [])
    needs = set(answer_trace.get("needs_followup_fact_types") or [])
    return "visual_asset" in fallback or "visual_asset" in needs
