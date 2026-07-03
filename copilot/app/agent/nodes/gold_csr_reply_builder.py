"""Gold CSR reply polishing with strict, rule-based safety boundaries."""

from __future__ import annotations

import time

LOCKED_POLICY_INTENTS = {
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


def _already_asked_order_text(state: dict) -> str:
    if state.get("live_order") or state.get("order") or state.get("logistics_trace"):
        return "我已经先按您补充的信息查到相关记录，会继续按实际物流和订单信息帮您核实。"
    from app.agent.state import has_order_identifier
    if has_order_identifier(state):
        return "我已收到您提供的单号，正在进一步核实中，请稍等。"
    ctx = state.get("conversation_context", {}) or {}
    if ctx.get("has_already_asked_order_id"):
        return "我这边需要订单号或物流单号才能准确核实，您发订单截图也可以，我会继续帮您查。"
    return "麻烦您提供一下订单号、物流单号或订单截图，我帮您继续核实。"


def _known_product_text(state: dict) -> str:
    generic_terms = {
        "具体材质", "材质", "功能", "参数", "设置方式", "商品", "这个", "这款",
        "瀹炴湪", "鏉愯川", "瀹夊叏", "鏃犳瘨", "濉厖",
    }
    exact_generic_terms = generic_terms | {
        "\u5177\u4f53\u6750\u8d28", "\u6750\u8d28", "\u529f\u80fd", "\u53c2\u6570",
        "\u8bbe\u7f6e\u65b9\u5f0f", "\u5546\u54c1", "\u8fd9\u4e2a", "\u8fd9\u6b3e",
    }
    short_contains_terms = {
        "\u5177\u4f53\u6750\u8d28", "\u6750\u8d28", "\u662f\u4e0d\u662f\u5b9e\u6728",
        "鍏蜂綋鏉愯川", "鏉愯川",
    }
    product = state.get("matched_product_name", "")
    identity = state.get("order_product_identity") or {}
    if not product:
        product = identity.get("matched_product_name", "") or identity.get("internal_product_name", "")
    slots = state.get("slots", {}) or {}
    if not product:
        product = slots.get("product_name", "") or slots.get("sku_name", "")
    ctx = state.get("copilot_context", {}) or {}
    if not product:
        product = ctx.get("product_name", "")
    candidates = state.get("product_candidates") or ctx.get("product_candidates") or []
    if not product and isinstance(candidates, list):
        for cand in candidates:
            if isinstance(cand, dict) and cand.get("value"):
                product = str(cand.get("value")).strip()
                break
            if isinstance(cand, str) and cand.strip():
                product = cand.strip()
                break
    if product in exact_generic_terms or (len(product) <= 12 and any(term and term in product for term in short_contains_terms)):
        return ""
    return product


def _known_order_text(state: dict) -> str:
    if state.get("order_id") or state.get("tracking_no"):
        return state.get("order_id") or state.get("tracking_no")
    slots = state.get("slots", {}) or {}
    for key in ("order_id", "platform_trade_id", "tracking_no"):
        if slots.get(key):
            return slots[key]
    ctx = state.get("copilot_context", {}) or {}
    for key in ("order_id", "platform_trade_id", "tracking_no"):
        if ctx.get(key):
            return ctx[key]
    for cand_key in ("order_candidates", "tracking_candidates"):
        for cand in ctx.get(cand_key, []) or []:
            if isinstance(cand, dict) and cand.get("value"):
                return str(cand["value"]).strip()
    return ""


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


def _product_no_evidence_reply(state: dict) -> str:
    product = _known_product_text(state)
    msg = state.get("normalized_message") or state.get("customer_message") or ""
    fact_type = state.get("query_fact_type", "")
    if fact_type == "installation":
        if product:
            return (
                f"亲，您要的是「{product}」的安装视频/安装说明对吗？我先帮您核对一下对应版本，避免发错教程影响安装。\n"
                "麻烦您稍等一下，我这边先帮您转给同事确认，确认后再把准确的安装方式或视频发给您。"
            )
        return (
            "亲，安装视频需要先对上具体商品和款式，避免不同型号教程混在一起。\n"
            "您可以发一下商品截图、链接或 SKU，我帮您按对应商品核对安装视频/教程。"
        )
    if fact_type == "pinch_safety":
        if product:
            return (
                f"亲，您担心的是「{product}」滑门/结构会不会夹手、家里宝宝使用是否安全对吗？\n"
                "这个点我先帮您按对应款式核实清楚，避免不同款式结构说错影响您判断。\n"
                "麻烦您稍等一下，我确认后再按准确说法回复您。"
            )
        return (
            "亲，夹手和宝宝使用安全这个点需要先对上具体款式后再确认。\n"
            "您可以发一下商品截图、链接或 SKU，我帮您按对应商品核实，避免不同款式信息混在一起。"
        )
    if fact_type == "variant_compare" or any(word in msg for word in ("基础款", "升级款", "升级版", "差什么", "区别", "差别")):
        topic = "基础款和升级款的区别"
    elif fact_type == "detachable":
        topic = "\u662f\u5426\u53ef\u62c6\u5378"
    elif fact_type:
        from app.services.fact_type_service import FACT_TYPE_LABELS
        topic = FACT_TYPE_LABELS.get(fact_type, "您问的这个点")
    else:
        topic = "您问的商品问题"

    if product:
        if fact_type == "detachable":
            return (
                f"亲，已经帮您对到「{product}」这款商品了。\n"
                "关于是否可拆卸/怎么拆装，我这边先帮您核实一下准确说法，避免不同款式说错影响您使用。\n"
                "麻烦您稍等一下，我先转给同事确认，确认后再回复您。"
            )
        return (
            f"亲，您问的是「{product}」的{topic}，我先帮您核对一下准确说法。\n"
            "麻烦您稍等一下，我这边确认后再回复您，避免给您说错影响选择。"
        )
    return (
        f"亲，{topic}我需要先对上具体款式后再确认。\n"
        "您可以发一下商品截图、链接或 SKU，我帮您按对应商品核实，避免不同款式的信息混在一起。"
    )


def _has_sidecar_known_context(state: dict) -> bool:
    ctx = state.get("copilot_context", {}) or {}
    if ctx.get("product_name") or ctx.get("order_id") or ctx.get("platform_trade_id") or ctx.get("tracking_no"):
        return True
    if ctx.get("product_candidates") or ctx.get("order_candidates") or ctx.get("tracking_candidates"):
        return True
    if state.get("product_candidates") or state.get("order_product_identity"):
        return True
    return False


def _has_ambiguous_sidecar_product_name(state: dict) -> bool:
    identity = state.get("order_product_identity") or {}
    return (
        identity.get("source") == "sidecar_product_name"
        and identity.get("status") == "ambiguous"
    )


def _refund_complaint_handoff_reply(state: dict) -> str:
    msg = _combined_customer_text(state)
    if not _is_refund_or_complaint_text(msg):
        return ""
    if not any(cue in msg for cue in ("\u9000\u6b3e", "\u9000\u94b1", "\u9000\u8d27", "\u4e0d\u7ed9\u9000", "\u9000\u5dee")):
        return ""
    if _mentions_physical_issue(msg) or state.get("image_attachments"):
        return ""

    order_id = _known_order_text(state)
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


def _combined_customer_text(state: dict) -> str:
    parts = [
        str(state.get("normalized_message") or ""),
        str(state.get("customer_message") or ""),
    ]
    ctx = state.get("copilot_context", {}) or {}
    for item in ctx.get("conversation_history", []) or []:
        if isinstance(item, dict) and item.get("role") == "customer":
            parts.append(str(item.get("text") or ""))
    return " ".join(p for p in parts if p)


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


def _mentions_physical_issue(text: str) -> bool:
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


def gold_csr_reply_builder(state: dict) -> dict:
    t0 = time.time()
    plan = state.get("response_strategy_plan", {}) or {}
    goal = plan.get("reply_goal", "")
    reply = state.get("suggested_reply", "")
    answer_mode = state.get("answer_mode", "")
    identity = state.get("order_product_identity") or {}
    has_grounded_identity_or_evidence = (
        bool(state.get("used_knowledge_entry_ids"))
        or identity.get("status") == "resolved"
    )
    changed = False
    # clarify_product_identity 只有在没有已解析商品身份时才强制改写；
    # 若已有明确商品身份和 grounded 答案，则保留原答案。
    identity_resolved = identity.get("status") == "resolved"
    force_clarify_product_identity = (
        goal == "clarify_product_identity"
        and not identity_resolved
    )
    locked_grounded_answer = (
        not force_clarify_product_identity
        and answer_mode in ("exact_faq_answer", "product_fact_answer")
        and bool((reply or "").strip())
        and has_grounded_identity_or_evidence
    ) or (
        state.get("intent", "") in LOCKED_POLICY_INTENTS
        and answer_mode == "policy_grounded_answer"
        and bool((reply or "").strip())
    ) or (
        state.get("intent", "") in ("logistics_eta", "logistics_trace", "shipping", "logistics", "delivery_not_received")
        and state.get("answer_type", "") in ("verified", "fallback", "estimated", "human_review")
        and bool((reply or "").strip())
    )

    if _has_ambiguous_sidecar_product_name(state):
        reply = state.get("clarification_question") or (
            "亲亲，当前会话里的商品名称可能对应多个内部商品，"
            "麻烦您确认一下具体 SKU、商品编码、商品链接或订单号，我帮您核实准确参数～"
        )
        answer_mode = "no_evidence_clarification"
        changed = True

    elif locked_grounded_answer:
        changed = False

    elif goal == "explain_no_guarantee":
        reply = (
            "亲亲，不能直接保证一定在今天/明天送到，我先跟您说清楚，避免耽误您的安排。\n"
            "到达时间会受是否已发货、收货地区、快递揽收和中转情况影响，最终以实际物流更新为准。\n"
            f"{_already_asked_order_text(state)}"
        )
        changed = True

    elif answer_mode == "no_evidence_clarification" and (
        goal in ("answer_product_fact", "answer_or_clarify")
        or state.get("intent") in ("product_question", "product_consult")
        or state.get("query_fact_type")
    ):
        reply = _product_no_evidence_reply(state)
        changed = True

    elif goal == "social_reply":
        concern = state.get("customer_concern", "")
        if concern == "smalltalk":
            reply = "我在。您可以直接说要查物流、问商品、处理售后，或者先简单问一句都可以。"
        else:
            reply = "亲，我在的。刚才的回复如果没帮到您，您可以直接说具体问题，我重新帮您核对清楚。"
        changed = True

    elif answer_mode == "no_evidence_clarification" and goal in ("answer_product_fact", "answer_or_clarify"):
        reply = _product_no_evidence_reply(state)
        changed = True

    elif goal == "clarify_product_identity" and _has_sidecar_known_context(state) and (_known_product_text(state) or _known_order_text(state)):
        product_text = _known_product_text(state)
        order_text = _known_order_text(state)
        known_parts = []
        if product_text:
            known_parts.append(f"商品：{product_text}")
        if order_text:
            known_parts.append(f"订单/物流信息：{order_text}")
        known_text = "，".join(known_parts)
        reply = (
            f"亲，您问的这个点我先帮您对上当前信息：{known_text}。\n"
            "这个我需要按实际商品信息帮您核对清楚，不能直接凭感觉说。\n"
            "我会继续按当前商品和订单信息核对，需要人工确认的地方也会一起确认后再回复您。"
        )
        answer_mode = "no_evidence_clarification"
        changed = True

    elif goal == "clarify_product_identity":
        reply = (
            "亲，这个我需要先对上具体款式，不能直接凭感觉说，避免给您说错。\n"
            "您可以发一下商品链接、截图、订单号、SKU 或具体款式，我帮您确认准确用法和设置方式。"
        )
        answer_mode = "no_evidence_clarification"
        changed = True

    elif goal == "handle_delivery_not_received":
        trace = state.get("logistics_trace", {}) or {}
        order = state.get("live_order") or state.get("order") or {}
        tracking_no = trace.get("tracking_no") or order.get("l_id", "")
        carrier = trace.get("carrier") or order.get("logistics_company", "")
        checked = ""
        if tracking_no or carrier:
            checked = f"\n我这边查到包裹信息：{carrier} {tracking_no}。"
        reply = (
            "亲亲，理解您没收到包裹会着急，显示签收但您没有收到的话，我会帮您一起核实。"
            f"{checked}\n"
            "您可以先看一下家人、门卫、前台、驿站或快递柜是否代收，也可以留意快递员是否放在门口附近。\n"
            f"{_already_asked_order_text(state)}"
        )
        changed = True

    elif goal == "deescalate_complaint":
        if _is_material_safety_consultation(state):
            product = _known_product_text(state)
            subject = f"「{product}」" if product else "这款商品"
            reply = (
                f"亲，您关心{subject}的材质和安全很正常。"
                "这类信息要以商品页、材质说明或检测/合格资料为准，我这边不直接替您下结论。"
                "我先帮您按当前商品核对资料，有依据后再发您参考。"
            )
            changed = True
        else:
            targeted_reply = _refund_complaint_handoff_reply(state)
            if targeted_reply:
                reply = targeted_reply
                changed = True
            else:
                reply = (
                "亲亲，非常抱歉让您等着急了，这个情况我会优先帮您跟进。\n"
                "为了避免信息不准，我需要先核实订单和处理记录，再转人工/主管继续处理。\n"
                f"{_already_asked_order_text(state)}\n"
                "我这边不会先做超出核实结果的承诺，但会按实际情况给您推进处理。"
            )
            changed = True

    trace = {
        "node": "gold_csr_reply_builder",
        "status": "success",
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": False,
        "summary": f"goal={goal}, changed={changed}",
    }
    product_no_evidence_review = bool(
        answer_mode == "no_evidence_clarification"
        and (
            state.get("intent") in ("product_question", "product_consult", "installation")
            or state.get("query_fact_type")
        )
    )
    return {
        "suggested_reply": reply,
        "answer_mode": answer_mode,
        "generation_mode": "rule_based" if changed else state.get("generation_mode", "rule_based"),
        "llm_used": state.get("llm_used", False),
        "gold_csr_applied": changed,
        "requires_human_review": state.get("requires_human_review", False) or product_no_evidence_review,
        "review_reason": state.get("review_reason", "") or (
            "商品具体字段需要人工核实" if product_no_evidence_review else ""
        ),
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
