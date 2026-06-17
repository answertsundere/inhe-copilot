"""Final semantic consistency audit for customer-facing replies.

This is the outermost brake before an API response is shown to the operator.
It does not route tools or create facts. It only checks whether the final reply
is answering the same customer question and whether it leaks internal/system
language. When it blocks, it rewrites to a conservative human-handoff message.
"""

from __future__ import annotations

import re
import json
import logging
from typing import Any

from app import config
from app.services.generic_service_rule_service import unsafe_promise_terms

logger = logging.getLogger(__name__)

_FACT_TOPIC = {
    "pinch_safety": "pinch_safety",
    "safety_small_parts": "small_parts_battery",
    "installation": "installation",
    "detachable": "detachable",
    "material": "material",
    "certification_report": "certification",
    "load_capacity": "load_capacity",
    "stability": "stability",
    "dimensions": "dimensions",
    "space_fit": "space_fit",
    "placement_scene": "placement_scene",
    "age_range": "age_range",
    "cleaning_care": "cleaning",
    "odor": "odor",
    "gift_policy": "gift",
    "stock_shipping": "stock_shipping",
    "invoice_policy": "invoice",
    "price_protection": "price_protection",
    "promotion_policy": "promotion",
    "aftersales_policy": "aftersales",
}

_INTENT_TOPIC = {
    "installation": "installation",
    "gift_missing": "gift",
    "invoice": "invoice",
    "price_protection": "price_protection",
    "promotion_query": "promotion",
    "stock_query": "stock_shipping",
    "cleaning_care": "cleaning",
    "odor_question": "odor",
    "material_safety": "material",
    "child_safety": "material",
    "aftersales": "aftersales",
}

_TOPIC_CUES = {
    "pinch_safety": ("夹手", "防夹", "被夹", "夹到", "夹住", "滑门", "结构安全", "安全隐患"),
    "small_parts_battery": ("小零件", "零件松", "误吞", "吞了", "卡喉", "窒息", "电池", "电池仓", "电池盖"),
    "installation": ("安装", "组装", "怎么装", "教程", "说明书", "打孔", "租房", "螺丝", "装不上"),
    "detachable": ("可拆", "拆卸", "拆开", "拆下来", "能拆", "拆装"),
    "material": ("材质", "材料", "什么料", "用料", "板材", "环保", "受潮", "防潮", "生锈"),
    "certification": ("甲醛", "检测报告", "质检", "认证", "合格证", "环保报告"),
    "load_capacity": ("承重", "放多重", "放多少", "多少本", "压弯", "结实"),
    "stability": ("会不会倒", "防倾倒", "倾倒", "倒塌", "稳不稳", "稳定", "稳固"),
    "dimensions": ("尺寸", "多高", "多宽", "多长", "长宽高", "占地", "规格"),
    "space_fit": ("放得下", "放的下", "摆得下", "摆的下", "空间够", "够不够放", "几平方", "平方", "占空间", "占地方", "预留"),
    "placement_scene": ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放"),
    "age_range": ("适合多大", "适合几岁", "多大宝宝", "月龄", "年龄"),
    "cleaning": ("清洁", "清理", "水洗", "怎么洗", "擦洗", "保养"),
    "odor": ("气味", "味道", "有味", "无味", "无异味", "异味", "刺鼻", "散味", "闻着", "通风"),
    "gift": ("赠品", "礼品", "没送", "少送", "赠送"),
    "stock_shipping": ("库存", "有货", "现货", "发货", "今天发", "多久发"),
    "invoice": ("发票", "电子发票", "抬头", "税号"),
    "price_protection": ("价保", "保价", "降价", "补差"),
    "promotion": ("优惠", "活动", "满减", "折扣", "券"),
    "aftersales": (
        "补发", "漏发", "发错", "发漏", "少件", "少了", "缺件", "缺配件",
        "破损", "坏了", "退货", "退款", "换货", "售后", "退换",
    ),
}

_UNICODE_TOPIC_CUES = {
    "pinch_safety": ("夹手", "防夹", "被夹", "夹到", "夹住", "滑门", "结构安全", "安全隐患"),
    "small_parts_battery": ("小零件", "零件松", "误吞", "吞了", "卡喉", "窒息", "电池", "电池仓", "电池盖"),
    "installation": ("安装", "组装", "怎么装", "教程", "说明书", "打孔", "租房", "螺丝", "装不上"),
    "detachable": ("可拆", "可拆卸", "拆卸", "拆开", "拆下来", "能拆", "拆装"),
    "material": ("材质", "材料", "什么料", "用料", "板材", "环保", "受潮", "防潮", "生锈", "食品级", "PP", "HDPE"),
    "certification": ("甲醛", "检测报告", "质检", "认证", "合格证", "环保证书", "3C"),
    "load_capacity": ("承重", "载重", "放多重", "放多少", "多少本", "压弯", "结实"),
    "stability": ("会不会倒", "防倾倒", "倾倒", "倒塌", "稳不稳", "稳定", "稳固"),
    "dimensions": ("尺寸", "多高", "多宽", "多长", "长宽高", "占地", "规格"),
    "space_fit": ("放得下", "放的下", "摆得下", "摆的下", "空间够", "够不够放", "几平方", "平方", "占空间", "占地方", "预留"),
    "placement_scene": ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放"),
    "age_range": ("适合多大", "适合几岁", "多大宝宝", "月龄", "年龄"),
    "cleaning": ("清洁", "清理", "水洗", "怎么洗", "擦洗", "保养"),
    "odor": ("气味", "味道", "味儿", "有味", "无味", "无异味", "无毒无味", "异味", "刺鼻", "散味", "闻着", "通风"),
    "gift": ("赠品", "礼品", "没送", "少送", "漏发赠品"),
    "stock_shipping": ("库存", "有货", "现货", "发货", "今天发", "多久发"),
    "invoice": ("发票", "电子发票", "抬头", "税号"),
    "price_protection": ("价保", "保价", "降价", "补差"),
    "promotion": ("优惠", "活动", "满减", "折扣", "券"),
    "aftersales": ("补发", "漏发", "发错", "少件", "少了", "缺件", "破损", "坏了", "退货", "退款", "换货", "售后"),
}

_MESSAGE_REQUIRED_TOPICS = {
    "pinch_safety",
    "small_parts_battery",
    "installation",
    "detachable",
    "certification",
    "load_capacity",
    "stability",
    "dimensions",
    "space_fit",
    "placement_scene",
    "age_range",
    "odor",
    "gift",
    "invoice",
    "price_protection",
    "promotion",
    "aftersales",
}

_PRODUCT_CARD_REQUIRED_FACT_TYPES = {
    "material",
    "certification_report",
    "pinch_safety",
    "safety_small_parts",
    "installation",
    "detachable",
    "odor",
    "dimensions",
    "space_fit",
    "placement_scene",
    "load_capacity",
    "stability",
    "age_range",
    "cleaning_care",
}

# Cues that are ambiguous between installation guidance and an aftersales
# missing-parts problem (e.g. 螺丝/配件/说明书). Alone, these must not flag an
# installation expectation when the message is a 补发/少件 aftersales request.
_INSTALLATION_AMBIGUOUS_CUES = ("螺丝", "配件", "说明书")
_INSTALLATION_STRONG_CUES = ("安装", "组装", "怎么装", "装不上", "教程", "打孔", "租房")

_CONFLICTS = {
    "pinch_safety": {"small_parts_battery", "material", "load_capacity", "dimensions", "cleaning", "gift", "invoice"},
    "small_parts_battery": {"pinch_safety", "load_capacity", "dimensions", "cleaning", "gift", "invoice"},
    "installation": {"load_capacity", "material", "cleaning", "gift", "invoice", "stock_shipping"},
    "detachable": {"installation", "load_capacity", "material", "gift", "invoice"},
    "material": {"cleaning", "installation", "load_capacity", "gift", "invoice"},
    "certification": {"installation", "load_capacity", "cleaning", "gift", "invoice"},
    "load_capacity": {"installation", "cleaning", "gift", "invoice"},
    "dimensions": {"installation", "cleaning", "gift", "invoice"},
    "space_fit": {"load_capacity", "material", "cleaning", "gift", "invoice"},
    "placement_scene": {"load_capacity", "material", "gift", "invoice"},
    "gift": {"installation", "material", "load_capacity", "dimensions"},
    "invoice": {"installation", "material", "load_capacity", "dimensions"},
}

_INTERNAL_PHRASES = (
    "系统里",
    "资料库",
    "知识库",
    "已审核资料",
    "RAG",
    "Evidence Gate",
    "query_fact_type",
    "fact_type",
    "小零件/电池安全",
    "夹手/结构安全",
    "\u56db\u7ea7\u63a7\u4ef7",
    "\u96364",
    "\u5927\u4fc3\u4ef7",
    "\u5927\u4fc3\u4ef7_\u96364",
    "\u5185\u90e8\u4ef7",
    "\u63a7\u4ef7",
    "\u6210\u672c\u4ef7",
    "\u5e95\u4ef7",
    "\u6bdb\u5229",
    "\u5229\u6da6",
)


def audit_final_answer(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit and, if needed, replace the final suggested reply."""
    display_name = _display_product_name(response, copilot_context or {})
    if display_name:
        response["display_product_name"] = display_name
    reply = str(response.get("suggested_reply") or "")
    if not reply.strip():
        return response

    expected = _expected_topics(customer_message, response)
    actual = _detect_topics(reply, ignore_quoted_names=True)
    llm_audit = None
    if config.COPILOT_FINAL_AUDIT_LLM_ENABLED:
        llm_audit = _semantic_llm_audit(
            customer_message,
            reply,
            response,
            sorted(expected),
            sorted(actual),
            copilot_context or {},
        )

    if llm_audit:
        issues = []
        if not llm_audit.get("passed", True):
            issues.extend(f"llm:{issue}" for issue in llm_audit.get("issues", []) or ["semantic_mismatch"])
        issues.extend(_hard_safety_issues(reply, response, copilot_context or {}))
    else:
        issues = _audit_issues(customer_message, reply, expected, actual, response, copilot_context or {})
    passed = not issues

    audit = {
        "checked": True,
        "passed": passed,
        "issues": issues,
        "expected_topics": sorted(expected),
        "reply_topics": sorted(actual),
        "mode": "deterministic_semantic_consistency",
    }
    if llm_audit:
        audit["llm_audit"] = llm_audit
        audit["mode"] = "llm_semantic_consistency_with_hard_safety"
    response["final_answer_audit"] = audit
    response.setdefault("evidence_debug", {})["final_answer_audit"] = audit

    if passed:
        return response

    original_reply = reply
    corrected_reply = _generic_rule_correction_reply(response, expected)
    response["suggested_reply"] = corrected_reply or _fallback_reply(response, customer_message, expected)
    response["requires_human_review"] = False if corrected_reply else True
    if corrected_reply:
        response["final_answer_audit"]["correction_source"] = "generic_service_rule"
    if not corrected_reply:
        response["reason_for_review"] = _append_reason(
            response.get("reason_for_review", ""),
        "最终回复语义一致性审核未通过",
        )
    if not corrected_reply:
        response["risk_level"] = response.get("risk_level") or "medium"
    response["generation_mode"] = "final_answer_audit_fallback"
    response["final_answer_audit"]["fallback_used"] = True
    response["final_answer_audit"]["original_reply"] = original_reply
    response.setdefault("guard_warnings", []).append(
        "final_answer_audit: " + ",".join(issues)
    )
    response.setdefault("trace_steps", []).append({
        "node": "final_answer_audit",
        "status": "blocked",
        "issues": issues,
        "summary": "final answer semantic consistency blocked",
    })
    return response


def _expected_topics(message: str, response: dict[str, Any]) -> set[str]:
    topics = _detect_topics(message)
    debug = response.get("evidence_debug") or {}
    fact_type = (
        debug.get("query_fact_type")
        or response.get("query_fact_type")
        or response.get("missing_fact_type")
        or ""
    )
    mapped = _FACT_TOPIC.get(str(fact_type))
    if mapped:
        topics.add(mapped)
    intent_topic = _INTENT_TOPIC.get(str(response.get("intent") or ""))
    if intent_topic:
        topics.add(intent_topic)
    return topics


def _detect_topics(text: str, *, ignore_quoted_names: bool = False) -> set[str]:
    if ignore_quoted_names:
        text = re.sub(r"「[^」]{1,80}」", "「商品」", text)
    found: set[str] = set()
    for topic, cues in _TOPIC_CUES.items():
        if any(cue in text for cue in cues):
            found.add(topic)
    for topic, cues in _UNICODE_TOPIC_CUES.items():
        if any(cue in text for cue in cues):
            found.add(topic)
    # Disambiguate installation vs aftersales: 螺丝/配件/说明书 alone is not an
    # installation question when the message is an aftersales 补发/少件 request
    # (e.g. "少了一个螺丝，能补发不？" must not be expected as installation).
    if "aftersales" in found and "installation" in found:
        only_ambiguous = any(cue in text for cue in _INSTALLATION_AMBIGUOUS_CUES)
        has_strong = any(cue in text for cue in _INSTALLATION_STRONG_CUES)
        if only_ambiguous and not has_strong:
            found.discard("installation")
    return found


def _required_topics_from_message(message: str, response: dict[str, Any]) -> set[str]:
    """Topics explicitly asked by the customer that the final reply must cover."""
    topics = _detect_topics(message)
    required = {topic for topic in topics if topic in _MESSAGE_REQUIRED_TOPICS}
    if "odor" in topics:
        required.add("odor")
    if "space_fit" in required:
        required.discard("placement_scene")
    fact_type = str((response.get("evidence_debug") or {}).get("query_fact_type") or "")
    mapped = _FACT_TOPIC.get(fact_type)
    if mapped and mapped in _MESSAGE_REQUIRED_TOPICS:
        required.add(mapped)
    return required


def _audit_issues(
    message: str,
    reply: str,
    expected: set[str],
    actual: set[str],
    response: dict[str, Any],
    copilot_context: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    required_topics = _required_topics_from_message(message, response)
    if required_topics and not _is_generic_handoff(reply):
        for topic in sorted(required_topics):
            if topic not in actual:
                issues.append(f"missing_required_topic:{topic}")

    for topic in expected:
        conflicts = _CONFLICTS.get(topic, set())
        if actual & conflicts and topic not in actual:
            issues.append(f"wrong_topic:{topic}->{','.join(sorted(actual & conflicts))}")

    if expected and actual and not (expected & actual):
        # Do not block generic "please wait while I verify" messages unless they
        # introduce a conflicting topic.
        if not _is_generic_handoff(reply):
            issues.append("answer_not_about_customer_question")

    if any(phrase.lower() in reply.lower() for phrase in _INTERNAL_PHRASES):
        issues.append("internal_system_language")
    unsafe_terms = unsafe_promise_terms(reply)
    if unsafe_terms:
        issues.append("unsafe_customer_promise:" + ",".join(unsafe_terms))

    if _asks_for_order_when_already_given(reply, response, copilot_context):
        issues.append("asks_for_existing_order_id")

    if "pinch_safety" in expected and "small_parts_battery" in actual:
        issues.append("pinch_safety_answered_as_small_parts_battery")

    if _product_card_missing_fact_but_reply_answers(response, reply):
        issues.append("product_card_missing_fact_answered_as_direct")

    return _dedupe(issues)


def _hard_safety_issues(
    reply: str,
    response: dict[str, Any],
    copilot_context: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if any(phrase.lower() in reply.lower() for phrase in _INTERNAL_PHRASES):
        issues.append("internal_system_language")
    unsafe_terms = unsafe_promise_terms(reply)
    if unsafe_terms:
        issues.append("unsafe_customer_promise:" + ",".join(unsafe_terms))
    if _asks_for_order_when_already_given(reply, response, copilot_context):
        issues.append("asks_for_existing_order_id")
    if _product_card_missing_fact_but_reply_answers(response, reply):
        issues.append("product_card_missing_fact_answered_as_direct")
    return _dedupe(issues)


def _is_generic_handoff(reply: str) -> bool:
    return any(phrase in reply for phrase in ("稍等", "核实", "确认清楚", "确认后", "转人工", "转给同事"))


def _product_card_missing_fact_but_reply_answers(response: dict[str, Any], reply: str) -> bool:
    debug = response.get("evidence_debug") or {}
    if debug.get("evidence_sufficient") is True:
        return False
    evidence_pack = _product_card_evidence_pack(response)
    if not evidence_pack:
        return False
    fact_type = str(evidence_pack.get("query_fact_type") or debug.get("query_fact_type") or "")
    if fact_type not in _PRODUCT_CARD_REQUIRED_FACT_TYPES:
        return False
    if evidence_pack.get("answerability") not in {"missing_product_fact", "no_product_profile", "no_product_identity"}:
        return False
    return not _is_generic_handoff(reply)


def _product_card_evidence_pack(response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    pack = response.get("product_card_evidence_pack") or debug.get("product_card_evidence_pack")
    if isinstance(pack, dict) and pack:
        return pack
    product_summary = debug.get("product_context_pack_summary") or {}
    if isinstance(product_summary, dict):
        pack = product_summary.get("evidence_pack")
        if isinstance(pack, dict) and pack:
            return pack
    product_pack = response.get("product_context_pack") or {}
    if isinstance(product_pack, dict):
        pack = product_pack.get("evidence_pack")
        if isinstance(pack, dict):
            return pack
    return {}


def _asks_for_order_when_already_given(
    reply: str,
    response: dict[str, Any],
    copilot_context: dict[str, Any],
) -> bool:
    has_order = bool(
        response.get("order_id")
        or response.get("platform_order_id")
        or copilot_context.get("order_id")
        or copilot_context.get("platform_order_id")
        or copilot_context.get("platform_trade_id")
    )
    if not has_order:
        debug = response.get("evidence_debug") or {}
        has_order = bool(debug.get("order_id") or debug.get("platform_order_id"))
    if not has_order:
        return False
    if any(
        phrase in reply
        for phrase in (
            "\u4e0d\u7528\u60a8\u91cd\u590d\u63d0\u4f9b\u8ba2\u5355\u53f7",
            "\u4e0d\u7528\u91cd\u590d\u63d0\u4f9b\u8ba2\u5355\u53f7",
            "\u4e0d\u9700\u8981\u60a8\u91cd\u590d\u63d0\u4f9b\u8ba2\u5355\u53f7",
        )
    ):
        return False
    return any(phrase in reply for phrase in ("提供订单号", "发一下订单号", "补充订单号", "订单号发我"))


def _fallback_reply(response: dict[str, Any], message: str, expected: set[str]) -> str:
    product = _product_name(response) or "这款商品"
    if "pinch_safety" in expected:
        return (
            f"亲亲，您担心「{product}」会不会夹手、宝宝使用是否安全，这个顾虑很正常。\n"
            "这类收纳/柜架产品建议先确认安装是否到位，滑门、抽屉、卡扣、连接件这些位置使用前可以简单检查一下，避免松动或没有扣紧。\n"
            "宝宝使用时建议大人在旁边看护，不建议让孩子攀爬、摇晃或把手伸进活动缝隙里玩。\n"
            "如果您是看到某个位置比较担心，可以把页面截图或实物位置发我，我帮您按具体位置判断怎么处理。"
        )
    if "small_parts_battery" in expected:
        return (
            f"亲亲，您担心「{product}」有没有小零件、电池件或误吞风险是对的，宝宝用品这类问题需要谨慎一点。\n"
            "建议收到后先核对配件和说明书，小配件、安装五金这类物品在安装前后都不要让宝宝单独接触。\n"
            "如果您不确定某个配件是否适合宝宝接触，可以把配件图发我，我帮您一起看一下。"
        )
    if "installation" in expected:
        return (
            f"亲亲，您问的是「{product}」的安装方式对吗？\n"
            "建议您先按说明书把配件全部核对齐，再从主体框架开始安装，卡扣/螺丝位置不要一次性拧太紧，整体对齐后再固定会更稳。\n"
            "如果安装到某一步卡住，可以把当前步骤或卡住的位置拍给我，我帮您对照处理。"
        )
    if "detachable" in expected:
        return (
            f"亲亲，您问的是「{product}」能不能拆装对吗？\n"
            "这类收纳/柜架商品通常是按配件结构组装使用的，后续需要搬动或调整位置时，一般可以按安装步骤反向拆开再重新装。\n"
            "拆装时建议先清空内部物品，再从可拆连接件位置开始，不要硬掰受力部位，避免影响卡扣或框架稳定。"
        )
    if "odor" in expected:
        return (
            f"亲亲，您担心「{product}」的气味问题很正常，宝宝用品确实要谨慎一些。\n"
            "这类新出库商品刚拆包装时，可能会有一点新材料或包装密封运输带来的味道，一般不是明显刺鼻异味，通风放置后会慢慢散掉。\n"
            "建议您收到后先把外包装全部拆开，抽屉、柜门、收纳格这些位置尽量打开，放在阳台或窗边通风处晾一晾，也可以用干净湿布简单擦拭表面后自然晾干，等气味散掉后再给宝宝使用会更安心。\n"
            "如果您收到后感觉味道明显刺鼻，或者通风后仍然很明显，建议先暂停使用，并拍照/视频联系咱们客服，我们会根据实际情况帮您处理。"
        )
    if "material" in expected or "certification" in expected:
        return (
            f"亲亲，您关注「{product}」的材质和安全很正常，家里有宝宝的话确实要看得更细一点。\n"
            "材质、检测、证书这类信息建议以商品详情页、包装标识和随货说明为准；没有检测依据时不做绝对化承诺。\n"
            "收到后建议先检查外观和气味，放在通风处散味后再给宝宝使用；如果有明显刺鼻气味、破损或材质异常，可以拍照/视频联系我们处理。"
        )
    if "gift" in expected:
        return (
            "亲亲，赠品一般需要同时看下单活动页面、订单是否满足条件，以及仓库发货明细。\n"
            "如果您方便，可以把活动页或订单页面截图发我，我帮您一起核对；如果确实符合活动但漏发，我们会按售后流程协助处理。"
        )
    return (
        "亲亲，这个细节我先帮您按当前商品和页面信息一起核对。\n"
        "如果您方便，也可以把商品页面或实物位置截图发我，我这边会更快帮您判断。"
    )


def _generic_rule_correction_reply(response: dict[str, Any], expected: set[str]) -> str:
    rule = _matched_generic_rule(response, expected)
    if not rule:
        return ""
    if str(rule.get("risk_level") or "low") != "low":
        return ""
    if rule.get("auto_reply_allowed") is False:
        return ""
    try:
        from app.services.generic_service_rule_service import render_generic_service_reply
    except Exception:
        return ""
    product = _product_name(response) or _display_product_name(response) or ""
    reply = render_generic_service_reply(rule, product_name=product)
    if not reply:
        return ""
    if unsafe_promise_terms(reply):
        return ""
    return reply


def _matched_generic_rule(response: dict[str, Any], expected: set[str]) -> dict[str, Any] | None:
    pack = (response.get("context_used") or {}).get("product_context_pack") or {}
    candidates = []
    candidates.extend(pack.get("generic_rules") or [])
    evidence_pack = pack.get("evidence_pack") or {}
    candidates.extend(evidence_pack.get("matched_generic_rules") or [])
    if not candidates:
        return None
    expected = set(expected or set())
    exact = [item for item in candidates if item.get("fact_type") in expected]
    pool = exact or candidates
    return max(pool, key=lambda item: float(item.get("score") or item.get("source_confidence") or 0))


def _display_product_name(response: dict[str, Any]) -> str:
    return str(
        response.get("display_product_name")
        or ((response.get("context_used") or {}).get("display_product_name"))
        or ""
    ).strip()


def _product_name(response: dict[str, Any]) -> str:
    context_used = response.get("context_used") or {}
    context_summary = context_used.get("conversation_context_summary") or {}
    product_pack = context_used.get("product_context_pack") or {}
    pack_identity = product_pack.get("identity") or {}
    candidates = [
        response.get("display_product_name"),
        response.get("platform_product_title"),
        response.get("front_product_title"),
        response.get("product_name"),
        response.get("matched_product_name"),
        context_used.get("matched_product_name"),
        context_summary.get("confirmed_product"),
        context_summary.get("product_name"),
        pack_identity.get("product_name"),
        (response.get("evidence_debug") or {}).get("matched_product_name"),
    ]
    reply = str(response.get("suggested_reply") or "")
    match = re.search(r"「([^」]{2,60})」", reply)
    if match:
        candidates.append(match.group(1))
    for value in candidates:
        text = str(value or "").strip()
        if text and text not in {"商品", "这款", "这个"}:
            return text
    return ""


def _display_product_name(response: dict[str, Any], copilot_context: dict[str, Any]) -> str:
    candidates: list[Any] = [
        response.get("display_product_name"),
        response.get("platform_product_title"),
        response.get("front_product_title"),
        response.get("product_title"),
        response.get("item_title"),
        copilot_context.get("display_product_name"),
        copilot_context.get("platform_product_title"),
        copilot_context.get("front_product_title"),
        copilot_context.get("product_title"),
        copilot_context.get("item_title"),
    ]
    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        nested = context_used.get("copilot_context") or {}
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("display_product_name"),
                nested.get("platform_product_title"),
                nested.get("front_product_title"),
                nested.get("product_title"),
                nested.get("item_title"),
            ])
    for source in (
        copilot_context.get("product_candidates"),
        response.get("product_candidates"),
        (context_used.get("copilot_context") or {}).get("product_candidates") if isinstance(context_used, dict) else None,
    ):
        if not isinstance(source, list):
            continue
        for candidate in source:
            if isinstance(candidate, str):
                candidates.append(candidate)
            elif isinstance(candidate, dict):
                candidates.extend([
                    candidate.get("display_product_name"),
                    candidate.get("platform_product_title"),
                    candidate.get("front_product_title"),
                    candidate.get("product_title"),
                    candidate.get("item_title"),
                    candidate.get("title"),
                    candidate.get("sidecar_front_title"),
                    candidate.get("product_name"),
                    candidate.get("value"),
                ])
    for value in candidates:
        text = str(value or "").strip()
        if _looks_like_customer_product_title(text):
            return text
    return ""


def _looks_like_customer_product_title(text: str) -> bool:
    if not text:
        return False
    if len(text) >= 16:
        return True
    return "英禾" in text or "INHE" in text.upper()


def _append_reason(existing: str, reason: str) -> str:
    if not existing:
        return reason
    if reason in existing:
        return existing
    return f"{existing}；{reason}"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _semantic_llm_audit(
    customer_message: str,
    reply: str,
    response: dict[str, Any],
    expected_topics: list[str],
    reply_topics: list[str],
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Ask the model to judge whether the final reply logically answers the user."""
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        if not client.api_key:
            return None

        evidence_debug = response.get("evidence_debug") or {}
        payload = {
            "customer_message": customer_message,
            "suggested_reply": reply,
            "conversation_context": copilot_context or {},
            "intent": response.get("intent", ""),
            "query_fact_type_hint": evidence_debug.get("query_fact_type", ""),
            "expected_topics_hint": expected_topics,
            "reply_topics_hint": reply_topics,
            "evidence_summary": {
                "evidence_used": response.get("evidence_used", ""),
                "evidence_sufficient": evidence_debug.get("evidence_sufficient"),
                "direct_answer_supported": evidence_debug.get("direct_answer_supported"),
                "faq_evidence": (evidence_debug.get("faq_evidence") or [])[:5],
                "product_facts": (evidence_debug.get("product_facts") or [])[:5],
                "unknowns": (evidence_debug.get("unknowns") or [])[:5],
            },
        }
        result = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "\u4f60\u662f\u667a\u80fd\u5ba2\u670d\u6700\u7ec8\u56de\u590d\u7684\u8bed\u4e49\u4e00\u81f4\u6027\u5ba1\u6838\u5458\uff0c\u53ea\u8d1f\u8d23\u5224\u65ad\uff0c\u4e0d\u8d1f\u8d23\u6539\u5199\u3002"
                        "\u4f60\u7684\u5ba1\u6838\u6807\u51c6\u53ea\u6709\u4e00\u4e2a\u6838\u5fc3\uff1a\u8fd9\u6bb5\u6700\u7ec8\u8981\u53d1\u7ed9\u5ba2\u6237\u7684\u8bdd\uff0c"
                        "\u4f5c\u4e3a\u4e00\u4f4d\u91d1\u724c\u5ba2\u670d\uff0c\u662f\u5426\u80fd\u6b63\u9762\u3001\u51c6\u786e\u3001\u81ea\u7136\u5730\u56de\u7b54\u5ba2\u6237\u5f53\u524d\u95ee\u9898\u3002"
                        "\u4e0d\u8981\u673a\u68b0\u6309 fact_type\u3001expected_topics \u6216\u5173\u952e\u8bcd\u5224\u65ad\uff1b\u8fd9\u4e9b\u53ea\u80fd\u5f53\u4f5c\u53c2\u8003\u7ebf\u7d22\u3002"
                        "\u4f60\u8981\u5148\u7528\u81ea\u5df1\u7684\u8bed\u4e49\u7406\u89e3\u5224\u65ad\u5ba2\u6237\u771f\u6b63\u5728\u95ee\u4ec0\u4e48\uff0c\u518d\u770b suggested_reply \u662f\u5426\u771f\u7684\u56de\u7b54\u4e86\u8fd9\u4e2a\u95ee\u9898\u3002"
                        "\u4f8b\u5982\uff1a\u5ba2\u6237\u95ee\u201c\u5367\u5ba4\u53ef\u4ee5\u7528\u5417\u201d\uff0c\u56de\u590d\u53ea\u8bb2\u6750\u8d28/\u9632\u6f6e\u662f\u8dd1\u9898\uff1b"
                        "\u5ba2\u6237\u95ee\u201c\u7a7a\u95f4\u591f\u4e0d\u591f\u653e\u4e0b\u201d\uff0c\u56de\u590d\u627f\u91cd\u591a\u5c11\u662f\u8dd1\u9898\u3002"
                        "\u8bf7\u50cf\u771f\u4eba\u8d28\u68c0\u4e3b\u7ba1\u4e00\u6837\u5224\u65ad\uff1a\u5ba2\u6237\u5230\u5e95\u5728\u95ee\u4ec0\u4e48\uff0c\u51c6\u5907\u53d1\u9001\u7684\u56de\u590d\u662f\u5426\u6b63\u9762\u56de\u7b54\u3002"
                        "\u5982\u679c\u5ba2\u6237\u53ea\u662f\u50ac\u9000\u6b3e\u6216\u7528\u6295\u8bc9\u65bd\u538b\uff0c\u6ca1\u6709\u63d0\u7834\u635f\u3001\u5c11\u4ef6\u3001\u53d1\u9519\u3001\u5b9e\u7269\u5f02\u5e38\u6216\u5df2\u53d1\u56fe\uff0c"
                        "\u56de\u590d\u4e0d\u5e94\u8be5\u8981\u5b9e\u7269\u7167\u3001\u5916\u7bb1\u7167\u3001\u9762\u5355\u7167\uff1b\u8fd9\u79cd\u51ed\u7a7a\u7d22\u8bc1\u5c5e\u4e8e\u7b54\u975e\u6240\u95ee\uff0c\u5fc5\u987b passed=false\u3002"
                        "\u5982\u679c\u5ba2\u6237\u5df2\u7ecf\u63d0\u4f9b\u8ba2\u5355\u53f7\u6216\u4e0a\u4e0b\u6587\u6709\u8ba2\u5355\uff0c\u56de\u590d\u4e0d\u80fd\u518d\u8ba9\u5ba2\u6237\u63d0\u4f9b\u8ba2\u5355\u53f7\u3002"
                        "\u4e0d\u8981\u6309\u5173\u952e\u8bcd\u673a\u68b0\u5224\u65ad\uff0c\u8981\u6309\u8bed\u4e49\u3001\u5df2\u77e5\u4e0a\u4e0b\u6587\u548c\u56de\u590d\u903b\u8f91\u5224\u65ad\u3002"
                        "你是智能客服最终回复的语义一致性审核员，只负责判断，不负责改写。"
                        "你要像真人质检主管一样看：客户到底问什么，准备发送的回复是否正面回答，"
                        "是否跑题、答非所问、遗漏核心问题、索要已提供的信息、暴露系统/RAG/知识库/审核等内部措辞，"
                        "是否把不确定信息包装成确定承诺。不要按关键词机械判断，要按语义判断。"
                        "query_fact_type_hint、expected_topics_hint、reply_topics_hint 只能作为提示，不能替代你的语义判断。"
                        "如果客户问“材质有气味吗”，回复只讲防潮、钢管、PP 材质但没有回答气味，就必须 passed=false。"
                        "如果回复是礼貌说明稍等核实，且没有跑题承诺，可以 passed=true。"
                        "只输出 JSON: {\"passed\": boolean, \"issues\": string[], \"reason\": string}"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=260,
            response_format={"type": "json_object"},
        )
        raw = result.choices[0].message.content.strip()
        parsed = json.loads(raw)
        issues = parsed.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        return {
            "passed": bool(parsed.get("passed", False)),
            "issues": [str(x)[:80] for x in issues if str(x).strip()][:5],
            "reason": str(parsed.get("reason", ""))[:300],
        }
    except Exception as exc:
        logger.warning("semantic final answer llm audit failed: %s", exc)
        return None


def _optional_llm_audit(
    customer_message: str,
    reply: str,
    response: dict[str, Any],
    expected_topics: list[str],
    reply_topics: list[str],
) -> dict[str, Any] | None:
    """Optional second-pass semantic judge.

    Deterministic blocking rules are never overridden by this judge. The LLM is
    only allowed to add a block when the deterministic pass did not find a
    conflict but the answer is still semantically off.
    """
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        if not client.api_key:
            return None
        payload = {
            "customer_message": customer_message,
            "suggested_reply": reply,
            "intent": response.get("intent", ""),
            "query_fact_type": (response.get("evidence_debug") or {}).get("query_fact_type", ""),
            "expected_topics": expected_topics,
            "reply_topics": reply_topics,
            "instruction": (
                "判断 suggested_reply 是否正面回答 customer_message。"
                "如果回复主题跑偏、暴露系统/知识库/已审核资料等内部措辞、"
                "或把夹手安全答成电池/小零件/材质等其他主题，则 passed=false。"
            ),
        }
        result = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是客服回复的最终语义一致性审核器，只输出 JSON。"
                        "schema: {\"passed\": boolean, \"issues\": string[], \"reason\": string}"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=220,
            response_format={"type": "json_object"},
        )
        raw = result.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return {
            "passed": bool(parsed.get("passed", False)),
            "issues": [str(x)[:80] for x in parsed.get("issues", []) if str(x).strip()][:5],
            "reason": str(parsed.get("reason", ""))[:300],
        }
    except Exception as exc:
        logger.warning("optional final answer llm audit failed: %s", exc)
        return None
