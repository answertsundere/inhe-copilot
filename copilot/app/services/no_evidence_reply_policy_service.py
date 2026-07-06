"""Controlled customer-facing replies when evidence is missing.

This service does not create product facts. It turns the current turn contract,
real conversation context, and media availability into a safe next customer
service action.
"""

from __future__ import annotations

from typing import Any

from app.services.customer_facing_safe_handoff_service import apply_customer_facing_safe_handoff


MEDIA_PROMISE_TERMS = (
    "我把视频发您",
    "我把安装视频发您",
    "我把图片发您",
    "下面发您",
    "已发您",
    "可以发安装视频",
    "发您参考",
    "图片发您",
)

PRODUCT_CONTEXT_REQUEST_TERMS = (
    "请提供商品链接",
    "提供商品链接",
    "发一下商品链接",
    "发一个商品链接",
    "发一下商品截图",
    "提供SKU",
    "提供 SKU",
)

ORDER_CONTEXT_REQUEST_TERMS = (
    "请提供订单号",
    "提供订单号",
    "发一下订单号",
)

INSTALLATION_FACT_TYPES = {"installation", "visual_asset", "media_reference"}
ACCESSORY_FACT_TYPES = {"accessory_usage", "accessories", "packaging"}
ACCESSORY_AVAILABILITY_FACT_TYPES = {"accessory_availability"}
RETURN_PICKUP_FACT_TYPES = {"return_pickup", "aftersales_logistics"}
AFTERSALES_FACT_TYPES = {"aftersales", "aftersales_policy", "after_sales", "media_mismatch", "wrong_item", "missing_part"} | RETURN_PICKUP_FACT_TYPES
PROMOTION_FACT_TYPES = {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy", "price_negotiation"}
DIMENSION_FACT_TYPES = {"dimensions", "space_fit"}
SPACE_FIT_MEDIA_ASSET_TYPES = {
    "dimension_image",
    "dimensions_image",
    "size_chart",
    "size_image",
    "product_size_chart",
    "space_fit_image",
}
SPACE_FIT_MEDIA_HINT_TERMS = (
    "尺寸",
    "尺码",
    "大小",
    "空间",
    "位置",
    "size",
    "dimension",
    "measure",
)
PLACEMENT_SCENE_FACT_TYPES = {"placement_scene"}
STRUCTURE_FUNCTION_FACT_TYPES = {"structure_function"}
LOAD_CAPACITY_FACT_TYPES = {"load_capacity", "stability"}
GROSS_WEIGHT_FACT_TYPES = {"gross_weight"}
MATERIAL_SAFETY_FACT_TYPES = {"material", "material_safety", "certification_report"}
AGE_RANGE_FACT_TYPES = {"age_range", "child_suitability", "child_safety"}
ACCESSORY_MESSAGE_TERMS = (
    "部件",
    "配件",
    "防倒器",
    "双面贴",
    "顶板",
    "底板",
    "背板",
    "侧板",
    "干啥用",
    "什么用",
    "哪个",
    "哪块",
    "位置",
)
ACCESSORY_PACKAGE_ITEM_TERMS = ("螺丝刀", "螺丝", "五金包", "工具包", "安装工具")
ACCESSORY_PACKAGE_INTENT_TERMS = (
    "没有配",
    "没配",
    "有配",
    "配了",
    "带不带",
    "有没有",
    "少了",
    "缺",
    "漏发",
    "少件",
    "缺件",
)
STRUCTURE_MODIFICATION_TERMS = (
    "改装",
    "加装",
    "补配",
    "补一面",
    "第四面",
    "拆掉",
    "拆了",
    "拆下来",
    "只装中间",
    "只保留中间",
    "保留中间",
    "中间部分",
    "不要两边",
    "一边不要",
    "两边不要",
    "单独配",
    "能不能配",
    "能不能用",
    "适不适配",
    "摇晃",
    "稳固",
    "稳定性",
)
STRUCTURE_PART_TERMS = ("侧板", "护栏", "围栏", "挡板", "板件", "中间", "两边", "一边", "结构", "孔位", "配件")
MEDIA_REQUEST_TERMS = (
    "视频",
    "安装视频",
    "说明书",
    "安装资料",
    "教程",
    "图片",
)
MISMATCH_MESSAGE_TERMS = (
    "不对",
    "对不上",
    "不一致",
    "不一样",
    "不太一样",
    "不匹配",
)
MISMATCH_CONTEXT_TERMS = (
    "说明书",
    "视频",
    "资料",
    "物品",
    "实物",
    "东西",
    "买的",
    "发来的",
    "发过来",
    "发给我",
)
DAMAGED_ITEM_TERMS = (
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
    "破损",
    "压坏",
    "磕坏",
)
INSTALLATION_VIDEO_ASSET_TYPES = {"install_video", "installation_video", "video"}
INSTALLATION_DIAGRAM_ASSET_TYPES = {"install_image", "pack_guide_image", "installation_guide", "manual", "manual_image"}
VIDEO_PROMISE_TERMS = ("安装视频", "视频发", "发视频", "把视频", "录制安装视频")
_POLICY_FACT_TYPES = (
    INSTALLATION_FACT_TYPES
    | ACCESSORY_FACT_TYPES
    | AFTERSALES_FACT_TYPES
    | PROMOTION_FACT_TYPES
    | DIMENSION_FACT_TYPES
    | PLACEMENT_SCENE_FACT_TYPES
    | STRUCTURE_FUNCTION_FACT_TYPES
    | LOAD_CAPACITY_FACT_TYPES
    | GROSS_WEIGHT_FACT_TYPES
    | MATERIAL_SAFETY_FACT_TYPES
    | AGE_RANGE_FACT_TYPES
    | ACCESSORY_AVAILABILITY_FACT_TYPES
)


def _reply_installation_diagram_without_video() -> str:
    return (
        "亲，我先按当前这款商品帮您核对安装资料。这款目前暂时没有可直接发送的安装视频，"
        "我先把安装示意图/说明书发您参考。"
        "您可以按图上的板件编号和步骤来装；过程中如果卡在哪一步，"
        "直接拍一下当前安装位置和配件，我帮您对照图纸看。"
    )


def _reply_installation_verify() -> str:
    return (
        "亲，这个需要按您这款商品核对对应安装资料。我先帮您确认对应款式的视频/说明书，"
        "防止资料和款式不对应；如果您卡在某一步，也可以把当前位置拍给我，我一起帮您看。"
    )


def _reply_installation_video_request_with_diagram_review() -> str:
    return (
        "\u4eb2\uff0c\u6211\u5148\u6309\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1\u5e2e\u60a8\u6838\u5bf9\u5b89\u88c5\u8d44\u6599\u3002"
        "\u76ee\u524d\u53ea\u80fd\u770b\u5230\u5b89\u88c5\u56fe/\u8bf4\u660e\u4e66\u7c7b\u8d44\u6599\uff0c\u4e0d\u76f4\u63a5\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891\u3002"
        "\u60a8\u5982\u679c\u5361\u5728\u67d0\u4e00\u6b65\uff0c\u53ef\u4ee5\u628a\u5f53\u524d\u4f4d\u7f6e\u62cd\u7167\u53d1\u6765\uff0c"
        "\u6211\u8fd9\u8fb9\u8f6c\u4eba\u5de5\u5e2e\u60a8\u6309\u8fd9\u6b3e\u7ed3\u6784\u786e\u8ba4\u4e0b\u4e00\u6b65\u3002"
    )


def _reply_installation_handoff_verify() -> str:
    return (
        "\u4eb2\uff0c\u8fd9\u4e2a\u9700\u8981\u6309\u60a8\u8fd9\u6b3e\u5546\u54c1\u6838\u5bf9\u5bf9\u5e94\u5b89\u88c5\u8d44\u6599\u3002"
        "\u6211\u5148\u8f6c\u4eba\u5de5\u786e\u8ba4\u5bf9\u5e94\u6b3e\u5f0f\u7684\u89c6\u9891/\u8bf4\u660e\u4e66\uff0c\u9632\u6b62\u8d44\u6599\u548c\u6b3e\u5f0f\u4e0d\u5bf9\u5e94\uff1b"
        "\u5982\u679c\u60a8\u5361\u5728\u67d0\u4e00\u6b65\uff0c\u4e5f\u53ef\u4ee5\u628a\u5f53\u524d\u4f4d\u7f6e\u62cd\u7ed9\u6211\uff0c\u6211\u4e00\u8d77\u5e2e\u60a8\u770b\u3002"
    )


def _reply_stability_verify() -> str:
    return (
        "亲，正常放书本、玩具这类日常使用可以参考商品资料来判断。"
        "没有具体承重数值前，我不直接报公斤数；建议分散摆放，不要集中压在一处，"
        "安装时按说明固定好、螺丝拧紧，稳定性会更好。具体承重我帮您按资料核一下。"
    )


def _reply_internal_space_verify() -> str:
    return (
        "亲，您是想看里面的收纳格/内部空间对吗？这类内部结构一般在商品详情页会有展示图。"
        "我这边也可以帮您找对应的内部空间图发您参考。您如果是想放玩具、衣服或书本，"
        "也可以告诉我大概尺寸，我帮您判断能不能放下。"
    )


def _reply_space_fit_verify() -> str:
    return (
        "亲，我可以帮您判断能不能放下。需要对照这款商品尺寸和您家预留位置的长、宽、高，"
        "还要留一点余量，方便摆放、开门或抽屉拉出。您把预留空间尺寸发我，"
        "我帮您对照看是否合适。"
    )


def _reply_structure_function_verify() -> str:
    return (
        "亲，这个需要按您这款的结构和配件规格核对，不能直接按其他款式判断。"
        "主要要看孔位、结构件、侧板/护栏/挡板位置，以及说明书里是否标注支持补配、加装、调节或左右互换。"
        "您把商品截图、订单信息、说明书那一页或需要补配/加装的位置发我，我这边转人工确认是否可补、是否适配，避免装错方向。"
    )


def _reply_promotion_verify() -> str:
    return (
        "亲，我帮您看一下当前这款能用的优惠。现在页面价格一般会跟活动、优惠券、满减和下单时间有关，"
        "具体以您下单页面显示为准；我这边先转人工帮您核对当前活动口径，确认有没有还能领取或叠加的券。"
    )


def _reply_placement_bed_rail_verify() -> str:
    return (
        "亲，这个要看您准备放的位置和环境。如果是阳台、卫生间这类可能潮湿或暴晒的位置，"
        "建议先确认这款材质和页面使用说明；您也可以把摆放位置拍一下，"
        "我帮您按资料一起看是否合适。"
    )


def _reply_material_safety_verify() -> str:
    return (
        "亲，材质和安全说明要以这款商品页、材质说明或检测/合格资料为准。"
        "我这边不直接说无毒或有证书；您要确认材质、气味或检测证明的话，"
        "我按当前商品资料核对，有依据再发您参考。"
    )


def _reply_child_suitability_verify() -> str:
    return (
        "亲，儿童适用和安全这类问题要按这款商品页的适用年龄、材质/结构说明，"
        "以及检测或合格资料一起核对。我这边不直接承诺适合某个年龄段，"
        "也不说绝对安全；您如果是给宝宝使用，我按当前商品资料先核对清楚，有依据再发您参考。"
    )


def _reply_damaged_aftersales_with_context() -> str:
    return (
        "\u4eb2\uff0c\u6536\u5230\uff0c\u5148\u522b\u7740\u6025\u3002"
        "\u9ebb\u70e6\u60a8\u62cd\u4e00\u4e0b\u65ad\u88c2/\u7834\u635f\u4f4d\u7f6e\u3001"
        "\u95ee\u9898\u4f4d\u7f6e\u3001\u914d\u4ef6\u6574\u4f53\u548c\u5916\u5305\u88c5\uff0c"
        "\u6211\u8fd9\u8fb9\u6309\u5f53\u524d\u8ba2\u5355\u5148\u8f6c\u4eba\u5de5\u6838\u5b9e\uff0c"
        "\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u5bf9\u5e94\u7684\u5904\u7406\u65b9\u6848\u3002"
    )


def _reply_damaged_aftersales_request_context() -> str:
    return (
        "\u4eb2\uff0c\u6536\u5230\uff0c\u5148\u522b\u7740\u6025\u3002"
        "\u9ebb\u70e6\u60a8\u8865\u5145\u4e00\u4e0b\u8ba2\u5355\u4fe1\u606f\u3001\u5546\u54c1\u4fe1\u606f\uff0c"
        "\u5e76\u62cd\u4e00\u4e0b\u65ad\u88c2/\u7834\u635f\u4f4d\u7f6e\u3001\u95ee\u9898\u4f4d\u7f6e\u548c\u914d\u4ef6\u6574\u4f53\uff0c"
        "\u6211\u8fd9\u8fb9\u8f6c\u4eba\u5de5\u6838\u5b9e\u540e\u518d\u7ed9\u60a8\u5bf9\u5e94\u7684\u552e\u540e\u5904\u7406\u65b9\u6848\u3002"
    )


def _reply_aftersales_mismatch_check() -> str:
    return (
        "\u4eb2\uff0c\u5148\u522b\u7740\u6025\uff0c"
        "\u60a8\u53cd\u9988\u7684\u8d44\u6599\u548c\u5b9e\u7269\u53ef\u80fd\u4e0d\u4e00\u81f4\uff0c"
        "\u6211\u5148\u6309\u5f53\u524d\u8ba2\u5355\u548c\u552e\u540e\u95ee\u9898\u5e2e\u60a8\u6838\u5b9e\u3002"
        "\u9ebb\u70e6\u60a8\u53d1\u4e00\u4e0b\u5bf9\u5e94\u8d44\u6599\u622a\u56fe\u3001"
        "\u95ee\u9898\u4f4d\u7f6e\u548c\u5b9e\u7269\u7167\u7247\uff0c"
        "\u6211\u8fd9\u8fb9\u8f6c\u4eba\u5de5\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u5904\u7406\u65b9\u6848\u3002"
    )


def _reply_return_pickup_check(has_order_context: bool = False) -> str:
    if has_order_context:
        return (
            "亲，我先按当前订单的售后进度帮您核对一下。"
            "上门取件要看平台售后单里的取件方式、预约时间和快递揽收安排。"
            "我这边确认清楚后告诉您下一步处理方案。"
        )
    return (
        "亲，我先帮您核对售后取件安排。"
        "上门取件要看订单售后单里的取件方式、预约时间和快递揽收状态；"
        "您把订单/售后申请页面或取件信息发我，我确认后告诉您下一步处理方案。"
    )


def build_no_evidence_reply_policy(inputs: dict[str, Any]) -> dict[str, Any]:
    policy = _build_no_evidence_reply_policy_raw(inputs)
    policy = _apply_gold_service_reply(policy, inputs)
    return apply_customer_facing_safe_handoff(policy, inputs)


def _apply_gold_service_reply(policy: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    strategy = str(policy.get("reply_strategy") or "")
    if strategy == "send_installation_diagram_without_video":
        policy["reply"] = _reply_installation_diagram_without_video()
    elif strategy == "verify_installation_asset_before_send":
        policy["reply"] = _reply_installation_handoff_verify()
    elif strategy == "verify_structure_function_for_known_product":
        policy["reply"] = _reply_structure_function_verify()
    elif strategy == "verify_current_activity_rule":
        policy["reply"] = _reply_promotion_verify()
    elif strategy == "verify_space_fit_for_known_product":
        policy["reply"] = _reply_space_fit_verify()
    elif strategy == "verify_placement_scene_for_known_product":
        policy["reply"] = _reply_placement_bed_rail_verify()
    elif strategy == "verify_material_safety_for_known_product":
        policy["reply"] = _reply_material_safety_verify()
    elif strategy == "verify_child_suitability_for_known_product":
        policy["reply"] = _reply_child_suitability_verify()
    elif strategy == "verify_dimensions_for_known_product" and _looks_like_internal_space_question(inputs):
        policy["reply"] = _reply_internal_space_verify()
    elif strategy == "verify_stability_or_load_capacity":
        policy["reply"] = _reply_stability_verify()
    elif strategy == "aftersales_damaged_item_check":
        policy["reply"] = _reply_damaged_aftersales_with_context()
    elif strategy == "request_context_for_damaged_aftersales":
        policy["reply"] = _reply_damaged_aftersales_request_context()
    elif strategy == "aftersales_mismatch_check":
        policy["reply"] = _reply_aftersales_mismatch_check()
    elif strategy == "return_pickup_check":
        policy["reply"] = _reply_return_pickup_check(bool(inputs.get("has_order_context")))
    return policy


def _build_no_evidence_reply_policy_raw(inputs: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic safe reply for evidence-missing states."""
    fact_type = str(inputs.get("query_fact_type") or "").strip()
    actionability = str(inputs.get("turn_actionability") or "").strip()
    has_product_context = bool(inputs.get("has_product_context"))
    has_order_context = bool(inputs.get("has_order_context"))
    has_media_context = bool(inputs.get("has_media_context"))
    has_sendable_media_asset = bool(inputs.get("has_sendable_media_asset"))
    sendable_media_asset_types = {str(item or "").strip() for item in (inputs.get("sendable_media_asset_types") or [])}
    missing_reason = str(inputs.get("missing_reason") or "")

    forbidden_claims = list(MEDIA_PROMISE_TERMS)
    if actionability == "context_update":
        return {
            "reply": "亲，收到，我先记录这个情况。后续如果还有具体问题，您把对应位置或情况发我，我再帮您核对。",
            "requires_human_review": False,
            "needs_followup": False,
            "reply_strategy": "acknowledge_context_update",
            "reason": missing_reason or "context_update_without_question",
            "forbidden_claims": forbidden_claims,
        }
    if actionability == "deictic_followup":
        return {
            "reply": "亲，这句需要结合上文、图片或具体位置才能准确判断。您可以把对应位置圈一下，或再发一张图，我帮您确认。",
            "requires_human_review": False,
            "needs_followup": True,
            "reply_strategy": "clarify_context",
            "reason": missing_reason or "context_insufficient",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in GROSS_WEIGHT_FACT_TYPES:
        if has_product_context or has_order_context:
            return {
                "reply": "\u4eb2\uff0c\u8fd9\u6b3e\u7684\u6bdb\u91cd/\u5305\u88c5\u91cd\u91cf\u9700\u8981\u6309\u5bf9\u5e94 SKU \u6838\u5bf9\u51c6\u786e\u8d44\u6599\uff0c\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u3002",
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_gross_weight_for_known_product",
                "reason": missing_reason or "gross_weight_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，需要先确认具体商品或 SKU，我才能核对毛重/包装重量。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_product_context_for_gross_weight",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in LOAD_CAPACITY_FACT_TYPES:
        return {
            "reply": _reply_stability_verify(),
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "verify_stability_or_load_capacity",
            "reason": missing_reason or "stability_or_load_capacity_evidence_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in MATERIAL_SAFETY_FACT_TYPES:
        material_forbidden_claims = forbidden_claims + ["无毒", "食品级", "有证书", "有检测报告", "环保无味"]
        if has_product_context or has_order_context:
            return {
                "reply": _reply_material_safety_verify(),
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_material_safety_for_known_product",
                "reason": missing_reason or "material_safety_evidence_missing",
                "forbidden_claims": material_forbidden_claims,
            }
        return {
            "reply": "亲，材质和安全说明要先对应到具体商品资料。您发一下商品截图、链接或 SKU，我再按这款资料核对材质、气味或检测证明，避免按别的款式说错。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_product_context_for_material_safety",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": material_forbidden_claims,
        }

    if fact_type in AGE_RANGE_FACT_TYPES:
        child_forbidden_claims = forbidden_claims + [
            "适合0-6岁",
            "适合2周岁",
            "保护宝宝安全",
            "放心使用",
            "绝对安全",
            "不会夹手",
            "不会倒",
        ]
        if has_product_context or has_order_context:
            return {
                "reply": _reply_child_suitability_verify(),
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_child_suitability_for_known_product",
                "reason": missing_reason or "child_suitability_evidence_missing",
                "forbidden_claims": child_forbidden_claims,
            }
        return {
            "reply": "亲，儿童适用和安全说明要先对应到具体商品资料。您发一下商品截图、链接或 SKU，我再按这款商品核对适用年龄、材质/结构说明和检测资料。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_product_context_for_child_suitability",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": child_forbidden_claims,
        }

    if fact_type in ACCESSORY_AVAILABILITY_FACT_TYPES:
        if has_product_context or has_order_context:
            return {
                "reply": "亲，我按这款帮您核对这个配件是否能单独补买/售卖，避免和其他款式配件混用。",
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_accessory_availability_for_known_product",
                "reason": missing_reason or "accessory_availability_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，需要先确认具体商品或 SKU，我才能核对对应配件是否能单独购买。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_product_context_for_accessory_availability",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in INSTALLATION_FACT_TYPES and _looks_like_structure_modification_question(inputs):
        return {
            "reply": _reply_structure_function_verify(),
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "verify_structure_function_for_known_product",
            "reason": missing_reason or "structure_function_evidence_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in INSTALLATION_FACT_TYPES and _looks_like_accessory_question(inputs):
        return {
            "reply": "亲，这个部件要按您这款的配件图确认。我这边先转人工核对，您也可以把配件和说明书位置拍一下，我帮您确认具体装在哪个位置；如果确认是少件或配件不匹配，我这边按售后给您核实补发或处理方案。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "verify_accessory_usage_with_photo",
            "reason": missing_reason or "accessory_evidence_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in INSTALLATION_FACT_TYPES:
        if has_sendable_media_asset:
            if sendable_media_asset_types & INSTALLATION_VIDEO_ASSET_TYPES:
                return {
                    "reply": "亲，我把这款对应的安装视频/说明书发您参考，您可以先按步骤看一下；如果卡在某一步，把当前位置拍给我，我继续帮您看。",
                    "requires_human_review": False,
                    "needs_followup": False,
                    "reply_strategy": "send_supported_installation_asset",
                    "reason": "sendable_installation_video_available",
                    "forbidden_claims": [],
                }
            if sendable_media_asset_types & INSTALLATION_DIAGRAM_ASSET_TYPES:
                if _looks_like_installation_video_request(inputs):
                    return {
                        "reply": _reply_installation_video_request_with_diagram_review(),
                        "requires_human_review": True,
                        "needs_followup": True,
                        "reply_strategy": "review_installation_diagram_without_video",
                        "reason": "installation_video_requested_but_only_diagram_available",
                        "forbidden_claims": forbidden_claims,
                    }
                return {
                    "reply": "亲，这款目前暂时没有可直接发送的安装视频，我先把安装示意图/说明书发您参考。您可以按图上的板件编号和步骤来装；过程中如果卡在哪一步，直接拍一下当前安装位置和配件，我帮您对照图纸看。",
                    "requires_human_review": False,
                    "needs_followup": False,
                    "reply_strategy": "send_installation_diagram_without_video",
                    "reason": "sendable_installation_diagram_available_without_video",
                    "forbidden_claims": [],
                }
            return {
                "reply": _reply_installation_verify(),
                "requires_human_review": True,
                "needs_followup": True,
                "reply_strategy": "verify_installation_asset_before_send",
                "reason": missing_reason or "installation_media_role_mismatch",
                "forbidden_claims": forbidden_claims,
            }
        if has_product_context or has_order_context:
            return {
                "reply": "亲，这个需要按您这款商品核对对应安装资料。我先帮您转人工确认对应款式的视频/说明书，防止资料和款式不对应；如果您卡在某一步，也可以把当前位置拍给我，我一起帮您看。",
                "requires_human_review": True,
                "needs_followup": True,
                "reply_strategy": "verify_installation_asset_before_send",
                "reason": missing_reason or "no_sendable_installation_asset",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，麻烦您发一下商品链接、订单截图或款式图，我帮您核对对应安装资料，防止资料和款式不对应。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_minimal_product_context_for_installation",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in ACCESSORY_FACT_TYPES:
        return {
            "reply": "亲，这个部件要按您这款的配件图确认。我这边先转人工核对，您也可以把配件和说明书位置拍一下，我帮您确认具体装在哪个位置；如果确认是少件或配件不匹配，我这边按售后给您核实补发或处理方案。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "verify_accessory_usage_with_photo",
            "reason": missing_reason or "accessory_evidence_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in RETURN_PICKUP_FACT_TYPES:
        return {
            "reply": _reply_return_pickup_check(has_order_context),
            "requires_human_review": True,
            "needs_followup": not has_order_context,
            "reply_strategy": "return_pickup_check",
            "reason": missing_reason or "return_pickup_requires_order_aftersales_check",
            "forbidden_claims": forbidden_claims + ["一定会上门取件", "马上上门取件", "立即退款", "直接补发", "一定赔付"],
        }

    if fact_type in AFTERSALES_FACT_TYPES:
        if _looks_like_damaged_item_question(inputs):
            if has_product_context or has_order_context:
                return {
                    "reply": "亲，收到，先别担心。麻烦您拍一下断裂/破损位置、配件整体和外包装，我这边按订单核实后给您处理补发、换件或售后方案。",
                    "requires_human_review": True,
                    "needs_followup": True,
                    "reply_strategy": "aftersales_damaged_item_check",
                    "reason": missing_reason or "damaged_item_requires_aftersales_check",
                    "forbidden_claims": forbidden_claims,
                }
            return {
                "reply": "亲，收到。麻烦您补充一下订单信息、商品信息，并拍一下断裂/破损位置和配件整体，我这边核实后给您处理补发、换件或售后方案。",
                "requires_human_review": True,
                "needs_followup": True,
                "reply_strategy": "request_context_for_damaged_aftersales",
                "reason": missing_reason or "order_or_product_context_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，您反馈的资料和实物可能不一致，我先按售后核对处理。麻烦您发一下对应资料截图和实物照片，我这边确认后给您补正确资料或处理方案。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "aftersales_mismatch_check",
            "reason": missing_reason or "aftersales_mismatch_requires_evidence",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in STRUCTURE_FUNCTION_FACT_TYPES:
        if has_product_context:
            return {
                "reply": "亲，这个需要按您这款的结构确认，尤其是侧板、护栏、挡板等位置是否支持放下、翻起或调节，不能直接按其他款式判断。您可以拍一下对应位置，我这边帮您核对，或转人工确认后再回复您。",
                "requires_human_review": True,
                "needs_followup": True,
                "reply_strategy": "verify_structure_function_for_known_product",
                "reason": missing_reason or "structure_function_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，这个结构功能需要先确认具体商品、款式或对应位置截图，我才能核对是否支持放下、翻起或调节，避免按其他款式说错。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_context_for_structure_function",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in PROMOTION_FACT_TYPES:
        if has_product_context or has_order_context:
            return {
                "reply": "亲，我先帮您按这款商品核对当前活动/福利。不同活动会按下单时间和页面规则变化，我这边确认后给您说准确口径。",
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_current_activity_rule",
                "reason": missing_reason or "promotion_rule_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，麻烦您发一下商品链接或订单截图，我帮您看这款当前是否有活动或福利。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_product_context_for_activity_rule",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type == "space_fit":
        if has_sendable_media_asset and (sendable_media_asset_types & SPACE_FIT_MEDIA_ASSET_TYPES):
            return {
                "reply": "亲，这款的尺寸/实物图我一起发您参考。您可以先对照图片里的尺寸标注，再结合家里预留位置的宽度、进深和高度判断；如果您把预留尺寸发我，我也可以继续帮您一起看。",
                "requires_human_review": False,
                "needs_followup": False,
                "reply_strategy": "send_supported_space_fit_asset",
                "reason": "sendable_media_asset_available",
                "forbidden_claims": [],
            }
        if has_product_context:
            return {
                "reply": "亲，我已经看到当前商品信息了，但能不能放得下还需要对照这款尺寸和您家预留位置的宽度、进深、高度。我先帮您核对，避免不同款式尺寸说混；您也可以把预留位置尺寸发我，我一起帮您判断。",
                "requires_human_review": True,
                "needs_followup": True,
                "reply_strategy": "verify_space_fit_for_known_product",
                "reason": missing_reason or "space_fit_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，麻烦您发一下商品链接、截图或SKU，再把预留位置的宽度、进深、高度发我，我帮您判断这款能不能放得下。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_context_for_space_fit",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in PLACEMENT_SCENE_FACT_TYPES:
        if has_product_context:
            return {
                "reply": "亲，这个摆放位置需要按这款商品的材质、结构和使用环境核对后再确认。我先帮您核对，避免直接说能晒、能放导致口径不准确。",
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_placement_scene_for_known_product",
                "reason": missing_reason or "placement_scene_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，麻烦您发一下商品链接、截图或 SKU，并说明准备摆放的位置，我帮您核对这款是否适合这个环境。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_context_for_placement_scene",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    if fact_type in DIMENSION_FACT_TYPES:
        if has_product_context:
            return {
                "reply": "亲，我已经看到当前商品信息了，但这款具体尺寸还需要对照尺寸图/商品资料确认。我先帮您核对，避免不同款式尺寸说混。",
                "requires_human_review": True,
                "needs_followup": False,
                "reply_strategy": "verify_dimensions_for_known_product",
                "reason": missing_reason or "dimension_evidence_missing",
                "forbidden_claims": forbidden_claims,
            }
        return {
            "reply": "亲，麻烦您发一下商品链接、截图或SKU，我帮您核对这款的具体尺寸。",
            "requires_human_review": True,
            "needs_followup": True,
            "reply_strategy": "request_product_context_for_dimensions",
            "reason": missing_reason or "product_context_missing",
            "forbidden_claims": forbidden_claims,
        }

    return {
        "reply": "亲，这个细节需要结合对应商品资料核对。我先帮您确认清楚后再回复，避免给您说错。",
        "requires_human_review": True,
        "needs_followup": False,
        "reply_strategy": "generic_fact_verification",
        "reason": missing_reason or "no_evidence_for_fact_type",
        "forbidden_claims": forbidden_claims,
    }


def apply_no_evidence_reply_policy(result: dict[str, Any], copilot_context: dict[str, Any] | None) -> dict[str, Any]:
    """Apply no-evidence policy to a graph result when a controlled reply is needed."""
    response = dict(result or {})
    inputs = build_policy_inputs(response, copilot_context)
    if not should_apply_no_evidence_policy(response, inputs):
        return response

    policy = build_no_evidence_reply_policy(inputs)
    response["suggested_reply"] = policy["reply"]
    if inputs.get("query_fact_type"):
        response["query_fact_type"] = inputs["query_fact_type"]
        response["required_fact_types"] = [inputs["query_fact_type"]]
    response["requires_human_review"] = bool(response.get("requires_human_review")) or bool(policy.get("requires_human_review"))
    response["needs_clarification"] = bool(policy.get("needs_followup"))
    existing_reason = response.get("reason_for_review") or response.get("review_reason") or ""
    response["reason_for_review"] = existing_reason or policy.get("reason", "")
    response["review_reason"] = existing_reason or policy.get("reason", "")
    response["generation_mode"] = "no_evidence_reply_policy"
    response["answer_mode"] = "no_evidence_controlled_reply"

    debug = dict(response.get("evidence_debug") or {})
    debug["answer_mode"] = "no_evidence_controlled_reply"
    if inputs.get("query_fact_type"):
        debug["query_fact_type"] = inputs["query_fact_type"]
        debug["required_fact_types"] = [inputs["query_fact_type"]]
    debug["no_evidence_reply_policy"] = policy
    debug["no_evidence_reply_policy_inputs"] = inputs
    response["evidence_debug"] = debug

    trace = dict(response.get("answer_trace") or {})
    if inputs.get("query_fact_type"):
        trace["query_fact_type"] = inputs["query_fact_type"]
        trace["required_fact_types"] = [inputs["query_fact_type"]]
    trace["no_evidence_reply_policy"] = {
        "reply_strategy": policy.get("reply_strategy"),
        "reason": policy.get("reason"),
        "requires_human_review": policy.get("requires_human_review"),
    }
    response["answer_trace"] = trace
    response.setdefault("trace_steps", []).append({
        "node": "no_evidence_reply_policy",
        "status": "applied",
        "summary": f"{inputs.get('query_fact_type') or '-'}:{policy.get('reply_strategy')}",
    })
    return response


def build_policy_inputs(response: dict[str, Any], copilot_context: dict[str, Any] | None) -> dict[str, Any]:
    context = copilot_context if isinstance(copilot_context, dict) else {}
    understanding = context.get("turn_understanding") if isinstance(context.get("turn_understanding"), dict) else {}
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    answer_trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    semantic_query = debug.get("semantic_query") if isinstance(debug.get("semantic_query"), dict) else {}
    fact_type = str(
        understanding.get("expected_query_fact_type")
        or understanding.get("query_fact_type")
        or response.get("query_fact_type")
        or debug.get("query_fact_type")
        or answer_trace.get("query_fact_type")
        or ""
    ).strip()
    response_summary = response.get("real_context") if isinstance(response.get("real_context"), dict) else {}
    summary = context.get("real_context_summary") if isinstance(context.get("real_context_summary"), dict) else response_summary
    identity = context.get("real_context_product_identity") if isinstance(context.get("real_context_product_identity"), dict) else {}
    media_context = context.get("media_context") if isinstance(context.get("media_context"), dict) else {}
    pack = _product_context_pack(response)
    stats = pack.get("stats") if isinstance(pack.get("stats"), dict) else {}
    has_sendable_media = has_sendable_media_asset(response)
    sendable_media_types = sorted(get_sendable_media_asset_types(response))
    if fact_type in INSTALLATION_FACT_TYPES:
        selected_installation_types = _selected_delivery_media_asset_types(response)
        has_sendable_media = bool(
            selected_installation_types
            & (INSTALLATION_VIDEO_ASSET_TYPES | INSTALLATION_DIAGRAM_ASSET_TYPES)
        )
        sendable_media_types = sorted(selected_installation_types)
    return {
        "query_fact_type": fact_type,
        "turn_actionability": str(understanding.get("turn_actionability") or response.get("turn_actionability") or ""),
        "conversation_type": str(context.get("conversation_type") or summary.get("conversation_type") or ""),
        "source_page": str(context.get("source_page") or summary.get("source_page") or ""),
        "has_product_context": bool(
            summary.get("has_product_context")
            or identity.get("has_resolved_product_context")
            or context.get("product_name")
            or context.get("sku_code")
            or context.get("i_id")
            or context.get("product_candidates")
        ),
        "has_order_context": bool(
            summary.get("has_order_context")
            or context.get("order_id")
            or context.get("order_id_hash")
            or context.get("platform_order_id")
            or context.get("platform_trade_id")
        ),
        "has_media_context": bool(
            summary.get("has_media_context")
            or media_context.get("image_urls")
            or media_context.get("video_urls")
            or stats.get("media_context_count")
        ),
        "has_sendable_media_asset": has_sendable_media,
        "sendable_media_asset_types": sendable_media_types,
        "missing_reason": str(stats.get("conversation_media_rejected_reason") or debug.get("missing_reason") or ""),
        "product_name": str(
            response.get("product_name")
            or response.get("product_title")
            or context.get("product_name")
            or context.get("product_title")
            or ""
        ),
        "real_context_summary": summary,
        "customer_message": str(
            response.get("customer_message")
            or context.get("customer_message")
            or context.get("current_query")
            or debug.get("current_query")
            or semantic_query.get("current_query")
            or answer_trace.get("customer_message")
            or ""
        ),
    }


def should_apply_no_evidence_policy(response: dict[str, Any], inputs: dict[str, Any]) -> bool:
    fact_type = str(inputs.get("query_fact_type") or "")
    actionability = str(inputs.get("turn_actionability") or "")
    reply = str(response.get("suggested_reply") or "")
    selected_count = _selected_evidence_count(response)

    if contains_unsupported_media_promise(reply, bool(inputs.get("has_sendable_media_asset"))):
        return True
    if (
        fact_type in INSTALLATION_FACT_TYPES
        and _promises_installation_video(reply)
        and not (set(inputs.get("sendable_media_asset_types") or []) & INSTALLATION_VIDEO_ASSET_TYPES)
    ):
        return True
    if (
        fact_type in INSTALLATION_FACT_TYPES
        and _looks_like_installation_video_request(inputs)
        and inputs.get("has_sendable_media_asset")
        and not (set(inputs.get("sendable_media_asset_types") or []) & INSTALLATION_VIDEO_ASSET_TYPES)
    ):
        return True
    if _asks_for_known_context(reply, inputs):
        return True
    if _looks_like_generic_handoff(reply) and fact_type in _POLICY_FACT_TYPES:
        return True
    if actionability in {"context_update", "deictic_followup"}:
        return True
    if response.get("generation_mode") == "turn_contract_controlled_handoff":
        return True
    if fact_type in INSTALLATION_FACT_TYPES and (
        _looks_like_structure_modification_question(inputs) or _looks_like_accessory_question(inputs)
    ):
        return True
    if (
        fact_type in INSTALLATION_FACT_TYPES
        and not inputs.get("has_sendable_media_asset")
        and (_looks_like_media_request(inputs) or not selected_count)
    ):
        return True
    if fact_type in ACCESSORY_FACT_TYPES and not selected_count:
        return True
    if fact_type in AFTERSALES_FACT_TYPES and (not selected_count or _looks_like_mismatch_question(inputs)):
        return True
    if fact_type in AFTERSALES_FACT_TYPES and _looks_like_damaged_item_question(inputs):
        return True
    if fact_type in STRUCTURE_FUNCTION_FACT_TYPES and not selected_count:
        return True
    if fact_type in PROMOTION_FACT_TYPES and not selected_count:
        return True
    if fact_type in DIMENSION_FACT_TYPES and not selected_count:
        return True
    if fact_type in PLACEMENT_SCENE_FACT_TYPES and not selected_count:
        return True
    if fact_type in LOAD_CAPACITY_FACT_TYPES and not selected_count:
        return True
    if fact_type in GROSS_WEIGHT_FACT_TYPES and not selected_count:
        return True
    if fact_type in ACCESSORY_AVAILABILITY_FACT_TYPES and not selected_count:
        return True
    return False


def has_sendable_media_asset(response: dict[str, Any]) -> bool:
    if _has_media_blocks(response.get("reply_blocks")):
        return True
    if _has_auto_send_asset(response.get("recommended_assets")):
        return True
    pack = _product_context_pack(response)
    stats = pack.get("stats") if isinstance(pack.get("stats"), dict) else {}
    try:
        if int(stats.get("sendable_media_asset_count") or 0) > 0:
            return True
    except Exception:
        pass
    if _has_auto_send_asset(pack.get("recommended_assets")):
        return True
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    summary = debug.get("product_context_pack_summary") if isinstance(debug.get("product_context_pack_summary"), dict) else {}
    stats = summary.get("stats") if isinstance(summary.get("stats"), dict) else {}
    try:
        return int(stats.get("sendable_media_asset_count") or 0) > 0
    except Exception:
        return False


def get_sendable_media_asset_types(response: dict[str, Any]) -> set[str]:
    asset_types: set[str] = set()
    _collect_sendable_media_asset_types(asset_types, response.get("reply_blocks"), blocks=True)
    _collect_sendable_media_asset_types(asset_types, response.get("recommended_assets"))
    pack = _product_context_pack(response)
    _collect_sendable_media_asset_types(asset_types, pack.get("recommended_assets"))
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    summary = debug.get("product_context_pack_summary") if isinstance(debug.get("product_context_pack_summary"), dict) else {}
    _collect_sendable_media_asset_types(asset_types, summary.get("recommended_assets"))
    return asset_types


def _selected_delivery_media_asset_types(response: dict[str, Any]) -> set[str]:
    """Return media types that are actually attached to the current reply.

    Product context packs may contain usable media somewhere in the catalog, but
    that is not enough to make the current text reply sendable. For installation
    answers we only treat already-built image/video reply blocks as deliverable.
    """
    asset_types: set[str] = set()
    _collect_sendable_media_asset_types(asset_types, response.get("reply_blocks"), blocks=True)
    return asset_types


def contains_unsupported_media_promise(reply: str, has_sendable: bool) -> bool:
    if has_sendable:
        return False
    value = str(reply or "")
    return any(term in value for term in MEDIA_PROMISE_TERMS)


def _promises_installation_video(reply: str) -> bool:
    value = str(reply or "")
    return any(term in value for term in VIDEO_PROMISE_TERMS)


def _selected_evidence_count(response: dict[str, Any]) -> int:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    selected = debug.get("selected_evidence") or debug.get("evidence_selected") or response.get("selected_evidence") or []
    if isinstance(selected, list) and selected:
        return len(selected)
    if selected and not isinstance(selected, list):
        return 1

    count = 0
    for key in ("knowledge_evidence_summary", "filtered_evidence_summary"):
        items = debug.get(key)
        if isinstance(items, list):
            count += sum(1 for item in items if _is_direct_answer_evidence(item))

    summary = debug.get("product_context_pack_summary") if isinstance(debug.get("product_context_pack_summary"), dict) else {}
    for pack_key in ("product_first_evidence_pack", "evidence_pack"):
        pack = summary.get(pack_key) if isinstance(summary.get(pack_key), dict) else {}
        for bucket in ("product_structured_facts", "product_scoped_chunks"):
            rows = pack.get(bucket) if isinstance(pack.get(bucket), list) else []
            count += sum(1 for item in rows if _is_direct_answer_evidence(item))
    return count


def _is_direct_answer_evidence(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("reference_only") is True:
        return False
    if str(item.get("gate_status") or "").lower() in {"blocked", "reference_only"}:
        return False
    for key in ("direct_answer_allowed", "can_direct_answer", "evidence_allowed_for_exact_answer"):
        if item.get(key) is False:
            return False
    return bool(
        item.get("chunk_text")
        or item.get("chunk_preview")
        or item.get("preview")
        or item.get("content")
        or item.get("fact")
        or item.get("evidence_id")
        or item.get("chunk_id")
        or item.get("entry_id")
    )


def _asks_for_known_context(reply: str, inputs: dict[str, Any]) -> bool:
    value = str(reply or "")
    if inputs.get("has_product_context") and any(term in value for term in PRODUCT_CONTEXT_REQUEST_TERMS):
        return True
    if inputs.get("has_order_context") and any(term in value for term in ORDER_CONTEXT_REQUEST_TERMS):
        return True
    return False


def _looks_like_accessory_question(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    if any(term in message for term in ACCESSORY_MESSAGE_TERMS):
        return True
    has_package_item = any(term in message for term in ACCESSORY_PACKAGE_ITEM_TERMS)
    has_package_intent = any(term in message for term in ACCESSORY_PACKAGE_INTENT_TERMS)
    return has_package_item and has_package_intent


def _looks_like_structure_modification_question(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    if not message:
        return False
    has_modification = any(term in message for term in STRUCTURE_MODIFICATION_TERMS)
    has_structure_part = any(term in message for term in STRUCTURE_PART_TERMS)
    return has_modification and has_structure_part


def _looks_like_internal_space_question(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    return any(term in message for term in ("里面", "内部", "空间", "收纳格", "里面空间"))


def _looks_like_media_request(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    return any(term in message for term in MEDIA_REQUEST_TERMS)


def _looks_like_installation_video_request(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    install_context = any(
        term in message
        for term in ("\u5b89\u88c5", "\u7ec4\u88c5", "\u6559\u7a0b", "\u600e\u4e48\u88c5", "\u8bf4\u660e")
    )
    media_request = any(term in message for term in ("\u89c6\u9891", "\u6559\u7a0b"))
    return install_context and media_request


def _looks_like_mismatch_question(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    return (
        any(term in message for term in MISMATCH_MESSAGE_TERMS)
        and any(term in message for term in MISMATCH_CONTEXT_TERMS)
    )


def _looks_like_damaged_item_question(inputs: dict[str, Any]) -> bool:
    message = str(inputs.get("customer_message") or "")
    return any(term in message for term in DAMAGED_ITEM_TERMS)


def _looks_like_generic_handoff(reply: str) -> bool:
    value = str(reply or "")
    if "按这款商品" in value and "核对" in value and "再回复" in value:
        return True
    return "稍等" in value and "确认" in value and "再回复" in value


def _has_media_blocks(blocks: Any) -> bool:
    if not isinstance(blocks, list):
        return False
    return any(isinstance(block, dict) and block.get("type") in {"image", "video"} for block in blocks)


def _has_auto_send_asset(assets: Any) -> bool:
    if not isinstance(assets, list):
        return False
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if not (asset.get("asset_url") or asset.get("url")):
            continue
        auto_level = str(asset.get("auto_send_level") or asset.get("send_mode") or "auto")
        if auto_level in {"auto", "auto_when_platform_connected"}:
            return True
    return False


def _collect_sendable_media_asset_types(asset_types: set[str], assets: Any, *, blocks: bool = False) -> None:
    if not isinstance(assets, list):
        return
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if blocks:
            block_type = str(asset.get("type") or "").strip()
            if block_type in {"image", "video"}:
                asset_types.add(block_type)
            asset_type = str(asset.get("asset_type") or "").strip()
            if asset_type:
                asset_types.add(asset_type)
            continue
        if not (asset.get("asset_url") or asset.get("url")):
            continue
        auto_level = str(asset.get("auto_send_level") or asset.get("send_mode") or "auto")
        if auto_level not in {"auto", "auto_when_platform_connected"}:
            continue
        asset_type = str(asset.get("asset_type") or asset.get("type") or "").strip()
        if asset_type:
            asset_types.add(asset_type)
        if _is_space_fit_media_asset(asset):
            asset_types.add("space_fit_image")


def _is_space_fit_media_asset(asset: dict[str, Any]) -> bool:
    asset_type = str(asset.get("asset_type") or asset.get("type") or "").strip()
    purpose = str(asset.get("media_purpose") or asset.get("purpose") or "").strip()
    title = str(asset.get("asset_title") or asset.get("title") or "").strip()
    if asset_type in SPACE_FIT_MEDIA_ASSET_TYPES or purpose in SPACE_FIT_MEDIA_ASSET_TYPES:
        return True
    if asset_type not in {"sku_image", "product_photo", "image"}:
        return False
    haystack = f"{purpose} {title}".lower()
    return any(term.lower() in haystack for term in SPACE_FIT_MEDIA_HINT_TERMS)


def _product_context_pack(response: dict[str, Any]) -> dict[str, Any]:
    context_used = response.get("context_used") if isinstance(response.get("context_used"), dict) else {}
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    candidates = (
        response.get("product_context_pack"),
        context_used.get("product_context_pack"),
        debug.get("product_context_pack_summary"),
    )
    for pack in candidates:
        if isinstance(pack, dict) and pack:
            return pack
    return {}
