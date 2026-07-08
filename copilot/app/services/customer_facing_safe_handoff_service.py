"""Customer-facing copy for safe handoff replies.

The safety decision stays in upstream policy/final gates. This module only
translates an evidence-missing state into language a customer should see.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


CUSTOMER_FACING_INTERNAL_REDLINE_TERMS = (
    "不直接说",
    "不直接承诺",
    "不能承诺",
    "不敢保证",
    "缺少证据",
    "没有证据",
    "人工审核",
    "需要人工审核",
    "有依据再",
    "当前知识库",
    "知识库",
    "final gate",
    "RAG",
)


MATERIAL_SAFETY_FACT_TYPES = {"material", "material_safety", "certification_report", "odor"}
CHILD_SAFETY_FACT_TYPES = {"age_range", "child_suitability", "child_safety", "pinch_safety"}
LOAD_CAPACITY_FACT_TYPES = {"load_capacity", "stability"}
GROSS_WEIGHT_FACT_TYPES = {"gross_weight", "package_weight"}
DIMENSION_FACT_TYPES = {"dimensions", "space_fit", "placement_scene"}
INSTALLATION_FACT_TYPES = {"installation", "visual_asset", "media_reference"}
ACCESSORY_FACT_TYPES = {"accessory_usage", "accessories", "packaging", "accessory_availability", "structure_function"}
PROMOTION_FACT_TYPES = {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy", "price_negotiation"}
RETURN_PICKUP_FACT_TYPES = {"return_pickup", "aftersales_logistics"}
AFTERSALES_FACT_TYPES = {"aftersales", "aftersales_policy", "after_sales", "media_mismatch", "wrong_item", "missing_part"} | RETURN_PICKUP_FACT_TYPES


def apply_customer_facing_safe_handoff(policy: dict[str, Any], inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rewrite policy["reply"] for human-review cases without changing safety flags."""
    policy = dict(policy or {})
    if not bool(policy.get("requires_human_review")):
        return policy
    if sanitize_text(policy.get("reply_strategy")).startswith("request_"):
        return policy
    fact_type = _fact_type(policy, inputs or {})
    reply = customer_facing_safe_handoff_reply(fact_type, policy=policy, inputs=inputs or {})
    if reply:
        policy["reply"] = reply
        policy["customer_facing_handoff"] = sanitize_obj({
            "applied": True,
            "risk_type": _risk_type(fact_type),
            "customer_action": _customer_action(fact_type),
            "redline_terms": list(CUSTOMER_FACING_INTERNAL_REDLINE_TERMS),
        })
    return policy


def customer_facing_safe_handoff_reply(
    fact_type: str,
    *,
    policy: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
) -> str:
    fact_type = sanitize_text(fact_type)
    product_hint = _product_hint(inputs or {})
    if fact_type in MATERIAL_SAFETY_FACT_TYPES:
        return (
            f"亲，材质、气味和检测说明我帮您按{product_hint}资料核对一下，避免说错。"
            "您稍等，我确认后给您准确回复；如果方便，也可以把您关注的说明页拍给我，我一起看。"
        )
    if fact_type in CHILD_SAFETY_FACT_TYPES:
        return (
            f"亲，宝宝适用和安全说明我帮您按{product_hint}的适用年龄、材质和结构资料核对一下，避免说错。"
            "您稍等，我确认后给您准确回复；如果方便，也可以拍下您关注的位置或说明页，我一起帮您看。"
        )
    if fact_type in LOAD_CAPACITY_FACT_TYPES:
        return (
            f"亲，承重和稳定性我帮您按{product_hint}的承重标注和结构说明核对一下，避免说错。"
            "日常使用建议先分散摆放，不要集中压在一处；具体能放多少、怎么放更稳，我确认后给您准确回复。"
        )
    if fact_type in GROSS_WEIGHT_FACT_TYPES:
        return (
            f"亲，毛重和包装重量我帮您按{product_hint}资料核对一下，避免说错。"
            "您稍等，我确认后给您准确回复。"
        )
    if fact_type in INSTALLATION_FACT_TYPES:
        return (
            f"亲，安装资料我帮您按{product_hint}核对一下。"
            "您如果卡在哪一步，也可以把当前位置拍给我，我一起看；我确认后给您准确回复。"
        )
    if fact_type == "accessory_availability":
        return (
            f"亲，这个配件能不能单独补买或售卖，我帮您按{product_hint}的配件清单和售后规则核对一下。"
            "您可以拍下对应配件或说明书那一页，我一起帮您看；确认后给您准确回复。"
        )
    if fact_type in ACCESSORY_FACT_TYPES:
        return (
            f"亲，这个要按{product_hint}的结构、孔位和配件规格核对一下，避免侧板/护栏/挡板这类位置装错或配错。"
            "您可以拍下对应位置或说明书那一页，我一起帮您看；确认后给您准确回复。"
        )
    if fact_type in RETURN_PICKUP_FACT_TYPES:
        if _has_order_context(inputs or {}):
            return (
                "亲，我先帮您按当前订单售后进度核对一下。"
                "上门取件要看售后单里的取件方式、预约时间和快递揽收安排；"
                "我确认清楚后给您下一步处理方案。"
            )
        return (
            "亲，我先帮您按订单售后进度核对一下。"
            "上门取件要看售后单里的取件方式、预约时间和快递揽收安排；"
            "您把订单/售后申请页面或取件信息发我，我确认后给您下一步处理方案。"
        )
    if fact_type in PROMOTION_FACT_TYPES:
        return (
            f"亲，我帮您看下{product_hint}当前页面活动、优惠券和满减规则哈，具体以您下单页显示为准。"
            "您可以把优惠页面截图发我，我一起帮您核对。"
        )
    if fact_type in AFTERSALES_FACT_TYPES:
        return (
            "亲，收到，先别着急。我按当前订单和您反馈的售后问题帮您核实一下。"
            "麻烦您把问题位置、实物照片、外包装或相关说明页发我，我确认后给您对应处理方案。"
        )
    if fact_type == "placement_scene":
        return (
            f"亲，这个我帮您按{product_hint}的尺寸、结构和准备放的位置环境核对一下，避免不同款式说错。"
            "您也可以把家里预留位置的宽、深、高和现场环境发我，我一起帮您看；确认后给您准确回复。"
        )
    if fact_type in DIMENSION_FACT_TYPES:
        return (
            f"亲，这个我帮您按{product_hint}的尺寸/规格和内部空间资料核对一下，避免不同款式说错。"
            "您也可以把家里预留位置的宽、深、高发我，我一起帮您看；确认后给您准确回复。"
        )
    return (
        f"亲，这个细节我帮您按{product_hint}资料核对一下，避免说错。"
        "您稍等，我确认后给您准确回复。"
    )


def has_customer_facing_internal_redline(text: str) -> bool:
    value = sanitize_text(text)
    return any(term in value for term in CUSTOMER_FACING_INTERNAL_REDLINE_TERMS)


def _fact_type(policy: dict[str, Any], inputs: dict[str, Any]) -> str:
    return sanitize_text(
        _fact_type_from_strategy(sanitize_text(policy.get("reply_strategy")))
        or policy.get("query_fact_type")
        or policy.get("risk_type")
        or inputs.get("query_fact_type")
        or ""
    )


def _fact_type_from_strategy(reply_strategy: str) -> str:
    if "structure_function" in reply_strategy:
        return "structure_function"
    if "accessory_availability" in reply_strategy:
        return "accessory_availability"
    if "accessory_usage" in reply_strategy:
        return "accessory_usage"
    if "load_capacity" in reply_strategy or "stability" in reply_strategy:
        return "load_capacity"
    if "gross_weight" in reply_strategy:
        return "gross_weight"
    if "material_safety" in reply_strategy:
        return "material"
    if "child_suitability" in reply_strategy:
        return "age_range"
    if "current_activity" in reply_strategy:
        return "promotion"
    if "aftersales" in reply_strategy:
        return "aftersales"
    if "placement_scene" in reply_strategy:
        return "placement_scene"
    if "space_fit" in reply_strategy:
        return "space_fit"
    if "dimensions" in reply_strategy:
        return "dimensions"
    return ""


def _product_hint(inputs: dict[str, Any]) -> str:
    product = sanitize_text(
        inputs.get("product_title")
        or inputs.get("product_name")
        or inputs.get("display_product_name")
        or ""
    )
    if _looks_like_redacted_or_identifier(product):
        return "这款商品"
    return f"这款「{product}」" if product else "这款商品"


def _looks_like_redacted_or_identifier(value: str) -> bool:
    text = sanitize_text(value)
    if not text:
        return False
    upper = text.upper()
    if "REDACTED" in upper or "[LONG_ID" in upper or "[SKU" in upper:
        return True
    if len(text) >= 18 and re.fullmatch(r"[A-Za-z0-9_\-:]+", text):
        return True
    return False


def _has_order_context(inputs: dict[str, Any]) -> bool:
    return bool(
        inputs.get("has_order_context")
        or inputs.get("order_id")
        or inputs.get("platform_order_id")
        or inputs.get("order_id_hash")
    )


def _risk_type(fact_type: str) -> str:
    if fact_type in MATERIAL_SAFETY_FACT_TYPES:
        return "material_safety"
    if fact_type in CHILD_SAFETY_FACT_TYPES:
        return "child_safety"
    if fact_type in LOAD_CAPACITY_FACT_TYPES:
        return "load_capacity"
    if fact_type in GROSS_WEIGHT_FACT_TYPES:
        return "gross_weight"
    if fact_type in INSTALLATION_FACT_TYPES:
        return "installation_media"
    if fact_type in PROMOTION_FACT_TYPES:
        return "promotion_policy"
    if fact_type in RETURN_PICKUP_FACT_TYPES:
        return "return_pickup"
    if fact_type in AFTERSALES_FACT_TYPES:
        return "aftersales"
    return fact_type or "unknown"


def _customer_action(fact_type: str) -> str:
    if fact_type in PROMOTION_FACT_TYPES:
        return "核对当前页面活动/优惠券/满减规则"
    if fact_type in RETURN_PICKUP_FACT_TYPES:
        return "核对订单售后取件方式/预约时间/快递揽收安排"
    if fact_type in AFTERSALES_FACT_TYPES:
        return "核对订单和问题照片"
    if fact_type in INSTALLATION_FACT_TYPES:
        return "核对安装资料/说明书/当前位置"
    if fact_type in ACCESSORY_FACT_TYPES:
        return "核对结构和配件规格"
    if fact_type in CHILD_SAFETY_FACT_TYPES:
        return "核对适用年龄/材质/结构资料"
    if fact_type in MATERIAL_SAFETY_FACT_TYPES:
        return "核对商品资料/材质/检测资料"
    return "核对商品资料"
