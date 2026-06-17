"""Evidence-based hallucination guard for grounded generation."""

from __future__ import annotations

import time

from app.agent.nodes.generate_reply import CLARIFICATION_REPLY, _best_faq_evidence, _render_exact_faq


HIGH_RISK_TERMS = [
    "实木", "原木", "松木", "橡胶木", "填充棉", "记忆棉", "海绵",
    "食品级", "BPA free", "无毒", "无味", "环保", "防水", "可水洗",
    "机洗", "承重", "适合几岁", "尺寸", "厚度", "高度", "宽度",
    "枕芯采用",
]

POLICY_LOCKED_INTENTS = {
    "cleaning_care",
    "material_safety",
    "child_safety",
    "competitor_compare",
    "odor_question",
    "image_attachment",
}


def hallucination_guard(state: dict) -> dict:
    """Block product facts that are not present in selected evidence."""
    t0 = time.time()
    if _has_generic_service_rule_used(state):
        trace = {
            "node": "hallucination_guard",
            "status": "success",
            "duration_ms": int((time.time() - t0) * 1000),
            "cache_hit": False,
            "passed": True,
            "unsupported_terms": [],
            "fallback_used": False,
            "summary": "generic_service_rule_skip",
        }
        return {
            "hallucination_guard": {
                "passed": True,
                "unsupported_terms": [],
                "fallback_used": False,
            },
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if state.get("intent") in POLICY_LOCKED_INTENTS and state.get("answer_mode") == "policy_grounded_answer":
        trace = {
            "node": "hallucination_guard",
            "status": "success",
            "duration_ms": int((time.time() - t0) * 1000),
            "cache_hit": False,
            "passed": True,
            "unsupported_terms": [],
            "fallback_used": False,
            "summary": "policy_locked_skip",
        }
        return {
            "hallucination_guard": {
                "passed": True,
                "unsupported_terms": [],
                "fallback_used": False,
            },
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    reply = state.get("suggested_reply", "") or ""
    evidence_text = _evidence_text(state)
    unsupported_terms = [
        term for term in HIGH_RISK_TERMS
        if term in reply and term not in evidence_text
    ]

    passed = not unsupported_terms
    fallback_used = False
    generation_mode = state.get("generation_mode", "rule_based")
    guard_warnings = list(state.get("guard_warnings", []))
    trace_steps = list(state.get("trace_steps", []))
    answer_mode = state.get("answer_mode", "")

    if unsupported_terms:
        _metrics_increment("hallucination_guard_block_count")
        fallback_used = True
        guard_warnings.append(f"hallucination_guard blocked unsupported terms: {', '.join(unsupported_terms)}")
        faq = _best_faq_evidence(state)
        if faq:
            reply = _render_exact_faq(faq, state.get("matched_product_name", ""))
            answer_mode = "exact_faq_answer"
        else:
            reply = CLARIFICATION_REPLY
            answer_mode = "no_evidence_clarification"
        generation_mode = "llm_fallback_blocked"
        trace_steps.append({
            "node": "hallucination_guard_fallback",
            "status": "blocked",
            "summary": f"unsupported_terms={unsupported_terms}",
        })

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "hallucination_guard",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "passed": passed,
        "unsupported_terms": unsupported_terms,
        "fallback_used": fallback_used,
        "summary": "passed" if passed else f"blocked {unsupported_terms}",
    }

    return {
        "suggested_reply": reply,
        "answer_mode": answer_mode,
        "generation_mode": generation_mode,
        "hallucination_guard": {
            "passed": passed,
            "unsupported_terms": unsupported_terms,
            "fallback_used": fallback_used,
        },
        "guard_warnings": guard_warnings,
        "trace_steps": trace_steps + [trace],
    }


def _evidence_text(state: dict) -> str:
    parts = []
    evidence = state.get("evidence", {})
    for bucket in (
        "product_facts", "faq_evidence", "policy_facts", "logistics_facts",
        "order_facts", "sop_evidence", "template_evidence",
    ):
        for item in evidence.get(bucket, []):
            parts.append(str(item.get("fact") or item.get("chunk_text") or item.get("content") or ""))
    for item in state.get("filtered_evidence", []) + state.get("knowledge_evidence", []):
        parts.append(str(item.get("chunk_text") or item.get("fact") or item.get("content") or ""))
    for item in state.get("knowledge", []):
        parts.append(str(item.get("content") or ""))
    return "\n".join(parts)


def _has_generic_service_rule_used(state: dict) -> bool:
    if state.get("generic_service_rule_used"):
        return True
    if (state.get("evidence_debug") or {}).get("generic_service_rule_used"):
        return True
    return any(
        isinstance(step, dict) and step.get("generic_service_rule_used")
        for step in state.get("trace_steps", [])
    )


def _metrics_increment(key: str) -> None:
    try:
        from app.services.metrics_service import get_metrics_service
        get_metrics_service().increment(key)
    except Exception:
        pass
