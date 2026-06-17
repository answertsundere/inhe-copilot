"""
Post-generation Grounding Guard 节点

在回复生成后、Gold CSR 层之前执行。
检查最终回复中的事实是否被 evidence 支持。
如果失败，丢弃原回复并生成安全回退回复。
"""

import time
import logging

from app.services.grounding_validation_service import (
    validate_reply_grounding,
    _rewrite_fallback_reply,
)

logger = logging.getLogger(__name__)

POLICY_LOCKED_INTENTS = {
    "cleaning_care",
    "material_safety",
    "child_safety",
    "competitor_compare",
    "odor_question",
    "image_attachment",
}


def _filter_order_item_name_claims(state: dict, unsupported_claims: list[dict]) -> list[dict]:
    if state.get("intent") not in ("logistics_eta", "logistics_trace", "shipping", "logistics"):
        return unsupported_claims
    order = state.get("live_order") or state.get("order") or {}
    item_names = {
        str(item.get("name") or "").strip()
        for item in order.get("items", []) if isinstance(item, dict)
    }
    item_names = {name for name in item_names if name}
    if not item_names:
        return unsupported_claims
    filtered = []
    for claim in unsupported_claims:
        text = str(claim.get("claim") or "")
        if claim.get("fact_type") == "product_fact" and any(name in text for name in item_names):
            continue
        filtered.append(claim)
    return filtered


def post_generation_grounding_guard(state: dict) -> dict:
    """对生成的回复进行 post-generation grounding 校验。"""
    t0 = time.time()

    reply = state.get("suggested_reply", "") or ""
    if not reply:
        trace = {
            "node": "post_generation_grounding",
            "status": "skipped",
            "duration_ms": 0,
            "summary": "无回复，跳过 grounding 检查",
        }
        return {
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if state.get("intent") in POLICY_LOCKED_INTENTS and state.get("answer_mode") == "policy_grounded_answer":
        trace = {
            "node": "post_generation_grounding",
            "status": "skipped",
            "duration_ms": int((time.time() - t0) * 1000),
            "passed": True,
            "unsupported_claims_count": 0,
            "fallback_used": False,
            "fallback_mode": "",
            "summary": "policy_locked_skip",
        }
        return {
            "post_generation_grounding": {
                "checked": False,
                "passed": True,
                "unsupported_claims": [],
                "supported_claims": [],
                "fallback_used": False,
                "fallback_mode": "",
                "judge_mode": "policy_locked_skip",
            },
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if (
        state.get("generic_service_rule_used")
        or (state.get("evidence_debug") or {}).get("generic_service_rule_used")
        or any(
            isinstance(step, dict) and step.get("generic_service_rule_used")
            for step in state.get("trace_steps", [])
        )
    ):
        trace = {
            "node": "post_generation_grounding",
            "status": "skipped",
            "duration_ms": int((time.time() - t0) * 1000),
            "passed": True,
            "unsupported_claims_count": 0,
            "fallback_used": False,
            "fallback_mode": "",
            "summary": "generic_service_rule_skip",
        }
        return {
            "post_generation_grounding": {
                "checked": False,
                "passed": True,
                "unsupported_claims": [],
                "supported_claims": [],
                "fallback_used": False,
                "fallback_mode": "",
                "judge_mode": "generic_service_rule_skip",
            },
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    result = validate_reply_grounding(state)
    duration_ms = int((time.time() - t0) * 1000)

    new_reply = reply
    answer_mode = state.get("answer_mode", "")
    generation_mode = state.get("generation_mode", "")
    guard_warnings = list(state.get("guard_warnings", []))
    trace_steps = list(state.get("trace_steps", []))

    filtered_unsupported = _filter_order_item_name_claims(state, result["unsupported_claims"])
    if len(filtered_unsupported) != len(result["unsupported_claims"]):
        result = dict(result)
        result["unsupported_claims"] = filtered_unsupported
        result["passed"] = not filtered_unsupported
        result["fallback_used"] = bool(filtered_unsupported)
        if not filtered_unsupported:
            result["fallback_mode"] = ""

    if not result["passed"]:
        logger.warning(
            "Post-generation grounding failed: %s unsupported claims. "
            "Reply preview: %r. Evidence length: %s",
            len(result["unsupported_claims"]),
            reply[:200] if reply else "(empty)",
            result.get("evidence_text_length", 0),
        )
        for claim in result["unsupported_claims"]:
            logger.warning(
                "  unsupported claim: fact_type=%s, claim=%r, reason=%s",
                claim.get("fact_type"), claim.get("claim"), claim.get("reason"),
            )
            guard_warnings.append(
                f"grounding: unsupported {claim['fact_type']}: {claim['claim']} ({claim['reason']})"
            )

        # 回退到安全回复
        new_reply = _rewrite_fallback_reply(state, result["fallback_mode"])
        answer_mode = result["fallback_mode"] or "no_evidence_clarification"
        generation_mode = "grounding_fallback"

        trace_steps.append({
            "node": "post_generation_grounding_fallback",
            "status": "blocked",
            "unsupported_claims": [c["claim"] for c in result["unsupported_claims"]],
            "fallback_mode": result["fallback_mode"],
        })

    trace = {
        "node": "post_generation_grounding",
        "status": "passed" if result["passed"] else "blocked",
        "duration_ms": duration_ms,
        "passed": result["passed"],
        "unsupported_claims_count": len(result["unsupported_claims"]),
        "fallback_used": result["fallback_used"],
        "fallback_mode": result["fallback_mode"],
        "summary": (
            f"grounding passed" if result["passed"]
            else f"grounding blocked: {len(result['unsupported_claims'])} unsupported claims"
        ),
    }
    trace_steps.append(trace)

    return {
        "suggested_reply": new_reply,
        "answer_mode": answer_mode,
        "generation_mode": generation_mode,
        "guard_warnings": guard_warnings,
        "post_generation_grounding": {
            "checked": True,
            "passed": result["passed"],
            "unsupported_claims": result["unsupported_claims"],
            "supported_claims": result["supported_claims"],
            "fallback_used": result["fallback_used"],
            "fallback_mode": result["fallback_mode"],
            "judge_mode": result["judge_mode"],
        },
        "trace_steps": trace_steps,
    }
