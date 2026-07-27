"""Qualify the single model-first textual audit with bounded synthetic cases."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

from app.api.runtime_routes import _source_tree_sha256  # noqa: E402
from app.llm.client import get_llm_client  # noqa: E402
from app.services.final_answer_auditor import audit_final_answer  # noqa: E402
from app.services.final_semantic_quality_service import (  # noqa: E402
    _FINDING_ONTOLOGY_VERSION,
    _ATOMIC_SEMANTIC_OUTPUT_FIELDS,
    _ATOMIC_SEGMENT_FIELDS,
    _atomic_semantic_system_prompt,
    _canonicalize_finding_codes,
    _semantic_payload,
    audit_customer_reply_semantic_fit,
    finding_ownership_matrix,
)


REPORT_SCHEMA_VERSION = "unified-textual-audit-qualification/v2"


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case(
    *,
    case_id: str,
    customer_message: str,
    evidence_content: str,
    supported_text: str,
    unresolved_text: str,
    history_agent_text: str = "",
    expected_pass: bool,
    expected_finding: str = "",
) -> dict[str, Any]:
    evidence = {
        "evidence_uid": "evidence-direct",
        "evidence_role": "product_fact_direct",
        "fact_type": "product_attribute",
        "attribute_key": "primary_attribute",
        "content": evidence_content,
    }
    resolutions = [
        {
            "claim_uid": "goal-supported",
            "claim_type": "product_attribute",
            "attribute_key": "primary_attribute",
            "status": "supported",
            "evidence_uids": ["evidence-direct"],
        },
        {
            "claim_uid": "goal-unresolved",
            "claim_type": "secondary_attribute",
            "attribute_key": "secondary_attribute",
            "status": "unresolved",
            "evidence_uids": [],
        },
    ]
    clauses = [
        {
            "clause_ref": "clause-supported",
            "goal_ref": "goal-supported",
            "clause_kind": "supported_fact",
            "text": supported_text,
            "evidence_uids": ["evidence-direct"],
        },
        {
            "clause_ref": "clause-unresolved",
            "goal_ref": "goal-unresolved",
            "clause_kind": "unresolved",
            "text": unresolved_text,
            "evidence_uids": [],
        },
    ]
    reply = f"{supported_text}\n{unresolved_text}"
    response = {
        "suggested_reply": reply,
        "draft_reply": reply,
        "selected_evidence": [copy.deepcopy(evidence)],
        "minimal_decision_context": {
            "admitted_evidence": [copy.deepcopy(evidence)],
            "claim_resolutions": copy.deepcopy(resolutions),
            "requested_claims": [
                {
                    "claim_type": item["claim_type"],
                    "attribute_key": item["attribute_key"],
                }
                for item in resolutions
            ],
            "unresolved_claims": [copy.deepcopy(resolutions[1])],
        },
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
            "can_change_can_send": False,
            "can_send": False,
            "requires_human_review": True,
            "clauses": clauses,
        },
        "can_send": False,
        "requires_human_review": True,
        "sendable_reply": "",
        "reply_status": "needs_human_review",
    }
    context = {
        "conversation_history": (
            [{
                "role": "agent",
                "content": history_agent_text,
                "turn_index": 1,
            }]
            if history_agent_text
            else []
        )
    }
    return {
        "case_id": case_id,
        "customer_message": customer_message,
        "response": response,
        "copilot_context": context,
        "expected_pass": expected_pass,
        "expected_finding": expected_finding,
    }


def qualification_cases() -> list[dict[str, Any]]:
    return [
        _case(
            case_id="supported_unresolved_valid",
            customer_message="请说明主要属性，次要属性能否确认？",
            evidence_content="主要属性为A类。",
            supported_text="主要属性为A类。",
            unresolved_text="次要属性目前无法确认。",
            expected_pass=True,
        ),
        _case(
            case_id="history_conflict_candidate_valid",
            customer_message="请确认主要属性和次要属性。",
            evidence_content="主要属性为A类。",
            supported_text="主要属性为A类。",
            unresolved_text="次要属性目前无法确认。",
            history_agent_text="此前回复曾称主要属性为B类。",
            expected_pass=True,
        ),
        _case(
            case_id="unresolved_asserted_invalid",
            customer_message="请说明主要属性，次要属性能否确认？",
            evidence_content="主要属性为A类。",
            supported_text="主要属性为A类。",
            unresolved_text="次要属性已经确认适用。",
            expected_pass=False,
            expected_finding="unresolved_claim_asserted",
        ),
        _case(
            case_id="evidence_expansion_invalid",
            customer_message="请说明主要属性和次要属性。",
            evidence_content="主要属性为A类。",
            supported_text="主要属性为A类，并且次要属性为B类。",
            unresolved_text="次要属性目前无法确认。",
            expected_pass=False,
            expected_finding="unsupported_claim",
        ),
    ]


def _canonical_stability_components(
    semantic: dict[str, Any],
) -> dict[str, Any]:
    goals = [
        item
        for item in semantic.get("canonical_goal_findings") or []
        if isinstance(item, dict)
    ]
    global_finding = semantic.get("canonical_global_findings")
    if not isinstance(global_finding, dict):
        global_finding = {}
    return {
        "verdict": semantic.get("passed") is True,
        "blocking": (
            tuple(
                (
                    item.get("goal_ref"),
                    item.get("clause_ref"),
                    item.get("blocking") is True,
                )
                for item in goals
            ),
            global_finding.get("blocking") is True,
        ),
        "attribution": tuple(
            (item.get("goal_ref"), item.get("clause_ref"))
            for item in goals
        ),
        "primary_family": (
            tuple(
                (
                    item.get("goal_ref"),
                    item.get("clause_ref"),
                    item.get("primary_finding_family"),
                )
                for item in goals
            ),
            global_finding.get("primary_finding_family"),
        ),
        "primary_code": (
            tuple(
                (
                    item.get("goal_ref"),
                    item.get("clause_ref"),
                    item.get("primary_finding_code"),
                )
                for item in goals
            ),
            global_finding.get("primary_finding_code"),
        ),
        "canonical_roots": (
            tuple(
                (
                    item.get("goal_ref"),
                    item.get("clause_ref"),
                    tuple(
                        finding.get("canonical_root_code")
                        for finding in item.get(
                            "canonical_findings"
                        ) or []
                        if isinstance(finding, dict)
                    ),
                )
                for item in goals
            ),
            tuple(
                finding.get("canonical_root_code")
                for finding in global_finding.get(
                    "canonical_findings"
                ) or []
                if isinstance(finding, dict)
            ),
        ),
    }


def _canonical_attempt_findings(
    goal_reviews: list[dict[str, Any]],
    overall_findings: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    canonical_goals: list[dict[str, Any]] = []
    bound_raw_codes: set[str] = set()
    blockers: list[str] = []
    for review in goal_reviews:
        raw_codes = list(review.get("finding_codes") or [])
        normalized, issue = _canonicalize_finding_codes(raw_codes)
        if normalized is None:
            blockers.append(issue)
            continue
        bound_raw_codes.update(raw_codes)
        canonical_goals.append({
            "goal_ref": review.get("goal_ref"),
            "clause_ref": review.get("clause_ref"),
            **normalized,
        })
    unbound_codes = [
        code
        for code in overall_findings
        if code not in bound_raw_codes
    ]
    canonical_global, issue = _canonicalize_finding_codes(unbound_codes)
    if canonical_global is None:
        blockers.append(issue)
        canonical_global = {}
    return canonical_goals, canonical_global, blockers


def recompute_historical_report(
    historical_report: dict[str, Any],
) -> dict[str, Any]:
    recomputed_attempts: list[dict[str, Any]] = []
    blockers: list[str] = []
    previous_by_case: dict[str, dict[str, Any]] = {}
    stable_counts = {
        "verdict": 0,
        "blocking": 0,
        "attribution": 0,
        "primary_family": 0,
        "primary_code": 0,
        "canonical_roots": 0,
    }
    comparison_count = 0
    for attempt in historical_report.get("attempts") or []:
        reviews = [
            item
            for item in attempt.get("goal_review_refs") or []
            if isinstance(item, dict)
        ]
        if not reviews:
            blockers.append(
                f"{attempt.get('case_id')}:historical_attribution_incomplete"
            )
            continue
        canonical_goals, canonical_global, normalization_blockers = (
            _canonical_attempt_findings(
                reviews,
                list(attempt.get("finding_codes") or []),
            )
        )
        semantic = {
            "passed": attempt.get("unified_passed") is True,
            "canonical_goal_findings": canonical_goals,
            "canonical_global_findings": canonical_global,
        }
        components = _canonical_stability_components(semantic)
        derived_passed = not (
            any(item.get("blocking") is True for item in canonical_goals)
            or canonical_global.get("blocking") is True
        )
        if derived_passed is not (attempt.get("unified_passed") is True):
            normalization_blockers.append("verdict_changed")
        case_id = str(attempt.get("case_id") or "")
        previous = previous_by_case.get(case_id)
        if previous is not None:
            comparison_count += 1
            for key in stable_counts:
                if previous[key] == components[key]:
                    stable_counts[key] += 1
                else:
                    normalization_blockers.append(
                        f"{key}_instability"
                    )
        previous_by_case[case_id] = components
        blockers.extend(
            f"{case_id}:{item}" for item in normalization_blockers
        )
        recomputed_attempts.append({
            "case_id": case_id,
            "attempt": attempt.get("attempt"),
            "original_verdict": attempt.get("unified_passed") is True,
            "canonical_verdict": derived_passed,
            "goal_clause_attribution": [
                {
                    "goal_ref": item["goal_ref"],
                    "clause_ref": item["clause_ref"],
                    "blocking": item["blocking"],
                    "primary_finding_family": item[
                        "primary_finding_family"
                    ],
                    "primary_finding_code": item[
                        "primary_finding_code"
                    ],
                    "primary_canonical_root_code": item[
                        "primary_canonical_root_code"
                    ],
                    "primary_raw_finding_codes": item[
                        "primary_raw_finding_codes"
                    ],
                    "primary_canonical_subtypes": item[
                        "primary_canonical_subtypes"
                    ],
                    "secondary_finding_codes": item[
                        "secondary_finding_codes"
                    ],
                    "raw_finding_codes": item["raw_finding_codes"],
                }
                for item in canonical_goals
            ],
        })
    legal = [
        item for item in historical_report.get("attempts") or []
        if item.get("expected_pass") is True
    ]
    illegal = [
        item for item in historical_report.get("attempts") or []
        if item.get("expected_pass") is False
    ]
    return {
        "schema_version": "unified-textual-audit-historical-recompute/v1",
        "status": "recomputed" if not blockers else "invalid",
        "source_report_sha256": _sha256(historical_report),
        "finding_ontology_version": _FINDING_ONTOLOGY_VERSION,
        "offline_model_call_count": 0,
        "historical_recorded_model_call_count": sum(
            int(item.get("model_call_count") or 0)
            for item in historical_report.get("attempts") or []
        ),
        "summary": {
            "attempt_count": len(recomputed_attempts),
            "legal_pass_count": sum(
                item.get("unified_passed") is True
                for item in legal
            ),
            "legal_attempt_count": len(legal),
            "illegal_reject_count": sum(
                item.get("unified_passed") is False
                for item in illegal
            ),
            "illegal_attempt_count": len(illegal),
            "stability_comparison_count": comparison_count,
            **{
                f"{key}_stable_comparison_count": value
                for key, value in stable_counts.items()
            },
        },
        "attempts": recomputed_attempts,
        "blockers": blockers,
    }


def run_qualification(*, repeat: int) -> tuple[dict[str, Any], int]:
    if repeat != 3:
        raise ValueError("repeat_must_equal_3")
    client = get_llm_client()
    if not client.api_key:
        raise ValueError("provider_not_configured")
    cases = qualification_cases()
    attempts: list[dict[str, Any]] = []
    blockers: list[str] = []
    stable_components: dict[str, dict[str, Any]] = {}
    stability_comparison_count = 0
    stability_counts = {
        "verdict": 0,
        "blocking": 0,
        "attribution": 0,
        "primary_family": 0,
        "primary_code": 0,
        "canonical_roots": 0,
    }

    for case in cases:
        for attempt_index in range(1, repeat + 1):
            response = copy.deepcopy(case["response"])
            candidate_sha = hashlib.sha256(
                response["suggested_reply"].encode("utf-8")
            ).hexdigest()
            response = audit_final_answer(
                response,
                customer_message=case["customer_message"],
                copilot_context=case["copilot_context"],
            )
            final_audit = response.get("final_answer_audit") or {}
            input_sha = _sha256(
                _semantic_payload(
                    response,
                    case["customer_message"],
                    case["copilot_context"],
                )
            )
            semantic = audit_customer_reply_semantic_fit(
                response,
                customer_message=case["customer_message"],
                copilot_context=case["copilot_context"],
            )
            provider = semantic.get("provider_diagnostics") or {}
            reviews = semantic.get("goal_reviews") or []
            canonical_goals = [
                item
                for item in semantic.get("canonical_goal_findings") or []
                if isinstance(item, dict)
            ]
            components = _canonical_stability_components(semantic)
            canonical_finding_codes = {
                finding["finding_code"]
                for item in canonical_goals
                for finding in item.get("canonical_findings") or []
                if isinstance(finding, dict)
            }
            canonical_global = semantic.get("canonical_global_findings")
            if isinstance(canonical_global, dict):
                canonical_finding_codes.update(
                    finding["finding_code"]
                    for finding in canonical_global.get(
                        "canonical_findings"
                    ) or []
                    if isinstance(finding, dict)
                )
            attempt = {
                "case_id": case["case_id"],
                "attempt": attempt_index,
                "expected_pass": case["expected_pass"],
                "candidate_sha256": candidate_sha,
                "input_sha256": input_sha,
                "final_passed": final_audit.get("passed") is True,
                "final_model_call_count": int(
                    final_audit.get("model_call_count") or 0
                ),
                "unified_passed": semantic.get("passed") is True,
                "finding_codes": list(semantic.get("issues") or []),
                "goal_review_refs": [
                    {
                        "goal_ref": item.get("goal_ref"),
                        "clause_ref": item.get("clause_ref"),
                        "textual_status": item.get("textual_status"),
                        "finding_codes": list(
                            item.get("finding_codes") or []
                        ),
                    }
                    for item in reviews
                    if isinstance(item, dict)
                ],
                "canonical_goal_findings": canonical_goals,
                "canonical_global_findings": (
                    canonical_global
                    if isinstance(canonical_global, dict)
                    else {}
                ),
                "model_call_count": int(
                    provider.get("model_call_count") or 0
                ),
                "retry_count": int(provider.get("retry_count") or 0),
                "repair_count": int(provider.get("repair_count") or 0),
                "finish_reason": str(
                    provider.get("finish_reason") or ""
                ),
                "latency_ms": provider.get("provider_latency_ms"),
                "validation_category": str(
                    (semantic.get("validation_diagnostics") or {}).get(
                        "category"
                    )
                    or ""
                ),
            }
            attempts.append(attempt)

            case_blockers: list[str] = []
            if attempt["final_passed"] is not True:
                case_blockers.append("deterministic_final_failed")
            if attempt["final_model_call_count"] != 0:
                case_blockers.append("final_model_call_detected")
            if attempt["model_call_count"] != 1:
                case_blockers.append("unified_model_call_count_invalid")
            if attempt["retry_count"]:
                case_blockers.append("retry_detected")
            if attempt["repair_count"]:
                case_blockers.append("repair_detected")
            if attempt["unified_passed"] is not case["expected_pass"]:
                case_blockers.append("verdict_mismatch")
            expected_finding = str(case["expected_finding"] or "")
            if (
                expected_finding
                and expected_finding not in canonical_finding_codes
            ):
                case_blockers.append("expected_finding_missing")
            previous = stable_components.get(case["case_id"])
            if previous is not None:
                stability_comparison_count += 1
                for key in stability_counts:
                    if previous[key] == components[key]:
                        stability_counts[key] += 1
                    else:
                        case_blockers.append(f"{key}_instability")
            stable_components[case["case_id"]] = components
            if case_blockers:
                blockers.extend(
                    f"{case['case_id']}:{item}" for item in case_blockers
                )
                break
        if blockers:
            break

    legal = [
        item for item in attempts
        if item["expected_pass"] is True
    ]
    illegal = [
        item for item in attempts
        if item["expected_pass"] is False
    ]
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "qualified" if not blockers and len(attempts) == 12 else "not_qualified",
        "source_tree_sha256": _source_tree_sha256(),
        "provider": {
            "model_name": str(client.model or ""),
            "configured": bool(client.api_key and client.model),
        },
        "finding_ontology_version": _FINDING_ONTOLOGY_VERSION,
        "finding_ownership_matrix": finding_ownership_matrix(),
        "contract_hashes": {
            "prompt_sha256": hashlib.sha256(
                _atomic_semantic_system_prompt().encode("utf-8")
            ).hexdigest(),
            "output_schema_sha256": _sha256({
                "top_level": sorted(_ATOMIC_SEMANTIC_OUTPUT_FIELDS),
                "goal_review": sorted(_ATOMIC_SEGMENT_FIELDS),
            }),
            "finding_ontology_sha256": _sha256(
                finding_ownership_matrix()
            ),
            "case_set_sha256": _sha256([
                {
                    "case_id": item["case_id"],
                    "expected_pass": item["expected_pass"],
                    "expected_finding": item["expected_finding"],
                    "input_sha256": _sha256(
                        _semantic_payload(
                            copy.deepcopy(item["response"]),
                            item["customer_message"],
                            item["copilot_context"],
                        )
                    ),
                }
                for item in cases
            ]),
        },
        "limits": {
            "case_count": 4,
            "repeat_per_case": repeat,
            "max_model_calls": 12,
            "fail_fast": True,
        },
        "summary": {
            "attempt_count": len(attempts),
            "legal_pass_count": sum(
                item["unified_passed"] is True for item in legal
            ),
            "legal_attempt_count": len(legal),
            "illegal_reject_count": sum(
                item["unified_passed"] is False for item in illegal
            ),
            "illegal_attempt_count": len(illegal),
            "final_model_call_count": sum(
                item["final_model_call_count"] for item in attempts
            ),
            "unified_model_call_count": sum(
                item["model_call_count"] for item in attempts
            ),
            "retry_count": sum(item["retry_count"] for item in attempts),
            "repair_count": sum(item["repair_count"] for item in attempts),
            "schema_error_count": sum(
                item["validation_category"] != "accepted"
                for item in attempts
            ),
            "timeout_count": sum(
                item["validation_category"] == "provider_error"
                for item in attempts
            ),
            "stability_comparison_count": stability_comparison_count,
            **{
                f"{key}_stable_comparison_count": value
                for key, value in stability_counts.items()
            },
        },
        "attempts": attempts,
        "blockers": blockers,
    }
    report["report_content_sha256"] = _sha256(report)
    qualified = (
        report["status"] == "qualified"
        and report["summary"]["legal_pass_count"] == 6
        and report["summary"]["illegal_reject_count"] == 6
        and report["summary"]["schema_error_count"] == 0
        and report["summary"]["timeout_count"] == 0
        and report["summary"]["final_model_call_count"] == 0
        and report["summary"]["unified_model_call_count"] == 12
        and report["summary"]["retry_count"] == 0
        and report["summary"]["repair_count"] == 0
        and report["summary"]["stability_comparison_count"] == 8
        and all(
            report["summary"][f"{key}_stable_comparison_count"] == 8
            for key in stability_counts
        )
    )
    return report, 0 if qualified else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    try:
        report, exit_code = run_qualification(repeat=args.repeat)
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "status": "invalid_run",
            "reason": str(exc),
        }, ensure_ascii=False))
        return 2
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "summary": report["summary"],
        "blockers": report["blockers"],
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
