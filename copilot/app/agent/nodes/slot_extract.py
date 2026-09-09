"""
slot_extract 节点 - 从客户消息中抽取所有标识符
严格区分：internal_order_id / platform_trade_id / platform_order_id / tracking_no / possible_numeric_id

identifier_type 枚举:
  internal_order_id   — 聚水潭内部 o_id（短数字 + 语义标记 "订单号"）
  platform_trade_id   — 外部交易单号 / outer_so_id（18-19 位纯数字，或带"交易单号/外部单号/天猫/淘宝"等语义）
  platform_order_id   — 店铺订单号 / so_id（带"店铺订单号/平台订单号/so_id"等语义）
  tracking_no         — 快递单号（SF/JT/JD/YT/ZTO/EMS 等前缀）
  unknown_identifier  — 无上下文纯长数字，类型待定
  none                — 无标识符
"""

import re
import time

# 物流单号正则（仅匹配明确快递公司前缀）
_TRACKING_PATTERNS = [
    (r'(?<![A-Za-z0-9])(SF\d{12,16})(?![A-Za-z0-9])', 'shunfeng'),
    (r'(?<![A-Za-z0-9])(JT\d{10,})(?![A-Za-z0-9])', 'jtexpress'),
    (r'(?<![A-Za-z0-9])(JD\d{10,})(?![A-Za-z0-9])', 'jd'),
    (r'(?<![A-Za-z0-9])(YT\d{10,})(?![A-Za-z0-9])', 'yuantong'),
    (r'(?<![A-Za-z0-9])(ZTO\d{10,})(?![A-Za-z0-9])', 'zhongtong'),
    (r'(?<![A-Za-z0-9])(EMS\d{9,})(?![A-Za-z0-9])', 'ems'),
]

# 订单号正则（文本中明确提到"订单"相关语义 → internal_order_id 或 platform_order_id）
_ORDER_SEMANTIC_PATTERNS = [
    r'(?:订单号|订单编号|主订单号|订单ID|订单)[\s:：是为]*([A-Za-z0-9\-]{4,30})',
    r'(?:聚水潭|JST)[\s:：]*([A-Za-z0-9\-]{4,30})',
]

# 平台交易单号正则（"交易单号/外部单号/天猫订单/淘宝订单/拼多多订单"等 → platform_trade_id）
_PLATFORM_TRADE_PATTERNS = [
    r'(?:交易单号|外部交易单号|外部单号|平台交易号|第三方交易号|支付宝交易号)[\s:：]*(\d{10,30})',
    r'(?:天猫订单|淘宝订单|拼多多订单|京东订单|抖音订单|快手订单|小红书订单)[\s:：]*(\d{10,30})',
    r'(?:outer_so_id|outer_so|external_trade)[\s:=：]*(\d{10,30})',
]

# 店铺订单号正则（"店铺订单号/平台订单号/so_id" → platform_order_id）
_PLATFORM_ORDER_PATTERNS = [
    r'(?:店铺订单号|平台订单号|网店订单号)[\s:：]*([A-Za-z0-9\-]{4,30})',
    r'(?:so_id|so_id号)[\s:=：]*([A-Za-z0-9\-]{4,30})',
]

# 纯数字编号（12-20位，可能是订单号也可能是运单号）
_NUMERIC_ID_PATTERN = r'(?<![A-Za-z0-9])(\d{12,20})(?![A-Za-z0-9])'

# 商品名/SKU 关键词
_PRODUCT_KEYWORDS = [
    "书架", "绘本架", "置物架", "收纳架", "鞋架", "花架", "杂志架",
    "书桌", "电脑桌", "学习桌", "办公桌", "餐桌", "茶几",
    "椅子", "餐椅", "办公椅", "凳子", "沙发", "床",
    "柜子", "衣柜", "鞋柜", "书柜", "橱柜", "电视柜",
    "绘本", "儿童", "多层", "三层", "四层", "五层",
    "落地", "壁挂", "简约", "北欧", "日式", "复古",
]

_MODEL_PRODUCT_PATTERN = re.compile(
    r"([一二三四五六七八九十百千万两0-9]+号[\u4e00-\u9fff]{0,12}?(?:围兜|罩衣|防摔枕|枕头|书架|绘本架|收纳架|柜|凳|桌|椅))"
)


def _extract_tracking_no(text: str) -> tuple[str, str]:
    """从文本中提取明确的快递单号（仅匹配 SF/JT/JD/YT/ZTO/EMS 前缀）"""
    if not text:
        return "", ""
    for pattern, carrier in _TRACKING_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper(), carrier
    return "", ""


def _extract_order_id_semantic(text: str) -> tuple[str, str]:
    """从文本中通过语义标记提取订单号。
    Returns (identifier_value, identifier_type) where type is one of
    'internal_order_id', 'platform_order_id', or ''.
    """
    if not text:
        return "", ""
    # Check platform order patterns first (店铺订单号/平台订单号)
    for pattern in _PLATFORM_ORDER_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(), "platform_order_id"
    # Then generic order patterns → internal_order_id
    for pattern in _ORDER_SEMANTIC_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(), "internal_order_id"
    return "", ""


def _extract_platform_trade_id(text: str) -> str:
    """从文本中提取平台交易单号（如天猫/淘宝订单号、交易单号等）"""
    if not text:
        return ""
    for pattern in _PLATFORM_TRADE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _extract_numeric_id(text: str) -> str:
    """从文本中提取纯数字编号（12-20位）"""
    if not text:
        return ""
    match = re.search(_NUMERIC_ID_PATTERN, text)
    if match:
        return match.group(1)
    return ""


def _extract_product_name(text: str) -> str:
    """从文本中提取商品名"""
    if not text:
        return ""
    model_match = _MODEL_PRODUCT_PATTERN.search(text)
    if model_match:
        return model_match.group(1)
    for kw in _PRODUCT_KEYWORDS:
        if kw in text:
            return kw
    return ""


# 当纯数字旁边有这些词时，判定为 platform_trade_id
_TRADE_CONTEXT_KEYWORDS = (
    "交易单号", "外部单号", "交易号", "交易编号",
    "天猫", "淘宝", "拼多多", "京东", "抖音", "快手", "小红书",
    "outer_so_id", "external_trade",
)


def _classify_numeric_with_context(text: str, numeric_id: str) -> str:
    """根据上下文判断纯数字 ID 应归类为哪种 identifier_type。
    Returns 'platform_trade_id', 'internal_order_id', or ''.
    """
    if not numeric_id or not text:
        return ""
    # Check if any trade context keyword appears near the numeric id
    for kw in _TRADE_CONTEXT_KEYWORDS:
        if kw in text:
            return "platform_trade_id"
    # Generic "订单" context near a long number → still likely a trade id if 18+ digits
    if len(numeric_id) >= 18 and any(kw in text for kw in ("订单", "单号", "快递")):
        return "platform_trade_id"
    return ""


def _extract_risk_keywords(text: str) -> list:
    """提取风险关键词"""
    risk_words = ["投诉", "12315", "媒体", "曝光", "律师", "起诉", "告你", "差评", "退货", "退款", "赔偿"]
    found = []
    for w in risk_words:
        if w in text:
            found.append(w)
    return found


def slot_extract(state: dict) -> dict:
    """抽取客户消息中的所有 slot，严格区分标识符类型。

    identifier_type 输出枚举:
      internal_order_id / platform_trade_id / platform_order_id /
      tracking_no / unknown_identifier / none
    """
    t0 = time.time()
    msg = state.get("customer_message", "")
    normalized = state.get("normalized_message", msg)
    api_order_id = state.get("order_id", "")
    api_tracking_no = state.get("tracking_no", "")
    ctx = state.get("copilot_context", {}) or {}
    context_order_id = str(ctx.get("order_id") or "").strip()
    context_order_type = str(ctx.get("order_identifier_type") or "").strip()
    runtime_reference = state.get("_runtime_explicit_order_reference") or {}
    runtime_order_type = str(runtime_reference.get("identifier_type") or "").strip()
    runtime_has_explicit_order = (
        isinstance(runtime_reference, dict)
        and runtime_reference.get("source") == "explicit_request"
        and bool(str(api_order_id or "").strip())
        and runtime_order_type in {
            "internal_order_id",
            "platform_trade_id",
            "platform_order_id",
            "tracking_no",
            "unknown_identifier",
        }
    )
    context_has_explicit_order = (
        ctx.get("order_reference_source") == "explicit_request"
        and bool(context_order_id)
        and context_order_id == str(api_order_id or "").strip()
        and context_order_type in {
            "internal_order_id",
            "platform_trade_id",
            "platform_order_id",
            "tracking_no",
            "unknown_identifier",
        }
    )

    # 1. 提取明确的快递单号
    tracking_no = api_tracking_no
    carrier = ""
    if not tracking_no:
        tracking_no, carrier = _extract_tracking_no(msg)
    if not tracking_no:
        tracking_no, carrier = _extract_tracking_no(normalized)
    if tracking_no and not carrier:
        _, carrier = _extract_tracking_no(tracking_no)

    # 2. 提取平台交易单号（优先于订单号，避免 18-19 位数字被误当订单号）
    platform_trade_id = _extract_platform_trade_id(msg)
    if not platform_trade_id:
        platform_trade_id = _extract_platform_trade_id(normalized)
    # 从 copilot_context 读取平台标识
    if not platform_trade_id:
        platform_trade_id = ctx.get("platform_trade_id", "")

    # 3. 提取订单号（语义标记）
    order_id, order_id_type = _extract_order_id_semantic(msg)
    if not order_id:
        order_id, order_id_type = _extract_order_id_semantic(normalized)
    if api_order_id:
        order_id = api_order_id
        explicit_order_type = (
            runtime_order_type
            if runtime_has_explicit_order
            else context_order_type if context_has_explicit_order else ""
        )
        if explicit_order_type:
            order_id_type = explicit_order_type
            if explicit_order_type == "platform_trade_id":
                platform_trade_id = api_order_id
            else:
                platform_trade_id = ""
        elif api_order_id.isdigit() and len(api_order_id) >= 18:
            platform_trade_id = platform_trade_id or api_order_id
            order_id_type = "platform_trade_id"
        else:
            order_id_type = order_id_type or "internal_order_id"
    # 从 copilot_context 读取平台订单号
    ctx_platform_order_id = ctx.get("platform_order_id", "")
    if ctx_platform_order_id and not order_id and not platform_trade_id:
        order_id = ctx_platform_order_id
        order_id_type = "platform_order_id"

    # 4. 提取纯数字编号（12-20位）
    possible_numeric_id = ""
    if not tracking_no and not order_id and not platform_trade_id:
        numeric = _extract_numeric_id(msg)
        if not numeric:
            numeric = _extract_numeric_id(normalized)
        if numeric:
            # 根据上下文判断纯数字是否为平台交易单号
            ctx_type = _classify_numeric_with_context(msg, numeric)
            if not ctx_type:
                ctx_type = _classify_numeric_with_context(normalized, numeric)
            if ctx_type == "platform_trade_id":
                platform_trade_id = numeric
            else:
                possible_numeric_id = numeric

    # 5. 如果 order_id 看起来像快递单号且没有单独的 tracking_no
    if order_id and not tracking_no:
        t_no, t_carrier = _extract_tracking_no(order_id)
        if t_no:
            tracking_no = t_no
            carrier = t_carrier

    # 6. 去重
    if order_id and tracking_no and order_id.upper() == tracking_no.upper():
        tracking_no = ""
        carrier = ""

    # 7. 提取商品名
    product_name = _extract_product_name(msg) or _extract_product_name(normalized)

    # 8. 提取风险关键词
    risk_keywords = _extract_risk_keywords(msg)

    # 9. 确定 identifier_type
    if tracking_no and not order_id and not platform_trade_id:
        identifier_type = "tracking_no"
    elif platform_trade_id:
        identifier_type = "platform_trade_id"
    elif order_id:
        identifier_type = order_id_type or "internal_order_id"
    elif possible_numeric_id:
        identifier_type = "unknown_identifier"
    else:
        identifier_type = "none"

    # 10. 18-19 位纯数字无上下文时，默认标为 unknown_identifier（不能默认当商品咨询）
    # 已在步骤 4 处理：possible_numeric_id 被设置后 identifier_type = "unknown_identifier"

    slots = {
        "order_id": order_id,
        "platform_trade_id": platform_trade_id,
        "platform_order_id": order_id if order_id_type == "platform_order_id" else "",
        "tracking_no": tracking_no,
        "possible_numeric_id": possible_numeric_id,
        "identifier_type": identifier_type,
        "carrier": carrier,
        "product_name": product_name,
        "sku_name": "",
        "sku_code": "",
        "platform": "",
        "time_hint": "",
        "location_hint": "",
        "risk_keywords": risk_keywords,
        "has_screenshot": False,
    }

    parts = []
    if order_id:
        parts.append(f"订单标识已提供(type={order_id_type})")
    if platform_trade_id:
        parts.append("平台交易标识已提供")
    if tracking_no:
        parts.append("物流标识已提供")
    if possible_numeric_id:
        parts.append("未知数字标识已提供")
    if product_name:
        parts.append(f"商品={product_name}")
    if risk_keywords:
        parts.append(f"风险词={risk_keywords}")

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "slot_extract",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"identifier_type={identifier_type}; " + (", ".join(parts) if parts else "无标识符"),
    }

    result = {
        "slots": slots,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
    # Set top-level identifier fields for downstream nodes
    if order_id:
        result["order_id"] = order_id
    if tracking_no:
        result["tracking_no"] = tracking_no
    if platform_trade_id:
        result["identifier_type"] = identifier_type
    return result
