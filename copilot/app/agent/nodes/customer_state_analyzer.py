"""LLM-first customer emotion and concern analyzer."""

from __future__ import annotations

import json
import logging
import time

from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)

CONCERNS = {
    "wants_eta_certainty",
    "worries_package_lost",
    "worries_product_safety",
    "worries_material",
    "worries_refund_loss",
    "wants_compensation",
    "confused_about_installation",
    "angry_about_delay",
    "received_but_problem",
    "social_frustration",
    "smalltalk",
    "unknown",
}

LOGISTICS_CERTAINTY_TERMS = (
    "\u7269\u6d41", "\u5feb\u9012", "\u5230", "\u5230\u8d27", "\u9001\u5230",
    "\u660e\u5929", "\u4eca\u5929", "\u4e00\u5b9a", "\u4fdd\u8bc1", "\u80af\u5b9a",
    "eta", "delivery", "arrive",
)

SYSTEM_PROMPT = """你是客服 Agent 的客户状态分析器，只输出 JSON，不要输出客服回复。

你要根据用户当前消息、路由结果和上下文，判断客户情绪、真实顾虑、是否需要安抚/追问/边界说明/人工介入。

特别注意：
- 当前消息优先于历史上下文。即使上一轮用户不满，如果当前消息只是普通打招呼，也应归类为 smalltalk。
- 打招呼、闲聊、讽刺、辱骂、吐槽客服能力，如果没有明确订单/物流/商品/售后事实请求，应归类为 customer_concern=social_frustration 或 smalltalk。
- 投诉平台、维权、差评、12315 等明确升级诉求，归类为 angry_about_delay，并 needs_human_review=true。
- 物流到达“能不能保证/一定到/今天明天到”归类 wants_eta_certainty，需要 boundary_setting。
- 商品材质/实木/填充/安全担忧归类 worries_material 或 worries_product_safety。

输出 JSON:
{
  "customer_emotion": "neutral | anxious | angry | frustrated | polite | confused",
  "urgency_level": "low | medium | high",
  "customer_concern": "wants_eta_certainty | worries_package_lost | worries_product_safety | worries_material | worries_refund_loss | wants_compensation | confused_about_installation | angry_about_delay | received_but_problem | social_frustration | smalltalk | unknown",
  "expectation_type": "normal_answer | certainty_request | escalation | tone_repair | greeting | clarification",
  "trust_level": "normal | low | high",
  "needs_empathy": true,
  "needs_clarification": false,
  "needs_reassurance": true,
  "needs_boundary_setting": false,
  "needs_human_review": false
}
"""


def customer_state_analyzer(state: dict) -> dict:
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", ""))
    risk_level = state.get("risk_level", "low")

    customer_state = _llm_analyze(state)
    source = "llm"
    if not customer_state:
        customer_state = _fallback_analyze(state)
        source = "rule_fallback"

    if risk_level in ("high", "critical"):
        customer_state["urgency_level"] = "high"
        customer_state["needs_human_review"] = True
    if state.get("requires_human_review"):
        customer_state["needs_human_review"] = True

    emotion = customer_state.get("customer_emotion", "neutral")
    urgency = customer_state.get("urgency_level", "low")
    concern = customer_state.get("customer_concern", "unknown")
    if (
        concern == "wants_eta_certainty"
        and state.get("intent", "") in ("product_question", "product_consult")
        and not any(term in msg.lower() for term in LOGISTICS_CERTAINTY_TERMS)
    ):
        concern = "unknown"
        customer_state["customer_concern"] = concern
        customer_state["needs_boundary_setting"] = False
    needs_human_review = bool(customer_state.get("needs_human_review", False))

    trace = {
        "node": "customer_state_analyzer",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": False,
        "source": source,
        "summary": f"emotion={emotion}, urgency={urgency}, concern={concern}",
    }
    return {
        "customer_state": customer_state,
        "customer_emotion": emotion,
        "customer_urgency": urgency,
        "customer_concern": concern,
        "needs_human_review": needs_human_review,
        "requires_human_review": bool(state.get("requires_human_review", False) or needs_human_review),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _llm_analyze(state: dict) -> dict:
    client = get_llm_client()
    if not client.api_key:
        return {}
    payload = {
        "customer_message": state.get("normalized_message", state.get("customer_message", "")),
        "intent": state.get("intent", ""),
        "router_decision": state.get("router_decision", {}),
        "risk_level": state.get("risk_level", "low"),
        "slots": state.get("slots", {}),
        "conversation_context": state.get("conversation_context_summary", {}),
    }
    try:
        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=350,
            response_format={"type": "json_object"},
        )
        return _sanitize(json.loads(response.choices[0].message.content))
    except Exception as exc:
        logger.warning("customer_state_analyzer LLM failed: %s", exc)
        return {}


def _sanitize(data: dict) -> dict:
    concern = str(data.get("customer_concern") or "unknown")
    if concern not in CONCERNS:
        concern = "unknown"
    urgency = str(data.get("urgency_level") or "low")
    if urgency not in ("low", "medium", "high"):
        urgency = "low"
    return {
        "customer_emotion": str(data.get("customer_emotion") or "neutral"),
        "urgency_level": urgency,
        "customer_concern": concern,
        "expectation_type": str(data.get("expectation_type") or "normal_answer"),
        "trust_level": str(data.get("trust_level") or "normal"),
        "needs_empathy": bool(data.get("needs_empathy", False)),
        "needs_clarification": bool(data.get("needs_clarification", False)),
        "needs_reassurance": bool(data.get("needs_reassurance", False)),
        "needs_boundary_setting": bool(data.get("needs_boundary_setting", False)),
        "needs_human_review": bool(data.get("needs_human_review", False)),
    }


def _fallback_analyze(state: dict) -> dict:
    """Minimal non-LLM fallback. It is intentionally conservative."""
    intent = state.get("intent", "")
    risk_level = state.get("risk_level", "low")
    msg = state.get("normalized_message", state.get("customer_message", ""))
    concern = "unknown"
    if intent == "general" and any(p in msg for p in ("你", "你们", "客服")):
        concern = "social_frustration"
    elif intent == "delivery_not_received":
        concern = "worries_package_lost"
    elif intent == "complaint" or risk_level in ("high", "critical"):
        concern = "angry_about_delay"
    elif intent == "product_question":
        concern = "worries_material"
    elif intent in ("logistics_eta", "logistics_trace"):
        concern = "wants_eta_certainty"
    return {
        "customer_emotion": "frustrated" if concern == "social_frustration" else "neutral",
        "urgency_level": "high" if risk_level in ("high", "critical") else "low",
        "customer_concern": concern,
        "expectation_type": "normal_answer",
        "trust_level": "normal",
        "needs_empathy": concern in ("worries_package_lost", "angry_about_delay"),
        "needs_clarification": False,
        "needs_reassurance": concern in ("worries_package_lost", "wants_eta_certainty"),
        "needs_boundary_setting": concern == "wants_eta_certainty",
        "needs_human_review": risk_level in ("high", "critical") or intent == "delivery_not_received",
    }
