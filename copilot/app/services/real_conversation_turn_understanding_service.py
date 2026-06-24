"""Lightweight understanding for real-conversation replay turns.

The replay evaluator needs to know whether a buyer turn is an actual question
before it judges the Agent reply. This module only classifies the current turn;
it does not retrieve knowledge, call tools, or rewrite product facts.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.eval_sanitizer_service import sanitize_text


PRODUCT_FACT_TOPICS = {
    "dimensions": ("尺寸", "长宽高", "多高", "多宽", "多长", "高度", "宽度", "深度", "最窄", "规格"),
    "space_fit": ("放得下", "放的下", "摆得下", "摆的下", "空间", "占地方", "占地", "几平方", "平方"),
    "load_capacity": ("承重", "载重", "多重", "压弯", "压塌", "结实", "放很多书", "容量"),
    "material": ("材质", "材料", "板材", "环保", "防潮", "受潮", "防水", "甲醛", "气味", "material"),
    "installation": ("安装", "组装", "装", "教程", "说明书", "视频", "打孔", "螺丝", "install", "installation", "video"),
    "age_range": ("适合几岁", "适合多大", "年龄", "月龄", "宝宝", "儿童", "孩子"),
    "stock_shipping": ("发货", "现货", "库存", "几天到", "物流", "快递", "签收", "没收到"),
    "aftersales": (
        "退", "退款", "退货", "换", "换货", "补发", "漏发", "缺件", "少件",
        "少了", "没有", "破损", "售后", "发错", "不对", "对不上", "不一样",
        "不太一样", "物品", "wrong item",
    ),
}

FORBIDDEN_TOPICS_BY_ACTIONABILITY = {
    "context_update": ["dimensions", "space_fit", "load_capacity", "material", "age_range"],
    "acknowledgement": ["dimensions", "space_fit", "load_capacity", "material", "installation", "age_range"],
    "noise": ["dimensions", "space_fit", "load_capacity", "material", "installation", "age_range"],
    "deictic_followup": ["dimensions", "space_fit", "load_capacity", "material", "installation", "age_range"],
    "media_reference": ["dimensions", "space_fit", "load_capacity", "material", "installation", "age_range"],
}

QUESTION_MARKERS = ("?", "？", "吗", "么", "呢", "怎么", "怎样", "如何", "多少", "几", "有没有", "能不能", "是否", "question")
REQUEST_MARKERS = ("请", "发", "给我", "帮我", "麻烦", "需要", "要", "想要", "看看", "处理", "补发", "退", "换")
STATUS_TERMS = ("收到", "收到了", "到货", "到了", "拿到", "装好", "装好了", "装完", "安装好", "安装好了", "处理好", "解决了")
ACK_TERMS = {"好", "好的", "嗯", "恩", "嗯嗯", "哦", "噢", "行", "可以", "知道了", "收到", "谢谢", "谢了", "ok", "OK"}
DEICTIC_TERMS = ("这个", "这个呢", "这一块", "这块", "这里", "那个", "那这个", "单门的", "抽屉的", "也行", "也可以", "为什么", "为何", "咋回事", "怎么回事")
MEDIA_TERMS = ("图里", "图片", "照片", "视频", "圈出来", "拍的", "这里", "这个位置")


@dataclass
class TurnUnderstanding:
    turn_actionability: str
    needs_agent_reply: bool
    needs_rag: bool
    needs_tool: bool
    should_score: bool
    reply_strategy: str
    context_dependency: str
    forbidden_reply_topics: list[str] = field(default_factory=list)
    reason: str = ""
    query_fact_type: str = ""
    skip_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RealConversationTurnUnderstandingService:
    def understand(
        self,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        message_type: str = "text",
        product_hint: str = "",
    ) -> dict[str, Any]:
        text = sanitize_text(message)
        history = history or []
        normalized = _normalize(text)
        message_type_text = str(message_type or "").lower()

        if _looks_corrupted(text):
            return TurnUnderstanding(
                turn_actionability="noise",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=False,
                reply_strategy="skip",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["noise"],
                reason="Message appears to be encoding-corrupted or unreadable.",
                skip_reason="encoding_corruption",
            ).to_dict()

        if not normalized:
            return TurnUnderstanding(
                turn_actionability="noise",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=False,
                reply_strategy="skip",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["noise"],
                reason="Empty buyer turn.",
                skip_reason="empty_message",
            ).to_dict()

        if _is_acknowledgement(normalized):
            return TurnUnderstanding(
                turn_actionability="acknowledgement",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=False,
                reply_strategy="skip",
                context_dependency="low",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["acknowledgement"],
                reason="Short acknowledgement does not require an Agent answer.",
                skip_reason="non_actionable_acknowledgement",
            ).to_dict()

        if _is_context_update(text):
            return TurnUnderstanding(
                turn_actionability="context_update",
                needs_agent_reply=True,
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="acknowledge_aftercare",
                context_dependency="medium",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["context_update"],
                reason="Buyer is reporting receipt, installation, or handling status rather than asking a product fact.",
            ).to_dict()

        fact_type = infer_query_fact_type(text)
        if _is_deictic_followup(text, fact_type):
            has_context = bool(history or product_hint)
            return TurnUnderstanding(
                turn_actionability="deictic_followup",
                needs_agent_reply=has_context,
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="normal_agent" if has_context else "clarify_context",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["deictic_followup"],
                reason="Buyer turn is an elliptical follow-up that requires prior context.",
                skip_reason="" if has_context else "context_insufficient",
            ).to_dict()

        if (message_type_text in {"image", "图片", "video", "视频"} or _contains_any(text, MEDIA_TERMS)) and not _is_actionable_question(text, fact_type):
            return TurnUnderstanding(
                turn_actionability="media_reference",
                needs_agent_reply=bool(history),
                needs_rag=False,
                needs_tool=False,
                should_score=bool(history),
                reply_strategy="clarify_context" if not history else "normal_agent",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["media_reference"],
                reason="Buyer turn depends on media or visual context.",
                skip_reason="" if history else "context_insufficient",
            ).to_dict()

        if _is_actionable_question(text, fact_type):
            needs_media = "视频" in text or "图片" in text or "图" in text
            needs_rag = False if fact_type in {"stock_shipping", "aftersales"} else (bool(fact_type) or needs_media)
            return TurnUnderstanding(
                turn_actionability="actionable_question",
                needs_agent_reply=True,
                needs_rag=needs_rag,
                needs_tool=fact_type in {"stock_shipping", "aftersales"},
                should_score=True,
                reply_strategy="normal_agent",
                context_dependency="low" if product_hint or fact_type in {"stock_shipping", "aftersales"} else "medium",
                forbidden_reply_topics=[],
                reason="Buyer turn contains a question or request that needs an answer.",
                query_fact_type=fact_type,
            ).to_dict()

        return TurnUnderstanding(
            turn_actionability="noise",
            needs_agent_reply=False,
            needs_rag=False,
            needs_tool=False,
            should_score=False,
            reply_strategy="skip",
            context_dependency="high",
            forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["noise"],
            reason="Buyer turn is not actionable enough for automated scoring.",
            skip_reason="not_actionable",
        ).to_dict()


def infer_query_fact_type(text: str) -> str:
    value = str(text or "")
    if _is_aftersales_or_mismatch(value):
        return "aftersales"
    if any(term in value for term in ("视频", "教程", "说明书", "怎么装", "如何装", "安装")):
        return "installation"
    for fact_type, cues in PRODUCT_FACT_TOPICS.items():
        if any(cue in value for cue in cues):
            return fact_type
    return ""


def detect_reply_topics(text: str) -> list[str]:
    value = str(text or "")
    topics = []
    for fact_type, cues in PRODUCT_FACT_TOPICS.items():
        if any(cue in value for cue in cues):
            topics.append(fact_type)
    return topics


def _normalize(text: str) -> str:
    return re.sub(r"[\s~～!！?？.。,…，、；;：:]+", "", str(text or "")).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_acknowledgement(normalized: str) -> bool:
    return normalized in ACK_TERMS or (len(normalized) <= 4 and normalized.lower() in {item.lower() for item in ACK_TERMS})


def _is_context_update(text: str) -> bool:
    if not _contains_any(text, STATUS_TERMS):
        return False
    return not _has_question_or_request(text)


def _is_deictic_followup(text: str, fact_type: str = "") -> bool:
    stripped = _normalize(text)
    if fact_type:
        return False
    if stripped in {"为什么", "为何", "咋回事", "怎么回事"}:
        return True
    if stripped in {re.sub(r"[\s~～!！?？.。,…，、；;：:]+", "", item) for item in DEICTIC_TERMS}:
        return True
    return len(stripped) <= 8 and _contains_any(text, DEICTIC_TERMS) and not _has_question_or_request(text)


def _is_actionable_question(text: str, fact_type: str) -> bool:
    if _has_question_or_request(text):
        return True
    return bool(fact_type and not _is_context_update(text))


def _has_question_or_request(text: str) -> bool:
    return _contains_any(text, QUESTION_MARKERS) or _contains_any(text, REQUEST_MARKERS)


def _is_aftersales_or_mismatch(text: str) -> bool:
    value = str(text or "")
    if any(term in value for term in ("退", "退款", "退货", "换", "换货", "补发", "少件", "缺件", "漏发", "发错", "破损", "售后")):
        return True
    mismatch_terms = ("不对", "对不上", "不一样", "不太一样", "不匹配", "不符合")
    sent_material_terms = ("说明书", "视频", "发过来", "发来的", "发给我", "物品", "东西", "买的")
    return any(term in value for term in mismatch_terms) and any(term in value for term in sent_material_terms)


def _looks_corrupted(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if value.count("?") >= 3 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", value):
        return True
    mojibake_markers = ("锛", "绔", "浣", "妗", "鐭", "璧", "瀹", "鍟")
    return sum(1 for marker in mojibake_markers if marker in value) >= 2
