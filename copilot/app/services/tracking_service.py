"""
快递物流轨迹查询服务 - LEGACY：调用快递100 API 获取实时物流信息
此服务已从正式业务链路移除。
物流查询已统一走聚水潭（live_jst_repository + query_logistics_trace）。
仅保留用于：extract_tracking_no 单号识别函数（仍被 detect_intent 等节点使用）和测试。
"""

import logging
import os
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------- 配置 ----------
_TRACKING_TIMEOUT = float(os.environ.get("COPILOT_TRACKING_TIMEOUT", "3"))
_TRACKING_RETRY = os.environ.get("COPILOT_TRACKING_RETRY", "false").lower() == "true"

# ---------- 会话级缓存 ----------
_TRACKING_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600


def _get_cached(tracking_no: str) -> dict | None:
    entry = _TRACKING_CACHE.get(tracking_no)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _set_cache(tracking_no: str, data: dict):
    _TRACKING_CACHE[tracking_no] = (time.time(), data)

# 快递公司编码映射
_COURIER_MAP = {
    "shunfeng": "顺丰速运",
    "yuantong": "圆通速递",
    "zhongtong": "中通快递",
    "shentong": "申通快递",
    "yunda": "韵达快递",
    "jtexpress": "极兔快递",
    "jd": "京东快递",
    "ems": "EMS",
    "youzhengguonei": "中国邮政",
    "huitongkuaidi": "百世快递",
    "debangwuliu": "德邦物流",
}

# 状态码映射
_STATE_MAP = {
    "0": "运输中",
    "1": "已揽收",
    "2": "疑难",
    "3": "已签收",
    "4": "已退签",
    "5": "派件中",
    "6": "退回中",
}


def _auto_com(code: str) -> str | None:
    """根据单号自动识别快递公司编码"""
    code = code.upper().strip()
    if code.startswith("SF") and len(code) >= 12:
        return "shunfeng"
    if code.startswith("YT") and len(code) >= 10:
        return "yuantong"
    if code.startswith("JT") and len(code) >= 10:
        return "jtexpress"
    if code.startswith("JD") and len(code) >= 10:
        return "jd"
    if code.startswith("EMS") or code.startswith("EA") or code.startswith("EB"):
        return "ems"
    if code.startswith("ZTO") and len(code) >= 10:
        return "zhongtong"
    if code.isdigit():
        if len(code) == 12:
            return "yunda"
        if len(code) == 13:
            return "youzhengguonei"
        if len(code) == 15:
            return "zhongtong"
    return None


def query_tracking(tracking_no: str, courier: str = "") -> dict:
    """
    查询快递物流轨迹。

    返回:
        {
            "tracking_no", "courier", "courier_name",
            "state", "state_text", "data", "error",
            "elapsed_ms", "cache_hit", "timeout"
        }
    """
    t0 = time.time()

    # 缓存命中
    cached = _get_cached(tracking_no)
    if cached:
        cached["cache_hit"] = True
        return cached

    result = {
        "tracking_no": tracking_no,
        "courier": courier or "",
        "courier_name": "",
        "state": "",
        "state_text": "",
        "data": [],
        "error": "",
        "elapsed_ms": 0,
        "cache_hit": False,
        "timeout": False,
    }

    if not courier:
        courier = _auto_com(tracking_no)
        result["courier"] = courier or ""

    if not courier:
        result["error"] = f"无法识别快递公司: {tracking_no}"
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        _set_cache(tracking_no, result)
        return result

    result["courier_name"] = _COURIER_MAP.get(courier, courier)

    try:
        url = "https://m.kuaidi100.com/query"
        temp = f"{time.time():.6f}"
        resp = requests.get(
            url,
            params={"type": courier, "postid": tracking_no, "temp": temp},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            timeout=_TRACKING_TIMEOUT,
        )
        data = resp.json()

        if data.get("status") != "200" and _TRACKING_RETRY:
            temp = f"{time.time() + 1:.6f}"
            resp = requests.get(
                url,
                params={"type": courier, "postid": tracking_no, "temp": temp},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                timeout=_TRACKING_TIMEOUT,
            )
            data = resp.json()

        if data.get("status") != "200":
            result["error"] = data.get("message", "查询失败")
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
            _set_cache(tracking_no, result)
            return result

        result["state"] = str(data.get("state", ""))
        result["state_text"] = _STATE_MAP.get(result["state"], "未知")
        result["data"] = data.get("data", [])

        if data.get("com") and data["com"] != courier:
            result["courier"] = data["com"]
            result["courier_name"] = _COURIER_MAP.get(data["com"], data["com"])

    except requests.exceptions.Timeout:
        logger.warning("物流查询超时(%s)", tracking_no)
        result["error"] = "查询超时"
        result["timeout"] = True
    except Exception as e:
        logger.error("物流查询失败(%s): %s", tracking_no, e)
        result["error"] = str(e)

    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    _set_cache(tracking_no, result)
    return result


# 快递单号正则（仅匹配明确快递公司前缀）
_TRACKING_PATTERNS = [
    r'(?<![A-Za-z0-9])(SF\d{12,16})(?![A-Za-z0-9])',
    r'(?<![A-Za-z0-9])(JT\d{10,})(?![A-Za-z0-9])',
    r'(?<![A-Za-z0-9])(JD\d{10,})(?![A-Za-z0-9])',
    r'(?<![A-Za-z0-9])(YT\d{10,})(?![A-Za-z0-9])',
    r'(?<![A-Za-z0-9])(ZTO\d{10,})(?![A-Za-z0-9])',
    r'(?<![A-Za-z0-9])(EMS\d{9,})(?![A-Za-z0-9])',
    r'(?<![A-Za-z0-9])([A-Z]{2}\d{9,}[A-Z]{2})(?![A-Za-z0-9])',
]


def extract_tracking_no(text: str) -> str | None:
    """从文本中提取快递单号"""
    for pattern in _TRACKING_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
