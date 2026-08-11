"""Compare the model-first candidate against the legacy reply path."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any
from urllib import request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

from app.services.formal_knowledge_database_guard_service import (  # noqa: E402
    compare_formal_knowledge_fingerprints,
    fingerprint_formal_knowledge_tables,
    formal_kb_audit_hmac_key,
)
from app.services.claim_polarity_service import contains_asserted_claim  # noqa: E402
from app.services.claim_resolution_service import (  # noqa: E402
    valid_restricted_request_boundary,
)
from app.services.fact_type_alias_service import (  # noqa: E402
    canonical_material_composition_claim_type,
)
from app.services.no_evidence_reply_policy_service import (  # noqa: E402
    contains_unsupported_media_promise,
)


REPORT_SCHEMA_VERSION = "model-first-answer-comparison/v1"
GOAL_TRUTH_SCHEMA_VERSION = "model-first-goal-truth/v1"
_ANSWER_STRATEGY_RISK_RANK = {"low": 0, "medium": 1}
_RESTRICTED_POLICY_INTENT_KINDS = {
    "absolute_guarantee",
    "test_standard_request",
    "warranty_or_liability_request",
}
GOAL_FUNNEL_BREAKPOINTS = {
    "canonical_context_missing",
    "turn_understanding_goal_missing",
    "requested_claim_missing",
    "evidence_coverage_gap",
    "evidence_selection_gap",
    "admission_gap",
    "claim_resolution_gap",
    "answer_plan_gap",
    "render_gap",
    "final_audit_rejection",
    "semantic_audit_rejection",
    "dataset_runtime_semantic_mismatch",
}
_PROHIBITED_AGENT_FIELDS = {
    "accuracy_claim_allowed",
    "correct_answer",
    "expected_contract",
    "expected_claims",
    "forbidden_claims",
    "gold_reply",
    "pass_criteria",
    "reference_label",
    "reconstruction_alias",
    "required_actions",
    "rubric",
    "scoring_contract",
    "prohibited_outcomes",
    "source_class",
}
_SYSTEM_TONE_TERMS = (
    "帮您核对",
    "我先核对",
    "确认后回复",
    "确认后再回复",
    "请稍等",
    "转人工",
    "资料显示",
    "系统显示",
    "公司资料",
    "知识库",
    "RAG",
)
_ORDER_REQUEST_TERMS = ("提供订单号", "发一下订单号", "订单号发", "补充订单号")
_PRODUCT_REQUEST_TERMS = ("发商品链接", "提供商品链接", "发一下商品截图", "提供商品截图")


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _post_json(url: str, payload: dict[str, Any], timeout: int) -> tuple[int, dict[str, Any], int, str]:
    started = time.perf_counter()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            status = int(response.status)
        return status, parsed, round((time.perf_counter() - started) * 1000), ""
    except Exception as exc:
        return 0, {}, round((time.perf_counter() - started) * 1000), type(exc).__name__


def _get_json(url: str, timeout: int) -> dict[str, Any]:
    with request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _agent_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(scenario.get("api_request_template") or {})
    if not isinstance(payload, dict) or not payload:
        raise ValueError("api_request_template_missing")
    serialized = json.dumps(payload, ensure_ascii=False)
    for field in _PROHIBITED_AGENT_FIELDS:
        if f'"{field}"' in serialized:
            raise ValueError(f"evaluation_field_leakage:{field}")
    return payload


def _load_goal_truth(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != GOAL_TRUTH_SCHEMA_VERSION:
        raise ValueError("goal_truth_schema_mismatch")
    if payload.get("diagnostic_only") is not True or payload.get("agent_payload_allowed") is not False:
        raise ValueError("goal_truth_boundary_invalid")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("goal_truth_scenarios_invalid")
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError("goal_truth_scenario_invalid")
        scenario_uid = str(scenario.get("scenario_uid") or "").strip()
        source_turn_uid = str(scenario.get("source_turn_uid") or "").strip()
        goals = scenario.get("goals")
        if not scenario_uid or not source_turn_uid or not isinstance(goals, list):
            raise ValueError("goal_truth_scenario_contract_invalid")
        prepared: list[dict[str, Any]] = []
        for goal in goals:
            if not isinstance(goal, dict):
                raise ValueError("goal_truth_goal_invalid")
            item = {
                "scenario_uid": scenario_uid,
                "source_turn_uid": source_turn_uid,
                "source_provenance": str(scenario.get("source_provenance") or ""),
                "diagnostic_goal_ref": str(goal.get("diagnostic_goal_ref") or "").strip(),
                "expected_goal_kind": str(goal.get("expected_goal_kind") or "").strip(),
                "expected_claim_type": str(goal.get("expected_claim_type") or "").strip(),
                "expected_attribute_key": str(goal.get("expected_attribute_key") or "").strip(),
                "expected_source_span_sha256": str(
                    goal.get("expected_source_span_sha256") or ""
                ).strip(),
                "expected_source_span_start": goal.get("expected_source_span_start"),
                "expected_source_span_end": goal.get("expected_source_span_end"),
                "diagnostic_label_uncertain": goal.get("diagnostic_label_uncertain") is True,
            }
            if not item["diagnostic_goal_ref"] or item["expected_goal_kind"] not in {
                "customer_goal",
                "evidence_dependency",
                "service_action",
                "contextual_constraint",
            }:
                raise ValueError("goal_truth_goal_contract_invalid")
            source_hash = item["expected_source_span_sha256"]
            if source_hash and (
                len(source_hash) != 64
                or source_hash.lower() != source_hash
                or any(char not in "0123456789abcdef" for char in source_hash)
            ):
                raise ValueError("goal_truth_source_span_hash_invalid")
            source_start = item["expected_source_span_start"]
            source_end = item["expected_source_span_end"]
            if source_hash and (
                not isinstance(source_start, int)
                or isinstance(source_start, bool)
                or not isinstance(source_end, int)
                or isinstance(source_end, bool)
                or source_start < 0
                or source_end <= source_start
            ):
                raise ValueError("goal_truth_source_span_range_invalid")
            prepared.append(item)
        refs = [item["diagnostic_goal_ref"] for item in prepared]
        if len(refs) != len(set(refs)):
            raise ValueError("goal_truth_duplicate_goal_ref")
        by_scenario[scenario_uid] = prepared
    return by_scenario


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _turn_understanding(response: dict[str, Any]) -> dict[str, Any]:
    for container in (
        response,
        _as_dict(response.get("evidence_debug")),
        _as_dict(response.get("answer_trace")),
        _as_dict(response.get("context_used")),
    ):
        understanding = container.get("turn_understanding")
        if isinstance(understanding, dict):
            return understanding
    return {}


def _claim_type(value: Any) -> str:
    return canonical_material_composition_claim_type(value)


def _goal_matches(item: dict[str, Any], truth: dict[str, Any]) -> bool:
    expected_source_hash = str(
        truth.get("expected_source_span_sha256") or ""
    ).strip()
    observed_source_hash = str(item.get("source_span_sha256") or "").strip()
    if expected_source_hash and observed_source_hash:
        if expected_source_hash == observed_source_hash:
            return True
        expected_start = truth.get("expected_source_span_start")
        expected_end = truth.get("expected_source_span_end")
        observed_start = item.get("source_span_start")
        observed_end = item.get("source_span_end")
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (expected_start, expected_end, observed_start, observed_end)
        ):
            return (
                observed_start <= expected_start < expected_end <= observed_end
                or expected_start <= observed_start < observed_end <= expected_end
            )
        return False
    expected_ref = truth["diagnostic_goal_ref"]
    observed_ref = str(item.get("goal_ref") or item.get("diagnostic_goal_ref") or "").strip()
    if observed_ref and observed_ref == expected_ref:
        return True
    expected_claim = _claim_type(truth["expected_claim_type"])
    observed_claim = _claim_type(item.get("claim_type") or item.get("query_fact_type"))
    expected_attribute = str(truth["expected_attribute_key"] or "").strip().lower()
    observed_attribute = str(item.get("attribute_key") or "").strip().lower()
    if not expected_claim:
        return bool(expected_attribute and expected_attribute == observed_attribute)
    if observed_claim != expected_claim:
        return False
    return not expected_attribute or not observed_attribute or expected_attribute == observed_attribute


def _runtime_customer_goals(response: dict[str, Any]) -> list[dict[str, Any]]:
    understanding = _turn_understanding(response)
    declared = [
        item
        for item in _as_dict_list(understanding.get("customer_goals"))
        if str(item.get("goal_kind") or "customer_goal") == "customer_goal"
    ]
    if declared:
        return declared
    debug = _as_dict(response.get("evidence_debug"))
    primary = (
        understanding.get("query_fact_type")
        or response.get("query_fact_type")
        or debug.get("query_fact_type")
    )
    secondary = (
        understanding.get("secondary_fact_types")
        or debug.get("secondary_fact_types")
        or []
    )
    return [
        {"claim_type": item}
        for item in [primary, *secondary]
        if str(item or "").strip()
    ]


def _goal_funnel(
    scenario: dict[str, Any],
    response: dict[str, Any],
    truth_goals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    understanding = _turn_understanding(response)
    understanding_goals = _as_dict_list(understanding.get("customer_goals"))
    requested_claims = _as_dict_list(understanding.get("requested_claims"))
    if not requested_claims:
        requested_claims = _as_dict_list(
            _as_dict(response.get("minimal_decision_context")).get("requested_claims")
        )
    runtime_customer_goals = _runtime_customer_goals(response)
    selected = _as_dict_list(response.get("selected_evidence"))
    minimal = _as_dict(response.get("minimal_decision_context"))
    admitted = _as_dict_list(minimal.get("admitted_evidence") or minimal.get("admitted_direct_facts"))
    resolutions = _as_dict_list(minimal.get("claim_resolutions"))
    composer = _as_dict(response.get("model_first_answer_composer"))
    answer_plan = _as_dict(composer.get("answer_plan"))
    plan_segments = _as_dict_list(
        answer_plan.get("segments")
        or composer.get("clauses")
        or composer.get("factual_clauses")
    )
    reply = str(response.get("suggested_reply") or "")
    canonical_present = bool(
        str((scenario.get("api_request_template") or {}).get("message") or "").strip()
        or str(scenario.get("current_buyer_message") or "").strip()
    )
    rows: list[dict[str, Any]] = []
    for truth in truth_goals:
        observed_understanding = any(
            _goal_matches(item, truth)
            for item in [*understanding_goals, *runtime_customer_goals]
        )
        observed_requested = any(_goal_matches(item, truth) for item in requested_claims)
        observed_resolution = any(_goal_matches(item, truth) for item in resolutions)
        candidate_count = sum(_goal_matches(item, truth) for item in _as_dict_list(
            _as_dict(response.get("evidence_debug")).get("candidate_evidence")
            or _as_dict(response.get("evidence_debug")).get("product_facts")
        ))
        selected_count = sum(_goal_matches(item, truth) for item in selected)
        admitted_count = sum(_goal_matches(item, truth) for item in admitted)
        plan_count = sum(_goal_matches(item, truth) for item in plan_segments)
        matching_resolutions = [
            item for item in resolutions if _goal_matches(item, truth)
        ]
        rendered_count = sum(
            1
            for resolution in matching_resolutions
            for clause in _as_dict_list(composer.get("clauses"))
            if str(clause.get("goal_ref") or "").strip()
            == str(resolution.get("claim_uid") or "").strip()
        )
        breakpoint: str | None = None
        if not canonical_present:
            breakpoint = "canonical_context_missing"
        elif truth["expected_goal_kind"] == "customer_goal" and not observed_understanding:
            breakpoint = (
                "dataset_runtime_semantic_mismatch"
                if truth["diagnostic_label_uncertain"]
                else "turn_understanding_goal_missing"
            )
        elif not observed_requested:
            breakpoint = "requested_claim_missing"
        elif truth["expected_goal_kind"] == "customer_goal" and not observed_resolution:
            breakpoint = "claim_resolution_gap"
        elif selected_count and not admitted_count:
            breakpoint = "admission_gap"
        elif admitted_count and not plan_count and composer.get("status") == "accepted":
            breakpoint = "answer_plan_gap"
        elif plan_count and not rendered_count:
            breakpoint = "render_gap"
        elif (response.get("final_answer_audit") or {}).get("passed") is False:
            breakpoint = "final_audit_rejection"
        elif (response.get("final_semantic_fit_audit") or {}).get("passed") is False:
            breakpoint = "semantic_audit_rejection"
        if breakpoint is not None and breakpoint not in GOAL_FUNNEL_BREAKPOINTS:
            raise ValueError("goal_funnel_breakpoint_invalid")
        rows.append({
            **truth,
            "observed_in_canonical_turn": canonical_present,
            "observed_in_turn_understanding": observed_understanding,
            "observed_in_requested_claims": observed_requested,
            "observed_in_claim_resolution": observed_resolution,
            "candidate_evidence_count": candidate_count,
            "selected_evidence_count": selected_count,
            "admitted_evidence_count": admitted_count,
            "answer_plan_segment_count": plan_count,
            "rendered_clause_count": rendered_count,
            "final_audit_status": (response.get("final_answer_audit") or {}).get("passed"),
            "semantic_audit_status": (response.get("final_semantic_fit_audit") or {}).get("passed"),
            "reply_nonempty": bool(reply),
            "earliest_breakpoint": breakpoint,
        })
    return rows


def _goal_recall_summary(
    rows: list[dict[str, Any]],
    runtime_observations: list[dict[str, Any]],
) -> dict[str, Any]:
    scored = [
        row for row in rows
        if row["expected_goal_kind"] == "customer_goal"
        and not row["diagnostic_label_uncertain"]
    ]
    observed = [row for row in scored if row["observed_in_turn_understanding"]]
    resolved = [row for row in scored if row.get("observed_in_claim_resolution") is True]
    truth_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for row in scored:
        truth_by_scenario.setdefault(row["scenario_uid"], []).append(row)
    runtime_goal_count = 0
    matched_runtime_goal_count = 0
    unexpected_runtime_goals: list[dict[str, str]] = []
    for observation in runtime_observations:
        scenario_uid = str(observation.get("scenario_uid") or "")
        truth = truth_by_scenario.get(scenario_uid, [])
        for item in observation.get("customer_goals") or []:
            if not isinstance(item, dict):
                continue
            runtime_goal_count += 1
            if any(_goal_matches(item, expected) for expected in truth):
                matched_runtime_goal_count += 1
            else:
                unexpected_runtime_goals.append({
                    "scenario_uid": scenario_uid,
                    "claim_type": _claim_type(item.get("claim_type") or item.get("query_fact_type")),
                    "attribute_key": str(item.get("attribute_key") or ""),
                })
    target = [
        row for row in scored
        if row["earliest_breakpoint"] in {
            "turn_understanding_goal_missing",
            "requested_claim_missing",
        }
    ]
    return {
        "customer_goal_recall": {
            "numerator": len(observed),
            "denominator": len(scored),
            "rate": len(observed) / len(scored) if scored else None,
        },
        "customer_goal_precision": {
            "numerator": matched_runtime_goal_count,
            "denominator": runtime_goal_count,
            "rate": (
                matched_runtime_goal_count / runtime_goal_count
                if runtime_goal_count else None
            ),
        },
        "customer_goal_resolution_coverage": {
            "numerator": len(resolved),
            "denominator": len(scored),
            "rate": len(resolved) / len(scored) if scored else None,
        },
        "unexpected_runtime_goals": unexpected_runtime_goals,
        "target_denominator": len(target),
        "target_goal_refs": sorted(row["diagnostic_goal_ref"] for row in target),
        "diagnostic_uncertain_count": sum(
            row["diagnostic_label_uncertain"] for row in rows
        ),
    }


def _runtime_contract(
    runtime: dict[str, Any],
    *,
    mode: str,
    expected_commit: str,
    expected_source_hash: str,
    expected_model: str,
) -> list[str]:
    findings: list[str] = []
    flags = runtime.get("feature_flags") if isinstance(runtime.get("feature_flags"), dict) else {}
    enabled = mode == "ON"
    if (runtime.get("readiness") or {}).get("ready") is not True:
        findings.append(f"{mode.lower()}_runtime_not_ready")
    if runtime.get("source_tree_drift") is not False:
        findings.append(f"{mode.lower()}_source_tree_drift")
    if runtime.get("formal_knowledge_query_only") is not True:
        findings.append(f"{mode.lower()}_formal_knowledge_not_query_only")
    if expected_commit and runtime.get("runtime_commit") != expected_commit:
        findings.append(f"{mode.lower()}_commit_mismatch")
    if expected_source_hash and runtime.get("source_tree_sha256") != expected_source_hash:
        findings.append(f"{mode.lower()}_source_hash_mismatch")
    if expected_model and runtime.get("formal_model") != expected_model:
        findings.append(f"{mode.lower()}_model_mismatch")
    if bool(flags.get("formal_evidence_convergence")) is not enabled:
        findings.append(f"{mode.lower()}_convergence_flag_mismatch")
    if bool(flags.get("model_first_answer_composer")) is not enabled:
        findings.append(f"{mode.lower()}_composer_flag_mismatch")
    return findings


def _issue_text(response: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("block_reasons", "guard_warnings", "policy_warnings"):
        values.extend(str(item) for item in response.get(key) or [])
    for key in ("final_answer_audit", "final_semantic_fit_audit"):
        audit = response.get(key) or {}
        values.extend(str(item) for item in audit.get("issues") or [])
    return "\n".join(values)


def _expected_claim_diagnostics(
    scenario: dict[str, Any],
    response: dict[str, Any],
    reply: str,
) -> dict[str, Any]:
    supported = [
        item for item in scenario.get("expected_claims") or []
        if isinstance(item, dict) and item.get("expected_status") == "supported"
    ]
    unresolved = [
        item for item in scenario.get("expected_claims") or []
        if isinstance(item, dict) and item.get("expected_status") in {"unresolved", "conflicting"}
    ]

    def covered(claim: dict[str, Any]) -> bool:
        points = [str(item).strip() for item in claim.get("required_answer_points") or [] if str(item).strip()]
        return bool(points) and all(point in reply for point in points)

    supported_hits = sum(covered(item) for item in supported)
    composer = response.get("model_first_answer_composer") or {}
    declared_unresolved = {
        str(item) for item in composer.get("unresolved_claim_types") or []
    }
    unresolved_hits = sum(
        str(item.get("claim_type") or "") in declared_unresolved or covered(item)
        for item in unresolved
    )
    return {
        "dataset_supported_claim_numerator": supported_hits,
        "dataset_supported_claim_denominator": len(supported),
        "dataset_unresolved_handling_numerator": unresolved_hits,
        "dataset_unresolved_handling_denominator": len(unresolved),
        "supported_complete": not supported or supported_hits == len(supported),
        "unresolved_complete": not unresolved or unresolved_hits == len(unresolved),
        "dataset_partial_answer_expected": bool(supported and unresolved),
    }


def _goal_ref_partial_answer_diagnostics(
    response: dict[str, Any],
) -> dict[str, Any]:
    understanding = _turn_understanding(response)
    context = _as_dict(response.get("minimal_decision_context"))
    composer = _as_dict(response.get("model_first_answer_composer"))
    composer_eligibility = _as_dict(composer.get("input_eligibility"))
    goals = [
        item
        for item in _as_dict_list(understanding.get("customer_goals"))
        if str(item.get("goal_kind") or "").strip() == "customer_goal"
    ]
    resolutions = _as_dict_list(context.get("claim_resolutions"))
    clauses = _as_dict_list(composer.get("clauses"))
    admitted_uids = {
        str(item.get("evidence_uid") or "").strip()
        for item in _as_dict_list(
            context.get("admitted_evidence")
            or context.get("admitted_direct_facts")
        )
        if str(item.get("evidence_uid") or "").strip()
    }
    used_evidence_uids = {
        str(item).strip()
        for item in composer.get("used_evidence_uids") or []
        if str(item).strip()
    }
    reasons: list[str] = []

    if understanding.get("goal_understanding_status") != "valid":
        reasons.append("authoritative_goal_understanding_invalid")

    goal_ref_counts = Counter(
        str(item.get("goal_ref") or "").strip() for item in goals
    )
    missing_goal_ref_count = goal_ref_counts.pop("", 0)
    duplicate_goal_ref_count = sum(
        count - 1 for count in goal_ref_counts.values() if count > 1
    )
    if missing_goal_ref_count:
        reasons.append("authoritative_goal_ref_missing")
    if duplicate_goal_ref_count:
        reasons.append("authoritative_goal_ref_duplicate")
    goals_by_ref = {
        ref: next(item for item in goals if item.get("goal_ref") == ref)
        for ref, count in goal_ref_counts.items()
        if count == 1
    }

    resolutions_by_goal_ref: dict[str, list[dict[str, Any]]] = {}
    resolutions_by_claim_uid: dict[str, list[dict[str, Any]]] = {}
    for resolution in resolutions:
        goal_ref = str(resolution.get("goal_ref") or "").strip()
        claim_uid = str(resolution.get("claim_uid") or "").strip()
        if goal_ref:
            resolutions_by_goal_ref.setdefault(goal_ref, []).append(resolution)
        if claim_uid:
            resolutions_by_claim_uid.setdefault(claim_uid, []).append(resolution)

    unknown_resolution_goal_ref_count = sum(
        len(items)
        for ref, items in resolutions_by_goal_ref.items()
        if ref not in goals_by_ref
        and any(
            str(item.get("goal_kind") or "").strip() == "customer_goal"
            for item in items
        )
    )
    duplicate_resolution_count = sum(
        len(resolutions_by_goal_ref.get(ref, [])) - 1
        for ref in goals_by_ref
        if len(resolutions_by_goal_ref.get(ref, [])) > 1
    )
    duplicate_claim_uid_count = sum(
        len(items) - 1
        for items in resolutions_by_claim_uid.values()
        if len(items) > 1
    )
    if unknown_resolution_goal_ref_count:
        reasons.append("unknown_resolution_goal_ref")
    if duplicate_resolution_count:
        reasons.append("customer_goal_resolution_duplicate")
    if duplicate_claim_uid_count:
        reasons.append("resolution_claim_uid_duplicate")

    supported: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    missing_resolution_count = 0
    resolution_claim_uid_missing_count = 0
    for goal_ref in sorted(goals_by_ref):
        matching = resolutions_by_goal_ref.get(goal_ref, [])
        if len(matching) != 1:
            if not matching:
                missing_resolution_count += 1
            continue
        resolution = matching[0]
        if str(resolution.get("goal_kind") or "").strip() != "customer_goal":
            reasons.append("customer_goal_resolution_kind_invalid")
            continue
        claim_uid = str(resolution.get("claim_uid") or "").strip()
        if not claim_uid:
            resolution_claim_uid_missing_count += 1
            continue
        status = str(resolution.get("status") or "").strip()
        if status == "supported":
            supported.append(resolution)
        elif status in {"unresolved", "conflicting", "prohibited"}:
            unresolved.append(resolution)
        else:
            reasons.append("customer_goal_resolution_status_invalid")
    if missing_resolution_count:
        reasons.append("customer_goal_resolution_missing")
    if resolution_claim_uid_missing_count:
        reasons.append("resolution_claim_uid_missing")

    clause_ref_counts: Counter[str] = Counter()
    multiple_goal_ref_clause_count = 0
    missing_clause_goal_ref_count = 0
    for clause in clauses:
        raw_ref = clause.get("goal_ref")
        if not isinstance(raw_ref, str):
            multiple_goal_ref_clause_count += int(
                isinstance(raw_ref, (list, tuple, set))
            )
            missing_clause_goal_ref_count += int(raw_ref is None)
            continue
        ref = raw_ref.strip()
        if not ref:
            missing_clause_goal_ref_count += 1
            continue
        clause_ref_counts[ref] += 1
    duplicate_goal_ref_clause_count = sum(
        count - 1 for count in clause_ref_counts.values() if count > 1
    )
    if multiple_goal_ref_clause_count:
        reasons.append("clause_multiple_goal_refs")
    if missing_clause_goal_ref_count:
        reasons.append("clause_goal_ref_missing")
    if duplicate_goal_ref_clause_count:
        reasons.append("duplicate_goal_ref_clause")

    known_claim_uids = set(resolutions_by_claim_uid)
    unknown_goal_ref_count = sum(
        count
        for ref, count in clause_ref_counts.items()
        if ref not in known_claim_uids
    )
    if unknown_goal_ref_count:
        reasons.append("unknown_goal_ref_clause")

    non_customer_goal_clause_count = 0
    service_action_fact_clause_count = 0
    media_request_fact_clause_count = 0
    for ref, count in clause_ref_counts.items():
        matching = resolutions_by_claim_uid.get(ref, [])
        if len(matching) != 1:
            continue
        goal_kind = str(matching[0].get("goal_kind") or "").strip()
        if goal_kind == "customer_goal":
            continue
        matching_clauses = [
            clause
            for clause in clauses
            if isinstance(clause.get("goal_ref"), str)
            and clause.get("goal_ref").strip() == ref
        ]
        factual_count = sum(
            str(clause.get("clause_kind") or "").strip()
            in {"supported_fact", "unresolved"}
            for clause in matching_clauses
        )
        non_customer_goal_clause_count += factual_count
        service_action_fact_clause_count += (
            factual_count if goal_kind == "service_action" else 0
        )
        media_request_fact_clause_count += (
            factual_count if goal_kind == "media_request" else 0
        )
    if non_customer_goal_clause_count:
        reasons.append("non_customer_goal_rendered_as_fact")

    wrong_clause_kind_count = 0
    unsupported_evidence_ref_count = 0
    unknown_evidence_ref_count = 0
    supported_hits = 0
    unresolved_hits = 0

    def matching_clauses(resolution: dict[str, Any]) -> list[dict[str, Any]]:
        claim_uid = str(resolution.get("claim_uid") or "").strip()
        return [
            clause
            for clause in clauses
            if isinstance(clause.get("goal_ref"), str)
            and clause.get("goal_ref").strip() == claim_uid
        ]

    def preserves_allowed_inference_contract(
        resolution: dict[str, Any],
        clause: dict[str, Any],
    ) -> bool:
        options = _as_dict_list(resolution.get("eligible_policy_options"))
        selected_refs = {
            str(item).strip()
            for item in clause.get("inference_policy_refs") or []
            if str(item).strip()
        }
        if clause.get("clause_kind") != "allowed_inference" or len(selected_refs) != 1:
            return False
        matching_options = [
            option
            for option in options
            if str(option.get("policy_ref") or "").strip() in selected_refs
        ]
        if len(matching_options) != 1:
            return False
        option = matching_options[0]
        expected_premises = [
            str(item).strip()
            for item in option.get("premise_evidence_refs") or []
            if str(item).strip()
        ]
        actual_evidence_refs = [
            str(item).strip()
            for item in clause.get("evidence_uids") or []
            if str(item).strip()
        ]
        actual_premise_refs = [
            str(item).strip()
            for item in clause.get("premise_evidence_uids") or []
            if str(item).strip()
        ]
        provenance = _as_dict(option.get("option_provenance"))
        empty_premise_is_authoritative = (
            not expected_premises
            and provenance.get("premise_owner") == "authoritative_customer_goal"
        )
        return bool(
            option.get("review_only") is True
            and provenance.get("policy_owner") == "domain_policy_pack"
            and provenance.get("filter_owner") == "claim_resolution"
            and (
                provenance.get("premise_owner") == "admitted_answer_context"
                or empty_premise_is_authoritative
            )
            and str(option.get("applicable_goal_ref") or "").strip()
            == str(resolution.get("goal_ref") or "").strip()
            and actual_evidence_refs == expected_premises
            and actual_premise_refs == expected_premises
            and (
                bool(expected_premises)
                or empty_premise_is_authoritative
            )
            and set(actual_premise_refs).issubset(admitted_uids)
            and clause.get("inference_review_only") is True
            and str(clause.get("scope_qualifier") or "").strip()
            == str(option.get("allowed_scope") or "").strip()
            and str(clause.get("requested_claim_risk_level") or "").strip()
            == str(option.get("requested_claim_risk") or "").strip()
            and str(clause.get("inference_risk_level") or "").strip()
            == str(option.get("answer_strategy_risk") or "").strip()
            and str(clause.get("maximum_risk_level") or "").strip()
            == str(option.get("maximum_risk") or "").strip()
            and [
                str(item).strip()
                for item in clause.get("required_qualifiers") or []
                if str(item).strip()
            ]
            == [
                str(item).strip()
                for item in option.get("required_qualifiers") or []
                if str(item).strip()
            ]
            and [
                str(item).strip()
                for item in clause.get("prohibited_extensions") or []
                if str(item).strip()
            ]
            == [
                str(item).strip()
                for item in option.get("forbidden_claim_families") or []
                if str(item).strip()
            ]
            and _as_dict(clause.get("restricted_request_boundary"))
            == _as_dict(option.get("restricted_request_boundary"))
        )

    def preserves_restricted_boundary(
        resolution: dict[str, Any],
        clause: dict[str, Any],
    ) -> bool:
        boundary = _as_dict(resolution.get("restricted_request_boundary"))
        selected_refs = {
            str(item).strip()
            for item in clause.get("inference_policy_refs") or []
            if str(item).strip()
        }
        return bool(
            preserves_allowed_inference_contract(resolution, clause)
            and valid_restricted_request_boundary(boundary)
            and _as_dict(clause.get("restricted_request_boundary"))
            == boundary
            and clause.get("inference_review_only") is True
            and str(clause.get("requested_claim_risk_level") or "").strip()
            == str(resolution.get("requested_claim_risk") or "").strip()
            and len(selected_refs) == 1
        )

    for resolution in supported:
        matched = matching_clauses(resolution)
        if len(matched) != 1:
            continue
        clause = matched[0]
        if str(clause.get("clause_kind") or "").strip() != "supported_fact":
            wrong_clause_kind_count += 1
            continue
        allowed = {
            str(item).strip()
            for item in resolution.get("evidence_uids") or []
            if str(item).strip()
        }
        referenced = {
            str(item).strip()
            for item in clause.get("evidence_uids") or []
            if str(item).strip()
        }
        unsupported = referenced - allowed
        unknown = referenced - admitted_uids
        unsupported_evidence_ref_count += len(unsupported)
        unknown_evidence_ref_count += len(unknown)
        if (
            allowed
            and referenced
            and not unsupported
            and not unknown
            and referenced.issubset(used_evidence_uids)
        ):
            supported_hits += 1

    for resolution in unresolved:
        matched = matching_clauses(resolution)
        if len(matched) != 1:
            continue
        clause = matched[0]
        if preserves_restricted_boundary(resolution, clause):
            unresolved_hits += 1
            continue
        if preserves_allowed_inference_contract(resolution, clause):
            unresolved_hits += 1
            continue
        if str(clause.get("clause_kind") or "").strip() != "unresolved":
            wrong_clause_kind_count += 1
            continue
        referenced = {
            str(item).strip()
            for item in clause.get("evidence_uids") or []
            if str(item).strip()
        }
        unsupported_evidence_ref_count += len(referenced)
        unknown_evidence_ref_count += len(referenced - admitted_uids)
        if not referenced:
            unresolved_hits += 1

    if wrong_clause_kind_count:
        reasons.append("wrong_clause_kind")
    if unsupported_evidence_ref_count:
        reasons.append("unsupported_evidence_ref")
    if unknown_evidence_ref_count:
        reasons.append("unknown_evidence_ref")

    shadow_candidate_formal_use_count = sum(
        _as_dict(response.get(field)).get("used_for_final_reply") is True
        for field in (
            "supervisor_candidate_preview",
            "llm_decision_shadow",
            "grounded_reasoning_shadow",
            "answer_memory_shadow",
            "evidence_action_shadow",
        )
    )
    if shadow_candidate_formal_use_count:
        reasons.append("shadow_candidate_formal_use")
    if composer.get("status") != "accepted":
        reasons.append("composer_not_accepted")
    if composer.get("used_for_final_reply") is not True:
        reasons.append("composer_not_used_for_final_reply")
    if composer.get("can_change_can_send") is not False:
        reasons.append("composer_can_change_can_send")
    if composer.get("can_send") is not False:
        reasons.append("composer_can_send_invalid")
    if composer.get("requires_human_review") is not True:
        reasons.append("composer_human_review_missing")
    if (response.get("final_answer_audit") or {}).get("passed") is not True:
        reasons.append("final_audit_failed")
    if response.get("can_send") is not False:
        reasons.append("can_send_pollution")
    if response.get("requires_human_review") is not True:
        reasons.append("human_review_contract_missing")
    if str(response.get("sendable_reply") or ""):
        reasons.append("sendable_reply_pollution")
    if not goals:
        reasons.append("partial_answer_denominator_empty")

    applicable = bool(supported and unresolved)
    supported_rate = supported_hits / len(supported) if supported else None
    unresolved_rate = unresolved_hits / len(unresolved) if unresolved else None
    customer_goal_clause_numerator = supported_hits + unresolved_hits
    customer_goal_clause_denominator = len(supported) + len(unresolved)
    dependency_coverage = _as_dict(
        composer_eligibility.get("dependency_evidence_link_coverage")
    )
    return {
        "renderable_customer_goal_count": int(
            composer_eligibility.get(
                "renderable_customer_goal_count",
                len(goals),
            )
            or 0
        ),
        "supporting_dependency_count": int(
            composer_eligibility.get("supporting_dependency_count") or 0
        ),
        "customer_goal_clause_coverage_numerator": (
            customer_goal_clause_numerator
        ),
        "customer_goal_clause_coverage_denominator": (
            customer_goal_clause_denominator
        ),
        "customer_goal_clause_coverage_rate": (
            customer_goal_clause_numerator
            / customer_goal_clause_denominator
            if customer_goal_clause_denominator
            else None
        ),
        "dependency_evidence_link_coverage_numerator": int(
            dependency_coverage.get("numerator") or 0
        ),
        "dependency_evidence_link_coverage_denominator": int(
            dependency_coverage.get("denominator") or 0
        ),
        "dependency_evidence_link_coverage_rate": (
            dependency_coverage.get("rate")
        ),
        "unknown_goal_kind_count": int(
            composer_eligibility.get("unknown_goal_kind_count") or 0
        ),
        "authoritative_customer_goal_count": len(goals),
        "supported_goal_count": len(supported),
        "supported_clause_count": sum(
            len(matching_clauses(item)) for item in supported
        ),
        "supported_goal_coverage_numerator": supported_hits,
        "supported_goal_coverage_denominator": len(supported),
        "supported_goal_coverage_rate": supported_rate,
        "unresolved_goal_count": len(unresolved),
        "unresolved_clause_count": sum(
            len(matching_clauses(item)) for item in unresolved
        ),
        "unresolved_goal_coverage_numerator": unresolved_hits,
        "unresolved_goal_coverage_denominator": len(unresolved),
        "unresolved_goal_coverage_rate": unresolved_rate,
        "unknown_goal_ref_count": unknown_goal_ref_count,
        "duplicate_goal_ref_clause_count": duplicate_goal_ref_clause_count,
        "wrong_clause_kind_count": wrong_clause_kind_count,
        "unsupported_evidence_ref_count": unsupported_evidence_ref_count,
        "unknown_evidence_ref_count": unknown_evidence_ref_count,
        "non_customer_goal_clause_count": non_customer_goal_clause_count,
        "service_action_fact_clause_count": service_action_fact_clause_count,
        "media_request_fact_clause_count": media_request_fact_clause_count,
        "multiple_goal_ref_clause_count": multiple_goal_ref_clause_count,
        "missing_clause_goal_ref_count": missing_clause_goal_ref_count,
        "missing_goal_ref_count": missing_goal_ref_count,
        "duplicate_goal_ref_count": duplicate_goal_ref_count,
        "missing_resolution_count": missing_resolution_count,
        "duplicate_resolution_count": duplicate_resolution_count,
        "duplicate_claim_uid_count": duplicate_claim_uid_count,
        "unknown_resolution_goal_ref_count": (
            unknown_resolution_goal_ref_count
        ),
        "resolution_claim_uid_missing_count": (
            resolution_claim_uid_missing_count
        ),
        "shadow_candidate_formal_use_count": (
            shadow_candidate_formal_use_count
        ),
        "partial_answer_applicable": applicable,
        "partial_answer_contract_pass": (
            None
            if not goals
            else False
            if reasons
            else (
                supported_rate == 1.0 and unresolved_rate == 1.0
                if applicable
                else None
            )
        ),
        "partial_answer_contract_reasons": sorted(set(reasons)),
        "runtime_supported_claim_numerator": supported_hits,
        "runtime_supported_claim_denominator": len(supported),
        "runtime_unresolved_handling_numerator": unresolved_hits,
        "runtime_unresolved_handling_denominator": len(unresolved),
    }


def _runtime_claim_diagnostics(response: dict[str, Any]) -> dict[str, Any]:
    return _goal_ref_partial_answer_diagnostics(response)


def _policy_contract_diagnostics(response: dict[str, Any]) -> dict[str, Any]:
    context = _as_dict(response.get("minimal_decision_context"))
    resolutions = _as_dict_list(context.get("claim_resolutions"))
    policies = _as_dict_list(context.get("bounded_inference_policies"))
    composer = _as_dict(response.get("model_first_answer_composer"))
    clauses = _as_dict_list(composer.get("clauses"))

    policies_by_intent: dict[str, list[dict[str, Any]]] = {}
    policies_by_ref: dict[str, dict[str, Any]] = {}
    for policy in policies:
        intent_ref = str(policy.get("policy_intent_ref") or "").strip()
        policy_ref = str(policy.get("policy_ref") or "").strip()
        if intent_ref:
            policies_by_intent.setdefault(intent_ref, []).append(policy)
        if policy_ref:
            policies_by_ref[policy_ref] = policy

    nominated = [
        item
        for item in resolutions
        if str(item.get("policy_intent_ref") or "").strip()
    ]
    eligible = [
        item
        for item in resolutions
        if (
            bool(item.get("eligible_policy_options"))
            or item.get("support_basis") == "bounded_inference"
            and (
                item.get("bounded_inference_policy")
                in {"allowed", "review_required"}
            )
            or (
                item.get("status") == "unresolved"
                and str(
                    item.get("policy_intent_ref") or ""
                ).strip()
            )
        )
    ]
    valid_claim_uids: set[str] = set()
    for resolution in nominated:
        intent_ref = str(resolution.get("policy_intent_ref") or "").strip()
        candidates = policies_by_intent.get(intent_ref, [])
        if len(candidates) != 1:
            continue
        policy = candidates[0]
        restricted_boundary = _as_dict(
            resolution.get("restricted_request_boundary")
        )
        if restricted_boundary:
            if (
                valid_restricted_request_boundary(restricted_boundary)
                and resolution.get("status") == "unresolved"
                and str(
                    resolution.get("requested_claim_risk") or ""
                ).strip()
                == str(
                    restricted_boundary.get("requested_claim_risk") or ""
                ).strip()
                and intent_ref
                == str(
                    restricted_boundary.get("policy_intent_ref") or ""
                ).strip()
                == str(policy.get("policy_intent_ref") or "").strip()
                and str(
                    resolution.get("policy_goal_family") or ""
                ).strip()
                == str(
                    restricted_boundary.get("policy_goal_family") or ""
                ).strip()
                == str(policy.get("goal_family") or "").strip()
                and str(
                    resolution.get("policy_intent_kind") or ""
                ).strip()
                == str(
                    restricted_boundary.get("policy_intent_kind") or ""
                ).strip()
                == str(policy.get("intent_kind") or "").strip()
            ):
                claim_uid = str(
                    resolution.get("claim_uid") or ""
                ).strip()
                if claim_uid:
                    valid_claim_uids.add(claim_uid)
            continue
        matching_options = [
            option
            for option in _as_dict_list(
                resolution.get("eligible_policy_options")
            )
            if str(option.get("policy_intent_ref") or "").strip()
            == intent_ref
            and str(option.get("policy_ref") or "").strip()
            == str(policy.get("policy_ref") or "").strip()
        ]
        option_narrowing_valid = bool(
            len(matching_options) == 1
            and str(
                matching_options[0].get("goal_family") or ""
            ).strip()
            == str(policy.get("goal_family") or "").strip()
            and str(
                matching_options[0].get("intent_kind") or ""
            ).strip()
            == str(policy.get("intent_kind") or "").strip()
            and _as_dict(
                matching_options[0].get("option_provenance")
            ).get("intent_narrowed") is True
        )
        if (
            not option_narrowing_valid
            and (
                str(
                    resolution.get("policy_goal_family") or ""
                ).strip()
                != str(policy.get("goal_family") or "").strip()
                or str(
                    resolution.get("policy_intent_kind") or ""
                ).strip()
                != str(policy.get("intent_kind") or "").strip()
                or str(
                    resolution.get("maximum_risk_level") or ""
                ).strip()
                != str(policy.get("maximum_risk_level") or "").strip()
                or str(
                    resolution.get("inference_risk_level") or ""
                ).strip()
                not in {"low", "medium"}
                or resolution.get("inference_review_only") is not True
            )
        ):
            continue
        claim_uid = str(resolution.get("claim_uid") or "").strip()
        if claim_uid:
            valid_claim_uids.add(claim_uid)

    bounded = [
        item
        for item in resolutions
        if item.get("support_basis") == "bounded_inference"
    ]
    attributed = 0
    premise_complete = 0
    scope_complete = 0
    clauses_by_goal = {
        str(item.get("goal_ref") or "").strip(): item
        for item in clauses
        if str(item.get("goal_ref") or "").strip()
    }
    for resolution in bounded:
        claim_uid = str(resolution.get("claim_uid") or "").strip()
        clause = clauses_by_goal.get(claim_uid, {})
        evidence_uids = {
            str(item).strip()
            for item in resolution.get("evidence_uids") or []
            if str(item).strip()
        }
        premise_uids = {
            str(item).strip()
            for item in resolution.get("premise_evidence_uids") or []
            if str(item).strip()
        }
        policy_refs = {
            str(item).strip()
            for item in resolution.get("inference_policy_refs") or []
            if str(item).strip()
        }
        required_qualifiers = {
            str(item).strip()
            for item in resolution.get("required_qualifiers") or []
            if str(item).strip()
        }
        premise_ok = bool(
            premise_uids
            and premise_uids == evidence_uids
            and premise_uids
            == {
                str(item).strip()
                for item in clause.get("evidence_uids") or []
                if str(item).strip()
            }
        )
        scope_qualifier = str(
            resolution.get("scope_qualifier") or ""
        ).strip()
        scope_ok = bool(
            scope_qualifier
            and required_qualifiers
            and resolution.get("inference_review_only") is True
            and clause.get("inference_review_only") is True
            and str(clause.get("inference_risk_level") or "").strip()
            == str(
                resolution.get("inference_risk_level") or ""
            ).strip()
            and str(clause.get("maximum_risk_level") or "").strip()
            == str(
                resolution.get("maximum_risk_level") or ""
            ).strip()
            and scope_qualifier
            == str(clause.get("scope_qualifier") or "").strip()
            and required_qualifiers
            == {
                str(item).strip()
                for item in clause.get("required_qualifiers") or []
                if str(item).strip()
            }
        )
        if premise_ok:
            premise_complete += 1
        if scope_ok:
            scope_complete += 1
        if (
            composer.get("status") == "accepted"
            and resolution.get("status") == "supported"
            and claim_uid in valid_claim_uids
            and clause.get("clause_kind") == "allowed_inference"
            and policy_refs
            == {
                str(item).strip()
                for item in clause.get("inference_policy_refs") or []
                if str(item).strip()
            }
            and premise_ok
            and scope_ok
        ):
            attributed += 1

    valid_eligible = sum(
        str(item.get("claim_uid") or "").strip() in valid_claim_uids
        for item in eligible
    )
    admitted_uids = {
        str(item.get("evidence_uid") or "").strip()
        for item in _as_dict_list(context.get("admitted_evidence"))
        if str(item.get("evidence_uid") or "").strip()
    }
    eligible_option_goal_count = 0
    eligible_option_total_count = 0
    selected_policy_count = 0
    selected_policy_valid_count = 0
    selected_attributed_count = 0
    selected_premise_count = 0
    selected_scope_count = 0
    restricted_candidates = [
        resolution
        for resolution in resolutions
        if (
            str(
                resolution.get("policy_intent_kind") or ""
            ).strip()
            in _RESTRICTED_POLICY_INTENT_KINDS
            or bool(resolution.get("restricted_request_boundary"))
        )
    ]
    restricted_boundary_preserved_count = sum(
        bool(
            valid_restricted_request_boundary(
                resolution.get("restricted_request_boundary")
            )
            and resolution.get("status") == "unresolved"
            and str(
                resolution.get("requested_claim_risk") or ""
            ).strip()
            == str(
                _as_dict(
                    resolution.get("restricted_request_boundary")
                ).get("requested_claim_risk")
                or ""
            ).strip()
        )
        for resolution in restricted_candidates
    )
    risk_separation_count = 0
    risk_separation_total = 0
    for resolution in eligible:
        raw_options = _as_dict_list(
            resolution.get("eligible_policy_options")
        )
        valid_options: dict[str, dict[str, Any]] = {}
        for option in raw_options:
            policy_ref = str(option.get("policy_ref") or "").strip()
            policy = policies_by_ref.get(policy_ref, {})
            premise_uids = {
                str(item).strip()
                for item in option.get("premise_evidence_refs") or []
                if str(item).strip()
            }
            maximum_risk = str(
                option.get("maximum_risk") or ""
            ).strip()
            requested_risk = str(
                option.get("requested_risk") or ""
            ).strip()
            requested_claim_risk = str(
                option.get("requested_claim_risk")
                or requested_risk
            ).strip()
            answer_strategy_risk = str(
                option.get("answer_strategy_risk")
                or requested_risk
            ).strip()
            provenance = _as_dict(option.get("option_provenance"))
            resolution_boundary = _as_dict(
                resolution.get("restricted_request_boundary")
            )
            option_boundary = _as_dict(
                option.get("restricted_request_boundary")
            )
            restricted_alternative = bool(
                resolution_boundary
                or option_boundary
                or provenance.get(
                    "alternative_for_restricted_request"
                )
            )
            risk_separation_valid = bool(
                restricted_alternative
                and valid_restricted_request_boundary(
                    resolution_boundary
                )
                and option_boundary == resolution_boundary
                and requested_risk == requested_claim_risk
                and requested_claim_risk
                == str(
                    resolution.get("requested_claim_risk") or ""
                ).strip()
                == str(
                    resolution_boundary.get(
                        "requested_claim_risk"
                    )
                    or ""
                ).strip()
                and requested_claim_risk
                in {"high", "critical", "prohibited"}
                and answer_strategy_risk
                in _ANSWER_STRATEGY_RISK_RANK
                and maximum_risk in _ANSWER_STRATEGY_RISK_RANK
                and _ANSWER_STRATEGY_RISK_RANK[
                    answer_strategy_risk
                ]
                <= _ANSWER_STRATEGY_RISK_RANK[maximum_risk]
                and provenance.get(
                    "alternative_for_restricted_request"
                )
                is True
                and provenance.get("intent_narrowed") is False
                and str(option.get("intent_kind") or "").strip()
                == "practical_guidance"
            )
            if (
                str(
                    resolution.get("policy_intent_kind") or ""
                ).strip()
                in _RESTRICTED_POLICY_INTENT_KINDS
                or restricted_alternative
            ):
                risk_separation_total += 1
                if risk_separation_valid:
                    risk_separation_count += 1
            valid = bool(
                policy_ref
                and policy
                and str(option.get("applicable_goal_ref") or "").strip()
                == str(resolution.get("goal_ref") or "").strip()
                and str(
                    option.get("trusted_domain_pack_ref") or ""
                ).strip()
                == policy_ref.rsplit(":intent:", 1)[0]
                and str(option.get("policy_intent_ref") or "").strip()
                == str(policy.get("policy_intent_ref") or "").strip()
                and str(option.get("goal_family") or "").strip()
                == str(policy.get("goal_family") or "").strip()
                and str(option.get("intent_kind") or "").strip()
                == str(policy.get("intent_kind") or "").strip()
                == "practical_guidance"
                and sorted(option.get("premise_families") or [])
                == sorted(policy.get("premise_fact_families") or [])
                and premise_uids
                and premise_uids.issubset(admitted_uids)
                and str(option.get("allowed_scope") or "").strip()
                == str(policy.get("allowed_scope") or "").strip()
                and maximum_risk
                == str(policy.get("maximum_risk_level") or "").strip()
                and requested_risk == requested_claim_risk
                and answer_strategy_risk in {"low", "medium"}
                and maximum_risk in {"low", "medium"}
                and not (
                    answer_strategy_risk == "medium"
                    and maximum_risk == "low"
                )
                and sorted(option.get("required_qualifiers") or [])
                == sorted(policy.get("required_qualifiers") or [])
                and sorted(
                    option.get("forbidden_claim_families") or []
                )
                == sorted(
                    policy.get("prohibited_claim_families") or []
                )
                and option.get("review_only") is True
                and provenance.get("policy_owner")
                == "domain_policy_pack"
                and provenance.get("filter_owner") == "claim_resolution"
                and provenance.get("premise_owner")
                == "admitted_answer_context"
                and (
                    (
                        not restricted_alternative
                        and requested_claim_risk in {"low", "medium"}
                        and not option_boundary
                        and provenance.get("intent_narrowed") is True
                    )
                    or risk_separation_valid
                )
                and not resolution.get("conflicting_evidence_uids")
            )
            if valid and policy_ref not in valid_options:
                valid_options[policy_ref] = option
        if raw_options and len(valid_options) == len(raw_options):
            eligible_option_goal_count += 1
            eligible_option_total_count += len(valid_options)
        if not valid_options:
            continue
        claim_uid = str(resolution.get("claim_uid") or "").strip()
        clause = clauses_by_goal.get(claim_uid, {})
        selected_refs = {
            str(item).strip()
            for item in clause.get("inference_policy_refs") or []
            if str(item).strip()
        }
        selected_option = (
            valid_options.get(next(iter(selected_refs)), {})
            if len(selected_refs) == 1
            else {}
        )
        if (
            composer.get("status") == "accepted"
            and clause.get("clause_kind") == "allowed_inference"
            and selected_option
        ):
            selected_policy_count += 1
            selected_policy_valid_count += 1
            option_premises = {
                str(item).strip()
                for item in selected_option.get(
                    "premise_evidence_refs"
                )
                or []
                if str(item).strip()
            }
            clause_premises = {
                str(item).strip()
                for item in clause.get("premise_evidence_uids") or []
                if str(item).strip()
            }
            clause_evidence = {
                str(item).strip()
                for item in clause.get("evidence_uids") or []
                if str(item).strip()
            }
            premise_valid = bool(
                option_premises == clause_premises == clause_evidence
            )
            if premise_valid:
                selected_premise_count += 1
            scope_valid = bool(
                str(clause.get("scope_qualifier") or "").strip()
                == str(
                    selected_option.get("allowed_scope") or ""
                ).strip()
                and (
                    not selected_option.get(
                        "restricted_request_boundary"
                    )
                    or (
                        str(
                            clause.get(
                                "requested_claim_risk_level"
                            )
                            or ""
                        ).strip()
                        == str(
                            selected_option.get(
                                "requested_claim_risk"
                            )
                            or ""
                        ).strip()
                        and str(
                            clause.get(
                                "inference_risk_level"
                            )
                            or ""
                        ).strip()
                        == str(
                            selected_option.get(
                                "answer_strategy_risk"
                            )
                            or ""
                        ).strip()
                        and _as_dict(
                            clause.get(
                                "restricted_request_boundary"
                            )
                        )
                        == _as_dict(
                            selected_option.get(
                                "restricted_request_boundary"
                            )
                        )
                    )
                )
            )
            if scope_valid:
                selected_scope_count += 1
            if premise_valid and scope_valid:
                selected_attributed_count += 1
    selected_absolute_guarantee_count = sum(
        1
        for resolution in resolutions
        for clause in [
            clauses_by_goal.get(
                str(resolution.get("claim_uid") or "").strip(),
                {},
            )
        ]
        if clause.get("clause_kind") == "allowed_inference"
        and {
            str(item).strip()
            for item in clause.get("inference_policy_refs") or []
            if str(item).strip()
        }.intersection({
            str(option.get("policy_ref") or "").strip()
            for option in _as_dict_list(
                resolution.get("eligible_policy_options")
            )
            if str(option.get("intent_kind") or "").strip()
            == "absolute_guarantee"
        })
    )
    return {
        "policy_intent_refs": sorted({
            str(item.get("policy_intent_ref") or "").strip()
            for item in nominated
            if str(item.get("policy_intent_ref") or "").strip()
        }),
        "policy_intent_kinds": sorted({
            str(item.get("policy_intent_kind") or "").strip()
            for item in nominated
            if str(item.get("policy_intent_kind") or "").strip()
        }),
        "policy_intent_precision_numerator": len(valid_claim_uids),
        "policy_intent_precision_denominator": len(nominated),
        "policy_intent_recall_numerator": valid_eligible,
        "policy_intent_recall_denominator": len(eligible),
        "eligible_policy_options_numerator": eligible_option_goal_count,
        "eligible_policy_options_denominator": len(eligible),
        "eligible_policy_option_total_count": (
            eligible_option_total_count
        ),
        "policy_selection_numerator": selected_policy_count,
        "policy_selection_denominator": eligible_option_goal_count,
        "selected_policy_validity_numerator": (
            selected_policy_valid_count
        ),
        "selected_policy_validity_denominator": selected_policy_count,
        "selected_policy_premise_numerator": selected_premise_count,
        "selected_policy_premise_denominator": selected_policy_count,
        "selected_policy_scope_numerator": selected_scope_count,
        "selected_policy_scope_denominator": selected_policy_count,
        "inference_opportunity_missed_count": max(
            0,
            eligible_option_goal_count - selected_policy_count,
        ),
        "bounded_inference_attribution_numerator": (
            attributed + selected_attributed_count
        ),
        "bounded_inference_attribution_denominator": (
            len(bounded) + eligible_option_goal_count
        ),
        "bounded_inference_premise_numerator": (
            premise_complete + selected_premise_count
        ),
        "bounded_inference_premise_denominator": (
            len(bounded) + eligible_option_goal_count
        ),
        "bounded_inference_scope_numerator": (
            scope_complete + selected_scope_count
        ),
        "bounded_inference_scope_denominator": (
            len(bounded) + eligible_option_goal_count
        ),
        "restricted_boundary_preservation_numerator": (
            restricted_boundary_preserved_count
        ),
        "restricted_boundary_preservation_denominator": len(
            restricted_candidates
        ),
        "answer_strategy_risk_separation_numerator": (
            risk_separation_count
        ),
        "answer_strategy_risk_separation_denominator": (
            risk_separation_total
        ),
        "absolute_guarantee_supported_count": sum(
            item.get("policy_intent_kind") == "absolute_guarantee"
            and item.get("status") == "supported"
            for item in resolutions
        ) + selected_absolute_guarantee_count,
    }


def _score_response(
    scenario: dict[str, Any],
    response: dict[str, Any],
    *,
    status_code: int,
    error_type: str,
    latency_ms: int,
) -> dict[str, Any]:
    reply = str(response.get("suggested_reply") or "").strip()
    blocks = [item for item in response.get("reply_blocks") or [] if isinstance(item, dict)]
    media_types = sorted({str(item.get("type")) for item in blocks if item.get("type") in {"image", "video"}})
    forbidden_hits = [
        str(term) for term in scenario.get("forbidden_claims") or []
        if str(term).strip() and contains_asserted_claim(reply, str(term))
    ]
    issue_text = _issue_text(response)
    claim_diagnostics = _expected_claim_diagnostics(scenario, response, reply)
    runtime_claim_diagnostics = _runtime_claim_diagnostics(response)
    policy_contract_diagnostics = _policy_contract_diagnostics(response)
    payload = scenario.get("api_request_template") or {}
    order_present = bool(payload.get("order_id") or (payload.get("copilot_context") or {}).get("order_id"))
    product_present = bool(payload.get("sku_code") or payload.get("i_id") or payload.get("product_name"))
    repeated_known_request = (
        order_present and any(term in reply for term in _ORDER_REQUEST_TERMS)
    ) or (
        product_present and any(term in reply for term in _PRODUCT_REQUEST_TERMS)
    )
    selected = response.get("selected_evidence") or []
    unsupported_media = contains_unsupported_media_promise(reply, bool(media_types))
    unsupported_high_risk = bool(forbidden_hits) or "unsupported_high_risk_claim" in issue_text
    unsupported_service_action = any(
        marker in issue_text
        for marker in (
            "unsupported_service_action",
            "unsupported_order",
            "unsupported_refund",
            "unsupported_logistics",
        )
    )
    unnecessary_handoff = bool(
        not scenario.get("must_handoff")
        and any(term in reply for term in _SYSTEM_TONE_TERMS[:6])
    )
    structured_unresolved_complete = bool(
        runtime_claim_diagnostics[
            "runtime_unresolved_handling_denominator"
        ]
        and runtime_claim_diagnostics[
            "runtime_unresolved_handling_numerator"
        ]
        == runtime_claim_diagnostics[
            "runtime_unresolved_handling_denominator"
        ]
    )
    partial_success = bool(
        runtime_claim_diagnostics["partial_answer_contract_pass"] is True
        and not forbidden_hits
        and not unsupported_media
        and not unsupported_service_action
    )
    composer_audit = _as_dict(response.get("model_first_answer_composer"))
    composer_provider = _as_dict(composer_audit.get("provider_diagnostics"))
    final_audit = _as_dict(response.get("final_answer_audit"))
    unified_audit = _as_dict(response.get("final_semantic_fit_audit"))
    unified_provider = _as_dict(unified_audit.get("provider_diagnostics"))
    pipeline_stages = _as_dict_list(
        _as_dict(response.get("final_response_pipeline")).get("stages")
    )
    fallback_used = bool(
        final_audit.get("fallback_used") is True
        or any(item.get("fallback_used") is True for item in pipeline_stages)
    )
    supervisor_assist_candidate_eligible = bool(
        not error_type
        and status_code == 200
        and composer_audit.get("status") == "accepted"
        and composer_audit.get("used_for_final_reply") is True
        and final_audit.get("passed") is True
        and response.get("can_send") is False
        and response.get("requires_human_review") is True
        and not forbidden_hits
        and not unsupported_media
        and not unsupported_service_action
    )
    return {
        "status_code": status_code,
        "error_type": error_type,
        "latency_ms": latency_ms,
        "reply": reply,
        "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
        "nonempty_reply": bool(reply),
        "selected_evidence_count": len(selected),
        "composer_status": composer_audit.get("status", ""),
        "composer_rejection_reason": composer_audit.get("rejection_reason", ""),
        "composer_model_call_count": int(
            composer_provider.get("model_call_count") or 0
        ),
        "composer_latency_ms": composer_provider.get("provider_latency_ms"),
        "final_audit_passed": final_audit.get("passed"),
        "final_audit_mode": str(final_audit.get("mode") or ""),
        "final_audit_model_call_count": int(
            final_audit.get("model_call_count") or 0
        ),
        "semantic_audit_passed": unified_audit.get("passed"),
        "unified_audit_advisory_failed": unified_audit.get("passed") is False,
        "autonomous_send_audit_gate_passed": unified_audit.get("passed") is True,
        "supervisor_assist_candidate_eligible": (
            supervisor_assist_candidate_eligible
        ),
        "unified_audit_model_call_count": int(
            unified_provider.get("model_call_count") or 0
        ),
        "unified_audit_retry_count": int(
            unified_provider.get("retry_count") or 0
        ),
        "unified_audit_repair_count": int(
            unified_provider.get("repair_count") or 0
        ),
        "unified_audit_latency_ms": unified_provider.get(
            "provider_latency_ms"
        ),
        "fallback_used": fallback_used,
        "can_send": bool(response.get("can_send")),
        "requires_human_review": bool(response.get("requires_human_review")),
        "media_types": media_types,
        "system_tone_terms": [term for term in _SYSTEM_TONE_TERMS if term.lower() in reply.lower()],
        "repeated_known_information_request": bool(repeated_known_request),
        "unnecessary_handoff": unnecessary_handoff,
        "unsupported_high_risk_claim": unsupported_high_risk,
        "unsupported_media_promise": unsupported_media,
        "unsupported_service_action": unsupported_service_action,
        "forbidden_claim_hits": forbidden_hits,
        "partial_answer_success": partial_success,
        "partial_answer_expected": runtime_claim_diagnostics[
            "partial_answer_applicable"
        ],
        "structured_unresolved_complete": structured_unresolved_complete,
        **claim_diagnostics,
        **runtime_claim_diagnostics,
        **policy_contract_diagnostics,
    }


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    latencies = [int(row["latency_ms"]) for row in rows if not row["error_type"]]
    composer_latencies = [
        int(row["composer_latency_ms"])
        for row in rows
        if row.get("composer_latency_ms") is not None
    ]
    unified_latencies = [
        int(row["unified_audit_latency_ms"])
        for row in rows
        if row.get("unified_audit_latency_ms") is not None
    ]
    dataset_supported_num = sum(int(row["dataset_supported_claim_numerator"]) for row in rows)
    dataset_supported_den = sum(int(row["dataset_supported_claim_denominator"]) for row in rows)
    dataset_unresolved_num = sum(int(row["dataset_unresolved_handling_numerator"]) for row in rows)
    dataset_unresolved_den = sum(int(row["dataset_unresolved_handling_denominator"]) for row in rows)
    runtime_supported_num = sum(int(row["runtime_supported_claim_numerator"]) for row in rows)
    runtime_supported_den = sum(int(row["runtime_supported_claim_denominator"]) for row in rows)
    runtime_unresolved_num = sum(int(row["runtime_unresolved_handling_numerator"]) for row in rows)
    runtime_unresolved_den = sum(int(row["runtime_unresolved_handling_denominator"]) for row in rows)
    customer_goal_clause_num = sum(
        int(row["customer_goal_clause_coverage_numerator"])
        for row in rows
    )
    customer_goal_clause_den = sum(
        int(row["customer_goal_clause_coverage_denominator"])
        for row in rows
    )
    dependency_link_num = sum(
        int(row["dependency_evidence_link_coverage_numerator"])
        for row in rows
    )
    dependency_link_den = sum(
        int(row["dependency_evidence_link_coverage_denominator"])
        for row in rows
    )
    policy_precision_num = sum(
        int(row["policy_intent_precision_numerator"]) for row in rows
    )
    policy_precision_den = sum(
        int(row["policy_intent_precision_denominator"]) for row in rows
    )
    policy_recall_num = sum(
        int(row["policy_intent_recall_numerator"]) for row in rows
    )
    policy_recall_den = sum(
        int(row["policy_intent_recall_denominator"]) for row in rows
    )
    option_num = sum(
        int(row["eligible_policy_options_numerator"]) for row in rows
    )
    option_den = sum(
        int(row["eligible_policy_options_denominator"]) for row in rows
    )
    selection_num = sum(
        int(row["policy_selection_numerator"]) for row in rows
    )
    selection_den = sum(
        int(row["policy_selection_denominator"]) for row in rows
    )
    selected_valid_num = sum(
        int(row["selected_policy_validity_numerator"]) for row in rows
    )
    selected_valid_den = sum(
        int(row["selected_policy_validity_denominator"]) for row in rows
    )
    selected_premise_num = sum(
        int(row["selected_policy_premise_numerator"]) for row in rows
    )
    selected_premise_den = sum(
        int(row["selected_policy_premise_denominator"]) for row in rows
    )
    selected_scope_num = sum(
        int(row["selected_policy_scope_numerator"]) for row in rows
    )
    selected_scope_den = sum(
        int(row["selected_policy_scope_denominator"]) for row in rows
    )
    bounded_num = sum(
        int(row["bounded_inference_attribution_numerator"]) for row in rows
    )
    bounded_den = sum(
        int(row["bounded_inference_attribution_denominator"]) for row in rows
    )
    premise_num = sum(
        int(row["bounded_inference_premise_numerator"]) for row in rows
    )
    premise_den = sum(
        int(row["bounded_inference_premise_denominator"]) for row in rows
    )
    scope_num = sum(
        int(row["bounded_inference_scope_numerator"]) for row in rows
    )
    scope_den = sum(
        int(row["bounded_inference_scope_denominator"]) for row in rows
    )
    boundary_num = sum(
        int(row["restricted_boundary_preservation_numerator"])
        for row in rows
    )
    boundary_den = sum(
        int(row["restricted_boundary_preservation_denominator"])
        for row in rows
    )
    risk_separation_num = sum(
        int(row["answer_strategy_risk_separation_numerator"])
        for row in rows
    )
    risk_separation_den = sum(
        int(row["answer_strategy_risk_separation_denominator"])
        for row in rows
    )
    partial_rows = [row for row in rows if row["partial_answer_expected"]]
    reply_counts = Counter(row["reply_sha256"] for row in rows if row["reply"])
    duplicate_rows = sum(count for count in reply_counts.values() if count > 1)
    return {
        "scenario_count": len(rows),
        "execution_success_count": sum(not row["error_type"] and row["status_code"] == 200 for row in rows),
        "nonempty_reply_count": sum(row["nonempty_reply"] for row in rows),
        "selected_evidence_total_count": sum(int(row["selected_evidence_count"]) for row in rows),
        "selected_evidence_scenario_count": sum(int(row["selected_evidence_count"]) > 0 for row in rows),
        "renderable_customer_goal_count": sum(
            int(row["renderable_customer_goal_count"]) for row in rows
        ),
        "supporting_dependency_count": sum(
            int(row["supporting_dependency_count"]) for row in rows
        ),
        "customer_goal_clause_coverage": {
            "numerator": customer_goal_clause_num,
            "denominator": customer_goal_clause_den,
            "rate": (
                customer_goal_clause_num / customer_goal_clause_den
                if customer_goal_clause_den
                else None
            ),
        },
        "dependency_evidence_link_coverage": {
            "numerator": dependency_link_num,
            "denominator": dependency_link_den,
            "rate": (
                dependency_link_num / dependency_link_den
                if dependency_link_den
                else None
            ),
        },
        "unknown_goal_kind_count": sum(
            int(row["unknown_goal_kind_count"]) for row in rows
        ),
        "dataset_required_point_coverage": {
            "numerator": dataset_supported_num,
            "denominator": dataset_supported_den,
            "rate": (
                dataset_supported_num / dataset_supported_den
                if dataset_supported_den else None
            ),
        },
        "dataset_unresolved_point_coverage": {
            "numerator": dataset_unresolved_num,
            "denominator": dataset_unresolved_den,
            "rate": (
                dataset_unresolved_num / dataset_unresolved_den
                if dataset_unresolved_den else None
            ),
        },
        "runtime_supported_claim_attribution": {
            "numerator": runtime_supported_num,
            "denominator": runtime_supported_den,
            "rate": (
                runtime_supported_num / runtime_supported_den
                if runtime_supported_den else None
            ),
        },
        "runtime_unresolved_claim_declaration": {
            "numerator": runtime_unresolved_num,
            "denominator": runtime_unresolved_den,
            "rate": (
                runtime_unresolved_num / runtime_unresolved_den
                if runtime_unresolved_den else None
            ),
        },
        "supported_goal_coverage": {
            "numerator": runtime_supported_num,
            "denominator": runtime_supported_den,
            "rate": (
                runtime_supported_num / runtime_supported_den
                if runtime_supported_den else None
            ),
        },
        "unresolved_goal_coverage": {
            "numerator": runtime_unresolved_num,
            "denominator": runtime_unresolved_den,
            "rate": (
                runtime_unresolved_num / runtime_unresolved_den
                if runtime_unresolved_den else None
            ),
        },
        "policy_intent_precision": {
            "numerator": policy_precision_num,
            "denominator": policy_precision_den,
            "rate": (
                policy_precision_num / policy_precision_den
                if policy_precision_den else None
            ),
        },
        "policy_intent_recall": {
            "numerator": policy_recall_num,
            "denominator": policy_recall_den,
            "rate": (
                policy_recall_num / policy_recall_den
                if policy_recall_den else None
            ),
        },
        "eligible_policy_options_coverage": {
            "numerator": option_num,
            "denominator": option_den,
            "rate": option_num / option_den if option_den else None,
        },
        "policy_selection_coverage": {
            "numerator": selection_num,
            "denominator": selection_den,
            "rate": (
                selection_num / selection_den
                if selection_den
                else None
            ),
        },
        "selected_policy_validity": {
            "numerator": selected_valid_num,
            "denominator": selected_valid_den,
            "rate": (
                selected_valid_num / selected_valid_den
                if selected_valid_den
                else None
            ),
        },
        "selected_policy_premise_coverage": {
            "numerator": selected_premise_num,
            "denominator": selected_premise_den,
            "rate": (
                selected_premise_num / selected_premise_den
                if selected_premise_den
                else None
            ),
        },
        "selected_policy_scope_validity": {
            "numerator": selected_scope_num,
            "denominator": selected_scope_den,
            "rate": (
                selected_scope_num / selected_scope_den
                if selected_scope_den
                else None
            ),
        },
        "eligible_policy_option_total_count": sum(
            int(row["eligible_policy_option_total_count"])
            for row in rows
        ),
        "inference_opportunity_missed_count": sum(
            int(row["inference_opportunity_missed_count"])
            for row in rows
        ),
        "bounded_inference_attribution": {
            "numerator": bounded_num,
            "denominator": bounded_den,
            "rate": bounded_num / bounded_den if bounded_den else None,
        },
        "bounded_inference_premise_coverage": {
            "numerator": premise_num,
            "denominator": premise_den,
            "rate": premise_num / premise_den if premise_den else None,
        },
        "bounded_inference_scope_coverage": {
            "numerator": scope_num,
            "denominator": scope_den,
            "rate": scope_num / scope_den if scope_den else None,
        },
        "restricted_boundary_preservation": {
            "numerator": boundary_num,
            "denominator": boundary_den,
            "rate": boundary_num / boundary_den if boundary_den else None,
        },
        "answer_strategy_risk_separation": {
            "numerator": risk_separation_num,
            "denominator": risk_separation_den,
            "rate": (
                risk_separation_num / risk_separation_den
                if risk_separation_den
                else None
            ),
        },
        "policy_intent_ref_counts": dict(sorted(Counter(
            intent_ref
            for row in rows
            for intent_ref in row["policy_intent_refs"]
        ).items())),
        "policy_intent_kind_counts": dict(sorted(Counter(
            intent_kind
            for row in rows
            for intent_kind in row["policy_intent_kinds"]
        ).items())),
        "absolute_guarantee_supported_count": sum(
            int(row["absolute_guarantee_supported_count"]) for row in rows
        ),
        "unknown_goal_ref_count": sum(
            int(row["unknown_goal_ref_count"]) for row in rows
        ),
        "duplicate_goal_ref_clause_count": sum(
            int(row["duplicate_goal_ref_clause_count"]) for row in rows
        ),
        "wrong_clause_kind_count": sum(
            int(row["wrong_clause_kind_count"]) for row in rows
        ),
        "unsupported_evidence_ref_count": sum(
            int(row["unsupported_evidence_ref_count"]) for row in rows
        ),
        "unknown_evidence_ref_count": sum(
            int(row["unknown_evidence_ref_count"]) for row in rows
        ),
        "non_customer_goal_clause_count": sum(
            int(row["non_customer_goal_clause_count"]) for row in rows
        ),
        "shadow_candidate_formal_use_count": sum(
            int(row["shadow_candidate_formal_use_count"]) for row in rows
        ),
        "partial_answer_success": {
            "numerator": sum(row["partial_answer_success"] for row in partial_rows),
            "denominator": len(partial_rows),
            "rate": (
                sum(row["partial_answer_success"] for row in partial_rows) / len(partial_rows)
                if partial_rows else None
            ),
        },
        "unnecessary_handoff_count": sum(row["unnecessary_handoff"] for row in rows),
        "repeated_known_information_request_count": sum(
            row["repeated_known_information_request"] for row in rows
        ),
        "system_tone_count": sum(bool(row["system_tone_terms"]) for row in rows),
        "duplicate_reply_count": duplicate_rows,
        "unsupported_high_risk_claim_count": sum(row["unsupported_high_risk_claim"] for row in rows),
        "unsupported_media_promise_count": sum(row["unsupported_media_promise"] for row in rows),
        "unsupported_service_action_count": sum(row["unsupported_service_action"] for row in rows),
        "can_send_true_count": sum(row["can_send"] for row in rows),
        "requires_human_review_count": sum(row["requires_human_review"] for row in rows),
        "composer_accepted_count": sum(row["composer_status"] == "accepted" for row in rows),
        "composer_rejected_reasons": dict(sorted(Counter(
            row["composer_rejection_reason"]
            for row in rows
            if row["composer_rejection_reason"]
        ).items())),
        "final_audit_pass_count": sum(row["final_audit_passed"] is True for row in rows),
        "semantic_audit_pass_count": sum(row["semantic_audit_passed"] is True for row in rows),
        "unified_audit_advisory_failure_count": sum(
            row["unified_audit_advisory_failed"] for row in rows
        ),
        "autonomous_send_audit_gate_pass_count": sum(
            row["autonomous_send_audit_gate_passed"] for row in rows
        ),
        "supervisor_assist_candidate_eligible_count": sum(
            row["supervisor_assist_candidate_eligible"] for row in rows
        ),
        "final_audit_model_call_count": sum(
            int(row["final_audit_model_call_count"]) for row in rows
        ),
        "unified_audit_model_call_count": sum(
            int(row["unified_audit_model_call_count"]) for row in rows
        ),
        "unified_audit_retry_count": sum(
            int(row["unified_audit_retry_count"]) for row in rows
        ),
        "unified_audit_repair_count": sum(
            int(row["unified_audit_repair_count"]) for row in rows
        ),
        "fallback_count": sum(row["fallback_used"] for row in rows),
        "composer_latency_ms": {
            "p50": (
                round(statistics.median(composer_latencies))
                if composer_latencies else None
            ),
            "p95": _percentile(composer_latencies, 0.95),
        },
        "unified_audit_latency_ms": {
            "p50": (
                round(statistics.median(unified_latencies))
                if unified_latencies else None
            ),
            "p95": _percentile(unified_latencies, 0.95),
        },
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "p95": _percentile(latencies, 0.95),
        },
    }


def _correctness_gate_blockers(
    off_summary: dict[str, Any],
    on_summary: dict[str, Any],
    *,
    scenario_count: int,
) -> list[str]:
    blockers: list[str] = []
    partial = on_summary.get("partial_answer_success") or {}
    if int(partial.get("denominator") or 0) and int(partial.get("numerator") or 0) != int(partial["denominator"]):
        blockers.append("partial_answer_incomplete")
    for field, blocker in (
        ("runtime_supported_claim_attribution", "supported_claim_attribution_incomplete"),
        ("runtime_unresolved_claim_declaration", "unresolved_claim_declaration_incomplete"),
        ("customer_goal_clause_coverage", "customer_goal_clause_coverage_incomplete"),
        (
            "dependency_evidence_link_coverage",
            "dependency_evidence_link_coverage_incomplete",
        ),
        ("policy_intent_precision", "policy_intent_precision_incomplete"),
        ("policy_intent_recall", "policy_intent_recall_incomplete"),
        (
            "eligible_policy_options_coverage",
            "eligible_policy_options_incomplete",
        ),
        ("policy_selection_coverage", "policy_selection_incomplete"),
        ("selected_policy_validity", "selected_policy_invalid"),
        (
            "selected_policy_premise_coverage",
            "selected_policy_premise_incomplete",
        ),
        (
            "selected_policy_scope_validity",
            "selected_policy_scope_invalid",
        ),
        ("bounded_inference_attribution", "bounded_inference_attribution_incomplete"),
        ("bounded_inference_premise_coverage", "bounded_inference_premise_incomplete"),
        ("bounded_inference_scope_coverage", "bounded_inference_scope_incomplete"),
        (
            "restricted_boundary_preservation",
            "restricted_boundary_not_preserved",
        ),
        (
            "answer_strategy_risk_separation",
            "answer_strategy_risk_separation_invalid",
        ),
    ):
        metric = on_summary.get(field) or {}
        if int(metric.get("denominator") or 0) and int(metric.get("numerator") or 0) != int(metric["denominator"]):
            blockers.append(blocker)
    if int(on_summary.get("absolute_guarantee_supported_count") or 0):
        blockers.append("absolute_guarantee_supported")
    for field, blocker in (
        ("unknown_goal_ref_count", "unknown_goal_ref_clause"),
        (
            "duplicate_goal_ref_clause_count",
            "duplicate_goal_ref_clause",
        ),
        ("wrong_clause_kind_count", "wrong_clause_kind"),
        ("unsupported_evidence_ref_count", "unsupported_evidence_ref"),
        ("unknown_evidence_ref_count", "unknown_evidence_ref"),
        (
            "non_customer_goal_clause_count",
            "non_customer_goal_rendered_as_fact",
        ),
        (
            "shadow_candidate_formal_use_count",
            "shadow_candidate_formal_use",
        ),
        ("unknown_goal_kind_count", "unknown_goal_kind"),
    ):
        if int(on_summary.get(field) or 0):
            blockers.append(blocker)
    goal_resolution = (on_summary.get("goal_recall") or {}).get(
        "customer_goal_resolution_coverage"
    ) or {}
    if (
        int(goal_resolution.get("denominator") or 0)
        and int(goal_resolution.get("numerator") or 0)
        != int(goal_resolution["denominator"])
    ):
        blockers.append("customer_goal_resolution_incomplete")
    if int(on_summary.get("final_audit_pass_count") or 0) != scenario_count:
        blockers.append("final_audit_incomplete")
    if int(on_summary.get("semantic_audit_pass_count") or 0) != scenario_count:
        blockers.append("semantic_audit_incomplete")
    if int(on_summary.get("final_audit_model_call_count") or 0):
        blockers.append("final_audit_model_call_detected")
    if int(on_summary.get("unified_audit_model_call_count") or 0) > scenario_count:
        blockers.append("unified_audit_call_limit_exceeded")
    if int(on_summary.get("unified_audit_retry_count") or 0):
        blockers.append("unified_audit_retry_detected")
    if int(on_summary.get("unified_audit_repair_count") or 0):
        blockers.append("unified_audit_repair_detected")
    if int(on_summary.get("fallback_count") or 0):
        blockers.append("model_first_fallback_detected")
    if int(on_summary.get("requires_human_review_count") or 0) < int(off_summary.get("requires_human_review_count") or 0):
        blockers.append("requires_human_review_decreased")
    if int((on_summary.get("latency_ms") or {}).get("p95") or 0) > 35_000:
        blockers.append("latency_p95_exceeded")
    return blockers


def _fingerprint(path: Path) -> dict[str, Any]:
    return fingerprint_formal_knowledge_tables(
        path,
        hmac_key=formal_kb_audit_hmac_key(),
        tables=("kb_product", "kb_qa", "knowledge_entries", "knowledge_chunks"),
    )


def _dml_offset(path: Path | None) -> int:
    return path.stat().st_size if path and path.exists() else 0


def _dml_count(path: Path | None, offset: int) -> int:
    if not path or not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        return sum(1 for line in handle if line.strip())


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    scenarios = list(dataset.get("scenarios") or [])
    if not scenarios:
        raise ValueError("no_scenarios")
    scenarios = scenarios[: min(len(scenarios), max(1, int(args.limit)))]
    goal_truth = (
        _load_goal_truth(Path(args.goal_truth))
        if getattr(args, "goal_truth", "")
        else {}
    )

    off_runtime = _get_json(args.off_version_url, args.timeout)
    on_runtime = _get_json(args.on_version_url, args.timeout)
    runtime_findings = [
        *_runtime_contract(
            off_runtime,
            mode="OFF",
            expected_commit=args.expected_commit,
            expected_source_hash=args.expected_source_tree_sha256,
            expected_model=args.expected_model,
        ),
        *_runtime_contract(
            on_runtime,
            mode="ON",
            expected_commit=args.expected_commit,
            expected_source_hash=args.expected_source_tree_sha256,
            expected_model=args.expected_model,
        ),
    ]
    for field in ("runtime_commit", "source_tree_sha256", "formal_model"):
        if off_runtime.get(field) != on_runtime.get(field):
            runtime_findings.append(f"paired_runtime_{field}_mismatch")
    if runtime_findings:
        raise ValueError("runtime_contract_failed:" + ",".join(sorted(set(runtime_findings))))

    knowledge_path = Path(args.knowledge_db)
    knowledge_before = _fingerprint(knowledge_path)
    off_dml_path = Path(args.off_dml) if args.off_dml else None
    on_dml_path = Path(args.on_dml) if args.on_dml else None
    off_dml_offset = _dml_offset(off_dml_path)
    on_dml_offset = _dml_offset(on_dml_path)

    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        payload = _agent_payload(scenario)
        paired: dict[str, Any] = {
            "scenario_uid": str(scenario.get("scenario_uid") or ""),
            "business_domain": str(scenario.get("business_domain") or ""),
            "risk_level": str(scenario.get("risk_level") or ""),
            "must_handoff": bool(scenario.get("must_handoff")),
        }
        endpoints = (("OFF", args.off_analyze_url), ("ON", args.on_analyze_url))
        if int(args.pair_workers) == 2:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    mode: executor.submit(_post_json, url, payload, args.timeout)
                    for mode, url in endpoints
                }
                responses = {mode: futures[mode].result() for mode, _ in endpoints}
        else:
            responses = {
                mode: _post_json(url, payload, args.timeout)
                for mode, url in endpoints
            }
        for mode, _ in endpoints:
            status, response, latency, error = responses[mode]
            paired[mode.lower()] = _score_response(
                scenario,
                response,
                status_code=status,
                error_type=error,
                latency_ms=latency,
            )
            if paired["scenario_uid"] in goal_truth:
                paired[mode.lower()]["goal_funnel"] = _goal_funnel(
                    scenario,
                    response,
                    goal_truth[paired["scenario_uid"]],
                )
                paired[mode.lower()]["runtime_customer_goals"] = _runtime_customer_goals(response)
        results.append(paired)

    knowledge_after = _fingerprint(knowledge_path)
    knowledge_diff = compare_formal_knowledge_fingerprints(knowledge_before, knowledge_after)
    off_rows = [row["off"] for row in results]
    on_rows = [row["on"] for row in results]
    off_summary = _summarize(off_rows)
    on_summary = _summarize(on_rows)
    off_goal_rows = [
        item
        for row in off_rows
        for item in row.get("goal_funnel") or []
    ]
    on_goal_rows = [
        item
        for row in on_rows
        for item in row.get("goal_funnel") or []
    ]
    if goal_truth:
        off_summary["goal_recall"] = _goal_recall_summary(
            off_goal_rows,
            [
                {
                    "scenario_uid": row["scenario_uid"],
                    "customer_goals": row["off"].get("runtime_customer_goals") or [],
                }
                for row in results
                if row["scenario_uid"] in goal_truth
            ],
        )
        on_summary["goal_recall"] = _goal_recall_summary(
            on_goal_rows,
            [
                {
                    "scenario_uid": row["scenario_uid"],
                    "customer_goals": row["on"].get("runtime_customer_goals") or [],
                }
                for row in results
                if row["scenario_uid"] in goal_truth
            ],
        )
    blockers: list[str] = []
    if on_summary.get("execution_success_count") != len(results):
        blockers.append("on_execution_error")
    if on_summary.get("nonempty_reply_count") != len(results):
        blockers.append("on_empty_reply")
    for field in (
        "unsupported_high_risk_claim_count",
        "unsupported_media_promise_count",
        "unsupported_service_action_count",
        "can_send_true_count",
    ):
        if int(on_summary.get(field) or 0):
            blockers.append(field)
    off_dml_count = _dml_count(off_dml_path, off_dml_offset)
    on_dml_count = _dml_count(on_dml_path, on_dml_offset)
    if knowledge_diff.get("changed"):
        blockers.append("formal_knowledge_changed")
    if off_dml_count or on_dml_count:
        blockers.append("formal_knowledge_dml_attempted")
    blockers.extend(_correctness_gate_blockers(
        off_summary,
        on_summary,
        scenario_count=len(results),
    ))

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluation_tier": "development_diagnostic",
        "accuracy_claim_allowed": False,
        "dataset": {
            "dataset_id": dataset.get("dataset_id"),
            "dataset_version": dataset.get("dataset_version"),
            "content_sha256": (dataset.get("manifest") or {}).get("content_sha256"),
            "scenario_count": len(dataset.get("scenarios") or []),
            "evaluated_scenario_count": len(results),
        },
        "runtime": {
            "runtime_commit": on_runtime.get("runtime_commit"),
            "source_tree_sha256": on_runtime.get("source_tree_sha256"),
            "formal_model": on_runtime.get("formal_model"),
            "formal_knowledge_query_only": on_runtime.get("formal_knowledge_query_only"),
            "off_feature_flags": off_runtime.get("feature_flags"),
            "on_feature_flags": on_runtime.get("feature_flags"),
        },
        "request_contract": {
            "payload_source": "scenario.api_request_template",
            "evaluation_fields_excluded": sorted(_PROHIBITED_AGENT_FIELDS),
            "goal_truth_source": "diagnostic_only_not_in_agent_payload" if goal_truth else "",
        },
        "results": results,
        "off_summary": off_summary,
        "on_summary": on_summary,
        "comparison": {
            "selected_evidence_scenario_delta": (
                int(on_summary.get("selected_evidence_scenario_count") or 0)
                - int(off_summary.get("selected_evidence_scenario_count") or 0)
            ),
            "unnecessary_handoff_delta": (
                int(on_summary.get("unnecessary_handoff_count") or 0)
                - int(off_summary.get("unnecessary_handoff_count") or 0)
            ),
            "system_tone_delta": (
                int(on_summary.get("system_tone_count") or 0)
                - int(off_summary.get("system_tone_count") or 0)
            ),
            "can_send_true_delta": (
                int(on_summary.get("can_send_true_count") or 0)
                - int(off_summary.get("can_send_true_count") or 0)
            ),
        },
        "formal_knowledge": {
            "changed": bool(knowledge_diff.get("changed")),
            "changed_row_count": int(knowledge_diff.get("changed_row_count") or 0),
            "off_dml_attempt_count": off_dml_count,
            "on_dml_attempt_count": on_dml_count,
        },
        "layer_gate": {
            "passed": not blockers,
            "blockers": sorted(set(blockers)),
        },
    }
    report["report_content_sha256"] = _canonical_hash(report)
    return report, 0 if not blockers else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--knowledge-db", required=True)
    parser.add_argument("--off-analyze-url", default="http://127.0.0.1:5014/api/analyze")
    parser.add_argument("--on-analyze-url", default="http://127.0.0.1:5013/api/analyze")
    parser.add_argument("--off-version-url", default="http://127.0.0.1:5014/api/runtime/version")
    parser.add_argument("--on-version-url", default="http://127.0.0.1:5013/api/runtime/version")
    parser.add_argument("--off-dml", default="")
    parser.add_argument("--on-dml", default="")
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--expected-source-tree-sha256", default="")
    parser.add_argument("--expected-model", default="")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--pair-workers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--goal-truth", default="")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    try:
        report, exit_code = run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_run", "reason": str(exc)}, ensure_ascii=False))
        return 2
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "evaluated_scenario_count": report["dataset"]["evaluated_scenario_count"],
        "off_summary": report["off_summary"],
        "on_summary": report["on_summary"],
        "layer_gate": report["layer_gate"],
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
