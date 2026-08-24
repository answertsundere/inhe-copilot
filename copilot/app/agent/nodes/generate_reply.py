"""
generate_reply 节点 - 非物流场景回复生成。

商品 FAQ / 商品参数使用 Grounded Generation：有证据时规则生成，
证据不足时追问，只有政策和 SOP 类回复允许 LLM 在严格证据约束下润色。
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from app import config
from app.llm.client import get_llm_client
from app.llm.prompts import build_system_prompt, build_user_message
from app.services.fact_type_service import fact_type_matches, infer_evidence_fact_type, is_strict_fact_type
from app.services.admitted_answer_context_service import is_placeholder_evidence_text

logger = logging.getLogger(__name__)

PRODUCT_INTENTS = {"product_question", "product_consult", "installation"}
POLICY_LLM_MODES = {"policy_grounded_answer", "policy_answer", "policy", "aftersales_policy"}
SOP_LLM_MODES = {"sop_human_review_answer", "human_review", "installation_guide"}
RULE_ONLY_INTENTS = {
    "aftersales",
    "invoice",
    "price_protection",
    "price_promotion",
    "promotion_query",
    "stock_query",
    "gift_missing",
    "child_safety",
    "competitor_compare",
    "odor_question",
    "cleaning_care",
    "material_safety",
    "image_attachment",
}

CLARIFICATION_REPLY = (
    "亲亲，不同款式可能不一样，我这边需要结合具体商品或 SKU 来确认。"
    "麻烦您发一下商品链接、截图、订单号或具体款式，我帮您核实准确参数～"
)

VAGUE_CLARIFICATION_REPLY = (
    "亲，我这边还需要看一下您说的是哪里有问题～"
    "您可以把照片或具体情况发我一下，比如是安装、配件、破损还是使用时不稳，我帮您一起看。"
)


IMAGE_MARKER_RE = re.compile(r"\[\s*\u56fe\u7247\s*\d*\s*\]")
TEXT_PRODUCT_QUESTION_TERMS = (
    "\u5417", "\u5462", "\u600e\u4e48", "\u5982\u4f55", "\u53ef\u4ee5",
    "\u80fd\u4e0d\u80fd", "\u662f\u4e0d\u662f", "\u6709\u6ca1\u6709",
    "\u4f1a\u4e0d\u4f1a", "\u53ef\u62c6", "\u62c6\u5378", "\u5b89\u88c5",
    "\u7ec4\u88c5", "\u6750\u8d28", "\u627f\u91cd", "\u5c3a\u5bf8",
    "\u6e05\u6d17", "\u9632\u6f6e",
)

PRODUCT_FIRST_SOURCE_PRIORITY = [
    "product_structured_facts",
    "product_media_assets",
    "product_scoped_chunks",
    "activity_policy_rules",
    "generic_fallback_rules",
]

CONCRETE_PRODUCT_FACT_TYPES = {
    "material",
    "dimensions",
    "space_fit",
    "placement_scene",
    "load_capacity",
    "gross_weight",
    "accessories",
    "accessory_availability",
    "installation",
    "certification_report",
    "age_range",
    "detachable",
}


def _has_product_context(state: dict) -> bool:
    ctx = state.get("copilot_context", {}) or {}
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots", {}) or {}
    return bool(
        state.get("matched_product_name")
        or state.get("product_candidates")
        or state.get("product_name")
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


def _has_deliverable_media_assets(state: dict) -> bool:
    """Return True if the resolved product context pack has auto-sendable media."""
    pack = state.get("product_context_pack") or {}
    for asset in pack.get("recommended_assets") or []:
        if not isinstance(asset, dict):
            continue
        if not (asset.get("asset_url") or asset.get("url")):
            continue
        level = str(asset.get("auto_send_level") or "auto").lower()
        if level == "auto":
            return True
    for asset in pack.get("media_assets") or []:
        if not isinstance(asset, dict):
            continue
        if not (asset.get("asset_url") or asset.get("url")):
            continue
        level = str(asset.get("auto_send_level") or "auto").lower()
        if level == "auto":
            return True
    return False


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


def _is_certification_report_query(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u7532\u919b",
        "\u68c0\u6d4b\u62a5\u544a",
        "\u68c0\u67e5\u62a5\u544a",
        "\u8d28\u68c0\u62a5\u544a",
        "\u68c0\u9a8c\u62a5\u544a",
        "\u5408\u683c\u8bc1",
        "\u73af\u4fdd\u8bc1\u4e66",
        "\u8ba4\u8bc1",
        "\u8bc1\u4e66",
    ))


def _is_material_detail_query(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u6750\u8d28",
        "\u6750\u6599",
        "\u4ec0\u4e48\u6599",
        "\u7528\u6599",
        "\u677f\u6750",
        "\u5b9e\u6728",
    ))


def _has_material_evidence(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u6750\u8d28",
        "\u6750\u6599",
        "\u7528\u6599",
        "PP",
        "PET",
        "ABS",
        "\u94a2\u7ba1",
        "\u94c1\u7ba1",
        "\u51b7\u8f67\u94a2",
        "\u65e0\u7eba\u5e03",
        "\u5e03",
        "\u5851\u6599",
        "\u677f",
        "\u6728",
    ))


def _is_invoice_query(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u53d1\u7968",
        "\u5f00\u7968",
        "\u7535\u5b50\u53d1\u7968",
        "\u589e\u503c\u7a0e",
        "\u62ac\u5934",
        "\u7a0e\u53f7",
    ))


def _is_price_protection_query(text: str) -> bool:
    text = text or ""
    return any(word in text for word in (
        "\u4ef7\u4fdd",
        "\u4fdd\u4ef7",
        "\u964d\u4ef7",
        "\u5dee\u4ef7",
        "\u8865\u5dee",
        "\u9000\u5dee",
        "\u4e70\u8d35",
    ))


def _is_gift_missing_query(text: str) -> bool:
    text = text or ""
    return (
        any(word in text for word in ("\u8d60\u54c1", "\u793c\u54c1", "\u8d60\u9001"))
        and any(word in text for word in ("\u6ca1\u6709", "\u6ca1\u6536\u5230", "\u672a\u6536\u5230", "\u6f0f\u53d1", "\u5c11\u53d1", "\u6ca1\u7ed9"))
    )


_INVOICE_POLICY_EVIDENCE = (
    "\u5e97\u94fa\u8d2d\u4e70\u4e14\u8ba2\u5355\u672a\u9000\u6b3e/\u672a\u5173\u95ed\u7684\u60c5\u51b5\u4e0b\uff0c"
    "\u652f\u6301\u5f00\u5177\u7535\u5b50\u53d1\u7968\u3002"
    "\u53d1\u7968\u91d1\u989d\u6309\u8ba2\u5355\u5e73\u53f0\u5b9e\u4ed8\u91d1\u989d\u5f00\u5177\uff0c\u4e0d\u80fd\u591a\u5f00\u6216\u5c11\u5f00\u3002"
    "\u589e\u503c\u7a0e\u666e\u901a\u7535\u5b50\u53d1\u7968\u9700\u8981\u62ac\u5934\u3001\u7a0e\u53f7\u3001\u63a5\u6536\u90ae\u7bb1\u548c\u624b\u673a\u53f7\uff1b"
    "\u4e13\u7968\u9700\u8981\u5f00\u6237\u884c\u3001\u8d26\u53f7\u3001\u6ce8\u518c\u5730\u5740\u53ca\u7535\u8bdd\u7b49\u4fe1\u606f\u3002"
)

_PRICE_PROTECTION_POLICY_EVIDENCE = (
    "\u662f\u5426\u7b26\u5408\u4ef7\u4fdd\uff0c\u9700\u70b9\u51fb\u8ba2\u5355\u8be6\u60c5\u540e\u5728\u3010\u6211\u7684\u670d\u52a1\u3011\u67e5\u770b\u3002"
    "\u6709\u4ef7\u4fdd\u670d\u52a1\u4e14\u5728\u4ef7\u4fdd\u671f\u5185\u6709\u5546\u54c1\u76f4\u964d\u65f6\uff0c\u53ef\u4ee5\u5728\u8ba2\u5355\u8be6\u60c5\u81ea\u52a9\u7533\u8bf7\u4ef7\u4fdd\u3002"
    "\u4ef7\u4fdd\u901a\u5e38\u6309\u5546\u54c1\u5b9e\u6536\u91d1\u989d\u548c\u540c\u6b3e\u540c\u7ec4\u5408\u6838\u7b97\uff0c"
    "\u7ea2\u5305\u3001\u4f18\u60e0\u5238\u3001\u7701\u94b1\u5361\u300188VIP\u7b49\u4e2a\u4eba\u4f18\u60e0\u901a\u5e38\u4e0d\u6309\u5546\u54c1\u76f4\u964d\u5dee\u4ef7\u5904\u7406\u3002"
)

_PROMOTION_POLICY_EVIDENCE = (
    "\u5f53\u524d\u4f18\u60e0\u3001\u6d3b\u52a8\u3001\u4f18\u60e0\u5238\u548c\u5230\u624b\u4ef7\u9700\u4ee5\u5e97\u94fa\u9875\u9762\u3001"
    "\u5546\u54c1\u8be6\u60c5\u9875\u3001\u8ba2\u5355\u7ed3\u7b97\u9875\u5b9e\u9645\u5c55\u793a\u4e3a\u51c6\uff0c\u5ba2\u670d\u4e0d\u5e94\u627f\u8bfa\u672a\u6838\u5b9e\u7684\u4ef7\u683c\u6216\u6d3b\u52a8\u3002"
)

_STOCK_POLICY_EVIDENCE = (
    "\u5e93\u5b58\u548c\u53d1\u8d27\u65f6\u95f4\u9700\u4ee5\u5546\u54c1\u9875\u9762\u3001\u8ba2\u5355\u9875\u548c\u4ed3\u5e93\u5b9e\u9645\u72b6\u6001\u4e3a\u51c6\uff0c"
    "\u672a\u6838\u5b9e\u524d\u4e0d\u5e94\u627f\u8bfa\u9a6c\u4e0a\u53d1\u8d27\u6216\u4eca\u5929\u4e00\u5b9a\u53d1\u51fa\u3002"
)

_GIFT_POLICY_EVIDENCE = (
    "\u8d60\u54c1\u95ee\u9898\u9700\u6838\u5bf9\u8ba2\u5355\u9875\u3001\u5546\u54c1\u6d3b\u52a8\u9875\u548c\u4ed3\u5e93\u53d1\u8d27\u8bb0\u5f55\uff0c"
    "\u5982\u786e\u8ba4\u6d3b\u52a8\u5305\u542b\u8d60\u54c1\u4e14\u8ba2\u5355\u672a\u53d1\u6216\u6f0f\u53d1\uff0c\u9700\u7531\u5ba2\u670d\u6838\u5b9e\u540e\u5904\u7406\u3002"
)

_PRODUCT_SAFETY_POLICY_EVIDENCE = (
    "\u6d89\u53ca\u5b9d\u5b9d\u5165\u53e3\u3001\u8bef\u98df\u3001\u523a\u6fc0\u6027\u6c14\u5473\u6216\u7ade\u54c1\u5b89\u5168\u5bf9\u6bd4\u65f6\uff0c"
    "\u5ba2\u670d\u4e0d\u5e94\u732e\u6d4b\u5546\u54c1\u6750\u8d28\u6216\u7ade\u54c1\u60c5\u51b5\uff0c\u5e94\u5148\u63d0\u9192\u505c\u6b62\u5f02\u5e38\u4f7f\u7528\u3001\u6838\u5bf9\u5546\u54c1\u9875\u9762\u6216\u68c0\u6d4b\u8bf4\u660e\uff0c\u5fc5\u8981\u65f6\u8f6c\u4eba\u5de5\u6838\u5b9e\u3002"
    "\u7ade\u54c1\u5bf9\u6bd4\u65f6\uff0c\u53ea\u80fd\u6838\u5bf9\u672c\u5e97\u5546\u54c1\u9875\u9762\u3001\u6750\u8d28\u8bf4\u660e\u3001\u9002\u7528\u5e74\u9f84\u548c\u5b89\u5168\u63d0\u9192\uff1b"
    "\u5982\u679c\u5ba2\u6237\u53d1\u6765\u522b\u5bb6\u9875\u9762\u622a\u56fe\uff0c\u4ec5\u80fd\u6309\u9875\u9762\u516c\u5f00\u4fe1\u606f\u5bf9\u7167\uff0c\u4e0d\u731c\u6d4b\u5bf9\u65b9\u672a\u5199\u660e\u7684\u5185\u5bb9\u3002"
)

_CLEANING_CARE_POLICY_EVIDENCE = (
    "\u6e05\u6d01\u4fdd\u517b\u7c7b\u95ee\u9898\u9700\u6309\u5546\u54c1\u9875\u9762\u6216\u5df2\u9a8c\u8bc1\u8bf4\u660e\u56de\u7b54\uff1b"
    "\u672a\u786e\u8ba4\u5177\u4f53\u6750\u8d28\u548c\u7ed3\u6784\u524d\uff0c\u4e0d\u5e94\u76f4\u63a5\u627f\u8bfa\u53ef\u6574\u4f53\u6c34\u6d17\u3001\u673a\u6d17\u6216\u957f\u65f6\u95f4\u6d78\u6ce1\u3002"
    "\u4e00\u822c\u53ef\u5efa\u8bae\u7528\u5e72\u5e03\u6216\u5fae\u6e7f\u5e03\u64e6\u62ed\uff0c\u6e05\u6d01\u540e\u653e\u5728\u901a\u98ce\u5904\u667e\u5e72\uff0c\u5177\u4f53\u4ee5\u5bf9\u5e94\u5546\u54c1\u8bf4\u660e\u4e3a\u51c6\u3002"
)

_IMAGE_ATTACHMENT_POLICY_EVIDENCE = (
    "\u5ba2\u6237\u53d1\u6765\u56fe\u7247\u3001\u7167\u7247\u6216\u622a\u56fe\u65f6\uff0c"
    "\u56fe\u7247\u53ea\u80fd\u4f5c\u4e3a\u5f85\u6838\u5b9e\u6750\u6599\uff0c\u4e0d\u5e94\u4ec5\u51ed\u56fe\u7247\u76f4\u63a5\u627f\u8bfa\u8d54\u4ed8\u3001"
    "\u5224\u5b9a\u8d28\u91cf\u95ee\u9898\u6216\u786e\u8ba4\u5b89\u5168\u4e8b\u5b9e\u3002"
    "\u5e94\u7ed3\u5408\u8ba2\u5355\u3001\u5546\u54c1 SKU\u3001\u7269\u6d41/\u5305\u88c5\u60c5\u51b5\u548c\u4eba\u5de5\u590d\u6838\u7ed3\u679c\u7ee7\u7eed\u5904\u7406\u3002"
)


def generate_reply(state: dict) -> dict:
    """生成回复建议（非物流场景）。"""
    t0 = time.time()

    msg = state.get("normalized_message", state.get("customer_message", ""))
    intent = state.get("intent", "general")
    if intent == "image_attachment" and _has_product_context(state) and _has_text_product_question(state):
        state = dict(state)
        state["intent"] = "product_question"
        intent = "product_question"
    risk_level = state.get("risk_level", "low")
    product_name = _product_name(state)
    policy = state.get("shipping_policy", {})
    product_knowledge = state.get("product_knowledge", [])
    knowledge = state.get("knowledge", [])

    answer_mode, mode_source = _resolve_answer_mode(state)
    suggested_reply = ""
    customer_emotion = "中性"
    reply_style = "温和专业"
    action_proposal = {"action_type": "无", "reason": ""}
    llm_used = False
    llm_skipped = False
    llm_error = ""
    generation_mode = "rule_based"
    safety_contract = state.get("safety_contract", {}) or {}
    generic_rule_used: dict[str, Any] | None = None

    if intent == "needs_clarification":
        suggested_reply = VAGUE_CLARIFICATION_REPLY
        generation_mode = "rule_based"
    elif answer_mode == "exact_faq_answer":
        suggested_reply = _render_exact_faq(_best_faq_evidence(state), product_name, state)
    elif answer_mode == "product_fact_answer":
        if state.get("query_fact_type") == "space_fit":
            candidate_rule = _best_generic_service_rule(state)
            if candidate_rule and candidate_rule.get("fact_type") == "space_fit":
                generic_rule_used = candidate_rule
        suggested_reply = _render_product_facts(state, product_name)
    elif answer_mode == "no_evidence_clarification":
        generic_rule_used = _best_generic_service_rule(state)
        if (
            _low_risk_generic_rule_fallback(generic_rule_used, state)
            and not _generic_fallback_is_concrete_product_fact(state, generic_rule_used)
        ):
            suggested_reply = _render_generic_service_rule(generic_rule_used, state, product_name)
            generation_mode = "rule_based"
        else:
            if _generic_fallback_is_concrete_product_fact(state, generic_rule_used):
                generic_rule_used = None
            no_evidence_reply = _no_evidence_reply(state, product_name)
            suggested_reply = (
                no_evidence_reply
                if no_evidence_reply != CLARIFICATION_REPLY
                else state.get("clarification_question") or no_evidence_reply
            )
    else:
        targeted_reply = _targeted_human_review_reply(state, msg, intent, answer_mode)
        if targeted_reply:
            suggested_reply = targeted_reply
            generation_mode = "rule_based"

        if not suggested_reply:
            generic_rule_used = _best_generic_service_rule(state)
            if generic_rule_used and not _generic_fallback_is_concrete_product_fact(state, generic_rule_used):
                suggested_reply = _render_generic_service_rule(generic_rule_used, state, product_name)
                generation_mode = "rule_based"
            elif _generic_fallback_is_concrete_product_fact(state, generic_rule_used):
                generic_rule_used = None

        can_use_llm = _can_use_llm_for_mode(answer_mode)
        llm_client = get_llm_client()
        has_llm = bool(llm_client.api_key)

        if (
            not suggested_reply
            and can_use_llm
            and has_llm
            and intent not in ("logistics_eta", "shipping", "logistics", "delivery_not_received")
            and intent not in RULE_ONLY_INTENTS
        ):
            knowledge_text = _build_knowledge_text(state, strict=True)
            system_prompt = build_system_prompt(
                forbidden_claims=["一定明天到", "保证", "肯定", "绝对"],
                knowledge_context=knowledge_text,
            )
            ctx = {
                "order": state.get("live_order") or state.get("order"),
                "shipment_status": state.get("shipment_status", "unknown"),
                "policy": policy,
                "product_knowledge": product_knowledge,
                "evidence": state.get("evidence", {}),
                "answer_mode": answer_mode,
            }
            user_message = build_user_message(
                customer_message=msg,
                order_id=state.get("order_id", ""),
                context=ctx,
                risk_hint=risk_level,
            )
            try:
                _metrics_increment("llm_call_count")
                result = llm_client.chat(system_prompt, user_message)
                if not result.get("error", "").startswith("UNCONFIGURED"):
                    suggested_reply = result.get("suggested_reply", "")
                    customer_emotion = result.get("customer_emotion", customer_emotion)
                    reply_style = result.get("reply_style", reply_style)
                    action_proposal = result.get("action_proposal", action_proposal)
                    llm_used = bool(suggested_reply)
                    generation_mode = "llm_grounded" if suggested_reply else "rule_based"
                    _metrics_increment("llm_success_count")
                else:
                    llm_skipped = True
                    llm_error = "LLM_UNCONFIGURED"
                    _metrics_increment("llm_unconfigured_count")
            except Exception as exc:  # pragma: no cover - external LLM failure path
                llm_skipped = True
                llm_error = str(exc)
                _metrics_increment("llm_failure_count")
                logger.warning("LLM 调用失败，降级规则引擎: %s", exc)

        if not suggested_reply:
            suggested_reply = _generate_rule_reply(
                msg, intent, risk_level, product_name, policy, knowledge, product_knowledge, state=state
            )
            generation_mode = "rule_based"

    customer_emotion = _detect_emotion(msg, customer_emotion)
    policy_warnings = _policy_warnings(state)
    action_proposal = _action_proposal(state, action_proposal)

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "generate_reply",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "answer_mode": answer_mode,
        "generation_mode": generation_mode,
        "llm_used": llm_used,
        "safety_contract_applied": bool(safety_contract),
        "summary": f"grounded_generation: {answer_mode} ({mode_source}), llm_used={llm_used}",
    }

    extra_state = {}
    if intent == "invoice":
        extra_state["evidence"] = _with_invoice_policy_evidence(state)
    elif intent in ("price_protection", "price_promotion"):
        extra_state["evidence"] = _with_price_protection_policy_evidence(state)
    elif intent == "promotion_query":
        extra_state["evidence"] = _with_builtin_policy_evidence(state, "builtin_promotion_policy", "\u4f18\u60e0\u6d3b\u52a8\u653f\u7b56", _PROMOTION_POLICY_EVIDENCE)
    elif intent == "stock_query":
        extra_state["evidence"] = _with_builtin_policy_evidence(state, "builtin_stock_policy", "\u5e93\u5b58\u53d1\u8d27\u653f\u7b56", _STOCK_POLICY_EVIDENCE)
    elif intent == "gift_missing":
        extra_state["evidence"] = _with_builtin_policy_evidence(state, "builtin_gift_policy", "\u8d60\u54c1\u6838\u5bf9\u653f\u7b56", _GIFT_POLICY_EVIDENCE)
    elif intent == "cleaning_care":
        extra_state["evidence"] = _with_builtin_policy_evidence(state, "builtin_cleaning_care_policy", "\u6e05\u6d01\u4fdd\u517b\u8fb9\u754c", _CLEANING_CARE_POLICY_EVIDENCE)
    elif intent == "image_attachment":
        extra_state["evidence"] = _with_builtin_policy_evidence(state, "builtin_image_attachment_policy", "\u56fe\u7247\u9644\u4ef6\u6838\u5b9e\u8fb9\u754c", _IMAGE_ATTACHMENT_POLICY_EVIDENCE)
        extra_state["requires_human_review"] = True
        extra_state["review_reason"] = "\u5ba2\u6237\u53d1\u6765\u56fe\u7247/\u622a\u56fe\uff0c\u9700\u8981\u4eba\u5de5\u6838\u5bf9\u56fe\u7247\u5185\u5bb9\u4e0e\u8ba2\u5355/\u5546\u54c1\u4fe1\u606f"
    elif intent in ("child_safety", "competitor_compare", "odor_question", "material_safety"):
        extra_state["evidence"] = _with_builtin_policy_evidence(state, "builtin_product_safety_policy", "\u5546\u54c1\u5b89\u5168\u8fb9\u754c", _PRODUCT_SAFETY_POLICY_EVIDENCE)
        has_direct_evidence = bool(_best_faq_evidence(state) or _real_product_facts(state))
        low_risk_generic_fallback = _low_risk_generic_rule_fallback(generic_rule_used, state)
        if not has_direct_evidence and not low_risk_generic_fallback:
            extra_state["requires_human_review"] = True
            extra_state["review_reason"] = "\u6d89\u53ca\u6750\u8d28\u3001\u5b9d\u5b9d\u5b89\u5168\u6216\u7ade\u54c1\u5b89\u5168\u5bf9\u6bd4\uff0c\u9700\u8981\u4eba\u5de5\u590d\u6838"
    elif intent == "needs_clarification":
        extra_state["requires_human_review"] = True
        extra_state["review_reason"] = "\u95ee\u9898\u63cf\u8ff0\u8fc7\u4e8e\u6a21\u7cca\uff0c\u9700\u8981\u4e70\u5bb6\u8865\u5145\u56fe\u7247\u6216\u5177\u4f53\u60c5\u51b5"
        extra_state["needs_clarification"] = True
        extra_state["missing_slots"] = ["\u5177\u4f53\u95ee\u9898", "\u56fe\u7247", "\u5f02\u5e38\u4f4d\u7f6e"]
    if generic_rule_used:
        generic_rule_summary = {
            "rule_key": generic_rule_used.get("rule_key", ""),
            "title": generic_rule_used.get("title", ""),
            "fact_type": generic_rule_used.get("fact_type", ""),
            "score": generic_rule_used.get("score", 0),
        }
        extra_state["evidence"] = _with_generic_rule_evidence({**state, **extra_state}, generic_rule_used)
        extra_state["generic_service_rule_used"] = generic_rule_summary
        extra_state.setdefault("evidence_debug", {})["generic_service_rule_used"] = generic_rule_summary
        trace["generic_service_rule_used"] = generic_rule_summary
        trace["summary"] += f", generic_rule={generic_rule_summary['rule_key']}"

    selected_product_first = _selected_product_first_evidence(state)
    final_answer_source = selected_product_first.get("role") or (
        "generic_fallback_rules" if generic_rule_used else answer_mode
    )
    trace["answer_source_priority"] = PRODUCT_FIRST_SOURCE_PRIORITY
    trace["selected_product_first_evidence"] = selected_product_first
    trace["selected_evidence_role"] = selected_product_first.get("role", "")
    trace["generic_fallback_used"] = bool(generic_rule_used)
    trace["missing_required_evidence"] = _missing_required_evidence_from_pack(state)
    trace["final_answer_source"] = final_answer_source
    trace["can_send"] = "deferred_to_final_contract"
    trace["block_reasons"] = []
    if selected_product_first.get("provisional_knowledge_used"):
        extra_state["requires_human_review"] = True
        extra_state["review_reason"] = "ai_provisional_knowledge_requires_review"
        trace["provisional_knowledge_used"] = True
        trace["provisional_draft_uid"] = selected_product_first.get("provisional_draft_uid", "")
        trace["provisional_verification_status"] = "pending_review"
        trace["usable_for_eval"] = True
        trace["usable_for_auto_send"] = False
        trace["can_send"] = False
        trace["block_reasons"] = ["ai_provisional_knowledge_not_verified"]

    return {
        "suggested_reply": suggested_reply,
        "customer_emotion": customer_emotion,
        "reply_style": reply_style,
        "policy_warnings": policy_warnings,
        "action_proposal": action_proposal,
        "answer_mode": answer_mode,
        "generation_mode": generation_mode,
        "llm_used": llm_used,
        "llm_skipped": llm_skipped,
        "llm_error": llm_error,
        "safety_contract": safety_contract,
        "used_knowledge_entry_ids": _used_knowledge_entry_ids(state),
        "used_knowledge_titles": _used_knowledge_titles(state),
        "trace_steps": state.get("trace_steps", []) + [trace],
        **extra_state,
    }


def _resolve_answer_mode(state: dict) -> tuple[str, str]:
    intent = state.get("intent", "")
    current = state.get("answer_mode", "")
    if intent == "invoice":
        return "policy_grounded_answer", "invoice_policy"
    if intent in ("price_protection", "price_promotion"):
        return "policy_grounded_answer", "price_protection_policy"
    if intent == "material_safety":
        if _is_certification_report_query(state.get("normalized_message", state.get("customer_message", ""))):
            return "policy_grounded_answer", f"{intent}_policy"
        faq = _best_faq_evidence(state)
        if faq and not config.USE_LLM_FOR_EXACT_FAQ:
            return "exact_faq_answer", "faq_evidence"
        if _real_product_facts(state) and not config.USE_LLM_FOR_PRODUCT_FACTS:
            return "product_fact_answer", "product_facts"
        return "policy_grounded_answer", f"{intent}_policy"

    if intent in (
        "promotion_query", "stock_query", "gift_missing", "child_safety",
        "competitor_compare", "odor_question", "cleaning_care", "image_attachment",
    ):
        return "policy_grounded_answer", f"{intent}_policy"

    if intent in PRODUCT_INTENTS:
        faq = _best_faq_evidence(state)
        if faq and not config.USE_LLM_FOR_EXACT_FAQ:
            return "exact_faq_answer", "faq_evidence"

        if _real_product_facts(state) and not config.USE_LLM_FOR_PRODUCT_FACTS:
            return "product_fact_answer", "product_facts"

        if _best_generic_service_rule(state):
            return "policy_grounded_answer", "generic_service_rule"

        if not faq and not _real_product_facts(state):
            return "no_evidence_clarification", "missing_evidence"

    if current in ("aftersales_policy", "policy", "policy_answer"):
        return "policy_grounded_answer", "legacy_policy_mode"
    if current == "human_review":
        return "sop_human_review_answer", "legacy_human_review_mode"
    return current or "no_evidence_clarification", "existing_mode"


def _best_faq_evidence(state: dict) -> dict | None:
    candidates = []
    query = state.get("normalized_message", state.get("customer_message", ""))
    query_fact_type = state.get("query_fact_type", "")
    for item in state.get("filtered_evidence", []) + state.get("knowledge_evidence", []):
        if item.get("source_type") != "faq" or item.get("reference_only"):
            continue
        if item.get("evidence_allowed_for_exact_answer") is False:
            continue
        if item.get("evidence_allowed_for_direct_answer") is False:
            continue
        if _is_compare_query(query) and not _has_compare_evidence(" ".join([
            item.get("title", ""),
            item.get("matched_title", ""),
            item.get("chunk_text", ""),
            item.get("fact", ""),
        ])):
            continue
        evidence_text = " ".join([
            item.get("title", ""),
            item.get("matched_title", ""),
            item.get("chunk_text", ""),
            item.get("fact", ""),
        ])
        if _is_certification_report_query(query):
            continue
        if _is_material_detail_query(query) and not _has_material_evidence(evidence_text):
            continue
        evidence_fact_type = item.get("evidence_fact_type") or infer_evidence_fact_type(item)
        if query_fact_type and not fact_type_matches(query_fact_type, evidence_fact_type):
            continue
        score = float(item.get("score") or 0)
        if score >= config.FAQ_EXACT_SCORE_THRESHOLD:
            candidates.append(item)

    if not candidates:
        for item in state.get("evidence", {}).get("faq_evidence", []):
            if item.get("fact") and not item.get("reference_only"):
                if _is_compare_query(query) and not _has_compare_evidence(" ".join([
                    item.get("title", ""),
                    item.get("matched_title", ""),
                    item.get("fact", ""),
                    item.get("chunk_text", ""),
                ])):
                    continue
                evidence_text = " ".join([
                    item.get("title", ""),
                    item.get("matched_title", ""),
                    item.get("fact", ""),
                    item.get("chunk_text", ""),
                ])
                if _is_certification_report_query(query):
                    continue
                if _is_material_detail_query(query) and not _has_material_evidence(evidence_text):
                    continue
                evidence_fact_type = item.get("evidence_fact_type") or infer_evidence_fact_type(item)
                if query_fact_type and not fact_type_matches(query_fact_type, evidence_fact_type):
                    continue
                copied = dict(item)
                copied["chunk_text"] = copied.get("fact", "")
                copied["score"] = copied.get("score", 1.0)
                candidates.append(copied)

    if not candidates:
        return None

    best = max(candidates, key=lambda x: float(x.get("score") or 0))

    # 标记 unverified_fact: draft entry 的 FAQ 包含高风险字段
    entry_status = best.get("entry_status", "unknown")
    chunk_text = best.get("chunk_text", "") or best.get("fact", "")
    from app.agent.nodes.evidence_builder import _detect_high_risk_fields
    risk_fields = _detect_high_risk_fields(chunk_text)
    if entry_status == "draft" and risk_fields:
        best["unverified_fact"] = True
        best["high_risk_fields"] = risk_fields

    return best


def _real_product_facts(state: dict) -> list[dict]:
    facts = []
    query_fact_type = state.get("query_fact_type", "")
    query = state.get("normalized_message", state.get("customer_message", "")) or ""
    formal_convergence_enabled = str(
        os.getenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    selected_evidence = list(state.get("selected_evidence") or [])
    if formal_convergence_enabled or selected_evidence:
        # Formal convergence is opt-in.  Once enabled, only the canonical
        # selection may supply customer-facing product facts.  A non-empty
        # selection remains authoritative for legacy callers too.
        candidate_items = selected_evidence
    else:
        candidate_items = (
            _product_first_structured_facts(state)
            + _product_first_scoped_chunks(state)
            + list(state.get("evidence", {}).get("product_facts", []) or [])
            + list(state.get("knowledge_evidence", []) or [])
            + list(state.get("filtered_evidence", []) or [])
        )
    seen = set()
    for item in candidate_items:
        source_type = item.get("source_type", "")
        fact = item.get("fact", "")
        chunk_text = _fact_text(item)
        dedupe_key = (item.get("entry_id"), item.get("chunk_id"), chunk_text)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        evidence_fact_type = item.get("evidence_fact_type") or infer_evidence_fact_type(item)
        if (
            query_fact_type
            and evidence_fact_type
            and not fact_type_matches(query_fact_type, evidence_fact_type)
        ):
            continue
        # reference_only / 被门控拦截的商品事实不能直接渲染给买家
        if item.get("reference_only"):
            continue
        if source_type == "faq" and item.get("evidence_allowed_for_exact_answer") is False:
            continue
        if item.get("evidence_allowed_for_direct_answer") is False:
            continue
        if item.get("direct_answer_allowed") is False:
            continue
        if _is_compare_query(query) and not _has_compare_evidence(" ".join([
            item.get("title", ""),
            item.get("matched_title", ""),
            chunk_text,
            fact,
        ])):
            continue
        if (source_type in ("product_facts", "installation_guide", "faq") or item.get("evidence_role") in {"product_fact_direct", "faq_direct"}) and chunk_text:
            facts.append(item)
    facts = _drop_placeholder_product_facts_when_concrete_exists(facts)
    if query_fact_type == "odor":
        facts.sort(key=lambda item: (0 if _has_specific_odor_evidence(_fact_text(item)) else 1, -float(item.get("score") or 0)))
    return facts


def _is_placeholder_product_fact(item: dict) -> bool:
    text = _fact_text(item)
    return is_placeholder_evidence_text(text)


def _drop_placeholder_product_facts_when_concrete_exists(facts: list[dict]) -> list[dict]:
    concrete = [item for item in facts if not _is_placeholder_product_fact(item)]
    if concrete:
        return concrete
    return []


def _product_first_pack(state: dict) -> dict[str, Any]:
    pack = state.get("product_first_evidence_pack")
    if isinstance(pack, dict) and pack:
        return pack
    product_pack = state.get("product_context_pack") if isinstance(state.get("product_context_pack"), dict) else {}
    for key in ("product_first_evidence_pack", "evidence_pack"):
        value = product_pack.get(key)
        if isinstance(value, dict) and value:
            return value
    value = state.get("product_card_evidence_pack")
    return value if isinstance(value, dict) else {}


def _product_first_identity_locked(state: dict) -> bool:
    pack = _product_first_pack(state)
    trace = pack.get("evidence_pack_trace") if isinstance(pack.get("evidence_pack_trace"), dict) else {}
    if trace.get("product_identity_locked") is False:
        return False
    return float(pack.get("identity_confidence") or 0) > 0 or bool(pack.get("resolved_product_identity"))


def _product_first_fact_items(state: dict, bucket: str) -> list[dict]:
    if not _product_first_identity_locked(state):
        return []
    pack = _product_first_pack(state)
    query_fact_type = str(state.get("query_fact_type") or pack.get("requested_fact_type") or pack.get("query_fact_type") or "")
    rows = pack.get(bucket) if isinstance(pack.get(bucket), list) else []
    facts: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        fact_type = str(item.get("fact_type") or item.get("evidence_fact_type") or "")
        if query_fact_type and fact_type and not fact_type_matches(query_fact_type, fact_type):
            continue
        if item.get("direct_answer_allowed") is False or item.get("can_direct_answer") is False:
            continue
        text = str(item.get("preview") or item.get("chunk_text") or item.get("fact") or item.get("content") or "").strip()
        if not text:
            continue
        if _is_placeholder_product_fact({**item, "chunk_text": text}):
            continue
        converted = dict(item)
        converted.setdefault("source_type", "product_facts" if bucket == "product_structured_facts" else "installation_guide")
        converted.setdefault("evidence_fact_type", fact_type)
        converted.setdefault("fact_type", fact_type)
        converted.setdefault("chunk_text", text)
        converted.setdefault("evidence_allowed_for_direct_answer", True)
        converted.setdefault("direct_answer_allowed", True)
        converted.setdefault("usable_for_auto_send", item.get("usable_for_auto_send", True))
        converted.setdefault("provisional_knowledge_used", bool(item.get("provisional_knowledge_used")))
        converted.setdefault("provisional_draft_uid", item.get("provisional_draft_uid", ""))
        converted["product_first_evidence_role"] = bucket
        facts.append(converted)
    return facts


def _product_first_structured_facts(state: dict) -> list[dict]:
    return _product_first_fact_items(state, "product_structured_facts")


def _product_first_scoped_chunks(state: dict) -> list[dict]:
    return _product_first_fact_items(state, "product_scoped_chunks")


def _selected_product_first_evidence(state: dict) -> dict[str, Any]:
    for role, facts in (
        ("product_structured_facts", _product_first_structured_facts(state)),
        ("product_scoped_chunks", _product_first_scoped_chunks(state)),
    ):
        if facts:
            item = facts[0]
            return {
                "role": role,
                "fact_type": item.get("fact_type") or item.get("evidence_fact_type") or "",
                "evidence_id": item.get("evidence_id") or item.get("chunk_id") or item.get("entry_id") or "",
                "source_table": item.get("source_table", ""),
                "protocol_source_type": item.get("protocol_source_type", ""),
                "provisional_knowledge_used": bool(item.get("provisional_knowledge_used")),
                "provisional_draft_uid": item.get("provisional_draft_uid", ""),
                "usable_for_eval": bool(item.get("usable_for_eval", False)),
                "usable_for_auto_send": bool(item.get("usable_for_auto_send", True)),
                "preview": _fact_text(item)[:160],
            }
    return {}


def _missing_required_evidence_from_pack(state: dict) -> list[dict[str, Any]]:
    pack = _product_first_pack(state)
    value = pack.get("missing_required_evidence") if isinstance(pack, dict) else []
    return value if isinstance(value, list) else []


def _generic_fallback_is_concrete_product_fact(state: dict, rule: dict[str, Any] | None) -> bool:
    if not rule:
        return False
    fact_type = str(rule.get("fact_type") or state.get("query_fact_type") or "")
    return fact_type in CONCRETE_PRODUCT_FACT_TYPES and not _real_product_facts(state)


def _generic_service_rules(state: dict) -> list[dict[str, Any]]:
    pack = state.get("product_context_pack") or {}
    rules = pack.get("generic_rules") or []
    if not rules:
        evidence_pack = pack.get("evidence_pack") or state.get("product_card_evidence_pack") or {}
        rules = evidence_pack.get("matched_generic_rules") or []
    return [item for item in rules if isinstance(item, dict)]


def _best_generic_service_rule(state: dict) -> dict[str, Any] | None:
    query_fact_type = state.get("query_fact_type", "")
    rules = _generic_service_rules(state)
    if not rules:
        return None
    if query_fact_type:
        exact = [rule for rule in rules if rule.get("fact_type") == query_fact_type]
        if exact:
            return max(exact, key=lambda item: float(item.get("score") or 0))
        media = [
            rule for rule in rules
            if rule.get("fact_type") == "media_reference"
            and query_fact_type in {"installation", "dimensions", "space_fit", "accessories"}
            and _has_deliverable_media_assets(state)
        ]
        if media:
            return max(media, key=lambda item: float(item.get("score") or 0))
    best = max(rules, key=lambda item: float(item.get("score") or 0))
    # Never promise images/videos when no deliverable media assets exist.
    if (
        best.get("fact_type") == "media_reference"
        and not _has_deliverable_media_assets(state)
    ):
        non_media = [rule for rule in rules if rule.get("fact_type") != "media_reference"]
        if non_media:
            return max(non_media, key=lambda item: float(item.get("score") or 0))
        return None
    return best


def _low_risk_generic_rule_fallback(rule: dict[str, Any] | None, state: dict) -> bool:
    if not rule:
        return False
    if str(rule.get("risk_level") or "low") != "low":
        return False
    if rule.get("auto_reply_allowed") is False:
        return False
    fact_type = str(rule.get("fact_type") or state.get("query_fact_type") or "")
    if fact_type not in {"odor", "cleaning_care", "installation", "detachable", "space_fit", "placement_scene"}:
        return False
    message = str(state.get("normalized_message") or state.get("customer_message") or "")
    high_risk_terms = (
        "0甲醛", "零甲醛", "甲醛超标", "检测报告", "质检报告", "证书",
        "绝对安全", "百分百安全", "宝宝能不能啃", "宝宝能啃", "入口",
        "投诉", "平台介入", "赔", "赔偿", "退款", "退货",
    )
    return not any(term in message for term in high_risk_terms)


def _render_generic_service_rule(rule: dict[str, Any], state: dict, product_name: str) -> str:
    try:
        from app.services.generic_service_rule_service import render_generic_service_reply
    except Exception:
        return ""
    display_name = _customer_product_display_name(state, product_name)
    return render_generic_service_reply(rule, product_name=display_name)


def _customer_product_display_name(state: dict, fallback: str = "") -> str:
    ctx = state.get("copilot_context") or {}
    for value in (
        ctx.get("display_product_name"),
        ctx.get("platform_product_title"),
        ctx.get("front_product_title"),
        ctx.get("product_title"),
        fallback,
    ):
        text = str(value or "").strip()
        if text and text not in {"商品", "这个", "这款"}:
            return text
    return ""


def _has_specific_odor_evidence(text: str) -> bool:
    return any(term in (text or "") for term in (
        "\u65e0\u6bd2\u65e0\u5473",
        "\u65e0\u5f02\u5473",
        "\u65e0\u5473",
        "\u6ca1\u6709\u5f02\u5473",
    ))


def _render_odor_product_facts(state: dict, product_name: str) -> str:
    facts = [_fact_text(item).strip() for item in _real_product_facts(state)]
    facts = list(dict.fromkeys(f for f in facts if f))
    if not facts:
        return CLARIFICATION_REPLY

    specific = next((fact for fact in facts if _has_specific_odor_evidence(fact)), facts[0])
    specific = _clean_odor_fact_text(specific)
    if not specific:
        return CLARIFICATION_REPLY

    name = f"\u8fd9\u6b3e\u300c{product_name}\u300d" if product_name else "\u8fd9\u6b3e\u5546\u54c1"
    return (
        "\u4eb2\uff5e\n"
        f"\u5173\u4e8e{name}\u7684\u6c14\u5473\uff1a{specific}\n"
        "\u65b0\u54c1\u5bc6\u5c01\u5305\u88c5\u6253\u5f00\u540e\uff0c\u5982\u679c\u6709\u8f7b\u5fae\u5305\u88c5\u6216\u8fd0\u8f93\u6c14\u5473\uff0c\u901a\u98ce\u653e\u7f6e\u540e\u4e00\u822c\u4f1a\u9010\u6b65\u51cf\u8f7b\u3002"
        "\u5982\u679c\u60a8\u6536\u5230\u540e\u89c9\u5f97\u660e\u663e\u523a\u9f3b\u6216\u5b9d\u5b9d\u95fb\u7740\u4e0d\u8212\u670d\uff0c\u53ef\u4ee5\u628a\u60c5\u51b5\u53d1\u6211\uff0c\u6211\u7ee7\u7eed\u5e2e\u60a8\u5904\u7406\u3002"
    )


def _clean_odor_fact_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    text = re.sub(r"^(Q|A|FAQ)[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[\u4eb2\u4eb2\u4eb2\u8bf7\u653e\u5fc3\uff0c,\s]+", "", text)
    text = text.replace("\u6750\u8d28\u8bf4\u660e:", "").replace("\u6750\u8d28\u8bf4\u660e\uff1a", "")
    text = text.replace("\u6c14\u5473\u8bf4\u660e:", "").replace("\u6c14\u5473\u8bf4\u660e\uff1a", "")

    sentences = [part.strip() for part in re.split(r"(?<=[\u3002\uff01\uff1f\uff1b;])\s*", text) if part.strip()]
    selected = next((part for part in sentences if _has_specific_odor_evidence(part)), text)
    selected = re.split(r"(?=\u8868\u9762\u5149\u6ed1|\u4e0d\u4f1a\u5212\u4f24)", selected)[0].strip()
    selected = selected.rstrip("\uff0c,;； ")
    if selected and selected[-1] not in "\u3002\uff01\uff1f":
        selected += "\u3002"
    return selected


def _render_exact_faq(faq: dict | None, product_name: str, state: dict | None = None) -> str:
    content = _fact_text(faq or {})
    if not content:
        return CLARIFICATION_REPLY
    if (state or {}).get("query_fact_type") == "odor":
        return _render_odor_product_facts(
            {"query_fact_type": "odor", "evidence": {"product_facts": [faq or {}]}},
            product_name,
        )
    if product_name:
        reply = f"亲亲，关于您咨询的{product_name}：{content}"
    else:
        reply = f"亲亲，关于您咨询的问题：{content}"

    # FAQ 中的高风险字段（如材质/填充物）如果来自 draft，追加保守声明
    # 这里检查 faq item 本身是否有 unverified_fact 标记
    if isinstance(faq, dict) and faq.get("unverified_fact"):
        reply += "\n\n具体细节建议以商品页面或 SKU 对应款式为准，我这边也可以继续帮您核实。"

    return reply


def _render_product_facts(state: dict, product_name: str) -> str:
    if state.get("query_fact_type") == "odor":
        return _render_odor_product_facts(state, product_name)

    facts = [_render_product_fact_line(item) for item in _real_product_facts(state)]
    facts = [f.strip() for f in facts if f and f.strip()]
    facts = list(dict.fromkeys(facts))
    if not facts:
        return CLARIFICATION_REPLY
    prefix = f"亲亲，关于您咨询的{product_name}：" if product_name else "亲亲，关于您咨询的问题："
    reply = prefix + "\n".join(facts[:3])
    if state.get("query_fact_type") == "space_fit":
        rule = _best_generic_service_rule(state)
        if rule and rule.get("fact_type") == "space_fit":
            guidance = _render_generic_service_rule(rule, state, product_name)
            if guidance:
                reply = f"{guidance}\n\n我这边也给您配了对应的尺寸/商品图，您可以结合图片标注一起看。"

    # 未审核的高风险字段 → 追加保守声明
    evidence = state.get("evidence", {})
    unverified_fields = evidence.get("unverified_fact_fields", [])
    if unverified_fields:
        reply += "\n\n具体细节建议以商品页面或 SKU 对应款式为准，我这边也可以继续帮您核实。"

    return reply


def _no_evidence_reply(state: dict, product_name: str) -> str:
    """Generate a no-evidence reply that acknowledges already-known product info."""
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots", {}) or {}
    sku = slots.get("sku_code") or identity.get("sku_id", "")
    resolved_name = product_name or identity.get("matched_product_name", "")

    if resolved_name or sku:
        # We know the product — acknowledge it, don't ask for SKU/link
        desc = resolved_name or sku
        return (
            f"亲亲，已经识别到您咨询的商品「{desc}」，"
            "这个点我先帮您核实一下准确说法，避免不同款式信息说错影响您使用。"
            "麻烦您稍等一下，我确认后再回复您～"
        )
    return CLARIFICATION_REPLY


def _generate_rule_reply(
    msg: str,
    intent: str,
    risk_level: str,
    product_name: str,
    policy: dict,
    knowledge: list,
    product_knowledge: list = None,
    state: dict | None = None,
) -> str:
    """规则引擎生成通用回复。保留给测试和兜底路径使用。"""
    state = state or {}
    product_knowledge = product_knowledge or []

    social_reply = _social_rule_reply(msg)
    if social_reply:
        return social_reply

    if intent == "invoice" or _is_invoice_query(msg):
        return _invoice_reply(state)

    if intent in ("price_protection", "price_promotion") or _is_price_protection_query(msg):
        return _price_protection_reply(state)

    if intent == "gift_missing" or _is_gift_missing_query(msg):
        return _gift_missing_reply(state)

    if intent == "aftersales":
        return _aftersales_reply(state)

    if intent == "promotion_query":
        return _promotion_reply(state)
    if intent == "stock_query":
        return _stock_reply(state)
    if intent == "child_safety":
        return _child_safety_reply(state)
    if intent == "competitor_compare":
        return _competitor_compare_reply(state)
    if intent == "odor_question":
        return _odor_reply(state)
    if intent == "cleaning_care":
        return _cleaning_care_reply(state)
    if intent == "material_safety":
        return _material_safety_reply(state)
    if intent == "image_attachment":
        return _image_attachment_reply(state)

    if intent == "delivery_not_received":
        return (
            "亲亲，非常理解您的着急。显示签收但您没有收到的话，我们会帮您一起核实。"
            "\n麻烦您发一下订单号或订单截图，我这边帮您查看签收情况；"
            "同时您可以先确认一下家人、门卫、驿站或快递员是否代收。"
        )

    if risk_level == "high":
        return "非常理解您的心情，这个问题我会先升级给主管核实处理，请您稍等。"
    if risk_level == "medium":
        return "感谢您的反馈，我已经记录您的问题，会尽快帮您核实情况。"

    if any(kw in msg for kw in ["谢谢", "感谢", "多谢"]):
        return "不客气～感谢您对我们的支持，如有其他问题随时告诉我哦～"
    if any(kw in msg for kw in ["你好", "您好", "在吗", "有人在吗"]):
        return "您好～欢迎咨询，请问有什么可以帮您的？"

    if intent == "installation":
        return _no_evidence_reply(state, product_name)

    if intent in ("product_question", "product_consult"):
        faq = _best_faq_evidence(state)
        if faq:
            return _render_exact_faq(faq, product_name, state)
        if _real_product_facts(state):
            return _render_product_facts(state, product_name)
        if knowledge:
            content = max((k.get("content", "") for k in knowledge), key=len, default="")
            if content:
                return _render_exact_faq({"chunk_text": content}, product_name, state)
        return _no_evidence_reply(state, product_name)

    return "我在的。您直接说遇到的问题就行，我会按订单、物流、商品或售后情况帮您判断下一步。"


def _targeted_human_review_reply(
    state: dict,
    msg: str,
    intent: str,
    answer_mode: str,
) -> str:
    """Return a precise handoff reply for high-risk refund complaints."""
    if answer_mode not in {"sop_human_review_answer", "human_review"} and intent != "complaint":
        return ""

    combined = _customer_history_text(state, msg)
    if not _is_refund_or_complaint_text(combined):
        return ""
    if _mentions_physical_evidence_need(combined) or state.get("image_attachments"):
        return ""

    order_id = _order_id_from_state(state)
    if order_id:
        order_line = (
            "\u6211\u8fd9\u8fb9\u5df2\u7ecf\u770b\u5230\u60a8\u7ed9\u7684\u8ba2\u5355\u4fe1\u606f\uff0c"
            "\u4f1a\u76f4\u63a5\u6309\u8fd9\u7b14\u8ba2\u5355\u5e2e\u60a8\u6838\u5bf9\uff0c\u4e0d\u7528\u60a8\u91cd\u590d\u63d0\u4f9b\u8ba2\u5355\u53f7\u3002"
        )
    else:
        order_line = (
            "\u6211\u5148\u5e2e\u60a8\u628a\u60c5\u51b5\u8bb0\u5f55\u4e0b\u6765\uff0c"
            "\u9700\u8981\u6838\u5bf9\u5230\u5177\u4f53\u8ba2\u5355\u540e\u518d\u7ed9\u60a8\u660e\u786e\u65b9\u6848\u3002"
        )

    return (
        "\u4eb2\uff5e\u6211\u7406\u89e3\u60a8\u7740\u6025\u60f3\u628a\u9000\u6b3e\u95ee\u9898\u5904\u7406\u597d\uff0c"
        "\u8fd9\u4e2a\u6211\u4f1a\u4f18\u5148\u5e2e\u60a8\u8ddf\u8fdb\u3002\n"
        f"{order_line}\n"
        "\u6211\u5148\u6838\u5bf9\u5f53\u524d\u8ba2\u5355\u7684\u552e\u540e\u8bb0\u5f55\u3001\u9000\u6b3e\u8fdb\u5ea6\u548c\u5e73\u53f0\u53ef\u5904\u7406\u8def\u5f84\uff0c"
        "\u9ebb\u70e6\u60a8\u7a0d\u7b49\u4e00\u4e0b\uff0c\u6211\u786e\u8ba4\u540e\u7ed9\u60a8\u4e00\u4e2a\u660e\u786e\u5904\u7406\u65b9\u5411\u3002"
    )


def _order_id_from_state(state: dict) -> str:
    slots = state.get("slots") or {}
    identity = state.get("order_product_identity") or {}
    for key in (
        "order_id",
        "platform_order_id",
        "platform_trade_id",
        "tid",
        "so_id",
    ):
        value = state.get(key) or slots.get(key) or identity.get(key)
        if value:
            return str(value)
    return ""


def _is_refund_or_complaint_text(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "\u9000\u6b3e",
            "\u9000\u94b1",
            "\u9000\u8d27\u9000\u6b3e",
            "\u4e0d\u7ed9\u9000",
            "\u6295\u8bc9",
            "\u5e73\u53f0\u4ecb\u5165",
            "12315",
            "\u5dee\u8bc4",
        )
    )


def _mentions_physical_evidence_need(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "\u7834\u635f",
            "\u574f\u4e86",
            "\u88c2",
            "\u5c11\u4ef6",
            "\u6f0f\u53d1",
            "\u53d1\u9519",
            "\u5b9e\u7269",
            "\u5916\u7bb1",
            "\u9762\u5355",
            "\u7167\u7247",
            "\u56fe\u7247",
            "\u8d28\u91cf",
            "\u7455\u75b5",
            "\u6c61\u6e0d",
            "\u8272\u5dee",
        )
    )


def _with_invoice_policy_evidence(state: dict) -> dict:
    evidence = dict(state.get("evidence") or {})
    template_evidence = list(evidence.get("template_evidence") or [])
    if not any(item.get("entry_id") == "builtin_invoice_policy" for item in template_evidence):
        template_evidence.append({
            "entry_id": "builtin_invoice_policy",
            "source_type": "aftersales_policy",
            "title": "\u53d1\u7968\u4e0e\u5f00\u7968\u653f\u7b56",
            "fact": _INVOICE_POLICY_EVIDENCE,
            "chunk_text": _INVOICE_POLICY_EVIDENCE,
            "confidence": "high",
        })
    evidence["template_evidence"] = template_evidence
    return evidence


def _with_builtin_policy_evidence(state: dict, entry_id: str, title: str, fact: str) -> dict:
    evidence = dict(state.get("evidence") or {})
    template_evidence = list(evidence.get("template_evidence") or [])
    if not any(item.get("entry_id") == entry_id for item in template_evidence):
        template_evidence.append({
            "entry_id": entry_id,
            "source_type": "aftersales_policy",
            "title": title,
            "fact": fact,
            "chunk_text": fact,
            "confidence": "high",
        })
    evidence["template_evidence"] = template_evidence
    return evidence


def _with_generic_rule_evidence(state: dict, rule: dict[str, Any]) -> dict:
    evidence = dict(state.get("evidence") or {})
    template_evidence = list(evidence.get("template_evidence") or [])
    entry_id = f"generic_rule:{rule.get('rule_key', '')}"
    if not any(item.get("entry_id") == entry_id for item in template_evidence):
        text = str(rule.get("content") or rule.get("reply_template") or "").strip()
        template_evidence.append({
            "entry_id": entry_id,
            "source_type": "generic_rules",
            "title": rule.get("title", ""),
            "fact": text,
            "chunk_text": text,
            "confidence": "high",
            "fact_type": rule.get("fact_type", ""),
            "forbidden_claims": rule.get("forbidden_claims", []),
        })
    evidence["template_evidence"] = template_evidence
    return evidence


def _with_price_protection_policy_evidence(state: dict) -> dict:
    evidence = dict(state.get("evidence") or {})
    template_evidence = list(evidence.get("template_evidence") or [])
    if not any(item.get("entry_id") == "builtin_price_protection_policy" for item in template_evidence):
        template_evidence.append({
            "entry_id": "builtin_price_protection_policy",
            "source_type": "aftersales_policy",
            "title": "\u4ef7\u4fdd\u4e0e\u9000\u5dee\u4ef7\u653f\u7b56",
            "fact": _PRICE_PROTECTION_POLICY_EVIDENCE,
            "chunk_text": _PRICE_PROTECTION_POLICY_EVIDENCE,
            "confidence": "high",
        })
    evidence["template_evidence"] = template_evidence
    return evidence


def _promotion_reply(state: dict) -> str:
    return (
        "\u4eb2\u4eb2\uff0c\u5f53\u524d\u6709\u6ca1\u6709\u4f18\u60e0\uff0c\u9700\u8981\u4ee5\u5546\u54c1\u8be6\u60c5\u9875\u3001"
        "\u5e97\u94fa\u6d3b\u52a8\u9875\u548c\u8ba2\u5355\u7ed3\u7b97\u9875\u5b9e\u9645\u5c55\u793a\u4e3a\u51c6\u3002"
        "\u60a8\u53ef\u4ee5\u5148\u70b9\u8fdb\u5546\u54c1\u9875\u770b\u4e00\u4e0b\u4f18\u60e0\u5238\u3001\u6ee1\u51cf\u548c\u5230\u624b\u4ef7\uff0c"
        "\u5982\u679c\u7ed3\u7b97\u4ef7\u548c\u9875\u9762\u6d3b\u52a8\u4e0d\u4e00\u81f4\uff0c\u628a\u622a\u56fe\u53d1\u6211\uff0c\u6211\u8fd9\u8fb9\u5e2e\u60a8\u6838\u5bf9\u662f\u54ea\u4e2a\u4f18\u60e0\u6ca1\u751f\u6548\u3002"
    )


def _stock_reply(state: dict) -> str:
    return (
        "\u4eb2\u4eb2\uff0c\u6709\u8d27\u548c\u80fd\u5426\u4eca\u5929\u53d1\uff0c\u9700\u8981\u4ee5\u5546\u54c1\u9875\u9762\u5e93\u5b58\u548c\u4ed3\u5e93\u5b9e\u9645\u51fa\u5e93\u72b6\u6001\u4e3a\u51c6\u3002"
        "\u6211\u5148\u5e2e\u60a8\u6309\u9875\u9762\u548c\u51fa\u5e93\u4fe1\u606f\u6838\u5bf9\uff0c\u4e0d\u76f4\u63a5\u505a\u5373\u65f6\u53d1\u51fa\u7684\u627f\u8bfa\uff0c\u514d\u5f97\u803d\u8bef\u60a8\u5b89\u6392\u3002"
        "\u60a8\u5982\u679c\u5df2\u7ecf\u4e0b\u5355\uff0c\u6211\u53ef\u4ee5\u6309\u8ba2\u5355\u53f7\u5e2e\u60a8\u67e5\u51fa\u5e93\u72b6\u6001\uff1b"
        "\u5982\u679c\u8fd8\u6ca1\u4e0b\u5355\uff0c\u5efa\u8bae\u5148\u770b\u5546\u54c1\u9875\u9762\u662f\u5426\u53ef\u62cd\u3001\u9884\u8ba1\u53d1\u8d27\u65f6\u95f4\u548c\u6536\u8d27\u5730\u533a\u9650\u5236\u3002"
    )


def _customer_history_text(state: dict, current_msg: str) -> str:
    """合并 customer 会话历史，用于跨轮次识别售后诉求。"""
    ctx = state.get("copilot_context", {}) or {}
    parts = [current_msg or ""]
    for item in ctx.get("conversation_history", []) or []:
        if isinstance(item, dict) and item.get("role") == "customer":
            from app.services.canonical_conversation_turn_service import turn_content
            parts.append(turn_content(item))
    return " ".join(p for p in parts if p)


def _aftersales_reply(state: dict) -> str:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    slots = state.get("slots") or {}
    order_id = (
        state.get("order_id")
        or slots.get("order_id")
        or slots.get("platform_trade_id")
        or slots.get("platform_order_id")
        or ""
    )
    combined = _customer_history_text(state, msg)
    query_fact_type = state.get("query_fact_type", "")

    damaged = any(word in combined for word in ("破损", "坏了", "损坏", "掉了", "掉落", "断了", "断裂", "裂了", "开裂"))
    wrong_item = any(word in combined for word in ("发错", "错货", "不是我拍", "不是我买", "发成"))
    missing_part = any(word in combined for word in ("少件", "少了", "缺件", "漏发", "少了配件", "缺配件"))
    refund_dispute = any(word in combined for word in ("退款", "退货", "退回", "退差", "券", "优惠券", "差价", "价格"))
    return_request = any(word in combined for word in ("不合适", "不想要", "能退", "可以退", "退吗", "七天无理由"))
    safety_issue = (
        query_fact_type in {"pinch_safety", "safety_small_parts"}
        or any(word in combined for word in ("被夹", "夹到", "夹到了", "夹住", "夹手", "宝宝受伤", "孩子受伤", "质量问题"))
    )

    if safety_issue:
        product_name = _product_name(state)
        name_part = f"「{product_name}」" if product_name else "这款商品"
        order_text = f"我这边已经对到订单 {order_id}，会先结合订单和商品信息核实。" if order_id else "我这边先帮您结合商品信息核实。"
        return (
            f"亲，宝宝使用{name_part}时被夹到这个情况我先帮您重点记录，安全相关问题需要谨慎核对。\n"
            f"{order_text}\n"
            "您先暂停让宝宝继续这样使用，避免再次夹到；我会把使用情况、商品结构和售后处理规则一起转给同事核实。\n"
            "麻烦您稍等一下，确认清楚后我再按准确方案回复您。"
        )

    # 零件破损/断裂优先，避免把“零件掉了/断了”误判为少件缺配件
    if damaged:
        product_name = _product_name(state)
        name_part = f"「{product_name}」" if product_name else "这款"
        return (
            f"亲，{name_part}出现零件破损/断裂确实影响使用，我先按零件破损帮您核对补配件方案。\n"
            "麻烦您把破损/断裂的零件位置、整体结构和外箱面单拍清楚发我，我核对后确认能不能补配件、补哪个配件。\n"
            "在核实清楚之前，我暂时不先承诺一定能补或换，核对完再给您准确方案。"
        )

    if wrong_item or missing_part:
        detail = "发错货/少件" if wrong_item and missing_part else ("发错货" if wrong_item else "少件/缺配件")
        order_text = f"我会先按订单 {order_id} " if order_id else "我需要先对上订单和发货明细，"
        return (
            f"亲，收到的和拍的不一致确实会让人着急，这个我先按{detail}帮您核对。\n"
            f"{order_text}核对您下单的款式、仓库发货记录和实际收到的商品/配件。\n"
            "麻烦您把收到的商品全景、外包装面单和缺少/发错的位置拍清楚发我；核对后如果确认是漏发或发错，会按店铺售后流程继续处理。"
        )

    if refund_dispute:
        order_text = f"我会结合订单 {order_id} " if order_id else "我会结合订单实付、活动规则和售后原因"
        return (
            "亲，您这个点我理解，优惠券用了之后再遇到发错货或退款，确实会担心自己吃亏。\n"
            f"{order_text}核对：原订单实付金额、优惠券/活动是否可退回，以及这次售后属于哪种责任原因。\n"
            "我先帮您按规则查清楚，再给您说能怎么处理，不会只用一句“按退款金额”就让您自己承担。"
        )

    if return_request:
        return (
            "亲，拆开看了不太合适我理解，是否能退主要看商品是否影响二次销售、是否在平台售后时效内，以及商品类目规则。\n"
            "如果包装、配件、商品本身都还完整，您可以先在订单里申请售后；我这边也会按店铺流程帮您核对是否符合退货条件。\n"
            "涉及运费或特殊类目限制的地方，我会核实清楚后再回复您。"
        )

    return (
        "亲，您的售后问题我收到了，我先帮您按实际情况核对，不会直接让您自己承担。\n"
        "我会优先看订单记录、发货明细、商品情况和对应售后规则，再给您下一步处理方式。\n"
        "如果涉及发错、少件、破损、退款金额或活动优惠，我会一起核清楚后再回复您。"
    )


def _gift_missing_reply(state: dict) -> str:
    order_id = state.get("order_id") or (state.get("slots") or {}).get("order_id") or ""
    evidence = state.get("evidence", {}) or {}
    has_order_evidence = bool(
        order_id
        or state.get("order_found")
        or state.get("live_order")
        or evidence.get("order_facts")
    )
    checked_line = (
        "\u6211\u8fd9\u8fb9\u5148\u6309\u5f53\u524d\u8ba2\u5355\u5e2e\u60a8\u6838\u5bf9\uff0c"
        "\u518d\u5bf9\u4e00\u4e0b\u6d3b\u52a8\u6761\u4ef6\u548c\u53d1\u8d27\u660e\u7ec6\u3002"
        if has_order_evidence
        else "\u6211\u5148\u5e2e\u60a8\u6838\u5bf9\u4e00\u4e0b\u3002"
    )
    if has_order_evidence:
        return (
            "\u4eb2\uff0c\u9875\u9762\u770b\u5230\u6709\u8d60\u54c1\uff0c\u6536\u5230\u540e\u6ca1\u770b\u5230\u786e\u5b9e\u4f1a\u7591\u60d1\uff0c"
            f"{checked_line}"
            "\u8d60\u54c1\u9700\u8981\u6838\u5bf9\u4e0b\u5355\u65f6\u7684\u6d3b\u52a8\u6761\u4ef6\u3001\u8ba2\u5355\u662f\u5426\u6ee1\u8db3\u6761\u4ef6\uff0c\u4ee5\u53ca\u4ed3\u5e93\u53d1\u8d27\u660e\u7ec6\u91cc\u6709\u6ca1\u6709\u5305\u542b\u3002"
            "\u6211\u5148\u6309\u8fd9\u7b14\u8ba2\u5355\u5e2e\u60a8\u5bf9\uff1b\u5982\u679c\u65b9\u4fbf\uff0c\u60a8\u4e5f\u53ef\u4ee5\u8865\u4e00\u4e0b\u6d3b\u52a8\u9875\u9762\u6216\u5305\u88f9\u5185\u7269\u54c1\u7167\u7247\uff0c\u8fd9\u6837\u6838\u5bf9\u4f1a\u66f4\u5feb\u3002"
            "\u5982\u679c\u786e\u8ba4\u7b26\u5408\u4e14\u6f0f\u53d1\uff0c\u4f1a\u6309\u5e97\u94fa\u6d41\u7a0b\u7ee7\u7eed\u5904\u7406\u3002"
        )
    return (
        "\u4eb2\uff0c\u9875\u9762\u770b\u5230\u6709\u8d60\u54c1\uff0c\u6536\u5230\u540e\u6ca1\u770b\u5230\u786e\u5b9e\u4f1a\u7591\u60d1\uff0c"
        f"{checked_line}"
        "\u8d60\u54c1\u9700\u8981\u770b\u4e0b\u5355\u65f6\u7684\u6d3b\u52a8\u9875\u9762\u3001\u8ba2\u5355\u662f\u5426\u6ee1\u8db3\u6761\u4ef6\uff0c\u4ee5\u53ca\u4ed3\u5e93\u53d1\u8d27\u660e\u7ec6\u91cc\u6709\u6ca1\u6709\u5305\u542b\u3002"
        "\u9ebb\u70e6\u60a8\u628a\u8ba2\u5355\u622a\u56fe\u6216\u8d60\u54c1\u9875\u9762\u622a\u56fe\u53d1\u6211\uff0c\u6211\u8fd9\u8fb9\u5e2e\u60a8\u5bf9\u4e0a\uff1b"
        "\u5982\u679c\u786e\u8ba4\u7b26\u5408\u4e14\u6f0f\u53d1\uff0c\u4f1a\u6309\u5e97\u94fa\u6d41\u7a0b\u7ee7\u7eed\u5904\u7406\u3002"
    )


def _child_safety_reply(state: dict) -> str:
    return (
        "\u4eb2\u4eb2\uff0c\u5982\u679c\u5b9d\u5b9d\u5df2\u7ecf\u628a\u73a9\u5177\u653e\u5230\u5634\u91cc\u54ac\uff0c\u5efa\u8bae\u5148\u6682\u505c\u7ed9\u5b9d\u5b9d\u8fd9\u6837\u4f7f\u7528\uff0c"
        "\u5e76\u68c0\u67e5\u5546\u54c1\u662f\u5426\u6709\u7834\u635f\u3001\u6389\u6e23\u3001\u5c0f\u914d\u4ef6\u677e\u8131\u7b49\u60c5\u51b5\u3002"
        "\u6750\u8d28\u548c\u9002\u7528\u65b9\u5f0f\u9700\u4ee5\u5546\u54c1\u9875\u9762\u6216\u5df2\u9a8c\u8bc1\u7684\u68c0\u6d4b\u8bf4\u660e\u4e3a\u51c6\uff0c\u6211\u4e0d\u76f4\u63a5\u731c\u3002"
        "\u5982\u679c\u5b9d\u5b9d\u6709\u8bef\u541e\u3001\u54bd\u5589\u4e0d\u9002\u6216\u5176\u4ed6\u5f02\u5e38\uff0c\u5efa\u8bae\u53ca\u65f6\u5c31\u533b\u786e\u8ba4\u3002"
        "\u60a8\u4e5f\u53ef\u4ee5\u628a\u5546\u54c1\u72b6\u6001\u6216\u9875\u9762\u622a\u56fe\u53d1\u6211\uff0c\u6211\u8fd9\u8fb9\u7ee7\u7eed\u5e2e\u60a8\u6838\u5bf9\u3002"
    )


def _competitor_compare_reply(state: dict) -> str:
    return (
        "\u4eb2\u4eb2\uff0c\u548c\u522b\u5bb6\u5546\u54c1\u7684\u5b89\u5168\u6027\u5bf9\u6bd4\uff0c\u6211\u8fd9\u8fb9\u4e0d\u80fd\u5728\u6ca1\u6709\u5bf9\u65b9\u68c0\u6d4b\u548c\u5546\u54c1\u8bc1\u636e\u7684\u60c5\u51b5\u4e0b\u76f4\u63a5\u4e0b\u7ed3\u8bba\u3002"
        "\u6211\u53ef\u4ee5\u5148\u5e2e\u60a8\u6838\u5bf9\u6211\u4eec\u8fd9\u6b3e\u7684\u5546\u54c1\u9875\u9762\u3001\u6750\u8d28\u8bf4\u660e\u3001\u9002\u7528\u5e74\u9f84\u548c\u5b89\u5168\u63d0\u9192\uff1b"
        "\u5982\u679c\u60a8\u53d1\u6765\u522b\u5bb6\u9875\u9762\u622a\u56fe\uff0c\u6211\u4e5f\u53ea\u80fd\u6309\u9875\u9762\u516c\u5f00\u4fe1\u606f\u5e2e\u60a8\u5bf9\u7167\uff0c\u4e0d\u4f1a\u731c\u6d4b\u5bf9\u65b9\u6ca1\u5199\u7684\u5185\u5bb9\u3002"
    )


def _odor_reply(state: dict) -> str:
    return (
        "亲亲，您担心气味问题很正常，宝宝用品确实要谨慎一些。\n"
        "这类新出库商品刚拆包装时，可能会有一点新材料或包装密封运输带来的味道，一般不是明显刺鼻异味，通风放置后会慢慢散掉。\n"
        "建议您收到后先把外包装全部拆开，抽屉、柜门、收纳格这些位置尽量打开，放在阳台或窗边通风处晾一晾，也可以用干净湿布简单擦拭表面后自然晾干，等气味散掉后再给宝宝使用会更安心。\n"
        "如果您收到后感觉味道明显刺鼻，或者通风后仍然很明显，建议先暂停使用，并拍照/视频联系咱们客服，我们会根据实际情况帮您处理。"
    )


def _cleaning_care_reply(state: dict) -> str:
    return (
        "\u4eb2\u4eb2\uff0c\u810f\u4e86\u600e\u4e48\u6e05\u6d01\u8fd9\u4e2a\u95ee\u9898\u5f88\u5b9e\u7528\uff0c\u6211\u5148\u6309\u4fdd\u5b88\u65b9\u5f0f\u8ddf\u60a8\u8bf4\u54e6\u3002"
        "\u672a\u6838\u5bf9\u5177\u4f53\u6750\u8d28\u548c\u9875\u9762\u6e05\u6d17\u8bf4\u660e\u524d\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u6574\u4f53\u6c34\u6d17\u6216\u957f\u65f6\u95f4\u6d78\u6ce1\u3002"
        "\u5e73\u65f6\u53ef\u4ee5\u5148\u7528\u5e72\u5e03\u6216\u5fae\u6e7f\u7684\u8f6f\u5e03\u64e6\u62ed\uff0c\u6709\u6c61\u6e0d\u7684\u5730\u65b9\u8f7b\u8f7b\u64e6\u6389\uff0c\u7136\u540e\u653e\u5728\u901a\u98ce\u5904\u667e\u5e72\u3002"
        "\u5982\u679c\u9875\u9762\u6216\u8bf4\u660e\u4e66\u6709\u6807\u6ce8\u53ef\u6c34\u6d17\uff0c\u518d\u6309\u5bf9\u5e94\u8bf4\u660e\u6765\u5904\u7406\u66f4\u7a33\u59a5\u3002"
    )


def _material_safety_reply(state: dict) -> str:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    product_name = _product_name(state)
    facts = _real_product_facts(state)
    is_cert_query = _is_certification_report_query(msg)
    facts_cover_cert = is_cert_query and any(
        kw in " ".join(_fact_text(item) for item in facts)
        for kw in ("检测", "报告", "质检", "甲醛")
    )
    if facts and (not is_cert_query or facts_cover_cert):
        return _render_product_facts(state, product_name)
        return _render_product_facts(state, product_name)

    if is_cert_query:
            return (
                "亲亲，您问甲醛/检测报告这个点很重要，家里有宝宝的话确实需要更谨慎。"
                "这类信息需要以对应商品 SKU 的已验证检测报告、质检说明或商品页面公示为准，我不先直接承诺无甲醛或有报告哦。"
                "我这边建议先按当前商品帮您转人工核实；如果页面有检测报告截图，也可以发来，核对后再给您准确回复。"
            )

    profile_unknowns = [
        item for item in (state.get("evidence", {}).get("unknowns", []) or [])
        if item.get("source_type") == "product_profile_lookup"
    ]
    if profile_unknowns:
        missing = "、".join(
            item.get("fact", "").replace("已按当前商品查询商品资料库，但缺少字段: ", "")
            .replace("已按当前商品查询商品卡片，但缺少字段: ", "")
            for item in profile_unknowns
            if item.get("fact")
        ).strip("、")
        name_part = f"「{product_name}」" if product_name else "这款商品"
        if _is_certification_report_query(msg):
            focus = "检测报告/质检说明"
        elif any(word in msg for word in ("受潮", "防潮", "潮")):
            focus = "材质和防潮说明"
        else:
            focus = "材质安全说明"
        return (
            f"亲，宝宝用的东西您关心材质和安全很正常，我先按当前商品{name_part}帮您核实一下准确说法。\n"
            f"{focus}这类信息我不先凭感觉判断，避免给您说错。麻烦您稍等一下，我这边确认清楚后再回复您。\n"
            "如果您手边有商品页面的材质说明截图，也可以一起发来，我这边会一起对照核实。"
        )

    if _is_certification_report_query(msg):
        return (
            "\u4eb2\u4eb2\uff0c\u60a8\u95ee\u7532\u919b/\u68c0\u6d4b\u62a5\u544a\u8fd9\u4e2a\u70b9\u5f88\u91cd\u8981\uff0c\u5bb6\u91cc\u6709\u5b9d\u5b9d\u7684\u8bdd\u786e\u5b9e\u9700\u8981\u66f4\u8c28\u614e\u3002"
            "\u8fd9\u7c7b\u4fe1\u606f\u9700\u8981\u4ee5\u5bf9\u5e94\u5546\u54c1 SKU \u7684\u5df2\u9a8c\u8bc1\u68c0\u6d4b\u62a5\u544a\u3001\u8d28\u68c0\u8bf4\u660e\u6216\u5546\u54c1\u9875\u9762\u516c\u793a\u4e3a\u51c6\uff0c\u6211\u4e0d\u5148\u76f4\u63a5\u627f\u8bfa\u201c\u65e0\u7532\u919b\u201d\u6216\u201c\u6709\u62a5\u544a\u201d\u54e6\u3002"
            "\u6211\u8fd9\u8fb9\u5efa\u8bae\u5148\u6309\u5f53\u524d\u5546\u54c1\u5e2e\u60a8\u8f6c\u4eba\u5de5\u6838\u5b9e\uff1b\u5982\u679c\u9875\u9762\u6709\u68c0\u6d4b\u62a5\u544a\u622a\u56fe\uff0c\u4e5f\u53ef\u4ee5\u53d1\u6765\uff0c\u6838\u5bf9\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        )
    return (
        "\u4eb2\u4eb2\uff0c\u6750\u8d28\u5b89\u5168\u548c\u662f\u5426\u5bb9\u6613\u53d7\u6f6e\uff0c\u5f88\u591a\u5bb6\u957f\u90fd\u4f1a\u7279\u522b\u5173\u5fc3\u3002"
        "\u8fd9\u7c7b\u6d89\u53ca\u6750\u8d28\u3001\u9632\u6f6e\u6216\u5b9d\u5b9d\u4f7f\u7528\u5b89\u5168\u7684\u4fe1\u606f\uff0c\u9700\u8981\u4ee5\u5bf9\u5e94\u5546\u54c1\u9875\u9762\u3001SKU \u548c\u5df2\u9a8c\u8bc1\u7684\u68c0\u6d4b/\u6750\u8d28\u8bf4\u660e\u4e3a\u51c6\uff0c\u6211\u4e0d\u76f4\u63a5\u731c\u3002"
        "\u6211\u8fd9\u8fb9\u53ef\u4ee5\u7ee7\u7eed\u6309\u5f53\u524d\u4f1a\u8bdd\u91cc\u7684\u5546\u54c1\u53bb\u6838\u5bf9\uff1b\u5982\u679c\u60a8\u65b9\u4fbf\uff0c\u4e5f\u53ef\u4ee5\u628a\u5546\u54c1\u9875\u9762\u6216\u6750\u8d28\u8bf4\u660e\u622a\u56fe\u53d1\u6211\uff0c\u6211\u5e2e\u60a8\u8f6c\u4eba\u5de5\u590d\u6838\u540e\u518d\u7ed9\u51c6\u786e\u7b54\u590d\u3002"
    )


def _image_attachment_reply(state: dict) -> str:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    ctx = state.get("copilot_context", {}) or {}
    attachments = state.get("image_attachments") or ctx.get("image_attachments") or []
    image_analysis = ctx.get("image_analysis") or []
    first_analysis = image_analysis[0] if image_analysis and isinstance(image_analysis[0], dict) else {}
    issue_type = first_analysis.get("issue_type", "")
    image_type = first_analysis.get("image_type", "")
    vlm_summary = first_analysis.get("summary", "")
    image_note = ""
    if attachments and isinstance(attachments[0], dict):
        image_note = str(
            attachments[0].get("description")
            or attachments[0].get("ocr_text")
            or attachments[0].get("note")
            or ""
        )
    combined = " ".join([msg, image_note, str(vlm_summary), str(first_analysis.get("visible_text", ""))])

    if issue_type == "damage" or image_type == "damage_photo" or any(w in combined for w in ("\u7834\u635f", "\u574f\u4e86", "\u88c2", "\u5212\u75d5", "\u78d5", "\u53d8\u5f62", "\u7455\u75b5")):
        return (
            "\u4eb2\uff0c\u56fe\u7247\u6211\u4eec\u9700\u8981\u7ed3\u5408\u8ba2\u5355\u548c\u5546\u54c1\u60c5\u51b5\u4e00\u8d77\u6838\u5bf9\uff0c"
            "\u4e0d\u5148\u76f4\u63a5\u4e0b\u7ed3\u8bba\uff0c\u514d\u5f97\u5904\u7406\u65b9\u5f0f\u4e0d\u51c6\u786e\u3002"
            "\u9ebb\u70e6\u60a8\u518d\u5e2e\u5fd9\u8865\u4e00\u4e0b\u8ba2\u5355\u53f7\uff0c\u5e76\u5c3d\u91cf\u62cd\u6e05\u695a\u7834\u635f\u4f4d\u7f6e\u3001\u5916\u5305\u88c5\u548c\u5546\u54c1\u5168\u666f\uff0c"
            "\u6211\u8fd9\u8fb9\u4f1a\u6309\u552e\u540e\u6d41\u7a0b\u5e2e\u60a8\u6838\u5b9e\uff0c\u5fc5\u8981\u65f6\u8f6c\u4eba\u5de5\u7ee7\u7eed\u5904\u7406\u3002"
        )

    if issue_type == "missing_parts" or image_type == "missing_parts" or any(w in combined for w in ("\u5c11\u4ef6", "\u7f3a\u4ef6", "\u914d\u4ef6", "\u6f0f\u53d1", "\u53d1\u9519")):
        return (
            "亲，看到您说零件掉了/少了，这个确实会影响使用，我先帮您核实能不能补配件。"
            "图片我已经收到了，麻烦您再补一下订单号或订单截图；如果方便，也把掉落的位置/缺的配件拍清楚一点。"
            "我这边对上订单和配件信息后，再给您确认对应的处理方案。"
        )

    if issue_type == "installation" or image_type == "installation_photo" or any(w in combined for w in ("\u5b89\u88c5", "\u600e\u4e48\u88c5", "\u88c5\u4e0d\u4e0a", "\u8bf4\u660e\u4e66", "\u62fc\u63a5")):
        return (
            "\u4eb2\uff0c\u60a8\u628a\u5b89\u88c5\u56fe\u53d1\u8fc7\u6765\u662f\u5bf9\u7684\uff0c\u8fd9\u6837\u66f4\u65b9\u4fbf\u5224\u65ad\u5361\u5728\u54ea\u4e00\u6b65\u3002"
            "\u6211\u4eec\u4f1a\u5148\u6309\u5f53\u524d\u5546\u54c1\u578b\u53f7\u6838\u5bf9\u5b89\u88c5\u8bf4\u660e\uff1b"
            "\u9ebb\u70e6\u60a8\u518d\u8865\u62cd\u4e00\u5f20\u914d\u4ef6\u5168\u666f\u548c\u88c5\u4e0d\u4e0a\u7684\u5177\u4f53\u4f4d\u7f6e\uff0c"
            "\u6211\u8fd9\u8fb9\u518d\u7ed9\u60a8\u5bf9\u5e94\u7684\u5b89\u88c5\u6b65\u9aa4\u3002"
        )

    if issue_type in ("promotion", "price_protection") or image_type == "promotion_screenshot" or any(w in combined for w in ("\u4f18\u60e0", "\u4ef7\u4fdd", "\u6d3b\u52a8", "\u5238", "\u4ef7\u683c", "\u5dee\u4ef7")):
        return (
            "\u4eb2\uff0c\u60a8\u53d1\u7684\u9875\u9762\u622a\u56fe\u6211\u4eec\u4f1a\u7ed3\u5408\u8ba2\u5355\u8be6\u60c5\u4e00\u8d77\u6838\u5bf9\u3002"
            "\u4ef7\u683c\u3001\u4f18\u60e0\u5238\u3001\u4ef7\u4fdd\u6216\u6d3b\u52a8\u662f\u5426\u751f\u6548\uff0c\u9700\u8981\u4ee5\u9875\u9762\u89c4\u5219\u548c\u8ba2\u5355\u7ed3\u7b97\u4fe1\u606f\u4e3a\u51c6\u3002"
            "\u60a8\u53ef\u4ee5\u518d\u8865\u4e00\u4e0b\u8ba2\u5355\u53f7\u6216\u7ed3\u7b97\u9875\u622a\u56fe\uff0c\u6211\u8fd9\u8fb9\u5e2e\u60a8\u7ee7\u7eed\u5bf9\u7167\u3002"
        )

    return (
        "\u4eb2\uff0c\u60a8\u53d1\u7684\u56fe\u7247\u6211\u4eec\u9700\u8981\u7ed3\u5408\u5177\u4f53\u95ee\u9898\u6765\u6838\u5bf9\u54e6\u3002"
        "\u5982\u679c\u662f\u7834\u635f/\u5c11\u4ef6/\u5b89\u88c5/\u4ef7\u683c\u6216\u6d3b\u52a8\u622a\u56fe\uff0c"
        "\u9ebb\u70e6\u60a8\u518d\u7b80\u5355\u8bf4\u4e0b\u60f3\u6838\u5bf9\u54ea\u4e2a\u70b9\uff0c\u6700\u597d\u540c\u65f6\u8865\u5145\u8ba2\u5355\u53f7\u6216\u5546\u54c1\u9875\u9762\u622a\u56fe\u3002"
        "\u6211\u8fd9\u8fb9\u6309\u60a8\u7684\u56fe\u7247\u548c\u8ba2\u5355/\u5546\u54c1\u4fe1\u606f\u7ee7\u7eed\u5e2e\u60a8\u6838\u5b9e\u3002"
    )


def _price_protection_reply(state: dict) -> str:
    slots = state.get("slots") or {}
    order = state.get("live_order") or state.get("order") or {}
    has_order = bool(order)
    order_id = (
        state.get("order_id")
        or slots.get("order_id")
        or slots.get("platform_trade_id")
        or slots.get("platform_order_id")
        or ""
    )
    prefix = (
        f"\u4eb2\u4eb2\uff0c\u6211\u5148\u6309\u60a8\u8fd9\u4e2a\u8ba2\u5355{order_id}\u6838\u5b9e\u4ef7\u4fdd\u72b6\u6001\u3002"
        if has_order and order_id else "\u4eb2\u4eb2\uff0c\u6211\u5148\u5e2e\u60a8\u8bf4\u4e0b\u4ef7\u4fdd\u7684\u5904\u7406\u65b9\u5f0f\u3002"
    )
    return (
        prefix
        + "\u662f\u5426\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\uff0c\u9700\u8981\u4ee5\u60a8\u8ba2\u5355\u8be6\u60c5\u91cc\u7684\u3010\u6211\u7684\u670d\u52a1\u3011\u4e3a\u51c6\uff1a"
        "\u5982\u679c\u6709\u4ef7\u4fdd\u670d\u52a1\u6807\u8bc6\uff0c\u4e14\u8fd8\u5728\u4ef7\u4fdd\u671f\u5185\u3001\u540c\u6b3e\u540c\u7ec4\u5408\u786e\u5b9e\u51fa\u73b0\u5546\u54c1\u76f4\u964d\uff0c"
        "\u60a8\u53ef\u4ee5\u5148\u5728\u8ba2\u5355\u8be6\u60c5\u91cc\u81ea\u52a9\u7533\u8bf7\u4ef7\u4fdd\u3002"
        "\u5982\u679c\u9875\u9762\u6ca1\u6709\u4ef7\u4fdd\u6807\u8bc6\uff0c\u6216\u5dee\u4ef7\u6765\u81ea\u7ea2\u5305\u3001\u4f18\u60e0\u5238\u3001\u7701\u94b1\u5361\u300188VIP\u7b49\u4e2a\u4eba\u4f18\u60e0\uff0c"
        "\u901a\u5e38\u4e0d\u6309\u5546\u54c1\u76f4\u964d\u5dee\u4ef7\u5904\u7406\u3002"
        "\u60a8\u53ef\u4ee5\u628a\u964d\u4ef7\u9875\u9762\u6216\u540c\u6b3e\u540c\u7ec4\u5408\u7684\u4ef7\u683c\u622a\u56fe\u53d1\u6211\uff0c"
        "\u6211\u8fd9\u8fb9\u7ee7\u7eed\u5e2e\u60a8\u6838\u5bf9\u9875\u9762\u4fe1\u606f\u548c\u8ba2\u5355\u6761\u4ef6\u3002"
    )


def _invoice_reply(state: dict) -> str:
    slots = state.get("slots") or {}
    order = state.get("live_order") or state.get("order") or {}
    has_order = bool(order)
    order_id = (
        state.get("order_id")
        or slots.get("order_id")
        or slots.get("platform_trade_id")
        or slots.get("platform_order_id")
        or ""
    )
    raw_status = str(
        state.get("order_status")
        or order.get("order_status")
        or order.get("status")
        or order.get("so_status")
        or ""
    ).lower()

    invalid_markers = ("cancel", "close", "refund", "\u5173\u95ed", "\u53d6\u6d88", "\u9000\u6b3e")
    if any(mark in raw_status for mark in invalid_markers):
        prefix = (
            f"\u4eb2\uff0c\u6211\u5148\u6309\u60a8\u8fd9\u4e2a\u8ba2\u5355{order_id}\u6838\u5b9e\u5f00\u7968\u72b6\u6001\u3002"
            if has_order and order_id else "\u4eb2\uff0c\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u8fd9\u4e2a\u8ba2\u5355\u7684\u5f00\u7968\u72b6\u6001\u3002"
        )
        return (
            prefix
            + "\u8fd9\u7c7b\u8ba2\u5355\u9700\u8981\u4ee5\u5e73\u53f0\u5b9e\u9645\u72b6\u6001\u4e3a\u51c6\uff0c"
            "\u5982\u679c\u8ba2\u5355\u5df2\u9000\u6b3e\u6216\u5df2\u5173\u95ed\uff0c\u901a\u5e38\u4e0d\u80fd\u6309\u539f\u8ba2\u5355\u76f4\u63a5\u5f00\u5177\u53d1\u7968\u3002"
            "\u6211\u8fd9\u8fb9\u6838\u5b9e\u6e05\u695a\u540e\u518d\u7ed9\u60a8\u767b\u8bb0\u3002"
        )

    prefix = (
        f"\u4eb2\uff0c\u6211\u5148\u6309\u60a8\u8fd9\u4e2a\u8ba2\u5355{order_id}\u6838\u5b9e\u4e00\u4e0b\u3002"
        if has_order and order_id else "\u4eb2\uff0c\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u8fd9\u4e2a\u8ba2\u5355\u7684\u5f00\u7968\u72b6\u6001\u3002"
    )
    return (
        prefix
        + "\u5e97\u94fa\u8d2d\u4e70\u4e14\u8ba2\u5355\u672a\u9000\u6b3e/\u672a\u5173\u95ed\u7684\u60c5\u51b5\u4e0b\uff0c\u652f\u6301\u5f00\u5177\u7535\u5b50\u53d1\u7968\u3002"
        "\u53d1\u7968\u91d1\u989d\u6309\u8ba2\u5355\u5e73\u53f0\u5b9e\u4ed8\u91d1\u989d\u5f00\u5177\uff0c\u4e0d\u80fd\u591a\u5f00\u6216\u5c11\u5f00\u3002"
        "\u5982\u679c\u662f\u589e\u503c\u7a0e\u666e\u901a\u7535\u5b50\u53d1\u7968\uff0c\u9ebb\u70e6\u60a8\u63d0\u4f9b\u62ac\u5934\u3001\u7a0e\u53f7\u3001\u63a5\u6536\u90ae\u7bb1\u548c\u624b\u673a\u53f7\uff1b"
        "\u5982\u679c\u662f\u4e13\u7968\uff0c\u8fd8\u9700\u8981\u5f00\u6237\u884c\u3001\u8d26\u53f7\u3001\u6ce8\u518c\u5730\u5740\u53ca\u7535\u8bdd\u7b49\u4fe1\u606f\u3002"
        "\u4e3a\u4e86\u907f\u514d\u540e\u7eed\u9000\u6362\u8d27\u5bfc\u81f4\u53d1\u7968\u4f5c\u5e9f\u91cd\u5f00\uff0c\u5efa\u8bae\u786e\u8ba4\u6536\u8d27\u65e0\u8bef\u540e\u518d\u5b89\u6392\u5f00\u5177\u3002"
    )


def _social_rule_reply(msg: str) -> str:
    text = (msg or "").strip().lower()
    if not text:
        return ""
    if any(kw in text for kw in ("谢谢", "感谢", "多谢", "辛苦了")):
        return "不客气，后面有订单、物流、商品或售后问题，直接发我就可以。"
    if any(kw in text for kw in ("你好", "您好", "在吗", "有人吗", "hello", "hi")):
        return "你好，我在。需要查物流、商品参数、售后问题，或者只是先问一句，都可以直接说。"
    if text in ("嗯", "哦", "好", "行", "可以", "好的"):
        return "好的，我在。您继续发问题就行。"
    return ""


def _build_knowledge_text(state: dict, strict: bool = False) -> str:
    parts = []
    if strict:
        parts.append(
            "## 已验证证据使用规则\n"
            "你只能使用【已验证证据】中的信息回答。\n"
            "禁止添加证据中没有的商品材质、尺寸、功能、适用年龄、填充物、洗涤方式、承重、物流状态、赔偿承诺。\n"
            "如果证据不足，请明确说需要核实，不要猜测。\n"
            "不能用“根据商品描述”这种表述，除非 evidence 中真的有商品描述。\n"
            "最终回复中的每个商品事实都必须能在 evidence 中找到。"
        )

    evidence = state.get("evidence", {})
    evidence_lines = []
    for bucket in ("product_facts", "faq_evidence", "policy_facts", "sop_evidence", "template_evidence"):
        for item in evidence.get(bucket, []):
            text = _fact_text(item)
            if text:
                evidence_lines.append(f"- [{item.get('source_type', bucket)}] {text[:500]}")
    for item in state.get("filtered_evidence", [])[:5]:
        text = _fact_text(item)
        if text:
            evidence_lines.append(f"- [{item.get('source_type', '')}/{item.get('confidence', '')}] {text[:500]}")
    if evidence_lines:
        parts.append("## 已验证证据")
        parts.extend(evidence_lines)

    knowledge = state.get("knowledge", [])
    if knowledge:
        parts.append("## 通用知识")
        for entry in knowledge[:5]:
            parts.append(f"- {entry.get('title', '')}: {entry.get('content', '')[:400]}")
    return "\n".join(parts)


def _can_use_llm_for_mode(answer_mode: str) -> bool:
    if answer_mode == "exact_faq_answer":
        return config.USE_LLM_FOR_EXACT_FAQ
    if answer_mode == "product_fact_answer":
        return config.USE_LLM_FOR_PRODUCT_FACTS
    if answer_mode in POLICY_LLM_MODES:
        return config.USE_LLM_FOR_POLICY_REWRITE
    if answer_mode in SOP_LLM_MODES:
        return config.USE_LLM_FOR_SOP_REWRITE
    return False


def _fact_text(item: dict[str, Any]) -> str:
    return str(item.get("chunk_text") or item.get("fact") or item.get("content") or item.get("preview") or "")


def _render_product_fact_line(item: dict[str, Any]) -> str:
    """Keep exact Hub attribute names next to their customer-facing values."""
    text = _fact_text(item).strip()
    if str(item.get("protocol_source_type") or "") != "product_data_hub":
        return text
    label = str(item.get("title") or item.get("attribute_key") or "").strip()
    if not label or len(label) > 80 or label in text:
        return text
    return f"{label}：{text}"


def _product_name(state: dict) -> str:
    if state.get("matched_product_name"):
        return state["matched_product_name"]
    identity = state.get("order_product_identity") or {}
    if identity.get("matched_product_name"):
        return identity["matched_product_name"]
    if identity.get("internal_product_name"):
        return identity["internal_product_name"]
    slots = state.get("slots") or {}
    for slot_key in ("product_name", "sku_name"):
        if slots.get(slot_key):
            return slots[slot_key]
    text = (
        state.get("normalized_message")
        or state.get("customer_message")
        or ""
    )
    inferred = _infer_product_name_from_aftersales_text(text)
    if inferred:
        return inferred
    return ""


def _infer_product_name_from_aftersales_text(text: str) -> str:
    """Infer simple product mentions from aftersales text when resolver is absent."""
    text = (text or "").strip()
    if not text:
        return ""
    patterns = (
        r"(?:我的|这个|这款)(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,12}?)(?:零件|配件|部件)",
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{2,12}?)(?:零件|配件|部件)(?:都)?(?:掉了|断了|坏了|破损)",
    )
    generic = {"商品", "东西", "产品", "这个", "这款"}
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group("name").strip()
            if name and name not in generic:
                return name
    return ""


def _used_knowledge_entry_ids(state: dict) -> list:
    ids = []
    for item in state.get("knowledge_evidence", []) + state.get("filtered_evidence", []):
        entry_id = item.get("entry_id")
        if entry_id and entry_id not in ids:
            ids.append(entry_id)
    for item in state.get("evidence", {}).get("faq_evidence", []) + state.get("evidence", {}).get("product_facts", []):
        entry_id = item.get("entry_id")
        if entry_id and entry_id not in ids:
            ids.append(entry_id)
    for rule in _generic_service_rules(state):
        entry_id = f"generic_rule:{rule.get('rule_key', '')}"
        if rule.get("rule_key") and entry_id not in ids:
            ids.append(entry_id)
    return ids


def _used_knowledge_titles(state: dict) -> list[str]:
    titles = []
    for item in state.get("knowledge_evidence", []) + state.get("filtered_evidence", []):
        title = item.get("title")
        if title and title not in titles:
            titles.append(title)
    for item in state.get("evidence", {}).get("faq_evidence", []) + state.get("evidence", {}).get("product_facts", []):
        title = item.get("title")
        if title and title not in titles:
            titles.append(title)
    for rule in _generic_service_rules(state):
        title = rule.get("title")
        if title and title not in titles:
            titles.append(title)
    return titles


def _detect_emotion(msg: str, default: str) -> str:
    if any(kw in msg for kw in ["急", "怎么还没", "投诉", "差评", "退款"]):
        return "焦急/不满"
    if any(kw in msg for kw in ["谢谢", "感谢", "好评", "满意"]):
        return "满意"
    return default


def _policy_warnings(state: dict) -> list[str]:
    warnings = []
    for sop in state.get("sop_scenarios", [])[:1]:
        claims = [c for c in sop.get("forbidden_claims", []) if isinstance(c, str) and len(c) < 40]
        triggers = [c for c in sop.get("escalation_triggers", []) if isinstance(c, str) and len(c) < 40]
        if claims:
            warnings.append(f"禁止承诺: {', '.join(claims[:2])}")
        if triggers:
            warnings.append(f"升级触发: {', '.join(triggers[:2])}")
    return warnings


def _action_proposal(state: dict, default: dict) -> dict:
    sops = state.get("sop_scenarios", [])
    if not sops:
        return default
    valid_steps = [
        step for step in sops[0].get("steps", [])
        if isinstance(step, str) and len(step) < 50
        and not any(b in step for b in ["Codex", ".py", "markdown", "```", "POST /", "GET /"])
    ]
    if valid_steps:
        return {"action_type": valid_steps[0], "reason": f"根据SOP「{sops[0].get('scenario', '')}」"}
    return default


def _metrics_increment(key: str) -> None:
    try:
        from app.services.metrics_service import get_metrics_service
        get_metrics_service().increment(key)
    except Exception:
        pass
