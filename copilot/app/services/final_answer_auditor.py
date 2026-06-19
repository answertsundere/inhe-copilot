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
    "visual_asset": "visual_asset",
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

_SAFE_COMPOSITION_FALLBACK_FACT_TYPES = {
    "space_fit",
    "placement_scene",
    "stock_shipping",
    "visual_asset",
    "aftersales_policy",
    "installation",
}

_TOPIC_CUES = {
    "pinch_safety": ("夹手", "防夹", "被夹", "夹到", "夹住", "滑门", "结构安全", "安全隐患"),
    "small_parts_battery": ("小零件", "零件松", "误吞", "吞了", "卡喉", "窒息", "电池", "电池仓", "电池盖"),
    "installation": ("安装", "组装", "怎么装", "教程", "说明书", "打孔", "租房", "螺丝", "装不上"),
    "detachable": ("可拆", "拆卸", "拆开", "拆下来", "能拆", "拆装"),
    "material": ("材质", "材料", "什么料", "用料", "板材", "环保", "受潮", "防潮", "防水", "面料", "生锈"),
    "certification": ("甲醛", "检测报告", "质检", "认证", "合格证", "环保报告"),
    "load_capacity": ("承重", "放多重", "放多少", "多少本", "压弯", "结实"),
    "stability": ("会不会倒", "防倾倒", "倾倒", "倒塌", "稳不稳", "稳定", "稳固"),
    "dimensions": ("尺寸", "多高", "多宽", "多长", "长宽高", "占地", "规格"),
    "space_fit": ("放得下", "放的下", "摆得下", "摆的下", "空间够", "够不够放", "几平方", "平方", "占空间", "占地方", "预留"),
    "placement_scene": ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放"),
    "age_range": ("适合多大", "适合几岁", "多大宝宝", "月龄", "年龄", "几个月", "半岁", "一岁", "两岁", "三岁", "岁宝宝"),
    "cleaning": ("清洁", "清理", "水洗", "水冲", "湿布", "晾干", "怎么洗", "擦洗", "保养"),
    "odor": ("气味", "味道", "有味", "无味", "无异味", "异味", "刺鼻", "散味", "闻着", "通风"),
    "visual_asset": ("图片", "照片", "图看", "看图", "有图", "实物图", "效果图", "样子"),
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
    "material": ("材质", "材料", "什么料", "用料", "板材", "环保", "受潮", "防潮", "防水", "面料", "生锈", "食品级", "PP", "HDPE"),
    "certification": ("甲醛", "检测报告", "质检", "认证", "合格证", "环保证书", "3C"),
    "load_capacity": ("承重", "载重", "放多重", "放多少", "多少本", "压弯", "结实"),
    "stability": ("会不会倒", "防倾倒", "倾倒", "倒塌", "稳不稳", "稳定", "稳固"),
    "dimensions": ("尺寸", "多高", "多宽", "多长", "长宽高", "占地", "规格"),
    "space_fit": ("放得下", "放的下", "摆得下", "摆的下", "空间够", "够不够放", "几平方", "平方", "占空间", "占地方", "预留"),
    "placement_scene": ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放"),
    "age_range": ("适合多大", "适合几岁", "多大宝宝", "月龄", "年龄", "几个月", "半岁", "一岁", "两岁", "三岁", "岁宝宝"),
    "cleaning": ("清洁", "清理", "水洗", "水冲", "湿布", "晾干", "怎么洗", "擦洗", "保养"),
    "odor": ("气味", "味道", "味儿", "有味", "无味", "无异味", "无毒无味", "异味", "刺鼻", "散味", "闻着", "通风"),
    "visual_asset": ("图片", "照片", "图看", "看图", "有图", "实物图", "效果图", "样子"),
    "gift": ("赠品", "礼品", "没送", "少送", "漏发赠品"),
    "stock_shipping": ("库存", "有货", "现货", "发货", "今天发", "多久发"),
    "invoice": ("发票", "电子发票", "抬头", "税号"),
    "price_protection": ("价保", "保价", "降价", "补差"),
    "promotion": ("优惠", "活动", "满减", "折扣", "券"),
    "aftersales": ("补发", "漏发", "发错", "少件", "少了", "缺件", "破损", "坏了", "退货", "退款", "换货", "售后"),
}

_UNICODE_TOPIC_CUE_EXTENSIONS = {
    "material": (
        "\u5b9d\u5b9d\u80fd\u7528",
        "\u5b69\u5b50\u80fd\u7528",
        "\u6750\u8d28\u653e\u5fc3",
        "\u653e\u5fc3\u5417",
        "\u6f6e\u6e7f",
        "\u53d7\u6f6e",
        "\u9632\u6f6e",
    ),
    "stock_shipping": (
        "\u4eca\u5929\u62cd",
        "\u4eca\u5929\u62cd\u80fd\u53d1",
        "\u62cd\u4e0b\u80fd\u53d1",
        "\u80fd\u53d1\u5417",
        "\u4ec0\u4e48\u65f6\u5019\u53d1",
        "\u4ec0\u4e48\u65f6\u5019\u53d1\u8d27",
        "\u6709\u73b0\u8d27",
    ),
    "aftersales": (
        "\u60f3\u9000",
        "\u600e\u4e48\u9000",
        "\u76f4\u63a5\u9000",
        "\u6536\u5230\u4e0d\u662f",
        "\u4e0d\u662f\u6211\u62cd",
        "\u53d1\u9519",
    ),
}
for _topic_key, _topic_values in _UNICODE_TOPIC_CUE_EXTENSIONS.items():
    _TOPIC_CUES[_topic_key] = _TOPIC_CUES.get(_topic_key, ()) + _topic_values
    _UNICODE_TOPIC_CUES[_topic_key] = _UNICODE_TOPIC_CUES.get(_topic_key, ()) + _topic_values

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
    "visual_asset",
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
_PLACEMENT_STRONG_CUES = (
    "卧室", "客厅", "书房", "厨房", "阳台", "卫生间",
    "摆放", "放在", "适合放", "使用环境", "干燥", "平整",
)

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
    "age_range": {"load_capacity", "material", "dimensions", "installation", "gift", "invoice"},
    "visual_asset": {"load_capacity", "material", "installation", "invoice"},
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

    multi_intent_audit = _multi_intent_coverage_audit(reply, response)
    if llm_audit:
        hard_issues = _hard_safety_issues(reply, response, copilot_context or {})
        issues = []
        if not llm_audit.get("passed", True):
            issues.extend(f"llm:{issue}" for issue in llm_audit.get("issues", []) or ["semantic_mismatch"])
        if issues and _safe_composition_reply_covers(response, reply) and not hard_issues:
            issues = []
        issues.extend(hard_issues)
    else:
        issues = _audit_issues(customer_message, reply, expected, actual, response, copilot_context or {})
    issues.extend(multi_intent_audit.get("issues", []))
    passed = not issues

    audit = {
        "checked": True,
        "passed": passed,
        "issues": issues,
        "expected_topics": sorted(expected),
        "reply_topics": sorted(actual),
        "covered_fact_types": multi_intent_audit.get("covered_fact_types", []),
        "missing_fact_types": multi_intent_audit.get("missing_fact_types", []),
        "mode": "deterministic_semantic_consistency",
    }
    if llm_audit:
        audit["llm_audit"] = llm_audit
        audit["mode"] = "llm_semantic_consistency_with_hard_safety"
    response["final_answer_audit"] = audit
    response.setdefault("evidence_debug", {})["final_answer_audit"] = audit

    if passed:
        response.setdefault("trace_steps", []).append({
            "node": "final_answer_audit",
            "status": "passed",
            "passed": True,
            "issues": [],
            "expected_topics": sorted(expected),
            "reply_topics": sorted(actual),
            "covered_fact_types": multi_intent_audit.get("covered_fact_types", []),
            "missing_fact_types": multi_intent_audit.get("missing_fact_types", []),
            "fallback_used": False,
            "summary": "final answer semantic consistency passed",
        })
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
        "passed": False,
        "issues": issues,
        "expected_topics": sorted(expected),
        "reply_topics": sorted(actual),
        "covered_fact_types": multi_intent_audit.get("covered_fact_types", []),
        "missing_fact_types": multi_intent_audit.get("missing_fact_types", []),
        "blocked_reason": ",".join(issues),
        "fallback_used": True,
        "summary": "final answer semantic consistency blocked",
    })
    return response


def _multi_intent_coverage_audit(reply: str, response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    grouping = debug.get("evidence_grouping") or response.get("evidence_grouping") or {}
    coverage = grouping.get("coverage") or {}
    required = [str(item) for item in coverage.get("required_fact_types", []) if str(item).strip()]
    if len(required) < 2:
        return {"covered_fact_types": [], "missing_fact_types": [], "issues": []}

    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    if isinstance(trace, dict) and trace.get("answer_sections"):
        answered = {
            str(item)
            for item in trace.get("answered_fact_types", trace.get("covered_fact_types", []))
            if str(item).strip()
        }
        acceptable_followup = {
            str(item)
            for item in [
                *(trace.get("fallback_fact_types") or []),
                *(trace.get("needs_followup_fact_types") or []),
            ]
            if str(item).strip()
        }
        covered = [fact_type for fact_type in required if fact_type in answered]
        missing = [fact_type for fact_type in required if fact_type not in answered]
        blocking_missing = [
            fact_type for fact_type in missing
            if fact_type not in acceptable_followup
        ]
        return {
            "covered_fact_types": covered,
            "missing_fact_types": missing,
            "issues": [f"missing_multi_intent_fact_type:{item}" for item in blocking_missing],
        }

    covered = []
    missing = []
    for fact_type in required:
        if _reply_covers_fact_type(reply, fact_type):
            covered.append(fact_type)
        else:
            missing.append(fact_type)
    return {
        "covered_fact_types": covered,
        "missing_fact_types": missing,
        "issues": [f"missing_multi_intent_fact_type:{item}" for item in missing],
    }


def _reply_covers_fact_type(reply: str, fact_type: str) -> bool:
    text = reply or ""
    cues = {
        "material": ("材质", "材料", "安全", "宝宝", "防潮", "防水", "检测"),
        "stock_shipping": ("发货", "库存", "现货", "仓库", "下单页", "今天"),
        "dimensions": ("尺寸", "长", "宽", "高", "尺寸图"),
        "space_fit": ("放得下", "放的下", "空间", "长宽高", "占地", "预留"),
        "placement_scene": ("卧室", "客厅", "书房", "厨房", "阳台", "摆放", "放在", "通风"),
        "visual_asset": ("图", "图片", "素材", "视频"),
        "aftersales_policy": ("售后", "补发", "少件", "缺配件", "退货", "退款"),
        "installation": ("安装", "组装", "教程", "说明"),
        "age_range": ("适合", "宝宝", "年龄", "月龄", "适龄"),
        "odor": ("气味", "味道", "有味", "异味", "通风", "刺鼻"),
    }.get(fact_type, (_FACT_TOPIC.get(fact_type, fact_type),))
    return any(cue and cue in text for cue in cues)


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
    if "placement_scene" in found and not any(cue in text for cue in _PLACEMENT_STRONG_CUES):
        found.discard("placement_scene")
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

    issues.extend(_media_reference_contract_issues(reply, response))

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
    issues.extend(_media_reference_contract_issues(reply, response))
    return _dedupe(issues)


def _media_reference_contract_issues(reply: str, response: dict[str, Any]) -> list[str]:
    fact_types = _required_fact_types(response)
    if not fact_types:
        return []
    if _has_deliverable_media_trace(response):
        return []

    issues: list[str] = []
    primary = _primary_fact_type(response)
    effective = fact_types or ({primary} if primary else set())
    if primary:
        effective.add(primary)

    if "installation" in effective:
        if _contains_any(reply, ("按图", "图里", "下方图片", "下面发", "看图", "发您参考", "图片/视频")):
            issues.append("unsupported_media_reference_without_asset")
        if _contains_any(reply, ("尺寸", "宽度", "进深", "高度", "预留位置", "长宽高")):
            issues.append("off_topic:installation_media_fallback_mentions_dimensions")
    if effective & {"dimensions", "space_fit"}:
        if _contains_any(reply, ("安装", "配件", "按图", "图里标注", "步骤", "教程")) and not _contains_any(reply, ("尺寸", "宽度", "进深", "高度", "长宽高")):
            issues.append("off_topic:dimensions_fallback_mentions_installation")
    if "visual_asset" in effective:
        if _contains_any(reply, ("下面发", "下方图片", "发您参考", "发您看", "一起发您", "直接参考我下面发")):
            issues.append("unsupported_media_reference_without_asset")
    return _dedupe(issues)


def _required_fact_types(response: dict[str, Any]) -> set[str]:
    debug = response.get("evidence_debug") or {}
    grouping = debug.get("evidence_grouping") or response.get("evidence_grouping") or {}
    coverage = grouping.get("coverage") if isinstance(grouping, dict) else {}
    values: list[Any] = []
    if isinstance(coverage, dict):
        values.extend(coverage.get("required_fact_types") or [])
    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    if isinstance(trace, dict):
        values.extend(trace.get("required_fact_types") or [])
        values.extend(trace.get("covered_fact_types") or [])
        values.extend(trace.get("fallback_fact_types") or [])
        values.extend(trace.get("needs_followup_fact_types") or [])
    values.append(debug.get("query_fact_type"))
    values.append(response.get("query_fact_type"))
    values.extend(debug.get("secondary_fact_types") or [])
    values.extend(response.get("secondary_fact_types") or [])
    return {str(item) for item in values if str(item or "").strip()}


def _primary_fact_type(response: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") or {}
    semantic = debug.get("semantic_query") or response.get("semantic_query") or {}
    if isinstance(semantic, dict) and semantic.get("primary_fact_type"):
        return str(semantic.get("primary_fact_type") or "")
    return str(debug.get("query_fact_type") or response.get("query_fact_type") or "")


def _has_deliverable_media_trace(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") or {}
    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    sources: list[Any] = [
        response.get("selected_assets"),
        response.get("recommended_assets"),
        response.get("reply_blocks"),
        debug.get("selected_assets") if isinstance(debug, dict) else None,
    ]
    if isinstance(trace, dict):
        sources.extend([
            trace.get("asset_evidence_used"),
            trace.get("media_evidence_used"),
        ])
    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        pack = context_used.get("product_context_pack") or {}
        if isinstance(pack, dict):
            sources.extend([
                pack.get("selected_assets"),
                pack.get("recommended_assets"),
                pack.get("media_evidence"),
            ])
    return any(_source_has_deliverable_media(source) for source in sources)


def _source_has_deliverable_media(source: Any) -> bool:
    if isinstance(source, dict):
        return any(_source_has_deliverable_media(value) for value in source.values())
    if not isinstance(source, list):
        return False
    for item in source:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("asset_type") or item.get("type") or item.get("media_type") or "").lower()
        has_asset_id = bool(item.get("asset_id") or item.get("id"))
        has_url = bool(
            item.get("asset_url")
            or item.get("url")
            or item.get("oss_url")
            or item.get("signed_url")
            or item.get("media_url")
            or item.get("thumbnail_url")
        )
        if has_url and (has_asset_id or media_type in {"image", "video", "picture", "photo"} or media_type.endswith("_image") or media_type.endswith("_video")):
            return True
    return False


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in str(text or "") for term in terms)


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
    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    if isinstance(trace, dict):
        needs_followup = {
            str(item)
            for item in trace.get("needs_followup_fact_types", [])
            if str(item).strip()
        }
        fallback = {
            str(item)
            for item in trace.get("fallback_fact_types", [])
            if str(item).strip()
        }
        evidence_answered = {
            str(item)
            for item in trace.get("evidence_answered_fact_types", [])
            if str(item).strip()
        }
        if fact_type in needs_followup and fact_type not in evidence_answered:
            return False
        if fact_type in fallback and fact_type not in evidence_answered and _is_generic_handoff(reply):
            return False
    if _safe_composition_fallback_covers(debug, fact_type, reply):
        return False
    return not _is_generic_handoff(reply)


def _safe_composition_fallback_covers(debug: dict[str, Any], fact_type: str, reply: str) -> bool:
    if fact_type not in _SAFE_COMPOSITION_FALLBACK_FACT_TYPES:
        return False
    if unsafe_promise_terms(reply):
        return False
    trace = debug.get("answer_composition_trace") or {}
    if not isinstance(trace, dict):
        return False
    covered = {str(item) for item in trace.get("covered_fact_types", []) if str(item).strip()}
    fallback = trace.get("fallback_used_by_fact_type") or {}
    return fact_type in covered and bool(fallback.get(fact_type))


def _safe_composition_reply_covers(response: dict[str, Any], reply: str) -> bool:
    if unsafe_promise_terms(reply):
        return False
    debug = response.get("evidence_debug") or {}
    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    if not isinstance(trace, dict) or not trace.get("answer_sections"):
        return False
    missing = [item for item in trace.get("missing_fact_types", []) if item]
    if missing:
        return False
    covered = [str(item) for item in trace.get("covered_fact_types", []) if str(item).strip()]
    if not covered:
        return False
    fallback = trace.get("fallback_used_by_fact_type") or {}
    for fact_type in covered:
        if fallback.get(fact_type) and fact_type not in _SAFE_COMPOSITION_FALLBACK_FACT_TYPES:
            return False
        if not _reply_covers_fact_type(reply, fact_type):
            return False
    return True


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
    intent = str(response.get("intent") or "").lower()
    debug = response.get("evidence_debug") or {}
    query_fact_type = str(debug.get("query_fact_type") or response.get("query_fact_type") or "")
    if intent in {"delivery_not_received", "logistics_eta", "logistics_trace", "shipping"}:
        return (
            "\u4eb2\uff0c\u7269\u6d41\u90e8\u5206\u6211\u5148\u6309\u5f53\u524d\u8ba2\u5355\u6216\u7269\u6d41\u4fe1\u606f\u5e2e\u60a8\u6838\u5b9e\u6700\u65b0\u72b6\u6001\u3002\n"
            "\u5982\u679c\u662f\u7b7e\u6536\u672a\u6536\u5230\uff0c\u60a8\u53ef\u4ee5\u5148\u770b\u4e00\u4e0b\u5bb6\u4eba\u3001\u95e8\u536b\u3001\u9a7f\u7ad9\u6216\u5feb\u9012\u67dc\u662f\u5426\u4ee3\u6536\uff0c\u6211\u8fd9\u8fb9\u4e5f\u4f1a\u7ee7\u7eed\u8ddf\u8fdb\u3002"
        )
    if intent == "aftersales" or query_fact_type == "aftersales_policy" or "aftersales" in expected:
        return (
            "\u4eb2\uff0c\u8fd9\u4e2a\u552e\u540e\u60c5\u51b5\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u5904\u7406\u3002\n"
            "\u53d1\u9519\u3001\u5c11\u4ef6/\u7f3a\u914d\u4ef6\u3001\u7834\u635f\u3001\u9000\u8d27\u6216\u6362\u8d27\u90fd\u9700\u8981\u6309\u5e73\u53f0\u552e\u540e\u6d41\u7a0b\u786e\u8ba4\uff1b"
            "\u5982\u679c\u8fd8\u6d89\u53ca\u80fd\u5426\u5b89\u88c5\uff0c\u6211\u4e5f\u4f1a\u7ed3\u5408\u7f3a\u5c11\u7684\u914d\u4ef6\u4e00\u8d77\u6838\u5bf9\u3002\n"
            "\u4e3a\u4e86\u66f4\u5feb\u5904\u7406\uff0c\u65b9\u4fbf\u7684\u8bdd\u60a8\u53ef\u4ee5\u628a\u5b9e\u7269\u3001\u9762\u5355\u6216\u95ee\u9898\u4f4d\u7f6e\u62cd\u6e05\u695a\u53d1\u6211\u3002"
        )
    if intent == "cleaning_care" or query_fact_type == "cleaning_care":
        return (
            "\u4eb2\uff0c\u6e05\u6d17\u65b9\u5f0f\u9700\u8981\u7ed3\u5408\u5177\u4f53\u6750\u8d28\u548c\u7ed3\u6784\u6838\u5b9e\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u786e\u8ba4\u662f\u5426\u80fd\u6c34\u6d17\u3001\u673a\u6d17\u6216\u53ea\u80fd\u64e6\u6d17\uff0c\u907f\u514d\u8bf4\u9519\u5f71\u54cd\u4f7f\u7528\u3002"
        )
    if query_fact_type == "odor":
        return (
            "\u4eb2\uff0c\u6c14\u5473\u95ee\u9898\u6211\u5148\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u548c\u5b9e\u9645\u60c5\u51b5\u5e2e\u60a8\u5224\u65ad\u3002\n"
            "\u6536\u5230\u540e\u53ef\u4ee5\u5148\u6253\u5f00\u5305\u88c5\uff0c\u653e\u5728\u901a\u98ce\u5904\u667e\u4e00\u667e\uff1b\u5982\u679c\u6709\u660e\u663e\u523a\u9f3b\u6216\u6301\u7eed\u4e0d\u6563\u7684\u60c5\u51b5\uff0c\u5148\u6682\u505c\u4f7f\u7528\uff0c\u62cd\u7167\u6216\u89c6\u9891\u53d1\u6211\u4eec\u7ee7\u7eed\u5904\u7406\u3002"
        )
    if query_fact_type in {"material", "certification_report"}:
        return (
            "\u4eb2\uff0c\u6750\u8d28\u3001\u5b89\u5168\u6216\u6c14\u5473\u8fd9\u7c7b\u95ee\u9898\u6211\u5148\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u5e2e\u60a8\u6838\u5b9e\u3002\n"
            "\u6ca1\u6709\u8bc1\u636e\u65f6\u6211\u4e0d\u4f1a\u628a\u5b89\u5168\u3001\u6c14\u5473\u6216\u68c0\u6d4b\u8bf4\u6210\u786e\u5b9a\u7ed3\u8bba\uff0c\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        )
    if intent == "stock_query" or query_fact_type == "stock_shipping" or "stock_shipping" in expected:
        return (
            "\u4eb2\uff0c\u53d1\u8d27\u90e8\u5206\u9700\u8981\u7ed3\u5408\u5f53\u524d\u5e93\u5b58\u3001\u4e0b\u5355\u65f6\u95f4\u548c\u53d1\u8d27\u5b89\u6392\u786e\u8ba4\u3002\n"
            "\u5b9e\u9645\u662f\u5426\u4eca\u5929\u53d1\u51fa\u4ee5\u4e0b\u5355\u9875\u663e\u793a\u548c\u5b9e\u9645\u5904\u7406\u72b6\u6001\u4e3a\u51c6\uff0c\u5177\u4f53\u53d1\u51fa\u65f6\u95f4\u4e0d\u505a\u786e\u5b9a\u6027\u627f\u8bfa\u3002\n"
            "\u5982\u679c\u60a8\u540c\u65f6\u5173\u5fc3\u6750\u8d28\u6216\u5b9d\u5b9d\u4f7f\u7528\u5b89\u5168\uff0c\u6211\u4e5f\u4f1a\u6309\u5546\u54c1\u8d44\u6599\u4e00\u8d77\u6838\u5b9e\u3002"
        )
    if query_fact_type == "age_range" or (
        "age_range" in expected
        and not ({"pinch_safety", "small_parts_battery"} & set(expected))
    ):
        return (
            "\u4eb2\uff0c\u9002\u5408\u591a\u5927\u5b9d\u5b9d\u9700\u8981\u6309\u5bf9\u5e94\u5546\u54c1\u7684\u9002\u7528\u5e74\u9f84\u3001\u7ed3\u6784\u548c\u4f7f\u7528\u573a\u666f\u6838\u5b9e\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u786e\u8ba4\uff1b\u6ca1\u6709\u660e\u786e\u9002\u9f84\u8bc1\u636e\u65f6\uff0c\u6211\u4e0d\u76f4\u63a5\u7ed9\u51fa\u9002\u9f84\u7ed3\u8bba\uff0c\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        )
    if query_fact_type == "dimensions" or "dimensions" in expected:
        return (
            "\u4eb2\uff0c\u5c3a\u5bf8\u90e8\u5206\u9700\u8981\u6309\u5bf9\u5e94\u6b3e\u5f0f\u7684\u957f\u3001\u5bbd\u3001\u9ad8\u6216\u5c3a\u5bf8\u56fe\u6765\u786e\u8ba4\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u5bf9\u4e00\u4e0b\uff0c\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u5c3a\u5bf8\u3002"
        )
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
    reply = render_generic_service_reply(
        rule,
        product_name=product,
        fact_type=_primary_fact_type(response),
        has_media=_has_deliverable_media_trace(response),
    )
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
    if not exact:
        return None
    return max(exact, key=lambda item: float(item.get("score") or item.get("source_confidence") or 0))


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
