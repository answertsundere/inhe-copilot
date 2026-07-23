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
from app.services.no_evidence_reply_policy_service import (  # noqa: E402
    contains_unsupported_media_promise,
)


REPORT_SCHEMA_VERSION = "model-first-answer-comparison/v1"
_PROHIBITED_AGENT_FIELDS = {
    "accuracy_claim_allowed",
    "correct_answer",
    "expected_claims",
    "forbidden_claims",
    "gold_reply",
    "pass_criteria",
    "reference_label",
    "required_actions",
    "rubric",
    "scoring_contract",
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
        "partial_answer_expected": bool(supported and unresolved),
    }


def _runtime_claim_diagnostics(response: dict[str, Any]) -> dict[str, Any]:
    context = response.get("minimal_decision_context")
    if not isinstance(context, dict):
        context = {}
    claims = [
        item
        for item in context.get("claim_resolutions") or []
        if isinstance(item, dict)
    ]
    supported = [item for item in claims if item.get("status") == "supported"]
    unresolved = [
        item
        for item in claims
        if item.get("status") in {"unresolved", "conflicting", "prohibited"}
    ]
    composer = response.get("model_first_answer_composer") or {}
    accepted = composer.get("status") == "accepted"
    final_audit_passed = (response.get("final_answer_audit") or {}).get("passed") is True
    used_evidence_uids = {
        str(item)
        for item in composer.get("used_evidence_uids") or []
        if str(item).strip()
    }
    declared_unresolved = {
        str(item)
        for item in composer.get("unresolved_claim_types") or []
        if str(item).strip()
    }
    supported_hits = 0
    for claim in supported:
        required = {
            str(item)
            for item in claim.get("evidence_uids") or []
            if str(item).strip()
        }
        if accepted and final_audit_passed and required and required.issubset(used_evidence_uids):
            supported_hits += 1
    unresolved_hits = sum(
        accepted
        and str(item.get("claim_type") or "").strip() in declared_unresolved
        for item in unresolved
    )
    return {
        "runtime_supported_claim_numerator": supported_hits,
        "runtime_supported_claim_denominator": len(supported),
        "runtime_unresolved_handling_numerator": unresolved_hits,
        "runtime_unresolved_handling_denominator": len(unresolved),
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
    payload = scenario.get("api_request_template") or {}
    order_present = bool(payload.get("order_id") or (payload.get("copilot_context") or {}).get("order_id"))
    product_present = bool(payload.get("sku_code") or payload.get("i_id") or payload.get("product_name"))
    repeated_known_request = (
        order_present and any(term in reply for term in _ORDER_REQUEST_TERMS)
    ) or (
        product_present and any(term in reply for term in _PRODUCT_REQUEST_TERMS)
    )
    selected = response.get("selected_evidence") or []
    runtime_claim_diagnostics = _runtime_claim_diagnostics(response)
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
    partial_success = bool(
        claim_diagnostics["partial_answer_expected"]
        and claim_diagnostics["supported_complete"]
        and claim_diagnostics["unresolved_complete"]
        and not forbidden_hits
    )
    return {
        "status_code": status_code,
        "error_type": error_type,
        "latency_ms": latency_ms,
        "reply": reply,
        "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
        "nonempty_reply": bool(reply),
        "selected_evidence_count": len(selected),
        "composer_status": (response.get("model_first_answer_composer") or {}).get("status", ""),
        "composer_rejection_reason": (response.get("model_first_answer_composer") or {}).get("rejection_reason", ""),
        "final_audit_passed": (response.get("final_answer_audit") or {}).get("passed"),
        "semantic_audit_passed": (response.get("final_semantic_fit_audit") or {}).get("passed"),
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
        **claim_diagnostics,
        **runtime_claim_diagnostics,
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
    dataset_supported_num = sum(int(row["dataset_supported_claim_numerator"]) for row in rows)
    dataset_supported_den = sum(int(row["dataset_supported_claim_denominator"]) for row in rows)
    dataset_unresolved_num = sum(int(row["dataset_unresolved_handling_numerator"]) for row in rows)
    dataset_unresolved_den = sum(int(row["dataset_unresolved_handling_denominator"]) for row in rows)
    runtime_supported_num = sum(int(row["runtime_supported_claim_numerator"]) for row in rows)
    runtime_supported_den = sum(int(row["runtime_supported_claim_denominator"]) for row in rows)
    runtime_unresolved_num = sum(int(row["runtime_unresolved_handling_numerator"]) for row in rows)
    runtime_unresolved_den = sum(int(row["runtime_unresolved_handling_denominator"]) for row in rows)
    partial_rows = [row for row in rows if row["partial_answer_expected"]]
    reply_counts = Counter(row["reply_sha256"] for row in rows if row["reply"])
    duplicate_rows = sum(count for count in reply_counts.values() if count > 1)
    return {
        "scenario_count": len(rows),
        "execution_success_count": sum(not row["error_type"] and row["status_code"] == 200 for row in rows),
        "nonempty_reply_count": sum(row["nonempty_reply"] for row in rows),
        "selected_evidence_total_count": sum(int(row["selected_evidence_count"]) for row in rows),
        "selected_evidence_scenario_count": sum(int(row["selected_evidence_count"]) > 0 for row in rows),
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
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "p95": _percentile(latencies, 0.95),
        },
    }


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
        results.append(paired)

    knowledge_after = _fingerprint(knowledge_path)
    knowledge_diff = compare_formal_knowledge_fingerprints(knowledge_before, knowledge_after)
    off_rows = [row["off"] for row in results]
    on_rows = [row["on"] for row in results]
    off_summary = _summarize(off_rows)
    on_summary = _summarize(on_rows)
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
