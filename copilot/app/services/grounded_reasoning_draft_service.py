"""Shadow-only grounded reasoning draft builder.

This layer prepares a safer, more human draft for future reasoning experiments.
It never changes final replies, selected evidence, or sendability.
"""

from __future__ import annotations

import os
import re
from hashlib import sha256
from typing import Any

from app.services.admitted_answer_context_service import (
    COMPATIBLE_FACT_TYPES as _COMPATIBLE_FACT_TYPES,
    collect_admitted_product_facts,
)
from app.services.claim_polarity_service import contains_asserted_claim
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.fact_type_service import classify_query_fact_type


HIGH_RISK_FACT_TYPES = {
    "age_range",
    "child_suitability",
    "child_safety",
    "pinch_safety",
    "material_safety",
    "material",
    "odor",
    "certification_report",
    "load_capacity",
    "stability",
}

INSTALLATION_FACT_TYPES = {
    "installation",
    "installation_media",
    "installation_media_request",
    "accessory_usage",
    "accessory_compatibility",
    "structure_function",
}

MATERIAL_FACT_TYPES = {"material", "material_safety", "odor", "certification_report"}
CHILD_FACT_TYPES = {"age_range", "child_suitability", "child_safety", "pinch_safety"}
VISUAL_FACT_TYPES = {"dimensions", "structure", "space_fit", "placement_scene", "gross_weight"}
WEIGHT_FACT_TYPES = {"gross_weight"}

SYSTEM_COPY_TERMS = (
    "final gate",
    "rag",
    "evidence",
    "query_fact_type",
    "used_for_fact",
    "can_change_can_send",
    "reference_only",
    "系统",
    "风控",
    "证据不足",
)

MOJIBAKE_MARKERS = ("锛", "銆", "绛", "鍏", "瀹", "鏍", "闂", "鐢", "搴", "", "鈥", "�")

ABSOLUTE_CLAIM_TERMS = (
    "绝对安全",
    "肯定安全",
    "肯定不会夹",
    "一定不会夹",
    "不会夹手",
    "不会夹脚",
    "肯定无毒",
    "绝对无毒",
    "完全无毒",
    "放心咬",
    "适合2周岁",
    "适合两岁",
    "适合二岁",
    "适合0-6岁",
    "有检测报告",
    "有证书",
)

MEDIA_PROMISE_TERMS = ("发视频", "安装视频发", "下面视频", "发图片", "发图给您", "下面图片")


def grounded_reasoning_shadow_enabled() -> bool:
    return str(os.getenv("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = sanitize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clip(text: Any, limit: int = 160) -> str:
    value = sanitize_text(text)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _contains_any(text: str, terms: tuple[str, ...] | set[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _infer_fact_type(customer_message: str, query_fact_type: str) -> str:
    fact_type = sanitize_text(query_fact_type)
    if fact_type:
        return fact_type
    text = sanitize_text(customer_message)
    if _contains_any(text, ("夹手", "夹脚", "夹到", "防夹", "安全隐患")):
        return "pinch_safety"
    if _contains_any(text, ("咬", "啃", "入口", "中毒", "有毒", "无毒")):
        return "material_safety"
    if _contains_any(text, ("几岁", "多大", "周岁", "宝宝能不能用", "适合宝宝", "小孩能不能用")):
        return "age_range"
    if _contains_any(text, ("两层", "三层", "几层", "看图", "图片里")):
        return "structure"
    if _contains_any(text, ("多重", "毛重", "重量")):
        return "gross_weight"
    result = classify_query_fact_type(customer_message, intent="")
    return sanitize_text(result.get("query_fact_type"))


def _reply_blocks_have_media(reply_blocks: list[dict[str, Any]] | None, media_type: str = "") -> bool:
    blocks = [item for item in _as_list(reply_blocks) if isinstance(item, dict)]
    if media_type:
        return any(sanitize_text(item.get("type")).lower() == media_type for item in blocks)
    return any(sanitize_text(item.get("type")).lower() in {"image", "video"} for item in blocks)


def _answer_memory_action_hints(answer_memory_guidance: dict[str, Any] | None) -> list[str]:
    guidance = _as_dict(answer_memory_guidance)
    hints = []
    hints.extend(guidance.get("action_hints") or [])
    hints.extend(guidance.get("style_hints") or [])
    return _unique(hints)[:4]


def _fact_texts_by_type(used_facts: list[dict[str, Any]], *keywords: str) -> list[str]:
    result = []
    for fact in used_facts:
        haystack = " ".join(
            sanitize_text(fact.get(key)) for key in ("fact_type", "role", "text")
        ).lower()
        if any(keyword.lower() in haystack for keyword in keywords):
            result.append(sanitize_text(fact.get("text")))
    return _unique(result)[:3]


def _plan_fact_type_compatible(fact: dict[str, Any], query_fact_type: str) -> bool:
    fact_type = sanitize_text(fact.get("fact_type"))
    compatible = _COMPATIBLE_FACT_TYPES.get(query_fact_type, set())
    return not query_fact_type or not fact_type or fact_type in {query_fact_type, *compatible}


def _plan_identity_compatible(fact: dict[str, Any], product_identity: dict[str, Any]) -> bool:
    if sanitize_text(fact.get("fact_scope")).lower() in {"global", "all"}:
        return True
    expected = {
        key: sanitize_text(product_identity.get(key))
        for key in ("sku_code", "i_id", "product_id")
        if sanitize_text(product_identity.get(key))
    }
    scopes = {
        sanitize_text(scope.get("namespace")): sanitize_text(scope.get("value"))
        for scope in _as_list(fact.get("identity_scopes"))
        if isinstance(scope, dict)
    }
    if not expected or not scopes:
        return False
    return any(scopes.get(key) == value for key, value in expected.items())


def build_fact_coverage_plan(
    used_facts: list[dict[str, Any]],
    *,
    query_fact_type: str,
    product_identity: dict[str, Any] | None = None,
    requested_attribute_keys: list[str] | None = None,
    requested_fact_types: list[str] | None = None,
    request_scope: str = "unavailable",
    requested_attribute_source: str = "unavailable",
    request_contract_diagnostics: dict[str, Any] | None = None,
    max_fact_count: int = 3,
) -> dict[str, Any]:
    """Create a deterministic shadow-only plan from already admitted facts."""
    requested_keys = sorted(set(_unique(requested_attribute_keys or [])))
    requested_types = sorted(set(_unique(requested_fact_types or [])))
    normalized_scope = sanitize_text(request_scope).lower()
    if normalized_scope not in {"explicit", "broad", "unavailable"}:
        normalized_scope = "unavailable"
    candidates = [
        fact
        for fact in used_facts
        if sanitize_text(fact.get("evidence_uid"))
        and sanitize_text(fact.get("text"))
        and _plan_fact_type_compatible(fact, query_fact_type)
        and _plan_identity_compatible(fact, product_identity or {})
    ]
    candidates = sorted(
        candidates,
        key=lambda item: (
            sanitize_text(item.get("attribute_key")),
            sanitize_text(item.get("evidence_uid")),
            sanitize_text(item.get("text")),
        ),
    )
    warnings: list[str] = []
    if normalized_scope == "explicit" and requested_keys:
        selected = [
            item for item in candidates
            if sanitize_text(item.get("attribute_key")) in requested_keys
        ][:max_fact_count]
        selected_uids = {sanitize_text(item.get("evidence_uid")) for item in selected}
        omitted = [item for item in candidates if sanitize_text(item.get("evidence_uid")) not in selected_uids]
        available_keys = {sanitize_text(item.get("attribute_key")) for item in candidates}
        if any(key not in available_keys for key in requested_keys):
            warnings.append("requested_fact_missing")
        if len(selected) < len([item for item in candidates if sanitize_text(item.get("attribute_key")) in requested_keys]):
            warnings.append("max_fact_count_reached")
    elif len(candidates) <= max_fact_count:
        selected = candidates
        omitted = []
    else:
        selected = []
        omitted = candidates
        warnings.append("selection_ambiguous")
    clauses = [
        {
            "evidence_uid": sanitize_text(item.get("evidence_uid")),
            "attribute_key": sanitize_text(item.get("attribute_key")),
            "fact_type": sanitize_text(item.get("fact_type")),
            "source": sanitize_text(item.get("source")),
            "evidence_role": sanitize_text(item.get("evidence_role") or item.get("role")),
            "text": sanitize_text(item.get("text")),
            "identity_scope": _as_list(item.get("identity_scopes")),
        }
        for item in selected
    ]
    return {
        "composition_mode": "fact_bound_multi_clause" if len(clauses) > 1 else "single_fact" if clauses else "no_fact",
        "requested_fact_type": query_fact_type,
        "requested_attribute_keys": requested_keys,
        "requested_fact_types": requested_types,
        "request_scope": normalized_scope,
        "requested_attribute_source": sanitize_text(requested_attribute_source) or "unavailable",
        "request_contract_diagnostics": sanitize_obj(request_contract_diagnostics or {}),
        "candidate_evidence_uids": [sanitize_text(item.get("evidence_uid")) for item in candidates],
        "selected_evidence_uids": [clause["evidence_uid"] for clause in clauses],
        "omitted_evidence_uids": [sanitize_text(item.get("evidence_uid")) for item in omitted],
        "factual_clauses": clauses,
        "coverage_warnings": warnings,
        "max_fact_count": max_fact_count,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def render_draft_segments(segments: list[dict[str, Any]] | None) -> str:
    """Render the shadow draft from auditable segments only."""
    parts = [sanitize_text(item.get("text")) for item in _as_list(segments) if isinstance(item, dict)]
    return " ".join(part for part in parts if part).strip()


def _build_draft_segments(customer_copy: str, plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clauses = [item for item in _as_list(plan.get("factual_clauses")) if isinstance(item, dict)]
    segments: list[dict[str, Any]] = []
    if sanitize_text(customer_copy):
        segments.append({"type": "customer_copy", "text": sanitize_text(customer_copy)})
    for clause in clauses:
        segments.append(
            {
                "type": "factual_clause",
                "text": sanitize_text(clause.get("text")),
                "evidence_uid": sanitize_text(clause.get("evidence_uid")),
                "attribute_key": sanitize_text(clause.get("attribute_key")),
            }
        )
    rendered_uids = [
        sanitize_text(item.get("evidence_uid"))
        for item in segments
        if item.get("type") == "factual_clause" and sanitize_text(item.get("evidence_uid"))
    ]
    rendered = render_draft_segments(segments)
    return segments, {
        **plan,
        "rendered_evidence_uids": rendered_uids,
        "rendered_draft_hash": sha256(rendered.encode("utf-8")).hexdigest(),
    }


def _has_explicit_certificate_fact(used_facts: list[dict[str, Any]]) -> bool:
    return bool(_fact_texts_by_type(used_facts, "certification", "检测", "证书", "报告"))


def _default_forbidden_claims(query_fact_type: str) -> list[str]:
    claims = ["绝对安全", "肯定不会夹手", "肯定不会夹脚", "肯定无毒"]
    if query_fact_type in CHILD_FACT_TYPES:
        claims.extend(["适合2周岁", "适合两岁", "适合0-6岁", "保护宝宝安全"])
    if query_fact_type in MATERIAL_FACT_TYPES:
        claims.extend(["无毒", "有证书", "有检测报告"])
    if query_fact_type in INSTALLATION_FACT_TYPES:
        claims.extend(["下面发安装视频", "可以补发配件"])
    return _unique(claims)


def _build_child_draft(customer_message: str, used_facts: list[dict[str, Any]], has_video: bool, has_image: bool) -> tuple[str, list[str], list[str]]:
    structure_facts = _fact_texts_by_type(used_facts, "structure", "结构", "pinch", "夹", "safety", "安全")
    material_facts = _fact_texts_by_type(used_facts, "material", "材质")
    fact_part = ""
    if structure_facts:
        fact_part = f"我先按这款的结构说明看：{structure_facts[0]}。"
    elif material_facts:
        fact_part = f"我先按这款的材质说明看：{material_facts[0]}。"
    draft = (
        f"亲，宝宝使用和夹手这类问题要按这款的结构、材质和适用说明一起核对。{fact_part}"
        "如果是经常开合、抽拉或孩子会碰到的位置，建议先让大人陪同使用，您也可以把担心的位置拍一下，我一起帮您看清楚。"
    )
    inferred = ["儿童使用场景需要按结构和适用说明核对", "可引导客户补充关注位置照片"]
    missing = ["适用年龄说明", "防夹或儿童安全说明"]
    return draft, inferred, missing


def _build_material_draft(customer_message: str, used_facts: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    material_facts = _fact_texts_by_type(used_facts, "material", "材质", "odor", "气味", "certification_report")
    fact_part = f"这款资料里能看到的材质信息是：{material_facts[0]}。" if material_facts else ""
    if _contains_any(customer_message, ("咬", "啃", "入口", "吃到")):
        draft = (
            f"亲，宝宝咬到的话先别继续让宝宝啃咬，您先看下表面有没有掉屑、破损或误吞的情况。{fact_part}"
            "材质、气味和检测说明我按这款商品资料再核对一下，确认后给您准确口径。"
        )
        inferred = ["误咬场景先停止继续啃咬并检查掉屑、破损或误吞"]
    else:
        draft = (
            f"亲，材质、气味和检测说明我帮您按这款商品资料核对一下。{fact_part}"
            "这类信息我需要对照官方资料确认，避免给您说错，您稍等我确认后回复您。"
        )
        inferred = ["材质和检测类问题需要按官方资料核对"]
    missing = []
    if not material_facts:
        missing.append("材质说明")
    if not _has_explicit_certificate_fact(used_facts):
        missing.append("检测或认证资料")
    return draft, inferred, missing


def _build_installation_draft(
    customer_message: str,
    used_facts: list[dict[str, Any]],
    has_video_block: bool,
    has_image_block: bool,
) -> tuple[str, list[str], list[str]]:
    install_facts = _fact_texts_by_type(
        used_facts,
        "installation",
        "安装",
        "manual",
        "说明书",
        "配件",
        "accessory",
        "structure_function",
    )
    if has_video_block:
        media_part = "下面的视频可以先参考。"
        missing: list[str] = []
    elif has_image_block:
        media_part = "下面的安装图或说明页可以先参考。"
        missing = []
    else:
        media_part = "我先按这款的安装资料和说明书页核对，确认后给您准确口径。"
        missing = ["当前回复没有可发送的安装图、说明书或视频"]
    fact_part = f"资料里和安装相关的信息是：{install_facts[0]}。" if install_facts else ""
    draft = (
        f"亲，安装这块我帮您按当前款式核对。{fact_part}{media_part}"
        "如果是螺丝拧紧还松、孔位对不上或某个配件卡住，您可以拍一下对应位置，我一起帮您判断下一步怎么处理。"
    )
    inferred = ["安装问题可围绕孔位、配件位置、步骤和卡住位置继续核对"]
    return draft, inferred, missing


def _build_visual_draft(customer_message: str, used_facts: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    visual_facts = _fact_texts_by_type(used_facts, "dimensions", "尺寸", "structure", "结构", "layer", "层", "gross_weight", "重量")
    if visual_facts:
        draft = f"亲，我先按这款资料看：{visual_facts[0]}。如果您是要确认图片里的层数、空间或摆放位置，也可以把对应页面截图发我，我一起帮您对照。"
        missing: list[str] = []
    else:
        draft = "亲，您问的是图片里的层数、空间或摆放位置的话，我需要对照当前款式页面和图片位置看一下，避免只凭文字判断错。您可以把对应截图发我，我一起帮您确认。"
        missing = ["结构或尺寸资料"]
    inferred = ["视觉或结构判断需要对照当前款式页面和客户关注位置"]
    return draft, inferred, missing


def _build_weight_draft(used_facts: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    weight_facts = _fact_texts_by_type(used_facts, "gross_weight", "重量", "毛重")
    if weight_facts:
        draft = f"亲，我先按这款资料看：{weight_facts[0]}。如果您是想确认包装重量还是商品本体重量，我可以再按页面资料帮您分开核对。"
        missing: list[str] = []
    else:
        draft = "亲，重量这类信息我帮您按这款商品资料核对一下，确认是包装毛重还是商品本体重量后给您准确口径。"
        missing = ["重量或毛重资料"]
    inferred = ["重量问题需要区分包装毛重和商品本体重量"]
    return draft, inferred, missing


def _build_general_draft(
    customer_message: str,
    answer_memory_guidance: dict[str, Any] | None,
    used_facts: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    fact_text = sanitize_text(used_facts[0].get("text")) if used_facts else ""
    if fact_text:
        return (
            f"亲，这款资料里写的是：{fact_text}。如果您还想确认具体使用情况，我再按页面说明帮您对一下。",
            ["只围绕已准入的商品事实组织说明"],
            [],
        )
    hints = _answer_memory_action_hints(answer_memory_guidance)
    if hints:
        draft = f"亲，我先按当前商品和您的问题核对一下。{hints[0]}我确认清楚后给您准确回复。"
        return draft, ["可参考已审核的客服处理动作组织回复"], ["当前问题所需的商品或规则确认项"]
    return (
        "亲，我先按当前商品资料和您的问题核对一下，避免给您说错。您稍等，我确认后给您准确回复。",
        ["需先核对当前商品或订单上下文再组织回复"],
        ["当前问题所需的确认项"],
    )


def build_grounded_reasoning_draft(
    *,
    customer_message: str,
    query_fact_type: str = "",
    product_identity: dict[str, Any] | None = None,
    selected_evidence: list[dict[str, Any]] | None = None,
    product_context_pack: dict[str, Any] | None = None,
    answer_memory_guidance: dict[str, Any] | None = None,
    reply_blocks: list[dict[str, Any]] | None = None,
    requested_attribute_keys: list[str] | None = None,
    requested_fact_types: list[str] | None = None,
    request_scope: str = "unavailable",
    requested_attribute_source: str = "unavailable",
    request_contract_diagnostics: dict[str, Any] | None = None,
    risk_level: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    message = sanitize_text(customer_message)
    fact_type = _infer_fact_type(message, query_fact_type)
    admission_response = {
        "selected_evidence": selected_evidence or [],
        "product_context_pack": product_context_pack or {},
    }
    used_facts, rejected_evidence, admission_warnings = collect_admitted_product_facts(
        admission_response,
        product_identity=product_identity or {},
        requested_claim_types=[fact_type] if fact_type else [],
    )
    has_video = _reply_blocks_have_media(reply_blocks, "video")
    has_image = _reply_blocks_have_media(reply_blocks, "image")

    # The customer-copy builders may describe actions and safety boundaries, but
    # dynamic product facts are rendered only from the coverage plan below.
    if fact_type in CHILD_FACT_TYPES:
        draft, inferred, missing = _build_child_draft(message, [], has_video, has_image)
    elif fact_type in MATERIAL_FACT_TYPES:
        draft, inferred, missing = _build_material_draft(message, [])
    elif fact_type in INSTALLATION_FACT_TYPES:
        draft, inferred, missing = _build_installation_draft(message, [], has_video, has_image)
    elif fact_type in WEIGHT_FACT_TYPES:
        draft, inferred, missing = _build_weight_draft([])
    elif fact_type in VISUAL_FACT_TYPES:
        draft, inferred, missing = _build_visual_draft(message, [])
    else:
        draft, inferred, missing = _build_general_draft(message, answer_memory_guidance, [])

    fact_coverage_plan = build_fact_coverage_plan(
        used_facts,
        query_fact_type=fact_type,
        product_identity=product_identity,
        requested_attribute_keys=requested_attribute_keys,
        requested_fact_types=requested_fact_types,
        request_scope=request_scope,
        requested_attribute_source=requested_attribute_source,
        request_contract_diagnostics=request_contract_diagnostics,
    )
    draft_segments, fact_coverage_plan = _build_draft_segments(draft, fact_coverage_plan)
    draft = render_draft_segments(draft_segments)

    risk = sanitize_text(risk_level) or ("high" if fact_type in HIGH_RISK_FACT_TYPES else "medium")
    forbidden_claims = _unique(_default_forbidden_claims(fact_type) + _as_list(_as_dict(answer_memory_guidance).get("forbidden_claims")))
    if any(item.get("reason") in {"conflicting_evidence", "incomparable_unit_domain"} for item in rejected_evidence):
        missing.append("conflicting evidence requires review")
    requires_review = risk == "high" or bool(missing)
    safety_boundaries = [
        "只使用已选证据和当前商品资料中的事实",
        "Answer Memory 只提供表达和处理动作参考",
        "不改变最终回复和可发送状态",
    ]
    if fact_type in CHILD_FACT_TYPES:
        safety_boundaries.append("儿童适用和夹伤风险不做绝对安全承诺")
    if fact_type in MATERIAL_FACT_TYPES:
        safety_boundaries.append("材质、气味和检测信息不做无毒或证书承诺")
    if fact_type in INSTALLATION_FACT_TYPES and not (has_video or has_image):
        safety_boundaries.append("没有当前回复附带的安装素材时不承诺发图或视频")

    result = {
        "enabled": bool(enabled),
        "shadow_only": True,
        "used_for_final_reply": False,
        "can_change_can_send": False,
        "grounded_draft": sanitize_text(draft),
        "draft_segments": draft_segments,
        "draft_render_integrity_pass": True,
        "used_facts": used_facts,
        "fact_coverage_plan": fact_coverage_plan,
        "rejected_evidence": rejected_evidence,
        "admission_warnings": admission_warnings,
        "inferred_points": _unique(inferred),
        "safety_boundaries": _unique(safety_boundaries),
        "forbidden_claims": forbidden_claims,
        "missing_confirmations": _unique(missing),
        "requires_human_review": bool(requires_review),
        "risk_level": risk,
        "reasoning_mode": "fact_bound_safe_inference",
        "query_fact_type": fact_type,
        "product_identity": sanitize_obj(product_identity or {}),
        "answer_memory_action_hints": _answer_memory_action_hints(answer_memory_guidance),
    }
    return sanitize_obj(result)


def guidance_text(draft: dict[str, Any]) -> str:
    text_parts = [
        draft.get("grounded_draft") or "",
        *(draft.get("inferred_points") or []),
        *(draft.get("safety_boundaries") or []),
    ]
    return "\n".join(sanitize_text(part) for part in text_parts if sanitize_text(part))


def has_mojibake_draft(draft: dict[str, Any]) -> bool:
    text = guidance_text(draft)
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def has_internal_jargon_draft(draft: dict[str, Any]) -> bool:
    text = guidance_text(draft).lower()
    return any(term.lower() in text for term in SYSTEM_COPY_TERMS)


def has_forbidden_claim_violation(draft: dict[str, Any]) -> bool:
    text = sanitize_text(draft.get("grounded_draft"))
    forbidden = _unique(list(ABSOLUTE_CLAIM_TERMS) + _as_list(draft.get("forbidden_claims")))
    return any(contains_asserted_claim(text, term) for term in forbidden)


def has_unsupported_media_claim(draft: dict[str, Any], reply_blocks: list[dict[str, Any]] | None = None) -> bool:
    text = sanitize_text(draft.get("grounded_draft"))
    if not any(term in text for term in MEDIA_PROMISE_TERMS):
        return False
    if "视频" in text and _reply_blocks_have_media(reply_blocks, "video"):
        return False
    if ("图" in text or "图片" in text) and _reply_blocks_have_media(reply_blocks, "image"):
        return False
    return True


def used_answer_memory_as_fact(draft: dict[str, Any]) -> bool:
    for fact in draft.get("used_facts") or []:
        if "answer_memory" in sanitize_text(_as_dict(fact).get("source")).lower():
            return True
    return False


def is_generic_handoff_only(draft: dict[str, Any]) -> bool:
    text = sanitize_text(draft.get("grounded_draft"))
    if not text:
        return True
    generic_terms = ("核对", "确认", "稍等", "回复")
    specific_terms = ("材质", "气味", "检测", "宝宝", "夹", "安装", "螺丝", "孔位", "配件", "尺寸", "层", "物流", "订单")
    return all(term in text for term in generic_terms[:2]) and not any(term in text for term in specific_terms)


def _request_contract_from_response(
    response: dict[str, Any],
    debug: dict[str, Any],
    trace: dict[str, Any],
    context_used: dict[str, Any],
) -> dict[str, Any]:
    """Read only upstream structured request fields; never infer them from text."""
    containers = [
        ("response", response),
        ("response.turn_understanding", _as_dict(response.get("turn_understanding"))),
        ("evidence_debug.turn_understanding", _as_dict(debug.get("turn_understanding"))),
        ("answer_trace.turn_understanding", _as_dict(trace.get("turn_understanding"))),
        ("context_used.turn_understanding", _as_dict(context_used.get("turn_understanding"))),
    ]
    candidates: list[dict[str, Any]] = []
    for priority, (container_name, container) in enumerate(containers):
        keys = sorted(set(item.lower() for item in _unique(_as_list(container.get("requested_attribute_keys")))))
        types = sorted(set(item.lower() for item in _unique(_as_list(container.get("requested_fact_types")))))
        scope = sanitize_text(container.get("request_scope")).lower()
        if scope not in {"explicit", "broad", "unavailable"}:
            scope = "explicit" if keys else "unavailable"
        if not keys and not types and scope == "unavailable":
            continue
        reliability = 3 if scope == "explicit" and keys else 2 if scope == "explicit" else 1 if scope == "broad" else 0
        candidates.append(
            {
                "container": container_name,
                "priority": priority,
                "reliability": reliability,
                "requested_attribute_keys": keys,
                "requested_fact_types": types,
                "request_scope": scope,
                "requested_attribute_source": sanitize_text(container.get("requested_attribute_source")) or container_name,
            }
        )
    if candidates:
        candidates.sort(key=lambda item: (-int(item["reliability"]), int(item["priority"])))
        selected = candidates[0]
        equally_reliable = [item for item in candidates if item["reliability"] == selected["reliability"]]
        signatures = {
            (tuple(item["requested_attribute_keys"]), tuple(item["requested_fact_types"]), item["request_scope"])
            for item in equally_reliable
        }
        return {
            **selected,
            "candidate_count": len(candidates),
            "request_contract_conflict": len(signatures) > 1,
            "request_contract_conflict_reason": "same_reliability_contract_conflict" if len(signatures) > 1 else "",
        }
    return {
        "requested_attribute_keys": [],
        "requested_fact_types": [],
        "request_scope": "unavailable",
        "requested_attribute_source": "unavailable",
        "container": "",
        "candidate_count": 0,
        "request_contract_conflict": False,
        "request_contract_conflict_reason": "",
    }


class GroundedReasoningDraftService:
    def build_for_response(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        product_identity: dict[str, Any] | None = None,
        answer_memory_guidance: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        debug = _as_dict(response.get("evidence_debug"))
        trace = _as_dict(response.get("answer_trace"))
        context_used = _as_dict(response.get("context_used"))
        product_pack = (
            _as_dict(response.get("product_context_pack"))
            or _as_dict(context_used.get("product_context_pack"))
            or _as_dict(debug.get("product_context_pack_summary"))
        )
        selected = response.get("selected_evidence") or debug.get("selected_evidence") or []
        fact_type = (
            response.get("query_fact_type")
            or debug.get("query_fact_type")
            or trace.get("query_fact_type")
            or _as_dict(product_pack.get("product_first_evidence_pack")).get("requested_fact_type")
            or ""
        )
        identity = product_identity or {
            "product_name": response.get("matched_product_name") or debug.get("matched_product_name"),
            "sku_code": response.get("sku_code") or debug.get("sku_code"),
            "i_id": response.get("i_id") or debug.get("i_id"),
        }
        request_contract = _request_contract_from_response(response, debug, trace, context_used)
        return build_grounded_reasoning_draft(
            customer_message=customer_message,
            query_fact_type=sanitize_text(fact_type),
            product_identity=identity,
            selected_evidence=selected if isinstance(selected, list) else [],
            product_context_pack=product_pack,
            answer_memory_guidance=answer_memory_guidance or response.get("answer_memory_guidance") or {},
            reply_blocks=response.get("reply_blocks") if isinstance(response.get("reply_blocks"), list) else [],
            requested_attribute_keys=request_contract["requested_attribute_keys"],
            requested_fact_types=request_contract["requested_fact_types"],
            request_scope=request_contract["request_scope"],
            requested_attribute_source=request_contract["requested_attribute_source"],
            request_contract_diagnostics={
                "selected_container": request_contract["container"],
                "candidate_count": request_contract["candidate_count"],
                "request_contract_conflict": request_contract["request_contract_conflict"],
                "request_contract_conflict_reason": request_contract["request_contract_conflict_reason"],
            },
            risk_level=response.get("risk_level") or debug.get("risk_level") or "",
            enabled=enabled,
        )

    def attach_shadow_draft(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        product_identity: dict[str, Any] | None = None,
        answer_memory_guidance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        draft = self.build_for_response(
            response,
            customer_message=customer_message,
            product_identity=product_identity,
            answer_memory_guidance=answer_memory_guidance,
            enabled=True,
        )
        response["grounded_reasoning_draft"] = draft
        response.setdefault("evidence_debug", {})["grounded_reasoning_draft"] = draft
        response.setdefault("answer_trace", {})["grounded_reasoning_draft"] = {
            "enabled": True,
            "shadow_only": True,
            "used_for_final_reply": False,
            "can_change_can_send": False,
            "used_fact_count": len(draft.get("used_facts") or []),
            "requires_human_review": bool(draft.get("requires_human_review")),
            "risk_level": draft.get("risk_level"),
            "query_fact_type": draft.get("query_fact_type"),
            "composition_mode": _as_dict(draft.get("fact_coverage_plan")).get("composition_mode"),
            "planned_fact_count": len(_as_list(_as_dict(draft.get("fact_coverage_plan")).get("factual_clauses"))),
            "requested_attribute_keys": _as_list(_as_dict(draft.get("fact_coverage_plan")).get("requested_attribute_keys")),
            "request_scope": _as_dict(draft.get("fact_coverage_plan")).get("request_scope"),
        }
        return response
