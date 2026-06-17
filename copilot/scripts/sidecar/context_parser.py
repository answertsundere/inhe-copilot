from __future__ import annotations

import re
from typing import Any

SYSTEM_TEXT_BLACKLIST = (
    "1天内暂无导入或导出的文件",
    "模块可以手动展开收起",
    "咨询宝贝",
    "发送宝贝",
    "超级会员",
    "非会员",
    "非粉丝",
    "买家信用",
    "店铺消费",
    "平均客单价",
    "优惠券",
    "订单信息",
    "物流信息",
    "菜单",
    "按钮",
    "首页",
    "设置",
    "标签栏",
    "关闭",
    "最小化",
    "最大化",
)

LABEL_TEXT_PATTERNS = [
    r"^[\d.]+$",
    r"^已读$",
    r"^未读$",
    r"^\d+条新消息$",
    r"^在线$",
    r"^离线$",
]

CUSTOMER_PREFIXES = ("客户", "买家", "顾客", "用户", "访客", "buyer", "customer")
AGENT_PREFIXES = ("客服", "卖家", "商家", "客服助手", "机器人", "agent", "seller")


def is_system_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    for blacklisted in SYSTEM_TEXT_BLACKLIST:
        if stripped == blacklisted or stripped.startswith(blacklisted):
            return True

    for pattern in LABEL_TEXT_PATTERNS:
        if re.match(pattern, stripped):
            return True

    return False


def is_customer_message_candidate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if is_system_text(stripped):
        return False
    if len(stripped) < 2:
        return False
    if stripped.startswith("客服:") or stripped.startswith("客服："):
        return False
    for prefix in AGENT_PREFIXES:
        if stripped.lower().startswith(prefix.lower()):
            return False
    return True


def build_extract_status(
    customer_message: str,
    has_uia_sidebar: bool = False,
    has_vision: bool = False,
) -> dict[str, Any]:
    if customer_message:
        return {
            "extract_status": "ok",
            "needs_manual_confirm": False,
            "should_call_copilot_context": True,
        }

    if has_vision:
        return {
            "extract_status": "vision_only_no_customer_message",
            "needs_manual_confirm": True,
            "should_call_copilot_context": False,
        }

    return {
        "extract_status": "no_customer_message",
        "needs_manual_confirm": True,
        "should_call_copilot_context": False,
    }
