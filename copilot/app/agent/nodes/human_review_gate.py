"""
human_review_gate 节点 - 人工复核门
第一阶段不真正 interrupt，只设置标记和 review_reason。
"""

import time


def human_review_gate(state: dict) -> dict:
    """人工复核门"""
    t0 = time.time()
    requires_human = state.get("requires_human_review", False)
    review_reason = state.get("review_reason", "")

    if requires_human and not review_reason:
        review_reason = "风险检测或业务规则触发人工复核"

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "human_review_gate",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"人工复核 {'需要' if requires_human else '不需要'}" + (f", 原因: {review_reason}" if requires_human else ""),
    }
    return {
        "requires_human_review": requires_human,
        "review_reason": review_reason,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
