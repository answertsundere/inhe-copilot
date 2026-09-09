"""Fact type classification and evidence matching helpers.

This module is intentionally deterministic. It centralizes the small amount of
keyword logic needed for Phase 1 so the rules do not spread across retrieval,
generation, and UI code.
"""

from __future__ import annotations

from typing import Any

from app.services.fact_type_alias_service import (
    canonical_material_composition_claim_type,
)


FACT_TYPE_LABELS = {
    # A broad product question is answerable only by restating concrete,
    # reviewed facts. It is not a quality, safety, or durability conclusion.
    "product_overview": (
        "商品整体概况/笼统产品评价（仅限已审核的材质和整体尺寸等具体事实，"
        "不得作为质量、安全、耐用或适用性结论）"
    ),
    "material_composition": "\u6750\u8d28",
    "material_safety": "\u6750\u8d28\u548c\u5b89\u5168\u8bf4\u660e",
    "bite_or_toxicity": "\u8bef\u5165\u53e3/\u8bef\u54ac\u5b89\u5168\u5904\u7406",
    "moisture_resistance": "\u9632\u6f6e\u60c5\u51b5",
    "child_safety": "\u513f\u7ae5\u4f7f\u7528\u5b89\u5168",
    "child_suitability": "\u513f\u7ae5\u9002\u7528\u60c5\u51b5",
    "installation_media": "\u5b89\u88c5\u8d44\u6599",
    "material": "材质",
    "certification_report": "检测/认证报告",
    "load_capacity": "承重",
    "stability": "\u7a33\u5b9a/\u9632\u503e\u5012",
    "dimensions": "尺寸",
    "space_fit": "空间适配",
    "placement_scene": "摆放场景",
    "structure_function": "结构功能/可调节",
    "age_range": "适用年龄",
    "cleaning_care": "清洁保养",
    "odor": "气味",
    "installation": "安装",
    "detachable": "拆卸/可拆",
    "color_options": "可选颜色",
    "variant_compare": "款式差异",
    "stock_shipping": "库存/发货",
    "return_pickup": "退货/售后取件",
    "invoice_policy": "发票政策",
    "price_protection": "价保政策",
    "promotion_policy": "优惠活动",
    "gift_policy": "赠品政策",
    "pinch_safety": "夹手/结构安全",
    "safety_small_parts": "小零件/电池安全",
    "aftersales_policy": "售后政策",
}

FACT_TYPE_LABELS.update({
    "gross_weight": "商品毛重/包装重量",
    "net_weight": "商品净重（商品本身、不含包装的重量，不是毛重或承重）",
    "accessory_availability": "配件售卖/补购",
    "accessory_usage": "配件用途/识别",
    "order_assistance": "下单/规格选择",
})


_QUERY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("safety_small_parts", ("误吞", "吞了", "吞到", "卡喉", "窒息", "电池盖", "电池仓", "小零件", "零件松", "宝宝受伤", "孩子受伤", "夹到手", "夹手", "被夹", "夹到", "夹到了", "夹住")),
    ("certification_report", ("甲醛", "检测报告", "检查报告", "质检报告", "检验报告", "合格证", "环保证书", "认证", "证书", "3C", "食品级")),
    ("variant_compare", ("基础款", "升级款", "升级版", "差什么", "区别", "差别", "差异", "对比", "哪个更好")),
    ("price_protection", ("价保", "保价", "价格保护", "买贵", "降价")),
    ("invoice_policy", ("发票", "开发票", "开票", "电子发票", "抬头", "税号")),
    ("promotion_policy", ("优惠", "活动", "券", "满减", "便宜", "折扣", "赠送", "送我")),
    ("gift_policy", ("赠品", "礼品", "没送", "少送", "漏发赠品")),
    ("stock_shipping", ("有货", "库存", "今天拍", "今天发", "什么时候发", "能发吗", "上发", "发货")),
    ("cleaning_care", ("清洁", "清理", "脏了", "水洗", "洗吗", "怎么洗", "擦洗", "可以洗", "酒精擦")),
    ("moisture_resistance", ("防潮", "受潮", "发霉", "霉变")),
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
    ("load_capacity", ("承重", "能放多重", "放多重", "结实", "稳不稳", "会不会倒", "放多少本", "能放多少本", "多少本", "放几本", "能放多少", "装多少", "能装多少", "放多少", "放很多", "压弯", "会不会压弯")),
    ("dimensions", ("尺寸", "多大", "多高", "多宽", "多长", "多厚", "厚度", "高度", "长度", "宽度", "占地")),
    ("detachable", ("可拆", "可拆卸", "拆卸", "拆开", "拆下来", "能拆", "拆装")),
    ("installation", ("安装", "怎么装", "装不上", "螺丝", "配件", "说明书", "安装视频", "教程", "组装", "拼接", "打孔", "需要打孔", "免打孔", "租房")),
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
    ("detachable", ("可拆", "可拆卸", "拆卸", "拆开", "拆下来", "能拆", "拆装")),
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
    "material_safety": "material_safety",
    "installation": "installation",
    "aftersales": "aftersales_policy",
}


# Aftersales补发/少件 markers indicate a post-purchase problem (missing/damaged
# parts, reissue, refund). These must win over the generic installation
# 螺丝/配件 keywords: "少了一个螺丝，能补发不？" is an aftersales reissue request,
# not an installation-guide question. Explicit installation verbs or safety
# markers (夹手/误吞/小零件/电池) still take precedence so we do not mask real
# installation or safety questions.
_AFTERSALES_STRONG_MARKERS = (
    "补发", "漏发", "发错", "发漏", "退货", "退款", "换货", "破损",
    "坏了", "缺件", "少了一个", "少送", "少发",
)
_INSTALLATION_EXPLICIT_MARKERS = (
    "安装", "组装", "怎么装", "装不上", "安装视频", "教程", "拼接", "打孔",
)
_SAFETY_OVERRIDE_BLOCKERS = (
    "防夹", "夹手", "夹到", "被夹", "夹住", "误吞", "吞了", "卡喉",
    "窒息", "电池", "小零件", "安全隐患",
)
_PROMOTION_STRONG_MARKERS = (
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
_AFTERSALES_PROMOTION_BOUNDARY_MARKERS = (
    "退货",
    "退款",
    "换货",
    "补发",
    "少件",
    "缺件",
    "漏发",
    "发错",
    "不一致",
    "不对",
    "破损",
    "投诉",
    "赔偿",
)
_RETURN_PICKUP_MARKERS = (
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


_UNICODE_QUERY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("pinch_safety", ("\u9632\u5939", "\u5939\u624b", "\u5939\u5230", "\u88ab\u5939", "\u5939\u4f4f", "\u5b89\u5168\u9690\u60a3")),
    ("safety_small_parts", ("\u5c0f\u96f6\u4ef6", "\u8bef\u541e", "\u541e\u4e86", "\u5361\u5589", "\u7a92\u606f", "\u7535\u6c60", "\u7535\u6c60\u4ed3", "\u7535\u6c60\u76d6")),
    ("certification_report", ("\u7532\u919b", "\u68c0\u6d4b\u62a5\u544a", "\u8d28\u68c0", "\u8ba4\u8bc1", "\u5408\u683c\u8bc1", "\u73af\u4fdd")),
    ("variant_compare", ("\u533a\u522b", "\u5dee\u522b", "\u5dee\u5f02", "\u5bf9\u6bd4", "\u54ea\u4e2a\u66f4\u597d", "\u54ea\u6b3e", "\u54ea\u6b3e\u66f4", "\u6570\u91cf\u66f4\u591a", "\u627f\u653e")),
    ("price_protection", ("\u4ef7\u4fdd", "\u4fdd\u4ef7", "\u964d\u4ef7")),
    ("invoice_policy", ("\u53d1\u7968", "\u5f00\u7968", "\u62ac\u5934", "\u7a0e\u53f7")),
    ("promotion_policy", (
        "\u4f18\u60e0",
        "\u6d3b\u52a8",
        "\u6ee1\u51cf",
        "\u6298\u6263",
        "\u4f18\u60e0\u5238",
        "\u798f\u5229",
        "\u4fbf\u5b9c\u70b9",
        "\u5c11\u70b9",
        "\u591a\u4e70",
        "\u4e70\u4e24\u4e2a",
        "\u6652\u56fe",
        "\u8fd4\u73b0",
    )),
    ("gift_policy", ("\u8d60\u54c1", "\u793c\u54c1", "\u6ca1\u9001", "\u5c11\u9001")),
    ("return_pickup", (
        "\u4e0a\u95e8\u53d6\u4ef6",
        "\u9000\u8d27\u53d6\u4ef6",
        "\u5feb\u9012\u53d6\u4ef6",
        "\u9884\u7ea6\u53d6\u4ef6",
        "\u53d6\u4ef6\u7801",
        "\u53d6\u4ef6\u5458",
        "\u53d6\u4ef6\u5b89\u6392",
        "\u4e0a\u95e8\u63fd\u6536",
        "\u5feb\u9012\u63fd\u6536",
        "\u63fd\u6536",
    )),
    ("stock_shipping", (
        "\u6709\u8d27",
        "\u5e93\u5b58",
        "\u53d1\u8d27",
        "\u73b0\u8d27",
        "\u7269\u6d41",
        "\u5feb\u9012",
        "\u7b7e\u6536",
        "\u6ca1\u6536\u5230",
        "\u672a\u6536\u5230",
        "\u5230\u54ea\u4e86",
        "\u51e0\u5929\u5230",
        "\u591a\u4e45\u5230",
        "\u8fd0\u5355\u53f7",
        "\u9001\u8d27\u4e0a\u95e8",
    )),
    ("order_assistance", (
        "\u600e\u4e48\u4e0b\u5355",
        "\u600e\u6837\u4e0b\u5355",
        "\u600e\u4e48\u4e70",
        "\u62cd\u54ea\u4e2a",
        "\u9009\u54ea\u4e2a",
        "\u53d1\u94fe\u63a5",
        "\u94fe\u63a5\u53d1\u6211",
        "\u4e0b\u5355\u94fe\u63a5",
        "\u89c4\u683c\u600e\u4e48\u9009",
        "\u6539\u5730\u5740",
        "\u6539\u4e00\u4e0b\u5730\u5740",
        "\u4fee\u6539\u5730\u5740",
        "\u6362\u5730\u5740",
        "\u6539\u6536\u8d27\u5730\u5740",
        "\u5730\u5740\u6ca1\u6539",
        "\u5730\u5740\u9519",
        "\u4e0b\u5355\u7684\u5730\u5740\u9519",
        "\u53d1\u5230\u8fd9\u4e2a\u5730\u5740",
        "\u53d1\u8fd9\u4e2a\u5730\u5740",
        "\u65b0\u5730\u5740",
    )),
    ("cleaning_care", ("\u6e05\u6d01", "\u6e05\u7406", "\u6c34\u6d17", "\u600e\u4e48\u6d17", "\u4fdd\u517b")),
    ("odor", ("\u6c14\u5473", "\u5473\u9053", "\u6709\u5473", "\u65e0\u5473", "\u65e0\u5f02\u5473", "\u5f02\u5473", "\u523a\u9f3b", "\u6563\u5473")),
    ("age_range", ("\u9002\u5408\u591a\u5927", "\u9002\u5408\u51e0\u5c81", "\u591a\u5927\u5b9d\u5b9d", "\u5b9d\u5b9d\u591a\u5927", "\u5b9d\u5b9d\u80fd\u4e0d\u80fd\u7528", "\u5c0f\u5b69\u80fd\u4e0d\u80fd\u7528", "\u513f\u7ae5\u9002\u7528", "\u5468\u5c81", "\u4e24\u5c81", "\u6708\u9f84", "\u5e74\u9f84")),
    ("stability", ("\u4f1a\u4e0d\u4f1a\u5012", "\u9632\u503e\u5012", "\u503e\u5012", "\u5012\u584c", "\u7a33\u4e0d\u7a33", "\u7a33\u56fa", "\u7a33\u5b9a")),
    ("space_fit", (
        "\u653e\u5f97\u4e0b",
        "\u653e\u7684\u4e0b",
        "\u6446\u5f97\u4e0b",
        "\u6446\u7684\u4e0b",
        "\u7a7a\u95f4\u591f",
        "\u591f\u4e0d\u591f\u653e",
        "\u51e0\u5e73\u65b9",
        "\u5e73\u65b9",
        "\u5360\u7a7a\u95f4",
        "\u5360\u5730\u65b9",
        "\u9884\u7559",
        "\u4f4d\u7f6e\u591f",
    )),
    ("placement_scene", (
        "\u5367\u5ba4",
        "\u5ba2\u5385",
        "\u4e66\u623f",
        "\u53a8\u623f",
        "\u9633\u53f0",
        "\u536b\u751f\u95f4",
        "\u53ef\u4ee5\u7528\u5417",
        "\u53ef\u4ee5\u653e\u5417",
        "\u80fd\u653e\u5417",
        "\u9002\u5408\u653e",
    )),
    ("load_capacity", ("\u627f\u91cd", "\u80fd\u653e\u591a\u91cd", "\u653e\u591a\u91cd", "\u653e\u51e0\u65a4", "\u653e\u591a\u5c11\u65a4", "\u7ed3\u5b9e", "\u80fd\u653e\u591a\u5c11", "\u538b\u5f2f", "\u538b\u6241", "\u538b\u584c", "\u538b\u574f")),
    ("accessory_usage", ("\u4f5c\u7528\u662f\u5565", "\u4ec0\u4e48\u4f5c\u7528", "\u6709\u4ec0\u4e48\u7528", "\u5e72\u5565\u7528", "\u5e72\u561b\u7528", "\u7528\u6765\u5e72\u5565", "\u7528\u9014")),
    ("dimensions", ("\u5c3a\u5bf8", "\u591a\u5927", "\u591a\u9ad8", "\u591a\u5bbd", "\u591a\u957f", "\u9ad8\u5ea6", "\u5bbd\u5ea6", "\u957f\u5ea6", "\u5360\u5730", "\u89c4\u683c")),
    ("detachable", ("\u53ef\u62c6", "\u62c6\u5378", "\u62c6\u5f00", "\u62c6\u4e0b\u6765", "\u80fd\u62c6", "\u62c6\u88c5")),
    ("installation", ("\u5b89\u88c5", "\u600e\u4e48\u88c5", "\u88c5\u4e0d\u4e0a", "\u87ba\u4e1d", "\u914d\u4ef6", "\u8bf4\u660e\u4e66", "\u5b89\u88c5\u89c6\u9891", "\u6559\u7a0b", "\u7ec4\u88c5", "\u6253\u5b54", "\u79df\u623f", "\u8d34\u7eb8", "\u80cc\u80f6", "\u8d34\u54ea", "\u8d34\u54ea\u91cc")),
    ("material", ("\u6750\u8d28", "\u6750\u6599", "\u4ec0\u4e48\u6599", "\u4ec0\u4e48\u5851\u6599", "\u5851\u6599", "\u7528\u6599", "\u677f\u6750", "\u5b9e\u6728", "\u5b89\u5168\u5417", "\u53d7\u6f6e", "\u9632\u6f6e", "\u751f\u9508")),
    ("aftersales_policy", (
        "\u9000\u8d27",
        "\u9000\u6b3e",
        "\u6362\u8d27",
        "\u8865\u53d1",
        "\u552e\u540e",
        "\u7834\u635f",
        "\u574f\u4e86",
        "\u5c11\u4ef6",
        "\u53d1\u9519",
        "\u6253\u6b3e",
        "\u652f\u4ed8\u5b9d\u6253\u6b3e",
        "\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e",
        "\u5c0f\u989d\u6253\u6b3e",
        "\u5230\u8d26",
        "\u6536\u6b3e\u8d26\u53f7",
        "\u6536\u6b3e\u4eba\u59d3\u540d",
        "\u8d54\u4ed8",
        "\u8865\u507f\u6b3e",
        "\u6ed1\u7259",
        "\u87ba\u5e3d\u6ed1\u7259",
    )),
]


_GROSS_WEIGHT_TERMS = (
    "毛重",
    "包装重量",
    "商品重量",
    "重量多少",
    "多重",
    "几斤",
    "几公斤",
    "多少斤",
    "多少公斤",
    "package_weight",
    "gross_weight",
    "gross_weight_kg",
    "product weight",
)
_LOAD_CAPACITY_BLOCKERS_FOR_WEIGHT = (
    "承重",
    "载重",
    "能放多重",
    "放多重",
    "放几斤",
    "放多少斤",
    "压弯",
    "压扁",
    "压塌",
    "压坏",
    "放多少",
)
_LOAD_CAPACITY_UNIT_TERMS = ("公斤", "kg", "KG", "斤")
_LOAD_CAPACITY_CONTEXT_TERMS = (
    "承重",
    "载重",
    "能放",
    "放书",
    "压弯",
    "压扁",
    "压塌",
    "压坏",
    "架子",
    "隔板",
    "层板",
    "顶板",
    "底板",
)
_ACCESSORY_OBJECT_TERMS = ("配件", "小篮子", "篮子", "零件", "部件", "防倒器", "双面贴")
_ACCESSORY_AVAILABILITY_TERMS = (
    "有卖",
    "卖吗",
    "卖不卖",
    "单独买",
    "单独购买",
    "单卖",
    "补买",
    "补购",
    "可售",
    "售卖",
    "另购",
    "有没有卖",
    "能不能买",
    "能买",
)
_ACCESSORY_USAGE_BLOCKERS = (
    "怎么装",
    "安装",
    "说明书",
    "安装视频",
    "干啥用",
    "什么用",
    "用法",
    "装哪里",
)
_STRUCTURE_OBJECT_TERMS = ("一边", "侧边", "侧板", "护栏", "围栏", "门", "挡板", "板子", "抽屉", "靠背", "背板", "隔板", "层板", "顶板", "底板", "孔位", "螺丝孔", "预留孔")
_STRUCTURE_ACTION_TERMS = ("放下来", "放下", "翻下来", "翻起", "打开", "收起", "折叠", "调节", "拆下来", "拆卸", "固定", "活动", "能动", "加装", "加个", "再加", "补", "补配", "打孔", "对上", "对齐", "匹配")
_STRUCTURE_CONFIRM_TERMS = ("不是可以", "可以吗", "能不能", "是不是", "怎么", "有吗", "吗", "呢")
_STRUCTURE_SCENE_BLOCKERS = ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间")
_STRUCTURE_SPACE_BLOCKERS = ("空间", "空间小", "放不下", "尺寸", "长宽高", "几平方", "平方", "占地方", "预留")
_MATERIAL_CONTEXT_TERMS = ("材质", "材料", "用料", "什么料", "板材")
_MATERIAL_SAFETY_TERMS = ("安全", "有害", "有毒", "无毒", "甲醛")
_BITE_OR_TOXICITY_TERMS = ("误入口", "误食", "吞咽", "吞了", "啃咬", "咬到", "咬了一下")


def _classify_product_fact_boundary(msg: str) -> dict[str, Any] | None:
    text = str(msg or "").lower()
    if any(term in msg for term in _BITE_OR_TOXICITY_TERMS):
        matched = [term for term in _BITE_OR_TOXICITY_TERMS if term in msg]
        return {
            "query_fact_type": "bite_or_toxicity",
            "query_fact_type_label": FACT_TYPE_LABELS.get("bite_or_toxicity", "bite_or_toxicity"),
            "confidence": 0.88,
            "matched_terms": matched[:5],
            "source": "product_fact_boundary_rule",
        }
    if (
        any(term in msg for term in _MATERIAL_CONTEXT_TERMS)
        and any(term in msg for term in _MATERIAL_SAFETY_TERMS)
    ):
        matched = [term for term in (*_MATERIAL_CONTEXT_TERMS, *_MATERIAL_SAFETY_TERMS) if term in msg]
        return {
            "query_fact_type": "material_safety",
            "query_fact_type_label": FACT_TYPE_LABELS.get("material_safety", "material_safety"),
            "confidence": 0.88,
            "matched_terms": matched[:5],
            "source": "product_fact_boundary_rule",
        }
    if (
        any(term.lower() in text for term in _GROSS_WEIGHT_TERMS)
        and not any(term in msg for term in _LOAD_CAPACITY_BLOCKERS_FOR_WEIGHT)
    ):
        matched = [term for term in _GROSS_WEIGHT_TERMS if term.lower() in text]
        return {
            "query_fact_type": "gross_weight",
            "query_fact_type_label": FACT_TYPE_LABELS.get("gross_weight", "gross_weight"),
            "confidence": 0.88,
            "matched_terms": matched[:5],
            "source": "product_fact_boundary_rule",
        }
    if (
        any(term in msg for term in _LOAD_CAPACITY_UNIT_TERMS)
        and any(term in msg for term in _LOAD_CAPACITY_CONTEXT_TERMS)
    ):
        matched = [term for term in (*_LOAD_CAPACITY_UNIT_TERMS, *_LOAD_CAPACITY_CONTEXT_TERMS) if term in msg]
        return {
            "query_fact_type": "load_capacity",
            "query_fact_type_label": FACT_TYPE_LABELS.get("load_capacity", "load_capacity"),
            "confidence": 0.88,
            "matched_terms": matched[:5],
            "source": "product_fact_boundary_rule",
        }
    if (
        any(term in msg for term in _ACCESSORY_OBJECT_TERMS)
        and any(term in msg for term in _ACCESSORY_AVAILABILITY_TERMS)
        and not any(term in msg for term in _ACCESSORY_USAGE_BLOCKERS)
    ):
        matched = [term for term in (*_ACCESSORY_OBJECT_TERMS, *_ACCESSORY_AVAILABILITY_TERMS) if term in msg]
        return {
            "query_fact_type": "accessory_availability",
            "query_fact_type_label": FACT_TYPE_LABELS.get("accessory_availability", "accessory_availability"),
            "confidence": 0.88,
            "matched_terms": matched[:5],
            "source": "product_fact_boundary_rule",
        }
    if _is_structure_function_query(msg):
        matched = [term for term in (*_STRUCTURE_OBJECT_TERMS, *_STRUCTURE_ACTION_TERMS, *_STRUCTURE_CONFIRM_TERMS) if term in msg]
        return {
            "query_fact_type": "structure_function",
            "query_fact_type_label": FACT_TYPE_LABELS.get("structure_function", "structure_function"),
            "confidence": 0.88,
            "matched_terms": matched[:5],
            "source": "product_fact_boundary_rule",
        }
    return None


def _is_structure_function_query(msg: str) -> bool:
    value = str(msg or "")
    if any(term in value for term in _STRUCTURE_SCENE_BLOCKERS):
        return False
    if any(term in value for term in _STRUCTURE_SPACE_BLOCKERS if term != "预留" or "预留孔" not in value):
        return False
    has_object = any(term in value for term in _STRUCTURE_OBJECT_TERMS)
    has_action = any(term in value for term in _STRUCTURE_ACTION_TERMS)
    has_confirm = any(term in value for term in _STRUCTURE_CONFIRM_TERMS)
    return has_object and has_action and has_confirm


def classify_query_fact_type(message: str, intent: str = "") -> dict[str, Any]:
    """Classify the business fact field a customer is asking about."""
    msg = message or ""
    product_fact_boundary = _classify_product_fact_boundary(msg)
    if product_fact_boundary:
        return product_fact_boundary
    promotion_hits = [kw for kw in _PROMOTION_STRONG_MARKERS if kw in msg]
    aftersales_promotion_boundary_hits = [kw for kw in _AFTERSALES_PROMOTION_BOUNDARY_MARKERS if kw in msg]
    if promotion_hits and aftersales_promotion_boundary_hits:
        return {
            "query_fact_type": "aftersales_policy",
            "query_fact_type_label": FACT_TYPE_LABELS.get("aftersales_policy", "aftersales_policy"),
            "confidence": 0.86,
            "matched_terms": aftersales_promotion_boundary_hits[:5],
            "secondary_fact_types": ["promotion_policy"],
            "source": "unicode_rule",
        }
    if promotion_hits:
        return {
            "query_fact_type": "promotion_policy",
            "query_fact_type_label": FACT_TYPE_LABELS.get("promotion_policy", "promotion_policy"),
            "confidence": 0.86 if len(promotion_hits) > 1 else 0.8,
            "matched_terms": promotion_hits[:5],
            "secondary_fact_types": [],
            "source": "unicode_rule",
        }
    return_pickup_hits = [kw for kw in _RETURN_PICKUP_MARKERS if kw in msg]
    if return_pickup_hits:
        return {
            "query_fact_type": "return_pickup",
            "query_fact_type_label": FACT_TYPE_LABELS.get("return_pickup", "return_pickup"),
            "confidence": 0.88,
            "matched_terms": return_pickup_hits[:5],
            "secondary_fact_types": ["aftersales_policy"],
            "source": "unicode_rule",
        }
    # Aftersales补发/少件 wins over the generic installation 螺丝/配件 keyword
    # (e.g. "少了一个螺丝，能补发不？" → aftersales_policy). Explicit installation
    # verbs or safety markers still take precedence.
    aftersales_hits = [kw for kw in _AFTERSALES_STRONG_MARKERS if kw in msg]
    if (
        aftersales_hits
        and not any(kw in msg for kw in _INSTALLATION_EXPLICIT_MARKERS)
        and not any(kw in msg for kw in _SAFETY_OVERRIDE_BLOCKERS)
    ):
        return {
            "query_fact_type": "aftersales_policy",
            "query_fact_type_label": FACT_TYPE_LABELS.get("aftersales_policy", "aftersales_policy"),
            "confidence": 0.85,
            "matched_terms": aftersales_hits[:5],
            "source": "unicode_rule",
        }
    for fact_type, keywords in _UNICODE_QUERY_RULES:
        matched = [kw for kw in keywords if kw in msg]
        if matched:
            return {
                "query_fact_type": fact_type,
                "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
                "confidence": 0.9 if len(matched) > 1 else 0.78,
                "matched_terms": matched[:5],
                "secondary_fact_types": _secondary_fact_types(msg, fact_type),
                "source": "unicode_rule",
            }
    for fact_type, keywords in _QUERY_RULES:
        matched = [kw for kw in keywords if kw in msg]
        if matched:
            return {
                "query_fact_type": fact_type,
                "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
                "confidence": 0.9 if len(matched) > 1 else 0.78,
                "matched_terms": matched[:5],
                "secondary_fact_types": _secondary_fact_types(msg, fact_type),
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


def _secondary_fact_types(message: str, primary: str) -> list[str]:
    """Expose independently requested fact domains without selecting evidence."""
    found: list[str] = []
    for fact_type, keywords in [*_UNICODE_QUERY_RULES, *_QUERY_RULES]:
        if (
            fact_type != primary
            and fact_type != "material"
            and any(keyword in message for keyword in keywords)
        ):
            found.append(fact_type)
    return sorted(set(found))


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
    boundary_from_title = _classify_product_fact_boundary(title_text)
    if boundary_from_title:
        return str(boundary_from_title.get("query_fact_type") or "")
    if any(kw in title_text for kw in ("承重", "载重", "能放", "放多重", "多少kg", "多少斤", "结实", "稳固")):
        return "load_capacity"
    if any(kw in title_text for kw in ("尺寸", "高度", "宽度", "长度", "多高", "多宽", "多长", "规格")):
        return "dimensions"
    if any(kw in title_text for kw in ("适合多大", "适合几岁", "多大宝宝", "月龄", "年龄")):
        return "age_range"
    if any(kw in title_text for kw in ("清洁", "清理", "水洗", "怎么洗", "保养")):
        return "cleaning_care"
    if any(kw in title_text for kw in ("安装", "怎么装", "组装", "装不上", "说明书", "安装视频", "教程")):
        return "installation"
    if any(kw in title_text for kw in ("材质", "材料", "什么料", "用料", "防潮", "受潮", "生锈")):
        return "material"
    for fact_type, keywords in _UNICODE_QUERY_RULES:
        if any(kw in title_text for kw in keywords):
            return fact_type

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
    boundary_from_text = _classify_product_fact_boundary(haystack)
    if boundary_from_text:
        return str(boundary_from_text.get("query_fact_type") or "")
    for fact_type, keywords in _UNICODE_QUERY_RULES:
        if any(kw in haystack for kw in keywords):
            return fact_type
    for fact_type, keywords in _EVIDENCE_RULES:
        if any(kw in haystack for kw in keywords):
            return fact_type
    return ""


def fact_type_matches(query_fact_type: str, evidence_fact_type: str) -> bool:
    """Return whether evidence can directly answer a query fact type.

    严格匹配：问题需要什么事实类型，证据就必须是该事实类型。
    不允许用清洁保养证据回答材质问题，也不允许用承重证据回答安装问题。
    """
    if not query_fact_type:
        return False
    if not evidence_fact_type:
        return False
    if query_fact_type == "product_overview":
        canonical_evidence_type = canonical_material_composition_claim_type(
            evidence_fact_type
        )
        return canonical_evidence_type in {"material_composition", "dimensions"}
    if query_fact_type == evidence_fact_type:
        return True
    if (
        canonical_material_composition_claim_type(query_fact_type)
        == canonical_material_composition_claim_type(evidence_fact_type)
        == "material_composition"
    ):
        return True
    compatible = {
        "space_fit": {"dimensions"},
    }
    return evidence_fact_type in compatible.get(query_fact_type, set())


def is_strict_fact_type(query_fact_type: str) -> bool:
    """Strict types must not fall back to neighboring product facts."""
    return query_fact_type in {
        "certification_report",
        "age_range",
        "pinch_safety",
        "safety_small_parts",
        "stability",
        "dimensions",
        "space_fit",
        "placement_scene",
        "structure_function",
        "detachable",
        "variant_compare",
        "invoice_policy",
        "price_protection",
        "gross_weight",
        "net_weight",
        "product_overview",
        "accessory_availability",
    }
