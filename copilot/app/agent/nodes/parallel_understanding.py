from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.agent.schemas.understanding import AnalyzerResult, ParallelUnderstandingResult, SafetyContract
from app.services.aftersales_intent_service import classify_colloquial_aftersales


TRACKING_PATTERNS = [
    r"(?<![A-Za-z0-9])(SF\d{10,18})(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])(YT\d{10,18})(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])(ZTO\d{10,18})(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])(JD\d{10,18})(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])(YD\d{10,18})(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])(JT\d{10,18})(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])(EMS\d{9,18})(?![A-Za-z0-9])",
]

LONG_NUMERIC_PATTERN = r"(?<![A-Za-z0-9])(\d{18,22})(?![A-Za-z0-9])"
ORDER_SEMANTIC_PATTERN = r"(?:订单号|订单|o_id|单号)\s*[:：]?\s*([A-Za-z0-9\-]{4,30})"
PRODUCT_WORDS = ("书架", "围兜", "防摔枕", "爬行垫", "围栏", "尿布台", "柜", "餐椅", "桌")
MATERIAL_WORDS = ("实木", "原木", "材质", "板材", "木头", "填充", "记忆棉", "海绵")
SIZE_WORDS = ("尺寸", "高度", "宽度", "厚度", "多大", "承重", "适合几岁", "适合多大")
INSTALL_WORDS = ("安装", "组装", "怎么装", "说明书")
LOGISTICS_WORDS = ("快递", "物流", "发货", "到哪", "到哪里", "什么时候到", "几天到", "多久到", "签收", "没收到")
ETA_CERTAINTY_WORDS = ("一定到", "保证到", "肯定到", "明天能不能")
COMPLAINT_WORDS = ("投诉", "平台介入", "差评", "曝光", "再不处理", "告你", "12315")
AFTERSALES_WORDS = ("退货", "退款", "售后", "赔偿", "赔", "补发", "破损", "坏了", "少件", "少了", "漏发", "发错")


AnalyzerFn = Callable[[dict], dict[str, Any]]


def parallel_understanding(state: dict) -> dict:
    t0 = time.time()
    analyzers: dict[str, AnalyzerFn] = {
        "intent_classifier": _intent_classifier,
        "risk_classifier": _risk_classifier,
        "slot_entity_extractor": _slot_entity_extractor,
        "context_resolver": _context_resolver,
        "customer_state_analyzer": _customer_state_analyzer,
        "tool_need_predictor": _tool_need_predictor,
        "knowledge_scope_predictor": _knowledge_scope_predictor,
        "safety_precheck": _safety_precheck,
    }
    results: dict[str, AnalyzerResult] = {}
    warnings: list[str] = []

    with ThreadPoolExecutor(max_workers=len(analyzers)) as executor:
        futures = {executor.submit(_run_analyzer, name, fn, state): name for name, fn in analyzers.items()}
        for future in as_completed(futures):
            result = future.result()
            results[result.name] = result
            if result.status != "success":
                warnings.append(f"{result.name}:{result.status}:{result.error_code}")

    analyzer_durations = {name: result.duration_ms for name, result in results.items()}
    overall_status = "degraded" if warnings else "success"
    payload = ParallelUnderstandingResult(
        intent_classifier=results["intent_classifier"].to_dict(),
        risk_classifier=results["risk_classifier"].to_dict(),
        slot_entity_extractor=results["slot_entity_extractor"].to_dict(),
        context_resolver=results["context_resolver"].to_dict(),
        customer_state_analyzer=results["customer_state_analyzer"].to_dict(),
        tool_need_predictor=results["tool_need_predictor"].to_dict(),
        knowledge_scope_predictor=results["knowledge_scope_predictor"].to_dict(),
        safety_precheck=results["safety_precheck"].to_dict(),
        analyzer_durations=analyzer_durations,
        overall_status=overall_status,
        warnings=warnings,
    ).to_dict()

    duration_ms = int((time.time() - t0) * 1000)
    traces = []
    for name in sorted(results):
        result = results[name]
        traces.append({
            "node": "parallel_understanding",
            "analyzer": name,
            "status": result.status,
            "duration_ms": result.duration_ms,
            "confidence": result.confidence,
            "summary": _summary_for(name, result),
        })
    traces.append({
        "node": "parallel_understanding",
        "status": overall_status,
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"parallel analyzers={len(results)}, warnings={len(warnings)}",
    })

    return {
        "parallel_understanding": payload,
        "analyzer_durations": analyzer_durations,
        "trace_steps": state.get("trace_steps", []) + traces,
    }


def _run_analyzer(name: str, fn: AnalyzerFn, state: dict) -> AnalyzerResult:
    t0 = time.time()
    try:
        data = fn(state)
        confidence = float(data.get("confidence", 0.8))
        return AnalyzerResult(
            name=name,
            status="success",
            duration_ms=int((time.time() - t0) * 1000),
            confidence=confidence,
            data=data,
        )
    except Exception as exc:
        return AnalyzerResult(
            name=name,
            status="failed",
            duration_ms=int((time.time() - t0) * 1000),
            confidence=0.0,
            data={},
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )


def _text(state: dict) -> str:
    msg = state.get("normalized_message") or state.get("customer_message", "")
    # 合并 customer 会话历史（不含 agent 回复），用于跨轮次理解；当前消息只算一次
    ctx = state.get("copilot_context", {}) or {}
    history = ctx.get("conversation_history", []) or []
    parts = [msg or ""]
    for item in history:
        if not isinstance(item, dict) or item.get("role") != "customer":
            continue
        from app.services.canonical_conversation_turn_service import turn_content
        t = turn_content(item)
        if t and t != msg and t not in parts:
            parts.append(t)
    return " ".join(p for p in parts if p)


def _current_text(state: dict) -> str:
    """Return only the current buyer message for current-turn classifiers.

    Raw history is contextual evidence, not another copy of the current turn.
    Reclassifying concatenated history revives already answered or unrelated
    intents and loses role/order semantics.
    """
    return str(
        state.get("normalized_message")
        or state.get("customer_message", "")
        or ""
    )


def _intent_classifier(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    identifiers = _extract_identifiers(text)
    colloquial_aftersales = classify_colloquial_aftersales(text)

    # 各意图命中检测：用于 primary 优先级，同时用于 secondary 多意图（避免漏答）
    _checks = {
        "missing_item": any(w in text for w in ("少件", "少了", "漏发", "缺配件", "少了配件", "缺件")),
        "damaged_item": any(w in text for w in ("破损", "坏了", "损坏", "掉了", "掉落", "断了", "断裂", "裂了", "开裂")),
        "wrong_item": any(w in text for w in ("发错", "错货", "不是我拍的", "不是我买的", "收到的不是")),
        "refund_request": any(w in text for w in ("退款", "退钱")),
        "return_request": any(w in text for w in ("退货", "退回")),
        "installation_question": any(w in text for w in INSTALL_WORDS),
        "material_question": any(w in text for w in MATERIAL_WORDS),
        "size_question": any(w in text for w in SIZE_WORDS),
        "product_question": any(w in text for w in PRODUCT_WORDS),
    }

    secondary: list[str] = []
    if any(w in text for w in COMPLAINT_WORDS):
        secondary.append("complaint")
        if "再不" in text or "曝光" in text or "平台" in text:
            secondary.append("complaint_threat")

    if identifiers and any(w in text for w in LOGISTICS_WORDS):
        primary = "logistics_eta"
    elif any(w in text for w in ("签收", "没收到", "未收到")):
        primary = "delivery_not_received"
    elif any(w in text for w in LOGISTICS_WORDS + ETA_CERTAINTY_WORDS):
        primary = "logistics_eta"
    elif any(w in text for w in COMPLAINT_WORDS):
        primary = "complaint"
    elif colloquial_aftersales.get("matched"):
        subtype = colloquial_aftersales.get("subtype")
        if ("掉" in text or "脱落" in text) and any(w in text for w in ("零件", "配件", "部件")):
            primary = "damaged_item"
        elif _checks["missing_item"]:
            primary = "missing_item"
        else:
            primary = {
                "replacement_request": "missing_item",
                "missing_item": "missing_item",
                "damaged_item": "damaged_item",
                "wrong_item": "wrong_item",
            }.get(subtype, "missing_item")
    elif _checks["missing_item"]:
        primary = "missing_item"
    elif _checks["damaged_item"]:
        primary = "damaged_item"
    elif _checks["wrong_item"]:
        primary = "wrong_item"
    elif _checks["refund_request"]:
        primary = "refund_request"
    elif _checks["return_request"]:
        primary = "return_request"
    elif _checks["installation_question"]:
        primary = "installation_question"
    elif _checks["material_question"]:
        primary = "material_question"
    elif _checks["size_question"]:
        primary = "size_question"
    elif _checks["product_question"]:
        primary = "product_question"
    else:
        primary = "general"

    # 多意图：把其它命中的意图也纳入 secondary，避免只保留一个导致漏答
    for _label in (
        "missing_item", "damaged_item", "wrong_item", "refund_request",
        "return_request", "installation_question", "material_question",
        "size_question", "product_question",
    ):
        if _checks.get(_label) and _label != primary and _label not in secondary:
            secondary.append(_label)

    if primary in ("material_question", "size_question", "installation_question"):
        if "product_question" not in secondary:
            secondary.append("product_question")
    if primary.startswith("logistics") and "complaint" in secondary:
        secondary.append("logistics_eta")

    return {
        "primary_intent": primary,
        "secondary_intents": _unique(secondary),
        "confidence": 0.9 if primary != "general" else 0.55,
    }


def _risk_classifier(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    reasons = []
    level = "low"

    high_words = ("投诉", "平台介入", "曝光", "12315", "孩子受伤", "安全事故", "再不处理", "告你")
    damaged_words = ("破损", "坏了", "损坏", "掉了", "掉落", "断了", "断裂", "裂了", "开裂")
    medium_words = ("差评", "赔偿", "赔", "补发", "退款", "少件", "少了", "漏发", "发错", "签收没收到", "没收到") + damaged_words
    if any(w in text for w in high_words):
        level = "high"
        reasons.extend([w for w in high_words if w in text])
    elif any(w in text for w in medium_words):
        level = "medium"
        reasons.extend([w for w in medium_words if w in text])

    return {
        "risk_level": level,
        "risk_reasons": reasons,
        "need_human_review": level == "high" or any(w in text for w in ("少件", "少了", "漏发", "发错", "赔", "签收没收到", "没收到") + damaged_words),
        "confidence": 0.9,
    }


def _slot_entity_extractor(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    identifiers = _extract_identifiers(text)
    product_mentions = [w for w in PRODUCT_WORDS if w in text]
    sku_mentions = re.findall(r"([一二三四五六七八九十百千万0-9]+号[^，。！？\s]{0,12})", text)
    missing_slots = []
    if any(w in text for w in LOGISTICS_WORDS) and not identifiers:
        missing_slots.extend(["order_id", "tracking_no"])
    if any(w in text for w in MATERIAL_WORDS) and not product_mentions and not sku_mentions:
        missing_slots.extend(["product_link", "sku"])
    return {
        "identifiers": identifiers,
        "product_mentions": _unique(product_mentions),
        "sku_mentions": _unique(sku_mentions),
        "missing_slots": _unique(missing_slots),
        "confidence": 0.9 if identifiers or product_mentions or sku_mentions else 0.65,
    }


def _context_resolver(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    ctx = state.get("conversation_context") or {}
    requested = ctx.get("last_requested_slots", []) or []
    identifiers = _extract_identifiers(text)
    fills_requested_slot = ""
    if identifiers and any(slot in requested for slot in ("order_id", "tracking_no")):
        fills_requested_slot = "order_id_or_trade_id"
    active_issue = ctx.get("active_issue", "")
    is_followup = bool(fills_requested_slot or (len(text.strip()) <= 24 and active_issue))
    return {
        "is_followup": is_followup,
        "fills_requested_slot": fills_requested_slot,
        "active_issue": active_issue,
        "known_order_id": ctx.get("known_order_id", ""),
        "known_tracking_no": ctx.get("known_tracking_no", ""),
        "known_product": ctx.get("confirmed_product", ""),
        "confidence": 0.8 if is_followup else 0.6,
    }


def _customer_state_analyzer(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    emotion = "calm"
    concern = "unknown"
    urgency = "low"
    needs_empathy = False
    needs_boundary = False
    needs_clarification = False

    if any(w in text for w in COMPLAINT_WORDS):
        emotion = "angry"
        concern = "angry_about_delay"
        urgency = "high"
        needs_empathy = True
    elif any(w in text for w in ETA_CERTAINTY_WORDS):
        emotion = "anxious"
        concern = "wants_eta_certainty"
        urgency = "medium"
        needs_boundary = True
    elif any(w in text for w in MATERIAL_WORDS):
        emotion = "confused"
        concern = "worries_material"
        needs_clarification = True
    elif any(w in text for w in ("没收到", "丢了", "签收")):
        emotion = "anxious"
        concern = "worries_package_lost"
        urgency = "medium"
        needs_empathy = True
    elif any(w in text for w in ("少件", "少了", "漏发")):
        emotion = "frustrated"
        concern = "missing_item_concern"
        urgency = "medium"
        needs_empathy = True

    return {
        "customer_emotion": emotion,
        "customer_concern": concern,
        "urgency_level": urgency,
        "needs_empathy": needs_empathy,
        "needs_boundary_setting": needs_boundary,
        "needs_clarification": needs_clarification,
        "confidence": 0.85,
    }


def _tool_need_predictor(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    identifiers = _extract_identifiers(text)
    ctx = state.get("conversation_context") or {}
    active_issue = ctx.get("active_issue", "")
    required: list[str] = []
    allowed = [
        "jst_lookup_order_tool",
        "jst_lookup_outbound_tool",
        "jst_lookup_tracking_tool",
        "rag_search_tool",
        "product_resolver_tool",
        "sop_lookup_tool",
        "template_select_tool",
    ]
    forbidden: list[str] = []

    id_types = {item["type"] for item in identifiers}
    if "tracking_no" in id_types:
        required.append("jst_lookup_tracking_tool")
    elif (
        "platform_trade_id" in id_types
        or ("unknown_identifier" in id_types and active_issue in ("delivery_not_received", "logistics_eta", "logistics_tracking"))
    ) and (any(w in text for w in LOGISTICS_WORDS) or active_issue in ("delivery_not_received", "logistics_eta", "logistics_tracking")):
        required.append("jst_lookup_outbound_tool")
    elif any(item["type"] == "internal_order_id" for item in identifiers):
        required.append("jst_lookup_order_tool")

    if any(w in text for w in PRODUCT_WORDS + MATERIAL_WORDS + SIZE_WORDS + INSTALL_WORDS):
        required.extend(["product_resolver_tool", "rag_search_tool"])
        if not any(w in text for w in LOGISTICS_WORDS):
            forbidden.extend(["jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"])
    if any(w in text for w in COMPLAINT_WORDS + AFTERSALES_WORDS):
        required.append("sop_lookup_tool")

    return {
        "required_tools": _unique(required),
        "allowed_tools": allowed,
        "forbidden_tools": _unique([tool for tool in forbidden if tool not in required]),
        "confidence": 0.85,
    }


def _knowledge_scope_predictor(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    allowed: list[str] = []
    forbidden: list[str] = []
    if any(w in text for w in MATERIAL_WORDS + SIZE_WORDS):
        allowed.extend(["product_facts", "faq"])
    if any(w in text for w in INSTALL_WORDS):
        allowed.extend(["installation_guide", "faq"])
    if any(w in text for w in LOGISTICS_WORDS + ETA_CERTAINTY_WORDS):
        allowed.extend(["shipping_policy", "faq"])
    if any(w in text for w in ("退货", "退款", "售后")):
        allowed.extend(["aftersales_policy", "faq"])
    if any(w in text for w in COMPLAINT_WORDS + ("赔偿",)):
        allowed.extend(["high_risk_sop", "forbidden_rules"])
    return {
        "allowed_source_types": _unique(allowed) or ["faq", "response_templates"],
        "forbidden_source_types": forbidden,
        "confidence": 0.8,
    }


def _safety_precheck(state: dict) -> dict[str, Any]:
    text = _current_text(state)
    contract = SafetyContract()
    if any(w in text for w in ETA_CERTAINTY_WORDS) or any(w in text for w in ("什么时候到", "几天到", "多久到")):
        contract.forbidden_claims.extend(["一定到", "保证到", "肯定到"])
        contract.requires_evidence_for.extend(["物流状态", "发货状态"])
        if any(w in text for w in ETA_CERTAINTY_WORDS):
            contract.must_include.append("不能承诺一定到")
    if any(w in text for w in MATERIAL_WORDS):
        contract.forbidden_claims.extend(["实木", "不是实木"])
        contract.requires_evidence_for.append("材质")
    if any(w in text for w in COMPLAINT_WORDS):
        contract.must_escalate_if.extend(["complaint", "platform_escalation"])
        contract.forbidden_claims.extend(["承诺赔偿", "保证解决"])
        contract.must_include.append("转人工核实")
    if any(w in text for w in ("少件", "破损", "坏了", "发错", "赔")):
        contract.must_escalate_if.append("manual_followup")
        contract.forbidden_claims.extend(["直接补发", "直接赔偿", "承诺赔偿", "保证赔"])
    contract.allowed_fact_sources.extend(["jst", "rag", "product_facts", "faq", "sop"])
    return {**contract.to_dict(), "confidence": 0.85}


def _extract_identifiers(text: str) -> list[dict[str, Any]]:
    identifiers: list[dict[str, Any]] = []
    for pattern in TRACKING_PATTERNS:
        for match in re.finditer(pattern, text or "", re.IGNORECASE):
            identifiers.append({
                "type": "tracking_no",
                "value": match.group(1).upper(),
                "source": "message",
                "confidence": 0.95,
            })
    for match in re.finditer(ORDER_SEMANTIC_PATTERN, text or "", re.IGNORECASE):
        value = match.group(1)
        if re.fullmatch(r"\d{18,22}", value):
            continue
        identifiers.append({
            "type": "internal_order_id",
            "value": value,
            "source": "message",
            "confidence": 0.9,
        })
    for match in re.finditer(LONG_NUMERIC_PATTERN, text or ""):
        value = match.group(1)
        nearby = text[max(0, match.start() - 12): match.end() + 12]
        id_type = "platform_trade_id" if any(w in nearby for w in ("交易", "平台", "外部", "天猫", "淘宝", "订单", "快递", "物流")) else "unknown_identifier"
        identifiers.append({
            "type": id_type,
            "value": value,
            "source": "message",
            "confidence": 0.85 if id_type == "platform_trade_id" else 0.7,
        })
    return _dedupe_identifiers(identifiers)


def _dedupe_identifiers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        key = (item.get("type"), item.get("value"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _unique(items: list[str] | tuple[str, ...]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _summary_for(name: str, result: AnalyzerResult) -> str:
    data = result.data or {}
    if name == "intent_classifier":
        return f"primary={data.get('primary_intent')} secondary={data.get('secondary_intents', [])}"
    if name == "risk_classifier":
        return f"risk={data.get('risk_level')} human_review={data.get('need_human_review')}"
    if name == "slot_entity_extractor":
        return f"identifiers={len(data.get('identifiers', []))} products={data.get('product_mentions', [])}"
    if name == "tool_need_predictor":
        return f"required={data.get('required_tools', [])}"
    return f"status={result.status}"
