"""
Golden Case Runner — 读取回归测试 JSON 并验证。

用法:
    python -m pytest tests/test_golden_case_runner.py -q
    python tests/golden_case_runner.py
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from app.services.reply_service import ReplyService


GOLDEN_CASES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_cases", "bad_cases")


def load_golden_cases() -> list[dict]:
    """Load all golden case JSON files."""
    cases = []
    if not os.path.exists(GOLDEN_CASES_DIR):
        return cases
    for fname in sorted(os.listdir(GOLDEN_CASES_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(GOLDEN_CASES_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            cases.append(json.load(f))
    return cases


def run_golden_case(case: dict, reply_service: ReplyService) -> dict:
    """Run a single golden case and return results."""
    t0 = time.time()
    input_data = case.get("input", {})
    expect = case.get("expect", {})

    customer_message = input_data.get("customer_message", "")
    order_id = ""
    tracking_no = ""
    context = input_data.get("context", {})

    if isinstance(context, dict):
        order_id = context.get("order_id", "")
        tracking_no = context.get("tracking_no", "")

    result = reply_service.analyze(
        customer_message=customer_message,
        order_id=order_id,
        tracking_no=tracking_no,
        conversation_id="golden_case_test",
    )

    duration_ms = int((time.time() - t0) * 1000)

    # Verify expectations
    checks = {}

    # Intent check
    allowed_intents = expect.get("allowed_intents", [])
    actual_intent = result.intent
    if allowed_intents:
        checks["intent_match"] = actual_intent in allowed_intents
    else:
        checks["intent_match"] = True

    # Required tools — check from multiple sources
    required_tools = expect.get("required_tools", [])
    if required_tools:
        ed = result.execution_debug or {}
        ed_tools = [tc.get("tool_name", "") for tc in ed.get("tool_calls", [])
                    if tc.get("status") not in ("skipped", "planned")]
        used_tool = result.used_fact_tool or ""
        all_tools = set(ed_tools) | {used_tool}
        checks["required_tools_called"] = any(t in " ".join(all_tools) for t in required_tools) if all_tools else False
    else:
        checks["required_tools_called"] = True

    # Must contain
    reply = result.suggested_reply
    must_contain = expect.get("reply_must_contain", [])
    checks["must_contain"] = all(phrase in reply for phrase in must_contain) if must_contain else True

    # Must not contain
    must_not = expect.get("reply_must_not_contain", [])
    checks["must_not_contain"] = all(phrase not in reply for phrase in must_not) if must_not else True

    # Duration
    max_ms = expect.get("max_duration_ms", 10000)
    checks["duration_ok"] = duration_ms <= max_ms

    # Human review
    checks["need_human_review"] = result.requires_human_review == expect.get("need_human_review", False)

    all_passed = all(checks.values())

    return {
        "case_id": case.get("case_id", ""),
        "name": case.get("name", ""),
        "passed": all_passed,
        "duration_ms": duration_ms,
        "checks": checks,
        "actual_intent": actual_intent,
        "actual_reply_length": len(reply),
    }


def run_all_cases() -> list[dict]:
    """Run all golden cases and return results."""
    from app.main import get_reply_service
    service = get_reply_service()
    cases = load_golden_cases()
    results = []
    for case in cases:
        try:
            results.append(run_golden_case(case, service))
        except Exception as e:
            results.append({
                "case_id": case.get("case_id", ""),
                "name": case.get("name", ""),
                "passed": False,
                "error": str(e),
            })
    return results


if __name__ == "__main__":
    results = run_all_cases()
    for r in results:
        status = "PASS" if r.get("passed") else "FAIL"
        print(f"[{status}] {r.get('case_id', '')} {r.get('name', '')} ({r.get('duration_ms', 0)}ms)")
        if not r.get("passed"):
            for k, v in r.get("checks", {}).items():
                if not v:
                    print(f"  FAIL: {k}")
            if r.get("error"):
                print(f"  ERROR: {r['error']}")
    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n{passed}/{len(results)} passed")
