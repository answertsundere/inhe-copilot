"""Fact type classification and evidence matching helpers.

This module is intentionally deterministic. It centralizes the small amount of
keyword logic needed for Phase 1 so the rules do not spread across retrieval,
generation, and UI code.
"""

from __future__ import annotations

from typing import Any


FACT_TYPE_LABELS = {
    "material": "材质",
    "certification_report": "检测/认证报告",
    "load_capacity": "承重",
    "stability": "\u7a33\u5b9a/\u9632\u503e\u5012",
    "dimensions": "尺寸",
    "age_range": "适用年龄",
    "cleaning_care": "清洁保养",
    "odor": "气味",
    "installation": "安装",
    "variant_compare": "款式差异",
    "stock_shipping": "库存/发货",
    "invoice_policy": "发票政策",
    "price_protection": "价保政策",
    "promotion_policy": "优惠活动",
    "gift_policy": "赠品政策",
    "safety_small_parts": "小零件/电池安全",
    "aftersales_policy": "售后政策",
}


_QUERY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("safety_small_parts", ("误吞", "吞了", "吞到", "卡喉", "窒息", "电池盖", "电池仓", "小零件", "零件松", "宝宝受伤", "孩子受伤", "夹到手", "夹手")),
    ("certification_report", ("甲醛", "检测报告", "检查报告", "质检报告", "检验报告", "合格证", "环保证书", "认证", "证书", "3C", "食品级")),
    ("variant_compare", ("基础款", "升级款", "升级版", "差什么", "区别", "差别", "差异", "对比", "哪个更好")),
    ("price_protection", ("价保", "保价", "价格保护", "买贵", "降价")),
    ("invoice_policy", ("发票", "开发票", "电子发票", "抬头", "税号")),
    ("promotion_policy", ("优惠", "活动", "券", "满减", "便宜", "折扣", "赠送", "送我")),
    ("gift_policy", ("赠品", "礼品", "没送", "少送", "漏发赠品")),
    ("stock_shipping", ("有货", "库存", "今天拍", "今天发", "什么时候发", "能发吗", "上发", "发货")),
    ("cleaning_care", ("清洁", "清理", "脏了", "水洗", "洗吗", "怎么洗", "擦洗", "可以洗", "酒精擦")),
    ("odor", ("味道", "异味", "刺鼻", "闻着", "散味")),
    ("age_range", ("适合多大", "适合几岁", "几个月", "多大宝宝", "几岁", "年龄")),
    ("stability", (
        "\u7edd\u5bf9\u4e0d\u4f1a\u5012",
        "\u4e0d\u4f1a\u5012",
        "\u4f1a\u4e0d\u4f1a\u5012",
        "\u9632\u503e\u5012",
        "\u503e\u5012",
        "\u5012\u584c",
        "\u7a33\u4e0d\u7a33",
        "\u7a33\u56fa",
        "\u7a33\u5b9a",
        "\u7a33\u5417",
    )),
    ("load_capacity", ("承重", "能放多重", "放多重", "结实", "稳不稳", "会不会倒")),
    ("dimensions", ("尺寸", "多高", "多宽", "多长", "高度", "长度", "宽度", "占地")),
    ("installation", ("安装", "怎么装", "装不上", "螺丝", "配件", "说明书", "安装视频", "教程", "组装", "拼接")),
    ("material", ("材质", "材料", "什么料", "用料", "板材", "实木", "环保", "安全吗", "安全", "受潮", "防潮", "生锈")),
    ("aftersales_policy", ("退货", "退款", "换货", "补发", "售后", "破损", "坏了", "少件", "发错")),
]


_EVIDENCE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("certification_report", ("甲醛", "检测报告", "检查报告", "质检报告", "检验报告", "合格证", "环保证书", "认证", "证书", "3C", "食品级")),
    ("variant_compare", ("基础款", "升级款", "升级版", "差别", "区别", "差异", "对比", "款式")),
    ("cleaning_care", ("清洁", "清理", "水洗", "擦拭", "酒精", "保养")),
    ("odor", ("味道", "异味", "刺鼻", "散味", "通风")),
    ("age_range", ("适合", "年龄", "宝宝", "月龄", "岁")),
    ("stability", (
        "\u7edd\u5bf9\u4e0d\u4f1a\u5012",
        "\u4e0d\u4f1a\u5012",
        "\u4f1a\u4e0d\u4f1a\u5012",
        "\u9632\u503e\u5012",
        "\u503e\u5012",
        "\u5012\u584c",
        "\u7a33\u4e0d\u7a33",
        "\u7a33\u56fa",
        "\u7a33\u5b9a",
        "\u5b89\u5168\u6263",
    )),
    ("load_capacity", ("承重", "载重", "能放", "结实", "稳固", "kg", "KG")),
    ("dimensions", ("尺寸", "高度", "宽度", "长度", "cm", "CM", "厘米")),
    ("installation", ("安装", "组装", "螺丝", "配件", "说明书", "工具", "步骤", "卡扣")),
    ("material", ("材质", "材料", "用料", "PP", "PET", "ABS", "钢管", "铁管", "冷轧钢", "无纺布", "塑料", "板材", "木")),
    ("stock_shipping", ("库存", "发货", "现货", "出库", "预售")),
    ("invoice_policy", ("发票", "抬头", "税号")),
    ("price_protection", ("价保", "保价", "降价")),
    ("promotion_policy", ("优惠", "活动", "券", "满减", "折扣")),
    ("gift_policy", ("赠品", "礼品", "随单")),
    ("safety_small_parts", ("误吞", "电池", "小零件", "松动", "夹手", "受伤", "暂停使用")),
    ("aftersales_policy", ("退货", "退款", "换货", "补发", "售后", "破损", "少件")),
]


_INTENT_DEFAULTS = {
    "invoice": "invoice_policy",
    "price_protection": "price_protection",
    "price_promotion": "price_protection",
    "promotion_query": "promotion_policy",
    "stock_query": "stock_shipping",
    "gift_missing": "gift_policy",
    "cleaning_care": "cleaning_care",
    "odor_question": "odor",
    "material_safety": "material",
    "installation": "installation",
    "aftersales": "aftersales_policy",
}


def classify_query_fact_type(message: str, intent: str = "") -> dict[str, Any]:
    """Classify the business fact field a customer is asking about."""
    msg = message or ""
    for fact_type, keywords in _QUERY_RULES:
        matched = [kw for kw in keywords if kw in msg]
        if matched:
            return {
                "query_fact_type": fact_type,
                "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
                "confidence": 0.9 if len(matched) > 1 else 0.78,
                "matched_terms": matched[:5],
                "source": "rule",
            }

    fact_type = _INTENT_DEFAULTS.get(intent, "")
    if fact_type:
        return {
            "query_fact_type": fact_type,
            "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
            "confidence": 0.58,
            "matched_terms": [],
            "source": "intent_default",
        }

    return {
        "query_fact_type": "",
        "query_fact_type_label": "",
        "confidence": 0.0,
        "matched_terms": [],
        "source": "none",
    }


def infer_evidence_fact_type(item: dict | None = None, text: str = "") -> str:
    """Infer fact_type from explicit metadata first, then title/content text."""
    item = item or {}
    explicit = (
        item.get("fact_type")
        or item.get("query_fact_type")
        or (item.get("metadata") or {}).get("fact_type")
        or (item.get("metadata") or {}).get("query_fact_type")
    )
    if explicit:
        return str(explicit)

    title_text = " ".join(str(x or "") for x in (
        item.get("title", ""),
        item.get("matched_title", ""),
        item.get("question", ""),
    ))
    if any(kw in title_text for kw in ("安装", "怎么装", "组装", "装不上", "说明书")):
        return "installation"

    haystack = " ".join(str(x or "") for x in (
        text,
        item.get("title", ""),
        item.get("matched_title", ""),
        item.get("chunk_text", ""),
        item.get("fact", ""),
        item.get("content", ""),
        item.get("category", ""),
        item.get("category_l3", ""),
        item.get("issue_type", ""),
    ))
    for fact_type, keywords in _EVIDENCE_RULES:
        if any(kw in haystack for kw in keywords):
            return fact_type
    return ""


def fact_type_matches(query_fact_type: str, evidence_fact_type: str) -> bool:
    """Return whether evidence can directly answer a query fact type."""
    if not query_fact_type:
        return True
    if not evidence_fact_type:
        return False
    if query_fact_type == evidence_fact_type:
        return True

    compatible = {
        "material": {"cleaning_care", "odor"},
        "cleaning_care": {"material"},
        "stock_shipping": {"promotion_policy"},
    }
    return evidence_fact_type in compatible.get(query_fact_type, set())


def is_strict_fact_type(query_fact_type: str) -> bool:
    """Strict types must not fall back to neighboring product facts."""
    return query_fact_type in {
        "certification_report",
        "age_range",
        "safety_small_parts",
        "stability",
        "variant_compare",
        "invoice_policy",
        "price_protection",
    }
