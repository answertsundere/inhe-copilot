"""
risk_check 节点 - 风险检测
"""

import time

from app.services.risk_service import RiskService
from app.repositories.file_policy_repository import FilePolicyRepository

# 延迟初始化以避免循环导入
_risk_service = None
_risk_service_init_ms = None


def _get_risk_service():
    global _risk_service, _risk_service_init_ms
    if _risk_service is None:
        t0 = time.time()
        policy_repo = FilePolicyRepository()
        policy_repo.load()
        _risk_service = RiskService(policy_repo)
        _risk_service_init_ms = int((time.time() - t0) * 1000)
    return _risk_service


def risk_check(state: dict) -> dict:
    """检测风险等级"""
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", ""))
    intent = state.get("intent", "")
    service = _get_risk_service()
    risk = service.detect_risk(msg)
    requires_human = service.should_require_human_review(msg, risk)

    # 签收未收到场景：至少 medium 风险
    if intent == "delivery_not_received":
        if risk == "low":
            risk = "medium"
        requires_human = True

    review_reason = ""
    short_circuit = False
    if requires_human:
        matched = service.get_matched_keywords(msg)
        if intent == "delivery_not_received":
            review_reason = "签收未收到场景，需人工跟进核实"
        elif matched.get("high"):
            review_reason = f"检测到高风险关键词: {', '.join(matched['high'][:3])}"
        else:
            review_reason = "检测到强制复核关键词"
        short_circuit = risk in ("high", "critical")

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "risk_check",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": _risk_service is not None and _risk_service_init_ms is not None,
        "summary": f"风险等级 {risk}, 需人工复核 {requires_human}",
    }
    if short_circuit:
        trace["risk_short_circuit"] = True

    return {
        "risk_level": risk,
        "requires_human_review": requires_human,
        "review_reason": review_reason,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
