"""
match_shipping_policy 节点 - 匹配物流政策
"""

import time

from app.agent.tools.knowledge_adapter import KnowledgeAdapter


def match_shipping_policy(state: dict) -> dict:
    """匹配物流时效政策"""
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", ""))
    product_name = state.get("matched_product_name", "")
    adapter = KnowledgeAdapter()
    try:
        from app.main import get_knowledge_repo, get_sop_repo, get_reply_template_repo
        adapter = KnowledgeAdapter(
            file_knowledge_repo=get_knowledge_repo(),
            sop_repo=get_sop_repo(),
            reply_template_repo=get_reply_template_repo(),
        )
    except Exception:
        pass

    policy = adapter.match_shipping_policy(msg, product_name)
    duration_ms = int((time.time() - t0) * 1000)

    trace = {
        "node": "match_shipping_policy",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"快递 {policy.get('default_courier') or '未指定'}, 时效 {policy.get('eta_days_min') or '-'}~{policy.get('eta_days_max') or '-'}天",
    }
    return {
        "shipping_policy": policy,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
