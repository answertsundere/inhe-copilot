"""LLM-powered intent and tool router."""

from __future__ import annotations

import json
import logging
import re
import time

from app.llm.client import get_llm_client
from app.services.logistics_fast_path import get_explicit_logistics_identifier

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {
    "logistics_eta",
    "logistics_trace",
    "product_question",
    "aftersales",
    "invoice",
    "price_protection",
    "price_promotion",
    "promotion_query",
    "gift_missing",
    "stock_query",
    "child_safety",
    "competitor_compare",
    "odor_question",
    "cleaning_care",
    "material_safety",
    "image_attachment",
    "installation",
    "complaint",
    "delivery_not_received",
    "needs_clarification",
    "general",
}
ALLOWED_IDENTIFIER_TYPES = {
    "internal_order_id", "platform_trade_id", "platform_order_id",
    "tracking_no", "unknown_identifier", "none",
    "order_id", "possible_numeric_id",
}
ALLOWED_TOOLS = {"jst_live_query", "rag_retrieve", "none"}

IMAGE_MARKER_RE = re.compile(r"\[\s*\u56fe\u7247\s*\d*\s*\]")
TEXT_PRODUCT_QUESTION_TERMS = (
    "\u5417", "\u5462", "\u600e\u4e48", "\u5982\u4f55", "\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd", "\u662f\u4e0d\u662f", "\u6709\u6ca1\u6709",
    "\u4f1a\u4e0d\u4f1a", "\u53ef\u62c6", "\u62c6\u5378", "\u5b89\u88c5",
    "\u7ec4\u88c5", "\u6750\u8d28", "\u627f\u91cd", "\u5c3a\u5bf8",
    "\u6e05\u6d17", "\u9632\u6f6e",
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


def _has_text_product_question(state: dict) -> bool:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    text = IMAGE_MARKER_RE.sub("", msg).strip()
    return bool(text and any(term in text for term in TEXT_PRODUCT_QUESTION_TERMS))


SYSTEM_PROMPT = """你是客服 Agent 的语义路由器，只输出 JSON，不要输出客服回复。

你需要判断客户意图，并选择下一步工具。你不能编造订单状态、物流状态、商品事实。
如果输入里包含最近会话上下文，必须结合上下文理解“最后一句客户消息”，不要只看最后一句字面。

输出 JSON schema:
{
  "intent": "logistics_eta | logistics_trace | product_question | aftersales | installation | complaint | delivery_not_received | general",
  "confidence": 0.0,
  "identifier_type": "internal_order_id | platform_trade_id | platform_order_id | tracking_no | unknown_identifier | none",
  "identifier_value": "",
  "product_name": "",
  "question_type": "eta | trace | material | washing | age | size | install | usage | policy | unknown",
  "need_tool": true,
  "tool_name": "jst_live_query | rag_retrieve | none",
  "reason": "简短说明"
}

硬规则：
- 18-19 位连续数字 + 快递/物流/到哪/什么时候到/几天到/发货/签收：intent=logistics_eta 或 logistics_trace，identifier_type=platform_trade_id，tool_name=jst_live_query。
- SF/JT/JD/YT/ZTO/EMS 等快递单号 + 到哪/物流/签收：intent=logistics_trace，identifier_type=tracking_no，tool_name=jst_live_query。
- 客户问商品材质、尺寸、能不能洗、适合多大、怎么使用、功能、感应、开关：intent=product_question，tool_name=rag_retrieve。
- 客户问安装、组装、说明书、螺丝、怎么装、装不上：intent=installation，tool_name=rag_retrieve。
- 客户说退货、退款、换货、不想要了、售后、破损、坏了、少件、发错、质量问题、赔偿：intent=aftersales，tool_name=rag_retrieve。
- 如果上下文提到“感应灯”，最后一句问“怎么让它自动感应/为什么只能手动按”：这是商品功能/使用咨询，intent=product_question，tool_name=rag_retrieve。
- 投诉、平台介入、12315、差评威胁：intent=complaint。
- 签收了但没收到：intent=delivery_not_received。
- 只是打招呼、闲聊、辱骂但没有订单/物流/商品/售后事实请求：intent=general，tool_name=none。
- 你只负责路由，不生成最终答复。
"""


def llm_intent_router(state: dict) -> dict:
    t0 = time.time()
    fallback_intent = state.get("intent", "general")
    slots = state.get("slots", {}) or {}
    msg = state.get("normalized_message", state.get("customer_message", ""))

    # 规则已判定为需要澄清的模糊问题，LLM 不再覆盖
    if fallback_intent == "needs_clarification":
        return _result(
            state,
            _fallback_decision(state, "rule_needs_clarification_sticky"),
            t0,
            "rule_sticky",
            "规则判定问题描述过于模糊，保持 needs_clarification",
        )

    explicit_identifier = get_explicit_logistics_identifier(state)
    if explicit_identifier:
        decision = _fallback_decision(state, "explicit_logistics_identifier_fast_path")
        decision.update({
            "intent": _canonical_intent(fallback_intent),
            "confidence": 1.0,
            "identifier_type": explicit_identifier["identifier_type"],
            "identifier_value": explicit_identifier["identifier_value"],
            "need_tool": True,
            "tool_name": "jst_live_query",
            "reason": "explicit_logistics_identifier_fast_path",
        })
        return _result(
            state,
            decision,
            t0,
            "explicit_logistics_identifier_fast_path",
            "explicit logistics identifier; skip intent LLM",
        )

    llm_client = get_llm_client()
    if not llm_client.api_key:
        _metrics_increment("llm_unconfigured_count")
        decision = _fallback_decision(state, "llm_unconfigured")
        return _result(state, decision, t0, "rule_fallback", "LLM 未配置，保留规则意图")

    user_payload = {
        "customer_message": msg,
        "rule_detected_intent": fallback_intent,
        "slots": {
            "order_id": slots.get("order_id", ""),
            "tracking_no": slots.get("tracking_no", ""),
            "possible_numeric_id": slots.get("possible_numeric_id", ""),
            "identifier_type": slots.get("identifier_type", ""),
            "product_name": slots.get("product_name", ""),
            "sku_name": slots.get("sku_name", ""),
            "sku_code": slots.get("sku_code", ""),
        },
    }

    try:
        _metrics_increment("llm_call_count")
        response = llm_client.chat_completion(
            model_alias="fast_model",
            node_name="llm_intent_router",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        decision = _sanitize_decision(json.loads(raw), state)
        _metrics_increment("llm_success_count")
        return _result(state, decision, t0, "llm", decision.get("reason", "LLM 路由"))
    except Exception as exc:
        _metrics_increment("llm_failure_count")
        logger.warning("LLM intent router failed, falling back to rule intent: %s", exc)
        decision = _fallback_decision(state, f"llm_router_error: {exc}")
        return _result(state, decision, t0, "rule_fallback", "LLM 路由失败，保留规则意图")


def _fallback_decision(state: dict, reason: str) -> dict:
    slots = state.get("slots", {}) or {}
    intent = state.get("intent", "general")
    tool_name = "none"
    need_tool = False
    if intent in ("logistics_eta", "shipping", "logistics", "delivery_not_received"):
        tool_name = "jst_live_query" if (
            slots.get("order_id")
            or slots.get("tracking_no")
            or slots.get("possible_numeric_id")
            or slots.get("platform_trade_id")
        ) else "none"
        need_tool = tool_name != "none"
    elif intent in (
        "invoice", "price_protection", "price_promotion", "promotion_query",
        "gift_missing", "stock_query", "child_safety", "competitor_compare", "odor_question",
        "cleaning_care", "material_safety", "image_attachment",
    ):
        tool_name = "none"
        need_tool = False
    elif intent in ("product_question", "product_consult", "installation"):
        tool_name = "rag_retrieve"
        need_tool = True
    return {
        "intent": _canonical_intent(intent),
        "confidence": 0.0,
        "identifier_type": slots.get("identifier_type") or "none",
        "identifier_value": (
            slots.get("platform_trade_id")
            or slots.get("order_id")
            or slots.get("tracking_no")
            or slots.get("possible_numeric_id")
            or ""
        ),
        "product_name": slots.get("product_name", ""),
        "question_type": "unknown",
        "need_tool": need_tool,
        "tool_name": tool_name,
        "reason": reason,
    }


def _sanitize_decision(decision: dict, state: dict) -> dict:
    slots = state.get("slots", {}) or {}
    rule_intent = state.get("intent", "general")
    llm_intent = _canonical_intent(str(decision.get("intent", "") or rule_intent))
    has_product_text_question = _has_product_context(state) and _has_text_product_question(state)
    if llm_intent == "image_attachment" and has_product_text_question:
        llm_intent = "product_question"

    # Protect high-confidence rule-detected intents from LLM override
    # When slots have order identifier and message has logistics semantics,
    # the rule-based intent (logistics_eta/aftersales/complaint/delivery_not_received)
    # must not be overridden by LLM to product_question/general
    _PROTECTED_INTENTS = {"logistics_eta", "logistics_trace", "delivery_not_received",
                          "complaint", "aftersales", "invoice", "price_protection", "price_promotion",
                          "promotion_query", "gift_missing", "stock_query", "child_safety",
                          "competitor_compare", "odor_question", "cleaning_care", "material_safety",
                          "image_attachment",
                          "installation"}
    _DOWNGRADE_TARGETS = {"product_question", "product_consult", "general"}
    if rule_intent in (
        "invoice", "price_protection", "price_promotion", "promotion_query", "gift_missing",
        "stock_query", "child_safety", "competitor_compare", "odor_question",
        "cleaning_care", "material_safety", "image_attachment",
    ) and llm_intent in ("aftersales", "product_question", "product_consult", "general"):
        if not (rule_intent == "image_attachment" and has_product_text_question):
            llm_intent = rule_intent

    if (
        rule_intent in _PROTECTED_INTENTS
        and llm_intent in _DOWNGRADE_TARGETS
        and not (rule_intent == "image_attachment" and has_product_text_question)
    ):
        # Check if there's an order identifier supporting the rule intent
        has_identifier = bool(
            slots.get("order_id") or state.get("order_id", "")
            or slots.get("platform_trade_id")
            or slots.get("tracking_no") or state.get("tracking_no", "")
            or slots.get("possible_numeric_id")
        )
        msg = state.get("normalized_message", state.get("customer_message", ""))
        has_logistics_terms = any(t in msg for t in (
            "快递", "物流", "运单", "发货", "到货", "配送", "签收", "到哪",
            "什么时候到", "几天到", "多久到", "什么时候发货",
        ))
        has_aftersales_terms = any(t in msg for t in (
            "退货", "退款", "换货", "不想要", "售后", "破损", "坏了",
        ))
        has_complaint_terms = any(t in msg for t in (
            "投诉", "12315", "媒体", "曝光", "差评", "起诉",
        ))

        # Keep rule intent if supported by evidence
        if (rule_intent in ("logistics_eta", "logistics_trace", "delivery_not_received")
                and (has_identifier or has_logistics_terms)):
            llm_intent = rule_intent
        elif rule_intent == "aftersales" and has_aftersales_terms:
            llm_intent = rule_intent
        elif rule_intent == "complaint" and has_complaint_terms:
            llm_intent = rule_intent
        elif rule_intent == "installation" and has_identifier:
            llm_intent = rule_intent

    intent = llm_intent

    try:
        confidence = float(decision.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    identifier_type = str(decision.get("identifier_type", "") or slots.get("identifier_type") or "none")
    if identifier_type not in ALLOWED_IDENTIFIER_TYPES:
        identifier_type = slots.get("identifier_type") or "none"
    identifier_value = str(decision.get("identifier_value", "") or "")
    if not identifier_value:
        identifier_value = (
            slots.get("platform_trade_id")
            or slots.get("order_id")
            or slots.get("tracking_no")
            or slots.get("possible_numeric_id")
            or ""
        )

    tool_name = str(decision.get("tool_name", "") or "none")
    if tool_name not in ALLOWED_TOOLS:
        tool_name = "none"
    if intent == "product_question" and tool_name == "none":
        tool_name = "rag_retrieve"
    elif intent == "installation" and tool_name == "none":
        tool_name = "rag_retrieve"

    need_tool = bool(decision.get("need_tool", False))
    if tool_name != "none":
        need_tool = True

    return {
        "intent": intent,
        "confidence": confidence,
        "identifier_type": identifier_type,
        "identifier_value": identifier_value,
        "product_name": str(decision.get("product_name", "") or slots.get("product_name", "")),
        "question_type": str(decision.get("question_type", "") or "unknown"),
        "need_tool": need_tool,
        "tool_name": tool_name,
        "reason": str(decision.get("reason", "") or "LLM 路由"),
    }


def _canonical_intent(intent: str) -> str:
    if intent in ("shipping", "logistics"):
        return "logistics_eta"
    if intent in ("product_consult",):
        return "product_question"
    if intent == "delivery_not_received":
        return "delivery_not_received"
    if intent == "price_promotion":
        return "price_protection"
    return intent if intent in ALLOWED_INTENTS else "general"


def _result(state: dict, decision: dict, t0: float, source: str, summary: str) -> dict:
    trace = {
        "node": "llm_intent_router",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": False,
        "router_source": source,
        "router_confidence": decision.get("confidence", 0),
        "selected_tool": decision.get("tool_name", "none"),
        "summary": summary,
    }
    intent = decision.get("intent", state.get("intent", "general"))
    skill = "logistics" if intent in ("logistics_eta", "logistics_trace") else (
            "product" if intent in (
                "product_question", "cleaning_care", "material_safety", "image_attachment",
                "child_safety", "competitor_compare", "odor_question",
            ) else (
            "aftersales" if intent in ("invoice", "price_protection", "promotion_query", "gift_missing") else intent
        )
    )
    return {
        "intent": intent,
        "skill": skill,
        "matched_product_name": decision.get("product_name") or state.get("matched_product_name", ""),
        "router_decision": decision,
        "router_source": source,
        "router_confidence": decision.get("confidence", 0),
        "router_reason": decision.get("reason", ""),
        "selected_tool": decision.get("tool_name", "none"),
        "identifier_type": decision.get("identifier_type", "none"),
        "identifier_value": decision.get("identifier_value", ""),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _metrics_increment(key: str) -> None:
    try:
        from app.services.metrics_service import get_metrics_service
        get_metrics_service().increment(key)
    except Exception:
        pass
