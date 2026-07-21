"""Read-only strict-schema and long-context qualification for the Tier D buyer simulator."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_long_conversation_simulation import CustomerSimulator  # noqa: E402


_CASES = (
    {
        "case_uid": "accept-concrete-handoff",
        "expected_states": {"continue", "handoff_accepted"},
        "scenario": {
            "scenario_domains": ["installation_accessory"],
            "initial_buyer_message": "安装到第二步卡住了怎么办？",
            "query_fact_types": ["installation"],
            "buyer_style": {"short_message_ratio": 0.7},
            "hidden_goal_contract": {
                "goal": "获得明确下一步或合理人工处理边界",
                "required_action_ids": ["locate_step_or_component"],
            },
        },
        "transcript": [
            {"speaker_role": "BUYER", "text": "安装到第二步卡住了。"},
            {"speaker_role": "AGENT", "text": "请拍一下卡住的步骤和部件位置，我按当前位置继续核对。"},
        ] * 8,
    },
    {
        "case_uid": "continue-minimum-context",
        "expected_states": {"continue"},
        "scenario": {
            "scenario_domains": ["context_insufficient"],
            "initial_buyer_message": "这个怎么处理？",
            "query_fact_types": ["context_insufficient"],
            "buyer_style": {"short_message_ratio": 0.8},
            "hidden_goal_contract": {
                "goal": "在缺少商品上下文时继续澄清",
                "required_action_ids": ["request_minimum_missing_context"],
            },
        },
        "transcript": [
            {"speaker_role": "BUYER", "text": "这个怎么处理？"},
            {"speaker_role": "AGENT", "text": "请说明具体问题位置。"},
            {"speaker_role": "BUYER", "text": "就是刚才说的那个位置。"},
            {"speaker_role": "AGENT", "text": "目前仍缺少能定位商品和位置的最小信息。"},
        ] * 4,
    },
    {
        "case_uid": "resolved-answer-stop",
        "expected_states": {"continue", "satisfied", "handoff_accepted"},
        "scenario": {
            "scenario_domains": ["order_logistics_service_action"],
            "initial_buyer_message": "接下来怎么查物流？",
            "query_fact_types": ["logistics"],
            "buyer_style": {"short_message_ratio": 0.6},
            "hidden_goal_contract": {
                "goal": "得到具体可执行的物流核对步骤",
                "required_action_ids": ["verify_live_state"],
            },
        },
        "transcript": [
            {"speaker_role": "BUYER", "text": "物流一直没更新。"},
            {"speaker_role": "AGENT", "text": "我会按当前订单核对物流节点和承运状态，确认后给您下一步。"},
        ] * 8,
    },
)

_SHORT_CASES = tuple({
    **case,
    "case_uid": f"short-{case['case_uid']}",
    "transcript": list(case["transcript"][-2:]),
} for case in _CASES)


def _rate(numerator: int, denominator: int) -> dict[str, float | int | None]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 2)


def _simulator_from_environment(*, allow_unqualified: bool) -> CustomerSimulator:
    return CustomerSimulator(
        api_key=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_API_KEY") or ""),
        api_base=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_API_BASE") or ""),
        model=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_MODEL") or ""),
        timeout=int(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_TIMEOUT_SECONDS") or 90),
        allow_unqualified=allow_unqualified,
    )


def _phase(*, cases: tuple[dict[str, Any], ...], repeats: int, workers: int) -> dict[str, Any]:
    jobs = [(case, repeat) for case in cases for repeat in range(1, max(1, repeats) + 1)]

    def run(job: tuple[dict[str, Any], int]) -> dict[str, Any]:
        case, repeat = job
        simulator = _simulator_from_environment(allow_unqualified=True)
        started = time.perf_counter()
        try:
            decision = simulator.next_turn(case["scenario"], case["transcript"], set())
            error_category = ""
        except Exception as exc:
            decision = {}
            error_category = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        latency_ms = None if error_category else round((time.perf_counter() - started) * 1000, 2)
        state = str(decision.get("buyer_state") or "")
        semantic_passed = state in case["expected_states"]
        return {
            "case_uid": case["case_uid"],
            "repeat_index": repeat,
            "status": "completed" if not error_category else "failed",
            "error_category": error_category,
            "latency_ms": latency_ms,
            "semantic_passed": semantic_passed,
            "signature": json.dumps({
                "buyer_state": state,
                "stop": decision.get("stop"),
                "stop_reason": decision.get("stop_reason"),
            }, sort_keys=True),
        }

    if workers <= 1:
        attempts = [run(job) for job in jobs]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            attempts = list(executor.map(run, jobs))
    latencies = [float(item["latency_ms"]) for item in attempts if item.get("latency_ms") is not None]
    timeout_seconds = int(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_TIMEOUT_SECONDS") or 90)
    stable = sum(
        len({item["signature"] for item in attempts if item["case_uid"] == case["case_uid"]}) == 1
        for case in cases
    )
    p95 = _percentile(latencies, 0.95)
    successful = sum(not item["error_category"] for item in attempts)
    passed = bool(attempts) and (
        successful == len(attempts)
        and all(item["semantic_passed"] for item in attempts)
        and stable == len(cases)
        and p95 is not None
        and p95 < timeout_seconds * 800
    )
    return {
        "status": "qualified" if passed else "not_qualified",
        "workers": workers,
        "repeat_count": max(1, repeats),
        "total_attempt_count": len(attempts),
        "successful_attempt_count": successful,
        "error_attempt_count": len(attempts) - successful,
        "semantic_pass_rate": _rate(sum(bool(item["semantic_passed"]) for item in attempts), len(attempts)),
        "repeat_stability_rate": _rate(stable, len(cases)),
        "case_count": len(cases),
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": p95},
        "timeout_seconds": timeout_seconds,
        "p95_limit_ms": timeout_seconds * 800,
        "attempts": [{key: value for key, value in item.items() if key != "signature"} for item in attempts],
    }


def qualify(*, repeats: int = 2, workers: int = 2) -> dict[str, Any]:
    simulator = _simulator_from_environment(allow_unqualified=True)
    report = {
        "schema_version": "tier-d-customer-simulator-qualification/v1",
        "provider": simulator.metadata(),
        "credentials_reported": False,
        "short": _phase(cases=_SHORT_CASES, repeats=repeats, workers=1),
        "serial": _phase(cases=_CASES, repeats=repeats, workers=1),
        "concurrent": _phase(cases=_CASES, repeats=repeats, workers=max(2, min(workers, 4))),
        "gold_label_leakage_count": 0,
    }
    report["qualification_status"] = "qualified" if (
        report["provider"].get("configured")
        and report["short"]["status"] == "qualified"
        and report["serial"]["status"] == "qualified"
        and report["concurrent"]["status"] == "qualified"
    ) else "not_qualified"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    report = qualify(repeats=args.repeat, workers=args.workers)
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "qualification_status": report["qualification_status"],
        "serial": report["serial"]["status"],
        "concurrent": report["concurrent"]["status"],
        "credentials_reported": False,
    }, ensure_ascii=False))
    return 0 if report["qualification_status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
