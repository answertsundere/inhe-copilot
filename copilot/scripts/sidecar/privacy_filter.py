from __future__ import annotations

import re
from typing import Any

PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
ADDRESS_PATTERN = re.compile(r"(?:省|市|区|县|镇|乡|街道|路|号|栋|楼|室).{2,30}")
NAME_PATTERN = re.compile(r"(?:收件人|收货人|姓名)[:：]\s*\S{2,4}")


def redact_phone(text: str) -> str:
    return PHONE_PATTERN.sub("1**#######", text)


def redact_address(text: str) -> str:
    return ADDRESS_PATTERN.sub("[地址已脱敏]", text)


def redact_name(text: str) -> str:
    return NAME_PATTERN.sub("[姓名已脱敏]", text)


def redact_all(text: str) -> str:
    text = redact_phone(text)
    text = redact_address(text)
    text = redact_name(text)
    return text


def redact_sidebar_text(text: str, max_length: int = 500) -> str:
    redacted = redact_all(text)
    if len(redacted) > max_length:
        redacted = redacted[:max_length] + "..."
    return redacted


def is_safe_for_log(data: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in data.items():
        if isinstance(value, str):
            safe[key] = redact_all(value)
        elif isinstance(value, dict):
            safe[key] = is_safe_for_log(value)
        elif isinstance(value, list):
            safe[key] = [
                redact_all(item) if isinstance(item, str) else item
                for item in value
            ]
        else:
            safe[key] = value
    return safe
