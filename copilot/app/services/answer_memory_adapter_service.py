"""Shadow adapter for Answer Memory.

The adapter converts answer-memory search hits into generation guidance. It is
explicitly not evidence and cannot change sendability.
"""

from __future__ import annotations

import os
from typing import Any

from app.services.answer_memory_service import AnswerMemoryService, infer_scenario_type, plain_text
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.fact_type_service import classify_query_fact_type

MOJIBAKE_GUIDANCE_MARKERS = (
    "锛",
    "銆",
    "绛",
    "鍏",
    "瀹",
    "鏍",
    "闂",
    "鐢",
    "搴",
    "",
    "€",
    "鈥",
    "�",
)

INTERNAL_GUIDANCE_TERMS = (
    "rag",
    "final gate",
    "evidence",
    "query_fact_type",
    "used_for_fact",
    "can_change_can_send",
    "reference_only",
    "风控",
    "证据不足",
)


def answer_memory_shadow_enabled() -> bool:
    return str(os.getenv("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _clip(text: str, limit: int = 180) -> str:
    text = sanitize_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _unique(values: list[Any]) -> list[str]:
    seen = set()
    result: list[str] = []
    for value in values:
        text = sanitize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def guidance_copy_text(guidance: dict[str, Any]) -> str:
    parts = []
    parts.extend(guidance.get("style_hints") or [])
    parts.extend(guidance.get("action_hints") or [])
    parts.append(guidance.get("draft_guidance") or "")
    return "\n".join(sanitize_text(part) for part in parts if sanitize_text(part))


def has_mojibake_guidance(guidance: dict[str, Any]) -> bool:
    text = guidance_copy_text(guidance)
    return any(marker in text for marker in MOJIBAKE_GUIDANCE_MARKERS)


def has_internal_jargon_guidance(guidance: dict[str, Any]) -> bool:
    text = guidance_copy_text(guidance).lower()
    return any(term.lower() in text for term in INTERNAL_GUIDANCE_TERMS)


def _action_hints_from_memory(memory: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    scenario = sanitize_text(memory.get("scenario_type"))
    if scenario == "aftersales":
        hints.append("先承接情绪，再核对订单和问题信息；需要时请买家补充照片、位置或包装信息。")
    elif scenario == "installation":
        hints.append("围绕安装步骤、卡住的位置、配件位置或说明书页组织回复；不要扩展无关商品事实。")
    elif scenario == "promotion":
        hints.append("围绕当前页面活动、优惠券、满减或赠品规则核对；不要承诺额外优惠。")
    elif scenario == "logistics":
        hints.append("围绕当前订单物流、发货或配送服务核对；不要承诺后台状态。")
    return _unique(hints)


def _style_hints_from_memory(memory: dict[str, Any]) -> list[str]:
    scenario = sanitize_text(memory.get("scenario_type"))
    risk = sanitize_text(memory.get("risk_level"))
    hints = ["用自然客服语气表达，像人工接待一样先回应客户关切。"]
    if risk == "high":
        hints.append("高风险事实只给安全边界和待确认项，不直接下结论。")
    if scenario == "aftersales":
        hints.append("先承接情绪，再说明核对动作和下一步。")
    return _unique(hints)


def build_answer_memory_guidance(memories: list[dict[str, Any]], *, enabled: bool = True) -> dict[str, Any]:
    matched = []
    style_hints: list[str] = []
    action_hints: list[str] = []
    forbidden_claims: list[str] = []
    required_fact_types: list[str] = []
    high_risk = False
    verified_reference_count = 0

    for memory in memories:
        item = sanitize_obj(
            {
                "memory_uid": memory.get("memory_uid"),
                "match_score": memory.get("match_score"),
                "answer_quality": memory.get("answer_quality"),
                "review_status": memory.get("review_status"),
                "scenario_type": memory.get("scenario_type"),
                "query_fact_type": memory.get("query_fact_type"),
                "risk_level": memory.get("risk_level"),
                "reference_only": True,
                "used_for_fact": False,
                "can_change_can_send": False,
                "requires_human_review": True if memory.get("risk_level") == "high" else bool(memory.get("requires_human_review", True)),
                "source_type": memory.get("source_type"),
            }
        )
        matched.append(item)
        style_hints.extend(_style_hints_from_memory(memory))
        action_hints.extend(_action_hints_from_memory(memory))
        forbidden_claims.extend(memory.get("forbidden_claims") or [])
        required_fact_types.extend(memory.get("required_fact_types") or [])
        high_risk = high_risk or sanitize_text(memory.get("risk_level")) == "high"
        if sanitize_text(memory.get("answer_quality")) == "verified_answer":
            verified_reference_count += 1

    return sanitize_obj(
        {
            "enabled": bool(enabled),
            "reference_only": True,
            "used_for_fact": False,
            "can_change_can_send": False,
            "matched_memories": matched,
            "style_hints": _unique(style_hints),
            "action_hints": _unique(action_hints),
            "forbidden_claims": _unique(forbidden_claims),
            "required_fact_types": _unique(required_fact_types),
            "risk_level": "high" if high_risk else ("medium" if matched else ""),
            "draft_guidance": "；".join(_unique(action_hints)[:3]),
            "verified_reference_count": verified_reference_count,
            "reference_only_count": len(matched),
            "high_risk_guidance_count": sum(1 for item in matched if item.get("risk_level") == "high"),
        }
    )


class AnswerMemoryAdapterService:
    def __init__(self, answer_memory_service: AnswerMemoryService | None = None):
        self.answer_memory_service = answer_memory_service or AnswerMemoryService()

    def build_for_context(
        self,
        *,
        customer_message: str,
        product_i_id: str = "",
        sku_code: str = "",
        product_title: str = "",
        query_fact_type: str = "",
        scenario_type: str = "",
        limit: int = 5,
        db_factory=None,
    ) -> dict[str, Any]:
        question = sanitize_text(plain_text(customer_message))
        fact_type = sanitize_text(query_fact_type)
        if not fact_type and question:
            fact = classify_query_fact_type(question, intent="")
            fact_type = sanitize_text(fact.get("query_fact_type"))
        scenario = sanitize_text(scenario_type)
        if not scenario:
            scenario = infer_scenario_type({"question_type": ""}, fact_type)
        hits = self.answer_memory_service.search_answer_memory(
            product_i_id=product_i_id,
            sku_code=sku_code,
            product_title=product_title,
            query_fact_type=fact_type,
            scenario_type=scenario,
            customer_message=question,
            limit=limit,
            db_factory=db_factory,
        )
        return build_answer_memory_guidance(hits, enabled=True)

    def attach_shadow_guidance(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        product_i_id: str = "",
        sku_code: str = "",
        product_title: str = "",
        copilot_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
        trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
        context = copilot_context if isinstance(copilot_context, dict) else {}
        guidance = self.build_for_context(
            customer_message=customer_message,
            product_i_id=product_i_id or debug.get("i_id") or trace.get("i_id") or context.get("i_id") or "",
            sku_code=sku_code or debug.get("sku_code") or trace.get("sku_code") or context.get("sku_code") or "",
            product_title=product_title
            or debug.get("matched_product_name")
            or trace.get("product_title")
            or context.get("product_name")
            or context.get("product_title")
            or "",
            query_fact_type=debug.get("query_fact_type") or trace.get("query_fact_type") or response.get("query_fact_type") or "",
            scenario_type=debug.get("scenario_type") or trace.get("scenario_type") or "",
        )
        response["answer_memory_guidance"] = guidance
        response.setdefault("evidence_debug", {})["answer_memory_guidance"] = guidance
        response.setdefault("answer_trace", {})["answer_memory_guidance"] = {
            "enabled": guidance["enabled"],
            "reference_only": True,
            "used_for_fact": False,
            "can_change_can_send": False,
            "hit_count": len(guidance.get("matched_memories") or []),
            "forbidden_claims": guidance.get("forbidden_claims") or [],
            "required_fact_types": guidance.get("required_fact_types") or [],
        }
        return response
