"""
evidence_filter 节点 - 过滤 RAG 检索结果
"""

import time

from app.services.evidence_fact_gate_service import evaluate_evidence_item


# source_type 可信度映射
SOURCE_TYPE_CONFIDENCE = {
    "product_facts": "high",
    "product_mapping": "medium",
    "shipping_policy": "medium",
    "aftersales_policy": "medium",
    "installation_guide": "medium",
    "faq": "low",
    "response_templates": "low",
    "high_risk_sop": "high",
    "forbidden_rules": "high",
    "real_cases": "low",
    "feedback_records": "low",
}


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


def _resolved_product_names(state: dict) -> list[str]:
    names = []
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots") or {}
    for val in (
        state.get("matched_product_name", ""),
        identity.get("matched_product_name", ""),
        slots.get("product_name", ""),
    ):
        val = str(val or "").strip()
        if val and val not in names:
            names.append(val)
    for candidate in state.get("product_candidates", []) or []:
        for text in _candidate_texts(candidate):
            if text and text not in names:
                names.append(text)
    return names


def _scope_matches_any(chunk_products: list, product_names: list[str]) -> bool:
    if not chunk_products or not product_names:
        return True
    return any(name in cp or cp in name for cp in chunk_products for name in product_names)


def _is_compare_query(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u57fa\u7840\u6b3e",
        "\u5347\u7ea7\u6b3e",
        "\u5347\u7ea7\u7248",
        "\u5dee\u4ec0\u4e48",
        "\u5dee\u522b",
        "\u5dee\u5f02",
        "\u533a\u522b",
        "\u5bf9\u6bd4",
        "\u54ea\u4e2a\u597d",
    ))


def _has_compare_evidence(text: str) -> bool:
    text = text or ""
    explicit_markers = (
        "\u57fa\u7840\u6b3e",
        "\u5347\u7ea7\u6b3e",
        "\u5347\u7ea7\u7248",
        "\u8c6a\u534e\u6b3e",
        "\u5dee\u522b",
        "\u5dee\u5f02",
        "\u533a\u522b",
        "\u5bf9\u6bd4",
        "\u6b3e\u5f0f",
    )
    if any(word in text for word in explicit_markers):
        return True
    return (
        ("\u4fbf\u5b9c" in text and "\u8d35" in text)
        or ("\u504f\u8584" in text and "\u52a0\u539a" in text)
    )


def evidence_filter_node(state: dict) -> dict:
    """过滤检索结果，输出可信证据"""
    t0 = time.time()
    chunks = state.get("retrieved_chunks", [])
    intent = state.get("intent", "general")
    allowed_source_types = state.get("allowed_source_types", [])
    sku_code = state.get("slots", {}).get("sku_code", "")
    query = state.get("normalized_message") or state.get("customer_message", "")
    query_fact_type = state.get("query_fact_type", "")
    resolved_product_names = _resolved_product_names(state)
    from app.services.fact_type_service import (
        fact_type_matches,
        infer_evidence_fact_type,
        is_strict_fact_type,
    )

    filtered = []
    rejected = []

    for chunk in chunks:
        reject_reasons = []

        # 1. source_type 不在允许列表
        if allowed_source_types and chunk.get("source_type") not in allowed_source_types:
            reject_reasons.append("source_type_not_allowed")

        # 2. intent 不一致（chunk.intent 为 general 时跳过）
        chunk_intent = chunk.get("intent", "general")
        # intent 兼容映射（支持英文 + 中文）
        compatible_intents = {
            "product_consult": {"product_question", "general", "产品咨询"},
            "product_question": {"product_consult", "general", "产品咨询"},
            "installation": {"general", "安装指南"},
            "logistics_eta": {"general", "shipping", "logistics", "物流发货"},
            "aftersales": {"general", "售后处理"},
        }
        allowed_intents = compatible_intents.get(intent, {intent, "general"})
        allowed_intents.add(intent)  # 总是允许自身
        allowed_intents.add("general")
        # 中文 intent 通用兼容：product 场景允许商品咨询，installation 允许安装指南等
        if intent in ("product_question", "product_consult"):
            allowed_intents.update({"产品咨询", "product_question", "product_consult"})
        if intent == "installation":
            allowed_intents.update({"安装指南", "installation"})
        if intent in ("logistics_eta", "shipping", "logistics"):
            allowed_intents.update({"物流发货", "logistics_eta", "shipping", "logistics"})
        if chunk_intent and chunk_intent != "general" and chunk_intent not in allowed_intents:
            reject_reasons.append("intent_mismatch")

        # 3. SKU 不匹配（从 chunk 顶层字段读取，metadata 中不存储 scope）
        chunk_skus = chunk.get("sku_scope", [])
        if chunk_skus and sku_code and sku_code not in chunk_skus:
            reject_reasons.append("sku_mismatch")

        # 3b. 商品范围不匹配：chunk 有明确 product_scope 但与当前查询商品无关
        chunk_products = chunk.get("product_scope", [])
        if chunk_products and resolved_product_names:
            if not _scope_matches_any(chunk_products, resolved_product_names):
                reject_reasons.append("product_scope_mismatch")

        # 4. auto_reply_allowed=false 标记为 reference_only
        chunk_meta = chunk.get("metadata", {})
        auto_reply = chunk_meta.get("auto_reply_allowed", True)
        human_review = chunk_meta.get("human_review_required", False)

        if reject_reasons:
            rejected.append({"chunk": chunk, "reasons": reject_reasons})
            continue

        # 保留证据，标记可信度
        confidence = SOURCE_TYPE_CONFIDENCE.get(chunk.get("source_type"), "low")
        filtered.append({
            **chunk,
            "confidence": confidence,
            "reference_only": not auto_reply,
            "needs_human_review": human_review,
        })

    # 按分数排序
    filtered.sort(key=lambda x: -x.get("score", 0))

    # 构建 knowledge_evidence（传递 entry_status 供 fact_review 判断）
    knowledge_evidence = []
    for f in filtered:
        # 判断 scope 是否匹配
        scope_match = True
        mismatch_reason = ""
        chunk_skus = f.get("sku_scope", [])
        if chunk_skus and sku_code:
            if sku_code not in chunk_skus:
                scope_match = False
                mismatch_reason = "sku_mismatch"

        chunk_products = f.get("product_scope", [])
        if scope_match and chunk_products and resolved_product_names:
            if not _scope_matches_any(chunk_products, resolved_product_names):
                scope_match = False
                mismatch_reason = "product_scope_mismatch"

        source_confidence = SOURCE_TYPE_CONFIDENCE.get(f.get("source_type"), "low")
        rerank_score = f.get("rerank_score", f.get("score", 0))

        # 证据是否允许用于精确回答：分数达标 + scope 匹配
        evidence_threshold = 0.3
        evidence_allowed_for_exact_answer = (
            rerank_score >= evidence_threshold and scope_match
        )
        if (
            evidence_allowed_for_exact_answer
            and _is_compare_query(query)
            and f.get("source_type") == "faq"
            and not _has_compare_evidence(" ".join([
                f.get("title", ""),
                f.get("chunk_text", ""),
                f.get("category", ""),
                f.get("category_l3", ""),
            ]))
        ):
            evidence_allowed_for_exact_answer = False
            mismatch_reason = mismatch_reason or "compare_evidence_mismatch"

        evidence_fact_type = infer_evidence_fact_type(f)
        f["query_fact_type"] = query_fact_type
        f["evidence_fact_type"] = evidence_fact_type
        if query_fact_type and not fact_type_matches(query_fact_type, evidence_fact_type):
            evidence_allowed_for_exact_answer = False
            f["evidence_allowed_for_direct_answer"] = False
            mismatch_reason = mismatch_reason or "wrong_fact_type"
            if is_strict_fact_type(query_fact_type):
                f["reference_only"] = True

        f["evidence_allowed_for_exact_answer"] = evidence_allowed_for_exact_answer
        if f.get("source_type") == "faq" and not evidence_allowed_for_exact_answer:
            f["evidence_allowed_for_direct_answer"] = False

        gate = evaluate_evidence_item(
            {
                **f,
                "scope_match": scope_match,
                "source_confidence": source_confidence,
                "query_fact_type": query_fact_type,
                "evidence_fact_type": evidence_fact_type,
                "rerank_score": rerank_score,
                "mismatch_reason": mismatch_reason,
                "evidence_allowed_for_exact_answer": evidence_allowed_for_exact_answer,
            },
            state,
        )
        f.update(gate)
        evidence_allowed_for_exact_answer = gate["evidence_allowed_for_exact_answer"]

        knowledge_evidence.append({
            "chunk_id": f.get("chunk_id", ""),
            "entry_id": f.get("entry_id", ""),
            "title": f.get("title", ""),
            "source_type": f["source_type"],
            "chunk_text": f["chunk_text"],
            "score": f.get("score", 0),
            "metadata": f.get("metadata", {}),
            "product_scope": f.get("product_scope", []),
            "sku_scope": f.get("sku_scope", []),
            "index_status": f.get("index_status", "unknown"),
            "fact_review_status": f.get("fact_review_status", ""),
            "confidence": f["confidence"],
            "reference_only": f["reference_only"],
            "needs_human_review": f["needs_human_review"],
            "evidence_allowed_for_direct_answer": f.get("evidence_allowed_for_direct_answer", True),
            "entry_status": f.get("entry_status", "unknown"),
            "entry_risk_level": f.get("entry_risk_level", "low"),
            "source_sheet": f.get("source_sheet", ""),
            "row_number": f.get("row_number", 0),
            "scope_match": scope_match,
            "source_confidence": source_confidence,
            "query_fact_type": query_fact_type,
            "evidence_fact_type": evidence_fact_type,
            "rerank_score": rerank_score,
            "mismatch_reason": mismatch_reason,
            "gate_status": f.get("gate_status", ""),
            "gate_reasons": f.get("gate_reasons", []),
            "direct_answer_allowed": f.get("direct_answer_allowed", False),
            "requires_human_review": f.get("requires_human_review", f.get("needs_human_review", False)),
            "evidence_allowed_for_exact_answer": evidence_allowed_for_exact_answer,
        })

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "evidence_filter",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"过滤: 通过{len(filtered)}条, 拒绝{len(rejected)}条",
    }

    return {
        "filtered_evidence": filtered,
        "knowledge_evidence": knowledge_evidence,
        "rejected_evidence": rejected,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
