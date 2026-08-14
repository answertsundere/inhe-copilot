"""Build a privacy-safe, high-frequency synthetic dialogue set for P1 review.

The fixture models recurring buyer needs, not real conversations or current
product truth. Every product, order, identity, and fact below is fictional.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "p1-high-frequency-synthetic-dialogues/v1"
DATASET_ID = "p1-high-frequency-synthetic-dialogues"
DATASET_VERSION = "1.0.0"


def _fact(uid: str, content: str, claim_type: str, attribute_key: str = "") -> dict[str, Any]:
    return {
        "evidence_uid": uid,
        "content": content,
        "fact_type": claim_type,
        "claim_types_supported": [claim_type],
        "attribute_key": attribute_key,
    }


def _claim(claim_type: str, attribute_key: str = "", *, risk_level: str = "") -> dict[str, Any]:
    payload = {"claim_type": claim_type}
    if attribute_key:
        payload["attribute_key"] = attribute_key
    if risk_level:
        payload["risk_level"] = risk_level
    return payload


def _scenario(
    uid: str,
    *,
    topic: str,
    scenario_type: str,
    customer_profile: str,
    opening: str,
    context: str,
    follow_up: str,
    summary: str,
    claims: list[dict[str, Any]],
    direct_facts: list[dict[str, Any]] | None = None,
    policy_facts: list[dict[str, Any]] | None = None,
    service_actions: list[dict[str, Any]] | None = None,
    media_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    conversation_turns = [
        {"speaker": "buyer", "text": opening},
        {"speaker": "agent", "text": "我先结合当前商品和您前面说的情况核对。"},
        {"speaker": "buyer", "text": context},
        {"speaker": "agent", "text": "收到，您补充的使用场景我已经记下了。"},
        {"speaker": "buyer", "text": follow_up},
    ]
    suffix = uid.rsplit("-", 1)[-1]
    raw_context: dict[str, Any] = {
        "customer_message": follow_up,
        "conversation_summary": {
            "source": "synthetic_fixture",
            "customer_profile": customer_profile,
            "known_context": summary,
            "prior_turn_count": len(conversation_turns) - 1,
        },
        "product_identity": {
            "product_title": "合成评测商品",
            "sku_code": f"SYN-SKU-{suffix}",
            "i_id": f"SYN-IID-{suffix}",
            "order_id": f"SYN-ORDER-{suffix}",
        },
        "requested_claims": claims,
    }
    if direct_facts:
        raw_context["admitted_direct_facts"] = direct_facts
    if policy_facts:
        raw_context["admitted_policy_facts"] = policy_facts
    if service_actions:
        raw_context["service_actions"] = service_actions
    if media_candidates:
        raw_context["media_candidates"] = media_candidates
    return {
        "scenario_uid": uid,
        "source_class": "synthetic_anonymous",
        "title": f"{topic}/{customer_profile}",
        "scenario_type": scenario_type,
        "demand_topic": topic,
        "customer_profile": customer_profile,
        "conversation_turns": conversation_turns,
        "raw_context": raw_context,
        "review_expectations": {
            "requires_human_review": True,
            "can_send": False,
            "real_customer_accuracy": None,
        },
    }


def build_dataset() -> dict[str, Any]:
    """Return forty fictional, multi-turn scenarios aligned to demand topics."""
    height = _fact("fact-height", "合成评测商品的总高约为 63 厘米。", "dimensions", "height")
    width = _fact("fact-width", "合成评测商品的外侧宽度约为 156 厘米。", "dimensions", "width")
    depth = _fact("fact-depth", "合成评测商品的外侧进深约为 123 厘米。", "dimensions", "depth")
    material = _fact("fact-material", "合成评测商品的主体材质为 PP，包边为硅胶。", "material_composition", "material")
    capacity = _fact("fact-capacity", "合成评测收纳柜的单层可用高度约为 28 厘米。", "storage_capacity", "usable_height")
    included = _fact("fact-included", "合成评测组合包含主体、连接件和说明卡，不包含墙面固定工具。", "configuration_included", "included_items")
    return_policy = _fact("policy-return", "合成评测规则：退货资格需要结合当前订单状态和平台规则核实。", "aftersales_policy", "return_eligibility")
    promotion_policy = _fact("policy-promotion", "合成评测规则：优惠以当前商品结算页实际生效信息为准。", "promotion", "current_offer")
    price_policy = _fact("policy-price", "合成评测规则：价格以当前商品页面和结算页显示为准。", "price", "current_price")
    delivery_policy = _fact("policy-delivery", "合成评测规则：物流进度、送货方式和改约结果需按当前订单记录核实。", "delivery_progress", "current_status")

    scenarios = [
        _scenario("hf-syn-001", topic="installation_video", scenario_type="installation", customer_profile="第一次安装", opening="围栏刚到，我没找到安装视频。", context="说明卡我看过了，卡在连接件方向。", follow_up="这款现在能直接发安装视频吗？", summary="客户已收到合成围栏，卡在连接件方向。", claims=[_claim("installation_media")], media_candidates=[{"evidence_uid": "media-install", "non_fact": True, "media_role": "installation_video"}]),
        _scenario("hf-syn-002", topic="installation_video", scenario_type="installation", customer_profile="图文偏好", opening="我不太会看小字说明。", context="我只想按本款对应的步骤来装。", follow_up="没有视频的话，有没有本款的图文步骤？", summary="客户要求本款安装资料，未确认可发送媒体。", claims=[_claim("installation_media")], media_candidates=[{"evidence_uid": "media-guide", "non_fact": True, "media_role": "installation_guide"}]),
        _scenario("hf-syn-003", topic="installation_video", scenario_type="installation", customer_profile="着急使用", opening="晚上就想给孩子用上。", context="我已经把主体拼到一半了。", follow_up="你别给我通用视频，先确认本款有没有对应安装资料。", summary="客户明确拒绝通用视频，需要型号对应资料。", claims=[_claim("installation_media")], service_actions=[{"evidence_uid": "action-media", "non_fact": True, "text": "核对本款安装资料"}]),
        _scenario("hf-syn-004", topic="installation", scenario_type="installation", customer_profile="步骤确认", opening="连接件要先装还是围栏片先装？", context="我还没有用力卡紧。", follow_up="我怕装反，能按现在这个步骤帮我确认吗？", summary="客户尚未强行安装，需要步骤核对。", claims=[_claim("installation_steps")], service_actions=[{"evidence_uid": "action-install", "non_fact": True, "text": "核对当前安装步骤"}]),
        _scenario("hf-syn-005", topic="installation", scenario_type="installation", customer_profile="配件困惑", opening="袋子里有两个看起来一样的卡扣。", context="说明卡上没有把正反面画得很清楚。", follow_up="这两个卡扣方向是否不同？", summary="客户需要确认配件方向，没有产品专属证据。", claims=[_claim("accessory_usage")]),
        _scenario("hf-syn-006", topic="installation", scenario_type="installation", customer_profile="稳定性担忧", opening="我按说明装好了。", context="放在平地上还有一点晃。", follow_up="能不能先凑合给孩子用，还是要先停用检查？", summary="客户已报告安装后晃动，需要安全边界与核对。", claims=[_claim("stability", risk_level="high")]),
        _scenario("hf-syn-007", topic="dimensions_space_fit", scenario_type="presales", customer_profile="空间核对", opening="我家预留的高度只有 60 厘米。", context="宽度和深度都还有位置。", follow_up="总高 63 厘米的话是不是高度就放不下？", summary="客户已提供 60 厘米净高，只询问高度是否可放入。", claims=[_claim("dimensions", "height")], direct_facts=[height]),
        _scenario("hf-syn-008", topic="dimensions_space_fit", scenario_type="presales", customer_profile="留余量", opening="柜子上方有个 65 厘米的空档。", context="我担心装进去以后不好拿出来。", follow_up="总高 63 厘米的话，这 2 厘米余量够不够？", summary="客户已知净高 65 厘米，询问高度余量，不涉及宽深。", claims=[_claim("dimensions", "height")], direct_facts=[height]),
        _scenario("hf-syn-009", topic="dimensions_space_fit", scenario_type="presales", customer_profile="长宽匹配", opening="我预留的地面大约 160 乘 125 厘米。", context="我不想买回去才发现挡住通道。", follow_up="外侧宽 156、进深 123 的话，按长宽能放下吗？", summary="客户提供平面空间，要求按宽深做确定性比较。", claims=[_claim("dimensions", "width"), _claim("dimensions", "depth")], direct_facts=[width, depth]),
        _scenario("hf-syn-010", topic="promotion", scenario_type="promotion", customer_profile="活动敏感", opening="我刚看到页面好像有券。", context="我担心晚一点活动就变了。", follow_up="现在到底能不能用优惠，别直接给我保证最低价。", summary="客户要求核对当前优惠，价格与活动均为动态信息。", claims=[_claim("promotion", "current_offer")], policy_facts=[promotion_policy]),
        _scenario("hf-syn-011", topic="promotion", scenario_type="promotion", customer_profile="组合比价", opening="我在比较两个组合。", context="我只想知道结算时哪个实际更合适。", follow_up="优惠要按商品页还是按最后结算页看？", summary="客户只要求说明动态优惠核对口径。", claims=[_claim("promotion", "current_offer")], policy_facts=[promotion_policy]),
        _scenario("hf-syn-012", topic="return_refund", scenario_type="aftersales", customer_profile="未拆封退货", opening="包裹刚到，还没有拆。", context="尺寸和我家空间不太合适。", follow_up="这种情况能不能退，要按什么信息核对？", summary="客户说明未拆封和尺寸不适，需要订单级退货资格核对。", claims=[_claim("aftersales_policy", "return_eligibility")], policy_facts=[return_policy]),
        _scenario("hf-syn-013", topic="return_refund", scenario_type="aftersales", customer_profile="犹豫退款", opening="收到后发现颜色和想象不一样。", context="商品没有使用过。", follow_up="不要先承诺退款，先告诉我该怎么核对处理条件。", summary="客户明确要求不做未核实退款承诺。", claims=[_claim("aftersales_policy", "return_eligibility")], policy_facts=[return_policy]),
        _scenario("hf-syn-014", topic="delivery_progress", scenario_type="logistics", customer_profile="等待焦虑", opening="我前天已经下单了。", context="页面状态一直没变化。", follow_up="现在是没发货还是物流慢，需要按哪里查？", summary="客户询问当前订单进度，未提供真实订单。", claims=[_claim("delivery_progress", "current_status")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-015", topic="delivery_progress", scenario_type="logistics", customer_profile="已签收未见", opening="物流页面显示已签收。", context="我家门口和驿站都没找到。", follow_up="这种情况先按订单和轨迹怎么核对？", summary="客户报告签收未收到，需要物流记录核对。", claims=[_claim("delivery_progress", "current_status")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-016", topic="price", scenario_type="promotion", customer_profile="价格比较", opening="我上午和晚上看到的价格不一样。", context="我还没有付款。", follow_up="现在的成交价要以页面还是结算页为准？", summary="客户问动态成交价口径。", claims=[_claim("price", "current_price")], policy_facts=[price_policy]),
        _scenario("hf-syn-017", topic="price", scenario_type="promotion", customer_profile="慎重下单", opening="我不需要额外赠品。", context="只想按当前可见价格做决定。", follow_up="你能先确认价格信息应该从哪里看吗？", summary="客户不要求承诺低价，只需当前价格来源。", claims=[_claim("price", "current_price")], policy_facts=[price_policy]),
        _scenario("hf-syn-018", topic="delivery_method", scenario_type="logistics", customer_profile="送货方式", opening="这个箱子看着可能比较大。", context="我白天不一定在家。", follow_up="会不会送上门，需要按订单哪里的服务信息看？", summary="客户问动态送货方式，不能承诺上门。", claims=[_claim("delivery_method")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-019", topic="delivery_method", scenario_type="logistics", customer_profile="楼层担忧", opening="我住的地方没有电梯。", context="我想提前安排接货。", follow_up="配送方式和是否送到门口要怎么确认？", summary="客户要求确认当前订单配送服务。", claims=[_claim("delivery_method")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-020", topic="purchase_link", scenario_type="presales", customer_profile="型号确认", opening="我已经看中这个组合。", context="担心点错到别的颜色。", follow_up="下单前应该按什么信息确认是同一款？", summary="客户要求确认购买入口与型号，不需要生成链接。", claims=[_claim("purchase_link")], service_actions=[{"evidence_uid": "action-link", "non_fact": True, "text": "核对当前商品链接和型号"}]),
        _scenario("hf-syn-021", topic="missing_parts", scenario_type="aftersales", customer_profile="缺件", opening="我拆箱后发现少了一个连接件。", context="外箱和配件袋都还在。", follow_up="我应该先拍哪些位置，才能避免补错配件？", summary="客户报告缺件，保留外箱与配件袋，需核对零件。", claims=[_claim("missing_parts")], service_actions=[{"evidence_uid": "action-parts", "non_fact": True, "text": "核对配件编号和订单"}]),
        _scenario("hf-syn-022", topic="missing_parts", scenario_type="aftersales", customer_profile="说明书缺失", opening="包裹里没有看到说明卡。", context="其他主要配件暂时都在。", follow_up="缺说明资料要先怎么确认，不要让我重复描述整单。", summary="客户只报告资料缺失，已说明主要配件在。", claims=[_claim("installation_media")], service_actions=[{"evidence_uid": "action-manual", "non_fact": True, "text": "核对本款说明资料"}]),
        _scenario("hf-syn-023", topic="damage_defect", scenario_type="aftersales", customer_profile="到货划痕", opening="外箱看着没破。", context="拆开后发现一块板面有划痕。", follow_up="我需要拍局部还是把外箱标签也一起拍？", summary="客户报告到货划痕，仍保留外箱。", claims=[_claim("damage_defect")], service_actions=[{"evidence_uid": "action-defect", "non_fact": True, "text": "核对问题位置与外箱标签"}]),
        _scenario("hf-syn-024", topic="damage_defect", scenario_type="aftersales", customer_profile="功能异常", opening="装好以后抽屉推拉不顺。", context="我没有继续硬拉。", follow_up="先别给我判断原因，我该补充什么信息让你核对？", summary="客户报告抽屉异常，未强行使用。", claims=[_claim("damage_defect")], service_actions=[{"evidence_uid": "action-function", "non_fact": True, "text": "核对安装位置和异常视频"}]),
        _scenario("hf-syn-025", topic="storage_capacity", scenario_type="presales", customer_profile="收纳规划", opening="我想放一些日常用品。", context="最担心隔层太矮，东西立不起来。", follow_up="单层可用高度是多少？", summary="客户只询问单层可用高度。", claims=[_claim("storage_capacity", "usable_height")], direct_facts=[capacity]),
        _scenario("hf-syn-026", topic="storage_capacity", scenario_type="presales", customer_profile="多层使用", opening="我会把不同物品分层收。", context="不需要你估算总容量。", follow_up="先告诉我每层大概能放多高的东西。", summary="客户明确不要求总容量推算。", claims=[_claim("storage_capacity", "usable_height")], direct_facts=[capacity]),
        _scenario("hf-syn-027", topic="compensation", scenario_type="aftersales", customer_profile="价保咨询", opening="我下单后看到页面有变化。", context="我想先确认是否属于价保范围。", follow_up="差价能不能补要按哪些条件核对？", summary="客户询问价保和补偿条件，不能承诺金额或结果。", claims=[_claim("compensation")], policy_facts=[_fact("policy-comp", "合成评测规则：价保或补偿资格需结合订单时间、活动类型和平台规则核实。", "compensation", "eligibility")]),
        _scenario("hf-syn-028", topic="configuration_included", scenario_type="presales", customer_profile="配置确认", opening="我在看基础组合。", context="墙面固定工具我家已经有。", follow_up="基础组合里具体包含哪些东西，哪些不含？", summary="客户只问基础组合包含和不包含项。", claims=[_claim("configuration_included", "included_items")], direct_facts=[included]),
        _scenario("hf-syn-029", topic="configuration_included", scenario_type="presales", customer_profile="避免漏买", opening="我不想收到后再单独补买。", context="最在意连接件是否随箱。", follow_up="连接件和说明卡是在组合里一起的吗？", summary="客户询问连接件与说明卡是否包含。", claims=[_claim("configuration_included", "included_items")], direct_facts=[included]),
        _scenario("hf-syn-030", topic="delivery_exception", scenario_type="logistics", customer_profile="异常派送", opening="物流有一条异常提示。", context="我还没有联系快递。", follow_up="先按订单和轨迹核对哪一项，不要直接说丢件。", summary="客户看到异常提示，要求客观核对。", claims=[_claim("delivery_exception")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-031", topic="delivery_exception", scenario_type="logistics", customer_profile="改地址担忧", opening="我刚发现收货信息可能填得不方便。", context="还不确定包裹有没有出库。", follow_up="改地址要先看订单在哪个状态？", summary="客户提出改址，需要订单当前状态。", claims=[_claim("delivery_schedule_change")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-032", topic="accessory_purchase", scenario_type="presales", customer_profile="单买配件", opening="我只想多买几个连接件备用。", context="目前还没确认具体规格。", follow_up="单买配件前需要先核对什么兼容信息？", summary="客户有购买配件意图但规格未确认。", claims=[_claim("accessory_compatibility")], service_actions=[{"evidence_uid": "action-accessory", "non_fact": True, "text": "核对配件规格与兼容性"}]),
        _scenario("hf-syn-033", topic="accessory_purchase", scenario_type="presales", customer_profile="扩展需求", opening="以后可能要把围栏加大。", context="我现在只买了基础组合。", follow_up="追加围栏片前是不是要先确认能不能和现有组合兼容？", summary="客户计划扩展组合，需要兼容性核对。", claims=[_claim("accessory_compatibility")], service_actions=[{"evidence_uid": "action-expand", "non_fact": True, "text": "核对现有组合和扩展件兼容性"}]),
        _scenario("hf-syn-034", topic="delivery_schedule_change", scenario_type="logistics", customer_profile="时间调整", opening="我明天白天不在。", context="订单是否已经出库我不清楚。", follow_up="想改送货时间，需要先查哪个状态？", summary="客户希望改约，未确认出库状态。", claims=[_claim("delivery_schedule_change")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-035", topic="delivery_schedule_change", scenario_type="logistics", customer_profile="临时出差", opening="我临时要离开几天。", context="不想让包裹无人签收。", follow_up="能否改约不能先保证，应该怎么查当前可处理的方式？", summary="客户主动要求不承诺改约结果。", claims=[_claim("delivery_schedule_change")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-036", topic="home_delivery", scenario_type="logistics", customer_profile="大件收货", opening="我想提前安排家里有人接收。", context="商品属于合成评测中的大件类别。", follow_up="是否送上门要按当前订单里的哪类信息核对？", summary="客户询问上门配送，不能脱离订单承诺。", claims=[_claim("home_delivery")], policy_facts=[delivery_policy]),
        _scenario("hf-syn-037", topic="material_durability", scenario_type="presales", customer_profile="耐摔常识", opening="孩子平时拿东西会不小心掉地上。", context="我主要想问日常轻微磕碰。", follow_up="PP 加硅胶这类材质，日常不小心摔一下通常怎么样？", summary="客户只问普通轻微跌落，不要求绝对耐摔保证。", claims=[_claim("material_composition", "material")], direct_facts=[material]),
        _scenario("hf-syn-038", topic="oral_exposure", scenario_type="presales", customer_profile="安全敏感", opening="宝宝偶尔会把手边东西往嘴里碰。", context="我会及时制止，也不会让他咬着玩。", follow_up="材质是 PP 和硅胶，能不能直接说适合入口啃咬？", summary="客户询问入口啃咬安全，属于高风险结论。", claims=[_claim("oral_safety", risk_level="high")], direct_facts=[material]),
        _scenario("hf-syn-039", topic="new_product_odor", scenario_type="presales", customer_profile="气味担忧", opening="刚拆封有一点材料味。", context="我还没让孩子接触。", follow_up="这种轻微新味道通常先怎么处理比较稳妥？", summary="客户描述轻微新产品气味，需要日常处理建议而非绝对安全结论。", claims=[_claim("odor")], direct_facts=[material]),
        _scenario("hf-syn-040", topic="structural_safety_gap", scenario_type="presales", customer_profile="承重追问", opening="我看到商品本身不算重。", context="但我没有看到明确承重参数。", follow_up="能不能从自重推断大人站上去没问题？", summary="客户试图由自重推断承重，属于结构安全高风险。", claims=[_claim("load_capacity", "load_capacity", risk_level="high")]),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "source": {
            "classification": "synthetic_anonymous",
            "derived_from": "aggregate_high_frequency_demand_map_only",
            "contains_real_customer_conversations": False,
            "contains_production_product_or_order_identifiers": False,
            "is_runtime_input": False,
        },
        "scenarios": scenarios,
        "generation_constraints": {
            "requires_human_review": True,
            "can_send": False,
            "real_customer_accuracy": None,
            "optimization_unverified": True,
        },
        "topic_counts": dict(sorted(Counter(item["demand_topic"] for item in scenarios).items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_dataset()
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"scenario_count": len(payload["scenarios"]), "topic_counts": payload["topic_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
