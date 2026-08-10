"""
factual_guard 节点 - 事实校验（扩展版）
A. 订单事实保护
B. 物流政策保护
C. 商品事实保护
D. 售后保护
E. 高风险保护
F. Knowledge Evidence Quality Gate (Phase 2.5)
"""
import logging
import re
import time

from app import config
from app.services.evidence_quality_gate import enforce_evidence_quality_gate

logger = logging.getLogger(__name__)


# 安全承诺短语（包含"承诺/确保"但不危险，不参与危险判断）
_SAFE_PROMISE_PHRASES = [
    "页面承诺时效", "店铺页面承诺时效", "详情页承诺时效",
    "以页面承诺时效为准", "按店铺页面展示时效安排", "以订单页显示为准",
    "以实际物流为准", "按平台规则安排", "按店铺规则安排",
    "承诺时效", "承诺的时效", "页面承诺", "店铺承诺",
    "确保安全", "确保质量", "确保正常使用", "确保准确",
]

# 危险承诺模式：承诺词 + 结果动作（中间最多4个任意字符）
_DANGEROUS_PROMISE_PATTERNS = [
    r"(?:一定|保证|肯定|绝对|确保).{0,4}(?:到|送达|赔偿|赔|退款|退|发出|签收|没问题|能到|准时|到货)",
]

# 订单状态动作词（严格订单状态，不含泛泛的物流动作）
_ORDER_ACTIONS = ["已发货", "已签收", "已送达", "已到达"]

# 售后动作词
_AFTERSALES_ACTIONS = ["已退款", "已赔偿", "已补发", "已处理", "已同意", "已批准"]

# 商品参数词
_PRODUCT_PARAMS = ["实木", "松木", "橡木", "榉木", "板材", "密度板", "颗粒板",
                   "厘米", "cm", "kg", "公斤", "承重", "尺寸", "长", "宽", "高",
                   "材质", "填充物", "填充", "防水", "食品级", "无毒", "无味",
                   "记忆棉", "乳胶", "海绵", "塑料", "PP", "ABS", "布艺", "金属"]


def _has_any(text: str, keywords: list) -> bool:
    return any(kw in text for kw in keywords)


def factual_guard(state: dict) -> dict:
    """检查回复是否包含虚假信息（扩展版）"""
    t0 = time.time()
    reply = state.get("suggested_reply", "")
    order = state.get("live_order") or state.get("order")
    logistics_trace = state.get("logistics_trace")
    evidence = state.get("evidence", {})
    guard_warnings = list(state.get("guard_warnings", []))
    intent = state.get("intent", "")
    answer_mode = state.get("answer_mode", "")
    slots = state.get("slots", {})
    order_id = slots.get("order_id", "")
    needs_rewrite = False
    safety_contract = state.get("safety_contract", {}) or {}

    # 判断是否有物流证据
    has_logistics = bool(
        logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", "")
    )

    # 判断是否有订单事实
    order_facts = evidence.get("order_facts", [])
    logistics_facts = evidence.get("logistics_facts", [])
    product_facts = evidence.get("product_facts", [])
    policy_facts = evidence.get("policy_facts", [])
    sop_evidence = evidence.get("sop_evidence", [])
    conflicts = evidence.get("conflicts", [])
    unknowns = evidence.get("unknowns", [])

    if config.ENABLE_PARALLEL_SAFETY_CONTRACT and safety_contract:
        reply, contract_warnings, contract_changed = _apply_safety_contract(state, reply, safety_contract)
        if contract_warnings:
            guard_warnings.extend(contract_warnings)
        if contract_changed:
            logger.debug("factual_guard: safety_contract changed reply")

    # ========== A. 订单事实保护 ==========
    # A1. 没有 order_facts 时不得说订单状态（签收未收到场景除外）
    if not order_facts and intent != "delivery_not_received":
        if _has_any(reply, _ORDER_ACTIONS):
            guard_warnings.append(
                "无订单事实但回复中出现了订单状态描述（已发货/已签收等），疑似编造。"
            )
            needs_rewrite = True
            logger.debug("factual_guard A1: no order_facts but reply has order status")

    # A2. 没有 logistics_facts 时不得输出具体物流轨迹
    # 注意：出现"物流/快递/发货/发出"等泛词不算编造，只有出现具体轨迹动作才算
    if not logistics_facts and has_logistics is False and intent != "delivery_not_received":
        if _has_any(reply, ["到达", "中转", "派送", "派件", "揽收", "已发出", "正在配送"]):
            guard_warnings.append(
                "无物流事实但回复中出现了具体物流轨迹描述（到达/中转/派送等），疑似编造。"
            )
            needs_rewrite = True
            logger.debug("factual_guard A2: no logistics_facts but reply has trace details")

    # ========== B. 物流政策保护 ==========
    # B1. shipping_policy 只能说"通常/一般/以实际物流为准"
    if policy_facts and answer_mode in ("policy", "logistics_policy_without_order"):
        # 先排除安全短语
        cleaned = reply
        for safe in _SAFE_PROMISE_PHRASES:
            cleaned = cleaned.replace(safe, "")
        # 检查危险承诺模式
        if any(re.search(p, cleaned) for p in _DANGEROUS_PROMISE_PATTERNS):
            guard_warnings.append(
                "物流政策回复中出现了绝对承诺（一定/保证/肯定/绝对/确保+到/送达/赔偿等），必须改为'通常/以实际物流为准'。"
            )
            needs_rewrite = True
            logger.debug("factual_guard B1: dangerous promise in policy reply")

    # B2. 无订单号不得出现"您的订单已发出"
    if not order_id and not order:
        if "您的订单" in reply and ("已发出" in reply or "已发货" in reply or "已签收" in reply):
            guard_warnings.append(
                "无订单号但回复中出现了'您的订单已发出/已发货/已签收'，必须改为通用说明或追问订单号。"
            )
            needs_rewrite = True
            logger.debug("factual_guard B2: no order but reply claims order shipped")

    # B3. 不得说"您的订单一定48小时内发货"或"一定到/送达"
    if "一定" in reply:
        _YIDING_DANGEROUS = [
            r"一定.{0,4}(?:小时|天|天内).{0,4}(?:发货|发出|到|送达)",
            r"一定.{0,4}(?:到|送达|赔偿|赔|退款|退|发出|签收|没问题|能到|准时|到货)",
        ]
        if any(re.search(p, reply) for p in _YIDING_DANGEROUS):
            guard_warnings.append(
                "回复中出现了'一定X小时/天内发货'或'一定到/送达'等绝对承诺，必须改为'通常/一般'。"
            )
            needs_rewrite = True
            logger.debug("factual_guard B3: dangerous '一定' promise")

    # B4. 无订单号时不得承诺具体发货/送达时间（明天/后天/今天）
    if not order_id and not order and not logistics_facts:
        _SPECIFIC_TIME_PATTERNS = [
            r"(?:明天|后天|今天|今明两天).{0,5}(?:到|送达|发货|发出|派送)",
            r"(?:到|送达|发货|发出).{0,5}(?:明天|后天|今天|今明两天)",
        ]
        if any(re.search(p, reply) for p in _SPECIFIC_TIME_PATTERNS):
            guard_warnings.append(
                "无订单号/物流证据但回复中承诺了具体日期（今天/明天/后天到/发货），必须改为'通常/以实际物流为准'。"
            )
            needs_rewrite = True
            logger.debug("factual_guard B4: specific time commitment without order_id")

    # ========== C. 商品事实保护 ==========
    # C1. 没有 product_facts 不得说具体材质/尺寸/承重
    has_faq_evidence = bool(evidence.get("faq_evidence"))
    if intent in ("product_question", "product_consult") and not product_facts and not has_faq_evidence:
        if _has_any(reply, _PRODUCT_PARAMS):
            guard_warnings.append(
                "无 product_facts 支撑但回复中出现了具体商品参数（材质/尺寸/承重等），疑似编造。"
            )
            needs_rewrite = True
            logger.debug("factual_guard C1: no product_facts but reply has product params")

    # C2. product_identity 不明确时不得断言（豁免：有 RAG 证据支撑时允许）
    matched_product = state.get("matched_product_name", "")
    has_rag_evidence = bool(
        evidence.get("product_facts") or evidence.get("faq_evidence") or evidence.get("template_evidence")
    )
    if intent in ("product_question", "product_consult") and not matched_product and not has_rag_evidence:
        if _has_any(reply, ["这款", "这个", "本品", "本款"]):
            guard_warnings.append(
                "商品身份未明确但回复中出现了'这款/本品'等断言性描述，必须改为'不同款式可能不同'。"
            )
            needs_rewrite = True
            logger.debug("factual_guard C2: product identity unclear but reply asserts")

    # ========== D. 售后保护 ==========
    # D1. aftersales_policy 不得变成自动退款/赔偿承诺
    if answer_mode == "aftersales_policy":
        if _has_any(reply, _AFTERSALES_ACTIONS):
            guard_warnings.append(
                "售后政策回复中出现了动作性结论（已退款/已赔偿/已补发），需要人工复核。"
            )
            needs_rewrite = True
            logger.debug("factual_guard D1: aftersales reply has action conclusion")

    # D2. 出现"赔偿/补发/退款已处理"等结论需拦截
    if _has_any(reply, ["已退款", "已赔偿", "已补发", "已处理完毕"]):
        guard_warnings.append(
            "回复中出现了售后动作性结论，必须改为'请联系客服处理'或'我们会尽快处理'。"
        )
        needs_rewrite = True
        logger.debug("factual_guard D2: reply has aftersales action conclusion")

    # ========== E. 高风险保护 ==========
    # E1. high_risk_sop 命中时 need_human_review=true
    if sop_evidence:
        guard_warnings.append(
            f"high_risk_sop 命中 {len(sop_evidence)} 条，需要人工复核。"
        )
        state["requires_human_review"] = True
        if not state.get("review_reason"):
            state["review_reason"] = "命中高风险SOP"

    # E2. conflicts 非空时必须 human_review
    if conflicts:
        state["requires_human_review"] = True
        if not state.get("review_reason"):
            state["review_reason"] = "证据冲突"

    # E3. unknowns 非空但 answer_type 不是 clarification
    if unknowns and answer_mode not in ("clarification", "human_review"):
        guard_warnings.append(
            f"存在 {len(unknowns)} 条未知信息但 answer_mode={answer_mode}，建议改为追问或转人工。"
        )

    # ========== 原有检查（保留） ==========
    # 1. 检查回复中是否编造了订单号
    order_ids_in_reply = re.findall(r"\d{8,}", reply)
    if order_ids_in_reply and not order:
        guard_warnings.append(
            "回复中出现了订单号但系统未查到对应订单，疑似编造。"
        )
        logger.debug("factual_guard Rule1: order_ids in reply without real order, ids=%s", order_ids_in_reply)

    # 2. has_logistics=false 时不得出现已签收
    if not has_logistics:
        signed_claims = ["已签收", "已经签收", "签收啦", "已经签收啦"]
        if any(claim in reply for claim in signed_claims):
            guard_warnings.append(
                "无物流证据但回复肯定签收，必须改为核实型回复。"
            )
            needs_rewrite = True
            logger.debug("factual_guard Rule2: no logistics but reply says signed")

    # 3. 低可信度物流时肯定签收 → 拦截
    if logistics_trace and logistics_trace.get("low_confidence"):
        delivered_claims = ["已签收", "已经签收", "签收啦", "已经签收啦"]
        if any(claim in reply for claim in delivered_claims):
            guard_warnings.append(
                "低可信度物流信息时肯定签收，需改为核实型回复。"
            )
            needs_rewrite = True
            logger.debug("factual_guard Rule3: low confidence logistics but reply says signed")

    # 4. 没有 confirmed_delivered 但回复肯定签收
    if logistics_trace and not logistics_trace.get("confirmed_delivered"):
        if "已签收" in reply or "已经签收" in reply or "签收啦" in reply:
            guard_warnings.append(
                "物流未确认签收但回复肯定签收。"
            )
            needs_rewrite = True
            logger.debug("factual_guard Rule4: not confirmed delivered but reply says signed")

    # 5. 没有订单时编造商品
    if not order:
        product_pattern = re.search(r"订单[（(]([^)）]{2,20})[)）]", reply)
        if product_pattern:
            item_text = product_pattern.group(1)
            if item_text not in ("您购买的商品",):
                guard_warnings.append(
                    "无订单时回复中出现了具体商品信息，疑似编造。"
                )
                needs_rewrite = True
                logger.debug("factual_guard Rule5: no order but reply has specific product")

    # 6. 无真实订单时编造快递公司/签收
    # 豁免：有明确商品名且是物流意图时，允许提及 shipping_policy 中的默认快递
    _FORBIDDEN_COURIER_NAMES = ("顺丰", "中通", "圆通", "韵达", "申通", "极兔", "京东快递", "EMS", "百世", "德邦")
    has_product_identity = bool(state.get("matched_product_name", ""))
    if not order and not has_logistics and not has_product_identity:
        for name in _FORBIDDEN_COURIER_NAMES:
            if name in reply:
                guard_warnings.append(
                    f"无真实订单/物流证据时回复中出现了快递公司名'{name}'，疑似编造。"
                )
                needs_rewrite = True
                logger.debug("factual_guard Rule6: no order/logistics but reply has courier name '%s'", name)
                break

    # 7. 检查物流状态不一致
    if logistics_trace and logistics_trace.get("status") == "delivered":
        if "未签收" in reply or "还没收到" in reply:
            guard_warnings.append(
                "物流已签收但回复说未签收，状态不一致。"
            )
            needs_rewrite = True
            logger.debug("factual_guard Rule7: logistics delivered but reply says not signed")

    # ========== F. Knowledge Evidence Quality Gate (Phase 2.5) ==========
    # 检查高风险商品事实的审核状态
    if config.ENABLE_PARALLEL_SAFETY_CONTRACT:
        quality_result = enforce_evidence_quality_gate(state)
        if quality_result.get("answer_mode"):
            answer_mode = quality_result["answer_mode"]
        if quality_result.get("suggested_reply"):
            reply = quality_result["suggested_reply"]
            needs_rewrite = False  # quality gate already rewrote
        # 只追加 quality gate 新产生的警告，不覆盖已有警告
        quality_warnings = quality_result.get("guard_warnings", [])
        if quality_warnings:
            guard_warnings.extend(quality_warnings)
        evidence = quality_result.get("evidence", evidence)

    # 重写回复
    if needs_rewrite:
        try:
            from app.services.metrics_service import get_metrics_service
            get_metrics_service().increment("factual_guard_rewrite_count")
        except Exception:
            pass
        reply = _rewrite_safe_reply(state, reply)

    logger.debug("factual_guard: rewrite=%s", needs_rewrite)
    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "factual_guard",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"factual_guard: {len(guard_warnings)} 条警告, 需改写={needs_rewrite}",
    }

    return {
        "suggested_reply": reply,
        "guard_warnings": guard_warnings,
        "requires_human_review": state.get("requires_human_review", False),
        "review_reason": state.get("review_reason", ""),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _apply_safety_contract(state: dict, reply: str, contract: dict) -> tuple[str, list[str], bool]:
    """Enforce Phase 2 safety_contract as a hard post-generation rule."""
    warnings: list[str] = []
    changed = False
    protected = reply or ""

    forbidden_claims = [str(x) for x in contract.get("forbidden_claims", []) if x]
    requires_evidence_for = [str(x) for x in contract.get("requires_evidence_for", []) if x]

    material_terms = ["实木", "原木", "松木", "橡胶木", "填充棉", "记忆棉", "海绵"]
    material_requested = any(field in ("材质", "填充物") for field in requires_evidence_for)
    if material_requested and _has_any(protected, material_terms) and not _evidence_supports_any(state, material_terms):
        protected = (
            "亲亲，不同款式的材质可能不一样，我这边需要结合具体商品或 SKU 来确认。"
            "麻烦您发一下商品链接、截图、订单号或具体款式，我帮您核实准确参数～"
        )
        warnings.append("safety_contract: blocked unsupported material claim")
        changed = True

    for term in forbidden_claims:
        if term and term in protected:
            protected = protected.replace(term, _safe_replacement(term))
            warnings.append(f"safety_contract: removed forbidden claim '{term}'")
            changed = True

    return protected, warnings, changed


def _evidence_supports_any(state: dict, terms: list[str]) -> bool:
    evidence_text = _collect_evidence_text(state)
    return bool(evidence_text and any(term in evidence_text for term in terms))


def _collect_evidence_text(state: dict) -> str:
    parts: list[str] = []
    evidence = state.get("evidence", {}) or {}
    for value in evidence.values():
        _append_text_parts(parts, value)
    for key in ("filtered_evidence", "knowledge_evidence", "product_knowledge", "knowledge"):
        _append_text_parts(parts, state.get(key, []))
    return "\n".join(parts)


def _append_text_parts(parts: list[str], value) -> None:
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, dict):
        for key in ("fact", "content", "chunk_text", "title", "answer", "question"):
            item = value.get(key)
            if isinstance(item, str):
                parts.append(item)
        for item in value.values():
            if isinstance(item, (list, tuple)):
                _append_text_parts(parts, item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _append_text_parts(parts, item)


def _safe_replacement(term: str) -> str:
    replacements = {
        "一定到": "以实际物流更新为准",
        "保证到": "以实际物流更新为准",
        "肯定到": "以实际物流更新为准",
        "一定明天到": "以实际物流更新为准",
        "承诺赔偿": "核实后处理",
        "承诺退款": "核实后处理",
        "承诺补发": "核实后处理",
        "保证解决": "继续跟进处理",
        "直接补发": "核实后处理",
        "直接赔偿": "核实后处理",
        "保证赔": "先核实责任和方案",
        "实木": "具体材质",
        "不是实木": "具体材质",
    }
    return replacements.get(term, "需核实的信息")


def _rewrite_safe_reply(state: dict, original_reply: str) -> str:
    """生成安全降级回复 — 根据 intent 和订单状态分支"""
    from app.agent.state import has_order_identifier
    intent = state.get("intent", "")
    answer_mode = state.get("answer_mode", "")
    order = state.get("live_order") or state.get("order")
    logistics_trace = state.get("logistics_trace") or {}
    slots = state.get("slots", {}) or {}
    order_status = state.get("order_status", "")
    has_order_id = has_order_identifier(state)

    # --- delivery_not_received: must NEVER become generic "shipped" ---
    if intent == "delivery_not_received":
        reply = (
            "亲，非常抱歉给您带来不便，我理解您的焦急心情。"
            "\n建议您先确认一下：家人、门卫或邻居是否已代为签收？"
            "也可以查看一下门口、快递柜或驿站是否有包裹。"
        )
        if (
            order
            and isinstance(logistics_trace, dict)
            and logistics_trace.get("confirmed_delivered")
            and not logistics_trace.get("low_confidence")
        ):
            items = order.get("items", [])
            names = [i.get("name", "").strip() for i in items if i.get("name", "").strip()]
            item_names = "、".join(names[:3]) or "您购买的商品"
            reply += f"\n我这边查到您的订单（{item_names}）显示已签收。"
        reply += (
            "\n如果确认没有收到，麻烦您发一下订单截图，我会立即帮您联系快递核实并持续跟进。"
            "\n我会继续协助核实并跟进处理。"
        )
        return reply

    # --- aftersales: must stay in aftersales context ---
    if intent == "aftersales":
        if has_order_id:
            return (
                "亲，已收到您的订单信息和退货退款诉求。"
                "\n我先为您核实订单是否符合售后条件，核实后会尽快给您明确的处理方案。"
                "\n如需进一步了解退货原因，我会再跟您确认。"
            )
        return (
            "亲，关于售后问题，我会尽快为您核实处理方案。"
            "\n麻烦您提供一下订单号，我们会安排专人跟进。"
        )

    # --- material safety consultation: high-risk review without complaint flow ---
    if intent in ("complaint", "high_risk") and _is_material_safety_consultation(state):
        product_name = _customer_product_name(state)
        subject = f"「{product_name}」" if product_name else "这款商品"
        return (
            f"亲，您关心{subject}的材质和安全很正常。"
            "这类信息要以商品页、材质说明或检测/合格资料为准，我这边不直接替您下结论。"
            "我先帮您按当前商品核对资料，有依据后再发您参考。"
        )

    # --- complaint / high_risk: de-escalate ---
    if intent in ("complaint", "high_risk"):
        return (
            "亲，非常抱歉让您等着急了，这个情况我会优先帮您跟进。"
            "\n我这边不会先做超出核实结果的承诺，但会按实际情况给您推进处理。"
            "\n请您稍等，我会转人工/主管继续处理。"
        )

    # --- With order: branch by order_status ---
    if order:
        o_id = order.get("o_id", "")
        items = order.get("items", [])
        names = [i.get("name", "").strip() for i in items if i.get("name", "").strip()]
        item_names = "、".join(names[:3]) or "您购买的商品"
        carrier = order.get("logistics_company", "")
        l_id = order.get("l_id", "")
        send_date = order.get("send_date", "")

        # Pending shipment
        if order_status in ("pending_shipment", "presale", "out_of_stock"):
            status_text = {"pending_shipment": "待发货", "presale": "预售", "out_of_stock": "缺货/备货中"}.get(order_status, "未发货")
            reply = f"亲，您的订单（{item_names}）当前状态为{status_text}，尚未发货。"
            reply += "\n我们会按店铺页面承诺的时效尽快安排发货，发货后会第一时间通知您。"
            return reply

        # Delivered / signed
        if order_status == "delivered":
            reply = f"亲，您的订单（{item_names}）显示已完成/已签收。"
            if carrier:
                reply += f" 承运商：{carrier}。"
            if l_id:
                reply += f" 物流单号：{l_id}。"
            reply += "\n如您对订单有任何疑问，请随时联系我们处理。"
            return reply

        # Shipped with carrier info
        if carrier or l_id or send_date:
            reply = f"亲，帮您查到订单（{item_names}）已经发出"
            if carrier:
                reply += f"，快递是{carrier}"
            if l_id:
                reply += f"，单号是{l_id}"
            if send_date:
                reply += f"，发出时间是{send_date}"
            reply += "。具体送达时间以实际物流更新为准～"
            return reply

        return (
            f"亲，关于您的问题，我需要进一步核实相关信息。"
            f"\n订单号：{o_id}"
            f"\n麻烦您稍等，我会尽快为您确认准确情况。"
        )

    # --- No order but has identifier: "not found" ---
    if has_order_id:
        id_type = slots.get("identifier_type", "")
        if id_type == "tracking_no":
            tn = slots.get("tracking_no", "") or state.get("tracking_no", "")
            return (
                f"亲，我已收到您提供的物流单号{tn}，"
                f"但暂未查询到对应的物流信息。"
                f"\n请核对单号是否正确，或提供订单截图，我帮您继续核实。"
            )
        oid = slots.get("order_id", "") or state.get("order_id", "") or slots.get("possible_numeric_id", "")
        return (
            f"亲，我已收到您提供的单号，但暂未查询到对应的订单/物流信息。"
            f"\n请核对号码是否正确，或提供订单截图，我帮您进一步核实。"
        )

    # --- Time commitment: explain uncertainty ---
    if answer_mode == "logistics_time_commitment":
        return (
            "亲，非常理解您希望包裹准时到达的心情。"
            "\n但由于物流运输受天气、路况、分拣等多种因素影响，我们无法对具体到某一天或某一时刻的送达做出绝对承诺。"
            "\n实际送达时间以快递公司物流更新为准。"
            "\n如果您能提供订单号或物流单号，我可以帮您查询当前最新的物流动态和预计送达时间哦～"
        )

    # --- Logistics without identifier ---
    if intent in ("logistics_eta", "shipping", "logistics"):
        return (
            "亲，关于物流问题，我需要核实一下具体情况。"
            "\n麻烦您提供一下订单号或物流单号，我帮您查询准确信息。"
        )

    # --- Product question ---
    if intent in ("product_question", "product_consult"):
        return (
            "亲，关于商品详情，我需要确认一下具体信息。"
            "\n麻烦您提供一下商品链接、截图或订单号，我帮您核实准确参数。"
        )

    return (
        "亲，关于您的问题，我需要进一步核实。"
        "\n麻烦您提供更多详细信息，我会尽快为您确认。"
    )


# 向后兼容别名
_rewrite_low_confidence_reply = _rewrite_safe_reply


def _is_material_safety_consultation(state: dict) -> bool:
    message = str(state.get("normalized_message") or state.get("customer_message") or "")
    fact_type = str(state.get("query_fact_type") or "")
    semantic = state.get("semantic_query") or {}
    if isinstance(semantic, dict):
        fact_type = fact_type or str(semantic.get("query_fact_type") or semantic.get("primary_fact_type") or "")
    material_terms = ("材质", "材料", "什么料", "环保", "有毒", "无毒", "甲醛", "安全", "食品级", "检测", "合格")
    escalation_terms = ("投诉", "差评", "12315", "平台介入", "曝光", "举报", "律师", "起诉")
    if any(term in message for term in escalation_terms):
        return False
    if fact_type in {"material", "material_safety", "certification_report"}:
        return any(term in message for term in material_terms)
    return (
        any(term in message for term in ("材质", "材料", "什么料"))
        and any(term in message for term in ("有毒", "无毒", "甲醛", "安全", "环保", "食品级"))
    )


def _customer_product_name(state: dict) -> str:
    context = state.get("copilot_context") or {}
    for value in (
        state.get("matched_product_name"),
        state.get("product_name"),
        context.get("display_product_name") if isinstance(context, dict) else "",
        context.get("product_title") if isinstance(context, dict) else "",
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""
