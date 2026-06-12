"""Customer-facing reply beautifier.

The beautifier only changes tone and layout. It must not add product facts,
order status, promises, compensation, or policy claims.
"""

from __future__ import annotations

import re


_SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")

_EMOJI_POOLS = {
    "empathy": {
        "default": ("🫶", "🌷", "☺️", "💛", "✨"),
        "material": ("🌿", "🫶", "✨"),
        "certification_report": ("🛡️", "🫶", "🔎"),
        "cleaning_care": ("🧼", "☺️", "🌷"),
        "odor": ("🌬️", "🫶", "🌿"),
        "safety_small_parts": ("⚠️", "🫶", "🛡️"),
        "aftersales_policy": ("🫶", "📦", "💛"),
    },
    "facts": {
        "default": ("✅", "📍", "🔎", "📝", "⭐"),
        "material": ("🌿", "🧸", "✅"),
        "certification_report": ("🔎", "🛡️", "📄"),
        "load_capacity": ("💪", "📍", "✅"),
        "dimensions": ("📏", "📍", "✅"),
        "age_range": ("👶", "🧸", "✅"),
        "cleaning_care": ("🧼", "✅", "🌿"),
        "invoice_policy": ("🧾", "✅", "📄"),
        "price_protection": ("💰", "✅", "📌"),
        "promotion_policy": ("🎁", "💰", "✨"),
        "stock_shipping": ("📦", "🚚", "✅"),
    },
    "cautions": {
        "default": ("📌", "⚠️", "🔔", "🛡️", "💡"),
        "material": ("📌", "🌿", "🛡️"),
        "certification_report": ("🛡️", "📄", "⚠️"),
        "age_range": ("👶", "🛡️", "📌"),
        "safety_small_parts": ("⚠️", "🛡️", "🚨"),
        "cleaning_care": ("📌", "🧼", "💡"),
        "stock_shipping": ("📌", "🚚", "⏱️"),
    },
    "next_steps": {
        "default": ("🧡", "👉", "📩", "🔎", "🙌"),
        "material": ("🔎", "👉", "🧡"),
        "certification_report": ("📩", "🔎", "🧡"),
        "cleaning_care": ("👉", "🧼", "🙌"),
        "invoice_policy": ("🧾", "👉", "📩"),
        "price_protection": ("💰", "👉", "📩"),
        "stock_shipping": ("🚚", "🔎", "👉"),
        "aftersales_policy": ("📦", "🔎", "🧡"),
        "safety_small_parts": ("🛡️", "📩", "🔎"),
    },
}


def beautify_customer_reply(reply: str, state: dict | None = None) -> str:
    """Make a grounded reply warmer and easier to scan."""
    state = state or {}
    text = _soften_risky_convenience_claims(_normalize(reply))
    chat_reply = _build_absolute_safety_chat_reply(state)
    if chat_reply:
        return chat_reply
    text = _remove_ai_sounding_phrases(text, state)
    secondary_followup = _build_secondary_product_followup(text, state)
    if not _should_beautify(text, state):
        return _join_with_secondary(text, secondary_followup)

    sentences = _split_sentences(text)
    if not sentences:
        return _join_with_secondary(reply, secondary_followup)

    greeting, rest = _extract_greeting(sentences)
    if not rest:
        return _join_with_secondary(text, secondary_followup)

    grouped = _group_sentences(rest)
    blocks: list[str] = []
    intro = greeting or "亲亲～"
    blocks.append(intro)

    if grouped["empathy"]:
        blocks.append(_with_emoji("empathy", _join(grouped["empathy"]), state))
    if grouped["facts"]:
        blocks.append(_with_emoji("facts", _join(grouped["facts"]), state))
    if grouped["cautions"]:
        blocks.append(_with_emoji("cautions", _join(grouped["cautions"]), state))
    if grouped["next_steps"]:
        blocks.append(_with_emoji("next_steps", _join(grouped["next_steps"]), state))

    if not any(grouped.values()):
        return _join_with_secondary(_fallback_paragraphs(text), secondary_followup)

    return _join_with_secondary("\n".join(block for block in blocks if block.strip()), secondary_followup)


def _append_secondary_product_followup(text: str, state: dict) -> str:
    followup = _build_secondary_product_followup(text, state)
    return _join_with_secondary(text, followup)



def _soften_risky_convenience_claims(text: str) -> str:
    """Downgrade convenience promises that can create service risk."""
    if not text:
        return text
    replacements = (
        ("\u5b89\u88c5\u5f88\u65b9\u4fbf", "\u53ef\u4ee5\u53c2\u8003\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891\u6309\u6b65\u9aa4\u5b89\u88c5"),
        ("\u5b89\u88c5\u975e\u5e38\u65b9\u4fbf", "\u53ef\u4ee5\u53c2\u8003\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891\u6309\u6b65\u9aa4\u5b89\u88c5"),
        ("\u5b89\u88c5\u5f88\u7b80\u5355", "\u5b89\u88c5\u6b65\u9aa4\u53ef\u4ee5\u53c2\u8003\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891"),
        ("\u5b89\u88c5\u7b80\u5355", "\u5b89\u88c5\u6b65\u9aa4\u53ef\u4ee5\u53c2\u8003\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891"),
        ("\u64cd\u4f5c\u5f88\u7b80\u5355", "\u64cd\u4f5c\u6b65\u9aa4\u53ef\u4ee5\u53c2\u8003\u8bf4\u660e\u4e66\u6216\u9875\u9762\u6307\u5f15"),
        ("\u5f88\u5bb9\u6613\u5b89\u88c5", "\u53ef\u4ee5\u6309\u8bf4\u660e\u4e66\u6b65\u9aa4\u5b89\u88c5"),
        ("\u8f7b\u677e\u5b89\u88c5", "\u6309\u8bf4\u660e\u4e66\u6b65\u9aa4\u5b89\u88c5"),
        ("\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177", "\u662f\u5426\u9700\u8981\u5de5\u5177\u8bf7\u4ee5\u8bf4\u660e\u4e66\u548c\u5b9e\u9645\u914d\u4ef6\u4e3a\u51c6"),
        ("\u65e0\u9700\u989d\u5916\u5de5\u5177", "\u662f\u5426\u9700\u8981\u5de5\u5177\u8bf7\u4ee5\u8bf4\u660e\u4e66\u548c\u5b9e\u9645\u914d\u4ef6\u4e3a\u51c6"),
        ("\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5", "\u5b89\u88c5\u65f6\u95f4\u4f1a\u53d7\u719f\u7ec3\u7a0b\u5ea6\u548c\u73b0\u573a\u60c5\u51b5\u5f71\u54cd\uff0c\u53ef\u4ee5\u6309\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891\u4e00\u6b65\u6b65\u64cd\u4f5c"),
        ("15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5", "\u5b89\u88c5\u65f6\u95f4\u4f1a\u53d7\u719f\u7ec3\u7a0b\u5ea6\u548c\u73b0\u573a\u60c5\u51b5\u5f71\u54cd\uff0c\u53ef\u4ee5\u6309\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891\u4e00\u6b65\u6b65\u64cd\u4f5c"),
        ("\u4e00\u4e2a\u4eba\u5341\u51e0\u5206\u949f\u5c31\u80fd\u7ec4\u88c5\u597d", "\u5b89\u88c5\u65f6\u95f4\u4f1a\u53d7\u719f\u7ec3\u7a0b\u5ea6\u548c\u73b0\u573a\u60c5\u51b5\u5f71\u54cd\uff0c\u53ef\u4ee5\u6309\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891\u4e00\u6b65\u6b65\u64cd\u4f5c"),
        ("\u5341\u51e0\u5206\u949f\u5c31\u80fd\u7ec4\u88c5\u597d", "\u5b89\u88c5\u65f6\u95f4\u4f1a\u53d7\u719f\u7ec3\u7a0b\u5ea6\u548c\u73b0\u573a\u60c5\u51b5\u5f71\u54cd\uff0c\u53ef\u4ee5\u6309\u8bf4\u660e\u4e66\u6216\u5b89\u88c5\u89c6\u9891\u4e00\u6b65\u6b65\u64cd\u4f5c"),
        ("\u5b89\u88c5\u597d\u540e\u975e\u5e38\u7a33\u56fa\uff0c\u4e0d\u4f1a\u8f7b\u6613\u79fb\u52a8\u6216\u6643\u52a8", "\u5b89\u88c5\u5230\u4f4d\u540e\u7a33\u5b9a\u6027\u4f1a\u66f4\u597d\uff0c\u5b9e\u9645\u6548\u679c\u8fd8\u8981\u4ee5\u5b89\u88c5\u60c5\u51b5\u548c\u4f7f\u7528\u73af\u5883\u4e3a\u51c6"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text

def _build_secondary_product_followup(text: str, state: dict) -> str:
    if not text:
        return ""
    intent = state.get("intent", "")
    if intent not in ("logistics_eta", "logistics_trace", "shipping", "logistics", "delivery_not_received"):
        return ""

    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    safety_terms = (
        "\u6750\u8d28", "\u6750\u6599", "\u5b89\u5168\u5417", "\u5b89\u5168\u4e0d", "\u5b89\u5168",
        "\u53d7\u6f6e", "\u9632\u6f6e", "\u7532\u919b", "\u68c0\u6d4b\u62a5\u544a", "\u6709\u5473\u9053", "\u523a\u9f3b",
    )
    if not any(word in msg for word in safety_terms):
        return ""
    if any(word in text for word in safety_terms):
        return ""

    identity = state.get("order_product_identity") or {}
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or ""
    )
    if not product_name:
        candidates = state.get("product_candidates") or []
        first = candidates[0] if candidates else ""
        if isinstance(first, dict):
            product_name = str(first.get("value") or first.get("name") or "").strip()
        elif isinstance(first, str):
            product_name = first.strip()

    if not product_name:
        return (
            "\u60a8\u521a\u624d\u4e5f\u95ee\u5230\u201c\u8fd9\u4e2a\u4e1c\u897f\u5b89\u5168\u5417\u201d\uff0c\u8fd9\u4e2a\u6211\u4e0d\u4f1a\u76f4\u63a5\u51ed\u611f\u89c9\u5224\u65ad\u3002"
            "\u6211\u9700\u8981\u5148\u5bf9\u4e0a\u5177\u4f53\u5546\u54c1\u540d\u79f0\u3001\u94fe\u63a5\u6216\u8ba2\u5355\u5546\u54c1\u660e\u7ec6\uff0c\u518d\u6309\u5df2\u9a8c\u8bc1\u7684\u5546\u54c1\u77e5\u8bc6\u6216\u9875\u9762\u4fe1\u606f\u5e2e\u60a8\u6838\u5b9e\uff1b"
            "\u60a8\u53ef\u4ee5\u628a\u5546\u54c1\u622a\u56fe\u6216\u94fe\u63a5\u53d1\u6211\u4e00\u4e0b\uff0c\u6211\u7ee7\u7eed\u5e2e\u60a8\u786e\u8ba4\u3002"
        )

    fact = _usable_secondary_product_fact(state)
    if fact:
        return f"\u5173\u4e8e\u300c{product_name}\u300d\u7684\u5b89\u5168/\u6750\u8d28\u95ee\u9898\uff1a{fact}"

    asks_moisture = any(word in msg for word in ("\u53d7\u6f6e", "\u9632\u6f6e", "\u6f6e\u6e7f"))
    topic = "\u6750\u8d28\u5b89\u5168\u548c\u53d7\u6f6e\u95ee\u9898" if asks_moisture else "\u5b89\u5168\u95ee\u9898"
    return (
        f"\u5173\u4e8e\u300c{product_name}\u300d\u7684{topic}\uff0c\u6211\u5df2\u7ecf\u5148\u5e2e\u60a8\u5bf9\u4e0a\u5546\u54c1\u3002"
        "\u8fd9\u7c7b\u4fe1\u606f\u9700\u8981\u4ee5\u5df2\u9a8c\u8bc1\u7684\u6750\u8d28\u8bf4\u660e\u3001\u68c0\u6d4b\u8d44\u6599\u6216\u5546\u54c1\u9875\u9762\u4e3a\u51c6\uff0c"
        "\u6211\u5148\u4e0d\u51ed\u611f\u89c9\u5224\u65ad\uff0c\u4f1a\u6309\u5f53\u524d\u5546\u54c1\u7ee7\u7eed\u6838\u5b9e\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u7b54\u590d\u3002"
    )

def _join_with_secondary(text: str, secondary_followup: str) -> str:
    text = (text or "").strip()
    secondary_followup = (secondary_followup or "").strip()
    if not secondary_followup:
        return text
    if not text:
        return secondary_followup
    return f"{text}\n{secondary_followup}"


def _usable_secondary_product_fact(state: dict) -> str:
    evidence = state.get("evidence") or {}
    for bucket in ("product_facts", "faq_evidence"):
        for item in evidence.get(bucket, []) or []:
            if item.get("source_type") == "product_mapping":
                continue
            if item.get("evidence_allowed_for_direct_answer") is False:
                continue
            fact = str(item.get("fact") or item.get("chunk_text") or "").strip()
            if fact:
                return fact
    for item in (state.get("knowledge_evidence") or []) + (state.get("filtered_evidence") or []):
        if item.get("source_type") == "product_mapping":
            continue
        if item.get("direct_answer_allowed") is False or item.get("evidence_allowed_for_direct_answer") is False:
            continue
        fact = str(item.get("chunk_text") or item.get("fact") or "").strip()
        if fact:
            return fact
    return ""


def _should_beautify(text: str, state: dict) -> bool:
    if not text or len(text) < 24:
        return False
    if state.get("disable_reply_beautify"):
        return False
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        return False
    return True


def _normalize(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _build_absolute_safety_chat_reply(state: dict) -> str:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    if not msg:
        return ""
    asks_absolute = any(word in msg for word in ("保证", "一定不会", "绝对不会", "百分百", "100%", "不会出事", "不会倒"))
    asks_child_safety = any(word in msg for word in ("孩子", "宝宝", "小孩", "儿童", "安全", "出事"))
    if not (asks_absolute and asks_child_safety):
        return ""

    product_name = _known_product_name(state)
    scenario = _infer_child_safety_scenario(product_name, msg)
    question = _key_followup_question(scenario)
    if product_name:
        middle = f"这款「{product_name}」如果按说明安装、固定好，并且按适合的场景使用，会更稳妥一些。"
    else:
        middle = "这类儿童用品主要还是看孩子年龄、安装/摆放位置和实际使用方式。"
    return "\n".join((
        "亲，孩子用的东西您谨慎是应该的～",
        "这个我不能跟您说“百分百一定不会出事”，说太满反而不负责。",
        f"{middle}",
        f"{question} 🧡",
    ))


def _known_product_name(state: dict) -> str:
    identity = state.get("order_product_identity") or {}
    product = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or ""
    )
    if product:
        return str(product).strip()
    ctx = state.get("copilot_context") or {}
    if ctx.get("product_name"):
        return str(ctx.get("product_name")).strip()
    candidates = state.get("product_candidates") or ctx.get("product_candidates") or []
    for cand in candidates or []:
        if isinstance(cand, dict):
            value = str(cand.get("value") or cand.get("name") or "").strip()
            if value:
                return value
        elif isinstance(cand, str) and cand.strip():
            return cand.strip()
    return ""


def _infer_child_safety_scenario(product_name: str, msg: str) -> str:
    text = f"{product_name} {msg}"
    if any(word in text for word in ("护栏", "围栏", "防护")):
        return "guardrail"
    if any(word in text for word in ("收纳", "书架", "柜", "置物", "架")):
        return "furniture"
    if any(word in text for word in ("餐具", "围兜", "喂养", "杯", "碗")):
        return "feeding"
    return "general"


def _key_followup_question(scenario: str) -> str:
    if scenario == "guardrail":
        return "您家宝宝多大、准备装在什么位置呀？我帮您先看下适不适合。"
    if scenario == "furniture":
        return "您准备放哪里、宝宝大概多大呀？我帮您看下这个场景适不适合。"
    if scenario == "feeding":
        return "您家宝宝多大呀？我帮您看下这个阶段适不适合用。"
    return "您家孩子多大、准备怎么用呀？我帮您看下适不适合。"


def _remove_ai_sounding_phrases(text: str, state: dict) -> str:
    if not text:
        return text
    replacements = (
        ("根据您提供的信息，", ""),
        ("根据您提供的信息", ""),
        ("作为AI", ""),
        ("我是AI", ""),
        ("如果系统里暂时没有明确证据，", ""),
        ("如果系统里暂时没有明确证据", ""),
        ("系统里暂时没有明确证据", "我这边还需要再核实一下"),
        ("避免给您误导", "避免给您说错"),
        ("避免给您说错。", "避免给您说错。"),
        ("商品参数、功能或订单信息需要以已验证的商品知识和订单页面为准", "这个我需要按实际商品信息帮您核对清楚"),
        ("这类商品参数、功能或订单信息需要以已验证的商品知识和订单页面为准", "这个我需要按实际商品信息帮您核对清楚"),
        ("我先不凭感觉猜", "我先不乱说"),
        ("我不会直接凭感觉判断", "我不跟您乱保证"),
        ("请您以页面为准", "我帮您按当前商品再核对一下"),
        ("建议您查看商品详情页", "我帮您按当前商品再核对一下"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"亲亲[，,～~]?", "亲，", text)
    return text


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for match in _SENTENCE_RE.finditer(line):
            sentence = match.group(0).strip()
            if sentence:
                parts.append(sentence)
    return parts


def _extract_greeting(sentences: list[str]) -> tuple[str, list[str]]:
    first = sentences[0]
    if first.startswith(("亲亲，", "亲亲,", "亲，", "亲,")):
        first = re.sub(r"^亲亲[，,]\s*", "", first)
        first = re.sub(r"^亲[，,]\s*", "", first)
        return "亲～", ([first] if first else []) + sentences[1:]
    if first.startswith("您好"):
        first = re.sub(r"^您好[～~，,]?\s*", "", first)
        return "您好～", ([first] if first else []) + sentences[1:]
    return "", sentences


def _group_sentences(sentences: list[str]) -> dict[str, list[str]]:
    grouped = {
        "empathy": [],
        "facts": [],
        "cautions": [],
        "next_steps": [],
    }
    for sentence in sentences:
        bucket = _bucket(sentence)
        grouped[bucket].append(_trim_intro(sentence))
    return grouped


def _bucket(sentence: str) -> str:
    if any(word in sentence for word in ("理解", "关心", "担心", "着急", "抱歉", "不好意思", "不愉快", "重要", "这个问题", "很实用", "确实")):
        return "empathy"
    if any(word in sentence for word in ("但", "不过", "不能", "不建议", "需要以", "为准", "风险", "不先直接", "不直接", "未核对")):
        return "cautions"
    if any(word in sentence for word in ("您可以", "麻烦", "建议", "我这边", "我先", "请", "稍等", "发我", "发来", "继续", "核实", "转人工")):
        return "next_steps"
    return "facts"


def _trim_intro(sentence: str) -> str:
    sentence = sentence.strip()
    sentence = re.sub(r"^关于您咨询的([^：]{1,80})：", r"关于「\1」：", sentence)
    sentence = re.sub(r"^关于您咨询的问题：", "", sentence)
    return sentence


def _join(sentences: list[str]) -> str:
    return "\n".join(s.strip() for s in sentences if s.strip())


def _with_emoji(bucket: str, text: str, state: dict) -> str:
    if not text:
        return ""
    emoji = _pick_emoji(bucket, text, state)
    return f"{emoji} {text}" if emoji else text


def _pick_emoji(bucket: str, text: str, state: dict) -> str:
    fact_type = state.get("query_fact_type", "") or _infer_fact_type_from_text(text)
    pool = _EMOJI_POOLS.get(bucket, {})
    choices = pool.get(fact_type) or pool.get("default") or ()
    if not choices:
        return ""
    seed = sum(ord(ch) for ch in f"{bucket}:{fact_type}:{text[:16]}")
    return choices[seed % len(choices)]


def _infer_fact_type_from_text(text: str) -> str:
    if any(w in text for w in ("甲醛", "检测报告", "质检", "证书", "3C")):
        return "certification_report"
    if any(w in text for w in ("材质", "PP", "钢管", "无纺布", "环保")):
        return "material"
    if any(w in text for w in ("清洁", "水洗", "擦拭", "脏了")):
        return "cleaning_care"
    if any(w in text for w in ("发票", "抬头", "税号")):
        return "invoice_policy"
    if any(w in text for w in ("价保", "保价", "降价")):
        return "price_protection"
    if any(w in text for w in ("发货", "物流", "库存", "出库")):
        return "stock_shipping"
    return ""


def _fallback_paragraphs(text: str) -> str:
    sentences = _split_sentences(text)
    if len(sentences) <= 2:
        return text
    return "\n".join(_join(sentences[i:i + 2]) for i in range(0, len(sentences), 2))
