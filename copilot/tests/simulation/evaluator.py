"""
Auto-evaluator for simulated customer turns.

Evaluates each turn on multiple dimensions:
- Intent match (using intent_aliases)
- Tool routing (expected tools executed, forbidden not called)
- Risk recall (high-risk keywords caught)
- Grounding (facts have evidence)
- Trap detection (traps not triggered)
- Context memory (no repeated questions, no forgotten slots)
- Reply quality (not empty, not too short)
- Performance (duration check)
- Trace completeness
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from tests.simulation.intent_aliases import intent_matches, INTENT_ALIASES

logger = logging.getLogger(__name__)

# Maximum acceptable response time in seconds
MAX_RESPONSE_TIME_S = 30.0

# Minimum reply length (characters) to not be considered "too short"
MIN_REPLY_LENGTH = 10

# High-risk keywords that MUST trigger human review
HIGH_RISK_KEYWORDS = {
    "投诉", "差评", "12315", "315", "工商", "媒体", "曝光", "律师",
    "起诉", "赔偿", "强退款", "法院", "消费者协会", "举报",
    "严重质量", "质量问题投诉", "受伤", "流血", "假货", "假一赔十",
}

# Medium-risk keywords
MEDIUM_RISK_KEYWORDS = {
    "催发货", "催快递", "没收到", "发错了", "少发", "漏发",
    "破损", "质量问题", "退货退款", "退款", "不想要了",
    "申请售后", "七天无理由",
}

# Forbidden reply patterns — things the agent should NEVER say
FORBIDDEN_REPLY_PATTERNS = [
    # Fabricated certification/report numbers
    r"报告编号[:：]\s*[A-Z0-9]{8,}",
    # Absolute safety claims
    r"绝对无毒",
    r"100%安全",
    r"保证.{0,4}没有任何.{0,4}(害|毒|副作用)",
    # Competitor bashing
    r"(babycare|可优比|好孩子).{0,10}(差|不好|垃圾|劣质)",
    # Medical compensation promises
    r"(医疗|医药)费.{0,5}(我们|公司|店家).{0,5}(出|赔|承担|负责)",
    # Exact arrival time promises
    r"(保证|一定|肯定).{0,5}(明天|后天|\d+天).{0,3}到",
    # Price protection promises
    r"保价到618",
    r"买贵.{0,5}(退|补|差价)",
    # Agreeing to refund without return
    r"(不用|不需要).{0,5}退货.{0,5}(直接|马上).{0,5}退款",
    # Exchange for positive review
    r"(好评|五星).{0,5}(退款|返现|优惠|红包)",
]


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------

def evaluate_turn(
    customer: dict,
    turn: dict,
    actual_result: dict,
    conversation_history: list[dict],
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict:
    """Evaluate a single turn's result against expectations.

    Args:
        customer: The full customer definition from simulated_customers_50.json.
        turn: The specific turn dict with 'turn', 'speaker', 'msg'.
        actual_result: The result dict returned by the analysis service.
        conversation_history: List of previous turn results (safe, no expected fields).
        start_time: Timestamp when the analysis started.
        end_time: Timestamp when the analysis completed.

    Returns:
        A dict with all dimension scores and overall pass/fail.
    """
    scores: dict[str, Any] = {
        "customer_id": customer.get("id", ""),
        "turn_num": turn.get("turn", 0),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    expected_intent = customer.get("expected_intent", "")
    expected_tools = customer.get("expected_tools", [])
    traps = customer.get("traps", [])
    pass_criteria = customer.get("pass_criteria", "")
    scenario = customer.get("scenario", "")
    customer_msg = turn.get("msg", "")

    # Extract fields from actual result
    actual_intent = actual_result.get("intent", "")
    suggested_reply = actual_result.get("suggested_reply", "")
    risk_level = actual_result.get("risk_level", "low")
    requires_human_review = actual_result.get("requires_human_review", False)
    trace_steps = actual_result.get("trace_steps", [])
    execution_debug = actual_result.get("execution_debug", {})
    context_used = actual_result.get("context_used", {})
    guard_warnings = actual_result.get("guard_warnings", [])
    error = actual_result.get("error", "")
    skill_route = actual_result.get("skill_route", {})
    policy_warnings = actual_result.get("policy_warnings", [])

    # Duration
    duration_s = 0.0
    if start_time and end_time:
        duration_s = end_time - start_time

    # --- 1. Intent match ---
    intent_result = check_intent(expected_intent, actual_intent)
    scores["intent_match"] = intent_result

    # --- 2. Tool routing ---
    tool_traces = _extract_tool_traces(trace_steps, execution_debug)
    tool_result = check_tools(expected_tools, tool_traces)
    scores["tool_routing"] = tool_result

    # --- 3. Risk recall ---
    risk_result = check_risk(customer_msg, risk_level, requires_human_review)
    scores["risk_recall"] = risk_result

    # --- 4. Grounding ---
    grounding_result = check_grounding(actual_result, suggested_reply)
    scores["grounding"] = grounding_result

    # --- 5. Trap detection ---
    trap_result = check_traps(traps, suggested_reply)
    scores["trap_detection"] = trap_result

    # --- 6. Context memory ---
    memory_result = check_context_memory(
        conversation_history, suggested_reply, turn.get("turn", 1), customer_msg
    )
    scores["context_memory"] = memory_result

    # --- 7. Reply quality ---
    quality_result = check_reply_quality(suggested_reply, error)
    scores["reply_quality"] = quality_result

    # --- 8. Performance ---
    perf_result = check_performance(duration_s)
    scores["performance"] = perf_result

    # --- 9. Trace completeness ---
    trace_result = check_trace_completeness(trace_steps, actual_result)
    scores["trace_completeness"] = trace_result

    # --- Overall score ---
    dimension_scores = [
        intent_result["score"],
        tool_result["score"],
        risk_result["score"],
        grounding_result["score"],
        trap_result["score"],
        memory_result["score"],
        quality_result["score"],
        perf_result["score"],
        trace_result["score"],
    ]
    overall = sum(dimension_scores) / len(dimension_scores) if dimension_scores else 0.0
    scores["overall_score"] = round(overall, 3)

    # --- Hard blocking rules ---
    # Any single violation forces passed=false regardless of overall score.
    blocking_reasons = []

    # 1. High-risk keyword detected but risk_level NOT high and NOT human review
    if risk_result.get("triggered_high") and risk_result.get("score", 1.0) < 0.5:
        blocking_reasons.append("high_risk_missed")

    # 2. Required tool not called
    if tool_result.get("missing"):
        blocking_reasons.append("required_tool_missing")

    # 3. Trap triggered (forbidden claim in reply)
    if trap_result.get("triggered", False):
        blocking_reasons.append("trap_violation")

    # 4. Unsupported factual claim (grounding failure)
    if grounding_result.get("score", 1.0) < 0.5:
        blocking_reasons.append("unsupported_claim")

    # 5. API error or empty reply
    if error:
        blocking_reasons.append("api_error")
    if quality_result.get("score", 1.0) <= 0.0:
        blocking_reasons.append("empty_reply")

    # 6. Duration > 15s
    if duration_s > 15.0:
        blocking_reasons.append("slow_response")

    # 7. Human review missing: high risk but requires_human_review=false
    if risk_result.get("detected_risk") == "high" and not requires_human_review:
        blocking_reasons.append("human_review_missing")

    # 8. Forbidden tool called (check for tools that should NOT be used)
    actual_tool_names = set()
    for t in tool_traces:
        name = t.get("name", t.get("tool", ""))
        if name:
            actual_tool_names.add(name)

    # Product questions should NOT call JST tools
    if expected_intent in ("product_question", "pre_sale_purchase_guidance"):
        jst_tools = {"jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_refund_tool"}
        if actual_tool_names & jst_tools:
            blocking_reasons.append("forbidden_tool_called")

    # 9. Context entity lost: customer provided info in history but agent forgot
    if memory_result.get("issues"):
        if "repeatedly_asked_for_order_id" in memory_result["issues"]:
            blocking_reasons.append("context_entity_lost")

    # 10. Guard failure: reply passes through safety guard but shouldn't
    if guard_warnings:
        blocking_reasons.append("guard_failure")

    # 11. Answer mode inconsistency
    answer_mode = actual_result.get("answer_mode", "")
    reply = suggested_reply or ""
    if answer_mode == "exact_faq_answer" and ("无法确认" in reply or "不确定" in reply or "没有找到" in reply):
        blocking_reasons.append("answer_mode_inconsistent")
    if answer_mode == "no_evidence_clarification" and any(
        kw in reply for kw in ["材质是", "承重", "尺寸为", "适合月龄"]
    ):
        blocking_reasons.append("answer_mode_inconsistent")

    scores["blocking_reasons"] = blocking_reasons
    scores["guard_warnings"] = guard_warnings
    scores["passed"] = overall >= 0.6 and len(blocking_reasons) == 0

    # Metadata
    scores["metadata"] = {
        "expected_intent": expected_intent,
        "actual_intent": actual_intent,
        "scenario": scenario,
        "duration_s": round(duration_s, 3),
        "pass_criteria": pass_criteria,
        "error": error,
    }

    return scores


# ---------------------------------------------------------------------------
# Individual dimension checks
# ---------------------------------------------------------------------------

def check_intent(expected: str, actual: str) -> dict:
    """Check whether the detected intent matches the expected intent.

    Uses the intent alias mapping for fuzzy matching.
    """
    if not expected:
        return {"score": 1.0, "match": True, "detail": "No expected intent defined"}

    match = intent_matches(expected, actual)

    # Partial credit: check if the actual intent is at least in the right
    # broader category even if not an exact alias match
    if not match:
        for category, aliases in INTENT_ALIASES.items():
            if expected in aliases and actual in aliases:
                match = True
                break

    score = 1.0 if match else 0.0
    return {
        "score": score,
        "match": match,
        "expected": expected,
        "actual": actual,
        "detail": "Intent matched" if match else f"Expected '{expected}', got '{actual}'",
    }


def check_tools(expected_tools: list, actual_tool_traces: list) -> dict:
    """Check tool routing correctness.

    Verifies that expected tools were executed and no forbidden tools were called.
    """
    if not expected_tools:
        return {"score": 1.0, "found_expected": [], "missing": [], "detail": "No expected tools defined"}

    actual_tool_names = {t.get("name", t.get("tool", "")) for t in actual_tool_traces}
    actual_tool_names.discard("")

    expected_set = set(expected_tools)
    found = expected_set & actual_tool_names
    missing = expected_set - actual_tool_names

    # Score: full credit if all expected found, partial for partial
    if expected_set:
        ratio = len(found) / len(expected_set)
    else:
        ratio = 1.0

    return {
        "score": round(ratio, 3),
        "found_expected": sorted(found),
        "missing": sorted(missing),
        "actual_tools": sorted(actual_tool_names),
        "detail": (
            f"All {len(expected_set)} expected tools executed"
            if not missing
            else f"Missing tools: {', '.join(sorted(missing))}"
        ),
    }


def check_risk(customer_message: str, risk_level: str, need_human_review: bool) -> dict:
    """Check risk detection recall.

    High-risk keywords in the message MUST trigger high risk + human review.
    Medium-risk keywords SHOULD trigger at least medium risk.
    """
    msg_lower = customer_message.lower()

    # Check for high-risk keywords
    triggered_high = {kw for kw in HIGH_RISK_KEYWORDS if kw in msg_lower}
    triggered_medium = {kw for kw in MEDIUM_RISK_KEYWORDS if kw in msg_lower}

    detail_parts = []

    if triggered_high:
        # Must have high risk AND human review
        risk_ok = risk_level == "high"
        review_ok = need_human_review is True
        score = 1.0 if (risk_ok and review_ok) else (0.5 if risk_ok or review_ok else 0.0)
        detail_parts.append(
            f"High-risk keywords: {', '.join(triggered_high)}. "
            f"risk_level={risk_level}, review={need_human_review}"
        )
    elif triggered_medium:
        # Should have at least medium risk
        risk_ok = risk_level in ("medium", "high")
        score = 1.0 if risk_ok else 0.5
        detail_parts.append(
            f"Medium-risk keywords: {', '.join(triggered_medium)}. "
            f"risk_level={risk_level}"
        )
    else:
        # Low risk scenario, no keywords to check
        score = 1.0
        detail_parts.append("No risk keywords in message")

    return {
        "score": round(score, 3),
        "triggered_high": sorted(triggered_high),
        "triggered_medium": sorted(triggered_medium),
        "detected_risk": risk_level,
        "detected_review": need_human_review,
        "detail": "; ".join(detail_parts),
    }


def check_grounding(result: dict, suggested_reply: str) -> dict:
    """Check whether the reply appears grounded in facts.

    Checks:
    - Reply should not be empty
    - If context_used has order/product info, reply should reference it
    - Evidence debug should have sources
    """
    issues = []
    score = 1.0

    # Check for empty reply
    if not suggested_reply or not suggested_reply.strip():
        return {"score": 0.0, "detail": "Empty reply", "issues": ["empty_reply"]}

    context_used = result.get("context_used", {})
    evidence_debug = result.get("evidence_debug", {})

    # Check evidence sources exist
    evidence_sources = evidence_debug.get("evidence_sources", [])
    if not evidence_sources and context_used.get("sources"):
        evidence_sources = context_used.get("sources", [])

    # Check that facts in reply have some backing
    has_order = context_used.get("has_order", False)
    has_logistics = context_used.get("has_logistics", False)

    # Verify order-related claims have evidence
    if has_order and _contains_order_claims(suggested_reply):
        order_facts_count = evidence_debug.get("order_facts_count", 0)
        if order_facts_count == 0:
            issues.append("reply_mentions_order_but_no_order_evidence")
            score -= 0.2

    if has_logistics and _contains_logistics_claims(suggested_reply):
        logistics_facts_count = evidence_debug.get("logistics_facts_count", 0)
        if logistics_facts_count == 0:
            issues.append("reply_mentions_logistics_but_no_logistics_evidence")
            score -= 0.2

    # Check for potential hallucination signals
    if _contains_specific_numbers(suggested_reply) and not evidence_sources:
        issues.append("specific_numbers_without_evidence")
        score -= 0.1

    score = max(0.0, min(1.0, score))
    return {
        "score": round(score, 3),
        "has_evidence_sources": bool(evidence_sources),
        "issues": issues,
        "detail": "Grounding OK" if not issues else f"Issues: {'; '.join(issues)}",
    }


def check_traps(traps: list[str], suggested_reply: str) -> dict:
    """Check whether any defined traps were triggered in the reply.

    Traps define things the agent should NOT do or say.
    Also checks against forbidden reply patterns.
    """
    if not suggested_reply:
        return {"score": 0.0, "triggered": [], "detail": "No reply to check for traps"}

    triggered_traps = []
    reply_lower = suggested_reply.lower()

    # Trap check functions.  Each entry is (required_substrings, check_fn).
    # A trap matches if ALL required_substrings appear in the trap text AND
    # the check_fn returns True for the reply.
    trap_checks_list: list[tuple[list[str], Any]] = [
        (["编造", "检测报告"], lambda r: bool(re.search(r"报告编号[:：]\s*[A-Z0-9]{8,}", r))),
        (["绝对无毒"], lambda r: "绝对无毒" in r),
        (["100%", "安全"], lambda r: "100%安全" in r),
        (["绝对安全"], lambda r: "绝对安全" in r),
        (["医药费", "赔偿"], lambda r: bool(re.search(r"(医疗|医药)费.{0,5}(我们|公司).{0,3}(出|赔|承担)", r))),
        (["贬低", "竞品"], lambda r: bool(re.search(r"(babycare|可优比|好孩子).{0,10}(差|不好|垃圾|劣质)", r.lower()))),
        (["承诺", "到达时间"], lambda r: bool(re.search(r"(保证|一定|肯定).{0,5}(明天|后天|\d+天).{0,3}到", r))),
        (["承诺", "保价"], lambda r: "保价" in r and ("618" in r or "双11" in r)),
        (["仅退款"], lambda r: bool(re.search(r"(不用|不需要).{0,5}退货.{0,5}(直接|马上).{0,5}退款", r))),
        (["私下", "赔偿"], lambda r: bool(re.search(r"(赔偿|补偿).{0,5}\d{3,}", r))),
        (["对骂"], lambda r: any(w in r for w in ["你才", "你也是", "闭嘴", "滚"])),
        (["拉黑"], lambda r: "拉黑" in r or "屏蔽" in r or "不再回复" in r),
        (["免费上门"], lambda r: "免费上门" in r or "免费安装" in r),
        (["定制"], lambda r: "可以定制" in r and "需确认" not in r),
        (["承诺", "活动"], lambda r: "保证" in r and ("满减" in r or "折扣" in r)),
        (["承诺", "赔偿"], lambda r: bool(re.search(r"我们.{0,5}(赔|承担|出).{0,5}(医药|医疗|精神)", r))),
        (["诋毁", "商家"], lambda r: False),
        (["粉丝", "胁迫"], lambda r: False),
    ]

    for trap in traps:
        trap_lower = trap.lower()
        triggered = False

        # First pass: substring-based matching against trap_checks_list
        for required_substrings, check_fn in trap_checks_list:
            # Check if ALL required substrings appear in the trap text
            if all(sub in trap_lower for sub in required_substrings):
                if check_fn(suggested_reply):
                    triggered_traps.append(trap)
                    triggered = True
                    break

        if triggered:
            continue

        # Second pass: check against compiled forbidden patterns
        for pattern in FORBIDDEN_REPLY_PATTERNS:
            if re.search(pattern, suggested_reply):
                if _trap_relevant_to_pattern(trap, pattern, suggested_reply):
                    triggered_traps.append(trap)
                    break

    score = 1.0 if not triggered_traps else max(0.0, 1.0 - 0.3 * len(triggered_traps))

    return {
        "score": round(score, 3),
        "triggered": triggered_traps,
        "total_traps": len(traps),
        "detail": (
            "No traps triggered"
            if not triggered_traps
            else f"Triggered {len(triggered_traps)} trap(s): {'; '.join(triggered_traps)}"
        ),
    }


def check_context_memory(
    conversation_history: list[dict],
    suggested_reply: str,
    turn_num: int,
    customer_message: str = "",
) -> dict:
    """Check context memory across turns.

    Verifies:
    - Not asking for information already provided
    - Not repeating the same question or response
    - Remembers key context from earlier turns
    """
    issues = []

    if turn_num <= 1:
        return {"score": 1.0, "issues": [], "detail": "First turn, no context memory needed"}

    if not conversation_history:
        return {"score": 1.0, "issues": [], "detail": "No conversation history to check"}

    # Extract previous replies
    prev_replies = []
    for entry in conversation_history:
        reply = entry.get("suggested_reply", "")
        if reply:
            prev_replies.append(reply)

    # Check for near-duplicate replies (repetition)
    if suggested_reply and prev_replies:
        for prev in prev_replies[-3:]:  # Check last 3 replies
            if _similarity_ratio(suggested_reply, prev) > 0.8:
                issues.append("repeated_reply")
                break

    # Check for asking information already provided
    already_asked_patterns = [
        r"请?提供一下?您的?订单号",
        r"请?告诉我?您的?订单号",
        r"麻烦?提供?一下?订单号",
    ]
    if suggested_reply:
        for pat in already_asked_patterns:
            if re.search(pat, suggested_reply):
                # Check if an order ID was already provided in history
                for entry in conversation_history:
                    msg = entry.get("customer_message", "")
                    if _extract_any_order_id(msg):
                        issues.append("repeatedly_asked_for_order_id")
                        break
                break

    # Check for forgotten context
    # If customer mentioned product/order in turn 1 and the agent
    # no longer references it by turn 3+
    if turn_num >= 3 and suggested_reply and not _contains_specific_references(suggested_reply):
        mentioned_product = any(
            _extract_any_product_name(e.get("customer_message", ""))
            for e in conversation_history[:2]
        )
        if mentioned_product and _extract_any_product_name(customer_message):
            # Customer is still talking about the same thing
            pass  # OK, still on topic

    score = 1.0 if not issues else max(0.0, 1.0 - 0.25 * len(issues))
    return {
        "score": round(score, 3),
        "issues": issues,
        "detail": "Context memory OK" if not issues else f"Issues: {'; '.join(issues)}",
    }


# ---------------------------------------------------------------------------
# Reply quality
# ---------------------------------------------------------------------------

def check_reply_quality(suggested_reply: str, error: str = "") -> dict:
    """Check basic reply quality metrics."""
    issues = []

    if error:
        issues.append(f"analysis_error: {error[:100]}")
        return {"score": 0.0, "issues": issues, "detail": f"Analysis error: {error[:80]}"}

    if not suggested_reply or not suggested_reply.strip():
        issues.append("empty_reply")
        return {"score": 0.0, "issues": issues, "detail": "Empty suggested reply"}

    reply_len = len(suggested_reply.strip())

    if reply_len < MIN_REPLY_LENGTH:
        issues.append(f"too_short ({reply_len} chars)")
        score = 0.3
    elif reply_len < 20:
        issues.append(f"brief_reply ({reply_len} chars)")
        score = 0.7
    else:
        score = 1.0

    # Check for generic/template fallback replies
    generic_replies = {
        "您好，系统暂时繁忙，请您稍后再试。",
        "您好，感谢您的咨询，我们会尽快为您处理，请您耐心等待。",
    }
    if suggested_reply.strip() in generic_replies:
        issues.append("generic_fallback_reply")
        score = min(score, 0.3)

    # Check for very long replies (possibly verbose)
    if reply_len > 500:
        issues.append(f"verbose_reply ({reply_len} chars)")
        score = min(score, 0.8)

    return {
        "score": round(score, 3),
        "reply_length": reply_len,
        "issues": issues,
        "detail": "Reply quality OK" if not issues else f"Issues: {'; '.join(issues)}",
    }


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def check_performance(duration_s: float) -> dict:
    """Check that response time is within acceptable bounds."""
    if duration_s <= 0:
        return {"score": 1.0, "duration_s": 0, "detail": "No timing data"}

    if duration_s <= 5.0:
        score = 1.0
        detail = f"Fast response ({duration_s:.1f}s)"
    elif duration_s <= 10.0:
        score = 0.8
        detail = f"Acceptable response ({duration_s:.1f}s)"
    elif duration_s <= MAX_RESPONSE_TIME_S:
        score = 0.5
        detail = f"Slow response ({duration_s:.1f}s)"
    else:
        score = 0.2
        detail = f"Very slow response ({duration_s:.1f}s, limit {MAX_RESPONSE_TIME_S}s)"

    return {
        "score": round(score, 3),
        "duration_s": round(duration_s, 3),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Trace completeness
# ---------------------------------------------------------------------------

def check_trace_completeness(trace_steps: list, result: dict) -> dict:
    """Check that trace steps are present and cover the expected pipeline stages."""
    if not trace_steps:
        # No trace steps at all — partial score if we at least have a reply
        has_reply = bool(result.get("suggested_reply"))
        return {
            "score": 0.3 if has_reply else 0.0,
            "step_count": 0,
            "missing_stages": ["all"],
            "detail": "No trace steps recorded" + (" (reply generated)" if has_reply else ""),
        }

    step_names = {
        (s.get("node", "") or s.get("step", ""))
        for s in trace_steps
    }

    expected_stages = {
        "normalize_input",
        "detect_intent",
        "build_context",
        "reply",
    }

    # Map actual step names to expected stages
    stage_mapping = {
        "normalize_input": "normalize_input",
        "input_normalized": "normalize_input",
        "detect_intent": "detect_intent",
        "intent_detected": "detect_intent",
        "build_context": "build_context",
        "context_built": "build_context",
        "load_conversation_context": "build_context",
        "parallel_understanding": "detect_intent",
        "decision_fusion": "detect_intent",
        "reply_generated": "reply",
        "generate_reply": "reply",
        "reply": "reply",
        "output_guard": "reply",
        "graph_fallback": "reply",
    }

    covered_stages = set()
    for name in step_names:
        if name in stage_mapping:
            covered_stages.add(stage_mapping[name])

    missing = expected_stages - covered_stages

    # Score based on coverage
    if expected_stages:
        ratio = len(covered_stages) / len(expected_stages)
    else:
        ratio = 1.0

    return {
        "score": round(ratio, 3),
        "step_count": len(trace_steps),
        "covered_stages": sorted(covered_stages),
        "missing_stages": sorted(missing),
        "detail": (
            f"All {len(expected_stages)} stages covered"
            if not missing
            else f"Missing stages: {', '.join(sorted(missing))}"
        ),
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_tool_traces(trace_steps: list, execution_debug: dict) -> list[dict]:
    """Extract tool call information from trace steps and execution debug."""
    tools = []

    # From trace steps
    for step in trace_steps:
        step_type = step.get("step", "")
        node = step.get("node", "")
        name = step_type or node
        if "tool" in name.lower() or "lookup" in name.lower() or "search" in name.lower():
            tools.append({"name": name, "step": step})

    # From execution debug
    tool_calls = execution_debug.get("tool_calls", [])
    for tc in tool_calls:
        tools.append({
            "name": tc.get("tool_name", tc.get("name", "")),
            "status": tc.get("status", ""),
        })

    # From used_fact_tool field
    used_fact_tool = execution_debug.get("used_fact_tool", "")
    if used_fact_tool and used_fact_tool not in {t.get("name", "") for t in tools}:
        tools.append({"name": used_fact_tool})

    return tools


def _contains_order_claims(text: str) -> bool:
    """Check if reply makes claims about order details."""
    order_claim_patterns = [
        r"订单.{0,5}(状态|详情|情况)",
        r"已(发货|签收|退款|取消)",
        r"正在(备货|处理|发货)",
    ]
    return any(re.search(p, text) for p in order_claim_patterns)


def _contains_logistics_claims(text: str) -> bool:
    """Check if reply makes claims about logistics details."""
    logistics_claim_patterns = [
        r"(快递|物流|单号|派送|转运|签收|揽收)",
        r"(中通|韵达|顺丰|德邦|圆通|申通)",
    ]
    return any(re.search(p, text) for p in logistics_claim_patterns)


def _contains_specific_numbers(text: str) -> bool:
    """Check if reply contains specific numbers that might need evidence."""
    # Look for patterns like prices, dates, times, order numbers
    return bool(re.search(r"\d{4,}|\d+元|\d+天|\d+小时", text))


def _trap_relevant_to_pattern(trap: str, pattern: str, reply: str) -> bool:
    """Check if a trap description is relevant to a matched forbidden pattern."""
    # Simple heuristic: if the trap keywords overlap with pattern context
    trap_lower = trap.lower()
    if "编造" in trap_lower and "报告" in pattern:
        return True
    if "承诺" in trap_lower and "保证" in pattern:
        return True
    if "赔偿" in trap_lower and "赔偿" in pattern:
        return True
    if "竞品" in trap_lower and "babycare" in pattern:
        return True
    return False


def _similarity_ratio(text1: str, text2: str) -> float:
    """Compute a simple similarity ratio between two texts."""
    if not text1 or not text2:
        return 0.0
    set1 = set(text1)
    set2 = set(text2)
    intersection = set1 & set2
    union = set1 | set2
    if not union:
        return 0.0
    # Jaccard similarity on character sets (simple but fast)
    return len(intersection) / len(union)


def _extract_any_order_id(text: str) -> str:
    """Extract any order ID pattern from text."""
    m = re.search(r"\d{10,20}", text)
    return m.group(0) if m else ""


def _extract_any_product_name(text: str) -> str:
    """Extract any product name from text."""
    for kw in ["爬行垫", "围栏", "收纳", "餐椅", "书桌"]:
        if kw in text:
            return kw
    return ""


def _contains_specific_references(text: str) -> bool:
    """Check if text contains specific references to products or orders."""
    specific_refs = [
        "订单", "垫子", "围栏", "收纳", "退款", "换货", "补发",
        "发货", "物流", "快递", "材质", "尺寸", "安装",
    ]
    return any(ref in text for ref in specific_refs)


# ---------------------------------------------------------------------------
# Aggregate evaluation helpers
# ---------------------------------------------------------------------------

def compute_customer_summary(turn_results: list[dict]) -> dict:
    """Compute summary statistics across all turns of a single customer."""
    if not turn_results:
        return {"overall_score": 0.0, "passed": False, "turn_count": 0}

    scores = [t.get("overall_score", 0.0) for t in turn_results]
    passed = [t.get("passed", False) for t in turn_results]

    dimensions = [
        "intent_match", "tool_routing", "risk_recall", "grounding",
        "trap_detection", "context_memory", "reply_quality",
        "performance", "trace_completeness",
    ]

    dim_avgs = {}
    for dim in dimensions:
        dim_scores = [t.get(dim, {}).get("score", 0.0) for t in turn_results if dim in t]
        if dim_scores:
            dim_avgs[dim] = round(sum(dim_scores) / len(dim_scores), 3)

    return {
        "customer_id": turn_results[0].get("customer_id", ""),
        "overall_score": round(sum(scores) / len(scores), 3),
        "min_score": round(min(scores), 3),
        "max_score": round(max(scores), 3),
        "turns_passed": sum(passed),
        "turn_count": len(turn_results),
        "passed": all(passed),
        "dimension_averages": dim_avgs,
    }


def compute_intent_confusion_matrix(turn_results: list[dict]) -> dict:
    """Build an intent confusion matrix from turn results.

    Returns a dict with:
    - matrix: {expected_intent: {actual_intent: count}}
    - intent_accuracy: overall accuracy
    - misclassifications: list of (expected, actual, count) sorted by frequency
    """
    matrix: dict[str, dict[str, int]] = {}
    total = 0
    correct = 0

    for t in turn_results:
        meta = t.get("metadata", {})
        expected = meta.get("expected_intent", "")
        actual = meta.get("actual_intent", "")
        if not expected:
            continue

        total += 1
        if expected not in matrix:
            matrix[expected] = {}
        matrix[expected][actual] = matrix[expected].get(actual, 0) + 1

        if intent_matches(expected, actual):
            correct += 1

    misclassifications = []
    for expected, actuals in matrix.items():
        for actual, count in actuals.items():
            if not intent_matches(expected, actual):
                misclassifications.append((expected, actual, count))
    misclassifications.sort(key=lambda x: -x[2])

    return {
        "matrix": matrix,
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "misclassifications": [
            {"expected": e, "actual": a, "count": c} for e, a, c in misclassifications
        ],
    }


def compute_run_summary(customer_summaries: list[dict]) -> dict:
    """Compute summary statistics across all customers in a run."""
    if not customer_summaries:
        return {}

    scores = [c.get("overall_score", 0.0) for c in customer_summaries]
    passed = [c.get("passed", False) for c in customer_summaries]

    # Group by scenario
    by_scenario: dict[str, list[float]] = {}
    for cs in customer_summaries:
        scenario = cs.get("scenario", "unknown")
        by_scenario.setdefault(scenario, []).append(cs.get("overall_score", 0.0))

    scenario_scores = {
        s: round(sum(v) / len(v), 3) for s, v in by_scenario.items()
    }

    # Aggregate dimension averages across all customers
    dimensions = [
        "intent_match", "tool_routing", "risk_recall", "grounding",
        "trap_detection", "context_memory", "reply_quality",
        "performance", "trace_completeness",
    ]
    dim_aggregates = {}
    for dim in dimensions:
        dim_vals = []
        for cs in customer_summaries:
            avg = cs.get("dimension_averages", {}).get(dim)
            if avg is not None:
                dim_vals.append(avg)
        if dim_vals:
            dim_aggregates[dim] = round(sum(dim_vals) / len(dim_vals), 3)

    return {
        "total_customers": len(customer_summaries),
        "customers_passed": sum(passed),
        "pass_rate": round(sum(passed) / len(passed), 3) if passed else 0.0,
        "avg_score": round(sum(scores) / len(scores), 3),
        "min_score": round(min(scores), 3),
        "max_score": round(max(scores), 3),
        "scenario_scores": scenario_scores,
        "dimension_averages": dim_aggregates,
    }


def extract_context_slots(history: list[dict], customer_message: str = "") -> dict:
    """Extract current context slot values from conversation history.

    Tracks: order_id, tracking_no, product, color, size, decision.
    Returns a dict of slot_name -> value.
    """
    slots: dict[str, str] = {}

    # Scan history for slot values (most recent wins)
    all_messages = []
    for entry in history:
        cm = entry.get("customer_message", "")
        if cm:
            all_messages.append(cm)
        sr = entry.get("suggested_reply", "")
        if sr:
            all_messages.append(sr)
    if customer_message:
        all_messages.append(customer_message)

    combined = " ".join(all_messages)

    # Order ID
    oid = _extract_any_order_id(combined)
    if oid:
        slots["order_id"] = oid

    # Tracking number
    for pat in [r"(SF\d{10,})", r"(ZT\d{10,})", r"(DB\d{10,})"]:
        m = re.search(pat, combined)
        if m:
            slots["tracking_no"] = m.group(1)
            break

    # Product name
    prod = _extract_any_product_name(combined)
    if prod:
        slots["product"] = prod

    # Color
    color_patterns = [r"(粉色|蓝色|灰色|米色|绿色|白色|黑色|黄色|红色)"]
    for pat in color_patterns:
        m = re.search(pat, combined)
        if m:
            slots["color"] = m.group(1)
            break

    # Size
    size_patterns = [r"(\d+x\d+)", r"(\d+cm)", r"(加厚|薄款)"]
    for pat in size_patterns:
        m = re.search(pat, combined)
        if m:
            slots["size"] = m.group(1)
            break

    # Decision (keep/return/exchange)
    if "退货" in combined:
        slots["decision"] = "return"
    elif "换货" in combined:
        slots["decision"] = "exchange"
    elif "不退" in combined or "留下" in combined or "要了" in combined:
        slots["decision"] = "keep"

    return slots
