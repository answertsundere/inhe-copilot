"""Read-only semantic and strict-schema qualification for the Tier D grader."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.tier_d_transcript_grader_service import TierDTranscriptGrader  # noqa: E402


_QUALIFICATION_CASES = (
    ("positive-verify-order", "completed", "verify_order_and_issue", "我先核对当前订单和您反馈的问题，再给您明确处理结果。"),
    ("positive-review-material", "completed", "review_matching_material", "我按当前商品资料核对对应安装步骤，确认后回复您。"),
    ("positive-locate-step", "completed", "locate_step_or_component", "请把卡住的安装位置拍一张，我按这个位置继续核对。"),
    ("negative-refuse-verification", "blocked", "verify_order_and_issue", "无需核对，我不会查询订单。"),
    ("negative-no-product-context", "blocked", "use_identity_scoped_evidence", "这款商品信息我这里完全没有。"),
    ("negative-refuse-material", "blocked", "review_matching_material", "没有说明书，也不会核对安装图或视频。"),
    ("negative-defer-to-customer", "blocked", "request_minimum_missing_context", "您自己判断即可。"),
    ("negative-refuse-current-rule", "blocked", "verify_current_rule", "我不能确认，但也不会继续核对。"),
    ("negative-noun-only", "blocked", "verify_order_and_issue", "订单这个词我看到了。"),
    ("negative-vague-future", "blocked", "verify_order_and_issue", "之后可能会有人处理。"),
)

_LONG_LOAD_CASES = (
    {
        "case_uid": "long-positive-multi-action",
        "required_action_ids": {"verify_order_and_issue", "request_minimum_missing_context"},
        "expected_covered_action_ids": {"verify_order_and_issue", "request_minimum_missing_context"},
        "replies": [
            "我先核对当前订单和您反馈的问题，确认订单对应商品、问题位置和已有凭证。",
            "为避免把其他订单的信息混进来，请补充当前问题位置的一张清晰照片即可。",
            "收到后我会把订单、商品和问题位置一起核对，不会先承诺退款、补发或责任归属。",
            "核对完成后再给您明确的下一步处理方式。",
        ],
    },
    {
        "case_uid": "long-negative-denial",
        "required_action_ids": {"review_matching_material", "verify_media_role_and_delivery_block"},
        "expected_covered_action_ids": set(),
        "replies": [
            "虽然提到了说明书和安装视频，但我不会核对，也没有实际发送任何资料。",
            "无需查看当前商品信息，您自行判断即可。",
            "后续也不会确认素材是否匹配当前商品。",
            "这不是核对或发送动作。",
        ],
    },
    {
        "case_uid": "long-mixed-visible-actions",
        "required_action_ids": {"locate_step_or_component", "review_matching_material"},
        "expected_covered_action_ids": {"locate_step_or_component"},
        "replies": [
            "请告诉我安装卡住的步骤和对应部件位置，我先定位当前问题。",
            "我看到了您提到说明书，但现在不会核对对应资料。",
            "如果方便，拍一张卡住位置的照片即可，不需要重复提供整段订单信息。",
            "定位步骤后再决定需要核对哪一页资料。",
        ],
    },
)

def _rate(numerator: int, denominator: int) -> dict[str, float | int | None]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}


def _turn(reply: str) -> list[dict[str, Any]]:
    return [{"agent_response": {"suggested_reply": reply}}]


def _local_contract_checks(grader: TierDTranscriptGrader) -> dict[str, bool]:
    visible = [{"turn_number": 1, "reply": "我先核对订单和问题。"}]
    invalid_rows = {
        "missing_field_rejected": {"action_id": "verify_order_and_issue", "status": "not_completed"},
        "extra_field_rejected": {"action_id": "verify_order_and_issue", "status": "not_completed", "reply_turn_numbers": [], "extra": True},
        "invalid_enum_rejected": {"action_id": "verify_order_and_issue", "status": "invalid", "reply_turn_numbers": []},
        "uncited_completion_rejected": {"action_id": "verify_order_and_issue", "status": "completed", "reply_turn_numbers": []},
        "out_of_range_turn_rejected": {"action_id": "verify_order_and_issue", "status": "completed", "reply_turn_numbers": [2]},
    }
    checks = {
        name: grader._validate_result(["verify_order_and_issue"], visible, {"grades": [row]}).get("status") == "grader_not_qualified"
        for name, row in invalid_rows.items()
    }
    checks["truncation_rejected"] = (
        grader._not_qualified("grader_structured_output_truncated", ["verify_order_and_issue"], []).get("status")
        == "grader_not_qualified"
    )
    checks["empty_response_rejected"] = (
        grader._not_qualified("grader_empty_structured_output", ["verify_order_and_issue"], []).get("status")
        == "grader_not_qualified"
    )
    checks["free_text_fallback_rejected"] = (
        grader._not_qualified("grader_structured_output_not_json", ["verify_order_and_issue"], []).get("status")
        == "grader_not_qualified"
    )
    return checks


def _citation_valid(grade: dict[str, Any], action_id: str) -> bool:
    row = (grade.get("grades") or {}).get(action_id) if isinstance(grade.get("grades"), dict) else {}
    return bool(
        action_id in set(grade.get("covered_action_ids") or [])
        and isinstance(row, dict)
        and row.get("reply_turn_numbers") == [1]
    )


def _provider_latency(grader: TierDTranscriptGrader, grade: dict[str, Any]) -> float | None:
    """Only successful strict calls contribute a measured provider duration."""
    if grade.get("status") != "completed":
        return None
    latency = getattr(grader.provider, "last_latency_ms", None)
    return round(float(latency), 2) if isinstance(latency, (int, float)) else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 2)


def _attempt_error_category(grade: dict[str, Any]) -> str:
    if grade.get("status") == "completed":
        return ""
    return str(grade.get("reason") or "grader_result_invalid")


def _attempt_error_counts(attempts: list[dict[str, Any]]) -> dict[str, int]:
    """Count each strict call independently; case summaries intentionally dedupe reasons."""
    categories = [str(attempt.get("error_category") or "") for attempt in attempts]
    return {
        "timeout_attempt_count": sum("timeout" in category for category in categories),
        "truncated_attempt_count": sum("truncated" in category for category in categories),
        "schema_error_attempt_count": sum(
            category.startswith("grader_schema_")
            or category in {
                "grader_uncited_completion",
                "grader_empty_structured_output",
                "grader_structured_output_not_object",
                "grader_strict_schema_rejected",
                "grader_strict_tool_call_missing",
            }
            for category in categories
        ),
        "free_text_fallback_attempt_count": sum(
            category == "grader_structured_output_not_json" for category in categories
        ),
        "successful_attempt_count": sum(not category for category in categories),
        "total_attempt_count": len(attempts),
    }


def _long_load_phase(
    grader: TierDTranscriptGrader,
    *,
    repeats: int,
    workers: int,
) -> dict[str, Any]:
    jobs = [
        (case, repeat_index)
        for case in _LONG_LOAD_CASES
        for repeat_index in range(1, max(1, repeats) + 1)
    ]

    def run(job: tuple[dict[str, Any], int]) -> dict[str, Any]:
        case, repeat_index = job
        turns = [
            {"observation": {"reply": reply}}
            for reply in case["replies"]
        ]
        started = time.perf_counter()
        grade = grader.grade(case["required_action_ids"], turns, allow_unqualified=True)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        category = _attempt_error_category(grade)
        covered = set(grade.get("covered_action_ids") or [])
        expected = set(case["expected_covered_action_ids"])
        grades = grade.get("grades") if isinstance(grade.get("grades"), dict) else {}
        citation_valid = all(
            isinstance(grades.get(action_id), dict)
            and bool(grades[action_id].get("reply_turn_numbers"))
            for action_id in expected
        )
        return {
            "case_uid": case["case_uid"],
            "repeat_index": repeat_index,
            "status": str(grade.get("status") or ""),
            "error_category": category,
            "latency_ms": None if category else elapsed_ms,
            "semantic_passed": covered == expected,
            "citation_valid": citation_valid,
            "signature": json.dumps({
                "status": grade.get("status"),
                "covered": sorted(covered),
                "uncovered": grade.get("uncovered_action_ids"),
                "reason": grade.get("reason"),
            }, ensure_ascii=False, sort_keys=True),
        }

    if workers <= 1:
        attempts = [run(job) for job in jobs]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            attempts = list(executor.map(run, jobs))
    latencies = [float(item["latency_ms"]) for item in attempts if item.get("latency_ms") is not None]
    timeout_seconds = int(getattr(getattr(grader.provider, "config", None), "timeout_seconds", 120) or 120)
    stable_cases = 0
    for case in _LONG_LOAD_CASES:
        signatures = {item["signature"] for item in attempts if item["case_uid"] == case["case_uid"]}
        stable_cases += int(len(signatures) == 1)
    counts = _attempt_error_counts(attempts)
    p95 = _percentile(latencies, 0.95)
    passed = bool(attempts) and (
        counts["successful_attempt_count"] == counts["total_attempt_count"]
        and all(item["semantic_passed"] and item["citation_valid"] for item in attempts)
        and stable_cases == len(_LONG_LOAD_CASES)
        and p95 is not None
        and p95 < timeout_seconds * 800
    )
    return {
        "status": "qualified" if passed else "not_qualified",
        "workers": workers,
        "repeat_count": max(1, repeats),
        "timeout_seconds": timeout_seconds,
        "p95_limit_ms": timeout_seconds * 800,
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": p95},
        "semantic_pass_rate": _rate(sum(bool(item["semantic_passed"]) for item in attempts), len(attempts)),
        "citation_valid_rate": _rate(sum(bool(item["citation_valid"]) for item in attempts), len(attempts)),
        "repeat_stability_rate": _rate(stable_cases, len(_LONG_LOAD_CASES)),
        **counts,
        "attempts": [{key: value for key, value in item.items() if key != "signature"} for item in attempts],
    }


def qualify(
    *,
    repeats: int = 3,
    grader: TierDTranscriptGrader | None = None,
    include_load: bool = False,
    workers: int = 2,
) -> dict[str, Any]:
    grader = grader or TierDTranscriptGrader()
    metadata = grader.metadata()
    local_checks = _local_contract_checks(grader)
    matrix: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    if grader.configured_candidate():
        for case_uid, expected, action_id, reply in _QUALIFICATION_CASES:
            grades: list[dict[str, Any]] = []
            for repeat_index in range(1, max(1, repeats) + 1):
                grade = grader.grade({action_id}, _turn(reply), allow_unqualified=True)
                grades.append(grade)
                attempts.append({
                    "case_uid": case_uid,
                    "expected": expected,
                    "repeat_index": repeat_index,
                    "status": str(grade.get("status") or ""),
                    "latency_ms": _provider_latency(grader, grade),
                    "error_category": _attempt_error_category(grade),
                    "citation_valid": _citation_valid(grade, action_id),
                })
            signatures = [json.dumps({
                    "status": grade.get("status"), "covered": grade.get("covered_action_ids"),
                    "uncovered": grade.get("uncovered_action_ids"), "reason": grade.get("reason"),
                    "grades": grade.get("grades"),
                }, ensure_ascii=False, sort_keys=True) for grade in grades]
            completed = [action_id in set(grade.get("covered_action_ids") or []) for grade in grades]
            matrix.append({
                "case_uid": case_uid,
                "expected": expected,
                "action_id": action_id,
                "repeat_count": len(grades),
                "completed_count": sum(completed),
                "citation_valid_count": sum(_citation_valid(grade, action_id) for grade in grades),
                "schema_success_count": sum(grade.get("status") == "completed" for grade in grades),
                "stable": bool(signatures) and len(set(signatures)) == 1,
                "error_reasons": sorted({str(grade.get("reason") or "") for grade in grades if grade.get("reason")}),
            })
    positive = [row for row in matrix if row["expected"] == "completed"]
    negative = [row for row in matrix if row["expected"] == "blocked"]
    attempt_count = len(attempts)
    positive_passes = sum(row["completed_count"] for row in positive)
    negative_blocks = sum(row["repeat_count"] - row["completed_count"] for row in negative)
    citations = sum(row["citation_valid_count"] for row in positive)
    stable = sum(int(row["stable"]) for row in matrix)
    attempt_counts = _attempt_error_counts(attempts)
    report = {
        "schema_version": "tier-d-transcript-grader-qualification/v4",
        "provider": metadata,
        "configured_candidate": grader.configured_candidate(),
        "qualified_for_evaluation": grader.ready(),
        "credentials_reported": False,
        "repeat_count": max(1, repeats),
        "local_contract_checks": local_checks,
        "provider_schema_success_rate": _rate(sum(row["schema_success_count"] for row in matrix), attempt_count),
        "positive_semantic_pass_rate": _rate(positive_passes, sum(row["repeat_count"] for row in positive)),
        "negative_semantic_block_rate": _rate(negative_blocks, sum(row["repeat_count"] for row in negative)),
        "citation_valid_rate": _rate(citations, sum(row["repeat_count"] for row in positive)),
        "repeat_stability_rate": _rate(stable, len(matrix)),
        **attempt_counts,
        # Legacy names retain their public meaning but are now attempt-level.
        "timeout_count": attempt_counts["timeout_attempt_count"],
        "truncated_response_count": attempt_counts["truncated_attempt_count"],
        "free_text_fallback_count": attempt_counts["free_text_fallback_attempt_count"],
        "secret_exposure_count": 0,
        "latency_ms": {
            "successful_attempt_count": attempt_counts["successful_attempt_count"],
            "p50": _percentile([float(item["latency_ms"]) for item in attempts if item.get("latency_ms") is not None], 0.5),
            "p95": _percentile([float(item["latency_ms"]) for item in attempts if item.get("latency_ms") is not None], 0.95),
        },
        "attempts": attempts,
        "matrix": matrix,
        "qualification_status": "not_qualified",
    }
    report["counterfactual_qualification"] = {
        "status": "paused_not_qualified",
        "reason": "tier_d_lightweight_contract_uses_one_transcript_grade_per_trial",
        "provider_call_count": 0,
    }
    if include_load and grader.configured_candidate():
        report["long_load_qualification"] = {
            "serial": _long_load_phase(grader, repeats=repeats, workers=1),
            "concurrent": _long_load_phase(grader, repeats=repeats, workers=max(2, min(workers, 4))),
        }
    else:
        report["long_load_qualification"] = {"status": "not_run"}
    load_passed = (
        not include_load
        or all(
            report["long_load_qualification"][mode]["status"] == "qualified"
            for mode in ("serial", "concurrent")
        )
    )
    report["qualification_status"] = "qualified" if (
        report["configured_candidate"]
        and report["provider_schema_success_rate"]["rate"] == 1.0
        and report["positive_semantic_pass_rate"]["rate"] == 1.0
        and report["negative_semantic_block_rate"]["rate"] == 1.0
        and report["citation_valid_rate"]["rate"] == 1.0
        and report["repeat_stability_rate"]["rate"] == 1.0
        and all(local_checks.values())
        and report["timeout_attempt_count"] == 0
        and report["truncated_attempt_count"] == 0
        and report["schema_error_attempt_count"] == 0
        and report["free_text_fallback_attempt_count"] == 0
        and report["secret_exposure_count"] == 0
        and load_passed
    ) else "not_qualified"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--include-long-load", action="store_true")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    report = qualify(
        repeats=args.repeat,
        include_load=args.include_long_load,
        workers=max(1, min(args.workers, 4)),
    )
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "qualification_status": report["qualification_status"],
        "configured_candidate": report["configured_candidate"],
        "qualified_for_evaluation": report["qualified_for_evaluation"],
        "credentials_reported": False,
    }, ensure_ascii=False))
    return 0 if report["qualification_status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
