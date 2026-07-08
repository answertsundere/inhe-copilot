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
    "dimensions": ("尺寸", "长宽高", "多大", "多高", "多宽", "多长", "多厚", "厚度", "高度", "宽度", "深度", "最窄", "规格"),
    "space_fit": ("放得下", "放的下", "摆得下", "摆的下", "空间", "占地方", "占地", "几平方", "平方"),
    "load_capacity": ("承重", "载重", "多重", "压弯", "压塌", "结实", "放很多书", "容量", "承放"),
    "material": ("材质", "材料", "板材", "塑料", "什么塑料", "环保", "防潮", "受潮", "防水", "甲醛", "气味", "material"),
    "installation": ("安装", "组装", "装", "教程", "说明书", "视频", "打孔", "螺丝", "贴纸", "背胶", "贴哪", "贴哪里", "install", "installation", "video"),
    "placement_scene": ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "可以放", "可以用", "适合放"),
    "age_range": ("适合几岁", "适合多大", "年龄", "月龄", "宝宝", "儿童", "孩子"),
    "return_pickup": ("上门取件", "退货取件", "快递取件", "预约取件", "取件码", "取件员", "取件安排", "上门揽收", "快递揽收", "揽收"),
    "stock_shipping": (
        "发货", "现货", "库存", "几天到", "什么时候到", "明天能到", "能到吗", "到吗",
        "物流", "快递", "签收", "没收到", "发出", "发出来", "单号", "运单号", "送货上门",
    ),
    "aftersales": (
        "退", "退款", "退货", "换", "换货", "补发", "漏发", "缺件", "少件",
        "少了", "没有", "破损", "售后", "发错", "不对", "对不上", "不一样",
        "不太一样", "物品", "滑牙", "螺帽滑牙", "wrong item",
    ),
    "variant_compare": ("两款", "哪款", "哪个更", "哪款更", "区别", "差别", "对比", "数量更多"),
    "invoice_policy": ("发票", "开发票", "开票", "抬头", "税号"),
    "order_assistance": (
        "改地址", "改一下地址", "修改地址", "换地址", "改收货地址", "地址没改",
        "地址错", "下单的地址错", "发到这个地址", "发这个地址", "新地址",
        "怎么下单", "怎样下单", "下单链接", "规格怎么选",
    ),
}

PROMOTION_TERMS = (
    "福利",
    "优惠",
    "活动",
    "优惠券",
    "券",
    "红包",
    "返现",
    "晒图",
    "好评",
    "赠品",
    "买赠",
    "满减",
    "立减",
    "折扣",
    "返多少",
    "有没有送",
    "有什么送",
)
PRICE_NEGOTIATION_TERMS = (
    "便宜",
    "便宜点",
    "少点",
    "最低多少",
    "最低价",
    "套餐价",
    "优惠价",
    "多买",
    "买两个",
)
RETURN_PICKUP_TERMS = (
    "上门取件",
    "退货取件",
    "快递取件",
    "预约取件",
    "取件码",
    "取件员",
    "取件安排",
    "上门揽收",
    "快递揽收",
    "揽收",
    "取走退货",
)
AFTERSALES_STRONG_TERMS = (
    "质量问题",
    "全新的",
    "不是全新",
    "二手",
    "没收到",
    "没有收到",
    "未收到",
    "没拿到",
    "没看见",
    "没收到货",
    "没收到这个",
    "同一边",
    "同边",
    "重复的",
    "退货",
    "退款",
    "换货",
    "补发",
    "少件",
    "缺件",
    "少了",
    "只有",
    "只发",
    "只收到",
    "差一个",
    "还差",
    "漏发",
    "发错",
    "不一致",
    "不对",
    "对不上",
    "不一样",
    "破损",
    "断了",
    "裂了",
    "破了",
    "坏了",
    "掉了",
    "碎了",
    "开裂",
    "变形",
    "缺角",
    "断裂",
    "损坏",
    "压坏",
    "磕坏",
    "投诉",
    "赔偿",
    "补偿",
    "残次",
    "残次品",
    "质保",
    "保修",
    "没到一年",
    "对不上号",
    "对上号",
)


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
REASON_FOLLOWUP_TERMS = ("为什么", "为啥", "为何", "咋回事", "怎么回事")
DEICTIC_TERMS = ("这个", "这个呢", "这款", "这款呢", "这一块", "这块", "这里", "那个", "那这个", "这样的", "这种", "单门的", "抽屉的", "也行", "也可以", *REASON_FOLLOWUP_TERMS)
MEDIA_TERMS = ("图里", "图片", "照片", "视频", "圈出来", "拍的", "这里", "这个位置")
URL_OR_LINK_RE = re.compile(r"(https?://|www\.|item\.(taobao|tmall)\.com|img\.alicdn\.com|\.jpg|\.jpeg|\.png|\.mp4)", re.I)
EXTRA_QUESTION_MARKERS = (
    "？", "吗", "呢", "嘛", "怎么", "怎样", "如何", "多少", "几", "有没有", "能不能", "会不会", "是不是", "可不可以", "行不行",
)
SERVICE_OR_SYSTEM_TERMS = (
    "欢迎光临", "您好~欢迎", "自动回复", "转人工", "人工客服", "客服已接入", "请稍等",
    "咨询量大", "不是有意怠慢", "看到消息后", "为您服务",
)
PREFERENCE_UPDATE_TERMS = ("我要白色", "要白色", "我要大号", "要大号", "再买一个", "备注", "换成白色", "换白色")
ACCESSORY_COMPONENT_TERMS = ("防倒器", "双面贴", "顶板", "底板", "背板", "侧板", "层板", "板件", "螺丝", "配件", "卡扣", "固定件", "垫片", "安全带", "指甲刀", "工具", "套装", "其他", "其它")
ACCESSORY_USAGE_TERMS = ("干啥用", "做什么用", "用来干啥", "哪个是", "是哪一个", "怎么用", "装哪里", "贴哪里", "放哪里", "作用", "用途")
ACCESSORY_PRESENCE_TERMS = ("有吗", "有没有", "带吗", "配吗", "含吗", "送吗")
ACCESSORY_RETENTION_COMPONENT_TERMS = (*ACCESSORY_COMPONENT_TERMS, "螺丝刀", "工具")
ACCESSORY_RETENTION_TERMS = ("留下", "留着", "保留", "还要用", "还需要用", "后面要用", "后面还要用", "后面还需要用")
MISSING_QUANTITY_OBJECT_TERMS = ("配件", "零件", "部件", "螺丝", "板子", "面板", "层板", "抽屉", "件")
MISSING_QUANTITY_TERMS = ("只有", "只发", "只收到", "少了", "少", "缺", "差一个", "还差")
STRUCTURE_OBJECT_TERMS = ("一边", "侧边", "侧板", "护栏", "围栏", "门", "挡板", "板子", "抽屉", "靠背", "背板", "隔板", "层板", "顶板", "底板", "孔位", "螺丝孔", "预留孔")
STRUCTURE_ACTION_TERMS = ("放下来", "放下", "翻下来", "翻起", "打开", "收起", "折叠", "调节", "拆下来", "拆卸", "固定", "活动", "能动", "加装", "加个", "再加", "补", "补配", "打孔", "对上", "对齐", "匹配")
STRUCTURE_COMPATIBILITY_OBJECT_TERMS = (*STRUCTURE_OBJECT_TERMS, "配件", "第四面", "一面")
STRUCTURE_COMPATIBILITY_ACTION_TERMS = (
    "补第四面",
    "补一面",
    "补配件",
    "补一个",
    "补",
    "加装",
    "适配",
    "能不能配",
    "能配",
    "配吗",
    "单独配",
    "能不能装这款",
    "能装这款",
    "装这款",
)
STRUCTURE_CONFIRM_TERMS = ("不是可以", "可以吗", "能不能", "是不是", "怎么", "有吗", "吗", "呢")
STRUCTURE_SCENE_BLOCKERS = ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间")
STRUCTURE_SPACE_BLOCKERS = ("空间", "空间小", "放不下", "尺寸", "长宽高", "几平方", "平方", "占地方", "预留")
SPACE_FIT_OBJECT_TERMS = ("柜子", "床", "床垫", "书架", "收纳柜", "置物架", "架子", "桌子", "鞋柜")
SPACE_FIT_ACTION_TERMS = ("能不能放下", "能放下", "放得下", "放的下", "摆得下", "摆的下", "够不够放", "放不放得下")
LOAD_CAPACITY_UNIT_TERMS = ("公斤", "kg", "KG", "斤")
LOAD_CAPACITY_CONTEXT_TERMS = ("承重", "载重", "能放", "放书", "压弯", "压扁", "压塌", "压坏", "架子", "隔板", "层板", "顶板", "底板")


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
    secondary_fact_types: list[str] = field(default_factory=list)
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

        if _is_url_or_link_only(text):
            return TurnUnderstanding(
                turn_actionability="media_reference",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=False,
                reply_strategy="skip",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["media_reference"],
                reason="Buyer turn is only a URL or media link, not a product-fact question.",
                skip_reason="link_or_media_only",
            ).to_dict()

        if _is_link_share_without_actionable_request(text):
            return TurnUnderstanding(
                turn_actionability="media_reference",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=False,
                reply_strategy="skip",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["media_reference"],
                reason="Buyer shared a product or media link without asking an actionable question.",
                skip_reason="link_or_media_only",
            ).to_dict()

        if _is_service_or_system_fragment(text):
            return TurnUnderstanding(
                turn_actionability="noise",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=False,
                reply_strategy="skip",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["noise"],
                reason="Turn looks like service/system boilerplate rather than a buyer question.",
                skip_reason="service_or_system_fragment",
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

        if _is_accessory_retention_update(text):
            return TurnUnderstanding(
                turn_actionability="context_update",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="acknowledge_context_update",
                context_dependency="medium",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["context_update"],
                reason="Buyer is adding accessory/component status context rather than asking an installation question.",
                skip_reason="context_update_no_question",
            ).to_dict()

        if (_is_context_update(text) or _is_preference_update(text)) and not _is_aftersales_or_mismatch(text):
            return TurnUnderstanding(
                turn_actionability="context_update",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="acknowledge_context_update",
                context_dependency="medium",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["context_update"],
                reason="Buyer is reporting receipt, installation, or handling status rather than asking a product fact.",
                skip_reason="context_update_no_question",
            ).to_dict()

        if _is_contextual_dimension_short_question(text) and not (history or product_hint):
            return TurnUnderstanding(
                turn_actionability="deictic_followup",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="clarify_context",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["deictic_followup"],
                reason="Buyer turn is a short dimension follow-up that requires prior product context.",
                skip_reason="context_insufficient",
            ).to_dict()

        fact_type, secondary_fact_types = infer_query_fact_types(text)
        if not fact_type and _is_order_address_followup(text, history):
            fact_type = "order_assistance"
        if not fact_type and _is_contextual_dimension_short_question(text) and (history or product_hint):
            fact_type = "dimensions"
        if (message_type_text in {"image", "图片", "video", "视频"} or _contains_any(text, MEDIA_TERMS)) and not _is_actionable_question(text, fact_type):
            return TurnUnderstanding(
                turn_actionability="media_reference",
                needs_agent_reply=False,
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="clarify_context",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["media_reference"],
                reason="Buyer turn depends on media or visual context and has no explicit actionable question.",
                skip_reason="context_insufficient",
            ).to_dict()

        if _is_deictic_followup(text, fact_type):
            has_context = bool(history or product_hint)
            return TurnUnderstanding(
                turn_actionability="deictic_followup",
                needs_agent_reply=has_context and not _is_fragment_only(text),
                needs_rag=False,
                needs_tool=False,
                should_score=True,
                reply_strategy="clarify_context",
                context_dependency="high",
                forbidden_reply_topics=FORBIDDEN_TOPICS_BY_ACTIONABILITY["deictic_followup"],
                reason="Buyer turn is an elliptical follow-up that requires prior context.",
                skip_reason="" if has_context and not _is_fragment_only(text) else "context_insufficient",
            ).to_dict()

        if _is_actionable_question(text, fact_type):
            needs_media = "视频" in text or "图片" in text or "图" in text
            needs_rag = False if fact_type in {"stock_shipping", "aftersales", "return_pickup"} else (bool(fact_type) or needs_media)
            reason = "Buyer asks accessory or component usage, identification, or presence." if _is_accessory_usage_question(text) else "Buyer turn contains a question or request that needs an answer."
            return TurnUnderstanding(
                turn_actionability="actionable_question",
                needs_agent_reply=True,
                needs_rag=needs_rag,
                needs_tool=fact_type in {"stock_shipping", "aftersales", "return_pickup"},
                should_score=True,
                reply_strategy="normal_agent",
                context_dependency="low" if product_hint or fact_type in {"stock_shipping", "aftersales", "return_pickup"} else "medium",
                forbidden_reply_topics=[],
                reason=reason,
                query_fact_type=fact_type,
                secondary_fact_types=secondary_fact_types,
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
    return infer_query_fact_types(text)[0]
    value = str(text or "")
    if _is_aftersales_or_mismatch(value):
        return "aftersales"
    if _is_accessory_usage_question(value):
        return "installation"
    if any(term in value for term in ("视频", "教程", "说明书", "怎么装", "如何装", "安装")):
        return "installation"
    for fact_type, cues in PRODUCT_FACT_TOPICS.items():
        if any(cue in value for cue in cues):
            return fact_type
    return ""


def infer_query_fact_types(text: str) -> tuple[str, list[str]]:
    value = str(text or "")
    has_promotion = _is_promotion_query(value)
    has_return_pickup = _is_return_pickup_query(value)
    has_aftersales = _is_aftersales_or_mismatch(value)
    if has_return_pickup and has_promotion:
        return "return_pickup", ["promotion", "aftersales"]
    if has_return_pickup:
        return "return_pickup", ["aftersales"]
    if has_aftersales and has_promotion:
        return "aftersales", ["promotion"]
    if has_promotion:
        return "promotion", []
    if has_aftersales:
        return "aftersales", []
    if _is_variant_compare_query(value):
        return "variant_compare", []
    if _is_logistics_query(value):
        return "stock_shipping", []
    if _is_load_capacity_with_weight_unit(value):
        return "load_capacity", []
    if _is_structure_function_query(value):
        return "structure_function", []
    if _is_space_fit_query(value):
        return "space_fit", []
    if _is_accessory_usage_question(value):
        return "installation", []
    if any(term in value for term in ("视频", "教程", "说明书", "怎么装", "如何装", "安装")):
        return "installation", []
    for fact_type, cues in PRODUCT_FACT_TOPICS.items():
        if any(cue in value for cue in cues):
            return fact_type, []
    return "", []


def detect_reply_topics(text: str) -> list[str]:
    value = str(text or "")
    topics = []
    if _is_promotion_query(value):
        topics.append("promotion")
    for fact_type, cues in PRODUCT_FACT_TOPICS.items():
        if any(cue in value for cue in cues):
            topics.append(fact_type)
    return topics


def _normalize(text: str) -> str:
    return re.sub(r"[\s~～!！?？.。,…，、；;：:]+", "", str(text or "")).strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_accessory_usage_question(text: str) -> bool:
    value = str(text or "")
    return _contains_any(value, ACCESSORY_COMPONENT_TERMS) and (
        _contains_any(value, ACCESSORY_USAGE_TERMS)
        or _contains_any(value, ACCESSORY_PRESENCE_TERMS)
    )


def _is_accessory_retention_update(text: str) -> bool:
    value = str(text or "")
    if not _contains_any(value, ACCESSORY_RETENTION_COMPONENT_TERMS):
        return False
    if not _contains_any(value, ACCESSORY_RETENTION_TERMS):
        return False
    if _contains_any(value, ACCESSORY_USAGE_TERMS) or _contains_any(value, ACCESSORY_PRESENCE_TERMS):
        return False
    if _is_aftersales_or_mismatch(value):
        return False
    return not _contains_any(value, QUESTION_MARKERS)


def _is_acknowledgement(normalized: str) -> bool:
    return normalized in ACK_TERMS or (len(normalized) <= 4 and normalized.lower() in {item.lower() for item in ACK_TERMS})


def _is_context_update(text: str) -> bool:
    if not _contains_any(text, STATUS_TERMS):
        return False
    return not _has_question_or_request(text)


def _is_link_share_without_actionable_request(text: str) -> bool:
    value = str(text or "")
    if not URL_OR_LINK_RE.search(value):
        return False
    text_without_links = re.sub(
        r"https?://\S+|www\.\S+|\S*(?:item\.taobao\.com|item\.tmall\.com|img\.alicdn\.com)\S*|\S+\.(?:jpg|jpeg|png|mp4)\S*",
        "",
        value,
        flags=re.I,
    )
    if _contains_any(text_without_links, QUESTION_MARKERS) or _contains_any(text_without_links, EXTRA_QUESTION_MARKERS):
        return False
    if _is_aftersales_or_mismatch(value) or _is_promotion_query(value):
        return False
    return True


def _is_deictic_followup(text: str, fact_type: str = "") -> bool:
    stripped = _normalize(text)
    if fact_type:
        return False
    if _is_fragment_only(text):
        return True
    if stripped in REASON_FOLLOWUP_TERMS:
        return True
    if stripped in {re.sub(r"[\s~～!！?？.。,…，、；;：:]+", "", item) for item in DEICTIC_TERMS}:
        return True
    if _is_context_dependent_short_question(stripped):
        return True
    return len(stripped) <= 8 and _contains_any(text, DEICTIC_TERMS) and not _has_question_or_request(text)


def _is_context_dependent_short_question(stripped: str) -> bool:
    if not stripped or len(stripped) > 10:
        return False
    if any(term in stripped for term in ("尺寸", "材质", "材料", "安装", "物流", "发货", "退", "换")):
        return False
    if any(term in stripped for term in ("这个", "那个", "这样的", "这种", "这里", "这款")) and any(term in stripped for term in ("可以吗", "行吗", "能吗", "有吗", "是吗", "对吗", "呢", "多大")):
        return True
    if any(term in stripped for term in ("哪个", "哪一个", "哪块", "哪边")):
        return True
    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]{1,6}的有吗", stripped))


def _is_contextual_dimension_short_question(text: str) -> bool:
    stripped = _normalize(text)
    return bool(re.fullmatch(r"(这个|这款|那个|那款)?(多大|多高|多宽|多长|几层|几格)", stripped))


def _is_actionable_question(text: str, fact_type: str) -> bool:
    if _has_question_or_request(text):
        return True
    return bool(fact_type and (fact_type in {"aftersales", "stock_shipping", "return_pickup"} or not _is_context_update(text)))


def _has_question_or_request(text: str) -> bool:
    return _contains_any(text, QUESTION_MARKERS) or _contains_any(text, EXTRA_QUESTION_MARKERS) or _contains_any(text, REQUEST_MARKERS)


def _is_promotion_query(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in PROMOTION_TERMS) or any(term in value for term in PRICE_NEGOTIATION_TERMS)


def _is_logistics_query(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in PRODUCT_FACT_TOPICS["stock_shipping"])


def _is_variant_compare_query(text: str) -> bool:
    value = str(text or "")
    has_compare_subject = any(term in value for term in ("两款", "哪款", "哪个更", "哪款更", "对比"))
    has_compare_relation = any(term in value for term in ("更多", "更好", "区别", "差别", "哪个更", "哪款更", "数量"))
    return has_compare_subject and has_compare_relation


def _is_order_address_followup(text: str, history: list[dict[str, Any]] | None) -> bool:
    value = str(text or "")
    direct_address_action = (
        any(term in value for term in ("地址错", "下单的地址错", "发到这个地址", "发这个地址", "新地址", "改地址", "修改地址", "换地址"))
        and any(term in value for term in ("地址", "发到", "发这个", "收货"))
    )
    if direct_address_action:
        return True
    if not any(term in value for term in ("没改", "没有改", "还没改", "显示没改")):
        return False
    recent = " ".join(str(item.get("text") or item.get("content") or item.get("message") or "") for item in (history or [])[-6:])
    return any(term in recent for term in ("改地址", "修改地址", "换地址", "收货地址", "地址"))


def _is_load_capacity_with_weight_unit(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in LOAD_CAPACITY_UNIT_TERMS) and any(
        term in value for term in LOAD_CAPACITY_CONTEXT_TERMS
    )


def _is_return_pickup_query(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in RETURN_PICKUP_TERMS)


def _is_structure_function_query(text: str) -> bool:
    value = str(text or "")
    if any(term in value for term in STRUCTURE_SCENE_BLOCKERS):
        return False
    if any(term in value for term in STRUCTURE_SPACE_BLOCKERS if term != "预留" or "预留孔" not in value):
        return False
    has_object = any(term in value for term in STRUCTURE_OBJECT_TERMS)
    has_action = any(term in value for term in STRUCTURE_ACTION_TERMS)
    has_compatibility_object = any(term in value for term in STRUCTURE_COMPATIBILITY_OBJECT_TERMS)
    has_compatibility_action = any(term in value for term in STRUCTURE_COMPATIBILITY_ACTION_TERMS)
    has_confirm = any(term in value for term in STRUCTURE_CONFIRM_TERMS) or _has_question_or_request(value)
    return has_confirm and ((has_object and has_action) or (has_compatibility_object and has_compatibility_action))


def _is_space_fit_query(text: str) -> bool:
    value = str(text or "")
    if any(term in value for term in STRUCTURE_SCENE_BLOCKERS):
        return False
    has_object = any(term in value for term in SPACE_FIT_OBJECT_TERMS)
    has_action = any(term in value for term in SPACE_FIT_ACTION_TERMS)
    return has_object and has_action


def _is_aftersales_or_mismatch(text: str) -> bool:
    value = str(text or "")
    if any(term in value for term in AFTERSALES_STRONG_TERMS):
        return True
    if any(term in value for term in MISSING_QUANTITY_TERMS) and any(term in value for term in MISSING_QUANTITY_OBJECT_TERMS):
        return True
    if any(term in value for term in ("退", "退款", "退货", "换", "换货", "补发", "少件", "缺件", "漏发", "发错", "破损", "售后")):
        return True
    mismatch_terms = ("不对", "对不上", "不一样", "不太一样", "不匹配", "不符合")
    sent_material_terms = ("说明书", "视频", "发过来", "发来的", "发给我", "物品", "东西", "买的")
    return any(term in value for term in mismatch_terms) and any(term in value for term in sent_material_terms)


def _is_url_or_link_only(text: str) -> bool:
    value = str(text or "").strip()
    if not URL_OR_LINK_RE.search(value):
        return False
    without_urls = re.sub(
        r"https?://\S+|www\.\S+|\S*(?:item\.taobao\.com|item\.tmall\.com|img\.alicdn\.com)\S*|\S+\.(?:jpg|jpeg|png|mp4)\S*",
        "",
        value,
        flags=re.I,
    )
    return len(_normalize(without_urls)) <= 2


def _is_service_or_system_fragment(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in SERVICE_OR_SYSTEM_TERMS)


def _is_preference_update(text: str) -> bool:
    value = str(text or "")
    return any(term in value for term in PREFERENCE_UPDATE_TERMS)


def _is_fragment_only(text: str) -> bool:
    stripped = _normalize(text)
    return stripped in {"吗", "呢", "啊", "这个", "这个呢", "这款", "这款呢", "哪个", "哪一个"}


def _looks_corrupted(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    if value.count("?") >= 3 and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", value):
        return True
    mojibake_markers = ("锛", "绔", "浣", "妗", "鐭", "璧", "瀹", "鍟")
    return sum(1 for marker in mojibake_markers if marker in value) >= 2
