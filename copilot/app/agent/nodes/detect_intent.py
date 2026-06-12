"""
detect_intent 节点 - 意图识别
"""

import re
import time

from app.services.skill_router import SkillRouter
from app.services.tracking_service import extract_tracking_no

_skill_router = SkillRouter()

# 纯长数字（12-20位），很可能是订单号或运单号
_PURE_NUMERIC_PATTERN = re.compile(r'^[\s]*\d{10,20}[\s]*$')
_NUMERIC_IDENTIFIER_PATTERN = re.compile(r'(?<![A-Za-z0-9])\d{12,20}(?![A-Za-z0-9])')

# 签收未收到关键词
_SIGNED_NOT_RECEIVED = [
    "显示签收", "签收但没收到", "签收但未收到", "签收了但没",
    "签收了但我没", "显示已签收", "已签收但",
    "没收到货", "没有收到", "没拿到", "没见到",
]

# 高风险关键词
_HIGH_RISK_KEYWORDS = [
    "投诉", "差评", "平台介入", "12315", "律师", "曝光", "赔偿",
    "举报", "太差了", "告你", "起诉", "媒体", "工商局", "消协",
    "有毒", "中毒", "甲醛超标", "宝宝受伤", "孩子受伤", "安全隐患",
    "刺鼻",
]

# 售后关键词
_AFTERSALES_KEYWORDS = [
    "退货", "退款", "换货", "不想要", "七天无理由", "运费",
    "退回", "补发", "少件", "发错", "破损", "坏了", "质量问题",
    "瑕疵", " defective", "售后", "退换", "退",
    "缺件", "错发", "漏发", "划痕", "卡住", "松动", "变形", "开裂",
    "异味", "味道很大",
]

# 安装关键词
_INSTALLATION_KEYWORDS = [
    "安装", "怎么装", "装不上", "螺丝", "配件", "说明书",
    "安装视频", "教程", "步骤", "固定", "组装", "拼接", "搭建",
]

# 商品咨询关键词
_PRODUCT_KEYWORDS = [
    "材质", "尺寸", "承重", "适合几岁", "颜色", "规格",
    "配件", "味道", "安全吗", "甲醛", "环保", "实木", "板木",
    "防水", "结实", "耐用", "能放多少", "容量", "重量", "厚度",
    "洗涤", "机洗", "食品级", "无毒",
    "爬爬垫", "围栏", "游戏围栏", "床围栏", "床护栏", "防摔枕",
    "平衡石", "感统玩具", "花生车", "扭扭车", "滑板车", "学习桌",
    "多大", "几个月", "几岁", "能洗吗", "怎么洗", "可水洗",
]

# 物流关键词（基础）
_LOGISTICS_KEYWORDS = [
    "几天到", "什么时候到", "多久到", "物流", "快递",
    "到哪了", "运单", "发货", "没到", "签收", "配送",
    "什么时候发货", "多久发货", "快递单号",
    "待出库", "包裹", "派送", "改地址", "取件码", "合并发",
    "拆单", "尾款", "补尾款", "预约配送",
]

# 物流时效组合检测词
_LOGISTICS_TIME_INDICATORS = [
    "时间", "明天", "后天", "今天", "几天", "什么时候", "多久",
    "一定", "保证", "肯定", "能不能", "来得及", "赶得上", "准时",
]
_LOGISTICS_ACTION_INDICATORS = [
    "到", "到货", "送到", "发货", "物流", "快递", "配送", "运单", "签收",
    "待出库", "包裹", "派送", "取件码",
]

# 物流时效承诺类（一定/保证/肯定 + 到/送达）
_LOGISTICS_COMMITMENT_KEYWORDS = [
    "一定", "保证", "肯定", "绝对", "确保",
]
_LOGISTICS_COMMITMENT_ACTIONS = [
    "到", "送到", "送达", "到货", "能到", "准时", "来得及", "赶得上",
]


def _is_logistics_time_commitment(msg: str) -> bool:
    """检测是否为物流时效承诺类问题（一定/保证今天到吗？）"""
    has_commitment = any(kw in msg for kw in _LOGISTICS_COMMITMENT_KEYWORDS)
    has_action = any(kw in msg for kw in _LOGISTICS_COMMITMENT_ACTIONS)
    # 今天/明天 + 到/送达 也视为承诺类（客户期望具体时间）
    time_specific = any(kw in msg for kw in ["今天", "明天", "后天", "准时"])
    return (has_commitment and has_action) or (time_specific and has_action and ("吗" in msg or "？" in msg or "?" in msg))


def _keyword_match(msg: str, keywords: list) -> bool:
    return any(kw in msg for kw in keywords)


_ADDRESS_OR_INTERCEPT_KEYWORDS = [
    "\u6539\u5730\u5740",
    "\u6536\u8d27\u5730\u5740",
    "\u5730\u5740",
    "\u8f6c\u5bc4",
    "\u62e6\u622a",
    "\u62d2\u6536",
]

_INVOICE_KEYWORDS = [
    "\u53d1\u7968",
    "\u5f00\u7968",
    "\u7535\u5b50\u53d1\u7968",
    "\u589e\u503c\u7a0e",
    "\u62ac\u5934",
    "\u7a0e\u53f7",
]

_PRICE_PROTECTION_KEYWORDS = [
    "\u4ef7\u4fdd",
    "\u4fdd\u4ef7",
    "\u964d\u4ef7",
    "\u5dee\u4ef7",
    "\u8865\u5dee",
    "\u9000\u5dee",
    "\u4e70\u8d35",
]

_PROMOTION_QUERY_KEYWORDS = [
    "\u4f18\u60e0",
    "\u6d3b\u52a8",
    "\u5238",
    "\u6ee1\u51cf",
    "\u6298\u6263",
    "\u4fbf\u5b9c",
    "\u591a\u5c11\u94b1",
]

_GIFT_MISSING_KEYWORDS = [
    "\u8d60\u54c1",
    "\u793c\u54c1",
    "\u8d60\u9001",
    "\u6ca1\u6709",
    "\u6ca1\u6536\u5230",
    "\u6f0f\u53d1",
]

_STOCK_QUERY_KEYWORDS = [
    "\u6709\u8d27",
    "\u5e93\u5b58",
    "\u7f3a\u8d27",
    "\u65ad\u8d27",
    "\u9a6c\u4e0a\u53d1",
    "\u4eca\u5929\u53d1",
    "\u73b0\u8d27",
]

_CHILD_SAFETY_QUERY_KEYWORDS = [
    "\u653e\u5634\u91cc",
    "\u54ac",
    "\u5543",
    "\u541e",
    "\u8bef\u98df",
    "\u5b9d\u5b9d\u653e",
    "\u5b69\u5b50\u653e",
]

_COMPETITOR_COMPARE_KEYWORDS = [
    "\u522b\u5bb6",
    "\u6bd4\u54ea\u4e2a",
    "\u54ea\u4e2a\u66f4\u5b89\u5168",
    "\u5bf9\u6bd4",
]

_ODOR_QUERY_KEYWORDS = [
    "\u5473\u9053",
    "\u5f02\u5473",
    "\u523a\u9f3b",
    "\u95fb\u7740",
]

_CLEANING_CARE_KEYWORDS = [
    "\u6e05\u6d01",
    "\u6e05\u7406",
    "\u810f\u4e86",
    "\u6c34\u6d17",
    "\u6d17\u5417",
    "\u600e\u4e48\u6d17",
    "\u64e6\u6d17",
    "\u53ef\u4ee5\u6d17",
]

_MATERIAL_SAFETY_KEYWORDS = [
    "\u6750\u8d28\u5b89\u5168",
    "\u5b89\u5168\u5417",
    "\u53d7\u6f6e",
    "\u9632\u6f6e",
    "\u751f\u9508",
    "\u98df\u54c1\u7ea7",
    "\u7532\u919b",
    "\u65e0\u7532\u919b",
    "0\u7532\u919b",
    "\u68c0\u6d4b\u62a5\u544a",
    "\u68c0\u67e5\u62a5\u544a",
    "\u8d28\u68c0\u62a5\u544a",
    "\u68c0\u9a8c\u62a5\u544a",
    "\u5408\u683c\u8bc1",
    "\u73af\u4fdd\u8bc1\u4e66",
    "3C",
]

_IMAGE_ATTACHMENT_KEYWORDS = [
    "\u56fe\u7247",
    "\u7167\u7247",
    "\u622a\u56fe",
    "\u62cd\u7ed9\u4f60",
    "\u53d1\u4f60\u4e86",
    "\u53d1\u7ed9\u4f60",
    "\u770b\u56fe",
    "\u5982\u56fe",
]


def _has_image_attachment(state: dict, msg: str) -> bool:
    ctx = state.get("copilot_context", {}) or {}
    attachments = state.get("image_attachments") or ctx.get("image_attachments") or []
    return bool(attachments or ctx.get("has_image_attachment") or _keyword_match(msg, _IMAGE_ATTACHMENT_KEYWORDS))


def _is_logistics_time_query(msg: str) -> bool:
    """组合规则：包含物流动作词 + 时间/承诺词，才判定为物流时效查询"""
    has_action = any(kw in msg for kw in _LOGISTICS_ACTION_INDICATORS)
    has_time = any(kw in msg for kw in _LOGISTICS_TIME_INDICATORS)
    return has_action and has_time


def _has_numeric_logistics_query(msg: str) -> bool:
    """长数字 + 物流/时效问法，应优先按物流查件处理。"""
    if not _NUMERIC_IDENTIFIER_PATTERN.search(msg or ""):
        return False
    logistics_terms = [
        "快递", "物流", "运单", "单号", "发货", "到货", "配送", "签收",
        "什么时候到", "大概什么时候到", "几天到", "多久到", "到哪",
    ]
    return any(term in msg for term in logistics_terms)


def _has_order_identifier_in_state(state: dict) -> bool:
    """Check if state/slots already contain an order identifier from API or prior extraction."""
    from app.agent.state import has_order_identifier
    return has_order_identifier(state)


def detect_intent(state: dict) -> dict:
    """识别客户意图（优先级：high_risk > delivery_not_received > aftersales > installation > logistics > product_question > unknown）"""
    t0 = time.time()
    msg = state.get("normalized_message", state.get("customer_message", ""))

    # 0.5 图片/截图附件：作为证据入口处理，不能仅凭图片直接下事实结论
    if _has_image_attachment(state, msg) and not _keyword_match(msg, _HIGH_RISK_KEYWORDS):
        intent = "image_attachment"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（图片/截图附件）",
        }
        return {
            "intent": intent,
            "skill": "image_attachment",
            "matched_keywords": [k for k in _IMAGE_ATTACHMENT_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 1. 最高优先级：高风险 / 投诉
    if _keyword_match(msg, _HIGH_RISK_KEYWORDS):
        intent = "complaint"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（高风险关键词命中）",
        }
        return {
            "intent": intent,
            "skill": "complaint",
            "matched_keywords": [k for k in _HIGH_RISK_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 2. 签收未收到场景
    signed_not_received = any(kw in msg for kw in _SIGNED_NOT_RECEIVED)
    if signed_not_received:
        intent = "delivery_not_received"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（签收未收到）",
        }
        return {
            "intent": intent,
            "skill": "logistics",
            "matched_keywords": ["签收未收到"],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 3. 售后
    if _keyword_match(msg, _ADDRESS_OR_INTERCEPT_KEYWORDS):
        intent = "logistics_eta"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"address_or_intercept -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "logistics",
            "matched_keywords": [k for k in _ADDRESS_OR_INTERCEPT_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _INVOICE_KEYWORDS):
        intent = "invoice"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"invoice -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "aftersales",
            "matched_keywords": [k for k in _INVOICE_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _PRICE_PROTECTION_KEYWORDS):
        intent = "price_protection"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"price_protection -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "aftersales",
            "matched_keywords": [k for k in _PRICE_PROTECTION_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if (
        any(k in msg for k in ("\u8d60\u54c1", "\u793c\u54c1", "\u8d60\u9001"))
        and any(k in msg for k in ("\u6ca1\u6709", "\u6ca1\u6536\u5230", "\u6f0f\u53d1"))
    ):
        intent = "gift_missing"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"gift_missing -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "aftersales",
            "matched_keywords": [k for k in _GIFT_MISSING_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _STOCK_QUERY_KEYWORDS):
        intent = "stock_query"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"stock_query -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "shipping",
            "matched_keywords": [k for k in _STOCK_QUERY_KEYWORDS if k in msg][:3],
            "is_logistics_time_commitment": "\u9a6c\u4e0a\u53d1" in msg or "\u4eca\u5929\u53d1" in msg,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _PROMOTION_QUERY_KEYWORDS):
        intent = "promotion_query"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"promotion_query -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "price_promotion",
            "matched_keywords": [k for k in _PROMOTION_QUERY_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _CHILD_SAFETY_QUERY_KEYWORDS):
        intent = "child_safety"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"child_safety -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "product",
            "matched_keywords": [k for k in _CHILD_SAFETY_QUERY_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _COMPETITOR_COMPARE_KEYWORDS):
        intent = "competitor_compare"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"competitor_compare -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "product",
            "matched_keywords": [k for k in _COMPETITOR_COMPARE_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _ODOR_QUERY_KEYWORDS):
        intent = "odor_question"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"odor_question -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "product",
            "matched_keywords": [k for k in _ODOR_QUERY_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _CLEANING_CARE_KEYWORDS):
        intent = "cleaning_care"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"cleaning_care -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "product",
            "matched_keywords": [k for k in _CLEANING_CARE_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _MATERIAL_SAFETY_KEYWORDS):
        intent = "material_safety"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"material_safety -> {intent}",
        }
        return {
            "intent": intent,
            "skill": "product",
            "matched_keywords": [k for k in _MATERIAL_SAFETY_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _AFTERSALES_KEYWORDS):
        intent = "aftersales"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（售后关键词命中）",
        }
        return {
            "intent": intent,
            "skill": "aftersales",
            "matched_keywords": [k for k in _AFTERSALES_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 4. 安装
    if _keyword_match(msg, _INSTALLATION_KEYWORDS):
        intent = "installation"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（安装关键词命中）",
        }
        return {
            "intent": intent,
            "skill": "installation",
            "matched_keywords": [k for k in _INSTALLATION_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 5. 物流：数字+物流问法 OR 已有订单标识+物流语义
    has_logistics_kw = _keyword_match(msg, _LOGISTICS_KEYWORDS) or _is_logistics_time_query(msg)
    has_order_id_in_state = _has_order_identifier_in_state(state)

    if _has_numeric_logistics_query(msg):
        intent = "logistics_eta"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（长数字+物流问法）",
        }
        return {
            "intent": intent,
            "skill": "logistics",
            "matched_keywords": ["numeric_identifier", "logistics_query"],
            "is_logistics_time_commitment": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 5b. API-provided order identifier + logistics terms → logistics_eta
    if has_order_id_in_state and has_logistics_kw:
        intent = "logistics_eta"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（已有订单标识+物流语义）",
        }
        return {
            "intent": intent,
            "skill": "logistics",
            "matched_keywords": ["api_order_id", "logistics_query"],
            "is_logistics_time_commitment": False,
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    if _keyword_match(msg, _PRODUCT_KEYWORDS):
        intent = "product_question"
        duration_ms = int((time.time() - t0) * 1000)
        trace = {
            "node": "detect_intent",
            "status": "success",
            "duration_ms": duration_ms,
            "cache_hit": False,
            "summary": f"识别为 {intent}（商品关键词命中）",
        }
        return {
            "intent": intent,
            "skill": "product",
            "matched_keywords": [k for k in _PRODUCT_KEYWORDS if k in msg][:3],
            "trace_steps": state.get("trace_steps", []) + [trace],
        }

    # 6. 物流（组合规则 + 传统关键词）
    route = _skill_router.route(msg)
    intent = route.get("skill", "general")
    has_tracking_no = extract_tracking_no(msg) is not None
    is_pure_numeric_id = bool(_PURE_NUMERIC_PATTERN.match(msg))
    is_time_commitment = _is_logistics_time_commitment(msg)

    if (has_logistics_kw or has_tracking_no) and intent in ("shipping", "logistics", "general", "product_consult"):
        intent = "logistics_eta"
    elif is_pure_numeric_id and intent == "product_consult":
        intent = "logistics_eta"

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "detect_intent",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"识别为 {intent}" + (" [时效承诺]" if is_time_commitment else ""),
    }
    return {
        "intent": intent,
        "skill": route.get("skill", "general"),
        "matched_keywords": route.get("matched_keywords", []),
        "is_logistics_time_commitment": is_time_commitment,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
