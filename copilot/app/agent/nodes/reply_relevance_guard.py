"""Deterministic post-generation reply relevance guard.

This node checks whether the final customer-facing reply addresses the
customer's question, uses a compatible fact type and matches the product
context. It never adds product or order facts and rewrites at most once.
"""

from __future__ import annotations

import re
import time

from app.agent.state import has_order_identifier
from app.services.product_context_consistency import evaluate_product_context


_QUESTION_PATTERNS = {
    "installation": (
        "安装视频", "安装教程", "安装说明", "怎么安装", "如何安装",
        "怎么装", "组装", "说明书", "教程", "安装",
    ),
    "load_capacity": (
        "承重", "容量", "多少本", "放几本", "能放多少", "可以放多少",
        "装多少", "能装多少",
    ),
    "cleaning": (
        "怎么洗", "能洗", "水洗", "机洗", "清洗", "清洁", "擦洗",
        "怎么擦", "好打理",
    ),
    "gift_missing": (
        "赠品", "礼品", "赠送", "赠礼",
    ),
    "invoice": (
        "电子发票", "开发票", "开票", "发票", "抬头", "税号",
    ),
    "price_protection": (
        "价保", "保价", "差价", "补差", "退差", "买贵", "降价",
    ),
    "promotion": (
        "优惠券", "到手价", "有什么优惠", "活动价", "满减", "优惠",
    ),
    "missing_parts": (
        "少了一件", "少件", "缺件", "漏发", "少配件", "缺配件",
        "配件没", "少了配件",
    ),
    "wrong_item": (
        "发错", "错发", "错货", "不是我拍", "不是我买",
        "和下单不一样",
    ),
    "returns": (
        "退货", "退款", "退换", "换货", "申请售后", "想退", "可以退", "能退",
    ),
    "stock_shipping": (
        "有货", "现货", "库存", "多久发货", "什么时候发货",
        "几天发货", "马上发", "今天发", "今天能发", "还能发不", "拍下多久",
    ),
    "logistics": (
        "快递", "物流", "到哪里", "到哪了", "什么时候到",
        "几天到", "送到", "派送", "签收",
    ),
    "material_safety": (
        "材质", "材料", "实木", "甲醛", "无毒", "食品级", "填充",
        "安全", "味道", "气味", "刺鼻", "闻着不舒服",
    ),
}

_INTENT_TO_QUESTION_TYPE = {
    "installation": "installation",
    "gift_missing": "gift_missing",
    "invoice": "invoice",
    "price_protection": "price_protection",
    "price_promotion": "price_protection",
    "promotion_query": "promotion",
    "stock_query": "stock_shipping",
    "logistics_eta": "logistics",
    "logistics_trace": "logistics",
    "shipping": "logistics",
    "delivery_not_received": "logistics",
    "material_safety": "material_safety",
    "child_safety": "material_safety",
    "odor_question": "material_safety",
    "cleaning_care": "cleaning",
}

_REPLY_PATTERNS = {
    **_QUESTION_PATTERNS,
    "installation": _QUESTION_PATTERNS["installation"] + (
        "操作步骤", "对应型号的资料",
    ),
    "load_capacity": _QUESTION_PATTERNS["load_capacity"] + (
        "公斤", "kg", "KG",
    ),
    "material_safety": _QUESTION_PATTERNS["material_safety"] + (
        "PP", "ABS", "检测报告", "安全说明", "停止使用", "不适",
    ),
    "gift_missing": _QUESTION_PATTERNS["gift_missing"] + (
        "活动页面", "活动规则",
    ),
    "invoice": _QUESTION_PATTERNS["invoice"] + (
        "开具", "开票入口",
    ),
    "logistics": _QUESTION_PATTERNS["logistics"] + (
        "运输中", "物流单号", "运单",
    ),
    "stock_shipping": _QUESTION_PATTERNS["stock_shipping"] + (
        "发货安排", "下单页", "仓库", "待发货", "尚未发货",
        "未发货", "安排发货",
    ),
}

_QUESTION_PATTERNS["complaint"] = (
    "投诉", "差评", "12315", "平台介入", "曝光", "再不处理", "不处理",
    "质量太差", "太差了", "售后", "处理", "解决",
)
_INTENT_TO_QUESTION_TYPE.update({
    "complaint": "complaint",
    "high_risk": "complaint",
})
_REPLY_PATTERNS["complaint"] = _QUESTION_PATTERNS["complaint"] + (
    "抱歉", "不好体验", "反馈", "跟进", "优先处理", "订单信息",
    "售后", "主管", "处理方向", "拍照", "视频", "核实处理",
)

_PRODUCT_DETAIL_TYPES = {"load_capacity", "material_safety", "cleaning", "installation"}
_ORDER_SENSITIVE_TYPES = {"gift_missing", "missing_parts", "wrong_item", "returns", "logistics"}
_JST_TOOLS = {"jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"}

_INTERNAL_PHRASES = (
    "系统里没有明确证据",
    "系统暂时没有明确证据",
    "Evidence Gate",
    "evidence gate",
    "RAG",
    "我不能凭感觉猜",
    "我不会直接凭感觉判断",
    "商品参数以页面为准",
)

def reply_relevance_guard(state: dict) -> dict:
    """Check and, once only, conservatively rewrite an irrelevant reply."""
    started = time.time()
    message = state.get("normalized_message") or state.get("customer_message", "") or ""
    reply = state.get("suggested_reply", "") or ""
    customer_questions = _detect_question_types(message, state.get("intent", ""))
    answer_types = _detect_answer_types(reply)
    overlapping_logistics_types = {"logistics", "stock_shipping"}
    if (
        set(customer_questions) <= overlapping_logistics_types
        and answer_types & overlapping_logistics_types
    ):
        answered_questions = list(customer_questions)
        missed_questions = []
    else:
        answered_questions = [item for item in customer_questions if item in answer_types]
        missed_questions = [item for item in customer_questions if item not in answer_types]

    issues: list[str] = []
    wrong_fact_type = _has_wrong_fact_type(customer_questions, answer_types)
    if wrong_fact_type:
        issues.append("wrong_fact_type")

    context_validation = state.get("product_context_validation") or evaluate_product_context(
        message,
        _product_name(state),
    )
    product_context_mismatch = bool(context_validation.get("mismatch"))
    if product_context_mismatch:
        issues.append("product_context_mismatch")

    if missed_questions:
        issues.extend(f"missed_question:{item}" for item in missed_questions)

    if _has_internal_language(reply):
        issues.append("internal_system_language")

    if _has_unsafe_promise(reply):
        issues.append("unsafe_promise")

    if _asks_unnecessary_order_id(message, reply, customer_questions, state):
        issues.append("presale_unnecessary_order_request")

    if _order_tool_missing(state, customer_questions) and not _is_refund_complaint_handoff(
        message, reply, state
    ):
        issues.append("order_tool_not_executed")

    issues = _dedupe(issues)
    passed = not issues
    rewrite_instruction = _rewrite_instruction(
        issues, customer_questions, missed_questions
    )

    rewrite_count = int(state.get("reply_relevance_rewrite_count", 0) or 0)
    rewritten = False
    new_reply = reply
    if not passed and rewrite_count < 1:
        new_reply = _safe_rewrite(
            state=state,
            original_reply=reply,
            question_types=customer_questions,
            missed_questions=missed_questions,
            issues=issues,
        )
        rewrite_count += 1
        rewritten = new_reply != reply

    duration_ms = int((time.time() - started) * 1000)
    reason = "回复已覆盖客户问题" if passed else "；".join(issues)
    result = {
        "passed": passed,
        "issues": issues,
        "reason": reason,
        "rewrite_instruction": rewrite_instruction,
        "customer_questions": customer_questions,
        "answered_questions": answered_questions,
        "missed_questions": missed_questions,
        "wrong_fact_type": wrong_fact_type,
        "product_context_mismatch": product_context_mismatch,
        "rewritten": rewritten,
        "rewrite_count": rewrite_count,
    }

    warnings = list(state.get("guard_warnings", []))
    if not passed:
        warnings.append(f"reply_relevance_guard: {reason}")

    trace = {
        "node": "reply_relevance_guard",
        "status": "passed" if passed else "blocked",
        "passed": passed,
        "duration_ms": duration_ms,
        "issues": issues,
        "rewritten": rewritten,
        "summary": (
            "回复相关性检查通过"
            if passed
            else f"回复相关性检查未通过，发现 {len(issues)} 个问题"
        ),
    }

    if rewritten:
        _increment_metric("reply_relevance_rewrite_count")

    output = {
        "suggested_reply": new_reply,
        "reply_relevance_guard": result,
        "reply_relevance_rewrite_count": rewrite_count,
        "guard_warnings": warnings,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
    if rewritten:
        output["generation_mode"] = "relevance_guard_fallback"
    return output


def _detect_question_types(message: str, intent: str = "") -> list[str]:
    found = [
        question_type
        for question_type, patterns in _QUESTION_PATTERNS.items()
        if _contains_any(message, patterns)
    ]
    intent_type = _INTENT_TO_QUESTION_TYPE.get(intent)
    if intent_type and intent_type not in found:
        found.append(intent_type)
    return _dedupe(found)


def _detect_answer_types(reply: str) -> set[str]:
    return {
        answer_type
        for answer_type, patterns in _REPLY_PATTERNS.items()
        if _contains_any(reply, patterns)
    }


def _has_wrong_fact_type(question_types: list[str], answer_types: set[str]) -> bool:
    questions = set(question_types)
    if len(questions) > 1 and questions & answer_types:
        return False
    if "installation" in questions and "installation" not in answer_types:
        return bool(answer_types & {"load_capacity", "material_safety", "cleaning"})
    if "gift_missing" in questions and "gift_missing" not in answer_types:
        return bool(answer_types & _PRODUCT_DETAIL_TYPES)
    if "invoice" in questions and "invoice" not in answer_types:
        return bool(answer_types - {"invoice"})
    if questions & {"logistics", "stock_shipping"} and not (
        answer_types & {"logistics", "stock_shipping"}
    ):
        return bool(answer_types & _PRODUCT_DETAIL_TYPES)
    if questions & {"missing_parts", "wrong_item", "returns"} and not (
        answer_types & {"missing_parts", "wrong_item", "returns"}
    ):
        return bool(answer_types & _PRODUCT_DETAIL_TYPES)
    return False


def _product_name(state: dict) -> str:
    generic_names = {
        "实木", "不是实木", "材质", "具体材质", "材料", "商品", "这个", "这款",
        "尺寸", "承重", "功能", "参数", "设置方式",
    }
    identity = state.get("order_product_identity") or {}
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or ""
    )
    if product_name and str(product_name).strip() not in generic_names:
        return str(product_name)
    candidates = state.get("product_candidates") or []
    if candidates:
        first = candidates[0]
        if isinstance(first, dict):
            candidate = str(first.get("value") or first.get("name") or "").strip()
        else:
            candidate = str(first).strip()
        if candidate not in generic_names:
            return candidate
    return ""


def _has_internal_language(reply: str) -> bool:
    lowered = reply.lower()
    return any(phrase.lower() in lowered for phrase in _INTERNAL_PHRASES)


def _has_unsafe_promise(reply: str) -> bool:
    safe_text = re.sub(
        r"(?:不能|无法|不予|不会)(?:直接)?(?:保证|确保|承诺).{0,10}(?:绝对|一定|肯定)?",
        "",
        reply,
        flags=re.IGNORECASE,
    )
    safe_text = re.sub(
        r"(?:不能|无法|不予|不会).{0,6}(?:保证|确保|承诺)",
        "",
        safe_text,
        flags=re.IGNORECASE,
    )
    patterns = (
        r"(?:保证|确保).{0,6}(?:绝对|一定|不会出事|不会有问题|安全)",
        r"(?:绝对|一定).{0,6}(?:不会出事|不会有问题|安全)",
        r"(?:百分百|100%).{0,6}(?:安全|不会出事|没问题)",
    )
    return any(re.search(pattern, safe_text, flags=re.IGNORECASE) for pattern in patterns)


def _asks_unnecessary_order_id(
    message: str,
    reply: str,
    question_types: list[str],
    state: dict,
) -> bool:
    if "stock_shipping" not in question_types or has_order_identifier(state):
        return False
    post_purchase_markers = ("我的订单", "已经下单", "已经买", "买了", "付款了", "待发货")
    if _contains_any(message, post_purchase_markers):
        return False
    return _contains_any(reply, ("提供订单号", "发一下订单号", "麻烦提供订单号"))


def _order_tool_missing(state: dict, question_types: list[str]) -> bool:
    if not has_order_identifier(state):
        return False
    if not set(question_types) & _ORDER_SENSITIVE_TYPES:
        return False
    tool_results = state.get("tool_results") or {}
    if any(tool in tool_results for tool in _JST_TOOLS):
        return False
    for trace in state.get("tool_traces", []) or []:
        if trace.get("tool_name") in _JST_TOOLS:
            return False
    return True


def _safe_rewrite(
    state: dict,
    original_reply: str,
    question_types: list[str],
    missed_questions: list[str],
    issues: list[str],
) -> str:
    question_set = set(question_types)
    product_name = _product_name(state)
    has_identifier = has_order_identifier(state)

    if "unsafe_promise" in issues:
        return (
            "亲，孩子使用安全这类问题不能做“绝对不会出事”的保证。"
            "请先按对应商品的使用说明和适用场景使用；如果孩子已经出现不适，"
            "请先停止使用并及时就医，同时把具体商品信息发来，我帮您继续核实。"
        )

    if "product_context_mismatch" in issues:
        return (
            "亲，您咨询的商品类型和当前识别到的商品可能不是同一款。"
            "麻烦您发一下对应商品的链接或截图，我确认商品后再给您准确答复。"
        )

    overlapping_logistics_question = (
        set(question_types) <= {"logistics", "stock_shipping"}
    )
    if len(question_types) > 1 and missed_questions and (
        set(issues) & {"wrong_fact_type", "internal_system_language"}
    ):
        followups = [_missing_question_followup(item, state) for item in missed_questions]
        combined = "\n".join(item for item in followups if item)
        return f"亲，您这次问了几个问题，我分别帮您核实：\n{combined}".strip()

    if (
        len(question_types) > 1
        and missed_questions
        and not overlapping_logistics_question
        and not (
        set(issues) & {"wrong_fact_type", "internal_system_language"}
        )
    ):
        followups = [_missing_question_followup(item, state) for item in missed_questions]
        return original_reply.rstrip() + "\n" + "\n".join(item for item in followups if item)

    if "installation" in question_set:
        subject = f"「{product_name}」" if product_name else "这款商品"
        return (
            f"亲，您需要的是{subject}的安装视频或安装教程。"
            "我先帮您核对对应型号的安装资料，避免发错教程；"
            "如果当前商品型号还不明确，麻烦发一下商品链接或安装位置截图。"
        )

    if "gift_missing" in question_set:
        if has_identifier:
            return (
                "亲，赠品需要结合这笔订单参加的活动和发货记录核对。"
                "我已经收到您的订单信息，先帮您重新核实；"
                "如果方便，也可以补充活动页面或包裹内物品照片。"
            )
        return (
            "亲，赠品需要结合下单时的活动规则和实际发货记录核对。"
            "麻烦您发一下订单截图、活动页面和包裹内物品照片，我帮您确认。"
        )

    if "invoice" in question_set:
        return (
            "亲，电子发票需要按这笔订单的开票规则核实。"
            "您可以先在订单详情查看是否有开票入口；如果没有，"
            "把订单截图发我，我帮您继续确认开票方式。"
        )

    if "stock_shipping" in question_set:
        subject = f"「{product_name}」" if product_name else "这款商品"
        return (
            f"亲，{subject}的库存和发货安排需要结合下单页面和仓库实际情况确认。"
            "您把商品链接或具体款式发我，我帮您核对；实际发货时间以下单页显示为准。"
        )

    if question_set & {"missing_parts", "wrong_item", "returns"}:
        if has_identifier:
            return (
                "亲，我已经收到您的订单信息，这个情况需要先核对订单商品、"
                "发货记录和收到的实物。麻烦您补充实物及外箱面单照片，"
                "我核实后再给您对应的售后处理方案。"
            )
        return (
            "亲，这个情况需要先核对订单商品和收到的实物。"
            "麻烦您发一下订单截图、实物照片和外箱面单，我帮您继续核实处理。"
        )

    if "logistics" in question_set:
        if has_identifier:
            return (
                "亲，我已经收到您的订单或物流信息，但当前还需要重新查询最新状态。"
                "我先帮您核实，确认后再给您准确的物流进度。"
            )
        return (
            "亲，物流进度需要结合订单号或物流单号查询。"
            "麻烦您发一下对应号码，我帮您核实最新状态。"
        )

    if "load_capacity" in question_set:
        if product_name:
            return (
                f"亲，已经识别到您咨询的是「{product_name}」。"
                "关于可放多少本或具体承重数值，我先按这款商品帮您确认清楚。\n"
                "麻烦您稍等一下，确认后我再回复您，您不用重复补充商品信息。"
            )
        return (
            "亲，能放多少本需要结合具体商品型号、尺寸和已确认的容量资料判断。"
            "麻烦您发一下对应商品链接或截图，我确认商品后再给您准确答复。"
        )

    if "cleaning" in question_set:
        return (
            "亲，不同款式的材质和结构不同，清洁方式也可能不一样。"
            "麻烦您发一下具体商品链接、截图或款式，我帮您核对正确的清洁方法。"
        )

    if "material_safety" in question_set:
        if product_name:
            return (
                f"亲，已经识别到您咨询的是「{product_name}」。"
                "您问的材质和安全点我先按这款商品帮您再核实一下。\n"
                "麻烦您稍等一下，确认清楚后我再回复您，您不用重复补充商品信息。"
            )
        return (
            "亲，这个需要结合具体商品型号和已确认的材质或检测资料核实。"
            "麻烦您发一下商品链接、截图或具体款式，我帮您确认准确的信息。"
        )

    return (
        "亲，我先按您刚才的问题重新核实，当前信息还不足以直接下结论。"
        "麻烦您补充对应的商品或订单信息，我确认后再给您准确答复。"
    )


def _missing_question_followup(question_type: str, state: dict) -> str:
    if question_type == "material_safety":
        return "材质和安全部分还需要结合具体商品及已确认资料核实，我会一并帮您确认。"
    if question_type == "logistics":
        if has_order_identifier(state):
            return "物流部分我会按您提供的订单或物流信息继续核实最新状态。"
        return "物流部分还需要订单号或物流单号，您发来后我帮您查询。"
    if question_type == "cleaning":
        return "清洁方式还需要结合具体材质和结构核实，我会一并帮您确认。"
    if question_type == "installation":
        return "安装部分我会继续核对对应型号的安装视频或教程。"
    if question_type == "stock_shipping":
        return "发货部分需要结合当前库存和仓库安排确认，实际时间以下单页和仓库状态为准，我会一并帮您核实。"
    if question_type == "missing_parts":
        if has_order_identifier(state):
            return "少件部分我已收到订单信息，还需要核对发货记录和缺少的具体配件，请补充配件位置或清单。"
        return "少件部分还需要订单截图和缺少配件的位置或清单，我会一并帮您核实。"
    if question_type == "wrong_item":
        return "发错商品部分需要核对订单商品、实物和外箱面单，我会一并帮您核实。"
    if question_type == "returns":
        return "退货部分需要结合商品状态和平台售后规则核对，我会一并帮您确认处理路径。"
    if question_type == "gift_missing":
        return "赠品部分还需要核对活动规则和发货记录，我会一并帮您确认。"
    return "您刚才提到的其他部分我也会继续核实，不会漏掉。"


def _rewrite_instruction(
    issues: list[str],
    question_types: list[str],
    missed_questions: list[str],
) -> str:
    if not issues:
        return ""
    parts = [
        f"只回答客户实际咨询的类型：{', '.join(question_types) or '未识别'}。",
        "不得沿用不匹配的商品参数或订单结论。",
    ]
    if missed_questions:
        parts.append(f"补充回应遗漏问题：{', '.join(missed_questions)}。")
    if "order_tool_not_executed" in issues:
        parts.append("订单工具尚未执行，只能回复正在核实，不能直接下结论。")
    if "product_context_mismatch" in issues:
        parts.append("当前商品与问题品类冲突，先确认商品链接或截图。")
    return " ".join(parts)


def _is_refund_complaint_handoff(message: str, reply: str, state: dict) -> bool:
    if state.get("intent") != "complaint":
        return False
    if not has_order_identifier(state):
        return False
    if not any(
        cue in (message or "")
        for cue in (
            "\u9000\u6b3e",
            "\u9000\u94b1",
            "\u4e0d\u7ed9\u9000",
            "\u6295\u8bc9",
            "\u5e73\u53f0\u4ecb\u5165",
            "12315",
        )
    ):
        return False
    if any(
        cue in (reply or "")
        for cue in (
            "\u5b9e\u7269",
            "\u5916\u7bb1",
            "\u9762\u5355",
            "\u7167\u7247",
        )
    ):
        return False
    return "\u9000\u6b3e" in reply and any(
        cue in reply
        for cue in (
            "\u6838\u5bf9",
            "\u6838\u5b9e",
            "\u8ddf\u8fdb",
            "\u552e\u540e\u8bb0\u5f55",
            "\u5904\u7406\u8def\u5f84",
            "\u5904\u7406\u65b9\u5411",
        )
    )


def _contains_any(text: str, patterns) -> bool:
    lowered = (text or "").lower()
    return any(str(pattern).lower() in lowered for pattern in patterns)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _increment_metric(name: str) -> None:
    try:
        from app.services.metrics_service import get_metrics_service

        get_metrics_service().increment(name)
    except Exception:
        pass
