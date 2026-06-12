"""
rag_judge_node - RAG Judge 节点

在 evidence_filter 之后、evidence_builder 之前执行。
对过滤后的证据进行确定性检查。
如果 Judge 拒绝：丢弃证据，设置 no_evidence_clarification 模式。
"""

import time
import logging

logger = logging.getLogger(__name__)


def _candidate_texts(candidate) -> list[str]:
    if isinstance(candidate, str):
        return [candidate.strip()] if candidate.strip() else []
    if not isinstance(candidate, dict):
        return []
    texts = []
    for key in ("matched_product_name", "value", "name", "product_name", "title"):
        val = str(candidate.get(key) or "").strip()
        if val and val not in texts:
            texts.append(val)
    return texts


def _resolved_product_name(state: dict) -> str:
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots") or {}
    for val in (
        state.get("matched_product_name", ""),
        identity.get("matched_product_name", ""),
        slots.get("product_name", ""),
    ):
        val = str(val or "").strip()
        if val:
            return val
    for candidate in state.get("product_candidates", []) or []:
        texts = _candidate_texts(candidate)
        if texts:
            return texts[0]
    return ""


def rag_judge_node(state: dict) -> dict:
    """对过滤后的证据进行 RAG Judge 检查。"""
    t0 = time.time()

    knowledge_evidence = state.get("knowledge_evidence", [])
    filtered_evidence = state.get("filtered_evidence", [])

    # 如果没有证据，不需要 Judge
    if not knowledge_evidence:
        trace = {
            "node": "rag_judge",
            "status": "skipped",
            "duration_ms": 0,
            "summary": "无证据，跳过 RAG Judge",
        }
        return {
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    resolved_product = _resolved_product_name(state)
    slots = state.get("slots", {})
    identity = state.get("order_product_identity") or {}
    resolved_sku = slots.get("sku_code", "") or slots.get("sku_name", "") or identity.get("sku_id", "")
    expected_fact_type = state.get("intent", "")

    from app.services.rag_judge_service import judge_evidence, INTENT_TO_ALLOWED_FACT_TYPES
    allowed_fact_types = INTENT_TO_ALLOWED_FACT_TYPES.get(expected_fact_type)
    judge_result = judge_evidence(
        query=state.get("normalized_message", state.get("customer_message", "")),
        resolved_product=resolved_product,
        resolved_sku=resolved_sku,
        expected_fact_type=expected_fact_type,
        retrieved_chunks=state.get("retrieved_chunks", []),
        used_evidence=knowledge_evidence,
        final_reply="",  # 回复还未生成
    )

    duration_ms = int((time.time() - t0) * 1000)

    trace = {
        "node": "rag_judge",
        "status": "passed" if judge_result["passed"] else "rejected",
        "duration_ms": duration_ms,
        "judge_mode": judge_result["judge_mode"],
        "deterministic_passed": judge_result["deterministic_passed"],
        "wrong_product": judge_result["wrong_product_detected"],
        "wrong_sku": judge_result["wrong_sku_detected"],
        "wrong_fact_type": judge_result["wrong_fact_type_detected"],
        "unsupported_claims": judge_result["unsupported_claims"],
        "allowed_fact_types": list(allowed_fact_types) if allowed_fact_types else None,
        "evidence_entry_ids": [e.get("entry_id") for e in knowledge_evidence],
        "fallback_used": not judge_result["passed"],
        "summary": f"RAG Judge: {'passed' if judge_result['passed'] else 'rejected'}, "
                   f"reasons={judge_result['reasons']}",
    }

    result = {
        "rag_judge_result": judge_result,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }

    # 如果 Judge 拒绝，清空证据并设置降级模式
    if not judge_result["passed"]:
        logger.warning(
            "RAG Judge rejected: %s", judge_result["reasons"],
        )
        result["knowledge_evidence"] = []
        result["filtered_evidence"] = []
        result["answer_mode"] = "no_evidence_clarification"
        result["rag_judge_fallback"] = True

    return result
