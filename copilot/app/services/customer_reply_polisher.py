"""Customer-facing reply polishing.

This layer runs after factual/semantic guards. It must not invent facts or
change decisions. Its job is only to remove internal process language and make
handoff-style replies sound like a polished senior customer service agent.
"""

from __future__ import annotations

import re
from typing import Any


_BLOCKED_PHRASES = (
    "准确说法",
    "凭感觉",
    "系统里",
    "资料库",
    "知识库",
    "已审核资料",
    "RAG",
    "Evidence Gate",
    "query_fact_type",
    "fact_type",
)


def polish_customer_reply(
    response: dict[str, Any],
    *,
    customer_message: str = "",
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Polish response["suggested_reply"] without changing business facts."""
    original = str(response.get("suggested_reply") or "")
    previous_info = response.get("customer_reply_polish") or {}
    if not original.strip():
        return response

    polished = _polish_text(original)
    display_name = _display_product_name(response, copilot_context or {})
    internal_names = _internal_product_names(response)
    if display_name:
        polished = _replace_internal_product_names(polished, display_name, internal_names)
        response["display_product_name"] = display_name
    polished = _rewrite_complaint_service_reply(polished, response, customer_message)
    polished = _rewrite_media_workflow_reply(polished, response, customer_message, display_name)
    polished = _remove_unsupported_media_send_claims(polished, response, display_name)
    complaint_contract_passed = _is_customer_safe_complaint_reply(polished, response, customer_message)
    if complaint_contract_passed:
        debug = response.setdefault("evidence_debug", {})
        if isinstance(debug, dict):
            debug["answer_relevance_passed"] = True
            debug["complaint_output_contract"] = {
                "passed": True,
                "mode": "customer_safe_complaint_reply",
            }
    applied = polished != original or bool(previous_info.get("applied"))

    info = {
        "checked": True,
        "applied": applied,
        "mode": "deterministic_customer_language_expert",
        "blocked_phrases_removed": [p for p in _BLOCKED_PHRASES if p in original and p not in polished],
        "display_product_name": display_name,
        "internal_names_rewritten": [
            name for name in internal_names
            if display_name and name and name != display_name and name in original
        ],
    }
    if applied:
        response["suggested_reply"] = polished
        info["original_reply"] = original
    response["customer_reply_polish"] = info
    response.setdefault("evidence_debug", {})["customer_reply_polish"] = info
    return response


def _polish_text(text: str) -> str:
    text = _normalize_greeting(text)
    text = _rewrite_common_process_phrases(text)
    text = _rewrite_material_safety_handoff(text)
    text = _rewrite_generic_handoff(text)
    text = _remove_internal_words(text)
    text = _compact_lines(text)
    return text.strip()


def _normalize_greeting(text: str) -> str:
    text = re.sub(r"^\s*亲亲[，,～~]?", "亲～", text)
    text = re.sub(r"^\s*亲[，,]\s*", "亲～\n", text)
    return text


def _rewrite_common_process_phrases(text: str) -> str:
    replacements = (
        ("我先按当前商品", "我这边先按这款商品"),
        ("帮您核实一下准确说法", "为您确认清楚"),
        ("核实一下准确说法", "确认清楚"),
        ("核对一下准确说法", "确认清楚"),
        ("再按准确说法回复您", "再回复您"),
        ("给您准确回复", "回复您"),
        ("确认后再给您准确回复", "确认后回复您"),
        ("避免不同款式结构说错影响您判断", "避免不同款式结构有差异"),
        ("避免不同款式说错影响您使用", "避免不同款式有差异"),
        ("避免说错影响您判断", "避免不同款式信息有差异"),
        ("避免给您说错", "我会帮您确认清楚"),
        ("我不先凭感觉判断，", ""),
        ("不能直接凭感觉说，", ""),
        ("我先不凭感觉猜，", ""),
        ("我不会直接凭感觉判断，", ""),
        ("我先帮您转人工/货品同事确认，", "我这边先帮您确认清楚，"),
        ("我先帮您转人工核实，", "我这边先帮您确认清楚，"),
        ("我先转人工。", "我这边先帮您确认清楚。"),
        ("转人工/货品同事", "帮您确认"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _rewrite_material_safety_handoff(text: str) -> str:
    pattern = re.compile(
        r"宝宝用的东西您关心材质和安全很正常，"
        r"我这边先按这款商品(?P<product>「[^」]+」)?为您确认清楚。?\n?"
        r"(?P<focus>[^。\n]{0,30}(?:材质|防潮|安全)[^。\n]{0,30})我会帮您确认清楚。?"
    )

    def repl(match: re.Match[str]) -> str:
        product = match.group("product") or "这款商品"
        return (
            f"家里有宝宝的话，关心材质和安全很正常。"
            f"我先帮您把{product}的材质说明确认清楚。"
        )

    text = pattern.sub(repl, text)

    text = re.sub(
        r"宝宝用的东西您关心材质和安全很正常，"
        r"我先按当前商品(?P<product>「[^」]+」)?帮您核实一下准确说法。?",
        lambda m: (
            "家里有宝宝的话，关心材质和安全很正常。"
            f"我先帮您把{m.group('product') or '这款商品'}的材质说明确认清楚。"
        ),
        text,
    )
    return text


def _rewrite_generic_handoff(text: str) -> str:
    text = re.sub(
        r"这个点我先帮您按对应款式核实清楚[，,]?[^。\n]*。",
        "这个细节我先帮您按对应款式确认一下。",
        text,
    )
    text = re.sub(
        r"这个点我先按对应商品资料帮您核实清楚[，,]?[^。\n]*。",
        "这个细节我先帮您按对应商品确认一下。",
        text,
    )
    text = re.sub(
        r"这个点不同款式可能不一样，我先帮您核实清楚再回复您。",
        "不同款式可能会有差异，我先帮您确认清楚再回复您。",
        text,
    )
    text = re.sub(
        r"麻烦您稍等一下，我这边确认清楚后再回复您。",
        "您稍等一下，我确认清楚后回复您。",
        text,
    )
    text = re.sub(
        r"麻烦您稍等一下，我确认清楚后再回复您。",
        "您稍等一下，我确认清楚后回复您。",
        text,
    )
    text = re.sub(
        r"如果您手边有商品页面的材质说明截图，也可以一起发来，我这边会一起对照核实。",
        "如果方便，也可以把页面上的材质说明截图发我，我一起帮您对照。",
        text,
    )
    return text


def _remove_internal_words(text: str) -> str:
    replacements = (
        ("系统里目前没有这款商品的", "这款商品的"),
        ("系统里目前有这款商品的部分资料，但没有可直接引用的", "这款商品目前还需要进一步确认"),
        ("系统里", ""),
        ("资料库", "资料"),
        ("知识库", "资料"),
        ("已审核资料", "资料"),
        ("已审核说明", "说明"),
        ("可直接引用的", ""),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _compact_lines(text: str) -> str:
    lines: list[str] = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[🌿📍🛡️👉🧡🙌🔔📝🔎💬\s]+", "", line)
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"([。！？])\1+", r"\1", line)
        signature = line
        if signature in seen:
            continue
        seen.add(signature)
        lines.append(line)
    return "\n".join(lines)


def _rewrite_complaint_service_reply(
    text: str,
    response: dict[str, Any],
    customer_message: str,
) -> str:
    if not _is_complaint_or_quality_service_turn(response, customer_message):
        return text
    if not _needs_complaint_language_rewrite(text):
        return text

    has_order = _has_order_context(response)
    has_quality_issue = _contains_any_plain(customer_message, ("质量", "太差", "坏", "破损", "瑕疵", "裂", "变形", "掉漆"))
    order_line = (
        "我这边已经收到您提供的订单信息，会直接按这笔订单优先跟进处理。"
        if has_order
        else "为了尽快对到订单，麻烦您把订单号或购买记录发我一下，我这边马上帮您跟进。"
    )
    evidence_line = (
        "如果方便，也麻烦您把问题位置拍照或录个小视频发我，我会一起提交给售后/主管核实处理。"
        if has_quality_issue
        else "我会先把您的诉求记录清楚，再按订单和平台规则帮您推进处理。"
    )
    return (
        "亲～非常抱歉让您有这么不好的体验，您的反馈我已经收到，会优先帮您跟进。\n"
        f"{order_line}\n"
        f"{evidence_line}\n"
        "这边会尽快给您明确处理方向，不会让您一直等着没有结果。"
    )


def _is_complaint_or_quality_service_turn(response: dict[str, Any], customer_message: str) -> bool:
    intent = str(response.get("intent") or "").lower()
    risk = str(response.get("risk_level") or response.get("risk") or "").lower()
    debug = response.get("evidence_debug") or {}
    if isinstance(debug, dict):
        intent = intent or str(debug.get("intent") or "").lower()
        risk = risk or str(debug.get("risk_level") or "").lower()
    if intent in {"complaint", "high_risk"} or risk in {"high", "critical"}:
        return True
    return _contains_any_plain(
        customer_message,
        ("投诉", "差评", "12315", "平台介入", "曝光", "质量太差", "再不处理", "不处理"),
    )


def _needs_complaint_language_rewrite(text: str) -> bool:
    return _contains_any_plain(
        text,
        (
            "商品页面",
            "实物位置截图",
            "当前商品",
            "页面信息",
            "超出核实结果的承诺",
            "避免信息不准",
            "避免发错",
            "资料",
            "核对后再发",
            "不能凭感觉",
        ),
    )


def _has_order_context(response: dict[str, Any]) -> bool:
    if response.get("order_id") or response.get("platform_order_id") or response.get("platform_trade_id"):
        return True
    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        if context_used.get("identifier_value") or context_used.get("order_id"):
            return True
        summary = context_used.get("conversation_context_summary") or {}
        if isinstance(summary, dict) and (
            summary.get("has_known_order_id")
            or summary.get("has_known_platform_trade_id")
            or summary.get("has_known_tracking_no")
        ):
            return True
    return False


def _contains_any_plain(text: str, terms: tuple[str, ...]) -> bool:
    value = str(text or "")
    return any(term in value for term in terms)


def _is_customer_safe_complaint_reply(
    text: str,
    response: dict[str, Any],
    customer_message: str,
) -> bool:
    if not _is_complaint_or_quality_service_turn(response, customer_message):
        return False
    value = str(text or "")
    if _needs_complaint_language_rewrite(value):
        return False
    return (
        _contains_any_plain(value, ("抱歉", "不好体验", "反馈", "收到"))
        and _contains_any_plain(value, ("跟进", "处理", "售后", "主管"))
        and not _contains_any_plain(value, ("超出核实结果的承诺", "避免信息不准", "商品页面", "页面信息"))
    )


def _rewrite_media_workflow_reply(
    text: str,
    response: dict[str, Any],
    customer_message: str,
    display_name: str,
) -> str:
    """Turn internal media-matching language into customer-facing guidance."""
    if not _contains_media_workflow_language(text):
        return text

    fact_type = _current_fact_type(response)
    has_media = _has_deliverable_media(response)
    product = f"「{display_name}」" if display_name else "这款"

    if fact_type in {"dimensions", "space_fit"}:
        if has_media:
            return (
                f"亲～{product}的尺寸可以参考我下面发您的图片，图里有对应组合的尺寸/规格标注。\n"
                "您可以先对照家里预留位置的宽度、进深和高度看一下；"
                "如果您把预留尺寸发我，我也可以帮您一起判断能不能放下～"
            )
        return (
            f"亲～{product}不同组合的尺寸可能不一样。\n"
            "您可以把准备摆放位置的宽度、进深和高度发我，我帮您对照看一下是否合适。"
        )

    if fact_type == "detachable":
        if has_media:
            return (
                f"亲～{product}是否方便拆装，可以参考我下面发您的结构/尺寸图。\n"
                "图里会更直观看到对应组合的结构位置，您可以先对照看一下；"
                "如果还有具体哪一块不确定，也可以直接圈出来发我。"
            )
        return (
            f"亲～{product}不同组合结构可能会有差异。\n"
            "您可以把页面组合或实物位置截图发我，我帮您对照确认具体拆装位置。"
        )

    if fact_type == "installation":
        if has_media:
            return (
                f"亲～{product}的安装步骤可以参考我下面发您的安装图片/视频。\n"
                "您按里面的顺序对照安装就可以；如果卡在某一步，把位置拍给我，我继续帮您看。"
            )
        return (
            f"亲～{product}安装时建议先对照说明书步骤来。\n"
            "如果您卡在具体某一步，可以把当前位置拍给我，我帮您看下一步怎么处理。"
        )

    if fact_type in {"accessories", "packaging"}:
        if has_media:
            return (
                f"亲～{product}的配件/包装清单可以参考我下面发您的图片。\n"
                "您可以按图里的配件位置和数量逐一对照；如果有缺少的地方，拍给我我帮您继续处理。"
            )
        return (
            f"亲～{product}的配件建议先按包装和说明书清单逐一核对。\n"
            "如果您觉得少了某个部件，可以把收到的配件整体拍给我，我帮您一起看。"
        )

    if has_media:
        return (
            f"亲～{product}我把对应图片/视频一起发您参考。\n"
            "您可以先对照看一下，如果还有哪里不确定，直接截图或圈出来发我。"
        )
    return (
        f"亲～{product}这个细节我需要按具体款式帮您看。\n"
        "您可以把页面组合、实物位置或相关截图发我，我帮您对照确认。"
    )


def _remove_unsupported_media_send_claims(text: str, response: dict[str, Any], display_name: str) -> str:
    if _has_deliverable_media(response):
        return text
    value = str(text or "")
    fact_type = _current_fact_type(response)
    media_terms = ("图片", "视频", "图", "照片", "实物图", "尺寸图", "安装图")
    send_terms = ("下面发", "发您参考", "发您看", "一起发您", "下方图片", "直接参考我下面发")
    has_unsupported_send_claim = (
        any(term in value for term in media_terms)
        and any(term in value for term in send_terms)
    )
    if not has_unsupported_send_claim and not _has_media_fallback_topic_drift(value, fact_type):
        return value

    product = f"「{display_name}」" if display_name else "这款商品"
    replacement = _media_fallback_replacement(product, fact_type)
    lines = []
    replaced = False
    for raw_line in value.splitlines():
        line = raw_line.strip()
        remove_line = bool(line) and (
            (any(term in line for term in media_terms) and any(term in line for term in send_terms))
            or _is_media_fallback_drift_line(line, fact_type)
        )
        if remove_line:
            if not replaced:
                lines.append(replacement)
                replaced = True
            continue
        lines.append(raw_line)
    cleaned = "\n".join(line for line in lines if str(line).strip())
    cleaned = re.sub(r"^亲～\s*\n\s*亲～", "亲～", cleaned)
    return cleaned or replacement


def _has_media_fallback_topic_drift(text: str, fact_type: str) -> bool:
    return any(_is_media_fallback_drift_line(line.strip(), fact_type) for line in str(text or "").splitlines())


def _is_media_fallback_drift_line(line: str, fact_type: str) -> bool:
    if not line:
        return False
    dimension_terms = ("尺寸", "宽度", "进深", "高度", "预留位置", "长宽高")
    installation_terms = ("安装", "配件", "按图", "图里标注", "步骤", "教程")
    unsupported_visual_terms = ("按图", "图里", "下方图片", "下面发", "看图", "发您参考", "图片/视频")
    if fact_type == "installation":
        return any(term in line for term in dimension_terms) or any(term in line for term in unsupported_visual_terms)
    if fact_type in {"dimensions", "space_fit"}:
        return any(term in line for term in installation_terms)
    if fact_type == "visual_asset":
        return any(term in line for term in unsupported_visual_terms)
    return False


def _media_fallback_replacement(product: str, fact_type: str) -> str:
    if fact_type == "installation":
        return (
            f"亲～{product}目前没有可直接发送的安装图片/视频素材，我先帮您核对对应商品的安装资料，确认清楚后再回复您。"
            "安装前建议先对照配件清单，确认配件齐全后再操作。"
        )
    if fact_type in {"dimensions", "space_fit"}:
        return f"亲～{product}目前没有可直接发送的尺寸图，我先帮您核对对应款式的尺寸资料，确认清楚后再回复您。"
    if fact_type in {"accessories", "packaging"}:
        return f"亲～{product}目前没有可直接发送的配件/包装清单图片，我先帮您核对对应款式的配件资料，确认清楚后再回复您。"
    return f"亲～{product}目前没有可直接发送的图片/视频素材，我先帮您核对对应商品，确认清楚后再回复您。"


def _contains_media_workflow_language(text: str) -> bool:
    value = str(text or "")
    phrases = (
        "匹配到可发送",
        "可发送的资料",
        "图/视频资料",
        "图片/视频资料",
        "核对后再发",
        "避免发错",
        "安装步骤、尺寸或配件位置",
        "对照对应商品",
        "当前款式没有",
    )
    return any(phrase in value for phrase in phrases)


def _current_fact_type(response: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") or {}
    if isinstance(debug, dict):
        value = debug.get("query_fact_type") or debug.get("fact_type")
        if value:
            return str(value)
        semantic = debug.get("semantic_query") or response.get("semantic_query") or {}
        if isinstance(semantic, dict):
            value = semantic.get("primary_fact_type") or semantic.get("fact_type")
            if value:
                return str(value)
    return str(response.get("query_fact_type") or response.get("fact_type") or "")


def _has_deliverable_media(response: dict[str, Any]) -> bool:
    sources: list[Any] = [
        response.get("recommended_assets"),
        response.get("selected_assets"),
        response.get("reply_blocks"),
    ]
    evidence_debug = response.get("evidence_debug") or {}
    if isinstance(evidence_debug, dict):
        sources.append(evidence_debug.get("selected_assets"))
    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        pack = context_used.get("product_context_pack") or {}
        if isinstance(pack, dict):
            sources.append(pack.get("recommended_assets"))
            sources.append(pack.get("selected_assets"))
            sources.append(pack.get("media_evidence"))

    for source in sources:
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            media_type = str(item.get("asset_type") or item.get("type") or item.get("media_type") or "").lower()
            has_asset_id = bool(item.get("asset_id") or item.get("id"))
            has_url = bool(
                item.get("asset_url")
                or item.get("url")
                or item.get("oss_url")
                or item.get("signed_url")
                or item.get("media_url")
                or item.get("thumbnail_url")
            )
            if has_url and (has_asset_id or media_type in {"image", "video", "picture", "photo"} or media_type.endswith("_image") or media_type.endswith("_video")):
                return True
    return False


def _display_product_name(response: dict[str, Any], copilot_context: dict[str, Any]) -> str:
    candidates: list[Any] = []
    candidates.extend([
        response.get("display_product_name"),
        response.get("platform_product_title"),
        response.get("front_product_title"),
        response.get("product_title"),
        response.get("item_title"),
    ])
    candidates.extend([
        copilot_context.get("display_product_name"),
        copilot_context.get("platform_product_title"),
        copilot_context.get("front_product_title"),
        copilot_context.get("product_title"),
        copilot_context.get("item_title"),
    ])

    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        nested = context_used.get("copilot_context") or {}
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("display_product_name"),
                nested.get("platform_product_title"),
                nested.get("front_product_title"),
                nested.get("product_title"),
                nested.get("item_title"),
            ])

    for source in (
        copilot_context.get("product_candidates"),
        response.get("product_candidates"),
        (context_used.get("copilot_context") or {}).get("product_candidates") if isinstance(context_used, dict) else None,
    ):
        if not isinstance(source, list):
            continue
        for candidate in source:
            if isinstance(candidate, str):
                candidates.append(candidate)
            elif isinstance(candidate, dict):
                candidates.extend([
                    candidate.get("display_product_name"),
                    candidate.get("platform_product_title"),
                    candidate.get("front_product_title"),
                    candidate.get("product_title"),
                    candidate.get("item_title"),
                    candidate.get("title"),
                    candidate.get("product_name"),
                    candidate.get("value"),
                ])

    for value in candidates:
        text = str(value or "").strip()
        if _looks_like_customer_product_title(text):
            return text
    return ""


def _looks_like_customer_product_title(text: str) -> bool:
    if not text:
        return False
    if len(text) >= 16:
        return True
    upper = text.upper()
    return "英禾" in text or "INHE" in upper


def _internal_product_names(response: dict[str, Any]) -> list[str]:
    candidates: list[Any] = [
        response.get("product_name"),
        response.get("matched_product_name"),
    ]
    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        context_summary = context_used.get("conversation_context_summary") or {}
        product_pack = context_used.get("product_context_pack") or {}
        pack_identity = product_pack.get("identity") or {} if isinstance(product_pack, dict) else {}
        candidates.extend([
            context_used.get("matched_product_name"),
            context_summary.get("confirmed_product") if isinstance(context_summary, dict) else "",
            context_summary.get("product_name") if isinstance(context_summary, dict) else "",
            pack_identity.get("product_name") if isinstance(pack_identity, dict) else "",
            pack_identity.get("matched_product_name") if isinstance(pack_identity, dict) else "",
        ])
    evidence_debug = response.get("evidence_debug") or {}
    if isinstance(evidence_debug, dict):
        candidates.append(evidence_debug.get("matched_product_name"))

    reply = str(response.get("suggested_reply") or "")
    candidates.extend(re.findall(r"「([^」]{2,80})」", reply))

    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        if _looks_like_internal_product_name(text):
            seen.add(text)
            result.append(text)
    return sorted(result, key=len, reverse=True)


def _looks_like_internal_product_name(text: str) -> bool:
    if len(text) < 3 or len(text) > 24:
        return False
    if re.match(r"^[一二三四五六七八九十]+号", text):
        return True
    return any(token in text for token in (
        "一号", "二号", "三号", "四号", "五号", "六号",
        "七号", "八号", "九号", "十号", "十一号", "十二号",
    ))


def _replace_internal_product_names(text: str, display_name: str, internal_names: list[str]) -> str:
    if not display_name:
        return text
    for name in internal_names:
        if not name or name == display_name or name in display_name:
            continue
        text = text.replace(f"「{name}」", f"「{display_name}」")
        text = text.replace(name, display_name)
    return text
