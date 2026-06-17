"""Hard validation layer for LLM routing decisions."""

from __future__ import annotations

import re
import time

NUMERIC_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])(\d{12,20})(?![A-Za-z0-9])")
LOGISTICS_TERMS = (
    "快递", "物流", "运单", "单号", "发货", "到货", "配送", "签收",
    "什么时候到", "大概什么时候到", "几天到", "多久到", "到哪", "到哪里",
    "\u5feb\u9012", "\u7269\u6d41", "\u8fd0\u5355", "\u5355\u53f7",
    "\u53d1\u8d27", "\u5230\u8d27", "\u914d\u9001", "\u7b7e\u6536",
    "\u4ec0\u4e48\u65f6\u5019\u5230", "\u51e0\u5929\u5230",
    "\u591a\u4e45\u5230", "\u5230\u54ea", "\u5230\u54ea\u91cc",
)
PRODUCT_FACT_TERMS = (
    "材质", "尺寸", "承重", "能洗", "清洗", "机洗", "适合多大", "适合几岁",
    "填充", "防水", "实木", "感应灯", "感应", "自动感应", "手动摁",
    "手动按", "怎么用", "怎么使用", "怎么让", "开关", "功能",
)
PRODUCT_FOLLOWUP_TERMS = (
    "这个", "这款", "它", "商品", "宝贝", "款", "基础款", "升级款", "升级版",
    "差什么", "差别", "差异", "区别", "对比", "哪个好", "怎么选", "能买吗",
    "能用吗", "好用吗", "适合吗", "靠谱吗",
)
INSTALLATION_TERMS = (
    "安装", "怎么装", "装不上", "螺丝", "配件", "说明书",
    "安装视频", "教程", "步骤", "固定", "组装", "拼接", "搭建",
)
AFTERSALES_TERMS = (
    "退货", "退款", "换货", "不想要", "七天无理由", "运费",
    "退回", "补发", "少件", "发错", "破损", "坏了", "质量问题",
    "瑕疵", "售后", "退换", "赔偿",
    "能补吗", "补一个", "补一件", "能补发", "给补一个",
)
COMPLAINT_TERMS = (
    "投诉", "差评", "平台介入", "12315", "律师", "曝光", "赔偿",
    "举报", "告你", "起诉", "媒体", "工商局", "消协",
)
BUSINESS_TERMS = LOGISTICS_TERMS + PRODUCT_FACT_TERMS + INSTALLATION_TERMS + AFTERSALES_TERMS + COMPLAINT_TERMS + (
    "订单", "售后", "退款", "退货", "换货", "赔", "投诉", "平台", "质量", "破损",
)
SIGNED_NOT_RECEIVED_TERMS = (
    "显示签收", "签收但没收到", "签收但未收到", "签收了但没收到",
    "已签收但", "没收到货", "没有收到", "没拿到", "没见到",
)
GIFT_TERMS = ("赠品", "礼品", "赠送")
GIFT_MISSING_TERMS = ("没有", "没收到", "未收到", "漏发", "少发", "没给")
NON_BUSINESS_ADDRESS_TERMS = ("你", "你们", "客服")
PROTECTED_PRODUCT_POLICY_INTENTS = {
    "gift_missing",
    "cleaning_care",
    "material_safety",
    "child_safety",
    "competitor_compare",
    "odor_question",
    "image_attachment",
    "promotion_query",
    "stock_query",
    "invoice",
    "price_protection",
    "price_promotion",
}

IMAGE_MARKER_RE = re.compile(r"\[\s*\u56fe\u7247\s*\d*\s*\]")
TEXT_PRODUCT_QUESTION_TERMS = (
    "\u5417", "\u5462", "\u600e\u4e48", "\u5982\u4f55", "\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd", "\u662f\u4e0d\u662f", "\u6709\u6ca1\u6709",
    "\u4f1a\u4e0d\u4f1a", "\u53ef\u62c6", "\u62c6\u5378", "\u5b89\u88c5",
    "\u7ec4\u88c5", "\u6750\u8d28", "\u627f\u91cd", "\u5c3a\u5bf8",
    "\u6e05\u6d17", "\u9632\u6f6e",
)
TEXT_INSTALLATION_TERMS = (
    "\u5b89\u88c5", "\u600e\u4e48\u88c5", "\u7ec4\u88c5", "\u88c5\u4e0d\u4e0a",
    "\u8bf4\u660e\u4e66", "\u5b89\u88c5\u89c6\u9891", "\u6559\u7a0b",
)


def _has_product_context(state: dict) -> bool:
    ctx = state.get("copilot_context", {}) or {}
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots", {}) or {}
    return bool(
        state.get("matched_product_name")
        or state.get("product_candidates")
        or ctx.get("product_name")
        or ctx.get("product_candidates")
        or slots.get("sku_code")
        or slots.get("product_name")
        or identity.get("status") == "resolved"
        or identity.get("matched_product_name")
        or identity.get("sku_id")
    )


def _has_text_product_question(msg: str) -> bool:
    text = IMAGE_MARKER_RE.sub("", msg or "").strip()
    if not text:
        return False
    return any(term in text for term in TEXT_PRODUCT_QUESTION_TERMS)


def _is_text_installation_question(msg: str) -> bool:
    text = IMAGE_MARKER_RE.sub("", msg or "").strip()
    return bool(text and any(term in text for term in TEXT_INSTALLATION_TERMS))


def _looks_like_product_followup(msg: str) -> bool:
    if not msg:
        return False
    if any(term in msg for term in PRODUCT_FACT_TERMS + INSTALLATION_TERMS + PRODUCT_FOLLOWUP_TERMS):
        return True
    question_markers = ("吗", "么", "呢", "怎么", "如何", "是不是", "有没有", "能不能", "可以不", "可以吗")
    return len(msg) <= 30 and any(marker in msg for marker in question_markers)


def router_validation(state: dict) -> dict:
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    slots = state.get("slots", {}) or {}
    ctx = state.get("conversation_context", {}) or {}
    decision = dict(state.get("router_decision", {}) or {})
    intent = state.get("intent", "general")
    source = state.get("router_source", "rule_fallback")
    reason = state.get("router_reason", "")
    selected_tool = state.get("selected_tool", "none")
    overrides = []
    order_operation = ""

    numeric_match = NUMERIC_IDENTIFIER_RE.search(msg)
    has_logistics_terms = any(term in msg for term in LOGISTICS_TERMS)
    has_product_terms = any(term in msg for term in PRODUCT_FACT_TERMS)
    has_product_context = _has_product_context(state)
    has_text_product_question = has_product_context and _has_text_product_question(msg)
    looks_like_product_followup = has_product_context and _looks_like_product_followup(msg)
    has_installation_terms = any(term in msg for term in INSTALLATION_TERMS)
    has_aftersales_terms = any(term in msg for term in AFTERSALES_TERMS)
    has_complaint_terms = any(term in msg for term in COMPLAINT_TERMS)
    has_intercept_operation = any(term in msg for term in ("拦截", "改地址", "收货地址", "改收货", "拒收"))
    signed_not_received = any(term in msg for term in SIGNED_NOT_RECEIVED_TERMS)
    has_gift_missing_terms = (
        any(term in msg for term in GIFT_TERMS)
        and any(term in msg for term in GIFT_MISSING_TERMS)
    )
    looks_like_non_business_address = (
        any(p in msg for p in NON_BUSINESS_ADDRESS_TERMS)
        and not any(term in msg for term in BUSINESS_TERMS)
        and not numeric_match
    )

    # Check for order identifiers in slots/state (API-provided or extracted from message)
    has_slot_order_id = bool(
        slots.get("order_id") or state.get("order_id", "")
    )
    has_slot_tracking_no = bool(
        slots.get("tracking_no") or state.get("tracking_no", "")
    )
    has_slot_platform_trade_id = bool(slots.get("platform_trade_id"))
    has_slot_platform_order_id = bool(slots.get("platform_order_id"))
    has_any_identifier = bool(
        has_slot_order_id or has_slot_tracking_no or has_slot_platform_trade_id
        or has_slot_platform_order_id or slots.get("possible_numeric_id") or numeric_match
    )

    slot_identifier_type = slots.get("identifier_type", "")
    is_context_numeric_followup = bool(
        numeric_match
        and slot_identifier_type == "unknown_identifier"
        and (
            "order_id" in ctx.get("last_requested_slots", [])
            or "tracking_no" in ctx.get("last_requested_slots", [])
            or ctx.get("active_issue") in ("delivery_not_received", "logistics_eta", "logistics_trace")
        )
    )

    # 规则已判定为需要澄清的模糊问题，不再被 product follow-up 逻辑覆盖
    if intent == "needs_clarification":
        pass

    elif looks_like_non_business_address and intent != "image_attachment":
        if intent != "general":
            overrides.append(f"intent {intent} -> general")
        intent = "general"
        selected_tool = "none"
        decision.update({"intent": intent, "need_tool": False, "tool_name": selected_tool})

    elif is_context_numeric_followup:
        previous_issue = ctx.get("active_issue", "")
        intent = "delivery_not_received" if previous_issue == "delivery_not_received" else "logistics_eta"
        selected_tool = "jst_live_query"
        decision.update({
            "intent": intent,
            "need_tool": True,
            "tool_name": selected_tool,
            "identifier_type": "unknown_identifier",
            "identifier_value": slots.get("possible_numeric_id") or numeric_match.group(1),
        })
        overrides.append("numeric follow-up -> previous logistics issue")

    elif signed_not_received:
        if intent != "delivery_not_received":
            overrides.append(f"intent {intent} -> delivery_not_received")
        intent = "delivery_not_received"
        selected_tool = "none"
        decision.update({"intent": intent, "need_tool": False, "tool_name": selected_tool})

    elif has_gift_missing_terms:
        if intent != "gift_missing":
            overrides.append(f"intent {intent} -> gift_missing")
        intent = "gift_missing"
        selected_tool = "rag_retrieve"
        decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})

    elif intent == "image_attachment" and has_text_product_question:
        intent = "installation" if _is_text_installation_question(msg) else "product_question"
        selected_tool = "product_resolver_tool" if intent == "installation" else "rag_retrieve"
        decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})
        overrides.append(f"image attachment with product text -> {intent}")

    # 订单操作（拦截/改地址/拒收）且有订单标识：优先走物流查询，不降级为通用售后
    elif has_intercept_operation and has_any_identifier:
        order_operation = (
            "intercept" if "拦截" in msg
            else ("address_change" if any(t in msg for t in ("改地址", "收货地址", "改收货")) else "reject")
        )
        intent = "logistics_eta"
        selected_tool = "jst_live_query"
        decision.update({
            "intent": intent, "need_tool": True, "tool_name": selected_tool,
            "order_operation": order_operation,
        })
        overrides.append(f"order op -> logistics_eta ({order_operation})")

    # Numeric in message + logistics terms → logistics
    elif numeric_match and has_logistics_terms:
        if intent not in ("logistics_eta", "logistics_trace"):
            overrides.append(f"intent {intent} -> logistics_eta")
        intent = "logistics_eta"
        selected_tool = "jst_live_query"
        final_id_type = slot_identifier_type or "possible_numeric_id"
        decision.update({
            "intent": intent,
            "need_tool": True,
            "tool_name": selected_tool,
            "identifier_type": final_id_type,
            "identifier_value": (
                slots.get("platform_trade_id")
                or slots.get("order_id")
                or slots.get("tracking_no")
                or slots.get("possible_numeric_id")
                or numeric_match.group(1)
            ),
        })

    # NEW: Slot/state has order identifier + logistics terms → logistics
    # This catches cases where order_id comes from API (not in message text)
    elif has_any_identifier and has_logistics_terms and intent not in ("logistics_eta", "logistics_trace", "delivery_not_received", "aftersales", "complaint"):
        overrides.append(f"intent {intent} -> logistics_eta (slot identifier + logistics terms)")
        intent = "logistics_eta"
        selected_tool = "jst_live_query"
        final_id_type = slot_identifier_type or "internal_order_id"
        decision.update({
            "intent": intent,
            "need_tool": True,
            "tool_name": selected_tool,
            "identifier_type": final_id_type,
            "identifier_value": (
                slots.get("platform_trade_id")
                or slots.get("order_id")
                or state.get("order_id", "")
                or slots.get("tracking_no")
                or state.get("tracking_no", "")
                or slots.get("possible_numeric_id")
                or ""
            ),
        })

    # 高优先级意图保护：投诉 > 售后 > 安装
    elif has_complaint_terms:
        if intent not in ("complaint", "high_risk"):
            overrides.append(f"intent {intent} -> complaint")
        intent = "complaint"
        selected_tool = "sop_lookup_tool"
        decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})

    elif has_aftersales_terms and intent != "image_attachment":
        if intent != "aftersales":
            overrides.append(f"intent {intent} -> aftersales")
        intent = "aftersales"
        selected_tool = "rag_retrieve"
        decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})

    elif has_installation_terms:
        if intent != "installation":
            overrides.append(f"intent {intent} -> installation")
        intent = "installation"
        selected_tool = "product_resolver_tool"
        decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})

    elif has_product_terms and intent not in (
        "logistics_eta", "logistics_trace", "aftersales", "complaint", "installation",
        *PROTECTED_PRODUCT_POLICY_INTENTS,
    ):
        if numeric_match:
            pass
        else:
            if intent != "product_question":
                overrides.append(f"intent {intent} -> product_question")
            intent = "product_question"
            selected_tool = "rag_retrieve"
            decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})

    elif looks_like_product_followup and intent not in (
        "logistics_eta", "logistics_trace", "delivery_not_received",
        "aftersales", "complaint", "installation", "image_attachment",
        *PROTECTED_PRODUCT_POLICY_INTENTS,
    ):
        if not numeric_match:
            if intent != "product_question":
                overrides.append(f"intent {intent} -> product_question (product context follow-up)")
            intent = "product_question"
            selected_tool = "rag_retrieve"
            decision.update({"intent": intent, "need_tool": True, "tool_name": selected_tool})

    if overrides:
        source = "validation_override"
        reason = "; ".join(overrides)

    trace = {
        "node": "router_validation",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": False,
        "router_source": source,
        "selected_tool": selected_tool,
        "summary": reason or "router decision accepted",
    }

    skill = "logistics" if intent in ("logistics_eta", "logistics_trace", "delivery_not_received") else (
        "product" if intent in ("product_question", *PROTECTED_PRODUCT_POLICY_INTENTS) else intent
    )
    return {
        "intent": intent,
        "skill": skill,
        "router_decision": decision,
        "router_source": source,
        "router_reason": reason,
        "selected_tool": selected_tool,
        "order_operation": order_operation,
        "identifier_type": decision.get("identifier_type", slot_identifier_type or state.get("identifier_type", "")),
        "identifier_value": decision.get("identifier_value", state.get("identifier_value", "")),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
