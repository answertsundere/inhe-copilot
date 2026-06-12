"""
quality_guard 节点 - 输出守卫检查
"""

import logging
import time

from app.services.output_guard import OutputGuard
from app.repositories.file_policy_repository import FilePolicyRepository

logger = logging.getLogger(__name__)

_output_guard = None


def _get_output_guard():
    global _output_guard
    if _output_guard is None:
        policy_repo = FilePolicyRepository()
        policy_repo.load()
        _output_guard = OutputGuard(policy_repo)
    return _output_guard


def quality_guard(state: dict) -> dict:
    """质量守卫"""
    t0 = time.time()
    reply = state.get("suggested_reply", "")
    guard = _get_output_guard()

    guard_warnings = list(state.get("guard_warnings", []))
    if reply:
        check = guard.check_reply(reply)
        guard_warnings.extend(check["warnings"])
        if not check["safe"]:
            sanitized, sw = guard.sanitize_reply(reply)
            reply = sanitized
            guard_warnings.extend(sw)

    # 高风险一致性
    risk = state.get("risk_level", "low")
    if risk == "high" and not state.get("requires_human_review"):
        state["requires_human_review"] = True
        guard_warnings.append("高风险消息已自动标记需要人工复核")

    logger.debug("quality_guard: check completed")
    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "quality_guard",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"守卫检查 {'通过' if not guard_warnings else '发现 ' + str(len(guard_warnings)) + ' 条警告'}",
    }
    return {
        "suggested_reply": reply,
        "guard_warnings": guard_warnings,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
