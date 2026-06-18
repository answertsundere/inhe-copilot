"""
Post-generation Grounding Validation Service

校验最终回复中的事实是否被 evidence 支持。
只使用确定性规则，不依赖 LLM Judge。

核心能力：
1. 关键词匹配（商品事实、物流状态、售后承诺）
2. 否定关系校验（证据"不防水"→回复不能"防水"）
3. 数值+单位一致性（证据"10kg"→回复不能"100kg"）
4. 无证据时严格拦截具体事实声明
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ========== 商品事实关键词 ==========
_PRODUCT_FACT_TERMS = {
    "实木", "原木", "松木", "橡木", "榉木", "橡胶木", "板材", "密度板", "颗粒板",
    "填充棉", "记忆棉", "乳胶", "海绵", "PP", "ABS", "塑料", "布艺", "金属",
    "材质", "填充物", "填充",
    "厘米", "cm", "kg", "公斤", "承重", "尺寸", "长", "宽", "高", "厚度",
    "防水", "食品级", "无毒", "无味", "环保",
    "可水洗", "机洗", "手洗", "干洗",
    "枕芯采用", "适合几岁", "适用年龄",
}

# ========== 物流状态关键词 ==========
# 具体状态声明（需要证据支撑）
_LOGISTICS_STATUS_TERMS = {
    "已发货", "已发出", "已签收", "已送达", "已到达",
    "已揽收", "已揽件", "运输中", "派送中",
}

# 一般性物流解释词汇（不需要具体订单证据支撑）
_LOGISTICS_GENERAL_TERMS = {
    "中转", "派送", "派件", "揽收", "正在配送",
}

# ========== 售后承诺关键词 ==========
_AFTERSALES_PROMISE_TERMS = {
    "已退款", "已赔偿", "已补发", "已处理完毕",
    "退款", "赔偿", "补发", "赔付", "退钱",
    "一定赔", "一定退", "一定补发",
    "保证赔", "保证退", "保证补发",
}

# ========== 否定词 ==========
_NEGATION_PREFIXES = {"不", "非", "无", "未", "没", "没有"}

# ========== 数值+单位正则 ==========
_NUMBER_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([a-zA-Z%°℃℉]+|厘米|cm|千克|kg|公斤|克|g|米|m|厘米|cm|毫米|mm|升|L|毫升|ml|寸|英寸|磅|斤|两)"
)

# ========== intent 到允许的事实类型映射 ==========
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


def _collect_evidence_text(state: dict) -> str:
    """收集所有 evidence 文本用于 grounding 检查。"""
    parts = []
    evidence = state.get("evidence", {}) or {}
    for bucket in (
        "product_facts", "faq_evidence", "policy_facts",
        "logistics_facts", "order_facts", "sop_evidence", "template_evidence",
    ):
        for item in evidence.get(bucket, []):
            for key in ("fact", "chunk_text", "content", "title", "answer", "question"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    parts.append(val)
                    break

    # 也包含 filtered_evidence / knowledge_evidence 中的 chunk_text
    for item in state.get("filtered_evidence", []) + state.get("knowledge_evidence", []):
        text = item.get("chunk_text") or item.get("fact") or item.get("content") or ""
        if text:
            parts.append(text)

    return "\n".join(parts)


def _extract_claims(reply: str, terms: set) -> list[dict]:
    """从回复中提取包含指定术语的声明。"""
    claims = []
    for term in terms:
        if term in reply:
            # 提取包含该术语的上下文片段（前后各10字）
            for m in re.finditer(re.escape(term), reply):
                start = max(0, m.start() - 10)
                end = min(len(reply), m.end() + 10)
                context = reply[start:end]
                claims.append({"term": term, "context": context})
    return claims


def _extract_numbers_with_units(text: str) -> list[dict]:
    """提取文本中的数值+单位。"""
    results = []
    for m in _NUMBER_UNIT_RE.finditer(text):
        results.append({
            "value": float(m.group(1)),
            "unit": m.group(2).lower(),
            "raw": m.group(0),
            "span": (m.start(), m.end()),
        })
    return results


def _extract_negated_facts(text: str) -> list[dict]:
    """提取文本中的否定事实，如'不防水'、'非实木'。"""
    negated = []
    # 模式：不/非/无/未/没 + 关键词
    for prefix in _NEGATION_PREFIXES:
        pattern = prefix + r"([^，。！？\n]{1,8})"
        for m in re.finditer(pattern, text):
            negated.append({
                "prefix": prefix,
                "fact": m.group(1),
                "raw": m.group(0),
            })
    return negated


_NEGATION_PATTERN = re.compile(r"(不|不是|非|无|未|没|没有)")


def _has_negation_prefix(text: str, term: str) -> bool:
    """检查 text 中 term 的前面是否有否定前缀。"""
    for m in re.finditer(re.escape(term), text):
        start = max(0, m.start() - 5)
        prefix = text[start:m.start()]
        if _NEGATION_PATTERN.search(prefix):
            return True
    return False


def _check_negation_consistency(reply: str, evidence_text: str) -> list[dict]:
    """检查否定关系一致性。

    规则：
    - evidence 中有 "不X"，reply 中出现 "X"（无否定前缀）→ 矛盾
    - evidence 中有 "X"，reply 中出现 "不X" → 矛盾
    """
    unsupported = []

    # evidence 说 "不X"，reply 说 "X"
    # 提取 evidence 中的否定事实
    for prefix in _NEGATION_PREFIXES:
        pattern = prefix + r"([^，。！？\n]{1,8})"
        for m in re.finditer(pattern, evidence_text):
            negated_fact = m.group(1)
            # 如果 reply 中肯定了被否定的事实（且前面没有否定前缀）
            if negated_fact in reply and not _has_negation_prefix(reply, negated_fact):
                unsupported.append({
                    "claim": reply[max(0, reply.find(negated_fact)-5):min(len(reply), reply.find(negated_fact)+len(negated_fact)+5)],
                    "fact_type": "negation_conflict",
                    "reason": f"evidence否定'{m.group(0)}'，但reply肯定'{negated_fact}'",
                })

    # evidence 说 "X"，reply 说 "不X"
    # 提取 evidence 中的肯定事实（在 product_fact_terms 中的）
    for term in _PRODUCT_FACT_TERMS:
        if term in evidence_text and not _has_negation_prefix(evidence_text, term):
            # evidence 中是肯定的，检查 reply 中是否否定了它
            if _has_negation_prefix(reply, term):
                # 提取包含否定前缀的上下文
                for m in re.finditer(re.escape(term), reply):
                    start = max(0, m.start() - 5)
                    context = reply[start:m.start() + len(term)]
                    unsupported.append({
                        "claim": context,
                        "fact_type": "negation_conflict",
                        "reason": f"evidence肯定'{term}'，但reply否定该事实",
                    })

    return unsupported


def _check_number_consistency(reply: str, evidence_text: str) -> list[dict]:
    """检查数值+单位一致性。

    规则：
    - evidence 和 reply 中有相同单位的数值，但数值不同 → 矛盾
    - 允许 ±10% 的浮动（考虑近似值）
    """
    unsupported = []

    evidence_numbers = _extract_numbers_with_units(evidence_text)
    reply_numbers = _extract_numbers_with_units(reply)

    # 建立 evidence 中单位到数值的映射
    ev_by_unit = {}
    for en in evidence_numbers:
        ev_by_unit.setdefault(en["unit"], []).append(en["value"])

    for rn in reply_numbers:
        unit = rn["unit"]
        if unit not in ev_by_unit:
            # evidence 中没有这个单位的数值，但 reply 中有 → 未支撑
            unsupported.append({
                "claim": rn["raw"],
                "fact_type": "number_conflict",
                "reason": f"evidence中没有单位'{unit}'的数值，但reply出现'{rn['raw']}'",
            })
            continue

        # 检查数值是否在 evidence 允许范围内（±10%）
        ev_values = ev_by_unit[unit]
        matched = False
        for ev_val in ev_values:
            if ev_val == 0:
                if rn["value"] == 0:
                    matched = True
                    break
            else:
                tolerance = abs(ev_val) * 0.1
                if abs(rn["value"] - ev_val) <= tolerance:
                    matched = True
                    break

        if not matched:
            unsupported.append({
                "claim": rn["raw"],
                "fact_type": "number_conflict",
                "reason": f"evidence中单位'{unit}'的数值为{ev_values}，但reply为'{rn['raw']}'",
            })

    return unsupported


def _check_unsupported_facts_when_no_evidence(reply: str) -> list[dict]:
    """无证据时，检查回复中是否出现具体事实声明。"""
    unsupported = []

    # 检查商品事实
    product_claims = _extract_claims(reply, _PRODUCT_FACT_TERMS)
    for claim in product_claims:
        unsupported.append({
            "claim": claim["context"],
            "fact_type": "product_fact",
            "reason": "无证据支撑的商品事实声明",
        })

    # 检查物流状态（仅具体状态声明，排除一般性物流解释措辞）
    logistics_claims = _extract_claims(reply, _LOGISTICS_STATUS_TERMS)
    for claim in logistics_claims:
        unsupported.append({
            "claim": claim["context"],
            "fact_type": "logistics_fact",
            "reason": "无证据支撑的物流状态声明",
        })

    # 检查售后承诺
    aftersales_claims = _extract_claims(reply, _AFTERSALES_PROMISE_TERMS)
    for claim in aftersales_claims:
        if _is_aftersales_process_statement(claim["context"]):
            continue
        unsupported.append({
            "claim": claim["context"],
            "fact_type": "aftersales_promise",
            "reason": "无证据支撑的售后承诺声明",
        })

    # 检查数值声明
    reply_numbers = _extract_numbers_with_units(reply)
    for rn in reply_numbers:
        # 排除常见的非事实数值（如价格、数量）
        if rn["unit"] in {"cm", "kg", "公斤", "克", "g", "厘米", "毫米", "mm", "米", "m"}:
            unsupported.append({
                "claim": rn["raw"],
                "fact_type": "number_conflict",
                "reason": "无证据支撑的数值声明",
            })

    return unsupported


def _is_aftersales_process_statement(context: str) -> bool:
    text = context or ""
    hard_promises = (
        "\u5df2\u9000\u6b3e",
        "\u5df2\u7ecf\u9000\u6b3e",
        "\u4e00\u5b9a\u9000",
        "\u4e00\u5b9a\u8d54",
        "\u4e00\u5b9a\u8865\u53d1",
        "\u4fdd\u8bc1\u9000",
        "\u4fdd\u8bc1\u8d54",
        "\u4fdd\u8bc1\u8865\u53d1",
        "\u9a6c\u4e0a\u9000",
        "\u7acb\u5373\u9000",
        "\u76f4\u63a5\u9000\u6b3e",
        "\u8d54\u507f",
        "\u8d54\u4ed8",
        "\u8865\u53d1",
    )
    if any(term in text for term in hard_promises):
        return False

    process_terms = (
        "\u6838\u5bf9",
        "\u6838\u5b9e",
        "\u786e\u8ba4",
        "\u8ddf\u8fdb",
        "\u8bb0\u5f55",
        "\u67e5\u770b",
        "\u552e\u540e\u8bb0\u5f55",
        "\u9000\u6b3e\u95ee\u9898",
        "\u9000\u6b3e\u8fdb\u5ea6",
        "\u5904\u7406\u8def\u5f84",
        "\u5904\u7406\u65b9\u5411",
        "\u7a0d\u7b49",
    )
    return any(term in text for term in process_terms)


def _resolve_fallback_mode(intent: str, unsupported_claims: list) -> str:
    """根据失败的声明类型决定回退模式。"""
    fact_types = {c["fact_type"] for c in unsupported_claims}
    if "product_fact" in fact_types or "number_conflict" in fact_types:
        return "product_fact_answer"
    if "logistics_fact" in fact_types:
        return "no_evidence_clarification"
    if "aftersales_promise" in fact_types:
        return "human_review"
    if "negation_conflict" in fact_types:
        return "product_fact_answer"
    return "no_evidence_clarification"


def _rewrite_fallback_reply(state: dict, fallback_mode: str) -> str:
    """生成安全回退回复。"""
    from app.agent.state import has_order_identifier
    intent = state.get("intent", "")
    product_name = state.get("matched_product_name", "")
    slots = state.get("slots", {}) or {}
    has_order_id = has_order_identifier(state)

    if fallback_mode == "product_fact_answer":
        if has_order_id:
            return (
                "亲，关于商品详情，我已收到您的订单信息，正在核实具体参数。"
                "\n暂时无法确认该项属性，我会尽快为您查实。"
            )
        return (
            "亲，关于商品详情，我需要确认一下具体信息。"
            "\n麻烦您提供一下商品链接、截图或订单号，我帮您核实准确参数。"
        )

    if fallback_mode == "exact_faq_answer":
        faq = None
        for item in (state.get("evidence", {}) or {}).get("faq_evidence", []):
            faq = item
            break
        if faq:
            answer = faq.get("answer") or faq.get("chunk_text") or ""
            if answer:
                return answer

    if intent == "delivery_not_received":
        reply = (
            "亲，非常抱歉给您带来不便，我理解您没收到包裹会着急。"
            "\n显示签收但您没有收到的话，我会帮您一起核实派送和签收记录。"
            "\n您可以先看一下家人、门卫、前台、驿站、快递柜或门口附近是否代收/暂放。"
        )
        if has_order_id:
            reply += "\n我已收到当前订单/物流信息，会按现有号码继续核对。"
        else:
            reply += "\n麻烦您补充一下订单号或物流单号，我这边按号码帮您核实。"
        reply += "\n如果确认都没有收到，我这边会联系快递核实派送情况，并继续跟进处理。"
        return reply

    if intent in ("logistics_eta", "shipping", "logistics", "logistics_trace"):
        if has_order_id:
            id_type = slots.get("identifier_type", "")
            if id_type == "tracking_no":
                return (
                    "亲，我已收到您提供的物流单号，但暂未查询到对应的物流信息。"
                    "\n请核对单号是否正确，或提供订单截图，我帮您继续核实。"
                )
            return (
                "亲，我已收到您的订单号，但暂时没有查询到对应订单的详细物流信息。"
                "\n请核对一下订单号是否正确，或提供订单截图，我帮您进一步核实。"
            )
        return (
            "亲，物流时效受天气、路况等多种因素影响，我无法对具体到货时间给出准确判断。"
            "\n具体送达时间以实际更新为准。"
            "\n麻烦您提供一下订单号或物流单号，我帮您进一步核实。"
        )

    if intent in ("aftersales", "refund", "complaint"):
        if has_order_id:
            return (
                "亲，关于售后问题，我已收到您的订单信息，我们会尽快核实处理方案。"
                "\n请稍等，我会安排专人跟进。"
            )
        return (
            "亲，关于售后问题，我会尽快为您核实处理方案。"
            "\n麻烦您提供一下订单号和问题描述，我们会安排专人跟进。"
        )

    if has_order_id:
        return (
            "亲，关于您的问题，我已收到您的订单信息，正在进一步核实中。"
            "\n请稍等，我会尽快为您确认。"
        )

    return (
        "亲，关于您的问题，我需要进一步核实。"
        "\n麻烦您提供更多详细信息，我会尽快为您确认。"
    )


def validate_reply_grounding(state: dict) -> dict:
    """
    对最终回复进行 post-generation grounding 校验。

    Returns:
        {
            "passed": bool,
            "checked": True,
            "unsupported_claims": [...],
            "supported_claims": [...],
            "fallback_used": bool,
            "fallback_mode": str | None,
            "judge_mode": "deterministic",
            "evidence_text_length": int,
        }
    """
    reply = state.get("suggested_reply", "") or ""
    if not reply:
        return {
            "passed": True,
            "checked": True,
            "unsupported_claims": [],
            "supported_claims": [],
            "fallback_used": False,
            "fallback_mode": None,
            "judge_mode": "deterministic",
            "evidence_text_length": 0,
        }

    evidence_text = _collect_evidence_text(state)
    intent = state.get("intent", "")
    allowed_source_types = INTENT_TO_ALLOWED_FACT_TYPES.get(intent, set())

    unsupported_claims = []
    supported_claims = []

    if not evidence_text:
        # 无证据时：严格拦截任何具体事实声明
        unsupported_claims = _check_unsupported_facts_when_no_evidence(reply)
    else:
        # 有证据时：检查一致性
        # 1. 商品事实 grounding
        product_claims = _extract_claims(reply, _PRODUCT_FACT_TERMS)
        for claim in product_claims:
            if claim["term"] in evidence_text:
                supported_claims.append({"claim": claim["context"], "fact_type": "product_fact"})
            else:
                unsupported_claims.append({
                    "claim": claim["context"],
                    "fact_type": "product_fact",
                    "reason": "not_found_in_evidence",
                })

        # 2. 物流状态 grounding
        logistics_claims = _extract_claims(reply, _LOGISTICS_STATUS_TERMS)
        for claim in logistics_claims:
            if claim["term"] in evidence_text:
                supported_claims.append({"claim": claim["context"], "fact_type": "logistics_fact"})
            else:
                unsupported_claims.append({
                    "claim": claim["context"],
                    "fact_type": "logistics_fact",
                    "reason": "not_found_in_evidence",
                })

        # 3. 售后承诺 grounding
        aftersales_claims = _extract_claims(reply, _AFTERSALES_PROMISE_TERMS)
        for claim in aftersales_claims:
            if _is_aftersales_process_statement(claim["context"]):
                continue
            if claim["term"] in evidence_text:
                supported_claims.append({"claim": claim["context"], "fact_type": "aftersales_promise"})
            else:
                unsupported_claims.append({
                    "claim": claim["context"],
                    "fact_type": "aftersales_promise",
                    "reason": "not_found_in_evidence",
                })

        # 4. 否定关系一致性
        negation_conflicts = _check_negation_consistency(reply, evidence_text)
        unsupported_claims.extend(negation_conflicts)

        # 5. 数值+单位一致性
        number_conflicts = _check_number_consistency(reply, evidence_text)
        unsupported_claims.extend(number_conflicts)

    passed = len(unsupported_claims) == 0
    fallback_mode = None
    fallback_used = False

    if not passed:
        fallback_mode = _resolve_fallback_mode(intent, unsupported_claims)
        fallback_used = True

    return {
        "passed": passed,
        "checked": True,
        "unsupported_claims": unsupported_claims,
        "supported_claims": supported_claims,
        "fallback_used": fallback_used,
        "fallback_mode": fallback_mode,
        "judge_mode": "deterministic",
        "evidence_text_length": len(evidence_text),
    }


def get_grounding_result_for_debug(state: dict) -> dict:
    """供 execution_debug 使用的简化结果。"""
    result = validate_reply_grounding(state)
    return {
        "checked": result["checked"],
        "passed": result["passed"],
        "unsupported_claims": result["unsupported_claims"],
        "fallback_used": result["fallback_used"],
        "fallback_mode": result["fallback_mode"],
        "judge_mode": result["judge_mode"],
    }
