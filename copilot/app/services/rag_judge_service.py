"""
RAG Judge - 判断检索和回答是否被证据支持

RAG Judge 只判断"检索和回答是否被证据支持"，不能决定商品事实真假。

第一层：确定性规则（必须通过）
第二层：可选 LLM Judge（语义相关性、完整性、忠实度）
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# source_type 到事实类型的映射
_POLICY_SOURCE_TYPES = {"shipping_policy", "aftersales_policy", "installation_guide"}
_PRODUCT_SOURCE_TYPES = {"product_facts", "faq", "product_mapping"}

# intent 到允许的 fact_type(source_type) 映射
INTENT_TO_ALLOWED_FACT_TYPES = {
    "product_question": {"faq", "product_facts", "product_mapping"},
    "product_consult": {"faq", "product_facts", "product_mapping"},
    "logistics_eta": {"logistics_fact", "shipping_policy"},
    "logistics_trace": {"logistics_fact", "shipping_policy"},
    "shipping": {"logistics_fact", "shipping_policy"},
    "logistics": {"logistics_fact", "shipping_policy"},
    "aftersales": {"aftersales_policy", "sop", "high_risk_sop"},
    "refund": {"aftersales_policy", "sop", "high_risk_sop"},
    "complaint": {"complaint_sop", "aftersales_policy", "sop", "high_risk_sop"},
    "installation": {"installation_guide", "faq"},
    "delivery_not_received": {"logistics_fact", "shipping_policy", "sop"},
}

# 中文数字前缀匹配
_NUMBER_PREFIX_RE = re.compile(r"[一二三四五六七八九十百千]+号")


def judge_evidence(
    query: str,
    conversation_context: str = "",
    resolved_product: str = "",
    resolved_sku: str = "",
    expected_fact_type: str = "",
    retrieved_chunks: list = None,
    rejected_chunks: list = None,
    used_evidence: list = None,
    final_reply: str = "",
) -> dict:
    """对检索结果和最终回复进行评判。

    Returns:
        {
            "passed": bool,
            "deterministic_passed": bool,
            "query_product_match": bool,
            "query_sku_match": bool,
            "fact_type_match": bool,
            "scope_match": bool,
            "status_match": bool,
            "evidence_supports_reply": bool,
            "wrong_product_detected": bool,
            "wrong_sku_detected": bool,
            "wrong_fact_type_detected": bool,
            "conflicting_evidence_detected": bool,
            "unsupported_claims": [str],
            "confidence": float,
            "reasons": [str],
            "judge_mode": str,
            "duration_ms": int,
        }
    """
    t0 = time.time()
    retrieved_chunks = retrieved_chunks or []
    rejected_chunks = rejected_chunks or []
    used_evidence = used_evidence or []

    # 如果没有使用任何证据，不做评判（无证据降级由上游处理）
    if not used_evidence:
        return _empty_result("no_evidence", t0)

    # ---- 第一层：确定性规则 ----
    det = _deterministic_judge(
        query=query,
        resolved_product=resolved_product,
        resolved_sku=resolved_sku,
        expected_fact_type=expected_fact_type,
        evidence=used_evidence,
        final_reply=final_reply,
    )

    # ---- 第二层：可选 LLM Judge ----
    from app.config import _env_bool
    llm_judge_enabled = _env_bool("COPILOT_RAG_LLM_JUDGE_ENABLED", False)
    llm_result = None

    if llm_judge_enabled:
        try:
            llm_result = _llm_judge(
                query=query,
                evidence=used_evidence,
                final_reply=final_reply,
            )
        except Exception as e:
            logger.warning("LLM Judge failed: %s", e)

    # 综合判断
    judge_mode = "deterministic"
    if llm_result:
        judge_mode = "deterministic+llm"

    # 确定性拒绝不能被 LLM 覆盖
    passed = det["deterministic_passed"]
    if passed and llm_result and not llm_result.get("passed", True):
        passed = False
        det["reasons"].append("llm_judge_rejected")

    duration_ms = int((time.time() - t0) * 1000)

    return {
        "passed": passed,
        "deterministic_passed": det["deterministic_passed"],
        "query_product_match": det["query_product_match"],
        "query_sku_match": det["query_sku_match"],
        "fact_type_match": det["fact_type_match"],
        "scope_match": det["scope_match"],
        "status_match": det["status_match"],
        "evidence_supports_reply": det["evidence_supports_reply"],
        "wrong_product_detected": det["wrong_product_detected"],
        "wrong_sku_detected": det["wrong_sku_detected"],
        "wrong_fact_type_detected": det["wrong_fact_type_detected"],
        "conflicting_evidence_detected": det["conflicting_evidence_detected"],
        "unsupported_claims": det["unsupported_claims"],
        "confidence": det["confidence"],
        "reasons": det["reasons"],
        "judge_mode": judge_mode,
        "duration_ms": duration_ms,
    }


def _deterministic_judge(
    query: str,
    resolved_product: str,
    resolved_sku: str,
    expected_fact_type: str,
    evidence: list,
    final_reply: str,
) -> dict:
    """确定性规则评判。"""
    reasons = []
    all_passed = True

    query_product_match = True
    query_sku_match = True
    fact_type_match = True
    scope_match = True
    status_match = True
    evidence_supports_reply = True
    wrong_product_detected = False
    wrong_sku_detected = False
    wrong_fact_type_detected = False
    conflicting_evidence_detected = False
    unsupported_claims = []
    confidence = 1.0

    # 收集证据中的产品和 SKU
    evidence_products = set()
    evidence_skus = set()
    evidence_source_types = set()
    evidence_statuses = set()

    for ev in evidence:
        ev_product = ev.get("product_scope", [])
        ev_sku = ev.get("sku_scope", [])
        ev_source = ev.get("source_type", "")
        ev_status = ev.get("entry_status", "unknown")

        if isinstance(ev_product, list):
            evidence_products.update(ev_product)
        if isinstance(ev_sku, list):
            evidence_skus.update(ev_sku)
        if ev_source:
            evidence_source_types.add(ev_source)
        evidence_statuses.add(ev_status)

    # 规则 1：used evidence 必须 status=published
    non_published = [s for s in evidence_statuses if s != "published"]
    if non_published:
        all_passed = False
        status_match = False
        reasons.append(f"非 published 证据: {non_published}")

    # 规则 2：used evidence 必须 index_status=ready（从 metadata 获取）
    for ev in evidence:
        ev_index = ev.get("index_status", "")
        if ev_index and ev_index != "ready":
            all_passed = False
            reasons.append(f"证据 index_status={ev_index}")
            confidence *= 0.5

    # 规则 3：product_scope 必须匹配
    if resolved_product and evidence_products:
        match = _check_product_match(resolved_product, list(evidence_products))
        if not match:
            wrong_product_detected = True
            all_passed = False
            query_product_match = False
            reasons.append(f"商品不匹配: 查询={resolved_product}, 证据={evidence_products}")

    # 规则 4：sku_scope 如果存在必须匹配
    if resolved_sku and evidence_skus:
        if resolved_sku not in evidence_skus:
            wrong_sku_detected = True
            all_passed = False
            query_sku_match = False
            reasons.append(f"SKU 不匹配: 查询={resolved_sku}, 证据={evidence_skus}")

    # 规则 5：fact_type 必须匹配（使用 INTENT_TO_ALLOWED_FACT_TYPES 映射）
    if expected_fact_type and evidence_source_types:
        allowed_types = INTENT_TO_ALLOWED_FACT_TYPES.get(expected_fact_type)
        if allowed_types is not None:
            # intent 在映射中：检查 evidence source_type 是否都被允许
            rejected = evidence_source_types - allowed_types
            if rejected:
                wrong_fact_type_detected = True
                all_passed = False
                fact_type_match = False
                reasons.append(f"intent={expected_fact_type} 不允许的证据类型: {rejected}")
        else:
            # intent 不在映射中：保持旧行为（兼容未知 intent）
            if expected_fact_type == "product_facts":
                policy_overlap = evidence_source_types & _POLICY_SOURCE_TYPES
                if policy_overlap:
                    wrong_fact_type_detected = True
                    all_passed = False
                    fact_type_match = False
                    reasons.append(f"商品事实使用了政策类型证据: {policy_overlap}")

    # 规则 6：不同编号款式默认冲突
    if resolved_product and evidence_products:
        query_nums = _extract_number_prefixes(resolved_product)
        for ep in evidence_products:
            ep_nums = _extract_number_prefixes(ep)
            if query_nums and ep_nums and not (query_nums & ep_nums):
                conflicting_evidence_detected = True
                all_passed = False
                scope_match = False
                reasons.append(f"编号冲突: 查询={query_nums}, 证据={ep_nums}")

    # 规则 7：回复中的事实必须存在于 evidence
    if final_reply:
        unsupported = _check_reply_grounding(final_reply, evidence, resolved_product)
        if unsupported:
            evidence_supports_reply = False
            unsupported_claims = unsupported
            reasons.append(f"回复包含未支撑声明: {unsupported}")
            confidence *= 0.8

    # 规则 8：conflicting evidence 不能直接回答
    if conflicting_evidence_detected:
        all_passed = False
        confidence *= 0.5

    return {
        "deterministic_passed": all_passed,
        "query_product_match": query_product_match,
        "query_sku_match": query_sku_match,
        "fact_type_match": fact_type_match,
        "scope_match": scope_match,
        "status_match": status_match,
        "evidence_supports_reply": evidence_supports_reply,
        "wrong_product_detected": wrong_product_detected,
        "wrong_sku_detected": wrong_sku_detected,
        "wrong_fact_type_detected": wrong_fact_type_detected,
        "conflicting_evidence_detected": conflicting_evidence_detected,
        "unsupported_claims": unsupported_claims,
        "confidence": round(max(0.0, confidence), 4),
        "reasons": reasons,
    }


def _check_product_match(query_product: str, evidence_products: list) -> bool:
    """检查查询商品与证据商品是否匹配。"""
    for ep in evidence_products:
        if query_product in ep or ep in query_product:
            return True
    return False


def _extract_number_prefixes(text: str) -> set:
    """提取中文数字前缀。"""
    return set(_NUMBER_PREFIX_RE.findall(text))


def _check_reply_grounding(reply: str, evidence: list, resolved_product: str) -> list:
    """检查回复中的关键声明是否有证据支撑。"""
    unsupported = []

    # 检查回复中是否引用了与查询商品不同的商品
    reply_numbers = _extract_number_prefixes(reply)
    query_numbers = _extract_number_prefixes(resolved_product) if resolved_product else set()

    # 如果回复提到了具体编号但与查询不同
    if reply_numbers and query_numbers and not (reply_numbers & query_numbers):
        for rn in reply_numbers:
            if rn not in query_numbers:
                unsupported.append(f"回复提及 {rn} 但查询是 {query_numbers}")

    return unsupported


def _llm_judge(query: str, evidence: list, final_reply: str) -> dict:
    """可选的 LLM Judge。不能覆盖确定性拒绝。"""
    try:
        from app.llm.client import get_llm_client
        client = get_llm_client()
    except Exception:
        return {"passed": True, "reason": "llm_unavailable"}

    evidence_text = "\n".join([
        f"[{e.get('source_type', '')}] {e.get('chunk_text', '')[:200]}"
        for e in evidence[:5]
    ])

    prompt = f"""你是 RAG 质量评审。判断以下回复是否忠实于提供的证据。

查询: {query}

证据:
{evidence_text}

回复:
{final_reply[:500]}

请判断:
1. 回复是否完全基于证据？（是/否）
2. 回复是否引入了证据中没有的事实？（是/否）
3. 回复是否歪曲了证据的含义？（是/否）

回答 JSON: {{"passed": true/false, "reason": "..."}}"""

    try:
        import json
        response = client.chat(prompt, temperature=0.0)
        result = json.loads(response.strip())
        return result
    except Exception as e:
        logger.warning("LLM Judge parse failed: %s", e)
        return {"passed": True, "reason": f"parse_error: {e}"}


def _empty_result(judge_mode: str, t0: float) -> dict:
    return {
        "passed": True,
        "deterministic_passed": True,
        "query_product_match": True,
        "query_sku_match": True,
        "fact_type_match": True,
        "scope_match": True,
        "status_match": True,
        "evidence_supports_reply": True,
        "wrong_product_detected": False,
        "wrong_sku_detected": False,
        "wrong_fact_type_detected": False,
        "conflicting_evidence_detected": False,
        "unsupported_claims": [],
        "confidence": 0.0,
        "reasons": [],
        "judge_mode": judge_mode,
        "duration_ms": int((time.time() - t0) * 1000),
    }
