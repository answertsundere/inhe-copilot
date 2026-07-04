"""Generic service rules for grounded fallback replies.

These rules are not product facts. They are customer-safe service boundaries
used only after product-scoped facts/media/activity evidence has had priority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any


FORBIDDEN_CUSTOMER_CLAIMS = (
    "0甲醛",
    "零甲醛",
    "绝对安全",
    "完全无味",
    "绝对无味",
    "百分百无风险",
    "100%无风险",
    "百分百安全",
    "100%安全",
    "宝宝可以直接用",
)


DEFAULT_GENERIC_SERVICE_RULES: list[dict[str, Any]] = [
    {
        "rule_key": "odor_new_product_ventilation_v1",
        "title": "新品气味保守说明",
        "intent": "odor_question",
        "fact_type": "odor",
        "scenario": "product_question",
        "query_keywords": ["味道", "气味", "味儿", "异味", "刺鼻", "散味", "通风"],
        "content": (
            "新品拆开包装后可能会有轻微包装、仓储或运输密封带来的味道。"
            "建议拆开外包装并打开柜门、抽屉或收纳格，在通风处放置。"
            "如明显刺鼻或通风后仍很明显，应先暂停给宝宝使用并联系售后核实。"
        ),
        "reply_template": (
            "亲～您担心{product_display}的气味问题很正常，宝宝用品确实要谨慎一些。\n"
            "如果是刚拆包装的新商品，可能会有一点包装、仓储或运输密封带来的味道。"
            "建议先把外包装拆开，柜门、抽屉或收纳格尽量打开，放在通风处晾一晾。\n"
            "如果味道明显刺鼻，或者通风后仍然很明显，建议先暂停给宝宝使用，"
            "把实际情况拍照或视频发来，我这边继续帮您处理。"
        ),
        "forbidden_claims": ["0甲醛", "绝对安全", "完全无味", "宝宝可以直接用"],
        "source_confidence": 0.78,
    },
    {
        "rule_key": "cleaning_care_conservative_v1",
        "title": "清洁保养保守说明",
        "intent": "cleaning_care",
        "fact_type": "cleaning_care",
        "scenario": "product_question",
        "query_keywords": ["清洗", "水洗", "机洗", "擦洗", "脏了", "清洁", "保养"],
        "content": (
            "未确认具体材质和结构前，不应承诺整体水洗、机洗或长时间浸泡。"
            "通常可先用干布或微湿软布擦拭，再放通风处晾干。"
        ),
        "reply_template": (
            "亲～{product_display}怎么清洁这个问题我先按保守方式跟您说。\n"
            "在没有确认具体材质和结构前，不建议直接整体水洗、机洗或长时间浸泡。"
            "平时可以先用干布或微湿软布轻轻擦拭，有污渍的位置擦掉后放在通风处晾干。\n"
            "如果页面或说明书有单独标注清洗方式，再按对应说明处理会更稳妥。"
        ),
        "forbidden_claims": ["可以机洗", "可以整体水洗"],
        "source_confidence": 0.76,
    },
    {
        "rule_key": "space_fit_measure_before_buy_v1",
        "title": "\u7a7a\u95f4\u9002\u914d\u6d4b\u91cf\u5efa\u8bae",
        "intent": "product_question",
        "fact_type": "space_fit",
        "scenario": "space_fit",
        "query_keywords": [
            "\u653e\u5f97\u4e0b",
            "\u653e\u7684\u4e0b",
            "\u7a7a\u95f4",
            "\u51e0\u5e73\u65b9",
            "\u5e73\u65b9",
            "\u5360\u5730",
            "\u9884\u7559",
        ],
        "content": (
            "\u5ba2\u6237\u95ee\u623f\u95f4\u6216\u9884\u7559\u4f4d\u7f6e\u80fd\u5426\u653e\u4e0b\u65f6\uff0c"
            "\u4e0d\u80fd\u7528\u627f\u91cd\u3001\u6750\u8d28\u6216\u9632\u6f6e\u4fe1\u606f\u4ee3\u66ff\u56de\u7b54\u3002"
            "\u5e94\u8be5\u5f15\u5bfc\u5ba2\u6237\u6838\u5bf9\u9884\u7559\u4f4d\u7f6e\u7684\u5bbd\u3001\u6df1\u3001\u9ad8\u548c\u901a\u9053\u7a7a\u95f4\uff0c"
            "\u6709\u5c3a\u5bf8\u56fe\u65f6\u4f18\u5148\u53d1\u5c3a\u5bf8\u56fe\u3002"
        ),
        "reply_template": (
            "\u4eb2\uff5e{product_display}\u80fd\u4e0d\u80fd\u653e\u4e0b\uff0c\u4e3b\u8981\u8981\u770b\u60a8\u5bb6\u9884\u7559\u4f4d\u7f6e\u7684\u5bbd\u3001\u6df1\u3001\u9ad8\uff0c"
            "\u4ee5\u53ca\u653e\u597d\u540e\u65c1\u8fb9\u8d70\u52a8\u548c\u62ff\u53d6\u7269\u54c1\u7684\u7a7a\u95f4\u3002\n"
            "\u5efa\u8bae\u60a8\u5148\u91cf\u4e00\u4e0b\u51c6\u5907\u6446\u653e\u7684\u4f4d\u7f6e\uff1a\u5bbd\u5ea6\u3001\u8fdb\u6df1\u548c\u9ad8\u5ea6\u90fd\u8981\u7559\u51fa\u4e00\u70b9\u4f59\u91cf\uff0c"
            "\u8fd9\u6837\u6446\u653e\u540e\u4f7f\u7528\u4f1a\u66f4\u987a\u624b\u3002\n"
            "\u5982\u679c\u60a8\u628a\u9884\u7559\u4f4d\u7f6e\u7684\u5927\u6982\u5c3a\u5bf8\u53d1\u6211\uff0c\u6211\u53ef\u4ee5\u5e2e\u60a8\u5bf9\u7167\u5c3a\u5bf8\u56fe\u770b\u4e00\u4e0b\u662f\u5426\u5408\u9002\u3002"
        ),
        "forbidden_claims": ["\u4e00\u5b9a\u653e\u5f97\u4e0b", "\u80af\u5b9a\u53ef\u4ee5\u653e"],
        "source_confidence": 0.76,
    },
    {
        "rule_key": "placement_scene_dry_area_v1",
        "title": "\u6446\u653e\u573a\u666f\u4fdd\u5b88\u5efa\u8bae",
        "intent": "product_question",
        "fact_type": "placement_scene",
        "scenario": "placement_scene",
        "query_keywords": [
            "\u5367\u5ba4",
            "\u5ba2\u5385",
            "\u4e66\u623f",
            "\u53a8\u623f",
            "\u9633\u53f0",
            "\u536b\u751f\u95f4",
            "\u53ef\u4ee5\u653e",
            "\u53ef\u4ee5\u7528",
        ],
        "content": (
            "\u5ba2\u6237\u95ee\u5367\u5ba4/\u5ba2\u5385/\u4e66\u623f\u7b49\u573a\u666f\u80fd\u5426\u6446\u653e\u65f6\uff0c"
            "\u5e94\u56de\u7b54\u573a\u666f\u9002\u7528\u548c\u6446\u653e\u6ce8\u610f\u4e8b\u9879\uff0c\u4e0d\u80fd\u8dd1\u5230\u627f\u91cd\u6216\u5355\u7eaf\u6750\u8d28\u4ecb\u7ecd\u3002"
        ),
        "reply_template": (
            "\u4eb2\uff5e{product_display}\u653e\u5728\u5367\u5ba4\u3001\u5ba2\u5385\u3001\u4e66\u623f\u8fd9\u7c7b\u65e5\u5e38\u6536\u7eb3\u533a\u57df\u4e00\u822c\u662f\u53ef\u4ee5\u53c2\u8003\u7684\u3002\n"
            "\u5efa\u8bae\u60a8\u6446\u5728\u76f8\u5bf9\u5e72\u71e5\u3001\u5e73\u6574\u7684\u4f4d\u7f6e\uff0c\u65c1\u8fb9\u7559\u51fa\u62ff\u653e\u548c\u8d70\u52a8\u7684\u7a7a\u95f4\uff0c"
            "\u4f7f\u7528\u8d77\u6765\u4f1a\u66f4\u65b9\u4fbf\u3002\n"
            "\u5982\u679c\u662f\u5f88\u6f6e\u6e7f\u7684\u536b\u751f\u95f4\u6216\u957f\u65f6\u95f4\u66b4\u6652\u7684\u4f4d\u7f6e\uff0c\u5c31\u4e0d\u5efa\u8bae\u957f\u671f\u653e\u7f6e\uff1b"
            "\u5982\u679c\u60a8\u5bb6\u7a7a\u95f4\u6bd4\u8f83\u5c0f\uff0c\u53ef\u4ee5\u628a\u9884\u7559\u5bbd\u6df1\u9ad8\u53d1\u6211\uff0c\u6211\u5e2e\u60a8\u5bf9\u7167\u4e00\u4e0b\u3002"
        ),
        "forbidden_claims": ["\u4efb\u4f55\u573a\u666f\u90fd\u53ef\u4ee5", "\u4e00\u5b9a\u653e\u5f97\u4e0b"],
        "source_confidence": 0.74,
    },
    {
        "rule_key": "media_supported_install_size_parts_v1",
        "title": "安装尺寸配件优先推荐素材",
        "intent": "product_question",
        "fact_type": "media_reference",
        "scenario": "media_supported_question",
        "query_keywords": ["安装", "视频", "教程", "尺寸", "规格", "配件", "零件", "清单", "图片", "图"],
        "content": (
            "安装、尺寸、配件核对类问题，如已匹配到对应商品素材，应优先建议客服发送已审核图片或视频。"
            "未匹配到素材时，只能说明需要按对应款式核对。"
        ),
        "reply_template": (
            "亲～{product_display}这个点如果需要看安装步骤、尺寸或配件位置，"
            "我可以帮您对照对应商品的图片/视频资料。"
            "如果当前款式没有匹配到可发送的资料，我会先按对应款式核对后再发您，避免发错。"
        ),
        "forbidden_claims": ["一定能装", "保证能装"],
        "source_confidence": 0.72,
    },
    {
        "rule_key": "material_safety_needs_verified_fact_v1",
        "title": "材质安全需以验证信息为准",
        "intent": "material_safety",
        "fact_type": "material",
        "scenario": "safety_boundary",
        "query_keywords": ["材质", "材料", "甲醛", "环保", "安全", "有毒", "食品级", "宝宝"],
        "content": (
            "材质、安全、检测、食品级等内容必须以商品页、检测资料或 SKU 对应资料为准。"
            "不能在无证据时给出绝对化安全结论、无甲醛结论、食品级结论或宝宝使用结论。"
        ),
        "reply_template": (
            "亲～家里有宝宝的话，关心{product_display}的材质和安全很正常。\n"
            "材质、检测和安全说明需要以对应商品页面、包装标识或已验证资料为准；"
            "如果当前没有看到明确说明，我不直接替您下结论。\n"
            "您可以把页面材质说明或实物标签发来，我帮您一起核对。"
        ),
        "forbidden_claims": ["0甲醛", "绝对安全", "食品级", "宝宝可以直接用"],
        "source_confidence": 0.8,
    },
]


DEFAULT_GENERIC_SERVICE_RULES.append({
    "rule_key": "after_sales_payment_timing_v1",
    "title": "\u552e\u540e\u6253\u6b3e\u65f6\u6548\u8bf4\u660e",
    "intent": "aftersales",
    "fact_type": "aftersales_policy",
    "scenario": "after_sales_payment",
    "query_keywords": [
        "\u552e\u540e\u6253\u6b3e",
        "\u6253\u6b3e",
        "\u652f\u4ed8\u5b9d\u6253\u6b3e",
        "\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e",
        "\u5c0f\u989d\u6253\u6b3e",
        "\u5230\u8d26",
        "\u591a\u4e45\u5230\u8d26",
        "\u51e0\u5929\u5230",
        "\u6536\u6b3e\u8d26\u53f7",
        "\u652f\u4ed8\u5b9d\u8d26\u53f7",
        "\u6536\u6b3e\u4eba\u59d3\u540d",
        "\u8865\u507f\u6b3e",
        "\u8d54\u4ed8",
        "\u9000\u6b3e\u5dee\u989d",
    ],
    "content": (
        "\u552e\u540e\u6b3e\u9879\u5904\u7406\u9700\u533a\u5206\u652f\u4ed8\u5b9d\u6253\u6b3e\u548c\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e\u3002"
        "\u652f\u4ed8\u5b9d\u6253\u6b3e\u65f6\u6548\u4e00\u822c\u4e3a 7 \u5929\u5de6\u53f3\uff0c\u9700\u5ba2\u6237\u63d0\u4f9b\u6536\u6b3e\u652f\u4ed8\u5b9d\u8d26\u53f7\u548c\u6536\u6b3e\u4eba\u59d3\u540d\u3002"
        "\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e\u4e00\u822c\u5728 72 \u5c0f\u65f6\u5de6\u53f3\u3002"
        "\u5ba2\u670d\u53ea\u80fd\u8bf4\u660e\u53c2\u8003\u65f6\u6548\u548c\u6240\u9700\u4fe1\u606f\uff0c\u4e0d\u80fd\u627f\u8bfa\u7acb\u5373\u5230\u8d26\u6216\u7edd\u5bf9\u5230\u8d26\u65f6\u95f4\u3002"
    ),
    "reply_template": (
        "\u4eb2\uff5e\u552e\u540e\u6253\u6b3e\u8fd9\u8fb9\u7ed9\u60a8\u8bf4\u660e\u4e00\u4e0b\uff1a"
        "\u5982\u679c\u662f\u652f\u4ed8\u5b9d\u6253\u6b3e\uff0c\u65f6\u6548\u4e00\u822c\u662f 7 \u5929\u5de6\u53f3\uff0c"
        "\u9700\u8981\u60a8\u63d0\u4f9b\u6536\u6b3e\u652f\u4ed8\u5b9d\u8d26\u53f7\u548c\u6536\u6b3e\u4eba\u59d3\u540d\uff1b"
        "\u5982\u679c\u662f\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e\uff0c\u4e00\u822c\u5728 72 \u5c0f\u65f6\u5de6\u53f3\u5230\u8d26\u3002"
        "\u5177\u4f53\u5230\u8d26\u65f6\u95f4\u4e5f\u4f1a\u53d7\u5e73\u53f0\u548c\u8d22\u52a1\u5904\u7406\u8fdb\u5ea6\u5f71\u54cd\uff0c\u6211\u8fd9\u8fb9\u4f1a\u5e2e\u60a8\u8ddf\u8fdb\u3002"
    ),
    "forbidden_claims": [
        "\u9a6c\u4e0a\u5230\u8d26",
        "\u7acb\u5373\u5230\u8d26",
        "\u4e00\u5b9a\u5f53\u5929\u5230\u8d26",
        "\u4e00\u5b9a 72 \u5c0f\u65f6\u5185\u5230\u8d26",
        "\u672a\u6536\u96c6\u652f\u4ed8\u5b9d\u8d26\u53f7\u548c\u59d3\u540d\u5c31\u8bf4\u53ef\u4ee5\u6253\u6b3e",
    ],
    "required_guardrails": [
        "\u4ec5\u8bf4\u660e\u53c2\u8003\u65f6\u6548\uff0c\u4e0d\u627f\u8bfa\u7edd\u5bf9\u5230\u8d26\u65f6\u95f4",
        "\u652f\u4ed8\u5b9d\u6253\u6b3e\u9700\u5148\u6536\u96c6\u6536\u6b3e\u8d26\u53f7\u548c\u59d3\u540d",
    ],
    "source_confidence": 0.82,
    "risk_level": "medium",
    "priority": 40,
})

DEFAULT_GENERIC_SERVICE_RULES.extend([
    {
        "rule_key": "logistics_order_status_check_v1",
        "title": "物流/发货状态核对",
        "intent": "logistics",
        "fact_type": "stock_shipping",
        "scenario": "logistics_status_check",
        "query_keywords": [
            "发货",
            "什么时候发",
            "几天到",
            "多久到",
            "物流",
            "快递",
            "签收",
            "没收到",
            "到哪了",
            "运单号",
        ],
        "content": (
            "物流、发货、签收未收到类问题需要按当前订单物流信息核对。"
            "客服可以确认客户想查发货、运输进度还是签收未收到，并按订单/平台物流信息回复。"
            "不能承诺具体发货时效、到货时间或物流结果。"
        ),
        "reply_template": (
            "亲，我帮您按当前订单物流信息核对一下。"
            "您是想确认发货、到哪了，还是签收后没收到？"
            "我看准后给您回复，避免物流节点看错。"
        ),
        "forbidden_claims": ["今天一定发", "明天一定到", "马上到", "肯定已送达"],
        "required_guardrails": ["按订单物流核对", "不承诺绝对到货/发货时间"],
        "source_confidence": 0.78,
        "risk_level": "medium",
        "priority": 50,
    },
    {
        "rule_key": "aftersales_issue_collect_and_review_v1",
        "title": "售后问题信息收集与核实",
        "intent": "aftersales",
        "fact_type": "aftersales_policy",
        "scenario": "aftersales_issue_review",
        "query_keywords": [
            "售后",
            "破损",
            "坏了",
            "少件",
            "漏发",
            "补发",
            "退货",
            "退款",
            "换货",
            "发错",
            "不一致",
            "不对",
        ],
        "content": (
            "售后问题应先收集订单信息、问题位置照片、配件/包装情况，再按售后流程核实处理方案。"
            "不能在未核实前直接承诺退款、补发、换货或赔付。"
        ),
        "reply_template": (
            "亲，您反馈的情况我先帮您登记。"
            "麻烦发一下问题位置照片、配件整体和订单信息，我这边按售后流程核对处理方案。"
            "确认清楚后再给您准确处理，避免直接判断错。"
        ),
        "forbidden_claims": ["直接退款", "马上补发", "一定赔付", "肯定给您换"],
        "required_guardrails": ["先收集照片和订单信息", "核实后给处理方案"],
        "source_confidence": 0.78,
        "risk_level": "medium",
        "priority": 50,
    },
    {
        "rule_key": "promotion_current_activity_check_v1",
        "title": "优惠/活动核对",
        "intent": "promotion",
        "fact_type": "promotion_policy",
        "scenario": "promotion_activity_check",
        "query_keywords": [
            "优惠",
            "活动",
            "优惠券",
            "满减",
            "折扣",
            "福利",
            "便宜点",
            "多买",
            "买两个",
            "晒图",
            "返现",
            "赠品",
        ],
        "content": (
            "优惠、活动、议价和晒图返现类问题需要按当前商品页面、活动规则、优惠券和下单页展示核对。"
            "不能承诺额外优惠、返现金额、赠品或活动一定可叠加。"
        ),
        "reply_template": (
            "亲，我帮您看一下当前这款可用的活动和优惠。"
            "页面显示的券、满减和活动一般以下单页为准；页面没显示的，我再帮您核对一下。"
            "我确认后给您准确口径。"
        ),
        "forbidden_claims": ["一定有优惠", "肯定能便宜", "一定返现", "活动一定叠加"],
        "required_guardrails": ["以下单页/活动规则为准", "不承诺额外优惠"],
        "source_confidence": 0.78,
        "risk_level": "medium",
        "priority": 50,
    },
    {
        "rule_key": "purchase_assistance_spec_check_v1",
        "title": "下单/规格选择协助",
        "intent": "order_assistance",
        "fact_type": "order_assistance",
        "scenario": "purchase_assistance",
        "query_keywords": [
            "链接",
            "怎么买",
            "怎么下单",
            "拍哪个",
            "选哪个",
            "下单",
            "规格",
            "颜色",
            "款式",
        ],
        "content": (
            "下单协助类问题可以引导客户在当前商品页选择规格后下单。"
            "如果客户不确定规格/颜色/款式，应让客户说明需求，再按商品页面信息核对。"
            "不能代替客户确认未知商品事实或承诺平台交易结果。"
        ),
        "reply_template": (
            "亲，您可以从当前商品页选择规格后下单。"
            "如果不确定选哪款，把您想要的尺寸、颜色或使用场景发我，我帮您按页面信息核对一下。"
        ),
        "forbidden_claims": ["随便拍", "一定适合", "我替您下单"],
        "required_guardrails": ["按当前商品页规格核对", "不替客户承诺未知规格"],
        "source_confidence": 0.76,
        "risk_level": "medium",
        "priority": 60,
    },
])


for _rule in DEFAULT_GENERIC_SERVICE_RULES:
    if _rule.get("rule_key") == "media_supported_install_size_parts_v1":
        _rule.update({
            "title": "安装尺寸配件素材发送规则",
            "content": (
                "安装、尺寸、空间适配、拆装、配件核对类问题，如果商品卡片已经命中已审核素材，"
                "应直接用客户能理解的话说明并随回复发送对应图片或视频。"
                "不能把“匹配素材、核对后再发、避免发错”这类内部流程话术发给客户。"
            ),
            "reply_template": (
                "亲～{product_display}这个细节可以直接参考我下面发您的图片或视频。"
                "如果是看尺寸，重点对照家里预留位置的宽度、进深和高度；"
                "如果是看安装或配件，按图里标注的位置和步骤核对会更直观。"
            ),
        })


def normalize_rule(raw: dict[str, Any]) -> dict[str, Any]:
    keywords = _string_list(raw.get("query_keywords"))
    forbidden = _string_list(raw.get("forbidden_claims"))
    guardrails = _string_list(raw.get("required_guardrails"))
    normalized = {
        "rule_key": str(raw.get("rule_key") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "intent": str(raw.get("intent") or "general").strip(),
        "fact_type": str(raw.get("fact_type") or "").strip(),
        "scenario": str(raw.get("scenario") or "").strip(),
        "query_keywords": keywords,
        "content": str(raw.get("content") or "").strip(),
        "reply_template": str(raw.get("reply_template") or "").strip(),
        "forbidden_claims": forbidden,
        "allowed_when_product_fact_missing": bool(raw.get("allowed_when_product_fact_missing", True)),
        "required_guardrails": guardrails,
        "priority": int(raw.get("priority") or 100),
        "version": str(raw.get("version") or "v1").strip(),
        "status": str(raw.get("status") or "active").strip(),
        "risk_level": str(raw.get("risk_level") or "low").strip(),
        "auto_reply_allowed": bool(raw.get("auto_reply_allowed", True)),
        "source_confidence": float(raw.get("source_confidence") or 0.75),
        "source": str(raw.get("source") or "seed_generic_service_rules").strip(),
    }
    normalized["content_hash"] = _hash({
        key: normalized[key]
        for key in (
            "rule_key", "title", "intent", "fact_type", "scenario",
            "query_keywords", "content", "reply_template", "forbidden_claims",
            "allowed_when_product_fact_missing", "required_guardrails", "priority", "version",
        )
    })
    return normalized


def validate_rule(rule: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not rule.get("rule_key"):
        errors.append("missing_rule_key")
    if not rule.get("title"):
        errors.append("missing_title")
    if not rule.get("content") and not rule.get("reply_template"):
        errors.append("missing_content")
    customer_text = f"{rule.get('content', '')}\n{rule.get('reply_template', '')}"
    unsafe_terms = unsafe_promise_terms(customer_text)
    if unsafe_terms:
        errors.append("unsafe_promise_terms:" + ",".join(unsafe_terms))
    return errors


def upsert_generic_service_rule(db, RuleModel, raw_rule: dict[str, Any]):
    normalized = normalize_rule(raw_rule)
    errors = validate_rule(normalized)
    if errors:
        return None, "invalid", errors

    row = db.query(RuleModel).filter(RuleModel.rule_key == normalized["rule_key"]).first()
    if not row:
        row = RuleModel()
        db.add(row)
        action = "created"
        row.created_at = datetime.utcnow()
    else:
        action = "unchanged" if row.content_hash == normalized["content_hash"] else "updated"

    row.rule_key = normalized["rule_key"]
    row.title = normalized["title"]
    row.intent = normalized["intent"]
    row.fact_type = normalized["fact_type"]
    row.scenario = normalized["scenario"]
    row.set_query_keywords(normalized["query_keywords"])
    row.content = normalized["content"]
    row.reply_template = normalized["reply_template"]
    row.set_forbidden_claims(normalized["forbidden_claims"])
    row.allowed_when_product_fact_missing = normalized["allowed_when_product_fact_missing"]
    row.set_required_guardrails(normalized["required_guardrails"])
    row.priority = normalized["priority"]
    row.version = normalized["version"]
    row.status = normalized["status"]
    row.risk_level = normalized["risk_level"]
    row.auto_reply_allowed = normalized["auto_reply_allowed"]
    row.source_confidence = normalized["source_confidence"]
    row.source = normalized["source"]
    row.content_hash = normalized["content_hash"]
    row.updated_at = datetime.utcnow()
    return row, action, []


def search_generic_service_rules(
    *,
    db=None,
    RuleModel=None,
    query: str = "",
    intent: str = "",
    fact_type: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    rules = _load_db_rules(db, RuleModel)
    if not rules:
        rules = [normalize_rule(item) for item in DEFAULT_GENERIC_SERVICE_RULES]

    scored = []
    for rule in rules:
        if rule.get("status", "active") != "active" or not rule.get("auto_reply_allowed", True):
            continue
        score = _score_rule(rule, query=query, intent=intent, fact_type=fact_type)
        if score <= 0:
            continue
        item = dict(rule)
        item["score"] = round(score, 4)
        item["source_type"] = "generic_rules"
        item["source_confidence"] = float(rule.get("source_confidence") or 0.75)
        scored.append(item)
    scored.sort(key=lambda item: (-item["score"], int(item.get("priority") or 100)))
    return scored[:limit]


def generic_rule_to_fact(rule: dict[str, Any]) -> dict[str, Any]:
    text = str(rule.get("reply_template") or rule.get("content") or "").strip()
    return {
        "score": rule.get("score", 0),
        "text_score": rule.get("score", 0),
        "vector_score": 0.0,
        "scope_score": 0.0,
        "source_confidence": rule.get("source_confidence", 0.75),
        "rerank_score": rule.get("score", 0),
        "mismatch_reason": "",
        "chunk_id": f"generic_rule:{rule.get('rule_key', '')}",
        "entry_id": f"generic_rule:{rule.get('rule_key', '')}",
        "title": rule.get("title", ""),
        "chunk_text": text,
        "chunk_index": 0,
        "source_type": "generic_rules",
        "intent": rule.get("intent", "general"),
        "category": "generic_service_rule",
        "category_l3": rule.get("scenario", ""),
        "fact_type": rule.get("fact_type", ""),
        "evidence_fact_type": rule.get("fact_type", ""),
        "metadata": {
            "rule_key": rule.get("rule_key", ""),
            "generic_rule": True,
            "forbidden_claims": rule.get("forbidden_claims", []),
            "required_guardrails": rule.get("required_guardrails", []),
            "priority": rule.get("priority", 100),
            "version": rule.get("version", "v1"),
        },
        "entry_status": "active",
        "index_status": "ready",
        "entry_risk_level": rule.get("risk_level", "low"),
        "source_sheet": rule.get("source", ""),
        "row_number": 0,
        "sku_scope": [],
        "product_scope": [],
        "product_context_pack": True,
        "generic_rule": True,
        "evidence_allowed_for_direct_answer": True,
        "evidence_allowed_for_exact_answer": False,
    }


def render_generic_service_reply(rule: dict[str, Any], *, product_name: str = "") -> str:
    template = str(rule.get("reply_template") or rule.get("content") or "").strip()
    if not template:
        return ""
    product_display = f"「{product_name}」" if product_name else "这款商品"
    return template.replace("{product_display}", product_display).strip()


def unsafe_promise_terms(text: str) -> list[str]:
    value = str(text or "")
    found = []
    for term in FORBIDDEN_CUSTOMER_CLAIMS:
        start = 0
        while True:
            idx = value.find(term, start)
            if idx < 0:
                break
            prefix = value[max(0, idx - 10):idx]
            if not re.search(r"(不|不能|不会|无法|不直接|不先|不能直接).{0,8}$", prefix):
                found.append(term)
                break
            start = idx + len(term)
    return found


def _load_db_rules(db, RuleModel) -> list[dict[str, Any]]:
    if db is None or RuleModel is None:
        return []
    try:
        rows = (
            db.query(RuleModel)
            .filter(RuleModel.status == "active")
            .filter(RuleModel.auto_reply_allowed == True)  # noqa: E712
            .all()
        )
    except Exception:
        return []
    return [row.to_dict() for row in rows]


def _score_rule(rule: dict[str, Any], *, query: str, intent: str, fact_type: str) -> float:
    score = 0.0
    rule_fact_type = str(rule.get("fact_type") or "")
    if fact_type and rule_fact_type == fact_type:
        score += 8.0
    elif fact_type and rule_fact_type == "media_reference" and fact_type in {"installation", "dimensions", "space_fit", "accessories"}:
        score += 5.0
    elif fact_type:
        return 0.0

    rule_intent = str(rule.get("intent") or "")
    if intent and (rule_intent == intent or rule_intent in {"product_question", "product_consult"} and intent in {"product_question", "product_consult"}):
        score += 3.0

    keywords = [str(item) for item in rule.get("query_keywords") or []]
    query_text = str(query or "")
    for keyword in keywords:
        if keyword and keyword in query_text:
            score += 1.5
    overlap = _tokens(query_text) & _tokens(" ".join([rule.get("title", ""), rule.get("content", ""), " ".join(keywords)]))
    score += min(3.0, len(overlap) * 0.35)
    return score


def _tokens(text: str) -> set[str]:
    value = str(text or "").lower()
    latin = set(re.findall(r"[a-z0-9]{2,}", value))
    chinese = {value[i:i + 2] for i in range(max(0, len(value) - 1)) if "\u4e00" <= value[i] <= "\u9fff"}
    return {token for token in latin | chinese if token.strip()}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return _string_list(parsed)
        except Exception:
            pass
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [str(value).strip()] if str(value or "").strip() else []


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
